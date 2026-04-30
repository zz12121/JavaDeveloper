# Kafka 架构与原理

## 这个问题为什么存在？

在一个分布式系统里，有大量的服务需要交换数据。如果每一个服务都直接调用另一个服务，系统会变成一张复杂的网——每一个节点都要知道其他节点的地址、协议、超时配置。这张网一旦变大，没人能理清楚依赖关系。

更深层的问题：**数据流的组织方式**。

传统的消息队列（比如早期的 RabbitMQ、ActiveMQ）在设计时主要考虑的是"消息可靠投递"，而不是"海量数据的高效流转"。当 LinkedIn 的工程师面对每天数百亿条用户行为日志时，他们发现现有方案要么吞吐不够，要么成本太高，要么在集群扩容时根本没法平滑迁移数据。

Kafka 的出现就是为了解决这个问题：**如何在分布式环境下，以极低的成本存储和传输海量消息，同时保证高可用和高可靠？**

这个问题的本质是：**磁盘这么慢，为什么 Kafka 还能做到百万级 TPS？**

## 它是怎么解决问题的？

### 整体架构

```
                     ┌─────────────────────────────────┐
                     │        Kafka Cluster            │
                     │                                 │
Producer ───→        │  ┌─────────┐  ┌─────────┐     │
  (生产者)    ───→   │  │Broker-1 │  │Broker-2 │ ... │
                     │  │Leader   │  │Leader   │     │
                     │  │Follower │  │Follower │     │
                     │  └─────────┘  └─────────┘     │
                     └─────────────────────────────────┘
                           ↑        ↑        ↑
                           └────────┴────────┘
                                Consumer Group
                                 (消费者组)
```

核心角色：
- **Broker**：Kafka 服务器节点，存储消息和处理读写请求
- **Producer**：生产者，向 Broker 发送消息
- **Consumer**：消费者，从 Broker 拉取消息
- **ZooKeeper / KRaft**：元数据管理（旧版用 ZK，新版用内置 KRaft）

### 核心原理一：日志结构存储

Kafka 最核心的设计：**用顺序写磁盘 + 零拷贝，让磁盘比内存还快。**

```
传统 MQ 存储：
  消息到来 → 写入内存 → 刷盘（随机 I/O）→ 读取时从磁盘加载

Kafka 存储：
  消息到来 → 顺序追加到日志文件末尾（顺序 I/O）→ 读取时用 sendfile 零拷贝
```

**为什么顺序写这么快？**

机械硬盘的顺序写吞吐可以达到 600MB/s，而随机写可能只有 1MB/s。差距是 **600 倍**。

SSD 虽然没有寻道开销，但顺序写依然比随机写快 3-5 倍（写入放大、块对齐等原因）。

Kafka 的每个 Partition 本质上是一个**只追加写的日志文件**（Append-Only Log）：

```
Partition-0/
  ├── 00000000000000000000.log   (消息体)
  ├── 00000000000000000000.index (偏移量索引)
  ├── 00000000000000000000.timeindex (时间戳索引)
  ├── 00000000000000001000.log   (满 1GB 后新分片)
  └── ...
```

每个 `.log` 文件默认 1GB，写满后开新文件。这种**分段 + 索引**的设计，让查找消息时可以先通过二分查找在 `.index` 里定位到大致位置，再去 `.log` 里精确读取。

### 核心原理二：零拷贝（Zero Copy）

传统数据发送流程（4 次拷贝 + 2 次上下文切换）：

```
1. read() 系统调用 → 磁盘 → 内核缓冲区 (DMA拷贝)
2. 内核缓冲区 → 用户缓冲区 (CPU拷贝)  ← 这次没必要！
3. write() 系统调用 → 用户缓冲区 → Socket缓冲区 (CPU拷贝)  ← 这次也没必要！
4. Socket缓冲区 → 网卡 (DMA拷贝)
```

Kafka 用 `sendfile()` 系统调用，把第 2、3 步去掉：

