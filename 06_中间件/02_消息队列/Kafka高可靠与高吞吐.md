# Kafka 高可靠与高吞吐

## 这个问题为什么存在？

Kafka 的设计目标里，"高可靠"和"高吞吐"是两个经常冲突的维度。

**可靠性的敌人**是性能优化：

- 要可靠：每条消息要 fsync 到磁盘、要等所有副本确认、要写 WAL（预写日志）—— 这些都是"慢操作"
- 要高吞吐：要批量写、要异步刷盘、要零拷贝、要压缩 —— 这些都会牺牲可靠性

所以问题不是"怎么做到高可靠"或"怎么做到高吞吐"，而是 **"在可靠性要求下，吞吐能做到多高"** 以及 **"在吞吐要求下，可靠性底线在哪里"**。

这是一个权衡问题（Trade-off），不是非黑即白的技术问题。

## 它是怎么解决问题的？

### 高可靠：数据不丢的保证链条

Kafka 的可靠性是**分层保证**的，任何一层出问题，都可能导致消息丢失。

```
生产者层：acks=all + 重试 + 幂等
    ↓
Broker 层：副本机制 + ISR + 刷盘策略
    ↓
消费者层：手动提交 Offset + 先处理后提交
```

#### 第一层：生产者可靠性

```java
Properties props = new Properties();
props.put("bootstrap.servers", "broker1:9092,broker2:9092");
props.put("acks", "all");                    // 所有 ISR 副本确认才返回
props.put("retries", Integer.MAX_VALUE);     // 无限重试（网络抖动会重试）
props.put("max.in.flight.requests.per.connection", 1);  // 保证重试时顺序
props.put("enable.idempotence", true);      // 幂等，避免重试导致重复
```

**为什么 `max.in.flight.requests.per.connection=1`？**

如果允许同时有 5 个请求在飞（默认），请求1失败重试，请求2成功 —— 到达 Broker 的顺序变成 [请求2, 请求1]，消息顺序就乱了。`=1` 保证重试时"同一个连接只有一个在途请求"，顺序不会乱。

但这样会**降低吞吐**。Kafka 0.11+ 开启幂等后，即使 `max.in.flight > 1` 也能保证顺序（Broker 端会按序列号排序），所以**开启幂等后可以放心用默认值 5**。

#### 第二层：Broker 可靠性

**副本机制**：

每个 Partition 有多个副本，分布在不同的 Broker 上：

```
Topic: orders, ReplicationFactor=3
  Partition-0: Leader(Broker-1), Follower(Broker-2), Follower(Broker-3)
  Partition-1: Leader(Broker-2), Follower(Broker-3), Follower(Broker-1)
  ...
```

`ReplicationFactor=3` 意味着每个 Partition 有 3 个副本，允许最多 2 个 Broker 宕机而不丢数据。

**ISR 机制**：

不是所有 Follower 都算"可靠副本"。只有跟得上 Leader 的 Follower 才在 ISR（In-Sync Replicas）列表里：

```java
// Broker 配置
replica.lag.time.max.ms = 30000;  // Follower 落后超过 30 秒，踢出 ISR
min.insync.replicas = 2;          // 至少 2 个 ISR 副本写入成功，才认为消息写入成功
```

**`min.insync.replicas` 是关键**：

- `acks=all` + `min.insync.replicas=2`：至少 2 个副本（包括 Leader）写入成功才返回
- 如果 ISR 只有 1 个副本（Leader 自己），`acks=all` 也会立即返回 —— **失去了高可靠保证**
- 所以生产环境一定要设 `min.insync.replicas >= 2`

**刷盘策略**：

Kafka 默认**不调用 fsync**，数据只写到 PageCache（操作系统缓冲区），由操作系统决定什么时候刷盘。

```
# Broker 配置
# log.flush.interval.messages = 10000  # 每 10000 条消息刷一次（默认不设置，由 OS 决定）
# log.flush.interval.ms = 1000         # 每 1 秒刷一次（默认不设置）
```

