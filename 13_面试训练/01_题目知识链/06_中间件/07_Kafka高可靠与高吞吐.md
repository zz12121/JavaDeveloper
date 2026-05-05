# Kafka 如何保证高可靠？ Producer/Consumer 分别怎么配置？

> ⚠️ **先盲答**：Kafka 的消息可靠性怎么保证？Producer 端怎么配置？

---

## 盲答引导

1. Kafka 的 acks 配置有三个值：0 / 1 / all，它们分别代表什么？
2. acks=all 一定能保证不丢消息吗？还需要什么条件？
3. Consumer 端怎么保证不丢消息？—— 手动提交 offset
4. 「exactly-once」语义怎么实现？Kafka 事务是什么？

---

## 知识链提示

```
Kafka 高可靠
  → [[07_中间件/02_消息队列/Kafka高可靠与高吞吐]]
    → Producer 端保证
      → acks 配置
        → acks=0：发出去就返回，不管是否到达（最快，最容易丢）
        → acks=1：Leader 收到就返回（中等，可能丢 Leader 未同步给 Follower 的数据）
        → acks=all（-1）：Leader + 所有 ISR 副本都写入才返回（最安全，慢）
      → 重试机制：retries > 0（网络抖动时自动重试）
      → enable.idempotent=true（开启幂等 Producer）
    → Consumer 端保证
      → 手动提交 offset（enable.auto.commit=false）
        → 先处理业务，再提交 offset
        → 业务处理失败 → 不提交 offset → 重试
      → 幂等消费：业务层实现幂等（[[08_分布式与架构/05_高可用设计/幂等性设计]]）
    → Exactly-Once 语义
      → Kafka 0.11+ 事务：Producer 事务 + 消费者事务
      → Producer 事务：多分区操作的原子性
      → 消费者事务：offset 和业务操作原子性
      → 注意：只适用于 Kafka 内部，跨系统 exactly-once 需业务补偿
```

---

## 核心追问

| 追问 | 考点 |
|------|------|
| acks=all 一定安全吗？ | 需要 min.insync.replicas >= 2 配合，否则没有实际保护 |
| 消费者自动提交 offset 的问题是什么？ | 处理一半时消费者挂了 → 已处理但未提交 → 重消费 |
| 幂等 Producer 和 exactly-once 是一回事吗？ | 不是，幂等 Producer 只保证「重复消息不重复」，不能保证多分区原子性 |
| Kafka 事务适合什么场景？ | ETL 管道：Kafka → Flink/Spark → Kafka，保证端到端 exactly-once |

---

## 参考答案要点

**acks 三个级别**：

| acks | 速度 | 可靠性 | 适用场景 |
|------|------|--------|---------|
| 0 | 最快 | 可能丢 | 日志采集，丢几条无所谓 |
| 1 | 中 | 可能丢（Follower 未同步） | 一般场景 |
| all | 最慢 | 最安全 | 金融，订单等关键数据 |

**Consumer 不丢消息**：手动提交 offset + 业务幂等。

---

## 下一步

打开 [[07_中间件/02_消息队列/Kafka高可靠与高吞吐]]，补充 `双向链接`：「Kafka 的高可靠是一套组合拳——Producer 端 acks=all + ISR + 幂等，Consumer 端手动 offset + 幂等」。