```
sendfile():
  磁盘 → 内核缓冲区 (DMA) → Socket缓冲区 (DMA) → 网卡
  （数据全程在内核空间，不经过用户空间）
```

**实测效果**：零拷贝比传统方式快 **2-3 倍**，这是 Kafka 高吞吐的关键之一。

### 核心原理三：副本机制（Replication）

每个 Partition 有多个副本，分为：

```
Partition-0:
  Leader   (Broker-1)  ← 负责所有读写请求
  Follower (Broker-2)  ← 只负责从 Leader 拉取数据，不对外服务
  Follower (Broker-3)  ← 同上
```

**ISR（In-Sync Replicas）机制**：

不是所有 Follower 都有资格参与选举。只有"跟得上 Leader"的副本才在 ISR 列表里。

```
ISR = {Leader} ∪ {Follower | 落后不超过 replica.lag.time.max.ms}
```

如果某个 Follower 落后太多，会被踢出 ISR。等它追上来了，再加回来。

**ACK 机制**（生产者配置）：

| acks | 含义 | 可靠性 | 延迟 |
|------|------|--------|------|
| 0 | 发完就不管，不等待确认 | 最低（可能丢消息） | 最低 |
| 1 | 只要 Leader 写入成功就返回 | 中等（Leader 宕机可能丢） | 中等 |
| all（-1） | 所有 ISR 副本都写入才返回 | 最高 | 最高 |

### 源码关键路径：Producer 发送流程

```
KafkaProducer.send(ProducerRecord)
  → 拦截器 (onSend)                    // 可以做消息修改、统计
  → 序列化 key/value                    // String → byte[]
  → 分区器 (Partitioner.partition())    // 决定发到哪个 Partition
  → 追加到 RecordAccumulator            // 按 Partition 分组，批量积累
  → Sender 线程（后台）                
      → 从 RecordAccumulator 取批次    
      → 按 Broker 分组（同一 Broker 的多个 Partition 批次合并为一次请求）
      → NetworkClient 发送 ProduceRequest
      → Broker 处理：
          → 写入 PageCache（操作系统缓冲）
          → 刷盘（根据 log.flush.interval.messages 配置）
          → 副本同步（Follower 拉取）
      → 返回 ProduceResponse
```

**关键设计**：`RecordAccumulator` 是批处理的核心。每个 Partition 对应一个双端队列 `Deque<ProducerBatch>`，消息先追加到当前批次，批次满了（`batch.size`）或等待时间到了（`linger.ms`）才发送。这是 Kafka 吞吐高的核心原因之一：**把多条消息合并为一个网络请求**。

## 它和相似方案的本质区别是什么？

### Kafka vs 传统消息队列（RabbitMQ/ActiveMQ）

| 维度 | RabbitMQ | Kafka |
|------|-----------|-------|
| 消息存储 | 消息消费后删除（或 ACK 后删除） | 消息按时间保留（默认 7 天），不随消费删除 |
| 消费模式 | 推送（Push）给消费者 | 消费者主动拉取（Pull） |
| 吞吐量设计 | 单条消息低延迟 | 批量处理高吞吐 |
| 数据重放 | 不支持（消息已删） | 支持（通过 Offset 回溯） |

**本质区别**：RabbitMQ 是"消息中间件"（消息即投递，投递完就删除），Kafka 是"分布式流平台"（消息即日志，永久保留，可重放）。

这个区别决定了使用场景：
- 用 RabbitMQ：做异步解耦，消息"消费即销毁"
- 用 Kafka：做事件溯源、流处理、日志管道，消息需要被多个消费者反复读取

### Kafka vs RocketMQ

| 维度 | Kafka | RocketMQ |
|------|-------|----------|
| 延迟消息 | 不支持（需要外部方案如 Kafka Streams） | 原生支持（时间轮实现，精度高） |
| 事务消息 | 0.11 支持但实现复杂 | 原生支持，二阶段提交封装得好 |
| 顺序消息 | Partition 内有序 | 严格支持，有专门的有序消费机制 |
| 管理工具 | 命令行为主，Web UI 需第三方 | 自带 Web 控制台，管理方便 |
| 适用场景 | 日志、流处理、大数据 | 电商、金融（阿里自用） |

