# Spring Cloud 微服务核心组件

> ⚠️ **先盲答**：一个微服务架构通常包含哪些核心组件？各自解决什么问题？

---

## 盲答引导

1. 服务注册与发现是什么？Eureka 和 Nacos 有什么区别？
2. 配置中心解决什么问题？配置变更如何实时生效？
3. 声明式 HTTP 调用是怎么实现的？
4. 熔断、降级、限流的区别？

---

## 知识链提示

```
Spring Cloud 微服务全家桶
  → [[SpringCloud]]
    → 1. 注册中心（服务发现）
      → Eureka（Netflix，已停更）/ Nacos（Alibaba，活跃）
        → 服务启动时注册自己（IP + Port + 服务名）
        → 消费者从注册中心拉取服务列表（本地缓存）
        → 心跳机制：服务健康状态同步
      → Nacos 优势：支持 AP + CP 切换、配置中心合一、UI 更友好
    → 2. 配置中心
      → Spring Cloud Config（早期）/ Nacos Config（主流）
        → 配置外置，集中管理多环境配置
        → 动态刷新：@RefreshScope + Spring Cloud Bus（消息总线）或 Nacos 长轮询
        → Git 作为配置存储（Config）/ 自带存储（Nacos）
    → 3. 声明式 HTTP 调用
      → Spring Cloud OpenFeign（主流）
        → 接口 + @FeignClient → 动态代理生成 HTTP 客户端
        → 整合 Ribbon（负载均衡）/ Spring Cloud LoadBalancer
        → 支持 Fallback（熔断降级）
      → RestTemplate + @LoadBalanced（老方式）
    → 4. 负载均衡
      → Ribbon（Netflix，维护模式）/ Spring Cloud LoadBalancer（推荐）
        → 策略：轮询 / 随机 / 权重 / 最小并发
    → 5. 熔断与降级
      → Hystrix（Netflix，已停更）/ Resilience4j（推荐）
        → 熔断器状态机：Closed → Open → Half-Open
        → 熔断触发条件：错误率 > 阈值（如 50%）且请求数 > 最小请求数
        → 降级：熔断触发后的备用逻辑（Fallback）
    → 6. 网关（Gateway）
      → Spring Cloud Gateway（推荐，基于 WebFlux）
        → 路由（Route）+ 断言（Predicate）+ 过滤器（Filter）
        → 对比 Zuul 1.x（同步阻塞）vs Gateway（异步非阻塞，性能更好）
    → 7. 链路追踪
      → Sleuth + Zipkin（老）/ Micrometer Tracing + Zipkin（新）
        → 分布式 TraceId 传递，串联整个调用链
```

---

## 核心追问

| 追问 | 考点 |
|------|------|
| Nacos 的配置实时推送是怎么实现的？ | 长轮询（客户端定时请求，服务端 hold 住连接直到配置变更或超时）|
| OpenFeign 的超时配置？ | 连接超时 + 读超时，可针对单个 FeignClient 配置 |
| 网关和过滤器的区别？ | 网关是系统级（入口流量），过滤器是方法级（AOP）；网关做路由/鉴权/限流，过滤器做业务逻辑 |
| 注册中心挂了，服务还能调用吗？ | 能，消费者有本地缓存的服务列表，但无法感知新节点上线 |

---

## 参考答案要点

**注册中心**：服务的「通讯录」，解决硬 IP 地址问题；Nacos 比 Eureka 多了配置中心功能和 AP/CP 切换能力。

**配置中心**：配置外置 + 动态刷新，避免重启服务；Nacos Config 通过长轮询实现准实时推送。

**OpenFeign**：接口声明式 HTTP 调用，底层是 JDK 动态代理 + RestTemplate（或 WebClient）。

**熔断**：错误率超阈值则「跳闸」，一段时间后放一个请求探测（Half-Open），成功则关闭熔断。

---

## 下一步

打开 [[SpringCloud]]，补充 `[[双向链接]]`：「微服务不是把单体拆小就完了——注册中心、配置中心、网关、熔断，缺一不可」。
