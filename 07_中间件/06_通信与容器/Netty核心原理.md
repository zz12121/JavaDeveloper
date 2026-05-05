# Netty 核心原理

## 这个问题为什么存在？

Java 原生 NIO 虽然提供了非阻塞 IO 的能力，但**直接用它写网络程序极其痛苦**：

```
你要自己处理：
  - OP_ACCEPT / OP_READ / OP_WRITE 各种事件类型
  - 半包/粘包问题（TCP 是流式协议，没有消息边界）
  - 空闲检测与心跳
  - 优雅关闭（半关闭状态）
  - Selector 空轮询 bug（JDK 著名 bug）
  - ByteBuffer 的 flip/rewind/clear 容易写错
  ...
```

Netty 把这些复杂性全部封装好了。你只需要写 **ChannelHandler** 处理业务逻辑，其他都由框架搞定。

> Netty 是 Java 领域网络编程的**事实标准**。Dubbo、RocketMQ、Elasticsearch、Spark、Cassandra 等知名项目的底层通信全部依赖 Netty。

---

## 它是怎么解决问题的？

### 一、Reactor 线程模型（Netty 的骨架）

Reactor 模式是 Netty 的核心设计思想：**I/O 多路复用 + 事件驱动**。

```
┌─────────────────────────────────────────────────────┐
│                   Reactor 模型演进                    │
│                                                       │
│ 1. 单 Reactor 单线程：                                │
│    Reactor → Accept + Read/Write + Business（全在一个线程）│
│    → 业务处理慢时阻塞所有连接                           │
│                                                       │
│ 2. 单 Reactor 多线程：                                │
│    Reactor → Accept + Read/Write                      │
│    Worker 线程池 → Business                           │
│    → 读写还是单线程瓶颈                                │
│                                                       │
│ 3. 主从 Reactor 多线程（Netty 用这个）：               │
│    Main Reactor Group  → 只处理 Accept（建立连接）     │
│    Sub Reactor Group   → 处理 Read/Write（多线程）     │
│    → 高性能的标准模型                                  │
└─────────────────────────────────────────────────────┘
```

Netty 的 `EventLoopGroup` 就是 Reactor 线程池的实现：

```java
// Netty 服务端标准写法
EventLoopGroup bossGroup = new NioEventLoopGroup(1);   // Main Reactor（1个线程足够）
EventLoopGroup workerGroup = new NioEventLoopGroup();  // Sub Reactor（默认 CPU核心数×2）

ServerBootstrap b = new ServerBootstrap();
b.group(bossGroup, workerGroup)
 .channel(NioServerSocketChannel.class)
 .childHandler(new ChannelInitializer<SocketChannel>() {
     @Override
     protected void initChannel(SocketChannel ch) {
         ChannelPipeline p = ch.pipeline();
         p.addLast(new IdleStateHandler(60, 0, 0));  // 心跳检测
         p.addLast(new MyBusinessHandler());           // 业务处理器
     }
 });
```

### 二、EventLoop 原理

EventLoop 是 Netty 最核心的组件，**一个 EventLoop = 一个线程 + 一个 Selector + 一个 TaskQueue**。

```
EventLoop 内部结构：

  ┌─────────────────────────────────┐
  │          EventLoop              │
  │  ┌──────────┐  ┌────────────┐  │
  │  │ Selector │  │ TaskQueue  │  │
  │  │ (IO多路  │  │ (待执行任务) │  │
  │  │  复用)   │  │            │  │
  │  └────┬─────┘  └─────┬──────┘  │
  │       │               │         │
  │       └───────┬───────┘         │
  │               ▼                  │
  │        单线程循环执行             │
  │  while (!terminated) {           │
  │    1. Selector.select()  → 处理IO事件  │
  │    2. processSelectedKeys()      │
  │    3. runAllTasks()      → 处理定时/异步任务 │
  │  }                              │
  └─────────────────────────────────┘
```

**关键设计**：

| 特性 | 说明 |
|------|------|
| 一个连接绑定一个 EventLoop | 连接建立后，所有 IO 事件都由同一个 EventLoop 处理，**无需同步** |
| EventLoop 内无锁 | 同一个 EventLoop 内的操作都在同一个线程，天然线程安全 |
| TaskQueue 支持异步任务 | `channel.writeAndFlush()` 底层就是把写操作放进 TaskQueue |
| 定时任务支持 | 内置 HashedWheelTimer，支持延迟任务（心跳、超时检测） |

