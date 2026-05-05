# Dubbo 核心原理

## 这个问题为什么存在？

在微服务架构里，服务拆分后需要**跨进程调用**：订单服务要调库存服务，库存服务要调支付服务。问题来了：

1. **怎么找到对方？** —— 服务发现
2. **怎么通信？** —— 网络协议
3. **怎么序列化/反序列化？** —— 数据编解码
4. **调用挂了怎么办？** —— 容错策略
5. **服务多了怎么管理？** —— 治理（路由、降级、限流）

Dubbo 就是阿里开源的 **高性能 Java RPC 框架**，一站式解决上述问题。

```
没有 RPC 框架时，你要自己写：
  URL 连接管理 + 序列化 + 网络通信 + 负载均衡 + 服务发现...
  → 每个项目都重复造轮子，还容易写错

有了 Dubbo：
  @DubboService  // 加个注解，服务就暴露出去了
  @DubboReference // 加个注解，远程调用就像调本地方法
  → 上面的复杂问题全部帮你解决
```

---

## 它是怎么解决问题的？

### 一、整体架构

```
┌─────────────────────────────────────────────────┐
│                   Dubbo 架构                      │
│                                                   │
│  ┌──────────┐                    ┌──────────┐    │
│  │ Consumer  │                   │ Provider  │    │
│  │ (调用方)  │                   │ (服务方)  │    │
│  └────┬─────┘                    └────┬─────┘    │
│       │                               │          │
│       │  ① 订阅服务  ② 注册服务        │          │
│       │                               │          │
│  ┌────▼───────────────────────────────▼─────┐    │
│  │          Registry（注册中心）              │    │
│  │   ZooKeeper / Nacos / Redis              │    │
│  └──────────────────────────────────────────┘    │
│                                                   │
│       │ ③ 从注册中心获取地址列表，本地缓存          │
│       │ ④ 直接调用 Provider（不经注册中心）         │
│                                                   │
│  ┌────▼─────────────────────────────────────┐    │
│  │          Monitor（监控中心）               │    │
│  │   统计调用次数、耗时、成功率               │    │
│  └──────────────────────────────────────────┘    │
└─────────────────────────────────────────────────┘
```

**关键角色**：
| 角色 | 职责 | 说明 |
|------|------|------|
| **Provider** | 服务提供方 | 暴露服务，注册到注册中心 |
| **Consumer** | 服务消费方 | 从注册中心订阅服务，发起远程调用 |
| **Registry** | 注册中心 | 服务注册与发现（ZooKeeper/Nacos/Redis） |
| **Monitor** | 监控中心 | 统计服务调用数据（可选） |

**核心设计**：Consumer 调用 Provider **不经过注册中心**，注册中心只在服务发现阶段使用，避免注册中心成为性能瓶颈。

### 二、服务调用完整流程

```
Consumer 调用 dubboService.hello("world")：

1. 代理拦截：Consumer 调用的是代理对象（不是真实对象）
2. 服务发现：从本地缓存/注册中心拿到 Provider 地址列表
3. 负载均衡：从多个 Provider 中选一个（随机/轮询/一致性Hash...）
4. 网络传输：通过 Netty 发送请求（TCP 长连接，Dubbo 协议）
5. 服务处理：Provider 的线程池接收请求，反射调用真实方法
6. 结果返回：原路返回结果（同步/异步/单向）
```

```java
// Provider 端：暴露服务
@DubboService(version = "1.0.0", timeout = 3000)
public class OrderServiceImpl implements OrderService {
    @Override
    public Order getOrder(Long orderId) {
        return orderMapper.selectById(orderId);
    }
}

// Consumer 端：远程调用（和调本地方法一样）
@DubboReference(version = "1.0.0")
private OrderService orderService;

public void process(Long orderId) {
    // 看起来是本地调用，实际是网络请求
    Order order = orderService.getOrder(orderId);
}
```

### 三、SPI 机制（Dubbo 的灵魂）

**SPI = Service Provider Interface**，一种**可插拔**的扩展机制。Dubbo 的负载均衡、序列化、协议、线程池等全部通过 SPI 实现，用户可以自定义替换。

