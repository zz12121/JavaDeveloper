# Spring 生态 - 知识点考法对照

## IoC 容器

**第一问**：「IoC 是什么？」

| 追问层次 | 追问 | 考点 |
|---------|------|------|
| 第一层 | `@ComponentScan` 是怎么找到 Bean 的？ | 类路径扫描 → 注册 BeanDefinition |
| 第二层 | `@Import` 有哪些用法？ | ImportSelector / ImportBeanDefinitionRegistrar |
| 第三层 | BeanFactory 和 FactoryBean 的区别？ | BeanFactory 是容器 / FactoryBean 是创建复杂 Bean 的工厂 |

**实战型考法**：「你在项目里自定义过 Bean 吗？用来做什么？」

---

## AOP

**第一问**：「AOP 是什么？」

| 追问层次 | 追问 | 考点 |
|---------|------|------|
| 第一层 | JDK 动态代理和 CGLib 的区别？ | 接口 vs 继承 |
| 第二层 | `@Around` 和 `@Before` 的执行顺序？ | 嵌套拦截器 |
| 第三层 | 同一方法被多个 Aspect 拦截，顺序怎么控制？ | @Order / Ordered |

**实战型考法**：「你在项目里用过 AOP 吗？用来做什么？」

---

## 事务管理

**第一问**：「`@Transactional` 的传播行为有哪些？」

| 追问层次 | 追问 | 考点 |
|---------|------|------|
| 第一层 | 自调用为什么导致事务失效？ | AOP 代理绕过 |
| 第二层 | `REQUIRES_NEW` 和 `REQUIRED` 的区别？ | 挂起现有事务 |
| 第三层 | checked Exception 默认不回滚，为什么？ | Spring 设计哲学 |

**实战型考法**：「你遇到过事务不生效的情况吗？怎么排查的？」

---

## Spring Boot 自动配置

**第一问**：「Spring Boot 怎么实现自动配置的？」

| 追问层次 | 追问 | 考点 |
|---------|------|------|
| 第一层 | `@ConditionalOnMissingBean` 为什么能保证用户定义的 Bean 优先？ | 加载顺序（用户 Bean 在先）|
| 第二层 | 如何排除某个自动配置？ | `exclude` / `spring.autoconfigure.exclude` |
| 第三层 | Spring Boot 2.x 和 3.x 的自动配置文件有什么区别？ | spring.factories vs imports 文件 |

**实战型考法**：「你自定义过 Starter 吗？怎么做的？」

---

## Spring Boot 启动原理

**第一问**：「`SpringApplication.run()` 做了什么？」

| 追问层次 | 追问 | 考点 |
|---------|------|------|
| 第一层 | `refresh()` 的核心步骤有哪些？ | 九大步骤 |
| 第二层 | `ApplicationContextInitializer` 和 `ApplicationListener` 是怎么加载的？ | spring.factories / imports |
| 第三层 | `onRefresh()` 在 Web 场景做了什么？ | 创建内嵌 Web 服务器 |

---

## Spring Cloud 服务注册发现

**第一问**：「Eureka 和 Nacos 的区别？」

| 追问层次 | 追问 | 考点 |
|---------|------|------|
| 第一层 | Eureka 的自我保护机制是什么？ | 心跳丢失 > 15% → 停止剔除 |
| 第二层 | Nacos 如何同时支持 CP 和 AP？ | Raft + 心跳 |
| 第三层 | 注册中心挂了，服务还能调用吗？ | 本地缓存 |

---

## Spring Cloud 网关

**第一问**：「Gateway 和 Zuul 的区别？」|

| 追问层次 | 追问 | 考点 |
|---------|------|------|
| 第一层 | Gateway 基于什么模型？为什么性能高？ | WebFlux / Netty 非阻塞 |
| 第二层 | Gateway 的过滤器链有哪些类型？ | GlobalFilter / GatewayFilter |
| 第三层 | 如何实现统一认证？ | GlobalFilter（认证 Filter） |

**实战型考法**：「你用 Gateway 做过什么？限流？认证？」
