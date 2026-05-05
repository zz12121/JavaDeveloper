# CompletableFuture 异步编排

> CompletableFuture 是 Java 8 引入的异步编程利器。它让多个异步操作的串联、并联、组合变得像 Stream 链式调用一样自然。在现代 Java 开发中，它已经取代 Callback 和 Future，成为异步编排的标准工具。

---

## 这个问题为什么存在？

### Future 的局限

Java 5 引入的 `Future` 接口只能做最基础的异步操作：

```java
Future<String> future = executor.submit(() -> fetchData());
String result = future.get();  // 阻塞等待结果
// 只能做这些：get()、isDone()、cancel()
```

```
Future 的致命问题：

1. 不能链式组合
   查用户 → 查订单 → 查物流
   每个 Future 的结果需要手动 get()，再传给下一个 → 嵌套回调地狱

2. 不能组合多个 Future
   "同时查用户和订单，都完成后合并" → Future 做不到
   需要手动轮询 isDone() 或用 CountDownLatch

3. 没有异常处理链
   一步出错，后续所有步骤都无法执行
   需要大量 try-catch 嵌套

4. get() 阻塞
   调用线程被阻塞，违背了异步的初衷
```

**CompletableFuture 解决了所有这些问题**——它实现了 `CompletionStage` 接口，提供了完整的异步编排 DSL。

---

## 它是怎么解决问题的？

### 创建 CompletableFuture

```java
// 1. 从无到有创建
CompletableFuture<String> cf = new CompletableFuture<>();
cf.complete("done");     // 手动完成
cf.completeExceptionally(new RuntimeException("fail"));  // 手动异常

// 2. 提交异步任务（推荐）
// supplyAsync：有返回值
CompletableFuture<String> cf1 = CompletableFuture.supplyAsync(() -> fetchData());

// runAsync：无返回值
CompletableFuture<Void> cf2 = CompletableFuture.runAsync(() -> doSomething());

// 3. 指定线程池（重要！）
ExecutorService myPool = Executors.newFixedThreadPool(4);
CompletableFuture<String> cf3 = CompletableFuture.supplyAsync(
    () -> fetchData(), myPool
);
```

```
不指定线程池时默认用 ForkJoinPool.commonPool()：
- 线程数 = CPU 核心数 - 1
- 是 JVM 全局共享的
- 如果 commonPool 被占满，所有 CompletableFuture 都会变慢

生产环境必须指定自定义线程池！
```

### 转换链：thenApply / thenAccept / thenRun

```java
CompletableFuture<String> cf = CompletableFuture.supplyAsync(() -> "hello");

// thenApply：有参数、有返回值（转换）
CompletableFuture<Integer> len = cf.thenApply(s -> s.length());  // "hello" → 5

// thenAccept：有参数、无返回值（消费）
CompletableFuture<Void> print = cf.thenAccept(s -> System.out.println(s));

// thenRun：无参数、无返回值（后置动作）
CompletableFuture<Void> done = cf.thenRun(() -> System.out.println("完成"));
```

```
三者的区别（高频考点）：

        参数    返回值    用途
thenApply   ✓       ✓       转换：A → B
thenAccept  ✓       ✗       消费：处理 A，不返回
thenRun     ✗       ✗       后置：A 完成后执行 B
```

### 组合链：thenCompose / thenCombine

```java
CompletableFuture<String> userFuture = CompletableFuture.supplyAsync(() -> fetchUser());
CompletableFuture<String> orderFuture = CompletableFuture.supplyAsync(() -> fetchOrders());

// thenCompose：扁平化组合（类似 Stream.flatMap）
// 当第一步的结果是 CompletableFuture 时，展开为一层
CompletableFuture<String> result = userFuture.thenCompose(user ->
    CompletableFuture.supplyAsync(() -> fetchOrders(user))
);

// thenCombine：同时等待两个 Future，合并结果
CompletableFuture<String> merged = userFuture.thenCombine(orderFuture,
    (user, orders) -> user + " 的订单: " + orders
);
```

```
thenCompose vs thenCombine（高频考点）：

thenCompose：顺序依赖
  A 的结果是 B 的输入 → B 返回 CompletableFuture → 展开
  类比：flatMap（A → Future<B> → B）

thenCombine：并行无关
  A 和 B 独立执行 → 都完成后合并
  类比：zip（A + B → C）
```

### 并行执行：allOf / anyOf

```java
CompletableFuture<String> f1 = CompletableFuture.supplyAsync(() -> fetchUser());
CompletableFuture<String> f2 = CompletableFuture.supplyAsync(() -> fetchOrders());
CompletableFuture<String> f3 = CompletableFuture.supplyAsync(() -> fetchLogistics());

// allOf：等待所有完成
CompletableFuture<Void> all = CompletableFuture.allOf(f1, f2, f3);
all.join();  // 阻塞等待全部完成
// 获取各结果
String user = f1.join();
String orders = f2.join();

// anyOf：等待任意一个完成
CompletableFuture<Object> any = CompletableFuture.anyOf(f1, f2, f3);
Object firstResult = any.join();  // 返回最先完成的结果
// 注意：anyOf 返回 CompletableFuture<Object>，需要强制转换
```