```
为什么需要 SPI？
  → 不同场景需要不同实现：
    - 负载均衡：随机/轮询/一致性Hash/最少活跃数...
    - 序列化：Hessian/Kryo/Fastjson/Protobuf...
    - 协议：dubbo/rest/rmi/http...
  → SPI 让你可以"不改源码，只改配置"就切换实现
```

```java
// Dubbo SPI 使用方式
@SPI("random")  // 默认用随机负载均衡
public interface LoadBalance {
    <T> Invoker<T> select(List<Invoker<T>> invokers, URL url, Invocation invocation);
}

// 自定义负载均衡：实现接口 + 配置文件，Dubbo 自动加载
// META-INF/dubbo/org.apache.dubbo.rpc.cluster.LoadBalance：
//   myLoadBalance=com.example.MyLoadBalance
```

**Java SPI vs Dubbo SPI**：

| 维度 | Java SPI | Dubbo SPI |
|------|----------|-----------|
| 加载方式 | 全部加载（懒加载） | 按需加载（只加载指定的） |
| 依赖注入 | 不支持 | 支持（IOC） |
| 配置格式 | 文件里每行一个实现类 | key=value 格式 |
| 是否缓存 | 不缓存 | 缓存（性能更好） |

### 四、负载均衡策略

```
Dubbo 内置 4 种负载均衡：

1. RandomLoadBalance（默认）
   → 加权随机，按权重分配概率
   → 适合服务性能差不多的场景

2. RoundRobinLoadBalance
   → 加权轮询，按权重轮流
   → 适合需要平滑分配的场景

3. ConsistentHashLoadBalance
   → 一致性 Hash（虚拟节点），同一参数的请求打到同一 Provider
   → 适合有状态缓存的服务

4. LeastActiveLoadBalance
   → 最少活跃调用数，谁最闲找谁
   → 适合服务处理时间差异大的场景
```

```java
// 配置负载均衡
@DubboReference(loadbalance = "leastactive", timeout = 3000)
private OrderService orderService;

// 或者在配置文件里全局设置
// dubbo.consumer.loadbalance=leastactive
```

### 五、集群容错策略

当远程调用失败时，Dubbo 提供多种容错策略：

```
1. Failover（默认）—— 失败自动切换
   → 调用失败，自动重试其他 Provider
   → 配置 retries="2"（默认重试 2 次，总共调 3 次）
   → 注意：读操作用这个，写操作千万别用（会重复写入）

2. Failfast —— 快速失败
   → 调用失败立即报错，不重试
   → 适合写操作（创建订单、扣款等）

3. Failsafe —— 失败安全
   → 调用失败只记录日志，不报错
   → 适合日志记录等非核心操作

4. Failback —— 失败自动恢复
   → 调用失败，记录到失败队列，定时重试
   → 适合消息通知等可以延迟执行的操作

5. Forking —— 并行调用
   → 同时调用多个 Provider，哪个先返回用哪个
   → 适合实时性要求高的场景（会消耗更多资源）

6. Broadcast —— 广播调用
   → 逐个调用所有 Provider，任意一个报错则报错
   → 适合缓存更新等需要通知所有节点的场景
```

```java
// 配置容错策略
@DubboReference(cluster = "failfast", retries = 0)
private PaymentService paymentService;  // 支付用 failfast，不重试
```

### 六、序列化协议

```java
// Dubbo 支持的序列化方式
// 配置：dubbo.protocol.serialization=hessian2

// 性能对比：
// Hessian2（默认）：跨语言、中等性能
// Kryo：Java 专用、高性能（推荐内部服务使用）
// Fastjson：速度快、安全漏洞风险（慎用）
// Protobuf：跨语言、高性能（推荐跨语言场景）
// Java 原生序列化：性能差、不支持跨语言（不推荐）
```

**为什么默认用 Hessian2？** 兼顾跨语言支持和性能，是 Dubbo 生态的平衡选择。

### 七、Dubbo 协议

```
Dubbo 协议（默认）：
  → 单一 TCP 长连接
  → NIO 异步通信（底层 Netty）
  → Hessian2 序列化
  → 适合小数据量、高并发调用

  优点：连接复用，减少握手开销
  缺点：单一连接可能成为瓶颈（Provider 线程池要够大）

Dubbo 可以切换协议：
  - dubbo（默认）：单一长连接 + NIO
  - rmi：Java 原生 RMI 协议
  - hessian：HTTP 短连接 + Hessian 序列化
  - http：REST 风格，适合异构系统
```

