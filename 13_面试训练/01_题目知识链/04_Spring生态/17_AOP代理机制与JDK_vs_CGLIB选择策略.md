# AOP 代理机制与 JDK vs CGLIB 选择策略

> ⚠️ **先盲答**：Spring AOP 是如何在不修改源码的情况下增强方法的？JDK 动态代理和 CGLIB 有什么区别？

---

## 盲答引导

1. AOP 的核心概念：切点（Pointcut）/ 通知（Advice）/ 切面（Aspect）？
2. JDK 动态代理和 CGLIB 代理的实现原理？
3. Spring Boot 默认用哪种代理？为什么？
4. 什么情况下 CGLIB 也无法代理？

---

## 知识链提示

```
AOP 代理机制
  → [[04_Spring生态/01_Spring核心/AOP]]
    → 1. AOP 核心概念
      → Aspect（切面）：= Pointcut + Advice
      → JoinPoint（连接点）：程序执行点（方法调用 / 异常抛出）
      → Pointcut（切点）：哪些方法需要被增强（表达式匹配）
      → Advice（通知）：增强逻辑，分五种：
        → @Before / @AfterReturning / @AfterThrowing / @After / @Around
      → Weaving（织入）：把增强逻辑织入目标对象的过程
    → 2. 代理方式一：JDK 动态代理
      → 基于接口（Proxy + InvocationHandler）
        → Proxy.newProxyInstance(ClassLoader, interfaces[], InvocationHandler)
        → 生成的代理类继承了 Proxy，实现了目标接口
      → 限制：目标类必须实现接口
      → 调用流程：代理对象 → InvocationHandler.invoke() → 目标方法
    → 3. 代理方式二：CGLIB 代理
      → 基于继承（生成目标类的子类）
        → 使用 ASM 字节码框架，运行时生成子类字节码
        → 重写父类方法，在方法前后插入增强逻辑
      → 限制：目标类不能是 final；目标方法不能是 final
      → 调用流程：子类代理 → 方法体内调用拦截器链 → 目标方法
    → 4. Spring 的代理选择策略
      → Spring Boot 2.x 之前：默认 JDK 动态代理（需强制用 CGLIB 要配置）
      → Spring Boot 2.x 开始：默认 CGLIB（proxyTargetClass=true）
        → 原因：JDK 动态代理只能代理接口方法，CGLIB 可以代理普通类
        → 配置：spring.aop.proxy-target-class=true（默认就是 true）
    → 5. 代理的创建时机
      → AbstractAutoProxyCreator.postProcessAfterInitialization()
        → 初始化完成后，判断 Bean 是否被 AOP 切点匹配
        → 匹配则 wrapIfNecessary() → 创建代理对象
    → 6. 调用流程（以 @Around 为例）
      → 代理对象.方法()
        → CglibAopProxy.intercept() / JdkDynamicAopProxy.invoke()
        → 获取该方法的拦截器链（MethodInterceptor 列表）
        → ReflectiveMethodInvocation.proceed() → 链式调用所有 Advice
        → 最后调用目标方法
    → 7. 无法代理的情况
      → private 方法（CGLIB 可以代理 protected/package，但 Spring AOP 限制为 public）
      → final 方法（CGLIB 无法重写）
      → 自调用（this.方法() 不经过代理）
```

---

## 核心追问

| 追问 | 考点 |
|------|------|
| @Around 和 @Before + @After 的区别？ | @Around 完全控制方法调用（可决定是否执行、修改参数/返回值），功能最强 |
| 同一个方法被多个 Aspect 增强，执行顺序？ | @Order 注解 / 实现 Ordered 接口，值越小越先执行（Before 正序，After 倒序） |
| CGLIB 生成的子类存放在哪里？ | 默认在堆内存（Metaspace），使用 SoftReference 缓存，可配置缓存策略 |
| 目标方法是 final 会怎样？ | CGLIB 无法重写 final 方法，调用时直接执行目标方法（增强失效，无报错！） |

---

## 参考答案要点

**JDK 动态代理**：基于接口，生成的代理类继承 `Proxy`，实现目标接口；限制：必须有接口。

**CGLIB 代理**：基于继承，生成目标类的子类，重写方法插入增强；限制：类不能是 `final`，方法不能是 `final`。

**SpringBoot 默认 CGLIB**：因为实际开发中很多类没有接口，CGLIB 覆盖范围更广；配置项 `spring.aop.proxy-target-class=true`（默认开启）。

**调用链**：代理对象 → 获取拦截器链 → `ReflectiveMethodInvocation.proceed()` 链式调用 → 目标方法。

**自调用问题**：`this.method()` 不经过代理，AOP 失效；解决：拆到另一个 Bean，或通过 `AopContext.currentProxy()` 获取代理。

---

## 下一步

打开 [[04_Spring生态/01_Spring核心/AOP]]，补充 `双向链接`：「AOP 的本质是代理模式——JDK 代理基于接口，CGLIB 基于继承；SpringBoot 默认 CGLIB 是因为它不要求目标类实现接口」。
