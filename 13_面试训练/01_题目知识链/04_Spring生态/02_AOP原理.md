# AOP 是什么？它的实现原理是什么？

> ⚠️ **先盲答**：面向切面编程（AOP）是什么？能解决什么问题？

---

## 盲答引导

1. AOP 的核心概念有哪些？—— 切点（Pointcut）/ 通知（Advice）/ 切面（Aspect）/ 连接点（Join Point）
2. Spring AOP 的实现原理是什么？—— 动态代理（JDK 动态代理 / CGLib）
3. JDK 动态代理和 CGLib 的区别？—— 接口 vs 继承
4. 事务注解 `@Transactional` 的内部实现是什么？—— AOP + 事务拦截器

---

## 知识链提示

```
AOP 面向切面编程
  → [[04_Spring生态/01_Spring核心/AOP]]
    → 核心概念
      → Aspect（切面）：切点和通知的结合
      → Join Point（连接点）：程序执行点（方法调用/异常抛出等）
      → Pointcut（切点）：定义哪些 Join Point 会被拦截
      → Advice（通知）：拦截后要做什么
        → @Before / @After / @AfterReturning / @AfterThrowing / @Around
    → 实现原理：动态代理
      → JDK 动态代理：基于接口（Proxy + InvocationHandler）
        → 只能代理实现了接口的类
      → CGLib 动态代理：基于继承（生成子类）
        → 能代理普通类（CGLib 通过继承被代理类，覆写方法）
        → 不能代理 final 类 / final 方法
      → Spring 选择策略
        → 目标类实现了接口 → JDK 动态代理
        → 目标类没实现接口 → CGLib
    → 事务实现
      → [[05_持久层框架/01_MyBatis/08_事务管理]] → TransactionInterceptor → AOP 拦截 @Transactional 方法
        → 开启事务 → 执行业务 → 正常提交 / 异常回滚
```

---

## 核心追问

| 追问 | 考点 |
|------|------|
| 同一个方法被多个 Aspect 拦截，执行顺序是什么？ | @Order 注解 / Ordered 接口 |
| @Around 和 @Before + @After 有什么区别？ | @Around 能控制是否执行目标方法 |
| CGLib 为什么不能代理 final 方法？ | 继承重写，final 方法不能重写 |
| AspectJ 和 Spring AOP 的区别？ | AspectJ 编译期/类加载期织入，Spring AOP 运行时动态代理 |

---

## 参考答案要点

**JDK 动态代理 vs CGLib**：

| 维度 | JDK 动态代理 | CGLib |
|------|----------------|--------|
| 原理 | 实现接口（Proxy） | 继承（生成子类） |
| 要求 | 目标类必须实现接口 | 目标类不能是 final |
| 性能 | JDK 8+ 差不多 | JDK 8+ 差不多 |

**事务注解失效的常见原因**：
- 没标记为 `public`（Spring AOP 只能拦截 public 方法）
- 自调用（同一个类里的 A() 调用 B()，B 有 @Transactional，但不生效）

---

## 下一步

打开 [[04_Spring生态/01_Spring核心/AOP]]，补充 `双向链接`：「AOP 的本质是动态代理——JDK 动态代理要求接口，CGLib 通过继承实现，两者在 Spring 里自动切换」。
