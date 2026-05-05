# RabbitMQ 架构与交换机

## 这个问题为什么存在？

Kafka 很强，但它不是万能的。

Kafka 的设计哲学是"高吞吐日志流"，它的消费模型是"消费者主动拉取（Pull）"，消息是"持久化日志"。这带来了两个问题：

1. **低延迟场景**：如果消息量很少，消费者 pull 会有延迟（要等下一次 poll）。Kafka 不适合"来一条就要立即处理"的场景。
2. **灵活路由**：Kafka 只有 Topic + Partition，路由能力很弱。如果要根据消息头、消息内容，把消息路由到不同的消费者，Kafka 做不到。

RabbitMQ 就是来解决这两个问题的：

- **Push 模型**：Broker 主动把消息推给消费者，延迟更低
- **Exchange 路由**：生产者不直接发消息到 Queue，而是发到 Exchange，由 Exchange 根据 Binding 规则决定路由到哪些 Queue

简单说：**Kafka 是"广播站"，RabbitMQ 是"智能邮局"**。

## 它是怎么解决问题的？

### 核心架构

```
生产者 → Exchange (交换机) → Binding (绑定规则) → Queue (队列) → 消费者
```

关键点：**生产者不直接发消息到 Queue**，而是发到 Exchange。Exchange 根据路由规则（Binding）把消息路由到一个或多个 Queue。

```
                    ┌─────────────┐
                    │  Exchange   │
                    │  (type: direct)   │
                    └──────┬──────┘
               ┌───────────┼───────────┐
          Binding      Binding      Binding
           key=A         key=B        key=C
               ↓             ↓             ↓
         ┌─────────┐  ┌─────────┐  ┌─────────┐
         │ Queue A  │  │ Queue B  │  │ Queue C  │
         │(消费者1) │  │(消费者2) │  │(消费者3) │
         └─────────┘  └─────────┘  └─────────┘
```

### Exchange 的四种类型

#### 1. Direct Exchange（直连交换机）

**路由规则**：消息的 `routingKey` 必须**完全匹配** Binding 的 `routingKey`。

```
Exchange (direct)
  Binding: Queue-A ↔ "order.create"
  Binding: Queue-B ↔ "order.pay"

消息1: routingKey="order.create"  → 路由到 Queue-A
消息2: routingKey="order.pay"     → 路由到 Queue-B
消息3: routingKey="order.cancel"  → 不路由到任何 Queue（丢弃或返回）
```

**适用场景**：点对点消息，需要精确路由。比如"订单创建"消息只给订单服务，"支付成功"消息只给支付服务。

#### 2. Topic Exchange（主题交换机）

**路由规则**：`routingKey` 支持通配符匹配。

```
*  → 匹配一个单词
###  → 匹配零个或多个单词

routingKey 格式：单词.单词.单词  (用 . 分隔)
```

```
Exchange (topic)
  Binding: Queue-A ↔ "order.*"         # 匹配 order.create, order.pay 等
  Binding: Queue-B ↔ "order.#"         # 匹配 order.create, order.create.xxx 等
  Binding: Queue-C ↔ "*.pay.*"         # 匹配任何中间是 pay 的三段 key

消息: "order.create"     → Queue-A, Queue-B
消息: "order.create.xxx" → Queue-B（只有 # 能匹配多段）
消息: "user.pay.success" → Queue-C
```

**适用场景**：需要模式匹配的消息路由。比如"所有订单相关事件"都路由到一个 Queue。

#### 3. Fanout Exchange（扇出交换机）

**路由规则**：**广播**，消息发送到所有绑定的 Queue，忽略 `routingKey`。

```
Exchange (fanout)
  Binding: Queue-A ↔ (无 key)
  Binding: Queue-B ↔ (无 key)
  Binding: Queue-C ↔ (无 key)

任何消息 → Queue-A, Queue-B, Queue-C 都收到
```

**适用场景**：事件广播。比如"用户注册成功"事件，需要通知积分服务、优惠券服务、短信服务，三者都要收到完整消息。

#### 4. Headers Exchange（头交换机）

**路由规则**：根据消息的 `headers`（而不是 routingKey）来匹配，支持 `x-match=all` 或 `x-match=any`。

```java
// 生产者
AMQP.BasicProperties props = new AMQP.BasicProperties.Builder()
    .headers(Map.of("type", "order", "priority", "high"))
    .build();

// Binding
// x-match=all: headers 里必须同时有 type=order 且 priority=high 才路由
// x-match=any: headers 里有任意一个匹配就路由
```

