# 百万QPS API网关设计

> API网关核心：NIO通信 + 限流 + 鉴权 + 熔断 + 协议转换。

---

## 百万QPS API网关全链路架构

```
客户端请求
   │
   ▼
┌─────────┐  SSL卸载  ┌─────────────────┐
│  LVS    │ ──────→  │  API 网关集群    │
│  负载均衡 │          │  (Netty+NIO)    │
└─────────┘          └────────┬────────┘
                              │
            ┌─────────────────┼─────────────────┐
            │                 │                 │
            ▼                 ▼                 ▼
    ┌────────────┐    ┌────────────┐    ┌────────────┐
    │  插件链    │    │  限流熔断  │    │  协议转换  │
    │ (鉴权/日志)│    │  (令牌桶)  │    │ (HTTP→Dubbo)│
    └─────┬─────┘    └─────┬─────┘    └─────┬─────┘
          │                 │                 │
          └─────────────────┼─────────────────┘
                            │
            ┌───────────────┼───────────────┐
            │               │               │
            ▼               ▼               ▼
    ┌────────────┐  ┌────────────┐  ┌────────────┐
    │  后端服务1 │  │  后端服务2 │  │  后端服务3 │
    │  (HTTP)    │  │  (Dubbo)   │  │  (gRPC)    │
    └────────────┘  └────────────┘  └────────────┘
```

---

## 场景 A：Netty通信层

### 现象

```
Netty IO线程阻塞，网关平均延迟从5ms升至500ms以上
连接数达到1万时，新请求开始超时，TCP连接失败率上升
高并发下IO线程CPU使用率100%，无法处理新请求
```

### 根因分析

Netty采用Reactor模型，IO线程（EventLoop）负责处理所有网络读写事件。若IO线程中执行耗时操作（如同步调用DB、复杂业务逻辑计算），会导致IO线程阻塞，无法处理其他连接的请求。默认IO线程数为CPU核心数*2，百万QPS场景下16核服务器仅32个IO线程，无法支撑大量连接的读写调度。此外，连接管理不当（如未设置连接空闲超时）会导致无效连接堆积，占用内存和IO资源。

### 解决方案

```java
/**
 * Netty 网关服务端配置（百万QPS优化版）
 * 分离IO线程与业务线程，避免IO线程阻塞
 */
@Configuration
public class NettyGatewayServer {
    // IO线程数：CPU核心数 * 2，处理网络读写
    private static final int IO_THREADS = Runtime.getRuntime().availableProcessors() * 2;
    // 业务线程数：根据业务耗时调整，默认200
    private static final int BUSINESS_THREADS = 200;

    // 业务线程池：处理耗时业务逻辑，避免阻塞IO线程
    private final ThreadPoolExecutor businessExecutor = new ThreadPoolExecutor(
            BUSINESS_THREADS,
            BUSINESS_THREADS,
            60L, TimeUnit.SECONDS,
            new LinkedBlockingQueue<>(10000),
            new ThreadFactoryBuilder().setNameFormat("gateway-business-%d").build()
    );

    @Value("${gateway.port:8080}")
    private int port;

    @Autowired
    private GatewayPluginChain pluginChain;

    @PostConstruct
    public void start() throws Exception {
        // 1. 创建boss线程组（接收连接）
        EventLoopGroup bossGroup = new NioEventLoopGroup(1);
        // 2. 创建worker线程组（IO读写），指定线程数
        EventLoopGroup workerGroup = new NioEventLoopGroup(IO_THREADS);

        try {
            ServerBootstrap b = new ServerBootstrap();
            b.group(bossGroup, workerGroup)
             .channel(NioServerSocketChannel.class)
             // 连接队列大小：10000，应对突发连接
             .option(ChannelOption.SO_BACKLOG, 10000)
             // 禁用Nagle算法，降低延迟
             .childOption(ChannelOption.TCP_NODELAY, true)
             // 设置连接空闲超时：60秒无读写则关闭连接
             .childOption(ChannelOption.SO_KEEPALIVE, true)
             .childHandler(new ChannelInitializer<SocketChannel>() {
                 @Override
                 protected void initChannel(SocketChannel ch) {
                     ChannelPipeline p = ch.pipeline();
                     // HTTP编解码器
                     p.addLast(new HttpServerCodec());
                     // HTTP聚合器：最大请求体10MB
                     p.addLast(new HttpObjectAggregator(10 * 1024 * 1024));
                     // 连接空闲检测：60秒
                     p.addLast(new IdleStateHandler(60, 60, 0, TimeUnit.SECONDS));
                     // 网关业务处理器：将耗时操作提交到业务线程池
                     p.addLast(new GatewayBusinessHandler());
                 }
             });

            ChannelFuture f = b.bind(port).sync();
            log.info("网关启动成功，端口：{}，IO线程数：{}", port, IO_THREADS);
            f.channel().closeFuture().sync();
        } finally {
            bossGroup.shutdownGracefully();
            workerGroup.shutdownGracefully();
        }
    }

    /**
     * 网关业务处理器：将耗时操作提交到业务线程池，避免阻塞IO线程
     */
    private class GatewayBusinessHandler extends SimpleChannelInboundHandler<FullHttpRequest> {
        @Override
        protected void channelRead0(ChannelHandlerContext ctx, FullHttpRequest request) {
            // 将请求提交到业务线程池处理，IO线程立即返回处理其他连接
            businessExecutor.execute(() -> {
                try {
                    // 执行插件链（鉴权、限流、协议转换等）
                    FullHttpResponse response = pluginChain.execute(request);
                    // 写回响应
                    ctx.writeAndFlush(response);
                } catch (Exception e) {
                    log.error("处理请求失败", e);
                    ctx.writeAndFlush(new DefaultFullHttpResponse(HttpVersion.HTTP_1_1, HttpResponseStatus.INTERNAL_SERVER_ERROR));
                } finally {
                    // 释放请求资源
                    request.release();
                }
            });
        }

        @Override
        public void userEventTriggered(ChannelHandlerContext ctx, Object evt) {
            // 空闲连接关闭
            if (evt instanceof IdleStateEvent) {
                ctx.close();
                log.info("空闲连接关闭：{}", ctx.channel().remoteAddress());
            }
        }
    }
}
```