**为什么淘宝用 RocketMQ 而不是 Kafka？** 因为电商需要延迟消息（订单 30 分钟未支付自动取消）、事务消息（扣库存和创建订单原子性），这些是 Kafka 的弱项。

## 正确使用方式

### 正确用法

**1. 合理设置 Partition 数**

```
Partition 数 = 目标吞吐 / 单个 Partition 吞吐
单个 Partition 吞吐 ≈ 10MB/s (或 10000 TPS)

例如：目标 100MB/s，需要 10 个 Partition
```

**为什么**：Partition 是 Kafka 并行度的基本单位。Producer 可以并行往不同 Partition 写，Consumer Group 可以并行从不同 Partition 读。但 Partition 也不是越多越好——每个 Partition 在 Broker 端对应一个目录、一些内存开销，Partition 太多会导致 Broker 管理负担加重。

**2. 生产者：开启幂等 + 合理 batch.size**

```java
Properties props = new Properties();
props.put("bootstrap.servers", "localhost:9092");
props.put("enable.idempotence", true);  // 开启幂等，避免网络重试导致重复
props.put("batch.size", 16384);         // 16KB 一批，默认 16KB
props.put("linger.ms", 10);             // 最多等 10ms，让批次填满
props.put("compression.type", "lz4");  // 开启压缩，减少网络传输
```

**为什么正确**：开启幂等后，Kafka 为每个 Producer 分配一个 PID + 序列号，Broker 可以识别并丢弃重复消息。配合批处理和压缩，可以在保证可靠性的同时获得高吞吐。

**3. 消费者：合理设置 max.poll.records + 异步提交**

```java
@KafkaListener(topics = "order", containerFactory = "batchFactory")
public void onMessage(List<ConsumerRecord<String, String>> records) {
    // 批量处理，减少提交次数
    for (ConsumerRecord<String, String> record : records) {
        process(record);
    }
    // 异步提交，不阻塞下一批拉取
    consumer.commitAsync();
}
```

**为什么正确**：`max.poll.records` 设置太大，会导致单次 `poll()` 处理时间过长，触发 Rebalance；设置太小，频繁 poll 增加网络开销。一般建议单次处理时间在 `max.poll.interval.ms` 的 1/3 以内。

### 错误用法及后果

**错误1：Partition 数随便设，后来发现不够再扩容**

Kafka 扩容 Partition 数后，**已有消息不会重新分布**，只有新消息会进入新 Partition。这意味着：

```
原来 2 个 Partition，消息按 hash 分布
扩容到 4 个 Partition 后：
  - 旧消息还在原来的 2 个 Partition
  - 新消息按新 hash 分布到 4 个 Partition
  - 如果业务依赖 Partition 内有序，可能出问题
```

**修复**：一开始就要预估好 Partition 数。如果真的需要扩容，考虑新建一个 Topic，用工具把数据迁移过去。

**错误2：消费者处理逻辑太慢，导致 Rebalance 风暴**

```java
// 错误：处理一条消息要 10 秒
consumer.poll(Duration.ofMillis(100));
process(record);  // 要 10 秒
consumer.commitSync();
// 下次 poll 可能已经在 10 秒后，超过了 max.poll.interval.ms，被踢出 Group
```

**修复**：把慢处理放到独立线程池，消费者只负责快速拉取和提交；或者调大 `max.poll.interval.ms`。

## 边界情况和坑

### 坑1：Rebalance 导致消费停顿

**触发场景**：
- 消费者加入或退出 Group
- 订阅的 Topic Partition 数变化
- 消费者超过 `max.poll.interval.ms` 没发起 poll（被认为"死亡"）

**后果**：Rebalance 期间，整个 Consumer Group 停止消费（Stop-the-world），直到重新分配完 Partition。