**适用场景**：路由逻辑复杂，用 routingKey 表达不清晰的场景。但**实际用得很少**，因为 Topic Exchange 基本能覆盖需求，且性能更好。

### 队列特性：Durable / Exclusive / Auto-delete

创建 Queue 时可以设置：

```java
channel.queueDeclare(
    "order_queue",
    true,   // durable: 持久化（Broker 重启后 Queue 还在）
    false,  // exclusive: 排他（只有当前连接能用，连接关闭后自动删除）
    false,  // autoDelete: 自动删除（最后一个消费者断开后删除 Queue）
    null    // arguments: 额外参数（如 TTL、最大长度）
);
```

**关键点**：`durable=true` 只保证 Queue 的元数据持久化，**不保证消息持久化**。消息要持久化，发送时要设 `deliveryMode=2`：

```java
AMQP.BasicProperties props = new AMQP.BasicProperties.Builder()
    .deliveryMode(2)  // 2=持久化, 1=非持久化
    .build();
channel.basicPublish("", "order_queue", props, message.getBytes());
```

### 源码关键路径：消息发送与路由

RabbitMQ 是用 **Erlang** 写的，但客户端（Java）的流程是：

```
ConnectionFactory.newConnection()
  → 建立 TCP 连接
  → 创建 AMQP Channel（虚拟连接，复用 TCP）
  → channel.basicPublish(exchange, routingKey, props, body)

Broker 端（Erlang 进程）：
  → Exchange 模块根据 type 和 Binding 规则计算路由结果
  → 把消息写入目标 Queue 的队列进程
  → 如果 Queue 设置了持久化，写入 Mnesia 数据库（RabbitMQ 的嵌入式存储）
  → 向生产者发送 Confirm（如果开启了 Publisher Confirm）
```

**关键设计**：RabbitMQ 的每个 Queue 是一个独立的 Erlang 进程，消息路由是"进程间消息传递"。这带来了好处（隔离性好）也带来了代价（跨进程拷贝开销）。

## 深入原理

### RabbitMQ vs Kafka

| 维度 | RabbitMQ | Kafka |
|------|----------|-------|
| 消费模型 | Push（Broker 推送给消费者） | Pull（消费者主动拉取） |
| 消息路由 | 灵活（4种 Exchange） | 弱（只有 Topic + Partition） |
| 消息留存 | 消费后删除（或 ACK 后删除） | 按时间留存（可重放） |
| 吞吐量 | 万级 TPS | 百万级 TPS |
| 延迟 | 低（Push 模型） | 较高（取决于 poll 间隔） |
| 顺序性 | Queue 内有序 | Partition 内有序 |
| 适用场景 | 业务消息、低延迟、灵活路由 | 日志、流处理、高吞吐 |

**本质区别**：RabbitMQ 是"消息中间件"（消息即投递，投递完就删除），Kafka 是"分布式日志流平台"（消息持久化，可重放）。

**为什么选 A 不选 B？**

- 选 RabbitMQ：业务系统内部通信，需要低延迟、灵活路由，吞吐量不需要特别大
- 选 Kafka：日志收集、流处理、大数据管道，吞吐量是首要考虑

### RabbitMQ Exchange 类型选择

| 需求 | 选哪个 Exchange |
|------|----------------|
| 点对点，精确匹配 | Direct |
| 按模式匹配（如"所有订单事件"） | Topic |
| 广播给所有消费者 | Fanout |
| 根据消息头路由（复杂条件） | Headers（但很少用） |

**经验**：80% 的场景用 Direct 或 Topic，15% 用 Fanout，Headers 基本不用。

## 正确使用方式

### 正确用法

**1. 开启 Publisher Confirm（生产端可靠投递）**

```java
// 开启 Confirm 机制
channel.confirmSelect();

// 异步等待 Confirm 结果
channel.addConfirmListener(new ConfirmListener() {
    @Override
    public void handleAck(long deliveryTag, boolean multiple) {
        // 消息成功到达 Broker
        outstandingConfirms.remove(deliveryTag);
    }
    @Override
    public void handleNack(long deliveryTag, boolean multiple) {
        // 消息丢失，需要重发
        Message msg = outstandingConfirms.get(deliveryTag);
        resend(msg);
    }
});

// 发送消息
channel.basicPublish("exchange", "routingKey", props, body);
```

**为什么正确**：默认情况下，生产者 `basicPublish()` 是**异步的**，Broker 收到后不会通知生产者。如果网络断了，消息可能丢了但生产者不知道。`Confirm` 机制让 Broker 确认收到后才算发送成功。