### 八、服务降级与路由

```java
// 1. 服务降级：服务不可用时返回兜底数据
@DubboReference(mock = "return null")  // 服务挂了返回 null
private UserService userService;

// 或者自定义降级逻辑
@DubboReference(mock = "com.example.UserServiceMock")
private UserService userService;

// 2. 服务路由：根据条件分流
// dubbo.consumer.router=tag  → 标签路由（灰度发布）
// 例如：新版本打上 tag="gray"，灰度用户走 gray 标签的 Provider
```

### 九、线程模型

```
Dubbo 线程模型（基于 Netty EventLoop）：

  IO 线程（Netty EventLoop）
    → 负责网络读写、协议编解码
    → 如果业务逻辑在这里处理 → 所有请求串行，性能差！

  业务线程池（Dubbo ThreadPool）
    → IO 线程解码完请求后，丢给业务线程池处理
    → 默认 200 个线程，可配置
    → 这才是真正执行 Service 方法的地方

配置：
  dubbo.protocol.threads=200        // 业务线程数
  dubbo.protocol.iothreads=CPU核心数+1  // IO 线程数
```

---

## 深入原理

### Dubbo vs Spring Cloud

| 维度 | Dubbo | Spring Cloud |
|------|-------|--------------|
| **定位** | RPC 框架（专注服务调用） | 微服务全家桶（一站式） |
| **通信方式** | RPC（二进制，高性能） | HTTP/REST（文本，通用性好） |
| **服务发现** | ZooKeeper/Nacos | Eureka/Nacos/Consul |
| **负载均衡** | 客户端负载均衡 | 客户端负载均衡（Ribbon/LoadBalancer） |
| **熔断降级** | 自带 + Sentinel | Hystrix/Resilience4j |
| **配置中心** | 外挂（Nacos/Apollo） | Spring Cloud Config/Nacos |
| **API 网关** | 无内置 | Spring Cloud Gateway |
| **跨语言** | 较弱（主要是 Java） | 较好（HTTP 协议无关） |
| **性能** | 高（二进制 RPC） | 中（HTTP 序列化开销） |
| **社区** | 阿里主导，国内主流 | Netflix/ Spring 主导，国际主流 |
| **学习曲线** | 低（上手快） | 中（要学整套生态） |

**本质区别**：
- Dubbo 是**交通工具**（解决"怎么从 A 到 B"），性能高，但只管路
- Spring Cloud 是**城市规划**（路、灯、交通管理、消防...一套全包），功能全，但每个组件都依赖 Spring 生态

**怎么选？**
- 公司已有阿里系技术栈（HSF/EDAS）→ Dubbo
- 新项目、需要异构语言支持 → Spring Cloud
- 对性能极致要求 → Dubbo
- 想要开箱即用、少自己组装 → Spring Cloud
- **现实中最常见：Dubbo + Nacos + Sentinel**（阿里系标配）

### Dubbo vs gRPC

| 维度 | Dubbo | gRPC |
|------|-------|------|
| 语言支持 | 主要 Java | 多语言（原生支持） |
| 协议 | 自定义 TCP 协议 | HTTP/2 |
| 序列化 | Hessian2/Kryo | Protobuf |
| 服务治理 | 内置（负载均衡、路由、降级） | 不内置（需要自己实现） |
| 生态 | Java 微服务生态 | Google/K8s 生态 |
| 适用场景 | Java 微服务内部调用 | 跨语言、云原生 |

---

## 正确使用方式

### 正确用法

**1. 写操作不要用 Failover（重要！）**

```java
// 错误：支付用默认的 Failover，失败会重试
@DubboReference  // 默认 retries=2，失败重试 2 次
private PaymentService paymentService;

// 正确：写操作用 Failfast，不重试
@DubboReference(cluster = "failfast", retries = 0)
private PaymentService paymentService;
```

**为什么？** 支付失败了重试 → 重复扣款！Failover 默认会重试，写操作必须显式关掉。

**2. 接口要兼容版本号**