**缓解方案**：
- 合理设置 `session.timeout.ms` 和 `max.poll.interval.ms`
- 消费者处理逻辑尽量快，慢处理异步化
- Kafka 2.4+ 支持"增量 Rebalance"（Cooperative Sticky Assignor），可以减少停顿时间

### 坑2：消费者 Offset 提交混乱

**场景**：开了多线程消费，多个线程共享一个 Consumer 实例。

```java
// 错误：Kafka Consumer 不是线程安全的！
new Thread(() -> consumer.poll()).start();  // 会抛 ConcurrentModificationException
new Thread(() -> consumer.commitSync()).start();
```

**修复**：一个 Consumer 实例只能由一个线程使用。要并行消费，开多个 Consumer 实例（每个线程一个）。

### 坑3：消息太大，超过 Broker 限制

```
报错：RecordTooLargeException: The message is 1048589 bytes when max is 1048576
```

**原因**：Kafka 默认单条消息最大 1MB（`message.max.bytes`），Producer 端默认 `max.request.size` 也是 1MB。

**修复**：
- 调大 Broker 的 `message.max.bytes` 和 Topic 的 `max.message.bytes`
- 但更推荐：大消息（如文件）存到对象存储（OSS/S3），Kafka 里只传 URL

### 坑4：ISR 频繁收缩扩张

**现象**：监控发现 ISR 列表频繁变化，有时只有 Leader 一个节点。

**原因**：Follower 拉取速度跟不上 Leader，被踢出 ISR；追上后又加入，如此反复。

**后果**：如果 Leader 此时宕机，ISR 只有它自己，消息会丢失（因为没副本了）。

**修复**：
- 调大 `replica.lag.time.max.ms`（默认 30 秒，可以适当调大）
- 检查网络是否稳定、Broker 负载是否过高
- 确保 `acks=all` 时 `min.insync.replicas >= 2`（至少 2 个副本确认才认为写入成功）

## 面试话术

**Q：Kafka 为什么快？**
"四个原因：1) 顺序写磁盘，比随机写快 600 倍；2) 零拷贝（sendfile），数据不经过用户空间；3) 批处理，多条消息合并为一个网络请求；4) 分区并行，不同 Partition 可以并行消费。这四个设计叠加，让 Kafka 做到了百万级 TPS。"

**Q：Kafka 怎么保证消息不丢？**
"三层：生产端 acks=all + 重试 + 幂等；Broker 端 min.insync.replicas >= 2 + 副本机制；消费端手动提交 Offset + 先处理后提交。三个都做到，理论上不丢。"

**Q：Kafka 和 RabbitMQ 的核心区别？**
"Kafka 的消息消费后不删除，按时间保留，可以重放，适合做流处理、日志管道；RabbitMQ 的消息消费后就删除，适合传统的异步解耦场景。简单说：Kafka 是日志，RabbitMQ 是信件。"

**Q：Partition 数怎么设置？**
"Partition 数决定了并行度上限。建议：Partition 数 = 目标吞吐 / 单 Partition 吞吐（约 10MB/s）。也要考虑消费者数量，Partition 数应该 ≥ 消费者数，否则会有消费者分不到 Partition 空转。还要注意，Partition 数一旦设置，后期扩容有影响，要提前预估好。"

## 本文总结

Kafka 的高吞吐来自于四个核心设计：顺序写磁盘、零拷贝、批处理、分区并行。

存储模型：每个 Partition 是一个只追加写的日志文件，分段存储 + 稀疏索引，支持快速查找。

副本机制：Leader 负责读写，Follower 只做备份。ISR 机制保证只有"跟得上"的副本才能参与选举，平衡了可靠性和可用性。

Producer 关键配置：acks=all（不丢消息）、enable.idempotence=true（去重）、batch.size + linger.ms（批处理）、compression.type（压缩）。

Consumer 关键配置：max.poll.records（批量拉取）、手动提交 Offset（避免重复消费）、注意 Rebalance 问题。

Kafka 不是"消息队列"，是"分布式流平台"——消息持久化、可重放、支持流处理，这是它和传统 MQ 的本质区别。
