# ForkJoin 框架

> ForkJoin 框架是 Java 对"分治"并发模式的官方实现。核心思想：把大任务拆（Fork）成小任务，并行执行，最后合并（Join）结果。特别适合"可递归拆分"的计算任务——归并排序、并行求和、树遍历等。

---

## 这个问题为什么存在？

### 普通线程池的局限

```
ThreadPoolExecutor 的问题：
- 任务之间是独立的，不能拆分和合并
- 不知道任务之间的关系（父子、依赖）
- 不支持"一个大任务拆成多个小任务"的递归模式
- 线程如果等待子任务完成 → 线程被阻塞 → 浪费线程资源
```

**ForkJoinPool 解决的问题**：

```
工作窃取（Work Stealing）：
- 每个线程有自己的双端任务队列（Deque）
- 线程从自己队列的头部取任务执行
- 如果自己的队列空了，就"偷"其他线程队列尾部的任务
- 窃取行为减少了线程空闲时间，提高了整体 CPU 利用率

传统线程池：固定线程数，空闲线程等待
ForkJoinPool：空闲线程主动去偷任务
```

---

## 它是怎么解决问题的？

### ForkJoinTask

```
ForkJoinTask（抽象类）
├── RecursiveTask<V>   — 有返回值的递归任务
├── RecursiveAction    — 无返回值的递归任务
└── CountedCompleter<V> — 完成后触发回调的任务
```

### RecursiveTask：有返回值

```java
// 并行求和
class SumTask extends RecursiveTask<Long> {
    private final long[] array;
    private final int start;
    private final int end;
    private static final int THRESHOLD = 10_000;  // 拆分阈值

    SumTask(long[] array, int start, int end) {
        this.array = array;
        this.start = start;
        this.end = end;
    }

    @Override
    protected Long compute() {
        if (end - start <= THRESHOLD) {
            // 任务足够小，直接计算
            long sum = 0;
            for (int i = start; i < end; i++) {
                sum += array[i];
            }
            return sum;
        }

        // 任务太大，拆分成两个子任务
        int mid = (start + end) / 2;
        SumTask left = new SumTask(array, start, mid);
        SumTask right = new SumTask(array, mid, end);

        left.fork();       // 异步执行左子任务
        long rightResult = right.compute();  // 当前线程执行右子任务
        long leftResult = left.join();       // 等待左子任务结果

        return leftResult + rightResult;
    }
}

// 使用
ForkJoinPool pool = ForkJoinPool.commonPool();
long result = pool.invoke(new SumTask(array, 0, array.length));
```

```
fork/join 的执行模式：
1. fork()：把子任务推入当前线程的工作队列，异步执行
2. compute()：在当前线程中同步执行（当前线程不会闲着）
3. join()：等待子任务完成并获取结果

关键点：fork() 后当前线程不阻塞——它继续执行 right.compute()
这就是 ForkJoinPool 比普通线程池高效的原因：
线程不会因为等待子任务而闲置。
```

### RecursiveAction：无返回值

```java
// 并行排序（归并排序）
class SortTask extends RecursiveAction {
    private final long[] array;
    private final int start;
    private final int end;
    private static final int THRESHOLD = 10_000;

    SortTask(long[] array, int start, int end) {
        this.array = array; this.start = start; this.end = end;
    }

    @Override
    protected void compute() {
        if (end - start <= THRESHOLD) {
            Arrays.sort(array, start, end);  // 足够小，直接排序
            return;
        }
        int mid = (start + end) / 2;
        invokeAll(new SortTask(array, start, mid),
                  new SortTask(array, mid, end));  // 等价于 fork + join
        merge(array, start, mid, end);  // 合并
    }
}
```

```
invokeAll() 是便捷方法：
等价于对每个子任务调用 fork()，然后对最后一个调用 compute()，
其余的 join() 等待结果。

.invokeAll(task1, task2)
≈ task1.fork(); task2.compute(); task1.join();
```

### ForkJoinPool

```java
// 1. 获取公共池（Java 8+，推荐）
ForkJoinPool commonPool = ForkJoinPool.commonPool();
// 并行度 = Runtime.getRuntime().availableProcessors() - 1

// 2. 创建自定义池
ForkJoinPool pool = new ForkJoinPool(4);  // 并行度 = 4
```

```
ForkJoinPool.commonPool() 的注意事项：
1. 整个 JVM 共享一个公共池
2. 并行度默认 = CPU 核心数 - 1（留一个核心给主线程）
3. 可以通过系统属性调整：-Djava.util.concurrent.ForkJoinPool.common.parallelism=8
4. 如果公共池被 IO 密集型任务占满，会影响 Stream.parallel() 等其他使用者

什么时候需要自定义 ForkJoinPool？
- 公共池被其他任务占用
- 需要不同的并行度
- 需要隔离（不互相影响）
```

