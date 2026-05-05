# RocketMQ 消息模型与高可靠

## 这个问题为什么存在？

RocketMQ 作为业务消息中间件，可靠性要求和 Kafka 不一样：

- Kafka 的可靠是"日志不丢"，允许极端情况下丢消息（比如 ISR 只剩 Leader 时）
- RocketMQ 的可靠是"**金融级不丢**"，因为它是给淘宝订单、支付宝交易用的

同时，RocketMQ 支持几个 Kafka 没有或很难用的特性：

1. **延迟消息**：订单 30 分钟未支付自动取消
2. **事务消息**：本地事务和消息发送原子性（扣库存 + 创建订单要么都成功，要么都失败）
3. **顺序消息**：订单创建 → 支付 → 发货，必须按顺序消费

这些特性背后的本质问题：**如何在分布式环境下，保证消息投递的时序性、原子性和不丢失？**

## 它是怎么解决问题的？

### 一、延迟消息（定时消息）

RocketMQ 的延迟消息基于**时间轮（Time Wheel）** 实现。

#### 为什么不用普通定时器？

```
普通方案：每个延迟消息一个 Timer 任务
  → 100 万个延迟消息 = 100 万个 Timer 任务
  → 内存爆炸，OOM
```

**时间轮** 把任务按"到期时间"放到不同的槽位（Slot）里：

```
时间轮（精度：1秒，共 18 个等级）：
  Level-1:  1s~2s      (2^1)
  Level-2:  2s~4s      (2^2)
  ...
  Level-18: 2^17s~2^18s（约 6.2 天）

消息到期时间 → 计算落在哪个 Level 的哪个 Slot
→ 到期后，消息从 Schedule Topic 转移到真正的 Topic
```

```java
// 发送延迟消息（订单 30 分钟后检查是否支付）
Message msg = new Message("order_event", "PAY_TIMEOUT", key, body);
// delayTimeLevel: 预设的延迟级别（1s/5s/10s/30s/1m/2m/.../2h）
msg.setDelayTimeLevel(16);  // 16 = 30 分钟（预设级别）
producer.send(msg);
```

**预设延迟级别**（不能自定义任意时间，除非改源码或用定时消息版）：

```
1: 1s      2: 5s       3: 10s     4: 30s
5: 1m      6: 2m       7: 3m      8: 4m
9: 5m      10: 6m      11: 7m     12: 8m
13: 9m     14: 10m     15: 20m    16: 30m
17: 1h     18: 2h
```

> RocketMQ 5.x 支持了**任意时间延迟**（用定时消息服务，不依赖预设级别）。

#### 实现原理（简化）

```
Producer 发送延迟消息
  → Broker 放到 SCHEDULE_TOPIC_XXXX（内部 Topic）
  → 时间轮定时扫描，到期后
  → 转移到真正的 Topic（order_event）
  → 消费者正常消费
```

### 二、事务消息（Transaction Message）

**问题场景**：

```
订单服务：
  1. 创建订单（写 DB）
  2. 发送"订单创建"消息（通知库存服务扣库存）
  → 如果 1 成功、2 失败 → 库存没扣，订单创建了（不一致）
  → 如果 1 失败、2 成功 → 库存扣了，订单没创建（不一致）
```

**需求**：步骤 1 和步骤 2 要有**原子性**（要么都成功，要么都失败）。

#### 事务消息流程

```
Producer 发送"半消息"（Half Message，对消费者不可见）
  → 执行本地事务（写 DB）
  → 根据本地事务结果，Commit 或 Rollback
      → Commit: 半消息变成正常消息，消费者可见
      → Rollback: 半消息删除，消费者看不到
  → 如果 Producer 提交/回滚失败了？
      → Broker 会**回查**（Check Transaction Status）
      → Producer 检查本地事务状态，重新提交/回滚
```

```java
// RocketMQ 事务消息写法
TransactionMQProducer producer = new TransactionMQProducer("group");
producer.setTransactionListener(new TransactionListener() {

    // 执行本地事务（和发消息在同一个事务里感知）
    @Override
    public LocalTransactionState executeLocalTransaction(
        Message msg, Object arg) {
        try {
            orderService.createOrder(arg);  // 本地事务（写 DB）
            return LocalTransactionState.COMMIT_MESSAGE;  // 成功 → 提交
        } catch (Exception e) {
            return LocalTransactionState.ROLLBACK_MESSAGE; // 失败 → 回滚
        }
    }

    // 回查（Broker 不确定事务结果时调用）
    @Override
    public LocalTransactionState checkLocalTransaction(MessageExt msg) {
        String orderId = msg.getKeys();
        Order order = orderService.queryOrder(orderId);
        if (order != null) {
            return LocalTransactionState.COMMIT_MESSAGE;
        } else {
            return LocalTransactionState.ROLLBACK_MESSAGE;
        }
    }
});

// 发送事务消息（先发半消息）
TransactionSendResult result = producer.sendMessageInTransaction(
    new Message("order_event", "CREATE", key, body),
    orderData  // 传给 executeLocalTransaction 的参数
);
```