```java
// EventLoop 执行异步任务（不阻塞 IO 线程）
channel.eventLoop().execute(() -> {
    // 这个任务会在 EventLoop 线程里执行
    // 适合轻量异步操作
});

// 定时任务
channel.eventLoop().schedule(() -> {
    // 5 秒后执行
}, 5, TimeUnit.SECONDS);
```

### 三、ChannelPipeline 与 ChannelHandler（责任链模式）

Netty 用**责任链模式**处理入站/出站事件，每个 Channel 都有一条 Pipeline，上面挂载多个 Handler。

```
数据流向示意（请求进来 → 响应出去）：

入站（Inbound）：                               出站（Outbound）：
  Socket → [解码器] → [业务Handler] → [编码器] → Socket
           ↑                               ↑
        ByteToMessage              MessageToByte
        Decoder                    Encoder

ChannelPipeline pipeline = ch.pipeline();
pipeline.addLast("decoder",  new LengthFieldBasedFrameDecoder(1024, 0, 4, 0, 4));  // 解码
pipeline.addLast("encoder",  new LengthFieldPrepender(4));                          // 编码
pipeline.addLast("idle",     new IdleStateHandler(60, 0, 0));                      // 心跳
pipeline.addLast("handler",  new MyBusinessHandler());                              // 业务
```

**Inbound vs Outbound**：

| 方向 | 触发场景 | 典型 Handler |
|------|----------|-------------|
| **Inbound**（入站） | 数据从 Socket 读进来 | 解码器、业务 Handler、空闲检测 |
| **Outbound**（出站） | 数据写到 Socket 出去 | 编码器、压缩、SSL |

```java
// 入站 Handler：处理读进来的数据
public class MyInboundHandler extends ChannelInboundHandlerAdapter {
    @Override
    public void channelRead(ChannelHandlerContext ctx, Object msg) {
        // 收到数据，处理业务
        // ctx.fireChannelRead(msg) → 传给下一个 Inbound Handler
    }
}

// 出站 Handler：处理写出去的数据
public class MyOutboundHandler extends ChannelOutboundHandlerAdapter {
    @Override
    public void write(ChannelHandlerContext ctx, Object msg, ChannelPromise promise) {
        // 在写之前做处理（如编码、压缩）
        ctx.write(msg, promise);  // 传给下一个 Outbound Handler
    }
}
```

**Handler 共享与不共享**：

```java
// 错误：@Sharable 的 Handler 里有状态（多个连接共享同一个 Handler 实例）
@ChannelHandler.Sharable
public class MyHandler extends ChannelInboundHandlerAdapter {
    private int count = 0;  // 危险！多个连接共享，并发问题
}

// 正确：无状态 Handler 可以 @Sharable（所有连接复用一个实例，节省内存）
@ChannelHandler.Sharable
public class SafeHandler extends SimpleChannelInboundHandler<String> {
    @Override
    protected void channelRead0(ChannelHandlerContext ctx, String msg) {
        ctx.writeAndFlush("echo: " + msg);  // 无状态，线程安全
    }
}
```

### 四、粘包与拆包（TCP 的经典问题）

**为什么会有粘包/拆包？** TCP 是**流式协议**，没有消息边界。发送方两次 send("Hello") + send("World")，接收方可能收到：

```
正常：  "Hello" "World"
粘包：  "HelloWorld"    （两次合并成一次）
拆包：  "Hel" "loWorld" （一次拆成两次）
```

**Netty 内置的拆包器**：

| 拆包器 | 原理 | 适用场景 |
|--------|------|----------|
| `FixedLengthFrameDecoder` | 按固定长度切割 | 消息长度固定 |
| `LineBasedFrameDecoder` | 按 `\n` 或 `\r\n` 切割 | 文本协议（HTTP、FTP） |
| `DelimiterBasedFrameDecoder` | 按自定义分隔符切割 | 自定义文本协议 |
| `LengthFieldBasedFrameDecoder` | 消息头指定消息体长度 | **二进制协议（推荐）** |
| `LengthFieldPrepender` | 自动在消息前写入长度字段 | 配合上面使用 |

