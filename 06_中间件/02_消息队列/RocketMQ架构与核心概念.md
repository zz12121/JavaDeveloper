# RocketMQ 架构与核心概念

## 这个问题为什么存在？

Kafka 和 RabbitMQ 各有短板：

- **Kafka** 吞吐极强，但**延迟消息**、**事务消息**支持得不好（延迟消息要靠外部流处理，事务消息配置复杂）
- **RabbitMQ** 路由灵活，但**吞吐量**不够（万级 TPS），**分布式事务**也不支持

阿里巴巴在内部遇到了这个问题：电商场景里，"订单创建后 30 分钟未支付自动取消"需要**延迟消息**，"扣库存和下单要么同时成功要么同时失败"需要**事务消息**。Kafka 和 RabbitMQ 都搞不定，所以他们自研了 RocketMQ。

所以 RocketMQ 要解决的问题是：**在高吞吐的前提下，支持电商/金融场景的高级消息特性（延迟消息、事务消息、顺序消息）**。

## 它是怎么解决问题的？

### 整体架构

```
                    ┌────────────────────────────────────────────┐
                    │           RocketMQ 集群                     │
                    │                                            │
Producer ───────→  │  ┌──────────┐    ┌──────────┐           │
  (生产者)          │  │ NameServer│    │ NameServer│ ...      │
  (业务系统)        │  │(注册中心) │    │(注册中心) │           │
                    │  └────┬─────┘    └────┬─────┘           │
                    │       └────────┬─────────┘                 │
                    │                ↓                            │
                    │  ┌──────────────────────────┐             │
                    │  │      Broker Cluster       │             │
                    │  │  Master-1 (主)          │             │
                    │  │    └── Slave-1 (从)     │             │
                    │  │  Master-2 (主)          │             │
                    │  │    └── Slave-2 (从)     │             │
                    │  └──────────────────────────┘             │
                    └────────────────────────────────────────────┘
                            ↓ Pull（消费者主动拉取）
                        Consumer Group
```

核心角色：

| 角色 | 作用 | 类比 |
|------|------|------|
| NameServer | 服务注册与发现（轻量级，类似 Nacos） | 注册中心 |
| Broker | 存储消息、处理读写请求 | Kafka 的 Broker |
| Producer | 生产者，发消息 | 一样 |
| Consumer | 消费者，消费消息 | 一样 |

**NameServer vs ZooKeeper（Kafka 用 ZK）**：

RocketMQ 去掉了 ZK，用 **NameServer**（无状态，节点之间不通信）。Producer/Broker/Consumer 直接连 NameServer 获取路由信息。

**好处**：架构更简单，没有 ZK 的运维负担。
**代价**：路由信息更新有延迟（靠心跳 + 定时拉取，不是实时推送）。

### 核心概念

#### 1. Topic 和 Tag（二级分类）

RocketMQ 在 Topic 之下加了 **Tag**，做**二级消息分类**，避免创建太多 Topic。

```
Topic: order_event
  Tag: CREATE    (订单创建)
  Tag: PAY       (订单支付)
  Tag: CANCEL    (订单取消)
```

```java
// 生产者：发消息时指定 Topic + Tag
Message msg = new Message(
    "order_event",   // Topic
    "PAY",           // Tag
    key,             // 业务 Key（用于去重 / 排查问题）
    body             // 消息体
);
producer.send(msg);
```

```java
// 消费者：按 Tag 过滤（Broker 端过滤，减少网络传输）
consumer.subscribe("order_event", "CREATE || PAY");  // 只消费 CREATE 和 PAY
```

**为什么要有 Tag？** Kafka 只有一个 Topic 维度，如果要做"订单创建"和"订单支付"的差异化消费，只能建两个 Topic。RocketMQ 用 Tag 在一个 Topic 内做二级分类，管理更方便。

#### 2. 消费模型：集群消费 vs 广播消费

```
集群消费（默认，类似 Kafka 的 Consumer Group）：
  Consumer Group-A:
    Consumer-1 → 分到 Topic-A 的一部分队列
    Consumer-2 → 分到 Topic-A 的另一部分队列
  → 同一条消息只会被 Group 内的一个消费者消费

广播消费：
  Consumer Group-B:
    Consumer-1 → 收到 Topic-A 的所有消息
    Consumer-2 → 收到 Topic-A 的所有消息
  → 同一条消息会被 Group 内的所有消费者消费（类似 Pub/Sub）
```

