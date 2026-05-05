# RabbitMQ 消息可靠性

## 这个问题为什么存在？

RabbitMQ 的消息可靠性问题，本质上是一个**分布式系统的一致性问题**。

消息从生产者到消费者，要经过三个环节：

```
生产者 → Broker (RabbitMQ Server) → 消费者
   ↑                              ↑
   │                               │
   └── 环节1：生产者到 Broker     └── 环节2：Broker 到消费者
```

任何一个环节出问题，都可能导致消息丢失：

- **环节1**：生产者发消息时网络断了，或者 Broker 收到了但没持久化，重启后消息没了
- **环节2**：Broker 把消息推给消费者，但消费者处理到一半崩溃了，Broker 已经把消息删了（以为消费成功了）
- **环节3**：Broker 自己宕机，内存里的消息没刷盘

更要命的是：**RabbitMQ 默认什么都不保证**。生产者 `basicPublish()` 是异步的，Broker 收到了不会通知你；消费者默认 autoAck=true，Broker 把消息发出去就立即删除，不管你有没有处理完。

所以要解决的问题是：**如何在分布式环境下，保证消息从生产到消费的全链路不丢失？**

## 它是怎么解决问题的？

RabbitMQ 提供了**分层可靠性保障**，每一层解决一个环节的丢失问题。

### 第一层：生产者 → Broker（发送可靠性）

#### 方案1：Transaction（事务）—— 不推荐

```java
// 开启事务
channel.txSelect();
try {
    channel.basicPublish("exchange", "key", null, message.getBytes());
    channel.txCommit();  // 提交事务
} catch (Exception e) {
    channel.txRollback();  // 回滚
}
```

**问题**：性能极差。Transaction 会**同步阻塞**，每条消息都要等 Broker 确认，吞吐狂降 **250 倍**。

#### 方案2：Confirm 机制（推荐）

```java
// 开启 Confirm
channel.confirmSelect();

// 异步监听 Confirm 结果
channel.addConfirmListener(new ConfirmListener() {
    @Override
    public void handleAck(long deliveryTag, boolean multiple) {
        // Broker 确认收到（消息安全了）
        outstandingMessages.remove(deliveryTag);
    }
    @Override
    public void handleNack(long deliveryTag, boolean multiple) {
        // Broker 没收到（需要重发）
        Message msg = outstandingMessages.get(deliveryTag);
        resend(msg);
    }
});

// 发送消息（异步，不阻塞）
channel.basicPublish("exchange", "key", null, message.getBytes());
outstandingMessages.put(deliveryTag++, message);
```

**为什么好**：Confirm 是**异步**的，生产者可以继续发下一条，Broker 异步通知哪些收到了。性能比 Transaction 好得多。

**关键**：`handleNack` 里的 `deliveryTag` 是 Broker 返回的，表示哪条消息没收到，需要重发。

#### 方案3：Return 机制（路由失败通知）

```java
// 开启 Return 监听
channel.addReturnListener(new ReturnListener() {
    @Override
    public void handleReturn(int replyCode,
                             String replyText,
                             String exchange,
                             String routingKey,
                             AMQP.BasicProperties properties,
                             byte[] body) {
        // 消息路由不到任何 Queue 时触发
        log.error("消息路由失败: {}, body={}", routingKey, new String(body));
        // 处理逻辑：记录日志、重发、告警...
    }
});

// mandatory=true：如果路由不到 Queue，触发 Return 回调（而不是丢弃）
channel.basicPublish("exchange", "key", true, null, message.getBytes());
```

**为什么需要**：默认情况下，如果消息路由不到任何 Queue，RabbitMQ 会**直接丢弃**。设 `mandatory=true` 后，路由失败会触发 Return 回调，让生产者感知到。

### 第二层：Broker 存储可靠性

#### 消息持久化

```java
// 1. Queue 要持久化
channel.queueDeclare("order_queue",
    true,   // durable=true: Broker 重启后 Queue 还在
    false, false, null);

// 2. 消息要持久化
AMQP.BasicProperties props = new AMQP.BasicProperties.Builder()
    .deliveryMode(2)  // 2=持久化, 1=非持久化
    .build();
channel.basicPublish("", "order_queue", props, message.getBytes());
```

**两个都要设**：只设 Queue durable=true，消息不持久化，Broker 重启后 Queue 在但消息丢了；只设消息持久化但 Queue 不持久化，Broker 重启后 Queue 都没了，消息更没地方存。

#### 镜像队列 / 仲裁队列（高可用）

持久化只能保证"Broker 重启后消息不丢"，但如果**整个节点磁盘坏了**呢？

```java
// 镜像队列（旧版，已不推荐）
// 通过 policy 设置：ha-mode=all 或 ha-mode=nodes

// 仲裁队列（RabbitMQ 3.8+ 推荐）
Map<String, Object> args = new HashMap<>();
args.put("x-queue-type", "quorum");  // 仲裁队列
channel.queueDeclare("order_queue", true, false, false, args);
```

