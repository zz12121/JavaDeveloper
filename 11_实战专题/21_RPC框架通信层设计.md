# RPC 框架通信层设计

> RPC 框架通信层的核心是：**NIO Reactor 模型 + 自定义协议 + 连接池管理**。Netty 是最主流的实现选择，需要解决粘包拆包、心跳保活、断线重连等问题。

---

## 架构设计

```
┌─────────────────────────────────────────────────┐
│                Client 端                      │
│  │
│  ┌──────────┐    ┌──────────┐    ┌────────┐ │
│  │ Stub 代理 │───→│ 编解码    │───→│ 连接池  │ │
│  └──────────┘    └──────────┘    └───┬────┘ │
│               │
│               ▼
│           ┌────────┐
│           │  IO 线程│（Reactor 线程组）
│           └────────┘
└──────────────────────┬──────────────────────────┘
                       │ TCP 连接
                       ▼
┌─────────────────────────────────────────────────┐
│                Server 端                      │
│               │
│           ┌────────┐
│           │  IO 线程│（Boss 线程组）
│           └───┬────┘
│               │ 接受连接
│           ┌───▼────┐
│           │工作线程  │（Worker 线程组）
│           └───┬────┘
│               │
│           ┌───▼────┐    ┌──────────┐
│           │ 解码器  │───→│ 业务线程池│
│           └────────┘    └──────────┘
└─────────────────────────────────────────────────┘
```

---

## 场景 A：粘包拆包问题

### 现象
```
发送端发 2 个包：[Hello][World]
接收端可能收到：[HelloWo] [rld]  （拆包）
              或：[HelloWorld]        （粘包）
```
### 解决方案：自定义协议 + 长度字段
```
协议格式：
+--------+--------+--------+--------+--------+------------+
| 魔数(2B) | 版本(1B) | 类型(1B) |  长度(4B)  |    Body   |
+--------+--------+--------+--------+--------+------------+
```
```java
// Netty 实现：长度字段解码器（解决粘拆包）
public class RpcDecoder extends ByteToMessageDecoder {
    private static final int MAGIC = 0xCAFE;
    private static final int HEADER_SIZE = 8;  // 魔数2 + 版本1 + 类型1 + 长度4
    
    @Override
    protected void decode(ChannelHandlerContext ctx, ByteBuf in, 
                         List<Object> out) throws Exception {
        if (in.readableBytes() < HEADER_SIZE) return;
        
        in.markReaderIndex();
        
        int magic = in.readShort();
        if (magic != MAGIC) {
            throw new IllegalStateException("非法魔数: " + magic);
        }
        
        byte version = in.readByte();
        byte type = in.readByte();
        int length = in.readInt();
        
        if (in.readableBytes() < length) {
            in.resetReaderIndex();  // 数据不够，等待下次
            return;
        }
        
        byte[] body = new byte[length];
        in.readBytes(body);
        out.add(new RpcMessage(version, type, body));
    }
}

// Netty 内置方案（推荐）：LengthFieldBasedFrameDecoder
// 自动处理粘拆包，无需手写 decode
new LengthFieldBasedFrameDecoder(
    8 * 1024,   // 最大帧长度
    4,           // 长度字段偏移量（魔数2+版本1+类型1 = 4）
    4,           // 长度字段长度
    0,           // 长度调整（0 = 长度字段后面的就是 body）
    0            // 需要跳过的初始字节数
);
```

---

## 场景 B：心跳保活与断线重连

### 问题
```
NAT 超时（移动网络 5 分钟无数据 → 连接被运营商回收）
需要心跳保活；连接断开后需要自动重连
```
### 解决方案
```java
// 心跳处理器（IdleStateHandler 检测空闲）
public class HeartbeatHandler extends IdleStateHandler {
    // 读空闲 60s / 写空闲 30s / 全空闲 0（不检测）
    public HeartbeatHandler() {
        super(60, 30, 0, TimeUnit.SECONDS);
    }
    
    @Override
    protected void channelIdle(ChannelHandlerContext ctx, 
                              IdleStateEvent evt) {
        if (evt == IdleState.READER_IDLE) {
            // 60秒没收到数据 → 连接可能已死 → 关闭
            ctx.close();
        } else if (evt == IdleState.WRITER_IDLE) {
            // 30秒没写数据 → 发心跳
            ctx.writeAndFlush(new HeartbeatMessage());
        }
    }
}

// 断线重连（ChannelInboundHandlerAdapter）
public class ReconnectHandler extends ChannelInboundHandlerAdapter {
    private final String host;
    private final int port;
    private final Bootstrap bootstrap;
    
    @Override
    public void channelInactive(ChannelHandlerContext ctx) {
        // 连接断开 → 指数退避重连
        scheduleReconnect(ctx.channel().eventLoop());
    }
    
    private void scheduleReconnect(EventLoop eventLoop) {
        eventLoop.schedule(() -> {
            bootstrap.connect(host, port).addListener(future -> {
                if (!future.isSuccess()) {
                    // 连接失败 → 继续重试（指数退避）
                    scheduleReconnect(eventLoop);
                }
            });
        }, 5, TimeUnit.SECONDS);  // 首次 5 秒，后续可指数退避
    }
}
```

---

## 场景 C：连接池设计

### 设计要点
```
1. 连接复用（避免每次请求都建 TCP 连接）
2. 连接保活（心跳）
3. 连接数量控制（防止把对端打挂）
4. 故障节点自动摘除（熔断）
```
```java
@Component
public class RpcConnectionPool {
    private final Map<String, ConcurrentLinkedQueue<Channel>> pools 
        = new ConcurrentHashMap<>();
    private final Map<Channel, Long> lastActiveTime 
        = new ConcurrentHashMap<>();
    
    private static final int MAX_CONNECTIONS_PER_NODE = 10;
    private static final long IDLE_TIMEOUT = 60_000;  // 60秒空闲关闭
    
    public Channel getConnection(String host, int port) {
        String key = host + ":" + port;
        ConcurrentLinkedQueue<Channel> queue = pools.computeIfAbsent(
            key, k -> new ConcurrentLinkedQueue<>());
        
        // 1. 尝试复用空闲连接
        while (!queue.isEmpty()) {
            Channel ch = queue.poll();
            if (ch.isActive()) {
                lastActiveTime.put(ch, System.currentTimeMillis());
                return ch;
            }
            // 连接已断开，继续取下一个
        }
        
        // 2. 没有可用连接 → 新建（受限于最大连接数）
        if (queue.size() < MAX_CONNECTIONS_PER_NODE) {
            return createNewConnection(host, port, queue);
        }
        
        // 3. 超过最大连接数 → 等待（或抛异常）
        throw new RpcException("连接池已满: " + key);
    }
    
    public void returnConnection(Channel channel) {
        String key = channel.remoteAddress().toString();
        ConcurrentLinkedQueue<Channel> queue = pools.get(key);
        if (queue != null && channel.isActive()) {
            queue.offer(channel);
        }
    }
    
    // 定期清理空闲连接
    @Scheduled(fixedDelay = 30_000)
    public void cleanIdleConnections() {
        lastActiveTime.forEach((channel, lastTime) -> {
            if (System.currentTimeMillis() - lastTime > IDLE_TIMEOUT) {
                channel.close();
                lastActiveTime.remove(channel);
            }
        });
    }
}
```

---

## 排查 Checklist

```
□ （待补充）
```

---

## 涉及知识点

| 概念 | 所属域 | 关键点 |
|------|--------|--------|
| （待补充）| （待补充）| （待补充）|

---

## 我的实战笔记

-（待补充，项目中的真实经历）