**风险**：如果操作系统崩溃（不是 Kafka 崩溃），PageCache 里没刷盘的数据会丢失。

**权衡**：生产环境通常不强制刷盘（性能代价太大），而是靠**多副本**保证可靠 —— 只要有一个副本还活着，数据就不会丢。

#### 第三层：消费者可靠性

```java
// 关闭自动提交
props.put("enable.auto.commit", false);

// 消费逻辑
while (running) {
    ConsumerRecords<K, V> records = consumer.poll(Duration.ofMillis(100));
    for (ConsumerRecord<K, V> record : records) {
        processBusiness(record);  // 先处理业务
    }
    consumer.commitSync();        // 再提交 Offset
}
```

**为什么不能先提交再处理？** 如果先提交，处理失败，Offset 已经前进，消息永远不会再被消费（丢了）。

**为什么不能异步提交 + 不等待？** `commitAsync()` 失败后不会重试（因为可能已经有更新的提交），如果提交失败了，Offset 没更新，会重复消费。

### 高吞吐：百万 TPS 的技术手段

#### 手段1：顺序写磁盘

```
随机写：磁头频繁寻道，吞吐 ~1MB/s
顺序写：磁头不用移动，吞吐 ~600MB/s（机械盘也能做到）
```

Kafka 的 Partition 日志是**只追加写（Append-Only）**，天然的顺写。这是 Kafka 能"用磁盘战胜内存"的核心原因。

#### 手段2：零拷贝（sendfile）

传统网络发送（4 次拷贝）：

```
磁盘 → 内核缓冲区 → 用户缓冲区 → Socket缓冲区 → 网卡
        (DMA)       (CPU拷贝)     (CPU拷贝)     (DMA)
```

`sendfile()` 系统调用（零拷贝）：

```
磁盘 → 内核缓冲区 ──────→ Socket缓冲区 → 网卡
        (DMA)            (DMA，无CPU拷贝)
```

Java 的 `FileChannel.transferTo()` 底层就是 `sendfile()`。

**实测**：零拷贝比传统方式快 2-3 倍。

#### 手段3：批处理（Batching）

Producer 不是发一条就网络传输一条，而是**积累一批再发**：

```java
// RecordAccumulator 的核心逻辑（简化）
Deque<ProducerBatch> batchQueue = batches.get(partition);
ProducerBatch batch = batchQueue.peekLast();

if (batch == null || batch.isFull()) {
    batch = new ProducerBatch(partition, ...);
    batchQueue.add(batch);
}
batch.append(record);  // 追加到当前批次

// 发送条件：批次满了（batch.size）OR 等待时间到了（linger.ms）
```

**`batch.size` 和 `linger.ms` 的权衡**：

- `batch.size` 大 + `linger.ms` 大 → 批次大，吞吐高，但延迟高
- `batch.size` 小 + `linger.ms` 小 → 批次小，延迟低，但吞吐低

**推荐配置**：`batch.size=16384`（16KB），`linger.ms=10`（最多等 10ms）——平衡延迟和吞吐。

#### 手段4：数据压缩

```java
props.put("compression.type", "lz4");  // 可选：none/gzip/snappy/lz4/zstd
```

压缩在 Producer 端做，Broker 只存压缩后的数据，Consumer 端解压。

**效果**：

| 压缩算法 | 压缩比 | 速度 | 适用场景 |
|---------|--------|------|----------|
| gzip | 高（~50%压缩） | 慢 | 带宽贵、离线场景 |
| snappy | 中（~30%压缩） | 快 | 通用 |
| lz4 | 中（~30%压缩） | 很快 | 推荐（Kafka默认） |
| zstd | 高（~50%压缩） | 快 | 新版本推荐 |

#### 手段5：分区并行