**仲裁队列**：数据复制到多个节点（Raft 协议），即使一个节点磁盘坏了，其他节点还有数据。解决了"单节点故障"问题。

### 第三层：Broker → 消费者（消费可靠性）

#### 手动 Ack（最重要）

```java
// 关闭自动 Ack
channel.basicConsume("order_queue", false, new DefaultConsumer(channel) {
    @Override
    public void handleDelivery(String consumerTag,
                               Envelope envelope,
                               AMQP.BasicProperties properties,
                               byte[] body) throws IOException {
        try {
            processMessage(body);
            // 手动 Ack：告诉 Broker 处理完了，可以删除了
            channel.basicAck(envelope.getDeliveryTag(), false);
        } catch (Exception e) {
            // 处理失败：拒绝消息
            // requeue=true: 重新入队，给其他消费者处理
            // requeue=false: 丢弃或进入死信队列
            channel.basicNack(envelope.getDeliveryTag(), false, true);
        }
    }
});
```

**为什么必须手动 Ack**：自动 Ack（`autoAck=true`）下，Broker 把消息**发出去就立即删除**，不管消费者有没有处理成功。如果消费者拿到消息后处理到一半崩溃了，这条消息就永远丢了。

**`basicAck` vs `basicNack` vs `basicReject`**：
- `basicAck(deliveryTag, multiple)`：确认消费成功，Broker 可以删除消息
- `basicNack(deliveryTag, multiple, requeue)`：确认消费失败，`requeue=true` 重新入队
- `basicReject(deliveryTag, requeue)`：和 Nack 类似，但不能批量拒绝

### 源码关键路径：Confirm 机制实现

RabbitMQ 的 Confirm 机制在 AMQP 协议层是 **Confirm.Select** 扩展：

```
生产者:
  → 发送 Confirm.Select 请求
  ← Broker 返回 Confirm.Select-Ok
  
  → 发送消息1 (deliveryTag=1)
  → 发送消息2 (deliveryTag=2)
  ...
  ← Broker 异步返回 Ack (deliveryTag=1, multiple=false)
  ← Broker 异步返回 Ack (deliveryTag=2, multiple=false)

如果 Broker 处理失败：
  ← Broker 返回 Nack (deliveryTag=3)
```

**`multiple=true` 的含义**：表示"<= deliveryTag 的所有消息都确认了"。比如 `Ack(deliveryTag=5, multiple=true)` 表示 1~5 都成功了，减少网络开销。

## 深入原理

### RabbitMQ 可靠性 vs Kafka 可靠性

| 维度 | RabbitMQ | Kafka |
|------|----------|-------|
| 生产端确认 | Confirm 机制（异步） | acks=all + 重试 |
| 存储可靠 | 持久化 + 仲裁队列 | 副本机制 + ISR |
| 消费确认 | 手动 Ack（每条或批量） | 提交 Offset |
| 消息不丢配置 | Confirm + 持久化 + 手动Ack + 仲裁队列 | acks=all + min.isync.replicas=2 + 手动提交 |
| 性能代价 | Confirm 比 Transaction 好，但仍有开销 | acks=all 有明显性能下降 |

**本质区别**：RabbitMQ 的可靠性是"逐条确认"模型（每条消息或每批次确认），Kafka 是"批量 Offset 提交"模型。RabbitMQ 更精细，但开销更大；Kafka 更粗粒度，但吞吐更高。

**为什么选 A 不选 B？** 如果业务对可靠性要求极高（金融场景），且吞吐量不需要特别大，RabbitMQ 的逐条确认更让人放心。如果吞吐量是首要考虑，Kafka 的可靠性配置已经够用了。

## 正确使用方式

### 正确用法

**1. 生产端：Confirm + Return + 持久化**

```java
channel.confirmSelect();
channel.addConfirmListener(new ConfirmListener() {
    @Override
    public void handleAck(long deliveryTag, boolean multiple) {
        outstandingConfirms.acknowledge(deliveryTag, multiple);
    }
    @Override
    public void handleNack(long deliveryTag, boolean multiple) {
        // 重发逻辑
        outstandingConfirms.get(deiveryTag).forEach(this::resend);
    }
});
channel.addReturnListener(...);  // 路由失败监听

AMQP.BasicProperties props = new AMQP.BasicProperties.Builder()
    .deliveryMode(2)  // 持久化
    .build();
channel.basicPublish("exchange", "key", true, props, message.getBytes());
```

**为什么正确**：三层保护——Confirm 保证 Broker 收到，Return 保证路由没失败，持久化保证 Broker 重启后消息不丢。

**2. 消费端：手动 Ack + 幂等 + 死信队列**

