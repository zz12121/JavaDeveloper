# 千万PV API网关通信层设计

> 通信层核心：NIO多路复用 + HTTP/2多路复用 + TLS加速 + 连接复用。

---

## 网关通信层架构

```
客户端请求
   │
   ▼
┌─────────┐  TCP/TLS ┌─────────┐  NIO多路复用 ┌─────────┐
│  客户端  │ ───────→ │  Netty  │ ───────────→ │  业务线程池 │
│  App/Web │          │  Boss/Worker │           │  异步处理  │
└─────────┘          └────┬────┘             └────┬────┘
                          │                        │
       ┌──────────────────┼────────────────────────┤
       │                  │                        │
       ▼                  ▼                        ▼
┌───────────┐      ┌───────────┐          ┌───────────┐
│ HTTP/2    │      │ TLS优化   │          │ 连接池    │
│ 多路复用  │      │ Session复用│          │ 后端连接复用│
└───────────┘      └───────────┘          └───────────┘
```

---

## 场景 A：Netty NIO多路复用

### 现象

```
千万级QPS下，网关CPU使用率100%，但实际处理能力只有5万/s
大量线程阻塞在IO等待上，线程数膨胀到几千
内存占用过高，频繁Full GC
```

### 根因

```
使用传统BIO（阻塞IO），每个连接占一个线程
未利用操作系统NIO多路复用能力，单机并发上限低
线程上下文切换开销吃掉大部分CPU资源
```

### 解决方案

```java
/**
 * Netty高性能网关通信层实现（基于NIO多路复用）
 * 
 * 核心原理：
 * - 一个Selector线程可以管理数万个连接的IO事件（epoll/kqueue）
 * - IO就绪事件触发后，才分配线程处理数据
 * - 非阻塞读写，零拷贝技术减少内存复制
 */
public class GatewayServer {

    private static final int BOSS_THREADS = 1;  // Boss只需1个
    // Worker线程数 = CPU核心数 * 2（IO密集型场景最优配置）
    private static final int WORKER_THREADS = Runtime.getRuntime().availableProcessors() * 2;
    
    public void start(int port) {
        EventLoopGroup bossGroup = new NioEventLoopGroup(BOSS_THREADS);
        EventLoopGroup workerGroup = new NioEventLoopGroup(WORKER_THREADS);

        try {
            ServerBootstrap bootstrap = new ServerBootstrap();
            bootstrap.group(bossGroup, workerGroup)
                .channel(NioServerSocketChannel.class)
                
                // 关键参数1：全连接队列长度（防止SYN Flood打满队列）
                .option(ChannelOption.SO_BACKLOG, 65535)
                .option(ChannelOption.SO_REUSEADDR, true)
                
                // 关键参数2：TCP参数调优
                .childOption(ChannelOption.TCP_NODELAY, true)     // 关闭Nagle算法
                .childOption(ChannelOption.SO_KEEPALIVE, false)   // 网关自己管心跳
                .childOption(ChannelOption.ALLOCATOR, PooledByteBufAllocator.DEFAULT)  // 池化内存分配
                
                // 关键参数3：接收/发送缓冲区（根据MTU和消息大小调整）
                .childOption(ChannelOption.SO_RCVBUF, 128 * 1024)  // 接收缓冲128KB
                .childOption(ChannelOption.SO_SNDBUF, 256 * 1024)  // 发送缓冲256KB
                
                .childHandler(new ChannelInitializer<SocketChannel>() {
                    @Override
                    protected void initChannel(SocketChannel ch) {
                        ChannelPipeline pipeline = ch.pipeline();
                        
                        // HTTP编解码器（Netty内置高性能编解码）
                        pipeline.addLast("codec", new HttpServerCodec());
                        
                        // HTTP聚合器（将HTTP消息片段聚合成完整消息）
                        pipeline.addLast("aggregator", new HttpObjectAggregator(64 * 1024));
                        
                        // 业务处理器（异步非阻塞）
                        pipeline.addLast("gatewayHandler", new GatewayHandler());
                    }
                });

            ChannelFuture future = bootstrap.bind(port).sync();
            log.info("API网关启动成功, port={}, workerThreads={}", port, WORKER_THREADS);
            future.channel().closeFuture().sync();
            
        } finally {
            bossGroup.shutdownGracefully();
            workerGroup.shutdownGracefully();
        }
    }
}
```

**NIO关键点**：
- `NioEventLoop`底层用Linux epoll（或BSD kqueue）实现真正的多路复用
- 单个Worker线程可管理10万+连接的IO事件，线程数与连接数解耦
- `PooledByteBufAllocator.DEFAULT`减少GC压力，避免频繁创建/销毁Buffer

---

## 场景 B：HTTP/2多路复用优化

### 现象

```
HTTP/1.1每个请求独占一个TCP连接，头部冗余大
页面加载需要发起几十个串行请求，总耗时高
队头阻塞问题：前一个请求慢会阻塞后续所有请求
```

### 根因

```
HTTP/1.1无多路复用能力，必须排队等待响应
头部无压缩，重复字段浪费带宽
无法服务端主动推送资源
```