**为什么叫"半消息"？** 消息发到 Broker 后，状态是"不可见"（消费者读不到），只有 Producer 提交后，才变成正常消息。**这保证了"本地事务成功才让消费者看到消息"**。

#### 和 Kafka 事务的区别

| 维度 | Kafka 事务 | RocketMQ 事务消息 |
|------|--------------|-------------------|
| 目的 | Kafka → Kafka 的原子写 | **本地事务 + 消息发送**的原子性 |
| 适用场景 | 流处理（Consume → Process → Produce 原子性） | 业务系统（DB 写 + MQ 发消息原子性） |
| 跨系统 | 不支持 | **支持**（DB 和 MQ 是两个系统） |

**本质区别**：Kafka 事务解决的是"**消息系统内部**的原子性"；RocketMQ 事务消息解决的是"**业务 DB 和 MQ**之间的原子性"——这才是业务系统真正需要的。

### 三、顺序消息

**问题**：同一个订单的"创建 → 支付 → 发货"三条消息，如果发到不同队列，消费者并行处理，可能"支付"比"创建"先被处理。

#### 实现方式

**发送端**：相同 Key（如 orderId）发到同一个队列（MessageQueueSelector）

```java
SendResult result = producer.send(msg, new MessageQueueSelector() {
    @Override
    public MessageQueue select(List<MessageQueue> mqs, Message msg, Object arg) {
        // arg = orderId，保证同订单到同一队列
        int index = Math.abs(arg.hashCode()) % mqs.size();
        return mqs.get(index);
    }
}, orderId);
```

**消费端**：用 `MessageListenerOrderly`（串行消费同一队列）

```java
consumer.registerMessageListener(new MessageListenerOrderly() {
    @Override
    public ConsumeOrderlyStatus consumeMessage(
        List<MessageExt> msgs, ConsumeOrderlyContext context) {
        for (MessageExt msg : msgs) {
            process(msg);  // 同一队列的消息按序到达
        }
        return ConsumeOrderlyStatus.SUCCESS;
    }
});
```

**代价**：顺序消息 = 队列内串行消费，**吞吐下降**。

### 源码关键路径：事务消息回查机制

```
Broker 端：
  收到半消息 → 存到 Half Topic（特殊内部 Topic）
  → 超时未收到 Commit/Rollback → 发起回查（向 Producer 发送 Check 请求）
  → Producer.checkLocalTransaction() 返回状态
  → 根据结果：转移到真正 Topic（Commit）或从 Half Topic 删除（Rollback）
```

**回查次数上限**：默认最多回查 **15 次**，还不确定就丢弃（或进死信队列）。

## 深入原理

### RocketMQ 延迟消息 vs RabbitMQ 延迟队列

| 维度 | RabbitMQ 延迟 | RocketMQ 延迟消息 |
|------|-----------------|---------------|
| 实现方式 | TTL + DLX（消息过期后进死信队列） | 时间轮（Time Wheel） |
| 精度 | 低（TTL 是固定值，不能精确到秒） | 高（预设级别，5.x 支持任意时间） |
| 管理成本 | 需要建多个 Queue + DLX | 开箱即用 |
| 适用场景 | 简单延迟（固定延迟，如 10s） | 电商订单超时（30min） |

**本质区别**：RabbitMQ 的延迟是"绕弯子"实现的（TTL + 死信），不精确；RocketMQ 的时间轮是**原生支持**，精度高、性能好。

### RocketMQ 事务消息 vs 分布式事务（2PC / TCC）

| 维度 | RocketMQ 事务消息 | 2PC（XA）/ TCC |
|------|-------------------|-----------------|
| 一致性保证 | 最终一致性 | 强一致性（2PC） |
| 性能 | 高（异步） | 低（同步阻塞） |
| 复杂度 | 低（只保证消息和本地事务原子性） | 高（需要所有参与者实现 Try/Confirm/Cancel） |
| 适用场景 | 消息驱动的业务（订单→库存） | 金融转账（要求强一致） |

**本质区别**：RocketMQ 事务消息是"**最终一致性**"方案，性能好，适合大部分互联网业务；2PC/TCC 是"**强一致性**"方案，性能差，只适合金融核心场景。

## 正确使用方式

### 正确用法

**1. 延迟消息做订单超时取消**

