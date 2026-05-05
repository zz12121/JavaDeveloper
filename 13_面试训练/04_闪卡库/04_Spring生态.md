# 闪卡库：04_Spring生态

> 使用说明：本闪卡库可导入 Obsidian Spaced Repetition 插件或 Anki。按主题分组，覆盖 Spring 核心高频知识点。

---

## 1. IoC 与 Bean

**Q: IoC 的本质是什么？**

**A:**
**控制反转**：把对象创建和依赖管理的控制权从应用代码转移到 Spring 容器。

```
传统方式：                    IoC 方式：
  应用代码new对象               容器创建对象
       ↓                          ↓
  自己管理依赖                  容器注入依赖

好处：
  - 松耦合：对象不需要知道依赖的具体实现
  - 可测试：Mock 依赖很容易
  - 可复用：对象可以被不同容器实例化
```

**Tags:** #Spring #IoC #控制反转

---

**Q: BeanFactory 和 ApplicationContext 的区别？**

**A:**
| 维度 | BeanFactory | ApplicationContext |
|------|-------------|-------------------|
| 初始化 | 懒加载（第一次 getBean 才创建） | 预加载（容器启动时创建所有单例 Bean） |
| 功能 | 基础 DI 容器 | 扩展：事件机制、资源加载、AOP、国际化 |
| 适用场景 | 移动/嵌入式（资源受限） | 企业应用（主流选择） |
| 性能 | 启动快但第一次 getBean 慢 | 启动慢但运行时稳定 |

**Tags:** #Spring #IoC #ApplicationContext

---

**Q: Bean 的生命周期？**

**A:**
```
1. 实例化（Instantiation）    — new Object()
2. 属性填充（Populate）       — @Autowired / setXxx() 注入依赖
3. BeanNameAware              — setBeanName()
4. BeanFactoryAware            — setBeanFactory()
5. ApplicationContextAware     — setApplicationContext()
6. BeanPostProcessor 前置处理 — postProcessBeforeInitialization()
7. @PostConstruct             — 自定义初始化方法
8. InitializingBean           — afterPropertiesSet()
9. 自定义 init-method         — init-method
10. BeanPostProcessor 后置处理 — postProcessAfterInitialization()
11. 使用中...
12. @PreDestroy / DisposableBean / destroy-method — 销毁阶段
```

**Tags:** #Spring #IoC #Bean生命周期

---

## 2. AOP

**Q: JDK 动态代理 vs CGLIB 的区别？**

**A:**
```
JDK 动态代理：
  - 要求：目标类必须实现接口
  - 原理：实现接口，方法调用路由到 InvocationHandler
  - 生成：Proxy.newProxyInstance() 动态生成 $Proxy 类
  - 性能：每次反射调用，比 CGLIB 稍慢

CGLIB 代理：
  - 要求：无限制（通过继承生成子类）
  - 原理：继承目标类，覆盖所有非 final 方法
  - 生成：Enhancer 生成子类字节码
  - 性能：无反射，直接方法调用，比 JDK 快

Spring 默认（Spring Boot 2.0+）：
  → proxyTargetClass = true → 大多数情况用 CGLIB
  → 只有目标类实现了接口且 proxyTargetClass=false 时才用 JDK

坑：final 方法不能被 CGLIB 拦截！
```

**Tags:** #Spring #AOP #代理

---

**Q: Spring AOP 的通知类型？**

**A:**
```
@Before              — 方法执行前（Joint Point 之前）
@AfterReturning      — 方法正常返回后（不捕获异常）
@AfterThrowing       — 方法抛出异常后
@After               — 方法执行后（无论正常/异常，类似 finally）
@Around             — 方法执行前后（最强大，可以修改参数/返回值/阻止执行）

@Around 的典型用法：
  @Around("切入点")
  public Object logTime(ProceedingJoinPoint pjp) {
      long start = System.nanoTime();
      Object result = pjp.proceed();  // 调用原方法
      log.info("{} 耗时 {}ms", pjp.getSignature(), (System.nanoTime()-start)/1e6);
      return result;
  }
```

