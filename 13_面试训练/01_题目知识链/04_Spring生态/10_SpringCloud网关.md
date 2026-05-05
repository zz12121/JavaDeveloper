# Spring Cloud Gateway 是怎么工作的？

> ⚠️ **先盲答**：Spring Cloud Gateway 是什么？它和 Zuul 有什么区别？

---

## 盲答引导

1. Gateway 的请求处理流程是什么？—— DispatcherHandler → RoutePredicateHandlerMapping → FilterWebHandler
2. 什么是 Predicate（断言）？—— 路由匹配条件（路径/Host/Query参数）
3. 什么是 GatewayFilter？—— 请求/响应的过滤器链（单个路由级别）
4. 什么是 GlobalFilter？—— 全局过滤器，所有路由都生效

---

## 知识链提示

```
Spring Cloud Gateway
  → [[04_Spring生态/03_SpringCloud/网关]]
    → 架构
      → 响应式编程：基于 WebFlux（Netty + Reactor）
        → 非阻塞 IO：单线程处理高并发请求（不用传统 Servlet 线程池）
        → 对比：Zuul 1.x 基于 Servlet + 线程池（阻塞）
      → 三个核心组件
        → Route：路由规则（id / uri / predicates / filters）
        → Predicate：匹配条件（路径 / Host / Method / Query / Cookie / Header）
        → Filter：过滤器（请求前 + 请求后）
    → 请求处理流程
      → 1. Gateway Handler（DispatcherHandler）：接收请求
      → 2. Route Predicate Handler Mapping：匹配路由（Predicate 断言）
      → 3. Filter Web Handler：构建过滤器链（GlobalFilter + GatewayFilter）
      → 4. Pre Filter：执行前置逻辑（认证/限流/日志）
      → 5. Proxy Service：转发到下游服务
      → 6. Post Filter：执行后置逻辑（响应头处理/监控）
    → 常用过滤器
      → StripPrefix：去除路径前缀（StripPrefix=2 去掉前两层路径）
      → AddRequestHeader / AddResponseHeader：增加 Header
      → RequestRateLimiter：限流（基于令牌桶 / Redis）
      → CircuitBreaker：熔断（Hystrix / Resilience4j）
```

---

## 核心追问

| 追问 | 考点 |
|------|------|
| Gateway 和 Zuul 的核心区别是什么？ | Gateway 基于 WebFlux（非阻塞），Zuul 1.x 基于 Servlet（阻塞）|
| 为什么 Gateway 比 Zuul 性能高？ | Netty（IO多路复用）+ 非阻塞 + 单线程模型 vs 线程池模型 |
| 限流在 Gateway 里怎么实现？ | RequestRateLimiter（Redis + 令牌桶）|
| Gateway 如何实现统一认证？ | GlobalFilter（认证 Filter，验证 Token）|

---

## 参考答案要点

**Gateway 三大组件**：Route（路由规则）+ Predicate（匹配条件）+ Filter（过滤器链）。

**Gateway vs Zuul**：
- Zuul 1.x：Servlet 线程池，阻塞，并发量受限于线程数
- Gateway：WebFlux（Reactor + Netty），非阻塞，单线程可处理海量请求

---

## 下一步

打开 [[04_Spring生态/03_SpringCloud/网关]]，关联 [[08_分布式与架构/05_高可用设计/限流算法]] / [[13_面试训练/01_题目知识链/07_分布式与架构/10_熔断与降级]]，补充链接：「Gateway 的 Filter 链是 AOP 思想在网关层的体现——Pre Filter 做认证/限流，Post Filter 做监控/响应处理」。