---

## 场景 B：限流算法

### 现象

```
突发流量（如秒杀）导致后端服务被打垮，CPU 100%宕机
网关QPS超过100万时，部分请求超时，返回502错误
限流阈值设置不合理，重要接口（如支付）被误限流
限流后直接返回错误，没有给用户友好提示
```

### 根因分析

常见限流算法存在缺陷：计数器算法有突刺问题（临界时间请求翻倍）；滑动窗口算法精度与内存占用成正比，高精度下内存消耗大；令牌桶算法实现复杂，若令牌生成速率与桶大小配置不当，会导致限流效果不达预期。此外，没有区分接口优先级，所有接口共用同一个限流阈值，导致核心接口被非核心接口流量影响。

### 解决方案

```java
/**
 * 网关限流组件：基于令牌桶算法，支持接口级限流
 */
@Component
public class GatewayRateLimiter {
    // 令牌桶缓存：key为接口URI，value为令牌桶
    private final LoadingCache<String, TokenBucket> bucketCache = Caffeine.newBuilder()
            .maximumSize(1000)
            .build(this::createTokenBucket);

    // 令牌生成线程：定期向所有桶添加令牌
    @PostConstruct
    public void startTokenGenerator() {
        ScheduledExecutorService scheduler = Executors.newSingleThreadScheduledExecutor();
        scheduler.scheduleAtFixedRate(() -> {
            bucketCache.asMap().values().forEach(TokenBucket::addToken);
        }, 0, 100, TimeUnit.MILLISECONDS); // 每100ms生成一次令牌
    }

    /**
     * 尝试获取令牌，获取成功返回true
     * @param uri 接口URI
     * @param requireTokens 需要的令牌数（默认1）
     */
    public boolean tryAcquire(String uri, int requireTokens) {
        TokenBucket bucket = bucketCache.get(uri);
        return bucket.tryAcquire(requireTokens);
    }

    /**
     * 创建令牌桶：根据接口配置初始化
     */
    private TokenBucket createTokenBucket(String uri) {
        // 从配置中心获取接口限流配置，默认QPS 1000
        int qps = getQpsFromConfigCenter(uri);
        int bucketSize = qps * 2; // 桶大小为QPS的2倍，应对突发流量
        return new TokenBucket(qps, bucketSize);
    }

    /**
     * 令牌桶实现
     */
    private static class TokenBucket {
        private final int tokensPerSecond; // 每秒生成令牌数
        private final int maxTokens;       // 桶最大容量
        private int currentTokens;          // 当前令牌数
        private long lastAddTime;          // 上次添加令牌时间

        public TokenBucket(int tokensPerSecond, int maxTokens) {
            this.tokensPerSecond = tokensPerSecond;
            this.maxTokens = maxTokens;
            this.currentTokens = maxTokens;
            this.lastAddTime = System.currentTimeMillis();
        }

        /**
         * 尝试获取令牌
         */
        public synchronized boolean tryAcquire(int requireTokens) {
            addToken();
            if (currentTokens >= requireTokens) {
                currentTokens -= requireTokens;
                return true;
            }
            return false;
        }

        /**
         * 添加令牌：根据时间差计算新增令牌数
         */
        private void addToken() {
            long now = System.currentTimeMillis();
            long timeDiff = now - lastAddTime;
            if (timeDiff > 0) {
                int addCount = (int) (timeDiff / 1000.0 * tokensPerSecond);
                if (addCount > 0) {
                    currentTokens = Math.min(maxTokens, currentTokens + addCount);
                    lastAddTime = now;
                }
            }
        }
    }
}
```

