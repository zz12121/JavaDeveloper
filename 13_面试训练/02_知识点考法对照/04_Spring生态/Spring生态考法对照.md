# Spring 生态 - 知识点考法对照

> 本文档是「出题者视角」的知识梳理——每个知识点列出常见考法 + 回答要点。
> 配合对应知识文档一起使用，先学后考。

---

## IoC 容器原理

**关联知识文档**：[[04_Spring生态/01_IoC容器原理/IoC容器原理]]

**第一问**：「IoC 是什么？Spring IoC 容器是怎么工作的？」

| 追问层次 | 追问 | 考点 |
|---------|------|------|
| 第一层 | `@ComponentScan` 是怎么找到 Bean 的？ | ClassPathScanningCandidateComponentProvider + ASM 扫描 |
| 第二层 | BeanFactory 和 ApplicationContext 有什么区别？ | 延迟加载 vs 预加载 / 国际化 / 事件发布 |
| 第三层 | BeanFactory 和 FactoryBean 的区别？ | BeanFactory 是容器 / FactoryBean 是创建复杂 Bean 的工厂 |

**面试话术总结**：

- **IoC 本质**：控制反转，对象创建和依赖关系由容器管理，而非手动 new。DI（依赖注入）是实现 IoC 的方式
- **容器启动流程**（必须能口述大步骤）：
  1. `ResourceLoader` 加载配置（XML / 注解 / Java Config）
  2. `BeanDefinitionReader` 解析为 `BeanDefinition`
  3. `BeanDefinitionRegistry` 注册到 BeanDefinitionMap
  4. `BeanFactoryPostProcessor` 修改 BeanDefinition（如 `PropertySourcesPlaceholderConfigurer`）
  5. 实例化 Bean（构造函数 → 属性注入 → `@PostConstruct` → `InitializingBean.afterPropertiesSet` → `init-method`）
  6. `BeanPostProcessor` 后置处理（AOP 代理在此创建）
- **BeanFactory vs ApplicationContext**：BeanFactory 延迟加载（getBean 时才创建）；ApplicationContext 启动时预加载所有单例 Bean，支持事件机制、国际化、资源加载
- **FactoryBean**：实现 `FactoryBean<T>` 接口，`getObject()` 返回真正的对象；`@Bean` 方法返回 FactoryBean 时，注入的是 `getObject()` 的结果，而非 FactoryBean 本身

---

## AOP 原理

**关联知识文档**：[[04_Spring生态/02_AOP原理/AOP原理]]

**第一问**：「Spring AOP 是怎么实现的？」

| 追问层次 | 追问 | 考点 |
|---------|------|------|
| 第一层 | JDK 动态代理和 CGLIB 的区别？ | 接口 vs 继承 / Spring Boot 2.x 默认 CGLIB |
| 第二层 | `@Around` 和 `@Before` 的执行顺序？ | 同一切面按注解排序，不同切面按 `@Order` |
| 第三层 | 为什么 `@Transactional` 在同类方法调用时失效？ | AOP 基于代理，this.xxx() 绕过了代理对象 |

**面试话术总结**：

- **AOP 核心**：将横切关注点（日志、事务、权限）从业务逻辑中分离。基于代理模式实现
- **JDK 动态代理**：目标类实现接口 → `Proxy.newProxyInstance()` → `InvocationHandler.invoke()` → 反射调用目标方法
- **CGLIB**：目标类不实现接口 → `Enhancer.create()` → 生成子类 → `MethodInterceptor.intercept()` → `MethodProxy.invokeSuper()` 调用父类方法
- **Spring Boot 2.x 默认用 CGLIB**（`spring.aop.proxy-target-class=true` 是默认值），因为 CGLIB 不需要接口
- **同类调用失效原理**：
  ```java
  @Service
  public class UserService {
      public void methodA() { this.methodB(); } // this 是原始对象，不是代理对象 → AOP 失效
      @Transactional
      public void methodB() { ... }
  }
  ```
  解决：注入自己（`@Autowired UserService self; self.methodB()`）或用 `AopContext.currentProxy()`

---

## Spring 事务管理

**关联知识文档**：[[04_Spring生态/03_事务管理/事务管理]]

**第一问**：「`@Transactional` 的传播行为有哪些？」

| 追问层次 | 追问 | 考点 |
|---------|------|------|
| 第一层 | 自调用为什么导致事务失效？ | AOP 代理绕过（同 AOP 失效原因）|
| 第二层 | `REQUIRES_NEW` 和 `REQUIRED` 的区别？ | 挂起现有事务 vs 加入现有事务 |
| 第三层 | checked Exception 默认不回滚，为什么？ | Spring 设计哲学：checked 异常是可预期的业务异常 |

