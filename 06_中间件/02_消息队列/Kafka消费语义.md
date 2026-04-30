# Kafka 消费语义

## 这个问题为什么存在？

分布式系统里，**消息传递的可靠性**不是非黑即白的，而是一个谱系。网络会超时、机器会宕机、进程会 OOM。

"消息只被消费一次"——这句话听起来简单，实现起来却极其困难。因为在分布式系统里，**"消费成功"这个事件**，涉及两个独立的系统（Kafka Broker 和 消费者本地 DB/缓存），它们之间没有分布式事务的保证。

想象这个场景：

```
消费者拉到消息 → 处理业务（写数据库成功） → 提交 Offset（还没提交，宕机了）
重启后 → Offset 还是旧的 → 消息被重新消费 → 数据库写入重复
```

这就是经典的**"处理成功但 Offset 没提交"**问题。

所以要问的不是"能不能做到恰好一次"，而是"你愿意接受哪种不一致"。

## 它是怎么解决问题的？

Kafka 提供了三种消费语义，本质上是 **Offset 提交时机** 和 **业务处理** 之间的时序关系不同。

### At most once（最多一次）

```
拉取消息 → 立即提交 Offset → 处理业务
```

**特点**：Offset 提交在处理之前。如果提交了 Offset 但处理失败，这条消息就永远不会再被消费（丢了）。

**适用场景**：日志收集、埋点上报——偶尔丢几条没关系，重要的是吞吐量大、不重复。

```java
// 实现：自动提交 + 拉到就提交
props.put("enable.auto.commit", true);
props.put("auto.commit.interval.ms", 5000);  // 每5秒自动提交
```

**问题**：`auto.commit.interval.ms` 到了就提交，不管你有没有处理完。如果你的处理时间超过这个间隔，就可能丢消息。

### At least once（最少一次）—— 最常用

```
拉取消息 → 处理业务 → 提交 Offset
```

**特点**：处理完再提交 Offset。如果处理完、但 Offset 提交前崩溃，消息会被重新消费（重复了，但没丢）。

**适用场景**：绝大多数业务场景。重复比丢失好——重复可以通过幂等解决，丢失就真的丢了。

```java
// 实现：关闭自动提交，手动提交
props.put("enable.auto.commit", false);

@KafkaListener(topics = "order")
public void onMessage(ConsumerRecord<String, String> record) {
    processBusiness(record);       // 先处理业务
    // 注意：这里用的是 Acknowledgment，Spring 封装的手动提交
    // 如果是原生 KafkaConsumer，用 commitSync() / commitAsync()
}
// Spring 模式下，在 @KafkaListener 方法执行成功后自动提交
```

**为什么最常用**：业务上"不丢"是底线，重复可以通过幂等解决。而"不丢"的实现成本最低——只要先处理后提交就行。

### Exactly once（恰好一次）—— 理想但复杂

**目标**：消息只被消费一次，不丢不重。

**为什么难**？因为"处理业务"和"提交 Offset"是两个独立的写操作，没法用单个事务包裹。

```
两个系统：Kafka (Offset) 和 业务数据库
它们不能同时提交（跨系统分布式事务，成本高到不现实）
```

Kafka 提供了两种实现 Exactly once 的思路：

#### 思路1：Kafka 0.11+ 的 Exactly Once Semantics (EOS)

Kafka 引入了 **Transactional Producer** 和 **Read Committed** 隔离级别，把"写入结果"和"写入 Offset"放在同一个事务里：

```java
props.put("enable.idempotence", true);
props.put("transactional.id", "my-transactional-id");  // 必须唯一

KafkaProducer producer = new KafkaProducer<>(props);
producer.initTransactions();

try {
    producer.beginTransaction();
    producer.send(new ProducerRecord<>("topic", "key", "value"));
    // 在同一个事务里，也可以发送消费 Offset 的提交（写入 __consumer_offsets）
    producer.sendOffsetsToTransaction(
        Collections.singletonMap(new TopicPartition("topic", 0), new OffsetAndMetadata(100)),
        "consumer-group-id"
    );
    producer.commitTransaction();  // 原子提交：消息 + Offset
} catch (Exception e) {
    producer.abortTransaction();
}
```

**关键**：`sendOffsetsToTransaction()` 把 Offset 的提交也纳入了 Kafka 事务。这样，消费 → 处理 → 写结果 → 提交 Offset 在同一事务里，要么全成功，要么全失败。

**限制**：
- 只能保证 Kafka → Kafka 的 Exactly once（即消费者处理完后，结果也写到 Kafka）
- 如果消费者处理完要写 MySQL，还是没法保证原子性（跨系统了）
- 性能有明显下降（事务开销）

#### 思路2：业务幂等（最实用）

```
At least once 投递 + 业务幂等 = 实际上的 Exactly once
```

```java
// 利用 Redis SET NX 做幂等
public void processOrder(OrderMessage msg) {
    String key = "order:processed:" + msg.getOrderId();
    Boolean first = redis.setNX(key, "1", 86400);  // 24小时过期
    if (!first) {
        log.warn("重复消息，跳过: {}", msg.getOrderId());
        return;  // 幂等保护
    }
    // 处理业务...
}
```

