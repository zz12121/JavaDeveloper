# ForkJoin 详解

> ForkJoinPool 是为**分治任务**设计的线程池，核心思想是工作窃取（work-stealing）：空闲线程从其他线程的队列尾部"偷"任务，最大化 CPU 利用率。

---

## 这个问题为什么存在？

ThreadPoolExecutor 使用**共享队列**模型：所有线程从同一个队列取任务。这种模型在「大任务」场景下效率低——一个耗时 10 秒的任务阻塞了某个线程，其他线程即使空闲也无法帮忙。

ForkJoinPool 使用**双端队列**模型：每个线程有自己的任务队列，空闲线程可以从其他线程的队列尾部偷任务，实现负载均衡。

适合场景：大任务可以递归拆分成小任务（归并排序、并行计算、文件树遍历）。

---

## 它是怎么解决问题的？

### 核心模型：工作窃取（Work-Stealing）

```
ThreadPoolExecutor（共享队列）：
  所有线程 ─→  [ 共享队列 ]  ← 所有线程都从这里取
  - 竞争大（都需要抢队列锁）
  - 大任务阻塞时，其他线程帮不上忙

ForkJoinPool（工作窃取）：
  Thread1  [deque1]  ← Thread1 从队头取，其他线程从队尾偷
  Thread2  [deque2]
  Thread3  [deque3]
  - 无竞争（自己的队列，自己从头取）
  - 空闲线程偷别人的任务（尾端），帮忙加快执行
```

### RecursiveTask 与 RecursiveAction

```java
// 有返回值 → 继承 RecursiveTask
class SumTask extends RecursiveTask<Long> {
    private final long[] array;
    private final int start, end;
    private static final int THRESHOLD = 10000;

    protected Long compute() {
        if (end - start <= THRESHOLD) {
            // 足够小 → 直接计算
            long sum = 0;
            for (int i = start; i < end; i++) sum += array[i];
            return sum;
        }
        // 太大 → 拆分
        int mid = (start + end) / 2;
        SumTask left = new SumTask(array, start, mid);
        SumTask right = new SumTask(array, mid, end);
        left.fork();   // 异步执行左任务
        return right.compute() + left.join();  // 当前线程执行右任务，等左任务结果
    }
}

// 无返回值 → 继承 RecursiveAction
class PrintTask extends RecursiveAction { ... }
```

**fork() vs join()**：

| 方法 | 作用 | 是否阻塞 |
|------|------|---------|
| `fork()` | 异步执行任务（把任务放进自己的队列） | ✗ 不阻塞 |
| `join()` | 等待任务完成，获取结果 | ✓ 阻塞当前线程 |
| `invoke()` | 同步执行（fork + join） | ✓ 阻塞 |

### 正确写法：先 fork 大的一半

```java
// ✅ 推荐：先 fork 大的一半，当前线程处理小的一半
int mid = (start + end) / 2;
Task left = new Task(start, mid);
Task right = new Task(mid, end);
left.fork();   // 左任务异步执行
return right.compute() + left.join();  // 右任务当前线程执行

// ❌ 不推荐：两个都 fork，当前线程只 join
left.fork();
right.fork();
return left.join() + right.join();  // 当前线程闲着等，浪费
```

---

## 深入原理

### ForkJoinPool 源码关键结构

```java
// ForkJoinPool.java
public class ForkJoinPool extends AbstractExecutorService {
    volatile WorkQueue[] workQueues;  // 所有线程的工作队列数组
    final ThreadWorker[] workers;      // 所有工作线程
    volatile int stealCount;           // 全局窃取计数
}

// WorkQueue：每个工作线程对应一个
final class WorkQueue {
    ForkJoinTask<?>[] array;  // 任务数组（双端队列）
    int base;    // 偷任务的线程从这里取（尾端，base 递增）
    int top;     // 所属线程从这里取（头部，top 递减）
}
```

**工作窃取流程**：

```
Thread A（工作线程）的 WorkQueue：
  [task1][task2][task3][task4]
    ↑top                     ↑base

Thread A：从 top 端取任务（LIFO，栈式）
Thread B（空闲）：从 base 端偷任务（FIFO，队列式）
  → 偷走 task4，Thread A 继续从头部取 task3
```

