# ThreadPoolExecutor 详解

> ThreadPoolExecutor 是 Java 线程池的核心实现。理解它的 7 个参数和任务提交流程，才能正确配置线程池，避免 OOM 和死锁。

---

## 这个问题为什么存在？

每次来一个任务就创建一个线程（`new Thread(task).start()`），代价极高：

- 操作系统分配 PCB
- 分配 1MB 栈内存（默认 `-Xss`）
- 用户态 → 内核态切换

高并发场景下，线程数暴增 → 内存耗尽 → 系统假死。

线程池的核心思想：**线程复用 + 任务排队 + 可控并发数**，用有限的线程处理大量的任务。

---

## 它是怎么解决问题的？

### 7 个参数

```java
new ThreadPoolExecutor(
    int corePoolSize,      // ① 核心线程数（常住线程）
    int maximumPoolSize,   // ② 最大线程数（临时线程上限）
    long keepAliveTime,    // ③ 临时线程空闲存活时间
    TimeUnit unit,         // ④ 时间单位
    BlockingQueue<Runnable> workQueue,  // ⑤ 任务队列
    ThreadFactory threadFactory,          // ⑥ 线程工厂（命名、守护线程等）
    RejectedExecutionHandler handler      // ⑦ 拒绝策略
);
```

### 任务提交流程（面试必问）

```
任务 submit(task)
  │
  ├─ 1. 当前线程数 < corePoolSize？
  │     是 → 创建核心线程，执行 task（直接启动）
  │     否 → 继续
  │
  ├─ 2. 队列 workQueue.offer(task) 成功？
  │     是 → 任务入队，等待执行
  │     否 → 继续
  │
  ├─ 3. 当前线程数 < maximumPoolSize？
  │     是 → 创建临时线程，执行 task
  │     否 → 继续
  │
  └─ 4. 执行拒绝策略（handler.rejectedExecution）
```

> **关键点**：队列满了之后，才会创建「超过 `corePoolSize`」的线程。

### 源码关键路径：execute(Runnable command)

```java
// ThreadPoolExecutor.java
public void execute(Runnable command) {
    if (command == null) throw new NullPointerException();
    int c = ctl.get();   // AtomicInteger，高 3 位 = 线程池状态，低 29 位 = 线程数

    // ① 线程数 < corePoolSize
    if (workerCountOf(c) < corePoolSize) {
        if (addWorker(command, true)) return;  // core = true
        c = ctl.get();
    }

    // ② 尝试入队
    if (isRunning(c) && workQueue.offer(command)) {
        int recheck = ctl.get();
        if (!isRunning(recheck) && remove(command))
            reject(command);
        else if (workerCountOf(recheck) == 0)
            addWorker(null, false);  // 确保有工作线程
        return;
    }

    // ③ 尝试创建临时线程
    if (!addWorker(command, false)) {  // core = false
        reject(command);  // ④ 拒绝
    }
}
```

### Worker：线程的包装类

```java
class Worker extends AbstractQueuedSynchronizer implements Runnable {
    final Thread thread;       // 真正的线程
    Runnable firstTask;        // 第一个任务（可以为 null）
    volatile long completedTasks;

    Worker(Runnable firstTask) {
        setState(-1);  // 禁止中断（直到 runWorker 开始）
        this.firstTask = firstTask;
        this.thread = getThreadFactory().newThread(this);
    }

    public void run() {
        runWorker(this);  // 调用 ThreadPoolExecutor.runWorker()
    }
}
```

**`runWorker` 的核心循环**：

```java
final void runWorker(Worker w) {
    Runnable task = w.firstTask;
    w.firstTask = null;
    w.unlock();  // 允许中断
    boolean completedAbruptly = true;
    try {
        while (task != null || (task = getTask()) != null) {
            w.lock();  // 防止在运行期间被中断
            task.run();
            task = null;
        }
        completedAbruptly = false;
    } finally {
        processWorkerExit(w, completedAbruptly);  // 线程退出，清理
    }
}
```

> **为什么 `getTask()` 可能返回 `null`？**
> - 当前线程数 > `corePoolSize`，且超时没取到任务 → 返回 `null`（临时线程超时退出）
> - 线程池状态变成 `SHUTDOWN` 且队列为空 → 返回 `null`（优雅关闭）