```java
// allOf 的实用封装：收集所有结果
public static <T> CompletableFuture<List<T>> allOf(
    List<CompletableFuture<T>> futures
) {
    return CompletableFuture.allOf(futures.toArray(new CompletableFuture[0]))
        .thenApply(v -> futures.stream()
            .map(CompletableFuture::join)
            .toList()
        );
}
```

### 异常处理：exceptionally / handle / whenComplete

```java
CompletableFuture<Integer> cf = CompletableFuture.supplyAsync(() -> {
    if (Math.random() > 0.5) throw new RuntimeException("boom");
    return 42;
});

// exceptionally：只处理异常（类似 catch）
CompletableFuture<Integer> recovered = cf.exceptionally(ex -> {
    System.out.println("异常: " + ex.getMessage());
    return -1;  // 降级返回默认值
});

// handle：同时处理正常值和异常（类似 try-catch-finally）
CompletableFuture<String> handled = cf.handle((result, ex) -> {
    if (ex != null) {
        return "默认值";  // 异常时
    }
    return "结果: " + result;  // 正常时
});

// whenComplete：不转换结果，只做日志/监控
cf.whenComplete((result, ex) -> {
    if (ex != null) {
        logger.error("任务失败", ex);
    } else {
        logger.info("任务结果: {}", result);
    }
});
```

```
三者的区别（高频考点）：

              正常值    异常     返回类型
exceptionally  ✗        ✓       与原 Future 相同
handle         ✓        ✓       可转换类型
whenComplete   ✓（但不转换） ✓（不恢复）      CompletableFuture<Void> / 原类型

选择原则：
- 需要降级/恢复 → exceptionally
- 需要同时处理正常和异常 → handle
- 只做日志/监控，不改变结果 → whenComplete
```

### 实战：多接口聚合查询

```java
// 同时调用 3 个服务，合并结果，处理异常
public CompletableFuture<OrderDetail> getOrderDetail(String orderId) {
    // 三个独立查询并行执行
    CompletableFuture<User> userFuture = CompletableFuture.supplyAsync(
        () -> userService.getUser(orderId), ioPool
    );
    CompletableFuture<List<Order>> ordersFuture = CompletableFuture.supplyAsync(
        () -> orderService.getOrders(orderId), ioPool
    );
    CompletableFuture<Address> addressFuture = CompletableFuture.supplyAsync(
        () -> addressService.getAddress(orderId), ioPool
    );

    // 合并三个结果
    return userFuture
        .thenCombine(ordersFuture, (user, orders) -> new Pair<>(user, orders))
        .thenCombine(addressFuture, (pair, address) ->
            new OrderDetail(pair.getKey(), pair.getValue(), address)
        )
        .exceptionally(ex -> {
            logger.error("查询订单详情失败", ex);
            return new OrderDetail(null, Collections.emptyList(), null);
        });
}
```

### 超时控制

```java
// Java 9+: orTimeout / completeOnTimeout
CompletableFuture<String> cf = CompletableFuture.supplyAsync(() -> slowQuery())
    .orTimeout(3, TimeUnit.SECONDS)        // 超时抛 TimeoutException
    .exceptionally(ex -> {
        if (ex instanceof TimeoutException) {
            return "timeout-default";       // 超时降级
        }
        return "error-default";
    });

// Java 9+:
.completeOnTimeout("default", 3, TimeUnit.SECONDS);  // 超时返回默认值（不抛异常）
```

```java
// Java 8 的超时写法
ExecutorService timeoutPool = Executors.newSingleThreadExecutor();
CompletableFuture<String> cf = CompletableFuture.supplyAsync(() -> slowQuery());
timeoutPool.submit(() -> {
    try {
        cf.get(3, TimeUnit.SECONDS);
    } catch (TimeoutException e) {
        cf.complete("default");  // 手动完成
    } catch (Exception e) {
        cf.completeExceptionally(e);
    }
});
```

---

## 和相似方案的区别

### CompletableFuture vs Future

| 维度 | Future | CompletableFuture |
|------|--------|-------------------|
| 链式组合 | ✗ | ✓（thenApply/thenCompose） |
| 多 Future 组合 | ✗ | ✓（thenCombine/allOf/anyOf） |
| 异常处理 | ✗（get 抛异常） | ✓（exceptionally/handle） |
| 阻塞 | get() 阻塞 | join() 阻塞，但支持非阻塞链式 |
| 完成/取消 | 外部控制 | 内部/外部都可以 complete |
| 回调 | ✗ | ✓（thenAccept/whenComplete） |

### CompletableFuture vs Callback

```
Callback 的问题：
httpClient.get("/user", response -> {
    httpClient.get("/orders", orderResponse -> {
        httpClient.get("/logistics", logisticsResponse -> {
            // 回调地狱（Callback Hell）
        });
    });
});

CompletableFuture 的解决：
httpClient.getAsync("/user")
    .thenCompose(user -> httpClient.getAsync("/orders"))
    .thenCompose(orders -> httpClient.getAsync("/logistics"))
    .thenAccept(logistics -> { /* 处理结果 */ })
    .exceptionally(ex -> { /* 统一异常处理 */ });
```