```java
// Provider 端
@DubboService(version = "1.0.0")
public class OrderServiceImpl implements OrderService { ... }

// Consumer 端
@DubboReference(version = "1.0.0")  // 版本号必须匹配
private OrderService orderService;
```

**为什么？** 没有版本号，接口升级后新旧 Provider 共存，Consumer 可能调到不兼容的旧服务。生产环境建议始终带版本号。

**3. 合理设置超时时间**

```java
// 不要用默认超时（1秒），根据业务设置
@DubboReference(timeout = 5000)  // 查询 5 秒
private OrderQueryService queryService;

@DubboReference(timeout = 2000)  // 支付 2 秒
private PaymentService paymentService;
```

**原则**：读操作超时长一些（5s），写操作超时短一些（2s），避免慢调用拖垮线程池。

**4. Provider 端设置线程池隔离**

```java
// 不同服务用不同的线程池，避免互相影响
@DubboService(executor = "orderExecutor")
public class OrderServiceImpl implements OrderService { ... }
```

### 错误用法及后果

**错误1：DTO 对象实现 Serializable 但没声明 serialVersionUID**

```java
// 错误：DTO 没有 serialVersionUID
public class OrderDTO implements Serializable {
    private Long orderId;
    private String orderName;
    // 一旦字段变更，反序列化可能失败！
}
```

**后果**：服务升级后新增/删除字段，反序列化报 `InvalidClassException`，线上报错。

**修复**：

```java
public class OrderDTO implements Serializable {
    private static final long serialVersionUID = 1L;
    private Long orderId;
    private String orderName;
}
```

**错误2：Consumer 端本地缓存了 Provider 地址，Provider 扩缩容后路由不均**

```
正常情况：Consumer 定时从注册中心拉取最新地址列表
但如果注册中心挂了，Consumer 会用本地缓存的旧地址
→ 新扩容的 Provider 没有被路由到，老 Provider 压力过大
```

**修复**：注册中心要做高可用（ZooKeeper 集群 / Nacos 集群）。

**错误3：接口方法参数或返回值太大**

```java
// 错误：一次性查询大量数据返回
public List<Order> queryAllOrders();  // 可能返回百万条！
```

**后果**：序列化后数据包巨大，网络传输慢，Provider 线程池长时间占用。

**修复**：加分页参数，控制每次返回的数据量。

---

## 边界情况和坑

### 坑1：Dubbo 泛化调用（Generic Service）

```java
// 不依赖接口 SDK，用 Map 传参调用任意服务
GenericService genericService = (GenericService) applicationContext.getBean("orderService");
Object result = genericService.$invoke(
    "getOrder",                          // 方法名
    new String[]{"java.lang.Long"},      // 参数类型
    new Object[]{12345L}                 // 参数值
);
```

**场景**：网关层需要统一调用后端多个服务，但不想引入所有服务的 SDK。泛化调用可以"无接口编程"。

### 坑2：本地存根（Stub）

```java
// Consumer 端可以在调用远程服务前后加逻辑
public class OrderServiceStub implements OrderService {
    private OrderService orderService;  // 远程服务代理

    public OrderServiceStub(OrderService orderService) {
        this.orderService = orderService;
    }

    @Override
    public Order getOrder(Long orderId) {
        // 远程调用前：本地参数校验、缓存查询
        Order cached = localCache.get(orderId);
        if (cached != null) return cached;

        // 调用远程服务
        return orderService.getOrder(orderId);
    }
}
```

### 坑3：Dubbo 3.x 的应用级服务发现

```
Dubbo 2.x：接口级注册（每个接口注册一条地址）
  → 100 个接口 × 10 个 Provider = 1000 条注册记录
  → 注册中心压力大

Dubbo 3.x：应用级注册（每个应用注册一条地址，接口列表作为元数据）
  → 10 个 Provider = 10 条注册记录
  → 注册中心压力降低 100 倍
```

---

**关联文档**：
- [[07_中间件/00_概览|常见中间件综合]]（ZooKeeper/Netty 基础设施）
- [[08_分布式与架构/03_微服务核心/服务注册与发现]]（微服务层面的注册发现）
- [[08_分布式与架构/03_微服务核心/服务容错设计]]（熔断/降级/限流）
- [[08_分布式与架构/03_微服务核心/API网关设计]]（网关层架构）