**Tags:** #Spring #AOP #通知

---

**Q: Spring AOP 的织入时机？**

**A:**
```
织入（Weaving）：把切面代码插入到目标对象

时机：
  编译期织入    — 需要特殊编译器（AspectJ 编译器），编译后即有 AOP
  类加载期织入  — JVM 加载类时织入（Spring 支持，需要配置）
  运行期织入    — Spring AOP（默认），Bean 初始化时创建代理对象

Spring AOP = 运行期织入：
  Bean 创建 → 判断需要代理 → 生成代理对象 → 替换原 Bean 引用
  调用时：代理对象拦截 → 执行通知 → 调用原方法（或通过原方法）
```

**Tags:** #Spring #AOP #织入

---

## 3. 事务

**Q: @Transactional 为什么会失效？**

**A:**
```
失效场景（最常见）：

1. 自调用（最坑！）
   @Service
   class A {
       @Transactional
       public void methodA() { this.methodB(); }  // ❌ 不走代理
       @Transactional
       public void methodB() { }  // methodA 直接调用 methodB，跳过代理
   }

   解决：注入自身 Bean → aSelf.methodB()

2. 非 public 方法
   → @Transactional 只对 public 方法生效

3. 异常被 catch 吞掉
   → 只有抛出 RuntimeException/Error 时才回滚
   → 解决：rollbackFor = Exception.class

4. 多数据源未指定
   → @Transactional 默认作用于主数据源
   → 解决：@Transactional(dataSource = "xxx")

5. 事务传播行为不当
   → PROPAGATION_REQUIRES_NEW 会挂起外层事务
```

**Tags:** #Spring #事务 #Transactional

---

**Q: 事务的 7 种传播行为？**

**A:**
```
REQUIRED（默认）：       有事务就加入，没有就创建新事务
SUPPORTS：              有事务就加入，没有就不以事务运行
MANDATORY：             必须有事务，没有则抛异常
REQUIRES_NEW：          无论如何都创建新事务，挂起外层事务
NOT_SUPPORTED：         以非事务运行，挂起外层事务
NEVER：                 必须没有事务，有则抛异常
NESTED：                有事务则嵌套执行，没有则创建新事务（Jdbc 3.0 Savepoint）

实战场景：
  - REQUIRED：普通业务方法（默认，够用）
  - REQUIRES_NEW：记录审计日志（不影响主事务提交）
  - NESTED：子任务失败回滚到保存点（主事务继续）
```

**Tags:** #Spring #事务 #传播行为

---

## 4. 循环依赖

**Q: Spring 如何解决循环依赖？**

**A:**
```
循环依赖：A 依赖 B，B 依赖 A

三级缓存（singletonObjects / earlySingletonObjects / singletonFactories）：
  一级（singletonObjects）：完整 Bean（刚创建完成）
  二级（earlySingletonObjects）：早期暴露的 Bean（属性填充完成，但未初始化）
  三级（singletonFactories）：Bean 工厂（创建中，getEarlyBeanReference）

流程：
  1. 创建 A，存入三级缓存
  2. 注入 A 的属性时发现依赖 B
  3. 创建 B，存入三级缓存
  4. 注入 B 的属性时发现依赖 A
  5. 从三级缓存拿到 A 的工厂，创建 A 的早期引用
  6. B 创建完成，移到一级缓存
  7. A 继续创建，拿到 B 的引用
  8. A 创建完成，移到一级缓存

⚠️ 构造器注入的循环依赖无法解决（Spring 6.x 默认禁止）
```

**Tags:** #Spring #循环依赖 #三级缓存

---

**Q: 为什么 Spring 默认禁止构造器注入的循环依赖？**

**A:**
```
构造器注入循环依赖无法解决的原因：

  创建 A → 需要构造器注入 B
  创建 B → 需要构造器注入 A

此时 A 和 B 都没有完成创建，无法提前暴露引用。
（属性注入可以在属性填充阶段提前暴露早期引用）

Spring 6.x（Spring Boot 3.x）：
  → 构造器循环依赖默认抛出 BeanCurrentlyInCreationException
  → 字段注入和 setter 注入不受影响

解决方式：
  1. 改用 @Lazy 懒加载
  2. 改用 setter 注入
  3. 用 ObjectProvider / Provider<T>
  4. 重新设计依赖关系
```

