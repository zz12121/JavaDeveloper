# @Async 异步原理与线程池配置

> ⚠️ **先盲答**：@Async 是怎么让方法异步执行的？默认线程池是什么？如何自定义线程池？

---

## 盲答引导

1. `@EnabledAsync` 做了什么？
2. 异步方法的返回类型有哪些选择？
3. 默认的线程池是什么？有什么坑？
4. 异步方法内的异常如何捕获？
5. 异步方法和事务能一起用吗？

---

## 知识链提示

```
@Async 异步执行
  → Spring异步
    → 1. 启用异步：@EnableAsync
      → 导入 AsyncConfigurationSelector
      → 注册两个核心 Bean：
        → AsyncAnnotationBeanPostProcessor（AOP 代理）
        → AsyncAnnotationAdvisor（切点 + 通知）
      → mode 属性：PROXY（JDK/CGLIB）vs ASPECTJ（编译期织入，功能更强）
    → 2. 代理创建（AsyncAnnotationBeanPostProcessor）
      → 扫描所有 @Async / @Asynchronous（JSR-303）注解的方法
      → 创建代理对象（和 AOP 原理一样）
      → 方法调用被拦截，提交到线程池异步执行
    → 3. 线程池查找顺序（关键！）
      → ① 查找类型为 TaskExecutor 的 Bean（唯一）
      → ② 查找名称为 "taskExecutor" 的 Bean
      → ③ 如果都找不到 → 使用 SimpleAsyncTaskExecutor（每次新建线程！❌ 严重坑点）
      → 解决：自定义线程池 Bean，或实现 AsyncConfigurer 接口
    → 4. 自定义线程池（推荐方式）
      → @Bean("myExecutor") TaskExecutor taskExecutor() { ... }
      → @Async("myExecutor") 指定使用哪个线程池
      → 或者实现 AsyncConfigurer.getAsyncExecutor()
    → 5. 返回值类型
      → void：纯异步，无法获取结果
      → Future<T>：传统方式，get() 阻塞获取结果
      → CompletableFuture<T>：推荐（函数式回调，不阻塞）
      → ListenableFuture<T>：Spring 扩展（较少用）
    → 6. 异常处理
      → void 返回类型：异常会被吞掉（线程池的 UncaughtExceptionHandler）
      → Future/CompletableFuture：异常包装在 ExecutionException 中，get() 时抛出
      → 全局异常处理：实现 AsyncUncaughtExceptionHandler
    → 7. 事务问题
      → @Async 方法在新线程中执行
      → 事务上下文在 ThreadLocal 中 → 新线程没有事务！
      → 解决：异步方法内自己开启新事务（REQUIRES_NEW）
    → 8. 线程池配置参数（ThreadPoolTaskExecutor）
      → corePoolSize：核心线程数（默认 8）
      → maxPoolSize：最大线程数（默认 Integer.MAX_VALUE，危险！）
      → queueCapacity：队列容量（默认 Integer.MAX_VALUE，危险！）
      → keepAliveSeconds：空闲线程保活时间
      → ThreadNamePrefix：线程名前缀（方便排查）
```

---

## 核心追问

| 追问 | 考点 |
|------|------|
| 为什么默认线程池是个坑？ | SimpleAsyncTaskExecutor 每次新建线程，高并发下线程爆炸 |
| @Async 方法能是 private 吗？ | 不能，Spring AOP 代理无法拦截 private 方法 |
| 同一个类中，方法 A 调用 @Async 方法 B，会异步吗？ | 不会！自调用问题，不经过代理 |
| CompletableFuture 相比 Future 的优势？ | 函数式回调（thenApply/thenAccept）、异常链、不阻塞 |

---

## 参考答案要点

**启用**：`@EnableAsync` → 注册 AOP 代理处理器 → 拦截 @Async 方法 → 提交到线程池。

**默认线程池坑**：找不到自定义线程池时用 `SimpleAsyncTaskExecutor`——每次新建线程，高并发必炸。必须自定义。

**返回值选择**：`CompletableFuture<T>` 最灵活（链式回调 + 异常处理），避免阻塞。

**事务不传播**：新线程无事务上下文；异步方法内用 `REQUIRES_NEW` 开启新事务。

**异常处理**：void 返回类型异常会被吞；用 `CompletableFuture` 可以在回调中处理异常。

---

## 下一步

打开 Spring异步，补充 `双向链接`：「@Async 的本质是 AOP 代理 + 线程池提交；默认线程池是新线程爆炸源，必须自定义 ThreadPoolTaskExecutor」。