---

## 正确使用方式

### 1. 必须指定自定义线程池

```java
// ✗ 默认用 commonPool——可能被其他任务占满
CompletableFuture.supplyAsync(() -> queryDatabase());

// ✓ 指定 IO 线程池
ExecutorService ioPool = Executors.newFixedThreadPool(10);
CompletableFuture.supplyAsync(() -> queryDatabase(), ioPool);
```

### 2. IO 操作用独立线程池

```java
// CPU 密集和 IO 密集用不同的线程池
ExecutorService cpuPool = Executors.newFixedThreadPool(
    Runtime.getRuntime().availableProcessors()
);
ExecutorService ioPool = new ThreadPoolExecutor(
    20, 50, 60, TimeUnit.SECONDS,
    new LinkedBlockingQueue<>(1000)
);

// CPU 密集 → cpuPool
// IO 密集（HTTP/DB/文件）→ ioPool
```

### 3. 异常处理放在最后

```java
CompletableFuture.supplyAsync(() -> fetchUser())
    .thenApply(User::getId)
    .thenCompose(id -> fetchOrders(id))
    .thenAccept(orders -> processOrders(orders))
    .exceptionally(ex -> {
        // 所有步骤的异常都在这里统一处理
        logger.error("订单处理失败", ex);
        return null;  // thenAccept 的 exceptionally 返回 null
    });
```

### 4. join() vs get()

```java
// join()：不抛 checked exception，更简洁
String result = cf.join();

// get()：抛 InterruptedException + ExecutionException
String result = cf.get();

// 推荐用 join()——代码更干净，不需要 try-catch checked exception
// 但在需要区分超时等场景时用 get(timeout)
```

---

## 边界情况和坑

### 1. thenApply 等回调的线程执行位置

```java
CompletableFuture<String> cf = CompletableFuture.supplyAsync(
    () -> "hello", myPool  // 在 myPool 中执行
);

// thenApply 在哪个线程执行？
// 取决于前置阶段是否已完成：
// 1. 前置已完成 → 在当前线程中同步执行
// 2. 前置未完成 → 在完成前置的那个线程中执行
// 不是固定在 myPool 中！

// 如果需要确保在特定线程池中执行：
cf.thenApplyAsync(transform, myPool);
```

### 2. 链式调用中的异常传播

```java
CompletableFuture<String> cf = CompletableFuture.supplyAsync(() -> "hello")
    .thenApply(s -> {
        throw new RuntimeException("步骤1失败");
    })
    .thenApply(s -> s.toUpperCase())  // 这一步不会执行
    .exceptionally(ex -> "fallback");

// 结果："fallback"
// 中间步骤的异常会跳过后续的 thenApply，直接到 exceptionally
// 类似 try-catch 中 throw 跳过后续语句
```

### 3. exceptionally 只恢复一次

```java
CompletableFuture<Integer> cf = CompletableFuture.supplyAsync(() -> {
    throw new RuntimeException("失败");
})
.exceptionally(ex -> -1)        // 第一次恢复 → 返回 -1
.thenApply(x -> x * 2)          // 正常执行 → -2
.exceptionally(ex -> 0);        // 不会触发（前面没有异常）

// exceptionally 只捕获它之前步骤的异常
// 如果 exceptionally 本身又抛异常，下一个 exceptionally 可以捕获
```

### 4. thenApply vs thenApplyAsync

```java
// thenApply：可能同步执行（如果前置已完成）
cf.thenApply(x -> transform(x));

// thenApplyAsync：始终异步执行（提交到指定线程池）
cf.thenApplyAsync(x -> transform(x), myPool);
```

```
什么时候用 Async 版本？
1. 回调中有 IO 操作 → 必须用 Async，避免阻塞完成线程
2. 回调是纯 CPU 计算 → thenApply 就够（同步执行更快）
3. 需要精确控制执行线程 → thenApplyAsync
```

### 5. allOf 的结果收集陷阱

```java
CompletableFuture<String> f1 = supplyAsync(() -> "a");
CompletableFuture<String> f2 = supplyAsync(() -> "b");

CompletableFuture<Void> all = CompletableFuture.allOf(f1, f2);
all.join();  // 等待全部完成

// allOf 返回 CompletableFuture<Void>，没有直接的结果列表
// 必须手动从原始 Future 中获取：
List<String> results = List.of(f1.join(), f2.join());
```

### 6. 忘记 join/get 导致任务不执行

```java
// ✗ 没有 join/get，异步任务可能还没执行完
CompletableFuture.supplyAsync(() -> saveToDatabase(data));
// 方法返回，任务可能还在执行中或还没开始

// ✓ 确保等待结果
CompletableFuture.supplyAsync(() -> saveToDatabase(data)).join();

// 或者如果确实不需要等待，至少保证 future 引用不丢失
// 否则任务可能被 GC，永远不执行
```

---

