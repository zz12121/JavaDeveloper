# AOP切面编程

## 这个问题为什么存在？

> 如果没有 AOP，横向切面逻辑（事务、日志、安全、缓存）会散布在业务代码各处：每个方法都要手动 `try-catch`、每个 Service 都要 `beginTransaction`。问题是：**横切关注点与业务逻辑耦合**，代码无法复用，修改一处要动 N 个地方，改错了还会影响业务本身。

AOP 的本质是**把「做什么」从「在哪里做」中分离出来**。用代理模式在方法前后插入横切逻辑，业务代码不知道它的存在。

## 它是怎么解决问题的？

### 核心概念

```
切面（Aspect）：横切关注点的完整封装（Pointcut + Advice + 切面类）
连接点（Join Point）：程序执行的某个位置（方法调用、异常抛出等）
切入点（Pointcut）：匹配连接点的表达式，精确圈定哪些位置需要增强
通知（Advice）：切入点上执行的具体动作（Before / After / AfterReturning / AfterThrowing / Around）
织入（Weaving）：把切面代码插入到目标对象的过程（编译期 / 类加载期 / 运行期）
```

### Spring AOP 的两种代理机制

**JDK 动态代理**——要求目标类实现了接口。

```java
public class JdkProxyFactory {
    public static Object createProxy(Object target, Advice advice) {
        return Proxy.newProxyInstance(
            target.getClass().getClassLoader(),
            target.getClass().getInterfaces(),  // 必须是接口
            (proxy, method, args) -> {
                advice.before();
                Object result = method.invoke(target, args);
                advice.afterReturning();
                return result;
            }
        );
    }
}
```

生成的代理类：实现目标接口，方法调用全部路由到 `InvocationHandler.invoke()`。**没有接口的类用不了。**

**CGLIB 动态代理**——通过继承目标类生成子类，方法拦截用 `MethodInterceptor`。

```java
public class CglibProxyFactory {
    public static Object createProxy(Class<?> targetClass, Advice advice) {
        Enhancer enhancer = new Enhancer();
        enhancer.setSuperclass(targetClass);        // 设置父类
        enhancer.setCallback((MethodInterceptor) (proxy, method, args, methodProxy) -> {
            advice.before();
            Object result = methodProxy.invokeSuper(proxy, args);  // 调用父类方法
            advice.afterReturning();
            return result;
        });
        return enhancer.create();
    }
}
```

生成的代理类：继承自目标类，覆盖所有非 `final` 方法。**`final` 方法无法被重写拦截**。

### 代理选择逻辑（Spring 内部机制）

`ProxyFactory` 是 Spring AOP 的核心，它决定了用哪种代理：

```
ProxyFactory.setTargetClass(target)
    ↓
目标类实现了接口？ → YES → 默认使用 JDK 动态代理
    ↓ NO
    → 默认使用 CGLIB 代理

可通过 proxyTargetClass = true 强制使用 CGLIB（Spring 默认行为）
```

Spring Boot（从 2.0 开始）默认 `proxyTargetClass = true`，所以**大多数场景下走的是 CGLIB**，这是面试中容易搞错的地方。

```java
@EnableAspectJAutoProxy(proxyTargetClass = true)  // 默认值，强制 CGLIB
@EnableAspectJAutoProxy(proxyTargetClass = false) // 强制 JDK 动态代理
```

### ProxyFactory 源码关键路径

```java
// org.springframework.aop.framework.ProxyFactory
public Object getProxy(ClassLoader classLoader) {
    // 1. 选择代理方式
    createAopProxy().getProxy(classLoader);
}

// 实际在 DefaultAopProxyFactory 中决定
public AopProxy createAopProxy(AdvisedSupport config) {
    // optimize / proxyTargetClass / hasNoUserSuppliedProxyInterfaces
    if (config.isProxyTargetClass() || hasNoUserSuppliedProxyInterfaces(config)) {
        return new ObjenesisCglibAopProxy(config);  // CGLIB
    }
    return new JdkDynamicAopProxy(config);          // JDK
}
```

### 拦截方法 vs 被调用方法

一个高频混淆点：

- **JDK 动态代理**：`method.invoke(target, args)` —— `method` 是**接口方法**
- **CGLIB**：`methodProxy.invokeSuper(proxy, args)` —— `methodProxy` 是**子类覆盖方法**

用 CGLIB 时 `methodProxy.invokeSuper()` 不能传 `target`，因为 `target` 是原始对象，绕过代理就没有增强了。

### 织入时机

| 织入方式 | 时机 | 代表框架 |
|---|---|---|
| 编译期织入 | javac 编译时 | AspectJ (ajc) |
| 类加载期织入 | class 文件加载时 | AspectJ (javaagent) |
| 运行期织入 | 运行时通过代理 | Spring AOP（默认） |