**2. 消费者：手动 Ack（避免消息丢失）**

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
            // 手动 Ack：告诉 Broker 消息处理完了，可以删除了
            channel.basicAck(envelope.getDeliveryTag(), false);
        } catch (Exception e) {
            // 处理失败：拒绝消息，重新入队（或扔到死信队列）
            channel.basicNack(envelope.getDeliveryTag(), false, true);
        }
    }
});
```

**为什么正确**：自动 Ack 模式（`autoAck=true`）下，Broker 把消息发出去就立即删除，不管消费者有没有处理成功。手动 Ack 保证"处理完才删除"。

**3. 使用 Dead Letter Exchange（死信交换机）处理失败消息**

```java
// 创建死信 Exchange 和 Queue
channel.exchangeDeclare("dlx_exchange", "direct");
channel.queueDeclare("dlx_queue", true, false, false, null);
channel.queueBind("dlx_queue", "dlx_exchange", "dlx_routing_key");

// 主队列设置死信参数
Map<String, Object> args = new HashMap<>();
args.put("x-dead-letter-exchange", "dlx_exchange");
args.put("x-dead-letter-routing-key", "dlx_routing_key");
args.put("x-message-ttl", 10000);  // 消息超时 10 秒后变成死信

channel.queueDeclare("order_queue", true, false, false, args);
```

**为什么正确**：消息处理失败时，不应直接丢弃，也不应无限重试（可能阻塞队列）。死信队列让失败消息有地方去，可以后续人工处理或延迟重试。

### 错误用法及后果

**错误1：消息不持久化，Broker 重启后消息全丢**

```java
// 错误：没设 deliveryMode=2
channel.basicPublish("exchange", "key", null, message.getBytes());
```

**后果**：Broker 重启后，所有在内存里没刷盘的消息全部丢失。

**修复**：发送时设 `deliveryMode=2`，且 Queue 要设 `durable=true`。

**错误2：prefetch 设置太大，消费者被压垮**

```java
// 错误：一次推送 1000 条，消费者处理不过来
channel.basicQos(1000);
```

**后果**：RabbitMQ 的 Push 模型会把消息主动推给消费者。如果 `prefetch` 太大，消费者本地缓冲区溢出，可能导致 OOM 或消息处理超时。

**修复**：设置合理的 `prefetch`（一般 10~100），配合手动 Ack 做**限流**：

```java
// 正确：每次只推送 10 条，Ack 后才推送下一批
channel.basicQos(10);
```

## 边界情况和坑

### 坑1：消息堆积，Queue 爆满

**触发场景**：消费者处理慢，生产者还在不断发，Queue 里的消息越来越多。

**后果**：RabbitMQ 会把内存里的消息换页到磁盘（Page Out），性能急剧下降。如果磁盘也满了，Broker 可能 OOM 崩溃。

**解决方案**：
- 增加消费者实例（扩容）
- 设置 Queue 最大长度（`x-max-length`），超出后丢弃或拒绝新消息
- 用 Dead Letter Queue 把旧消息转移走

```java
Map<String, Object> args = new HashMap<>();
args.put("x-max-length", 10000);          // 最多 10000 条
args.put("x-overflow", "reject-publish");  // 超出后拒绝新消息
```

### 坑2：Exchange 和 Queue 的 bindings 太多，性能下降

**场景**：一个 Fanout Exchange 绑定了 100 个 Queue，每条消息都要复制 100 份。

**后果**：Broker CPU 和内存压力变大，吞吐下降。

**修复**：评估是否真的需要 100 个 Queue，考虑合并或改用其他架构（比如让消费者自己去拉）。

### 坑3：集群模式下，队列只存在于单个节点

**重要**：RabbitMQ 的**队列是位置敏感的**——每个队列只存在于一个节点上（虽然元数据在所有节点同步）。

```
集群：Node-A, Node-B, Node-C
Queue-X 创建在 Node-A 上
→ 所有发往 Queue-X 的消息都到 Node-A
→ 如果 Node-A 宕机，Queue-X 不可用（即使 Node-B/C 还在）
```

**解决**：镜像队列（Mirrored Queue，旧版）或仲裁队列（Quorum Queue，新版）。

```java
// 仲裁队列（RabbitMQ 3.8+ 推荐）
Map<String, Object> args = new HashMap<>();
args.put("x-queue-type", "quorum");  // 仲裁队列，数据复制到多个节点
channel.queueDeclare("order_queue", true, false, false, args);
```