```java
// 生产环境推荐：LengthFieldBasedFrameDecoder + LengthFieldPrepender
// 消息格式：[4字节长度][消息体]

ChannelPipeline p = ch.pipeline();

// 解码：读入时，根据前 4 字节长度字段截取消息体
// 参数：maxFrameLength=1MB, lengthFieldOffset=0, lengthFieldLength=4,
//       lengthAdjustment=0, initialBytesToStrip=4（去掉长度字段本身）
p.addLast(new LengthFieldBasedFrameDecoder(1024 * 1024, 0, 4, 0, 4));

// 编码：写出时，自动在消息前写入 4 字节长度
p.addLast(new LengthFieldPrepender(4));

// 自定义编解码器
p.addLast(new MyMessageDecoder());   // ByteBuf → 业务对象
p.addLast(new MyMessageEncoder());   // 业务对象 → ByteBuf
p.addLast(new MyBusinessHandler());  // 业务处理
```

### 五、ByteBuf（比 ByteBuffer 好在哪）

```java
// JDK ByteBuffer 的痛点：
ByteBuffer buf = ByteBuffer.allocate(1024);
buf.put(data);
buf.flip();       // 忘了 flip → 读到错误数据
buf.compact();    // 忘了 compact → 空间不够
// 只有一个指针（position），读写切换要手动 flip
// 没有引用计数 → 不知道什么时候可以释放

// Netty ByteBuf 的改进：
ByteBuf buf = Unpooled.buffer(1024);
buf.writeBytes(data);
// 两个指针：读指针 readerIndex + 写指针 writerIndex
// 读写不需要 flip！
// 引用计数：ReferenceCountUtil.release(buf) → 明确释放
```

**ByteBuf 两种模式**：

```
堆内存 ByteBuf（HeapByteBuf）：
  → 创建和销毁快，JVM 管理
  → 适合：消息编解码（业务处理）

直接内存 ByteBuf（DirectByteBuf）：
  → 创建和销毁慢（涉及 OS 调用），但读写快（零拷贝）
  → 适合：网络 IO（Socket 读写）

池化 ByteBuf（PooledByteBuf）：
  → 用对象池复用 ByteBuf，减少 GC 压力
  → Netty 4.1+ 默认使用池化
```

**ByteBuf 引用计数（重要）**：

```java
// ByteBuf 采用引用计数管理内存
// 创建时 refCnt=1，release() 时 refCnt-1，refCnt=0 时真正释放

// Inbound Handler：处理完要释放！
@Override
public void channelRead(ChannelHandlerContext ctx, Object msg) {
    try {
        ByteBuf buf = (ByteBuf) msg;
        byte[] data = new byte[buf.readableBytes()];
        buf.readBytes(data);
        // 处理 data...
    } finally {
        ReferenceCountUtil.release(msg);  // 必须释放！
    }
}

// 更简单：继承 SimpleChannelInboundHandler（自动释放）
public class MyHandler extends SimpleChannelInboundHandler<ByteBuf> {
    @Override
    protected void channelRead0(ChannelHandlerContext ctx, ByteBuf msg) {
        // 处理完自动释放，不需要手动 release
    }
}

// Outbound Handler：write 时不能提前释放（底层还没发送）
```

### 六、零拷贝

Netty 的"零拷贝"指的是**减少数据在用户空间和内核空间之间的拷贝次数**，不是真正零拷贝。

```
传统方式（4 次拷贝）：
  磁盘 → 内核缓冲区 → 用户缓冲区 → Socket 缓冲区 → 网卡

sendfile 零拷贝（2 次拷贝）：
  磁盘 → 内核缓冲区 → 网卡
  （跳过用户空间）

Netty 零拷贝的三种方式：
```

```java
// 1. CompositeByteBuf：多个 ByteBuf 合并，不拷贝数据
CompositeByteBuf composite = Unpooled.compositeBuffer();
composite.addComponents(true, headerBuf, bodyBuf);
// header 和 body 在物理上还是两个独立的内存块
// 但对外看起来是一个连续的 ByteBuf

// 2. FileRegion：文件传输用 sendfile() 系统调用
FileRegion region = new DefaultFileRegion(fileChannel, 0, fileLength);
channel.writeAndFlush(region);
// 底层调用 sendfile()，数据不经过用户空间

// 3. ByteBuf.slice()：切片，共享底层内存
ByteBuf original = Unpooled.copiedBuffer("Hello World", CharsetUtil.UTF_8);
ByteBuf slice = original.slice(0, 5);  // "Hello"，共享底层内存，不拷贝
```