Spring AOP 只支持**运行期织入**，只能拦截 Spring Bean 的方法。AspectJ 可以在编译期/加载期织入，功能更强但配置复杂。

## 它和相似方案的本质区别是什么？

### Spring AOP vs AspectJ

| | Spring AOP | AspectJ |
|---|---|---|
| 织入时机 | 运行期 | 编译期 / 类加载期 |
| 增强范围 | Spring Bean 的方法 | 任何方法（构造器、字段等） |
| 代理方式 | JDK / CGLIB | 编译器修改字节码 |
| 性能 | 有额外方法调用开销 | 接近零开销 |
| 依赖 | 只需 Spring | 需要 AspectJ 编译器或 agent |

**Spring AOP 的局限**：只能增强 Spring 管理的 Bean，非 Spring 对象（如 `new` 出来的普通对象）无法被 AOP 拦截。

### JDK 代理 vs CGLIB

| | JDK 动态代理 | CGLIB |
|---|---|---|
| 原理 | 接口实现 | 继承子类 |
| 要求 | 必须有接口 | 不能是 `final` 类/`final` 方法 |
| 生成的类 | 实现接口的匿名类 | 目标类的子类 |
| 性能 | JDK 8 后接近 CGLIB | 略优（生成字节码） |
| 构造器 | 不会调用目标构造器 | 会调用 |

Spring 5.x 后默认 CGLIB 的原因是：**JDK 动态代理生成的类不是 `targetClass` 的子类**，导致一些基于类型检查的场景（如 Spring Data JPA）出问题。

## 正确使用方式

### 正常用法

```java
@Aspect
@Component
public class PerformanceAspect {

    @Pointcut("execution(* com.example.service.*.*(..))")
    public void servicePointcut() {}

    @Around("servicePointcut()")
    public Object logTime(ProceedingJoinPoint pjp) throws Throwable {
        long start = System.currentTimeMillis();
        Object result = pjp.proceed();  // 必须调用，否则业务方法不执行
        long cost = System.currentTimeMillis() - start;
        log.info("方法 {} 耗时 {}ms", pjp.getSignature(), cost);
        return result;
    }
}
```

**`@Around` 通知必须显式调用 `pjp.proceed()`**，否则目标方法不会执行。这是容易出错的地方。

### Pointcut 表达式

```java
// 精确匹配
@Pointcut("execution(public void UserService.delete(Long))")

// 任意返回类型，service 包下所有方法
@Pointcut("execution(* com.example.service.*.*(..))")

// 注解匹配（最实用）
@Pointcut("@annotation(Logged)")
public void annotatedMethods() {}
```

### 错误用法

```java
@Aspect
@Component
public class BadAspect {
    @Around("execution(* *.*(..))")  // 太宽泛，拦截所有类，包括框架自身
    public Object ignore(ProceedingJoinPoint pjp) {
        return pjp.proceed();
    }
}
```

切入点太宽会导致**框架自身也被增强**，引发 StackOverflowError（代理递归调用自身）。

## 边界情况和坑

### 同一个类内部方法调用不走代理

```java
@Service
public class OrderService {
    public void create() {
        this.validate();  // this.validate() 不经过代理！
        doCreate();
    }

    @Transactional
    public void validate() { }  // 事务不生效
}
```

原因：`this` 指向的是原始对象，不是代理对象。内部调用绕过了 Spring 的代理机制。解决方案：
1. 注入自身：`@Autowired OrderService orderService;`
2. 用 `AopContext.currentProxy()` 获取代理对象
3. 抽取到另一个 Service

### CGLIB 代理下构造器被调用两次

CGLIB 通过 `Enhancer.create()` 创建实例时会调用两次构造器（一次生成代理，一次实际初始化）。如果构造器有副作用（如计数器、连接池初始化），要小心。

### `@Order` 和执行顺序

多个切面作用同一个连接点时，`@Order` 数值越小越先执行。但 `@Around` 的 Before 部分正序，After 部分反序：

```
@Order(1) before → @Order(2) before → 目标方法 → @Order(2) after → @Order(1) after
```

### 代理对象的类型判断

```java
UserService target = new UserService();
UserService proxy = (UserService) factory.getProxy();

target.getClass()  // class com.example.UserService
proxy.getClass()   // class com.example.UserService$$EnhancerByCGLIB$$xxx

proxy instanceof UserService  // Spring CGLIB 返回 true（JDK 代理返回 false）
```

## 我的理解

AOP 的核心就是**代理 + 切入点匹配**。Spring 在运行期通过 ProxyFactory 创建代理对象（JDK 或 CGLIB），把切面逻辑织入到匹配切入点的方法前后。面试中最重要的两个点：

1. **Spring Boot 默认 CGLIB**，不是因为 CGLIB 更快，而是因为生成的代理是目标类的子类，类型检查更兼容
2. **同类内部调用不走代理**，这是 Spring AOP 最大的坑，明白原理后就不容易踩了