### 解决方案

```
HTTP/2 vs HTTP/1.1对比：

| 特性 | HTTP/1.1 | HTTP/2 |
|------|----------|--------|
| 连接模型 | 1连接1请求 | 1连接多请求（多路复用） |
| 头部压缩 | 无 | HPACK算法压缩 |
| 服务端推送 | 不支持 | 支持 |
| 二进制协议 | 文本 | 二进制（解析更快） |

网关场景最佳实践：
- 客户端↔网关：支持HTTP/2（浏览器原生支持）
- 网关↔后端：保持HTTP/1.1或gRPC（后端兼容性考虑）
```

```java
/**
 * HTTP/2服务器端配置
 */
public class Http2Gateway {

    public void startHttp2(int port) throws Exception {
        SslContext sslCtx = SslContextBuilder.forServer(
            new File("cert.pem"), 
            new File("key.pem")
        ).protocols("TLSv1.3", "TLSv1.2")
         .ciphers(Http2SecurityUtil.CIPHERS)  // HTTP/2要求的加密套件
         .build();

        ServerBootstrap bootstrap = new ServerBootstrap();
        
        // 使用HTTP/2专用的NioServerSocketChannel
        bootstrap.channel(NioServerSocketChannel.class);
        bootstrap.childHandler(new ChannelInitializer<SocketChannel>() {
            @Override
            protected void initChannel(SocketChannel ch) {
                ch.pipeline().addLast(sslCtx.newHandler(ch.alloc()));
                
                // HTTP/2协商：客户端发送Upgrade请求时自动升级
                ch.pipeline().addLast(new Http2FrameCodecBuilder()
                    .initialSettings(Http2Settings.defaultSettings()
                        .maxConcurrentStreams(1000)  // 最大并发流数1000
                        .initialWindowSize(1048576))  // 初始窗口1MB
                    .build());
                    
                ch.pipeline().addLast(new Http2MultiplexHandler(
                    new Http2RequestHandler()  // 处理HTTP/2请求
                ));
            }
        });

        bootstrap.bind(port).sync();
    }
}
```

**HTTP/2关键**：
- `maxConcurrentStreams=1000`允许单个连接同时处理1000个请求
- HPACK头部压缩可将头部体积减小80%+
- 必须配合TLS（HTTP/2 over TLS即H2协议）

---

## 场景 C：TLS握手优化（Session复用）

### 现象

```
TLS握手每次都要完整的RTT往返（1-2次RTT），延迟高
HTTPS站点首字节时间（TTFB）比HTTP慢200ms+
高并发时CPU被TLS加解密操作消耗殆尽
```

### 根因

```
每次新连接都做完整TLS握手，未复用Session
未启用Session Ticket/Cache等加速机制
证书链过长，增加握手数据量
```

### 解决方案

```
TLS握手完整流程（无优化）：
ClientHello → ServerHello + Certificate + ServerKeyExchange → ClientKeyExchange → Finished
共需 2 RTT（约40-200ms，取决于网络距离）

优化方案（按效果排序）：

1. TLS Session Ticket（推荐）：首次握手后发Ticket给客户端，
   后续连接直接带Ticket跳过握手，节省 1-2 RTT
   
2. TLS Session Cache（服务端缓存）：服务端保存Session信息，
   ClientHello带SessionID直接恢复，节省 1-2 RTT
   
3. OCSP Stapling：服务端主动提供证书吊销状态，
   避免客户端额外查询OCSP服务器

4. 证书链精简：只包含必要中间证书，减少传输数据量
```

```java
// Netty TLS Session复用配置
SslContext sslCtx = SslContextBuilder.forServer(certFile, keyFile)
    // 启用Session Ticket（客户端可复用加密票据）
    .sessionTicketEnabled(true)
    // Session超时时间（越长复用率越高，安全性越低）
    .sessionTimeout(36000)  // 10小时
    
    // 协议版本选择（优先TLS 1.3，握手仅需1 RTT！）
    .protocols("TLSv1.3", "TLSv1.2")
    
    // 加密套件优化（选用ECDHE+AES-GCM，兼顾性能和安全）
    .ciphers(Arrays.asList(
        "TLS_AES_256_GCM_SHA384",      // TLS 1.3首选
        "TLS_CHACHA20_POLY1305_SHA256", // 移动端友好（无AES硬件加速）
        "TLS_ECDHE_ECDSA_WITH_AES_256_GCM_SHA384"  // TLS 1.2兼容
    ))
    .build();
```

**TLS优化关键**：
- **TLS 1.3是最大优化**：握手从2RTT降到1RTT（性能提升50%）
- `sessionTicketEnabled=true`对短连接场景提升最明显（如API网关）
- 移动端设备优先CHACHA20-POLY1305（ARM架构AES硬件加速弱于x86）

---

## 场景 D：连接池管理与复用

### 现象

```
网关到后端的连接数爆炸（每请求一连接）
后端服务连接数被打满，拒绝新的连接
频繁建立/销毁连接导致延迟波动大
```

### 根因

