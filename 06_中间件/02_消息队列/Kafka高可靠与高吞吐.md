# Kafka高可靠与高吞吐

## 这个问题为什么存在？

> 消息队列的核心矛盾是：**可靠性 vs 吞吐量**。要可靠，就要等ACK、刷盘、多副本同步，势必要牺牲速度；要高吞吐，就要批量发送、异步处理、减少等待，也必然牺牲可靠性。

Kafka 解决这个矛盾的方式是**把可靠性配置权交给用户**，通过参数组合让用户自己决定 trade-off。

## Kafka 的高吞吐核心

### 顺序写磁盘 + 内存映射（mmap）

**磁盘顺序写的速度可以接近内存**。原因是：随机写需要磁盘寻道（机械硬盘 10ms 级别），顺序写只需要磁头持续移动。

```
随机写：写 1MB → 需要多次寻道 → 耗时 ~100ms
顺序写：写 1MB → 一次寻道 → 耗时 ~1ms（顺序带的机械特性）
```

Kafka 把每条消息追加到日志文件末尾（顺序写），而不是随机写入不同位置。

**mmap（内存映射）**：通过 `FileChannel.map()` 把磁盘文件映射到内存地址空间，写入变成直接的内存写，操作系统负责异步刷盘。

### 零拷贝（sendfile）

传统方式读取文件并发送（4次拷贝）：
```
磁盘 → 内核缓冲区 → 用户空间 → Socket 缓冲区 → 网卡
```

Kafka 的 sendfile（2次拷贝）：
```
磁盘 → 内核缓冲区 → 网卡
        ↑ ↓
    直接传给网卡，跳过用户空间
```

节省了两次 CPU 拷贝，从 4 次降到 2 次。这是 Kafka 高吞吐的关键技术之一。

### 批量处理

```
生产者：积攒多条消息 → 一次网络请求发送（batch.size 默认 16KB）
 Broker：攒多个批次 → 一次刷盘（linger.ms 默认 0，即立即发送）
消费者：一次拉取多条（fetch.min.bytes）
```

参数配置：
```properties
# 生产者
batch.size=16384        # 批量大小（字节）
linger.ms=10             # 等待多久凑满 batch（默认 0，不等待）
compression.type=lz4   # 批量压缩（lz4/snappy/zstd/gzip）

# 消费者
fetch.min.bytes=1        # 消费者等待的最小数据量
fetch.max.wait.ms=500    # 最长等待时间
```

## Kafka 的高可靠：副本与 ISR

### 副本机制

每个 Topic 的每个 Partition 有 N 个副本（`replication.factor`），分布在不同 Broker 上：

```
Partition 0
├── Leader（Broker 1）→ 处理所有读写请求
├── Follower-1（Broker 2）→ 同步 Leader 数据
└── Follower-2（Broker 3）→ 同步 Leader 数据
```

Follower 不处理客户端请求，只**被动同步** Leader 的数据。如果 Leader 挂了，从 Follower 中选新的。

### ISR（In-Sync Replicas）：谁有资格当 Leader

只有跟得上 Leader 的 Follower 才算 ISR：

```
ISR = { Leader } ∪ { Follower 已追上 Leader 的所有消息 }

判断标准：
  1. Follower 与 Leader 的差距（replica.lag.max.messages）
  2. Follower 多久没拉取数据（replica.lag.time.max.ms）
```

参数：
```properties
replica.lag.time.max.ms=30000   # 超过 30s 不拉取 → 踢出 ISR
replica.lag.max.messages=4000   # 落后超过 4000 条 → 踢出 ISR
```

**ISR 是 Kafka 可靠性配置的核心**：把 `acks` 和 `ISR` 结合，控制需要多少副本确认才认为写入成功。

## Kafka 的可靠性配置：acks 参数

```properties
# 生产者 acks 配置
acks=0   # 发送即成功，不等任何确认
acks=1   # Leader 写入成功即返回（不等 Follower 同步）
acks=all # 等 ISR 中所有副本都写入成功才返回
```

### 三种 acks 的 trade-off

```
acks=0：生产者发出即成功
  ✅ 最高吞吐（网络正常时几乎无等待）
  ❌ Leader 刚写入就崩溃，数据丢失

acks=1：Leader 写入并刷盘后返回
  ✅ 吞吐较高，Leader 不丢
  ❌ Leader 崩溃后没来得及同步到 Follower，数据丢失

acks=all：等 ISR 所有副本都写入成功
  ✅ 最多丢 0 条（ISR ≥ 2 的前提下）
  ❌ 吞吐最低，等所有副本确认
```

### `min.insync.replicas`：最少的 ISR 数量

```properties
min.insync.replicas=2
acks=all
```

配合使用：ISR 中必须至少有 2 个副本确认，才算写入成功。如果只有 1 个副本（其他都掉线了），**写入会被拒绝**，抛出 `NotEnoughReplicasException`。这是防止"只有1个副本时 acks=all 退化成 acks=1"的保护机制。

### 消费者可靠性：offset 提交策略

消费者处理消息后，需要提交 offset 告诉 Broker"这条消息我处理完了"：