```java
// 设置为广播模式
consumer.setMessageModel(MessageModel.BROADCASTING);
```

#### 3. 消息存储模型（关键设计）

RocketMQ 的消息存储是**顺序写 CommitLog + 索引文件**。

```
Broker 磁盘布局：
  ├── CommitLog/ (所有 Topic 的消息都写同一个文件，顺序写！)
  │   └── 00000000000000000000
  │   └── 00000000001073741824
  ├── ConsumeQueue/ (逻辑队列，相当于 Kafka 的 Partition)
  │   └── TopicA/
  │       └── 0/ (Queue-0 的索引)
  │       └── 1/ (Queue-1 的索引)
  └── Index/ (按 Key 查询的哈希索引)
```

**关键设计：CommitLog 是混合型存储**

Kafka 每个 Partition 有独立的日志文件；RocketMQ **所有 Topic 的消息都写同一个 CommitLog**（混合存储）。

```
Kafka:  Partition-0 → 独立文件  → 随机 I/O（多个 Partition 刷盘时）
RocketMQ: 所有消息 → 同一个 CommitLog → 顺序 I/O（始终追加写）
```

**好处**：写入性能极高（始终顺序写），不管有多少个 Topic。
**代价**：消费时要**随机读 ConsumeQueue**（索引）→ 性能比 Kafka 差一点，但用 PageCache 缓存可以弥补。

#### 4. 队列数（ConsumeQueue）

每个 Topic 可以设置**队列数**（类似 Kafka 的 Partition 数）：

```java
// 创建 Topic 时设置队列数
admin.createTopic("order_event", 8, 2);
// 8 个队列（ConsumeQueue），2 个副本（Master + Slave）
```

**消费并行度 = 队列数**（和 Kafka 一样，Consumer 数 ≤ 队列数）。

### 源码关键路径：消息发送流程

```java
// RocketMQ Producer 发送流程（简化）
DefaultMQProducer producer = new DefaultMQProducer("group");

// 1. 从 NameServer 获取 Topic 的路由信息（哪些 Broker，哪些队列）
TopicPublishInfo info = this.mQClientFactory
    .getMQClientAPIImpl()
    .getTopicRouteInfoFromNameServer(topic);

// 2. 轮询或根据负载均衡策略选择队列
MessageQueue mq = selectOneMessageQueue(lastBrokerName);

// 3. 发送消息（同步 / 异步 / 单向）
SendResult sendResult = this.sendKernelImpl(
    mq, msg, communicationMode, sendCallback);
```

**关键设计：队列选择时的 Broker 故障延迟机制**

如果某个 Broker 上次发送失败了，RocketMQ 会**暂时跳过这个 Broker**（延迟一段时间再试），提高可用性。这比 Kafka Producer 的 `retries` 更智能。

## 它和相似方案的本质区别是什么？

### RocketMQ vs Kafka

| 维度 | Kafka | RocketMQ |
|------|-------|----------|
| **延迟消息** | 不支持（需要外挂流处理） | **原生支持**（时间轮，精度高） |
| **事务消息** | 0.11+ 支持，但只限 Kafka→Kafka | **原生支持**（二阶段提交，跨系统） |
| **消息存储** | 每个 Partition 独立日志文件 | 所有消息写同一个 CommitLog（混合存储） |
| **消费模式** | Pull（消费者主动拉） | Pull（默认）+ Push（封装了 Pull，看起来像 Push） |
| **顺序消息** | Partition 内有序 | **严格支持**（有序投递 + 有序消费） |
| **适用场景** | 日志、流处理、大数据管道 | **电商、金融**（事务消息、延迟消息） |

**本质区别**：

Kafka 是为**日志流**设计的，追求极致吞吐，功能克制；RocketMQ 是为**业务消息**设计的，追求功能完备（延迟消息、事务消息、顺序消息），吞吐也够用（单机十万级 TPS）。

**为什么选 A 不选 B？**

- 做日志收集、流处理、大数据管道 → **Kafka**（吞吐碾压）
- 做电商订单、支付、事务最终一致性 → **RocketMQ**（延迟消息、事务消息是刚需）

### RocketMQ vs RabbitMQ