---

## 场景 C：鉴权与协议转换

### 现象

```
HTTP请求转Dubbo协议时，参数丢失或类型转换错误
新增鉴权方式（如API签名）需要修改网关核心代码
插件执行顺序不当，鉴权在限流之后执行，浪费资源
不同协议（HTTP/gRPC/Dubbo）转换逻辑耦合，难以维护
```

### 根因分析

协议转换没有统一的适配层，不同协议的序列化/反序列化逻辑硬编码在网关核心中，缺乏扩展点。鉴权逻辑与网关核心耦合，新增鉴权方式需要修改核心代码，违反开闭原则。插件链没有统一的接口和执行顺序管理，插件之间的依赖关系（如鉴权在限流前执行）无法保证，导致无效请求流到下游。

### 解决方案

```java
/**
 * 网关插件链：统一插件接口，支持顺序执行、动态扩展
 */
@Component
public class GatewayPluginChain {
    // 插件列表：按执行顺序排序，从配置中心加载
    private volatile List<GatewayPlugin> plugins;

    @PostConstruct
    public void init() {
        // 初始化插件顺序：1.鉴权 → 2.限流 → 3.协议转换 → 4.日志
        plugins = Arrays.asList(
                new AuthPlugin(),    // 鉴权插件
                new RateLimitPlugin(), // 限流插件
                new ProtocolConvertPlugin(), // 协议转换插件
                new LogPlugin()      // 日志插件
        );
    }

    /**
     * 执行插件链
     */
    public FullHttpResponse execute(FullHttpRequest request) {
        // 1. 执行前置插件（鉴权、限流等）
        for (GatewayPlugin plugin : plugins) {
            if (!plugin.beforeHandle(request)) {
                // 插件拦截请求，返回错误响应
                return plugin.getErrorResponse();
            }
        }

        // 2. 协议转换：HTTP → 后端服务协议
        BackendRequest backendRequest = ProtocolConvertPlugin.convert(request);

        // 3. 转发请求到后端服务
        BackendResponse backendResponse = forwardToBackend(backendRequest);

        // 4. 执行后置插件（日志等）
        for (GatewayPlugin plugin : plugins) {
            plugin.afterHandle(request, backendResponse);
        }

        // 5. 转换响应为HTTP格式
        return convertToHttpResponse(backendResponse);
    }

    /**
     * 协议转换插件：支持HTTP→Dubbo/grpc转换
     */
    @Component
    public static class ProtocolConvertPlugin implements GatewayPlugin {
        @Override
        public boolean beforeHandle(FullHttpRequest request) {
            return true; // 转换逻辑在execute中统一处理
        }

        @Override
        public FullHttpResponse getErrorResponse() {
            return null;
        }

        @Override
        public void afterHandle(FullHttpRequest request, Object response) {
        }

        /**
         * HTTP请求转Dubbo请求
         */
        public static DubboRequest convertHttpToDubbo(FullHttpRequest httpRequest, String serviceName, String methodName) {
            DubboRequest dubboRequest = new DubboRequest();
            dubboRequest.setServiceName(serviceName);
            dubboRequest.setMethodName(methodName);
            // 解析HTTP参数，转为Dubbo参数类型
            Map<String, String> params = parseHttpParams(httpRequest);
            dubboRequest.setParameters(params);
            dubboRequest.setAttachment("traceId", getTraceId(httpRequest));
            return dubboRequest;
        }
    }

    /**
     * 统一插件接口
     */
    public interface GatewayPlugin {
        /**
         * 处理请求前执行，返回false则拦截请求
         */
        boolean beforeHandle(FullHttpRequest request);

        /**
         * 获取拦截时的错误响应
         */
        FullHttpResponse getErrorResponse();

        /**
         * 处理响应后执行
         */
        void afterHandle(FullHttpRequest request, Object response);
    }
}
```