```java
// 方式1：自动提交（默认）
properties.put("enable.auto.commit", "true");  // 每 5s 提交一次
// 风险：自动提交后消费者崩溃，消息会被重复消费

// 方式2：手动提交
consumer.commitSync();  // 同步提交，阻塞
// 风险：提交后才崩溃，同一条消息不会重复处理
```

**核心矛盾**：提交 offset 太早 → 消息处理失败但已经提交 → 消息丢失；提交 offset 太晚 → 重复消费。Kafka 没有 XA 事务，所以需要业务侧自己实现幂等（如数据库主键幂等）。

## 它和相似方案的本质区别是什么？

### Kafka vs RabbitMQ / RocketMQ

| | Kafka | RabbitMQ | RocketMQ |
|---|---|---|---|
| 吞吐量 | 极高（10万+/s） | 中（万级/s） | 高 |
| 消息模型 | 分区 + 顺序写 | 多 Exchange | 分区 + 延迟消息 |
| 可靠性配置 | acks + ISR | publisher confirms + 镜像队列 | 同步双写 |
| 消息顺序 | 同分区有序 | 队列有序 | 分区有序 |
| 事务 | 只支持 Producer 端 | ❌ | 完整 XA 事务 |
| 适用场景 | 日志、大数据、流处理 | 小中型业务队列 | 电商交易 |

### 零拷贝：Kafka vs 普通做法

Kafka 的 sendfile（零拷贝）让文件传输绕过用户空间，直接在内核缓冲区与网卡之间传递数据。省去 2 次 CPU 拷贝，是 Kafka 能达到百万 QPS 的核心原因之一。

## 正确使用方式

### 生产者推荐配置

```properties
acks=all
retries=3
enable.idempotence=true          # 开启幂等（防止生产者重试导致重复消息）
max.in.flight.requests.per.connection=5  # 飞行中请求数（幂等下可设 > 1）
compression.type=lz4
```

`enable.idempotence=true`：每个 Producer 有一个 PID（Producer ID），每个消息有单调递增的 sequence number。Broker 根据 (PID, sequence) 去重，实现**精确一次（Exactly-Once）语义**。

### 消费者正确处理消息

```java
while (true) {
    ConsumerRecords<String, String> records = consumer.poll(Duration.ofMillis(1000));
    for (ConsumerRecord<String, String> record : records) {
        try {
            process(record);         // 业务处理
            commitOffset();           // 业务处理成功后提交 offset
        } catch (Exception e) {
            // 处理失败：不要提交 offset，让下一轮重新消费
            // 结合重试机制或死信队列处理
        }
    }
}
```

**原则：先处理，再提交**。如果处理失败，**不要提交 offset**，这样下一轮 poll 还能拿到同一条消息。

## 边界情况和坑

### ISR 收缩导致数据丢失

```properties
# 如果只有 1 个副本在 ISR 里
min.insync.replicas=1  # ← 设置太低
acks=all
```

假设 Leader 崩溃前 ISR 收缩到只有 Leader 自己，此时 acks=all 等 Leader 确认就返回，但这个 Leader 崩溃后数据就丢了。**`min.insync.replicas` 必须 ≥ 2 才能真正保证不丢**。

### 消息重复消费

```
生产者发送消息 → Broker 写入成功 → 网络抖动 → 生产者重试 → 发送同样消息
```

幂等生产者（`enable.idempotence=true`）可以解决**生产者重试导致重复**的问题。但消费者端的重复消费（处理成功后崩溃，还没提交 offset），需要业务侧幂等（如消息处理前先查数据库主键）。

### Leader 选举时消息不可用

如果 Follower 全部掉线，Leader 也崩溃了，Kafka 无法选举新 Leader（没有足够的 ISR）。这段时间**整个 Partition 不可用**，直到有 Follower 重新连上。

参数 `unclean.leader.election.enable=true` 可以允许不在 ISR 的 Follower 当选 Leader（数据可能不一致），以可用性换数据完整性。

### 分区数与吞吐的关系

```
分区数越多 → 并发消费线程越多 → 吞吐越高
分区数越少 → 并发度低 → 吞吐受限
```

但分区数不是越多越好：
- 分区数过多会增加 Broker 间复制开销
- 每个分区有独立的 Leader 和 ISR 管理开销
- 消费者数量 ≤ 分区数（每个消费者分配至少 1 个分区）

**建议**：预估吞吐量，先设适中值（3-10），通过压测调整。

## 我的理解

Kafka 的高吞吐和高可靠是**参数配置层面的 trade-off**，不是架构上的矛盾：

- **高吞吐**：顺序写 + mmap + 零拷贝 + 批量发送 → 减少 IO 和 CPU 开销
- **高可靠**：`acks=all` + `min.insync.replicas≥2` + 幂等生产者 + 手动 offset 提交 → 零丢失

面试中最核心的两个追问：
1. **acks=all + min.insync.replicas=2 为什么能保证不丢数据**（ISR 里两个副本都确认才返回）
2. **零拷贝（sendfile）为什么快**（省去用户空间拷贝，2次拷贝 vs 4次）