### 工作窃取机制

```
线程0: [T0_1] [T0_2] [T0_3]  ← 从头取任务
线程1: [T1_1] [T1_2]          ← 从头取任务
线程2: [T2_1]                 ← 从头取任务（完成了，空闲）
线程3: []                      ← 空闲

线程3 空闲 → 去偷线程0的 T0_3（从尾部取）
线程2 空闲 → 去偷线程0的 T0_2（从尾部取）

窃取方向：
- 自己的队列：从头部取（LIFO）→ 复用缓存热度
- 别人的队列：从尾部取（FIFO）→ 减少和原线程的竞争

为什么工作窃取高效？
1. 大任务 Fork 出的子任务通常在同一个线程的队列中
2. 子任务执行过程中可能继续 Fork 更多子任务
3. 后 Fork 的大子任务放在队列尾部 → 窃取者拿到大任务，有更多工作可做
```

### 阈值的选择

```
阈值太小：
- 任务太多，Fork/Join 的调度开销 > 计算开销
- 大量小任务创建和调度，GC 压力增大

阈值太大：
- 并行度不够，很多任务串行执行
- 没有充分利用多核

经验值：
- CPU 密集型：1000 ~ 10000 个元素/任务
- IO 密集型：根据 IO 等待时间调整，阈值可以更小
- 实际中需要 benchmark 确定最佳阈值
```

---

## 和相似方案的区别

### ForkJoin vs 普通 ThreadPoolExecutor

| 维度 | ForkJoinPool | ThreadPoolExecutor |
|------|-------------|-------------------|
| 任务模型 | 可拆分/合并（递归） | 独立任务 |
| 任务队列 | 每线程独立 Deque | 共享队列 |
| 空闲策略 | 工作窃取 | 等待新任务 |
| 阻塞处理 | join() 不阻塞底层线程 | get() 阻塞线程 |
| 适用场景 | 分治、递归 | IO、独立的并行任务 |
| Stream 支持 | parallelStream() 底层 | 不支持 |

### ForkJoin vs CompletableFuture

| 维度 | ForkJoin | CompletableFuture |
|------|---------|-------------------|
| 模型 | 分治（同步拆分） | 异步链式（事件驱动） |
| 适用场景 | CPU 密集、可拆分的计算 | IO 密集、异步编排 |
| 组合 | 手动 fork/join | thenApply/thenCombine/... |
| 结果传递 | 显式 join() | 链式回调 |

```
简单判断标准：
- 一个大任务能拆成结构相同的子任务 → ForkJoin
- 多个独立的异步操作需要编排 → CompletableFuture
```

---

## 正确使用方式

### 1. fork + compute 模式（避免不必要的 fork）

```java
// ✗ 不推荐：两个都 fork，当前线程闲置
left.fork();
right.fork();
return left.join() + right.join();
// 当前线程 join 等待，浪费了一个线程

// ✓ 推荐：一个 fork，当前线程执行另一个
left.fork();
long rightResult = right.compute();
long leftResult = left.join();
return leftResult + rightResult;
// 当前线程不闲置，减少了上下文切换

// ✓ 更简洁：invokeAll
invokeAll(left, right);
return left.join() + right.join();
```

### 2. 不要在 RecursiveTask 中使用阻塞操作

```java
// ✗ ForkJoinTask 中阻塞 → 工作线程被阻塞，无法被窃取
class BadTask extends RecursiveTask<Integer> {
    @Override
    protected Integer compute() {
        Thread.sleep(1000);  // 阻塞！工作线程被占用
        return 42;
    }
}

// ForkJoinPool 的工作线程数量有限
// 如果任务阻塞，线程无法执行其他任务 → 整个池效率下降
```

### 3. parallelStream 底层就是 ForkJoinPool

```java
// parallelStream() 使用 ForkJoinPool.commonPool()
List<Integer> list = IntStream.range(0, 1_000_000).boxed().toList();

long sum = list.parallelStream()
    .mapToLong(Integer::longValue)
    .sum();

// 可以自定义池
ForkJoinPool customPool = new ForkJoinPool(4);
customPool.submit(() ->
    list.parallelStream().mapToLong(Integer::longValue).sum()
).join();
```

### 4. 正确处理异常