> **为什么用双端队列？**
> 工作线程自己取任务（头部）和偷窃线程取任务（尾部）不会冲突，无需加锁。

### ForkJoinTask 的状态机

```
0 = NEW        — 刚创建
1 = COMPLETED  — 正常完成
2 = CANCELLED  — 被取消
3 = EXCEPTIONAL — 抛异常
4 = SIGN/L    — 有后继任务需要唤醒（类似 AQS 的 SIGNAL）
```

**invoke() 的底层**（简化）：

```java
public final V invoke() {
    int s;
    if ((s = doInvoke()) < 0)  // 执行任务
        return getRawResult();  // 正常完成，返回结果
    throw new CancellationException();  // 被取消
}
```

---

## 正确使用方式

### 1. 合理设置阈值

```java
// ❌ 阈值太大：任务太少，并行度不够
// ❌ 阈值太小：任务拆分过多，调度开销超过并行收益

// ✅ 经验值：每个子任务执行时间 ≥ 100ms
// 或者：任务数 ≈ CPU 核数 * 2~4
private static final int THRESHOLD = 10000;  // 根据实际测试调整
```

### 2. 避免 join() 导致死锁

```java
// ❌ 危险：两个任务互相等待对方完成
class TaskA extends RecursiveTask<Integer> {
    protected Integer compute() {
        TaskB b = new TaskB();
        b.fork();
        return b.join();  // 等 TaskB
    }
}
class TaskB extends RecursiveTask<Integer> {
    protected Integer compute() {
        TaskA a = new TaskA();
        a.fork();
        return a.join();  // 等 TaskA → 死锁！
    }
}
```

> ForkJoinPool 的「任务窃」机制可以在一定程度上缓解这个问题（空闲线程帮着执行），但最好避免这种写法。

### 3. 使用 ManagedBlocker 处理阻塞操作

```java
// ❌ 在 ForkJoinTask 里做阻塞 IO → 线程被占住，窃取机制失效
class BadTask extends RecursiveTask<Data> {
    protected Data compute() {
        return httpClient.get(url);  // 阻塞等待 HTTP 响应
    }
}

// ✅ 用 ManagedBlocker 通知池子扩容
class GoodTask extends RecursiveTask<Data> {
    protected Data compute() {
        ForkJoinPool.managedBlock(new ManagedBlocker() {
            boolean blocked = false;
            public boolean block() throws InterruptedException {
                result = httpClient.get(url);
                blocked = true;
                return true;
            }
            public boolean isReleasable() { return blocked; }
        });
        return result;
    }
}
```

---

## 边界情况和坑

### 1. ForkJoinPool 不适合 IO 密集型任务

```
ForkJoinPool 默认线程数 = CPU 核数（Runtime.getRuntime().availableProcessors()）
→ 如果是 IO 密集型任务，线程都在等 IO，CPU 利用率为 0

解决：用 ThreadPoolExecutor（线程数 = CPU 核数 * 2），不要用 ForkJoinPool
```

### 2. CommonPool 的线程数限制

```java
// ForkJoinPool.commonPool() 是 JVM 全局共享的
// 默认线程数 = CPU 核数 - 1

// ❌ 危险：大量任务提交到 commonPool，可能饿死其他使用者
ForkJoinPool.commonPool().submit(task);

// ✅ 正确：自己创建 ForkJoinPool，用完关闭
ForkJoinPool pool = new ForkJoinPool(4);  // 4 个工作线程
try {
    Long result = pool.invoke(new SumTask(array, 0, array.length));
} finally {
    pool.shutdown();
}
```

### 3. 递归深度过大导致栈溢出

```java
// ❌ 如果阈值设得太小，任务拆分太深 → StackOverflowError
private static final int THRESHOLD = 1;  // 每个元素一个任务 → 递归深度 = 数组长度

// ✅ 合理设置阈值，控制递归深度
private static final int THRESHOLD = array.length / (CPU_CORES * 4);
```
