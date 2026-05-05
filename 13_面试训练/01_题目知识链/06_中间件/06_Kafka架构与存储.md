# Kafka 的架构是怎样的？为什么这么快？

> ⚠️ **先盲答**：Kafka 是什么？它的基本架构是什么？

---

## 盲答引导

1. Kafka 的核心组件是什么？—— Producer / Broker / Consumer / Topic / Partition / Zookeeper
2. Topic 和 Partition 是什么关系？Partition 的数量越多越好吗？
3. Kafka 为什么能做到高吞吐？—— 顺序写 + 零拷贝 + 批量压缩
4. Kafka 的消息是怎么存储的？—— Segment 文件 + 索引文件

---

## 知识链提示

```
Kafka 架构与存储
  → [[Kafka架构与存储]]
    → 核心概念
      → Topic：消息的逻辑分类
      → Partition：Topic 的物理分区，每个 Partition 是一个有序不可变的消息序列
      → Replica：副本，分区内有 Leader 和 Follower
      → Consumer Group：消费者组，同一 Partition 只能被组内一个 Consumer 消费
    → Kafka 为什么快（高吞吐）
      → 顺序写磁盘：消息追加到文件末尾，不随机寻址
      → 零拷贝（Zero Copy）：sendfile() 系统调用，数据从磁盘到网卡跳过用户态
      → 批量发送：多个消息打包一次网络往返
      → 压缩：批量压缩（gzip / snappy / lz4）
      → [[顺序读写]] vs 随机读写：顺序 IO 速度接近内存
    → 存储结构
      → 每个 Partition → 多个 Segment（.log 文件 + .index 索引 + .timeindex 时间索引）
      → Segment 满了 → 创建新 Segment
      → 索引文件：稀疏索引（不是每个消息都建索引，而是间隔建）
```

---

## 核心追问

| 追问 | 考点 |
|------|------|
| Partition 数量是越多越好吗？ | 不是，多 Partition = 多文件句柄 + 多 Leader 选举开销 |
| Kafka 怎么保证消息不丢失？ | acks=all + 副本数 ≥ 3 + 关闭 unclean leader election |
| Follower 和 Leader 之间的同步机制是什么？ | ISR（In-Sync Replicas）列表，只有 ISR 里的副本才算同步 |
| Segment 文件里，消息怎么定位？ | 稀疏索引：先二分查 .index，再顺序读 .log |

---

## 参考答案要点

**Kafka 高吞吐的四个关键**：
1. **顺序写磁盘**：磁盘顺序读写速度接近内存（HDD ~500MB/s，SSD 更高）
2. **零拷贝**：数据从磁盘到网卡，不经过用户态（传统方案经过 4 次拷贝，Kafka 2 次）
3. **批量压缩**：多条消息一起压缩，减少网络 IO
4. **批量发送**：攒够一定量再发，减少网络往返

---

## 下一步

打开 [[Kafka架构与存储]]，对比 [[MQ核心概念]]，补充链接：「Kafka 的 Partition 是并行消费的基础——Partition 数量决定了最大并发消费数」。