```java
// 声明死信 Exchange 和 Queue
channel.exchangeDeclare("dlx_exchange", "direct");
channel.queueDeclare("dlx_queue", true, false, false, null);
channel.queueBind("dlx_queue", "dlx_exchange", "dlx_key");

// 主队列绑定死信 Exchange
Map<String, Object> args = new HashMap<>();
args.put("x-dead-letter-exchange", "dlx_exchange");
args.put("x-dead-letter-routing-key", "dlx_key");
channel.queueDeclare("order_queue", true, false, false, args);

// 消费：手动 Ack + 幂等
channel.basicConsume("order_queue", false, new DefaultConsumer(channel) {
    @Override
    public void handleDelivery(...) {
        String bizKey = extractBizKey(body);
        if (redis.setNX("idempotent:" + bizKey, "1", 86400)) {
            process(body);
            channel.basicAck(envelope.getDeliveryTag(), false);
        } else {
            log.warn("重复消息，跳过");
            channel.basicAck(envelope.getDeliveryTag(), false);  // 幂等后也要 Ack，否则会一直重发
        }
    }
});
```

**为什么正确**：
- 手动 Ack 保证不丢
- 幂等（Redis SET NX）保证不重复处理
- 死信队列兜底，处理失败的消息有地方去

**3. 搭建仲裁队列（替代镜像队列）**

```java
Map<String, Object> args = new HashMap<>();
args.put("x-queue-type", "quorum");
// 仲裁队列自动复制到多个节点，用 Raft 协议保证一致性
channel.queueDeclare("order_queue", true, false, false, args);
```

**为什么正确**：单节点故障不会导致消息丢失。仲裁队列比旧版镜像队列更可靠、性能更好。

### 错误用法及后果

**错误1：开了 Confirm 但不处理 Nack**

```java
channel.addConfirmListener(new ConfirmListener() {
    @Override
    public void handleAck(long deliveryTag, boolean multiple) {
        // 处理了
    }
    @Override
    public void handleNack(long deliveryTag, boolean multiple) {
        // 空实现！！！Nack 的消息没重发
    }
});
```

**后果**：Broker 没收到的消息，生产者不知道，消息永远丢了。

**修复**：`handleNack` 里必须实现重发逻辑。

**错误2：手动 Ack 但忘了调用 basicAck**

```java
channel.basicConsume("queue", false, new DefaultConsumer(channel) {
    @Override
    public void handleDelivery(...) {
        process(body);
        // 忘了调用 basicAck！！！
    }
});
```

**后果**：消息一直停留在"Unacked"状态，RabbitMQ 认为消费者还在处理，不会重新投递。时间长了，Unacked 消息堆积，内存暴涨。

**修复**：确保 `basicAck` 在任何情况下（包括异常）都能被调用（用 `finally` 块）。

**错误3：`basicNack` 时 `requeue=true`，且消费一直失败，形成死循环**

```
消息 → 消费失败 → Nack(requeue=true) → 重新入队 → 又消费 → 又失败 → ...
```

**后果**：消息无限循环，CPU 和日志全部被打爆。

**修复**：用死信队列。`basicNack(requeue=false)` 让消息进入死信队列，后续人工处理或延迟重试。

## 边界情况和坑

### 坑1：Confirm 的 Ack 顺序和发送顺序不一致

**现象**：发送消息1、2、3，但收到的 Ack 顺序是 3、1、2。

**原因**：Broker 是**并行处理**的，先收到的消息不一定先处理完。

**影响**：如果对消息顺序有要求，Confirm 机制下顺序会被打乱。

**解决方案**：
- 接受乱序（大多数业务不需要严格顺序）
- 用业务层排序（比如消息带时间戳，消费者缓存后排序）
- 或者用单队列 + 单消费者（牺牲并行度）

### 坑2：持久化消息 + 内存告警，Broker 阻塞生产者

**现象**：RabbitMQ 内存使用率超过 `vm_memory_high_watermark`（默认 40%），生产者发送消息被阻塞（Connection 被 Block）。

**原因**：持久化消息要先写入内存，再刷盘。如果刷盘速度跟不上生产速度，内存会暴涨。RabbitMQ 的保护机制：阻塞生产者，让消费者先消费腾出空间。

**解决**：
- 增加 Broker 内存上限
- 增加消费者，加快消费速度
- 设置 `disk_free_limit`，保证磁盘有足够空间（刷盘需要）

### 坑3：Unacked 消息堆积，导致内存泄漏

**现象**：RabbitMQ 内存使用率持续上涨，但 QPS 不高。

**原因**：消费者 `basicAck` 调用不及时（或者忘了调用），消息一直卡在 Unacked 状态，占用内存。

**解决**：
- 检查消费者代码，确保 `basicAck` 在任何情况下都能执行
- 设置 `channel.basicQos(prefetchCount)`，限制 Unacked 消息数量

```java
// 限制：最多 100 条 Unacked 消息，超过后 Broker 不再推送
channel.basicQos(100);
```