---

## 场景 D：熔断与降级

### 现象

```
后端服务故障（如DB宕机），网关还在转发请求，导致大量请求堆积
熔断后直接返回错误，用户看到500页面，体验差
熔断恢复阈值设置不合理，服务恢复后还是无法访问
没有熔断监控，故障发生半小时后才被发现
```

### 根因分析

缺少后端服务健康状态监控，无法及时感知服务故障。熔断触发条件配置不合理（如错误率阈值太高），导致故障发生后很久才熔断。熔断后没有降级逻辑，直接返回错误响应，没有备用数据或友好提示。熔断恢复没有灰度机制，服务刚恢复就全量放开流量，可能导致二次故障。

### 解决方案

```java
/**
 * 网关熔断降级组件：基于滑动窗口统计错误率，支持降级兜底
 */
@Component
public class GatewayCircuitBreaker {
    // 熔断规则缓存：key为服务名
    private final LoadingCache<String, CircuitBreakerRule> ruleCache = Caffeine.newBuilder()
            .maximumSize(100)
            .build(this::loadCircuitBreakerRule);

    // 服务健康状态缓存：key为服务名
    private final LoadingCache<String, ServiceHealthState> healthCache = Caffeine.newBuilder()
            .maximumSize(100)
            .expireAfterWrite(1, TimeUnit.MINUTES)
            .build(this::initServiceHealthState);

    /**
     * 执行请求，带熔断降级
     * @param serviceName 服务名
     * @param request 请求
     * @param fallback 降级逻辑
     */
    public BackendResponse executeWithCircuitBreaker(String serviceName, BackendRequest request, Supplier<BackendResponse> fallback) {
        CircuitBreakerRule rule = ruleCache.get(serviceName);
        ServiceHealthState healthState = healthCache.get(serviceName);

        // 1. 检查是否熔断
        if (healthState.isCircuitOpen()) {
            // 熔断开启，执行降级逻辑
            return fallback.get();
        }

        try {
            // 2. 转发请求到后端服务
            BackendResponse response = forwardToBackend(serviceName, request);
            // 3. 记录成功请求
            healthState.recordSuccess();
            return response;
        } catch (Exception e) {
            // 4. 记录失败请求
            healthState.recordFailure();
            // 5. 检查是否需要触发熔断
            if (healthState.getErrorRate() > rule.getErrorRateThreshold()) {
                healthState.openCircuit(rule.getCircuitOpenTime());
                log.warn("服务{}触发熔断，错误率：{}", serviceName, healthState.getErrorRate());
            }
            // 执行降级逻辑
            return fallback.get();
        }
    }

    /**
     * 服务健康状态：滑动窗口统计最近100个请求的错误率
     */
    private static class ServiceHealthState {
        private final int windowSize = 100; // 滑动窗口大小
        private final boolean[] requestResults = new boolean[windowSize]; // 请求结果，true成功，false失败
        private int currentIndex = 0; // 当前窗口索引
        private int successCount = 0; // 成功次数
        private long circuitOpenTime = 0; // 熔断开启时间
        private boolean isOpen = false; // 是否熔断

        public synchronized void recordSuccess() {
            boolean oldResult = requestResults[currentIndex];
            requestResults[currentIndex] = true;
            if (oldResult != true) {
                successCount++;
            }
            moveIndex();
        }

        public synchronized void recordFailure() {
            boolean oldResult = requestResults[currentIndex];
            requestResults[currentIndex] = false;
            if (oldResult == true) {
                successCount--;
            }
            moveIndex();
        }

        public double getErrorRate() {
            return 1 - (successCount / (double) windowSize);
        }

        public synchronized void openCircuit(long openTimeMs) {
            isOpen = true;
            circuitOpenTime = System.currentTimeMillis() + openTimeMs;
        }

        public synchronized boolean isCircuitOpen() {
            if (isOpen && System.currentTimeMillis() > circuitOpenTime) {
                // 熔断时间到，进入半开状态
                isOpen = false;
                resetWindow(); // 重置窗口，灰度测试
            }
            return isOpen;
        }

        private void moveIndex() {
            currentIndex = (currentIndex + 1) % windowSize;
        }

        private void resetWindow() {
            Arrays.fill(requestResults, true);
            successCount = windowSize;
            currentIndex = 0;
        }
    }
}
```