---

## 深入原理

### Executors 工厂方法的问题

| Executors 方法 | 实际创建的线程池 | 问题 |
|------|----------------|------|
| `newFixedThreadPool(n)` | `new ThreadPoolExecutor(n, n, 0, LinkedBlockingQueue())` | 队列无界（`Integer.MAX_VALUE`），可能 OOM |
| `newCachedThreadPool()` | `new ThreadPoolExecutor(0, Integer.MAX_VALUE, 60s, SynchronousQueue())` | 最大线程数无界，高并发 → 创建大量线程 → OOM |
| `newSingleThreadExecutor()` | `new ThreadPoolExecutor(1, 1, 0, LinkedBlockingQueue())` | 同 Fixed，队列无界 |
| `newScheduledThreadPool(n)` | `ScheduledThreadPoolExecutor` | 队列无界 |

**为什么阿里规范禁止用 `Executors` 创建线程池？**

> 1. `FixedThreadPool`：队列 `LinkedBlockingQueue` 无界，任务堆积 → OOM
> 2. `CachedThreadPool`：最大线程数 `Integer.MAX_VALUE`，高并发 → 创建大量线程 → OOM
> 3. 无法自定义拒绝策略、线程工厂等关键参数

**正确做法**：手动 `new ThreadPoolExecutor()`，明确指定所有参数。

### 4 种拒绝策略

```java
// 1. AbortPolicy（默认）：抛异常
//    RejectedExecutionException → 调用者必须处理

// 2. CallerRunsPolicy：调用者线程自己执行
//    主线程提交任务，如果线程池满了，主线程自己跑 → 变相限流

// 3. DiscardPolicy：直接丢弃，不抛异常
//    任务悄无声息地没了 → 危险！

// 4. DiscardOldestPolicy：丢弃队列里最老的任务，再尝试提交
//    适合「新任务比老任务重要」的场景
```

**自定义拒绝策略**（面试加分）：

```java
RejectedExecutionHandler handler = (task, executor) -> {
    // 方案1：记录日志，稍后重试
    log.warn("任务被拒绝: " + task);
    retryQueue.add(task);

    // 方案2：降级处理（返回缓存数据、走备用逻辑）
    // 方案3：阻塞提交（用 Future 的 get() 阻塞当前线程）
};
```

### 线程池的 5 种状态

```
   RUNNING（高3位=111）   → 能接受新任务，能处理队列任务
        │  shutdown()
        ▼
   SHUTDOWN（000）         → 不接受新任务，但处理队列剩余任务
        │  队列空 + 工作线程结束
        ▼
   STOP（001）             → 不接受新任务，不处理队列，中断正在执行的任务
        │  shutdownNow()
        ▼
   TIDYING（010）         → 所有任务结束，工作线程数=0，准备调用 terminated()
        │
        ▼
   TERMINATED（011）      → terminated() 执行完成
```

---

## 正确使用方式

### 1. 推荐配置（CPU 密集型 vs IO 密集型）

```java
int cpuCores = Runtime.getRuntime().availableProcessors();

// CPU 密集型（加密、计算、压缩）：线程数 ≈ CPU 核数
ThreadPoolExecutor cpuPool = new ThreadPoolExecutor(
    cpuCores,           // core = max = CPU 核数
    cpuCores,
    0L, TimeUnit.MILLISECONDS,
    new LinkedBlockingQueue<>(1000),  // 有界队列
    new ThreadFactoryBuilder().setNameFormat("cpu-%d").build(),
    new ThreadPoolExecutor.CallerRunsPolicy()  // 调用者执行，变相限流
);

// IO 密集型（数据库、HTTP 调用）：线程数 ≈ CPU 核数 * 2
ThreadPoolExecutor ioPool = new ThreadPoolExecutor(
    cpuCores * 2,
    cpuCores * 4,
    60L, TimeUnit.SECONDS,
    new LinkedBlockingQueue<>(5000),
    new ThreadFactoryBuilder().setNameFormat("io-%d").build(),
    new ThreadPoolExecutor.AbortPolicy()  // 抛异常，方便监控
);
```

