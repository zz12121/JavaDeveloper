# CompletableFuture 是什么？它解决了什么问题？

> ⚠️ **先盲答**：为什么需要 CompletableFuture？它比 Future 好在哪里？

---

## 盲答引导

1. Future 的局限性是什么？—— get() 阻塞、不能组合、不能手动完成
2. CompletableFuture 怎么解决这些问题？
3. `thenApply`、`thenCompose`、`thenCombine` 分别是干什么的？
4. 什么叫**异步编程**？CompletableFuture 在其中扮演什么角色？

---

## 知识链提示

```
CompletableFuture 异步编排
  → [[CompletableFuture异步编排]]
    → Future 的局限
      → get() 阻塞 → 轮询浪费 CPU
      → 不能组合多个 Future → then chaining 做不到
      → 不能手动完成 → 回调注册做不到
    → CompletableFuture 的增强
      → supplyAsync / runAsync：异步执行
        → [[线程池]] → 默认 ForkJoinPool.commonPool()
      → thenApply：串行转换（A → B）
      → thenCompose：扁平化串联（返回 Future 的链式调用）
      → thenCombine：并行合并（等两个都完成再合并）
      → exceptionally / handle：异常处理
    → 应用场景
      → 多个无依赖的接口并行调用 → thenCombine 合并结果
      → 链式调用 → thenCompose
      → [[Virtual线程]] → CompletableFuture + 虚拟线程 = 高并发 IO
```

---

## 核心追问

| 追问 | 考点 |
|------|------|
| thenApply 和 thenCompose 的区别？ | flatMap vs map |
| CompletableFuture 默认用哪个线程池？ | ForkJoinPool.commonPool |
| 如果异步任务抛了异常，thenApply 还能执行吗？ | 异常会传播 |
| 如何处理超时？ | orTimeout / completeOnTimeout |

---

## 参考答案要点

**Future 的局限**：阻塞等待，不能组合，无法处理异常回调。

**CompletableFuture 的核心价值**：非阻塞 + 链式编排 + 并行合并。

| 方法 | 语义 |
|------|------|
| thenApply | 串行转换：`int → String` |
| thenCompose | 扁平化串联：`A → CompletableFuture<B>` → `B` |
| thenCombine | 并行合并：`CompletableFuture<A>` + `CompletableFuture<B>` → `C` |

---

## 下一步

打开 [[CompletableFuture异步编排]]，对比 [[Virtual线程]]，补充链接：「CompletableFuture 适合 IO 密集型并行，而 JDK 21 的虚拟线程让每个任务不再消耗 OS 线程，两者结合是现代高并发的主流写法」。