**为什么实用**：不依赖 Kafka 的事务机制，适用于任何存储（MySQL/Redis/MongoDB 都行），性能也比 EOS 好。

### 源码关键路径：Offset 提交流程

```java
// 消费者poll()的核心循环
while (!closed) {
    ConsumerRecords<K, V> records = poll(Duration.ofMillis(pollTimeout));
    
    // 自动提交模式：
    if (enableAutoCommit) {
        maybeAutoCommitOffsets();  // 按 auto.commit.interval.ms 定时提交
    }
    
    // 处理记录...
    processRecords(records);
    
    // 手动提交模式（调用 commitSync / commitAsync）
    // 由用户代码显式调用
}
```

**自动提交的坑**：`maybeAutoCommitOffsets()` 是按照时间间隔提交的，不管你有没有处理完。如果你处理一条消息要 10 秒，而 `auto.commit.interval.ms=5000`，那么每 5 秒就会提交一次 Offset —— 可能提交的是"还没处理完的消息的 Offset"。

**手动提交的正确姿势**：

```java
// 同步提交：可靠，但阻塞
consumer.commitSync();  

// 异步提交：不阻塞，但失败不会重试（因为可能已经有更新的提交）
consumer.commitAsync((offsets, exception) -> {
    if (exception != null) {
        log.error("提交失败", exception);
        // 可以在这里记录失败，后续人工介入
    }
});

// 最佳实践：异步提交 + 同步提交兜底
try {
    consumer.commitSync();  // 关闭时同步提交，确保提交成功
} finally {
    consumer.close();
}
```

## 它和相似方案的本质区别是什么？

### Kafka 的 Exactly Once  vs  二阶段提交（2PC）

| 维度 | Kafka EOS | 2PC (XA 事务) |
|------|-----------|----------------|
| 适用范围 | 仅 Kafka 内部（读 Kafka → 写 Kafka） | 跨任意系统（DB + MQ + ...） |
| 性能 | 中等（Kafka 事务有开销） | 差（协调者单点、阻塞） |
| 复杂度 | 低（Kafka 封装好了） | 高（需要 XA 驱动、协调者） |
| 实际落地 | 少（限制多） | 极少（性能差，基本没人用） |

**本质区别**：Kafka EOS 是"有限场景的 Exactly once"，只解决 Kafka 内部的问题；2PC 是"通用分布式事务"，但代价太高，互联网公司基本不用。

### At least once + 幂等  vs  Exactly once

| 维度 | At least once + 幂等 | Exactly once (Kafka EOS) |
|------|----------------------|--------------------------|
| 实现复杂度 | 低（业务层加个唯一键） | 高（要理解事务、隔离级别） |
| 适用范围 | 任意业务场景 | 仅 Kafka → Kafka |
| 性能 | 高（几乎没有额外开销） | 中（事务开销） |
| 可靠性 | 依赖幂等逻辑正确 | Kafka 保证 |

**为什么选 A 不选 B**：99% 的场景，用"At least once + 幂等"就够了。Kafka EOS 只适合流处理场景（Kafka Streams / Flink），不适合普通业务消费。

## 正确使用方式

### 正确用法

**1. 消费逻辑幂等化（最重要）**

```java
// 方案A：Redis SET NX（适合分布式环境）
String key = "idempotent:" + businessKey;
if (Boolean.FALSE.equals(redis.setNX(key, "1", 86400))) {
    return;  // 重复，跳过
}

// 方案B：数据库唯一索引（最可靠）
// 建表时：CREATE UNIQUE INDEX idx_biz_key ON orders(biz_key);
try {
    insertOrder(order);
} catch (DuplicateKeyException e) {
    log.warn("重复订单，跳过: {}", order.getBizKey());
    return;
}
```

**为什么正确**：这是业务层的最终保障。不管消息队列是 At least once 还是 At most once，幂等都能保证"不重复处理"。

**2. 手动提交 Offset + 批量提交**

```java
@Bean
public KafkaListenerContainerFactory<ConcurrentMessageListenerContainer<String, String>> 
        batchFactory(ConsumerFactory<String, String> consumerFactory) {
    ConcurrentKafkaListenerContainerFactory<String, String> factory =
        new ConcurrentKafkaListenerContainerFactory<>();
    factory.setConsumerFactory(consumerFactory);
    factory.setBatchListener(true);           // 开启批量消费
    factory.getContainerProperties().setAckMode(ContainerProperties.AckMode.MANUAL);  // 手动提交
    return factory;
}

@KafkaListener(topics = "order", containerFactory = "batchFactory")
public void onMessage(List<ConsumerRecord<String, String>> records, Acknowledgment ack) {
    for (ConsumerRecord<String, String> record : records) {
        process(record);
    }
    ack.acknowledge();  // 批量处理完后，一次性提交所有 Offset
}
```

**为什么正确**：批量消费 + 批量提交，减少了提交次数，提高了吞吐。但要注意：如果批量处理到一半崩溃，整个批次都会重新消费——所以批次内的每条消息都要幂等。