> **为什么 IO 密集型线程数可以更多？**
> CPU 密集型：线程一直占着 CPU，线程数 > CPU 核数 → 上下文切换过多 → 性能下降。
> IO 密集型：线程大部分时间在等 IO（阻塞），CPU 空闲。更多线程可以填满 CPU 的空闲时间。

### 2. 正确关闭线程池

```java
ExecutorService pool = new ThreadPoolExecutor(...);

// 方案1：优雅关闭（推荐）
pool.shutdown();           // 不再接受新任务，等队列任务执行完
pool.awaitTermination(60, TimeUnit.SECONDS);  // 等 60 秒
if (!pool.isTerminated()) {
    pool.shutdownNow();   // 强制关闭
}

// 方案2：立即关闭
pool.shutdownNow();       // 尝试中断所有线程，返回未执行任务列表
```

### 3. 正确的异常处理

```java
// ❌ 错误：submit() 的异常被吞掉
Future<?> f = pool.submit(() -> { throw new RuntimeException("oops"); });
// 不调用 f.get()，异常永远不会抛出！

// ✅ 方案1：用 execute()，异常会打印到控制台
pool.execute(() -> { throw new RuntimeException("oops"); });
// 异常会触发 Thread.UncaughtExceptionHandler

// ✅ 方案2：自定义 UncaughtExceptionHandler
ThreadFactory factory = r -> {
    Thread t = new Thread(r);
    t.setUncaughtExceptionHandler((thread, e) -> log.error("线程异常", e));
    return t;
};

// ✅ 方案3：submit() 后必须调用 future.get()
Future<?> f = pool.submit(task);
try {
    f.get();  // 这里会抛出 ExecutionException（包装了原始异常）
} catch (ExecutionException e) {
    Throwable cause = e.getCause();  // 原始异常
}
```

---

## 边界情况和坑

### 1. 用 `submit()` 却忘了 `get()` → 异常被吞

```java
// ❌ 错误：异常永远不会被看到
pool.submit(() -> { throw new RuntimeException("数据库挂了"); });

// ✅ 正确：必须获取结果
Future<?> f = pool.submit(task);
f.get();  // 阻塞，直到任务完成或抛异常
```

> `submit()` 把异常包装在 `Future` 里，只有调用 `get()` 才会抛出。
> 如果不需要返回值，用 `execute()`，异常会直接打印（或触发 `UncaughtExceptionHandler`）。

### 2. 队列用 `LinkedBlockingQueue()` 无参构造 → OOM

```java
// ❌ 危险：队列无界（容量 = Integer.MAX_VALUE）
new ThreadPoolExecutor(5, 10, 60s,
    new LinkedBlockingQueue<>()  // 无参 = 无界队列
);

// 任务提交速度 > 消费速度 → 队列无限增长 → OOM

// ✅ 正确：指定队列容量
new ThreadPoolExecutor(5, 10, 60s,
    new LinkedBlockingQueue<>(1000)  // 有界队列，满了就触发拒绝
);
```

### 3. `CallerRunsPolicy` 可能导致活锁

```java
// CallerRunsPolicy：当线程池满了，调用者线程自己执行任务
// 如果调用者线程是主线程（或 Web 容器的请求线程），
// 主线程被阻塞 → 无法继续提交新任务 → 变相限流

// 问题：如果任务执行很慢，主线程一直卡在 run()
// → 看起来像「死锁」，其实是「活锁」（一直在做，但进展很慢）
```

### 4. 线程池的 `ThreadFactory` 没自定义 → 排查困难

```java
// ❌ 默认：线程名是 pool-1-thread-1、pool-1-thread-2...
// 出问题时，日志里看不出是哪个线程池的线程

// ✅ 正确：自定义线程名
ThreadFactory factory = new ThreadFactoryBuilder()
    .setNameFormat("order-process-%d")  // 订单处理线程池
    .setDaemon(false)
    .build();
```

**线程池监控**（生产必做）：

```java
ThreadPoolExecutor pool = new ThreadPoolExecutor(...);

// 关键指标
pool.getActiveCount();       // 活跃线程数
pool.getQueue().size();      // 队列积压数
pool.getCompletedTaskCount(); // 已完成任务数

// 定期打印（配合监控告警）
log.info("pool stats: active={}, queue={}, completed={}",
    pool.getActiveCount(),
    pool.getQueue().size(),
    pool.getCompletedTaskCount());
```