```java
class SafeTask extends RecursiveTask<Long> {
    @Override
    protected Long compute() {
        try {
            // 可能失败的计算
            return dangerousOperation();
        } catch (Exception e) {
            // RecursiveTask 中异常通过 get()/join() 重新抛出
            throw new RuntimeException("计算失败", e);
        }
    }
}

// 调用方
try {
    pool.invoke(new SafeTask());
} catch (ExecutionException e) {
    // 任务内部的异常被包装成 ExecutionException
    e.getCause();  // 获取原始异常
}
```

---

## 边界情况和坑

### 1. join() 和 get() 的异常行为不同

```java
ForkJoinTask<Long> task = new MyTask();
pool.execute(task);  // 异步执行

// join()：直接抛出任务中的 unchecked 异常
task.join();  // RuntimeException 直接抛出

// get()：包装成 ExecutionException
task.get();   // ExecutionException 包装原始异常

// 注意：join() 不抛 InterruptedException
// get() 抛出 InterruptedException + ExecutionException
```

### 2. ForkJoinPool.commonPool() 的共享风险

```
commonPool 是 JVM 全局共享的：
- parallelStream() 用它
- CompletableFuture.supplyAsync() 默认用它
- 手动的 ForkJoin 任务也可以用它

如果有人提交了阻塞或耗时的任务到 commonPool：
→ parallelStream() 变慢
→ CompletableFuture 默认执行变慢

解决方案：
1. 不要向 commonPool 提交阻塞/IO 任务
2. 用自定义 ForkJoinPool 隔离
3. CompletableFuture 指定自定义 Executor
```

### 3. 递归深度过大导致 StackOverflow

```java
// 如果任务拆分不合理，递归层级可能太深
// ForkJoinTask 的 compute() 在工作线程栈上执行
// 深度过大 → StackOverflowError

// 解决方案：
// 1. 增大阈值，减少拆分深度
// 2. 使用 -Xss 调整线程栈大小
// 3. 重新设计任务拆分策略（二叉拆分改为多叉拆分）
```

### 4. 不适合 IO 密集型任务

```
ForkJoinPool 的设计目标：
- 短暂的 CPU 密集型任务
- 线程数 ≈ CPU 核心数（没有多余线程处理阻塞）

IO 密集型任务的问题：
- 线程阻塞在 IO 上，无法执行其他任务
- 窃取机制失效（被阻塞的线程没有任务可被偷）

IO 密集型 → 用 ThreadPoolExecutor（线程数可以远大于 CPU 核心数）
CPU 密集型 + 可拆分 → 用 ForkJoinPool
```

### 5. ForkJoinTask 不应在外部调用 get() 等待

```java
// ✗ 在 ForkJoinPool 外部等待 ForkJoinTask
ForkJoinTask<?> task = pool.submit(new MyTask());
task.get();  // 阻塞调用线程（通常是主线程），浪费资源

// ✓ 在 ForkJoin 框架内部用 join()
// ✓ 在外部用 invoke()（提交并等待）
pool.invoke(new MyTask());  // 同步等待，但不浪费工作线程
```

### 6. 任务对象不能被复用

```java
// ✗ 复用 ForkJoinTask 对象
MyTask task = new MyTask(data1);
pool.invoke(task);
task.reinitialize();  // 重置状态
task.setData(data2);   // 修改数据
pool.invoke(task);    // 可能出问题

// ✓ 每次创建新的任务对象
pool.invoke(new MyTask(data1));
pool.invoke(new MyTask(data2));
```

---

## 我的理解

ForkJoin 框架是 Java 对"分治并行"的官方答案。它不是一个通用的并发框架——它的适用场景非常明确：**任务可以被递归拆分，且计算量足够大、拆分粒度合适。**

在实际开发中，ForkJoin 最常见的使用方式不是直接写 RecursiveTask，而是通过 **parallelStream()** 间接使用。理解 ForkJoin 的工作窃取原理，有助于正确使用 parallelStream（比如知道不要在 parallelStream 中做阻塞操作）。

**面试中 ForkJoin 的高频考点**：

1. **工作窃取机制**（每个线程双端队列、从头取自己的/从尾偷别人的）
2. **fork/join 的执行流程**（fork 推入队列、当前线程执行另一个、join 等待结果）
3. **ForkJoin vs ThreadPoolExecutor**（任务模型、队列结构、空闲策略）
4. **parallelStream 底层实现**（使用 commonPool、不要阻塞）
5. **阈值选择**（太小调度开销大、太大并行度不够）
6. **ForkJoinPool.commonPool() 的共享风险**（隔离的重要性）
7. **不适用场景**（IO 密集型、不能阻塞、递归深度过大）