**实战型考法**：「你遇到过事务不生效的情况吗？怎么排查的？」

**面试话术总结**：

> 回答思路：先说「7 种传播行为」，再讲「事务失效的常见原因」（面试高频）。

- **7 种传播行为**（必须能说出常用的 3~4 种）：
  - `REQUIRED`（默认）：有事务加入，没有就新建
  - `REQUIRES_NEW`：总是新建事务，挂起当前事务
  - `NESTED`：嵌套事务（savepoint），外层回滚影响内层，内层回滚不影响外层
  - `SUPPORTS`：有事务加入，没有非事务执行
  - `NOT_SUPPORTED`：非事务执行，挂起当前事务
  - `MANDATORY`：必须在事务中，否则异常
  - `NEVER`：不能在事务中，否则异常
- **事务失效的常见原因**（面试必问）：
  1. 同类方法调用（this.xxx 绕过代理）
  2. 方法不是 `public`（Spring AOP 只代理 public 方法）
  3. 异常被 catch 了没抛出（事务只对抛出的异常回滚）
  4. 抛出了 checked Exception（默认只回滚 RuntimeException，需配 `rollbackFor = Exception.class`）
  5. 数据库引擎不支持事务（MyISAM 不支持，InnoDB 支持）
  6. Bean 没被 Spring 管理（自己 new 的对象）
- **`@Transactional` 最佳实践**：标注在 Service 层 public 方法上；指定 `rollbackFor = Exception.class`；避免大事务（事务方法尽量短）

---

## Spring Boot 自动配置

**关联知识文档**：[[04_Spring生态/04_SpringBoot自动配置/SpringBoot自动配置]]

**第一问**：「Spring Boot 怎么实现自动配置的？」

| 追问层次 | 追问 | 考点 |
|---------|------|------|
| 第一层 | `@SpringBootApplication` 做了什么？ | `@SpringBootConfiguration` + `@EnableAutoConfiguration` + `@ComponentScan` |
| 第二层 | `@ConditionalOnMissingBean` 为什么能保证用户 Bean 优先？ | 用户配置的 BeanDefinition 先加载 |
| 第三层 | Spring Boot 2.x 和 3.x 的自动配置文件有什么区别？ | `spring.factories` → `META-INF/spring/org.springframework.boot.autoconfigure.AutoConfiguration.imports` |

**面试话术总结**：

- **自动配置核心**：`@EnableAutoConfiguration` → `@Import(AutoConfigurationImportSelector.class)` → 读取 `META-INF/spring.factories`（2.x）或 `AutoConfiguration.imports`（3.x）→ 加载候选配置类 → `@Conditional` 系列注解判断是否生效
- **常用条件注解**：
  - `@ConditionalOnClass`：classpath 中存在某类才生效
  - `@ConditionalOnMissingBean`：容器中不存在某 Bean 才生效（用户自定义优先）
  - `@ConditionalOnProperty`：配置文件中有某属性才生效
- **Spring Boot 3.x 变化**：去掉了 `spring.factories` 的自动配置注册方式，改用 `imports` 文件；底层从 `spring-boot-autoconfigure` 模块迁移到 `AutoConfiguration` 包下

---

## Spring Boot 启动流程

**关联知识文档**：[[04_Spring生态/04_SpringBoot自动配置/SpringBoot自动配置]]

**第一问**：「`SpringApplication.run()` 做了什么？」

| 追问层次 | 追问 | 考点 |
|---------|------|------|
| 第一层 | `refresh()` 的核心步骤有哪些？ | instantiate / populate / initialize / post-process |
| 第二层 | `ApplicationContextInitializer` 和 `ApplicationListener` 的执行时机？ | 初始化器在 refresh 前 / 监听器在 refresh 后 |
| 第三层 | `onRefresh()` 在 Web 场景做了什么？ | 创建内嵌 Tomcat / Jetty |

**面试话术总结**：

- **`run()` 核心流程**（简化版，必须能口述）：
  1. 创建 `SpringApplication` → 推断应用类型（SERVLET/REACTIVE/NONE）
  2. 加载 `ApplicationContextInitializer` 和 `ApplicationListener`
  3. 执行 `run()` → 启动 `StopWatch` → 发布 `ApplicationStartingEvent`
  4. 准备 Environment（加载配置文件）
  5. 打印 Banner
  6. 创建 `ApplicationContext`（根据类型选择）
  7. `refresh()` 核心流程（Bean 加载、AOP 代理、自动配置生效）
  8. 发布 `ApplicationStartedEvent` → 执行 `CommandLineRunner`/`ApplicationRunner`

---

## 循环依赖

**关联知识文档**：[[04_Spring生态/05_循环依赖/循环依赖]]

**第一问**：「Spring 怎么解决循环依赖的？」