```
Topic 有 N 个 Partition → 可以并行写入 N 个 Broker
Consumer Group 有 M 个消费者 → 最多 M 个并行消费（M ≤ N）
```

**并行度上限 = Partition 数**。要提升吞吐，先增加 Partition 数。

### 源码关键路径：零拷贝在 Kafka 中的实现

Kafka 的 `Partition` 读取数据时用 `FileChannel.transferTo()`：

```scala
// Kafka 源码：LogSegment.read()
def read(startOffset: Long, maxSize: Int): FetchDataInfo = {
  val offset = translateOffset(startOffset)
  // ...
  val channel = openChannel(file)
  // transferTo: 零拷贝发送到网络
  val bytesSent = channel.transferTo(position, size, socketChannel)
  // ...
}
```

`transferTo()` 在 Linux 上底层是 `sendfile()` 系统调用，数据直接从 PageCache 到网卡，**不经过用户空间**。

## 它和相似方案的本质区别是什么？

### Kafka 可靠性 vs RocketMQ 可靠性

| 维度 | Kafka | RocketMQ |
|------|-------|----------|
| 副本同步 | ISR 机制，Follower 异步拉取 | 同步双写（主从都写成功才返回） |
| 刷盘策略 | 依赖 OS 刷盘（默认） | 支持同步刷盘（fysnc 每次写） |
| 事务消息 | 0.11+ 支持，但只限 Kafka 内部 | 原生支持，跨系统也可以 |
| 消息不丢配置 | acks=all + min.insync.replicas=2 | 同步双写 + 同步刷盘 |

**本质区别**：Kafka 的可靠性设计是"用副本换可靠"（允许异步刷盘，靠多副本保证），RocketMQ 可以做到"同步刷盘 + 同步双写"，可靠级别更高，但性能代价也更大。

**为什么选 A 不选 B？** 如果业务能容忍秒级数据丢失（比如机器全部宕机），Kafka 的默认配置够用了，吞吐更高。如果要求"绝对不丢"（金融场景），RocketMQ 的同步刷盘更合适。

## 正确使用方式

### 正确配置：高可靠场景

```java
// 生产者（高可靠优先）
props.put("acks", "all");
props.put("retries", Integer.MAX_VALUE);
props.put("enable.idempotence", true);
props.put("max.in.flight.requests.per.connection", 5);  // 幂等开启后可以用5

// Broker 配置（server.properties）
min.insync.replicas=2
default.replication.factor=3

// 消费者（高可靠优先）
props.put("enable.auto.commit", false);
props.put("isolation.level", "read_committed");  // 只消费已提交事务的消息
```

### 正确配置：高吞吐场景

```java
// 生产者（高吞吐优先）
props.put("acks", "1");                     // 只要 Leader 写入就返回（快）
props.put("compression.type", "lz4");       // 压缩
props.put("batch.size", 32768);              // 32KB 一批
props.put("linger.ms", 10);                 // 最多等 10ms

// Broker：不强制刷盘（默认行为，依赖副本保证可靠）

// 消费者：批量拉取
props.put("max.poll.records", 500);         // 每次 poll 最多 500 条
```

### 错误用法及后果

**错误1：`acks=all` 但 `min.insync.replicas=1`（默认）**

```java
props.put("acks", "all");
// Broker 端 min.insync.replicas 没设置（默认1）
```

**后果**：ISR 只有 Leader 一个时，`acks=all` 也只等待 Leader 写入，和 `acks=1` 没区别。高可靠没生效。

**修复**：Broker 端必须设置 `min.insync.replicas=2`（至少 2 个副本确认）。

**错误2：开启压缩但 CPU 成为瓶颈**

```
compression.type = gzip  // CPU 密集，压缩率高但慢
```

**后果**：Producer 端 CPU 飙升，发送吞吐反而下降。

**修复**：换成 `lz4` 或 `snappy`，CPU 开销小，压缩率适中。

**错误3：Partition 数过多，Broker 不堪重负**

