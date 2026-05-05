# API网关设计

## 这个问题为什么存在？

> 微服务架构中，客户端需要调用多个服务（订单、库存、支付）。如果客户端直接调用每个服务，会面临：**认证复杂（每个服务都要验token）、跨域问题（CORS）、客户端耦合严重**。问题是：**怎么统一处理这些横切面逻辑？**

API网关就是微服务的**统一入口**，负责认证、路由、限流、熔断等横切关注点。

---

## 它是怎么解决问题的？

### 核心能力：统一入口 + 横切逻辑

```

客户端（前端/移动端）
        │
        ▼
┌────────────────────┐
│     API 网关        │  ← 统一入口
│  ┌──────────────┐  │
│  │ 认证（JWT）   │  │  ← 横切逻辑1：认证
│  ├──────────────┤  │
│  │ 路由（/order/* │  │  ← 横切逻辑2：路由转发
│  │  → 订单服务） │  │
│  ├──────────────┤  │
│  │ 限流（令牌桶） │  │  ← 横切逻辑3：限流
│  ├──────────────┤  │
│  │ 熔断（Hystrix）│  │  ← 横切逻辑4：熔断
│  └──────────────┘  │
└────────┬───────────┘
         │
    ┌────┴────┐
    ▼         ▼
订单服务   支付服务
```

**请求流程**：
```
T0: 客户端携带JWT → API网关
T1: 网关校验JWT（无效 → 401）
T2: JWT有效，路由到订单服务
T3: 订单服务返回结果
T4: 网关记录访问日志（审计）
```

### Spring Cloud Gateway：基于WebFlux（响应式）

```yaml
spring:
  cloud:
    gateway:
      routes:
        - id: order-service
          uri: lb://order-service         # lb:// 表示负载均衡
          predicates:
            - Path=/api/orders/**        # 路径匹配
          filters:
            - name: RequestRateLimiter   # 限流
              args:
                redis-rate-limiter.replenishRate: 10
                redis-rate-limiter.burstCapacity: 20
            - name: CircuitBreaker       # 熔断
              args:
                name: orderCircularBreaker
```

```java
// 自定义全局过滤器（认证）
@Component
public class AuthFilter implements GlobalFilter {

    @Override
    public Mono<Void> filter(ServerWebExchange exchange, GatewayFilterChain chain) {
        String token = exchange.getRequest().getHeaders().getFirst("Authorization");
        if (token == null || !validateToken(token)) {
            exchange.getResponse().setStatusCode(HttpStatus.UNAUTHORIZED);
            return exchange.getResponse().setComplete();  // 中断请求
        }
        return chain.filter(exchange);  // 放行
    }
}
```

### Nginx：高性能反向代理（简单场景）

```nginx
http {
    upstream order_service {
        server order1:8080;
        server order2:8080;
    }

    server {
        listen 80;

        location /api/orders/ {
            # 认证（简单场景，用Nginx的auth_request模块）
            auth_request /auth;

            proxy_pass http://order_service/;
        }

        location = /auth {
            internal;
            proxy_pass http://auth-service/verify;
        }
    }
}
```

---

## 深入原理

| | Spring Cloud Gateway | Nginx | Kong（基于Nginx+Lua） | Zuul 1.x（已淘汰） |
|---|---|---|---|---|
| 性能 | 中（WebFlux异步） | 极高（C写的） | 高（Lua扩展） | 低（同步阻塞） |
| 功能完备性 | 高（集成Spring生态） | 低（需要Lua扩展） | 高（插件丰富） | 中 |
| 动态路由 | ✅（配置中心） | ❌（需reload） | ✅ | ✅ |
| 限流熔断 | ✅（集成Resilience4j） | ❌（需Lua） | ✅（插件） | ✅ |
| 适用场景 | Spring Cloud全家桶 | 简单路由、静态资源 | 高性能+插件扩展 | 不推荐 |

**本质区别**：
- **Nginx**：性能最高，但功能需要扩展（Lua），动态配置麻烦
- **Spring Cloud Gateway**：功能最完备，集成Spring生态，性能中
- **Kong**：性能和功能折中，基于Nginx+Lua，插件丰富

---

## 正确使用方式

### 场景1：认证统一处理

```java
// ❌ 错误：每个服务都写认证逻辑（重复代码）
@RestController
public class OrderController {
    public Order getOrder(Long id) {
        // 每个服务都要写一遍JWT验证...
        String token = request.getHeader("Authorization");
        if (!jwtUtil.validate(token)) {
            throw new RuntimeException("未登录");
        }
        // ...
    }
}

// ✅ 正确：网关统一认证，服务只关心业务
@Component
public class AuthFilter implements GlobalFilter {
    @Override
    public Mono<Void> filter(ServerWebExchange exchange, GatewayFilterChain chain) {
        // 只在这里写一次认证逻辑
        String token = exchange.getRequest().getHeaders().getFirst("Authorization");
        if (!validateToken(token)) {
            exchange.getResponse().setStatusCode(HttpStatus.UNAUTHORIZED);
            return exchange.getResponse().setComplete();
        }
        return chain.filter(exchange);  // 认证通过，放行
    }
}
```

### 场景2：灰度发布（金丝雀发布）

```yaml
spring:
  cloud:
    gateway:
      routes:
        - id: order-service-v1   # 95%流量
          uri: lb://order-service-v1
          predicates:
            - Weight=group1, 95
        - id: order-service-v2   # 5%流量（灰度）
          uri: lb://order-service-v2
          predicates:
            - Weight=group1, 5
```

---

## 边界情况和坑

### 坑1：网关成为单点瓶颈

```
场景：所有流量都经过网关
后果：网关挂了，整个系统不可用
```

**解决方案**：
1. **网关集群部署**（至少2个实例，前置Nginx负载均衡）
2. **分级网关**（外部流量用外网网关，内部流量走内网网关）
3. **降级方案**（网关挂了，关键服务直连，但要重新考虑认证）

### 坑2：网关超时设置不合理

```
场景：网关超时设5秒，但订单服务需要10秒
后果：订单服务还在处理，网关已经返回504 Timeout
```

**解决方案**：
```yaml
spring:
  cloud:
    gateway:
      httpclient:
        connect-timeout: 1000   # 连接超时1秒
        response-timeout: 30s     # 响应超时30秒（根据业务调整）
```

### 坑3：网关鉴权失效，敏感数据泄露

```
场景：网关只校验token是否存在，不校验权限
后果：普通用户能访问管理员的API
```

**解决方案**：
1. **网关只做认证（who are you），授权下放到服务（what you can do）**
2. **关键API，服务也要做权限校验**（双重保险）

---

