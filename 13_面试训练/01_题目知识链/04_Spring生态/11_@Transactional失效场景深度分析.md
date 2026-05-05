# @Transactional 失效场景深度分析

> ⚠️ **先盲答**：什么情况下 @Transactional 不生效？失效的根本原因是什么？

---

## 盲答引导

1. @Transactional 的本质是什么？—— AOP 代理 + 事务拦截器（TransactionInterceptor）
2. 哪些场景会导致事务不回滚或根本不开启？
3. Spring 事务的传播行为有哪些？默认是什么？
4. 异常类型与回滚规则的关系？

---

## 知识链提示

```
@Transactional 失效
  → [[05_持久层框架/01_MyBatis/08_事务管理]]
    → 本质：AOP 动态代理，方法调用实际上是代理对象的方法
      → 自调用问题（最常见）
        → 同一个类中，methodA() 调用 methodB()（@Transactional）
        → 直接调用，不经过代理对象 → 事务不生效
        → 原因：Spring 事务基于代理，自调用绕过了代理
        → 解决：通过 AopContext.currentProxy() 获取代理 / 拆分到另一个 Bean
    → 访问权限问题
      → 方法必须是 public（CGLIB 可以代理 protected，但 @Transactional 官方要求 public）
      → private / package-private 方法加 @Transactional 不生效（无代理）
    → 异常类型不匹配
      → 默认只回滚 RuntimeException 和 Error
      → checked 异常（Exception 子类但不是 RuntimeException）默认不回滚
      → 解决：@Transactional(rollbackFor = Exception.class)
    → 异常被 catch 吃掉
      → 方法内 try-catch 了异常，没有重新抛出 → 事务拦截器感知不到异常 → 不回滚
    → 传播行为配置错误
      → REQUIRED（默认）：当前有事务就加入，没有就新建
      → REQUIRES_NEW：挂起当前事务，新建事务（内外事务独立）
      → SUPPORTS：有事务就加入，没有就以非事务方式执行（可能不生效）
      → NOT_SUPPORTED：以非事务方式执行（挂起当前事务）
    → 数据库引擎不支持
      → MyISAM 不支持事务，只有 InnoDB 支持
    → 数据源没有配置事务管理器
      → 缺少 @EnableTransactionManagement
      → 没有配置 PlatformTransactionManager Bean
    → 多线程场景
      → 事务信息存储在 ThreadLocal（TransactionSynchronizationManager）
      → 新线程无法访问父线程的事务上下文 → 事务不传播
```

---

## 核心追问

| 追问 | 考点 |
|------|------|
| REQUIRED vs REQUIRES_NEW 的嵌套回滚行为？ | REQUIRED 内层抛异常，外层 catch 后外层可继续；REQUIRES_NEW 内层独立，外层异常不影响内层 |
| 事务的传播行为是在哪里实现的？ | AbstractPlatformTransactionManager.handleExistingTransaction() |
| @Transactional 可以加在类上吗？ | 可以，类中所有 public 方法都继承该事务配置 |
| 只读事务（readOnly=true）有什么用？ | 提示数据库做优化（如 MySQL 的只读事务可以避免某些锁）；代码内不允许修改数据 |

---

## 参考答案要点

**自调用问题**是最高频失效原因：Spring 事务基于 AOP 代理，`this.method()` 调用不经过代理，事务注解失效。

**异常规则**：默认只回滚 `RuntimeException` 和 `Error`，Checked 异常需显式配置 `rollbackFor`。

**传播行为**：默认 `REQUIRED`，理解 7 种传播行为的关键是「当前是否存在事务」这个前提。

**多线程**：事务上下文在 ThreadLocal 中，跨线程无法传播，这是 Spring 事务的设计限制。

---

## 下一步

打开 [[05_持久层框架/01_MyBatis/08_事务管理]]，补充 `双向链接`：「@Transactional 失效的底层逻辑始终是：代理没生效 / 异常没抛出 / 传播行为不匹配 —— 三者必居其一」。