### 七、心跳机制

```
为什么需要心跳？
  → TCP 连接没有"自动感知断开"的能力
  → 网络异常（拔网线、防火墙超时）→ 连接已死，但双方不知道
  → 半开连接堆积 → 资源泄漏

Netty IdleStateHandler：
  → 读空闲超时 → 触发 IdleStateEvent.READER_IDLE
  → 写空闲超时 → 触发 IdleStateEvent.WRITER_IDLE
  → 全空闲超时 → 触发 IdleStateEvent.ALL_IDLE
```

```java
// 服务端：60 秒没读到数据 → 认为客户端挂了，关闭连接
pipeline.addLast(new IdleStateHandler(60, 0, 0));

pipeline.addLast(new ChannelInboundHandlerAdapter() {
    @Override
    public void userEventTriggered(ChannelHandlerContext ctx, Object evt) {
        if (evt instanceof IdleStateEvent) {
            IdleStateEvent event = (IdleStateEvent) evt;
            if (event.state() == IdleStateEvent.READER_IDLE_STATE) {
                // 60 秒没收到数据，关闭连接
                ctx.close();
            }
        }
    }
});

// 客户端：每 30 秒发一次心跳包
pipeline.addLast(new IdleStateHandler(0, 30, 0));

pipeline.addLast(new ChannelInboundHandlerAdapter() {
    @Override
    public void userEventTriggered(ChannelHandlerContext ctx, Object evt) {
        if (evt instanceof IdleStateEvent) {
            if (event.state() == IdleStateEvent.WRITER_IDLE_STATE) {
                // 30 秒没写过数据，发心跳包
                ctx.writeAndFlush(new HeartbeatMessage());
            }
        }
    }
});
```

### 八、空轮询 Bug（JDK NIO 的著名问题）

```
问题现象：
  Selector.select() 不阻塞，立即返回 0（没有就绪事件但返回了）
  → while 循环疯狂空转
  → CPU 100%

原因：
  JDK NIO 的 epoll 实现有 bug（Linux）
  当某个 Channel 被从 Selector 取消注册后，epoll 的内核事件队列
  没有正确清理，导致 Selector 唤醒但无事件

Netty 的解决方案：
  → 检测到连续 N 次 select 返回 0（N 默认 512）
  → 自动重建 Selector
  → 把原来 Selector 上注册的所有 Channel 重新注册到新 Selector
```

```java
// Netty 源码中的处理逻辑（简化）
long selectCnt = 0;
long currentTimeNanos = System.nanoTime();

for (;;) {
    long timeoutMillis = selectTimeoutMillis;
    if (timeoutMillis <= 0) {
        selectCnt++;  // 记录空轮询次数
        if (selectCnt >= SELECT_CNT_THRESHOLD) {  // 默认 512
            // 重建 Selector
            selector = selectRebuildSelector(selectCnt);
            selectCnt = 0;
        }
    }
    int selectedKeys = selector.select(timeoutMillis);
    if (selectedKeys > 0) {
        selectCnt = 0;  // 有事件，重置计数
    }
    // ...
}
```

**面试要点**：这个问题是生产环境直接用原生 NIO 的一大风险，Netty 内部已经修复了。

### 九、Netty 线程模型最佳实践

```
原则1：EventLoop 线程里不要做慢操作
  → IO 线程是宝贵资源，被阻塞 = 所有连接卡住
  → 数据库查询、文件操作、复杂计算 → 放到业务线程池

原则2：ChannelHandler 如果无状态 → 标记 @Sharable，复用实例
  → 有状态 → 每个 Channel 创建新实例

原则3：writeAndFlush 是异步的
  → 返回 ChannelFuture，通过 listener 获取结果
  → 不要在 EventLoop 线程里 await()（会阻塞）

原则4：ByteBuf 要正确释放
  → Inbound：处理完 release
  → Outbound：write 之后不要 release（底层发送完才释放）
  → 用 SimpleChannelInboundHandler 最省心
```

