# RabbitMQ 的架构是怎样的？交换机类型有哪些？

> ⚠️ **先盲答**：RabbitMQ 的核心组件有哪些？Queue 和 Exchange 是什么关系？

---

## 盲答引导

1. RabbitMQ 的四组件是什么？—— Producer / Exchange / Binding / Consumer / Queue
2. 四种交换机类型分别是什么？—— direct / fanout / topic / headers
3. direct 和 topic 交换机的区别是什么？
4. RabbitMQ 的消息确认机制是什么？—— Confirm 模式 + Consumer ACK

---

## 知识链提示

```
RabbitMQ 架构
  → [[RabbitMQ架构与交换机]]
    → 核心组件
      → Producer：发送消息，不直接和 Queue 打交道
      → Exchange：交换机，接收 Producer 消息，按规则路由到 Queue
      → Binding：Exchange 和 Queue 之间的绑定关系（Routing Key）
      → Queue：消息队列，存储消息
      → Consumer：消费消息
    → 四种交换机
      → direct：精确匹配 Routing Key（完全相等）
      → fanout：广播，忽略 Routing Key，发送给所有绑定的 Queue
      → topic：通配符匹配（*.order.# / *.#）
      → headers：按消息 Header 属性匹配（基本不用，性能差）
    → 消息确认机制
      → 生产者确认（Publisher Confirm）：消息到达 Broker 返回 ACK
      → 消费者确认（Consumer ACK）
        → 自动 ACK：消息发出即确认（不可靠）
        → 手动 ACK：处理成功才确认（可靠）
      → 死信队列（DLX）：消息被拒绝（reject/nack）+TTL 超时 + 队列满 → 转入死信队列
```

---

## 核心追问

| 追问 | 考点 |
|------|------|
| RabbitMQ 和 Kafka 的核心区别是什么？ | RabbitMQ（队列模型，多租户）/ Kafka（日志模型，高吞吐）|
| RabbitMQ 的消息堆积了怎么办？ | 增加消费者 / 开启消息 TTL + 死信队列 / 消息过期策略 |
| 什么是镜像队列？它和普通队列的区别是什么？ | 镜像队列（主从同步，高可用）/ 普通队列（单节点）|
| RabbitMQ 的消息优先级是怎么实现的？ | 优先级队列（x-max-priority），消费者先取高优先级 |

---

## 参考答案要点

**四种交换机速记**：

| 类型 | 路由规则 | 典型场景 |
|------|---------|---------|
| direct | Routing Key 完全匹配 | 一对一精确路由 |
| fanout | 忽略 Key，广播到所有 Queue | 广播通知 |
| topic | 通配符（* 匹配一个词，# 匹配零或多个词）| 多消费者不同规则 |
| headers | 按 Header 属性匹配 | 很少用 |

**RabbitMQ vs Kafka**：RabbitMQ 功能更丰富（死信队列/延迟队列/优先级），Kafka 吞吐更高。

---

## 下一步

打开 [[RabbitMQ架构与交换机]]，对比 [[MQ核心概念]]，补充链接：「RabbitMQ 的交换机是『路由规则』，Kafka 的 Topic 是『日志流』——两者模型不同，导致适用场景不同」。