**Tags:** #Spring #循环依赖 #构造器注入

---

## 5. Spring Boot

**Q: Spring Boot 自动配置原理？**

**A:**
```
@EnableAutoConfiguration 触发自动配置

源码路径：
  @EnableAutoConfiguration
    → @Import(AutoConfigurationImportSelector.class)
      → AutoConfigurationImportSelector.selectImports()
        → SpringFactoriesLoader.loadFactoryNames(EnableAutoConfiguration)
          → 加载 META-INF/spring.factories（JDK 6~8）
          → 加载 META-INF/spring/org.springframework.boot.autoconfigure.AutoConfiguration.imports（JDK 9+）

原理：
  1. 加载所有 auto-configuration 类
  2. @Conditional 条件过滤（只有条件满足才生效）
  3. Bean 创建并注入

核心注解：@ConditionalOnClass / @ConditionalOnBean / @ConditionalOnMissingBean
  → 确保只有依赖的类存在时才会创建 Bean
  → 用户自定义 Bean 优先于自动配置
```

**Tags:** #SpringBoot #自动配置 #@Conditional

---

**Q: Spring Boot 的启动流程？**

**A:**
```
SpringApplication.run() 流程：

1. 创建 SpringApplication 对象
   → 判断是否是 Web 环境（classpath 中有没有 Spring MVC/Spring WebFlux）
   → 加载 spring.factories 中的 ApplicationContextInitializer

2. run() 执行：
   (1) 创建 BootstrapContext（引导上下文）
   (2) 配置 Headless Property
   (3) 获取并启动 SpringApplicationRunListeners
   (4) 准备 Environment（加载 application.yml 等）
   (5) 打印 Banner（启动横幅）
   (6) 创建 ApplicationContext
   (7) 准备 Context（设置 Environment、加载 Bean 定义）
   (8) 刷新 Context ← 核心！→ Bean 创建、组件扫描、自动配置
   (9) 刷新后处理（执行 Runner）
   (10) 返回 Context
```

**Tags:** #SpringBoot #启动流程

---

## 6. Spring MVC

**Q: Spring MVC 请求处理流程？**

**A:**
```
请求 → DispatcherServlet（前端控制器）
  ↓
HandlerMapping 查找 Handler（Controller 方法）
  ↓
HandlerAdapter 执行 Handler
  ↓
处理 Handler 的返回值
  ↓
ViewResolver 解析视图
  ↓
View 渲染
  ↓
响应

关键组件：
  DispatcherServlet     — 入口（统一分发请求）
  HandlerMapping         — @RequestMapping 映射表
  HandlerAdapter        — 适配器模式（执行 Controller）
  HandlerExceptionResolver — 全局异常处理
  ViewResolver          — 逻辑视图名 → 物理视图
  MultipartResolver     — 文件上传
```

**Tags:** #SpringMVC #请求处理 #DispatcherServlet

---

**Q: Spring MVC 的参数绑定原理？**

**A:**
```java
// 常用参数绑定
@RequestParam          — 请求参数（?name=xxx）
@PathVariable          — 路径变量（/user/{id}）
@RequestHeader         — 请求头
@CookieValue          — Cookie
@RequestBody          — JSON/XML 请求体（反序列化）
@ModelAttribute        — 表单对象绑定

原理：
  HandlerAdapter.invoke()
    → RequestResponseBodyMethodProcessor 处理 @RequestBody
      → HttpMessageConverter（Jackson/Gson）反序列化
    → ModelAttributeMethodProcessor 处理普通参数
      → 数据类型转换（ConversionService）
      → 参数校验（Validator）
```

**Tags:** #SpringMVC #参数绑定 #@RequestBody

---

*生成时间：2026-05-05*