| 维度 | RabbitMQ | RocketMQ |
|------|----------|----------|
| 吞吐量 | 万级 TPS | 十万级 TPS |
| 延迟消息 | TTL + DLX（不精确） | 原生支持（时间轮，精确到毫秒级） |
| 分布式 | 镜像队列 / 仲裁队列 | 原生支持（Broker Master-Slave） |
| 功能特性 | Exchange 路由灵活 | 延迟消息、事务消息、顺序消息 |

**本质区别**：RabbitMQ 是"老牌 MQ"（Erlang 写的，路由灵活但扩展难）；RocketMQ 是"现代 MQ"（Java 写的，水平扩展容易，功能更全）。

## 正确使用方式

### 正确用法

**1. 发送顺序消息（订单状态流转场景）**

```java
// 顺序消息：同一订单的消息发送到同一个队列
// 选择队列的算法：根据业务 Key 哈希
SendResult result = producer.send(msg, new MessageQueueSelector() {
    @Override
    public MessageQueue select(List<MessageQueue> mqs, Message msg, Object arg) {
        // arg = orderId，保证同一订单落到同一个队列
        int index = Math.abs(arg.hashCode()) % mqs.size();
        return mqs.get(index);
    }
}, orderId);  // ← 这里的 orderId 就是 arg
```

```java
// 消费者：有序消费（同一队列用一个线程消费）
consumer.registerMessageListener(new MessageListenerOrderly() {
    @Override
    public ConsumeOrderlyStatus consumeMessage(
        List<MessageExt> msgs, ConsumeOrderlyContext context) {
        for (MessageExt msg : msgs) {
            process(msg);  // 同一队列的消息按顺序到达
        }
        return ConsumeOrderlyStatus.SUCCESS;
    }
});
```

**为什么正确**：`MessageListenerOrderly` 保证**同一个队列的消息用一个线程串行消费**，配合生产者"相同 Key 到同一队列"，实现严格的顺序消费。

**2. 消费端幂等（必须做）**

```java
@Override
public ConsumeConcurrentlyStatus consumeMessage(
    List<MessageExt> msgs, ConsumeConcurrentlyContext context) {
    for (MessageExt msg : msgs) {
        String key = msg.getKeys();  // 发送时设置的业务唯一 Key
        // Redis SET NX 去重
        Boolean first = redis.setNX("mq:dedup:" + key, "1", 86400);
        if (Boolean.FALSE.equals(first)) {
            log.warn("重复消息，跳过: {}", key);
            continue;
        }
        process(msg);
    }
    return ConsumeConcurrentlyStatus.CONSUME_SUCCESS;
}
```

**为什么正确**：RocketMQ 和 Kafka 一样，只保证"不丢"，不保证"不重"。业务幂等是必须做的（和 MQ 选型无关）。

**3. 合理设置消费重试次数和死信队列**

```java
// 消费失败时，RocketMQ 默认重试 16 次（间隔递增）
// 可以自定义最大重试次数：
consumer.setMaxReconsumeTimes(3);  // 最多重试 3 次

// 3 次失败后，消息进入死信队列（%DLQ% + ConsumerGroup 名）
// 死信队列需要单独监控和处理
```

### 错误用法及后果

**错误1：Topic 设置太多，Broker 管理负担大**

```
错误：每个消息类型建一个 Topic
  Topic: order_create
  Topic: order_pay
  Topic: order_cancel
  ...（几百个 Topic）
```

**后果**：每个 Topic 都有 ConsumeQueue 文件，Topic 太多 → 文件句柄耗尽 → Broker OOM。

**修复**：用 **Tag** 做二级分类，一个业务域只建一个 Topic。

**错误2：消费逻辑太慢，导致消费积压**

```java
consumer.registerMessageListener((msgs, context) -> {
    for (MessageExt msg : msgs) {
        Thread.sleep(1000);  // 一条消息处理 1 秒
        process(msg);
    }
    return ConsumeConcurrentlyStatus.CONSUME_SUCCESS;
});
```

**后果**：消费速度跟不上生产速度，消息积压，延迟越来越大。

**修复**：
- 消费逻辑异步化（丢到线程池处理，快速返回 `CONSUME_SUCCESS`）
- 增加消费者实例（≤ 队列数）
- 批量消费（`consumeMessageBatchMaxSize`，默认 1，可调大）