```
10000 个 Partition，每个 Partition 有独立的日志文件和内存开销
```

**后果**：Broker 的 JVM 堆压力大（每个 Partition 的索引要放内存），文件句柄不够用，吞吐量反而下降。

**修复**：Partition 数不是越多越好。经验值：单个 Broker 的 Partition 数不超过 2000。需要更多并行度时，加 Broker 节点。

## 边界情况和坑

### 坑1：ISR 频繁收缩，可靠性和可用性二选一

**场景**：网络抖动，Follower 偶尔落后超过 `replica.lag.time.max.ms`，被踢出 ISR。

**问题**：ISR 只剩 Leader 一个 → `min.insync.replicas=2` 无法满足 → 生产者写入失败（NotEnoughReplicasException）。

**权衡**：
- 如果要高可靠：保留 `min.insync.replicas=2`，接受"ISR 不足时写入失败"
- 如果要高可用：降低 `min.insync.replicas=1`，接受"可能丢消息"

**没有完美方案**，只能根据业务取舍。

### 坑2：消费者 `read_committed` 模式下的性能问题

```java
props.put("isolation.level", "read_committed");  // 只消费已提交事务的消息
```

**问题**：如果生产者开启了事务，但长时间没提交（比如事务卡住了），消费者会**一直等待**，不消费任何消息。

**后果**：消费停顿，消息堆积。

**修复**：设置 `transaction.timeout.ms`（默认 60 秒），事务超时后 Kafka 会自动回滚。

### 坑3：批量发送导致消息延迟

```
batch.size=16KB, linger.ms=100ms
→ 消息最多延迟 100ms 才被发送
```

**场景**：对延迟敏感的业务（比如实时推荐），100ms 太长了。

**修复**：`linger.ms=0`（立即发送），或者减小 `batch.size`。但吞吐会下降。

## 面试话术

**Q：Kafka 怎么保证消息不丢？**
"三层保障：生产端 acks=all + 重试 + 幂等；Broker 端 min.insync.replicas >= 2 + 多副本；消费端手动提交 Offset + 先处理后提交。三层都做到，加上 Broker 不单机部署，理论上可以做到零丢失。"

**Q：Kafka 为什么快？**
"四个原因：1) 顺序写磁盘；2) 零拷贝（sendfile）；3) 批处理（多条消息合并发送）；4) 分区并行。四个叠加，做到了百万级 TPS。"

**Q：acks=all 就一定能保证不丢消息吗？**
"不一定。如果 Broker 端的 min.insync.replicas=1（默认），当 ISR 只有 Leader 一个时，acks=all 也只等 Leader 写入，和 acks=1 没区别。所以要真正不丢，必须同时设置 acks=all 和 min.insync.replicas >= 2。"

**Q：Kafka 的可靠性和性能怎么权衡？**
"acks=all + 同步刷盘 = 高可靠但性能差；acks=1 + 异步刷盘 = 高性能但可能丢消息。生产环境通常用 acks=all + min.insync.replicas=2 + 异步刷盘（依赖副本保证可靠），在可靠和性能之间取平衡。"

## 本文总结

Kafka 的可靠性是**分层保证**的：生产者（acks=all + 幂等）→ Broker（副本 + ISR + min.insync.replicas） → 消费者（手动提交 + 先处理后提交）。

高吞吐来自四个设计：顺序写磁盘、零拷贝（sendfile）、批处理（RecordAccumulator）、分区并行。

`min.insync.replicas` 是可靠性的关键配置 —— 只设 `acks=all` 不够，必须同时设 `min.insync.replicas >= 2`。

可靠性和性能是 Trade-off：同步刷盘 + acks=all 最可靠但最慢；acks=1 + 异步刷盘最快但可能丢消息。生产环境通常用"多副本 + 异步刷盘"取平衡。

Partition 数不是越多越好，单个 Broker 建议不超过 2000 个 Partition。