---

## 核心参数估算

```
性能参数：
  最大QPS：100万（集群部署，10个网关节点，单节点10万QPS）
  平均RT：5ms（不含后端服务耗时）
  IO线程数：32（16核CPU * 2）
  业务线程数：200/节点，队列长度10000

资源参数：
  内存：8GB/节点（连接缓存、令牌桶、插件上下文）
  CPU：16核/节点，IO线程CPU使用率<60%，业务线程<80%
  连接数：最大10万/节点，空闲超时60秒

可用性参数：
  熔断触发错误率阈值：50%（10秒内错误率）
  熔断时间：30秒，半开状态灰度10个请求
  限流阈值：核心接口1万QPS，非核心1千QPS
```

---

## 涉及知识点

| 概念 | 所属域 | 关键点 |
|------|--------|--------|
| Netty Reactor模型 | 网络编程/NIO | IO线程、业务线程分离、EventLoop |
| 令牌桶限流 | 中间件/限流 | 令牌生成、桶容量、突发流量应对 |
| 网关插件链 | 架构/设计模式 | 责任链模式、插件排序、扩展点 |
| 协议转换 | 网络/协议 | HTTP/Dubbo/gRPC序列化、参数映射 |
| 熔断降级 | 架构/高可用 | 滑动窗口、错误率统计、半开状态 |
| 连接管理 | 网络编程 | 空闲超时、TCP参数优化、连接池 |

---

## 排查 Checklist

```
□ IO线程是否阻塞？ → 检查业务线程池是否满，耗时操作是否提交到业务线程
□ 限流阈值是否合理？ → 核心接口QPS达标，无误限流
□ 插件执行顺序是否正确？ → 鉴权→限流→协议转换→日志
□ 协议转换是否丢参？ → 检查参数映射配置，测试各类请求
□ 熔断触发是否及时？ → 错误率50%时10秒内触发熔断
□ 降级逻辑是否生效？ → 熔断后返回降级数据，非500错误
□ 连接数是否过高？ → 最大连接数<10万，空闲连接及时回收
□ 网关RT是否达标？ → 平均RT<10ms，P99<50ms
□ 插件是否可扩展？ → 新增插件无需修改核心代码
□ 监控是否完善？ → QPS、RT、错误率、熔断状态实时监控
```

---

## 追问链

### 追问 1：Netty IO线程数设置多少合适？

> 建议设置为CPU核心数的1~2倍，过多的IO线程会导致线程上下文切换开销增大。百万QPS场景下，16核服务器设置32个IO线程即可，重点是将耗时操作转移到业务线程池，而非增加IO线程数。可通过压测调整IO线程数，找到CPU使用率与RT的平衡点。

### 追问 2：令牌桶和漏桶算法有什么区别？

> 令牌桶允许突发流量：只要桶中有令牌，就可以一次性处理多个请求，适合网关场景（应对突发流量）。漏桶算法则是匀速处理请求，不管桶中有多少请求，都按固定速率处理，无法应对突发流量，更适合需要严格限速的场景。

### 追问 3：插件链如何实现动态排序和热加载？

> 每个插件实现Ordered接口，指定执行顺序；插件链初始化时按order排序。热加载可通过监听配置中心（如Nacos）的插件配置变更，重新加载插件列表并排序，无需重启网关。注意热加载时需保证插件链线程安全，避免并发修改。

### 追问 4：熔断半开状态如何避免二次故障？

> 半开状态时，网关只放行少量请求（如10个/秒）到后端服务，若这些请求成功率>90%，则关闭熔断；若成功率<90%，则重新打开熔断。通过灰度放量验证服务恢复状态，避免全量放开流量导致二次故障。

---

## 我的实战笔记

-（待补充，项目中的真实经历）