| 追问层次 | 追问 | 考点 |
|---------|------|------|
| 第一层 | 三级缓存分别是什么？各自存什么？ | singletonObjects / earlySingletonObjects / singletonFactories |
| 第二层 | 为什么需要三级缓存？两级不行吗？ | 第三级缓存延迟生成代理对象 |
| 第三层 | 构造器注入的循环依赖能解决吗？ | 不能，只能解决 setter 注入的循环依赖 |

**面试话术总结**：

- **三级缓存**：
  - **一级缓存** `singletonObjects`：存放完全初始化好的单例 Bean
  - **二级缓存** `earlySingletonObjects`：存放提前暴露的早期 Bean 引用（可能有代理）
  - **三级缓存** `singletonFactories`：存放 `ObjectFactory`（Bean 的工厂，用于提前创建代理）
- **解决流程**（A 依赖 B，B 依赖 A）：
  1. 创建 A → 放入三级缓存（ObjectFactory）→ 属性注入发现需要 B
  2. 创建 B → 放入三级缓存 → 属性注入发现需要 A → 从三级缓存拿到 A 的早期引用（或代理）→ B 完成 → 放入一级缓存
  3. A 继续属性注入 → A 完成 → 放入一级缓存
- **为什么需要三级缓存**：如果 A 需要 AOP 代理，第三级缓存的 `ObjectFactory.getObject()` 可以延迟决定是否需要代理对象，保证代理创建时机正确
- **构造器注入**无法解决：因为还没来得及创建 Bean 放入三级缓存，就已经需要依赖了 → 报 `BeanCurrentlyInCreationException`

---

## Spring Cloud 注册发现

**关联知识文档**：[[04_Spring生态/06_微服务/微服务]]

**第一问**：「Eureka 和 Nacos 的区别？」

| 追问层次 | 追问 | 考点 |
|---------|------|------|
| 第一层 | Eureka 的自我保护机制是什么？ | 心跳丢失 > 15% → 停止剔除 |
| 第二层 | Nacos 如何同时支持 CP 和 AP？ | Raft 协议 + 心跳机制 |
| 第三层 | 注册中心挂了，服务还能调用吗？ | 本地缓存 + 已建立的连接仍可用 |

**面试话术总结**：

- **Eureka**（AP）：每个节点都是对等的 P2P 架构；自我保护机制：短时间内丢失大量心跳 → 认为是网络问题而非服务下线 → 停止剔除 → 保护可用性
- **Nacos**：支持临时实例（AP，心跳模式）+ 持久实例（CP，Raft 协议）；临时实例和 Eureka 类似；持久实例强一致性，适合配置中心
- **注册中心挂了**：服务调用者本地有缓存（Eureka 每 30s 刷新一次），已建立的长连接不受影响；但新服务无法注册、已有服务下线无法感知

---

## Spring Cloud Gateway

**关联知识文档**：[[04_Spring生态/06_微服务/微服务]]

**第一问**：「Gateway 和 Zuul 的区别？」

| 追问层次 | 追问 | 考点 |
|---------|------|------|
| 第一层 | Gateway 基于什么模型？为什么性能高？ | WebFlux + Netty（非阻塞异步）|
| 第二层 | Gateway 的过滤器链有哪些类型？ | GlobalFilter（全局）/ GatewayFilter（路由级）|
| 第三层 | 怎么实现统一认证？ | 自定义 GlobalFilter 校验 Token |

**面试话术总结**：

- **Gateway vs Zuul**：
  - Gateway 基于 Spring WebFlux + Netty（非阻塞，异步），性能远高于 Zuul 1.x
  - Zuul 1.x 基于 Servlet（同步阻塞），每个请求一个线程
  - Zuul 2.x 也改用 Netty，但 Gateway 与 Spring Cloud 生态集成更好
- **核心概念**：Route（路由规则）、Predicate（断言，匹配请求）、Filter（过滤器）
- **统一认证**：自定义 `GlobalFilter` 实现 `filter()` 方法，从请求头/Header 取 Token → 校验 → 放行或返回 401

---

## P8 架构型考法汇总

> P8 级别开放设计题，考察技术整合与架构决策能力。

1. **如何设计一个支持热部署的模块化 Spring 应用？**
   - 考点：Spring DevTools、自定义 ClassLoader、Bean 重载、状态保持
2. **如何设计一个全链路监控系统的埋点方案？**
   - 考点：AOP 统一埋点、TraceId 传递、采样率控制、低开销设计
3. **如何设计一个支撑 1000 个微服务的 Spring Cloud 架构？**
   - 考点：注册中心选型、配置中心、灰度发布、服务治理
4. **如何设计一个高可用的 Spring Boot Starter 给全公司用？**
   - 考点：自动配置原理、条件装配、健康监测、隔离设计