**3. 消费者线程池异步处理（提高吞吐）**

```java
@KafkaListener(topics = "order", containerFactory = "batchFactory")
public void onMessage(List<ConsumerRecord<String, String>> records, Acknowledgment ack) {
    List<Future<?>> futures = new ArrayList<>();
    for (ConsumerRecord<String, String> record : records) {
        futures.add(executor.submit(() -> process(record)));
    }
    // 等待所有任务完成
    for (Future<?> future : futures) {
        future.get();  // 阻塞等待
    }
    ack.acknowledge();  // 全部处理完才提交
}
```

**为什么正确**：把慢处理逻辑放到线程池，消费者主线程只负责拉取和提交，避免处理时间过长触发 Rebalance。

### 错误用法及后果

**错误1：自动提交 + 慢处理**

```java
props.put("enable.auto.commit", true);  // 自动提交
// 处理一条要 30 秒...
Thread.sleep(30000);
```

**后果**：`auto.commit.interval.ms` 默认 5 秒，每 5 秒就会提交一次 Offset。30 秒处理期间，Offset 已经被提交了 6 次。如果此时崩溃，这 30 秒的消息全部丢失（Offset 已经提交，但处理没完成）。

**修复**：关闭自动提交，改为手动提交。

**错误2：异步提交 + 不处理失败**

```java
consumer.commitAsync();  // 提交失败不会重试
// 如果这次提交失败了，Offset 没更新，下次会重复消费
```

**后果**：提交失败静默忽略，导致重复消费。

**修复**：异步提交 + 同步提交兜底，或者记录失败日志人工介入。

## 边界情况和坑

### 坑1：Rebalance 导致重复消费

**触发**：消费者被踢出 Group（超时、网络抖动），触发 Rebalance，Partition 被分配给其他消费者。

**问题**：旧消费者可能已经处理了一部分消息，但还没提交 Offset。新消费者接手后，从最后一次提交的 Offset 开始消费 —— 导致重复。

**缓解**：
- 调大 `session.timeout.ms` 和 `max.poll.interval.ms`
- 消费者处理逻辑尽量快
- 业务幂等（最终保障）

### 坑2：Offset 提交顺序问题

**场景**：先提交了 Offset-100，再提交 Offset-50（比如多线程处理，顺序乱了）。

**后果**：Offset-50 之后提交的会被忽略（Kafka 只认最大的 Offset），Offset 50~99 的消息永远不会被消费（丢了）。

**修复**：单线程按顺序提交，或者用 `commitSync` 阻塞等待，确保提交顺序。

### 坑3：消费者实例数 > Partition 数

```
3 个 Partition，5 个消费者 → 2 个消费者永远拿不到 Partition，空转
```

**后果**：资源浪费，且容易误导监控（以为并行度是 5，实际只有 3）。

**修复**：确保消费者数 ≤ Partition 数。要增加并行度，先增加 Partition 数。

## 面试话术

**Q：Kafka 怎么保证 Exactly once？**
"Kafka 0.11 之后提供了 EOS（Exactly Once Semantics），通过 Transactional Producer 把消息发送和 Offset 提交放在同一个事务里，原子提交。但这个只适用于 Kafka → Kafka 的场景。对于业务消费（Kafka → MySQL），更实用的方案是 At least once + 幂等，用唯一键去重。"

**Q：At least once 和 At most once 怎么选？**
"At most once 是'可能丢但不重复'，At least once 是'可能重复但不丢'。业务上'不丢'是底线，所以 99% 的场景选 At least once，配合幂等解决重复问题。At most once 只适合日志收集这种丢几条没关系的场景。"

**Q：自动提交有什么问题？**
"自动提交是按时间间隔提交的，不管你有没有处理完。如果处理时间超过了提交间隔，Offset 会被提前提交，导致消息丢失。所以生产环境建议关闭自动提交，改用手动提交。"

**Q：怎么解决重复消费？**
"三层：1) 生产端开启幂等（enable.idempotence=true），避免网络重试导致重复发送；2) 消费端用 At least once + 手动提交；3) 业务层做幂等，比如唯一业务键 + Redis SET NX，或者数据库唯一索引。第三层是最终保障。"

## 本文总结

Kafka 消费语义的本质是 **Offset 提交时机** 与 **业务处理** 的时序关系：

- At most once：先提交，再处理 → 可能丢，不重复
- At least once：先处理，再提交 → 可能重复，不丢（**最常用**）
- Exactly once：事务保证原子性 → 不丢不重，但限制多、性能差

Kafka 0.11+ 的 EOS 通过 Transactional Producer 实现 Kafka → Kafka 的 Exactly once，但不适合 Kafka → 外部 DB 的场景。

**最实用的方案**：At least once + 业务幂等。幂等实现：Redis SET NX / 数据库唯一索引 / 状态机校验。

自动提交在生产环境不要用，手动提交才能保证"先处理后提交"。批量消费可以提高吞吐，但要注意批次内每条消息都要幂等。