```
无连接池，每次转发都新建TCP连接
未做长连接保活，连接空闲后被关闭
连接池参数不合理，高峰期不够、低谷期浪费
```

### 解决方案

```java
/**
 * 网关到后端的HTTP连接池（基于Netty HttpClient）
 * 核心目标：连接复用 + 动态调整 + 健康检查
 */
public class BackendConnectionPool {

    private final PoolMap<String, HttpClient> poolMap;
    
    public BackendConnectionPool() {
        // 1. 创建连接池（按后端服务地址分组）
        poolMap = new ConsistentHashPoolMap<>(new PoolFactory());
    }

    /**
     * 从连接池获取连接（或创建新连接）
     */
    public Future<Response> sendRequest(String backendHost, Request request) {
        HttpClient client = poolMap.get(backendHost);
        return client.send(request);  // 内部自动复用连接
    }

    /** 
     * 连接池工厂：定义每个后端服务的连接池参数
     */
    private static class PoolFactory implements PoolMapFactory<HttpClient> {
        @Override
        public HttpClient createMap(PoolKey key) {
            return HttpClient.create()
                // 关键配置1：最大连接数（按后端服务规模设定）
                .option(ChannelOption.SO_KEEPALIVE, true)  // 长连接
                
                // 关键配置2：连接池大小限制
                .option(ChannelOption.CONNECT_TIMEOUT_MILLIS, 3000)
                
                // 关键配置3：响应超时（防止后端卡死拖垮网关）
                .responseTimeout(Duration.ofSeconds(30))
                
                // 关键配置4：连接空闲回收策略
                .poolResources(ConnectionProvider.builder("backend-pool")
                    .maxConnections(500)              // 每个后端最多500连接
                    .maxIdleTime(Duration.ofMinutes(5))  // 空闲5分钟后回收
                    .maxLifeTime(Duration.ofHours(2))    // 最长存活2小时
                    .pendingAcquireTimeout(Duration.ofMillis(1000))  // 获取超时1秒
                    .evictInBackground(Duration.ofSeconds(60))       // 每60秒后台清理
                    .build())
                .wiretap(true)  // 开启日志（生产环境建议关闭）
                .compress(true);  // 开启Gzip压缩
        }
    }

    /**
     * 定期健康检查：剔除不健康的连接
     */
    @Scheduled(fixedRate = 60_000)
    public void healthCheck() {
        for (Map.Entry<String, HttpClient> entry : poolMap.asMap().entrySet()) {
            String host = entry.getKey();
            HttpClient client = entry.getValue();
            
            try {
                // 发送健康检查探针
                Response healthResp = client.get()
                    .uri("/healthz")
                    .response()
                    .block(Duration.ofSeconds(5));
                
                if (healthResp == null || healthResp.statusCode() != 200) {
                    log.warn("后端{}健康检查失败，标记为不可用", host);
                    markUnhealthy(host);
                }
            } catch (Exception e) {
                log.error("后端{}健康检查异常: {}", host, e.getMessage());
            }
        }
    }
}
```

```
连接池参数参考值（千万PV级别）：

参数                      推荐值              说明
maxConnections            200~500/每后端      取决于后端实例数
maxIdleTime               5分钟               空闲过久释放
maxLifeTime               2小时               防止长时间连接状态异常
pendingAcquireTimeout     1000ms             获取超时快速失败，避免堆积
keepAliveInterval         30s                TCP Keepalive探测间隔
```

**连接池关键**：
- 每个后端服务独立连接池，避免互相影响
- `pendingAcquireTimeout`必须设置，否则获取不到连接时会无限等待
- 定期健康检查+后台清理，及时剔除坏连接

---

## 涉及知识点

| 概念 | 所属域 | 关键点 |
|------|--------|--------|
| NIO多路复用 | 04_并发编程/02_NIO | epoll/kqueue/Selector |
| HTTP/2多路复用 | 07_分布式与架构/04_远程调用 | HPACK/流控制/服务端推送 |
| TLS优化 | 08_安全/01_网络安全 | Session Ticket/TLS 1.3/OCSP Stapling |
| 连接池设计 | 06_中间件/01_JDBC/02_Redis | 长连接复用/动态调整/健康检查 |

---

## 排查 Checklist

```
□ 用NIO了吗？ → Netty NioEventLoop替代BIO
□ Worker线程数合理吗？ → CPU核数*2，不要超过32
□ 支持HTTP/2吗？ → 客户侧开启多路复用，减少连接数
□ TLS Session复用开了吗？ → sessionTicketEnabled=true
□ 用TLS 1.3了吗？ → 握手1 RTT，性能翻倍
□ 有连接池吗？ → 后端连接必须复用，禁止每次新建
□ 连接池有超时保护吗？ → pendingAcquireTimeout ≤ 1s
□ 内存用了池化吗？ → PooledByteBufAllocator降低GC压力
□ TCP参数调优了没？ → TCP_NODELAY=true / SO_REUSEADDR=true
□ 有连接健康检查吗？ → 定时探活剔除坏连接
```

---

## 我的实战笔记

-（待补充，项目中的真实经历）