## 边界情况和坑

### 坑1：消费位点（Offset）管理不当，导致重复消费或丢消息

RocketMQ 的 Offset 存储在 Broker 端（ConsumerOffsetManager），消费者重启后从哪里开始消费，取决于：**消费成功后才提交 Offset**。

```java
// 错误：先提交 Offset，再处理业务
public ConsumeConcurrentlyStatus consumeMessage(...) {
    consumer.updateOffset(msg.getQueue(), msg.getQueueOffset());  // 先提交
    process(msg);  // 再处理，如果这里失败，消息丢了！
    return CONSUME_SUCCESS;
}
```

**修复**：先处理业务，再返回 `CONSUME_SUCCESS`（RocketMQ 会在返回成功后自动提交 Offset）。

### 坑2：广播模式下，消费失败不会重试

```
集群消费：消费失败 → Broker 重新投递（重试队列）
广播消费：消费失败 → 不会重试（因为每条消息要发给所有消费者，重试成本太高）
```

**后果**：广播消费模式下，消费失败 = 消息丢失（应用要自己处理重试）。

**修复**：广播消费模式下，消费逻辑要有完善的异常处理和重试机制（比如 catch 到异常后，自己写重试逻辑）。

### 坑3：同一个 Consumer Group 订阅了不同的 Topic

```java
// 实例1 订阅了 Topic-A
consumer.subscribe("Topic-A", "*");

// 实例2（同一个 Group）订阅了 Topic-B
consumer.subscribe("Topic-B", "*");
```

**后果**：RocketMQ 的负载均衡是按 **Topic + Group** 分配的，同一个 Group 订阅不同 Topic，会导致负载均衡混乱，消息消费错乱。

**修复**：同一个 Consumer Group 的所有实例，必须订阅**相同的 Topic 和 Tag**。

## 面试话术

**Q：RocketMQ 和 Kafka 的核心区别是什么？**
"Kafka 是为日志流设计的，追求极致吞吐，延迟消息和事务消息支持不好；RocketMQ 是为业务消息设计的，原生支持延迟消息（时间轮）、事务消息（二阶段提交）、顺序消息，功能更全，是电商/金融场景的首选。吞吐量上 Kafka 更高（百万级 vs 十万级），但大多数业务场景十万级也够用了。"

**Q：RocketMQ 的存储模型是怎样的？为什么这么做？**
"RocketMQ 把所有 Topic 的消息都写同一个 CommitLog 文件（顺序写），然后用 ConsumeQueue 做索引（类似 Kafka 的 Partition）。这样做的好处是写入永远是顺序 I/O，不管有多少个 Topic 性能都稳定；代价是消费时要随机读 ConsumeQueue，但用 PageCache 缓存可以弥补。Kafka 是每个 Partition 独立文件，Partition 多了之后刷盘会变成随机 I/O。"

**Q：怎么保证 RocketMQ 消费不重复？**
"和 Kafka 一样，MQ 本身不保证不重复，要在业务层做幂等。常用方案：用消息的 Key（发送时设置的业务唯一键）+ Redis SET NX 去重，或者数据库唯一索引。必须在消费逻辑的最前面做去重检查。"

**Q：RocketMQ 的顺序消息是怎么实现的？**
"两点：1) 生产者用 MessageQueueSelector，让相同业务 Key（比如 orderId）的消息都落到同一个队列；2) 消费者用 MessageListenerOrderly（有序监听器），保证同一个队列的消息用一个线程串行消费。两点配合，实现严格的顺序消费。"

## 本文总结

RocketMQ 是**为业务消息设计的分布式 MQ**，核心优势是**延迟消息**、**事务消息**、**顺序消息**——这三个是 Kafka 的短板，却是电商/金融的刚需。

存储模型：所有消息写同一个 **CommitLog**（顺序写，写入性能极高）+ **ConsumeQueue**（索引文件，消费时随机读，靠 PageCache 加速）。

消费模型：集群消费（默认，竞争消费）+ 广播消费（每个消费者都收到全量）。

和 Kafka 选型：日志、流处理用 Kafka；业务消息（订单、支付、事务）用 RocketMQ。

**面试最高频**：事务消息流程、延迟消息实现（时间轮）、顺序消息实现、存储模型（vs Kafka）。