```java
// 最佳实践：EventLoop 处理 IO，业务线程池处理业务
ExecutorService bizPool = Executors.newFixedThreadPool(16);

public class MyHandler extends SimpleChannelInboundHandler<Request> {
    @Override
    protected void channelRead0(ChannelHandlerContext ctx, Request req) {
        // 把业务操作提交到业务线程池
        bizPool.submit(() -> {
            Response resp = orderService.process(req);

            // writeAndFlush 回到 EventLoop 线程执行
            ctx.writeAndFlush(resp).addListener(future -> {
                if (!future.isSuccess()) {
                    // 异步处理发送失败
                    log.error("发送失败", future.cause());
                }
            });
        });
    }
}
```

---

## 深入原理

### Netty vs 原生 NIO vs Mina

| 维度 | 原生 NIO | Netty | Mina |
|------|----------|-------|-------|
| 编程复杂度 | 高（半包/粘包/空闲检测全自己写） | 低（封装好） | 中 |
| 性能 | 高（但很难写对） | 高（经过大量生产验证） | 中 |
| 社区活跃度 | N/A（JDK 维护） | 非常活跃 | 不活跃 |
| 内存管理 | ByteBuffer（无引用计数） | ByteBuf（引用计数 + 池化） | ByteBuffer |
| 线程模型 | 自己实现 | 主从 Reactor（开箱即用） | 单线程 Reactor |
| 适用场景 | 学习 NIO 原理 | **生产环境网络编程** | 旧项目 |

**本质区别**：Netty 是"框架"（规定了你怎么写，帮你处理了所有脏活累活），原生 NIO 是"API"（你怎么写都行，但容易写错）。Mina 已停止维护，不推荐新项目使用。

### Netty vs Tomcat

| 维度 | Netty | Tomcat |
|------|-------|--------|
| 定位 | 通用网络框架 | Web 容器（Servlet） |
| 协议支持 | 任意协议（TCP/UDP/HTTP/自定义） | 主要 HTTP |
| 线程模型 | 主从 Reactor（高性能） | 一个连接一个线程（较重） |
| 适用场景 | RPC、消息队列、游戏服务器 | Web 应用、REST API |

---

## 边界情况和坑

### 坑1：ByteBuf 内存泄漏

**现象**：服务运行一段时间后内存持续上涨，最终 OOM。

**原因**：ByteBuf 忘了 release，或者继承了 `ChannelInboundHandlerAdapter` 而不是 `SimpleChannelInboundHandler`。

**排查**：启动时加 JVM 参数 `-Dio.netty.leakDetection.level=paranoid`，日志会报告泄漏的 ByteBuf 创建位置。

### 坑2：EventLoop 被阻塞

**现象**：所有连接响应变慢，甚至超时。

**原因**：某个 Handler 的 `channelRead` 里做了数据库查询、文件 IO 等慢操作，阻塞了 EventLoop 线程。

**排查**：看线程 dump，如果 EventLoop 线程栈停在业务代码 → 就是这个问题。

**修复**：把慢操作提交到业务线程池。

### 坑3：ChannelFuture 不会自动传播异常

```java
// 错误：writeAndFlush 失败了你不知道
ctx.writeAndFlush(response);  // 异步操作，失败不会抛异常

// 正确：监听结果
ctx.writeAndFlush(response).addListener(future -> {
    if (!future.isSuccess()) {
        future.cause().printStackTrace();
    }
});
```

### 坑4：@Sharable 的 Handler 里用了成员变量

```java
// 错误：多个 Channel 共享同一个 Handler 实例，count 并发问题
@ChannelHandler.Sharable
public class BadHandler extends ChannelInboundHandlerAdapter {
    private int count = 0;  // 多线程并发修改，结果不对
    @Override
    public void channelRead(ChannelHandlerContext ctx, Object msg) {
        count++;
        ctx.fireChannelRead(msg);
    }
}
```

---

**关联文档**：
- [[07_中间件/00_概览|常见中间件综合]]（ZooKeeper/雪花算法/中间件对比总览）
- [[07_中间件/05_RPC框架/Dubbo核心原理]]（Dubbo 底层通信依赖 Netty）
- [[10_计算机基础/02_操作系统/IO模型]]（Java IO 模型基础）