```java
// 订单创建后，发延迟消息（30 分钟后检查）
Message msg = new Message(
    "order_event",
    "PAY_TIMEOUT",
    orderId,
    orderId.getBytes()
);
msg.setDelayTimeLevel(16);  // 30 分钟
producer.send(msg);

// 消费者：检查订单是否已支付，未支付则取消
consumer.registerMessageListener((msgs, context) -> {
    for (MessageExt msg : msgs) {
        String orderId = msg.getKeys();
        Order order = orderService.query(orderId);
        if (order.getStatus() == OrderStatus.CREATED) {
            orderService.cancelOrder(orderId);  // 超时未支付，取消
        }
    }
    return ConsumeConcurrentlyStatus.CONSUME_SUCCESS;
});
```

**为什么正确**：延迟消息 + 消费者检查，是分布式系统做"超时取消"的标准做法。

**2. 事务消息保证 DB 和 MQ 一致性**

```java
// 正确做法：用事务消息，不用普通发送
TransactionMQProducer producer = ...;
producer.sendMessageInTransaction(
    new Message("inventory_event", "DEDUCT", key, body),
    orderData  // 本地事务参数
);
// executeLocalTransaction 里：同时写订单 DB 和感知消息发送结果
```

**为什么正确**：普通发送无法保证"DB 写成功但消息没发出去"或"消息发出去了但 DB 写失败"的问题。事务消息保证了原子性。

**3. 顺序消息：相同业务 Key 到同一队列**

```java
// 生产者
producer.send(msg, (mqs, msg, arg) -> {
    int index = Math.abs(arg.hashCode()) % mqs.size();
    return mqs.get(index);
}, orderId);  // arg = orderId

// 消费者（必须用 Orderly）
consumer.registerMessageListener(new MessageListenerOrderly() { ... });
```

**为什么正确**：`MessageListenerConcurrently`（并发消费）不管顺序，即使发到同一队列也会被并发处理。只有 `MessageListenerOrderly` 保证串行。

### 错误用法及后果

**错误1：事务消息的 `executeLocalTransaction` 里做 RPC 调用**

```java
@Override
public LocalTransactionState executeLocalTransaction(Message msg, Object arg) {
    orderService.createOrder(arg);   // 写 DB（快）
    inventoryService.deduct(arg);      // RPC 调用（慢，且可能失败）
    return COMMIT;
}
```

**后果**：`executeLocalTransaction` 超时（默认 6 秒），Broker 发起回查，但此时本地事务可能还没完成（RPC 还在跑），回查结果不确定。

**修复**：`executeLocalTransaction` **只做本地事务（写 DB）**，RPC 调用放到消息消费端处理。

**错误2：用普通消息做延迟，自己实现定时任务**

```java
// 错误：发普通消息，消费者收到后 sleep 30 分钟再处理
consumer.registerMessageListener((msgs, context) -> {
    Thread.sleep(30 * 60 * 1000);  // 睡 30 分钟！
    checkOrderStatus(msgs);
    return CONSUME_SUCCESS;
});
```

**后果**：消费者线程被占满（每条消息占一个线程 30 分钟），消费能力直接归零。

**修复**：用 RocketMQ 的延迟消息（原生支持，不占消费者线程）。

## 边界情况和坑

### 坑1：事务消息回查失败，消息最终丢弃

**现象**：Producer 宕机，Broker 回查时找不到 Producer，回查 15 次后消息被丢弃（或进死信队列）。

**后果**：本地事务其实成功了，但消息没提交，消费者收不到。

**缓解**：`checkLocalTransaction` 要能**独立检查本地事务状态**（查 DB），不能依赖内存状态。

### 坑2：延迟消息的预设级别不够用

**现象**：业务需要延迟 1 小时，但预设级别只有 2 小时（Level-18）。

**解决**：
- RocketMQ 5.x：用**定时消息**（支持任意时间）
- RocketMQ 4.x：改源码增加级别，或用**两个延迟消息嵌套**（不推荐，复杂）

### 坑3：顺序消息的某个队列消费卡住，整个队列阻塞

**现象**：某个队列里有一条消息一直消费失败（比如数据有问题），`MessageListenerOrderly` 会一直重试，**后续消息全部阻塞**。

**解决**：

```java
consumer.registerMessageListener(new MessageListenerOrderly() {
    @Override
    public ConsumeOrderlyStatus consumeMessage(
        List<MessageExt> msgs, ConsumeOrderlyContext context) {
        try {
            process(msgs);
            return SUCCESS;
        } catch (Exception e) {
            // 跳过这条消息（记录日志，人工处理）
            log.error("消息处理失败，跳过: {}", msgs.get(0).getKeys(), e);
            return SUCCESS;  // 或 SUSPEND_CURRENT_QUEUE_A_MOMENT（暂停一会再试）
        }
    }
});
```
