# 题目：CountDownLatch、CyclicBarrier、Semaphore 有什么区别？它们各自适合什么场景？

---

## ⚠️ 先盲答

**不要看任何资料，用自己的话回答，写到纸上或心里默念也行。**

---

## 盲答引导

1. `CountDownLatch` 的「倒计时」是什么含义？`await()` 和 `countDown()` 分别在做什么？
2. `CyclicBarrier` 和 `CountDownLatch` 最大的区别在哪？「循环使用」是什么意思？
3. `Semaphore` 的「许可证」是什么？控制的是资源数量还是线程数量？
4. 这三个类底层都是基于 AQS 的吗？各用的是什么模式（独占/共享）？
5. 什么场景下你会选哪一个？各举一个实际例子。

---

## 知识链提示

这道题应该让你联想到：

- `[[02_并发编程/04_AQS/AQS]]` → 三者底层都是 `tryAcquireShared`
- `栅栏 vs 闭锁` → CyclicBarrier 是栅栏，CountDownLatch 是闭锁
- `[[08_分布式与架构/05_高可用设计/限流算法]]` → Semaphore 是最简单的限流工具
- `线程协作` → await/signal vs CountDownLatch 的对比
- `[[02_并发编程/09_CompletableFuture/CompletableFuture异步编排]]` → 并发任务的另一种协作方式

---

## 核心追问

1. `CountDownLatch` 的计数器减到 0 之后，再调用 `countDown()` 会怎样？
2. `CyclicBarrier` 的 `await()` 超时了会怎样？其他等待的线程会收到什么？
3. `Semaphore` 的 `tryAcquire()` 和 `acquire()` 有什么区别？
4. `CyclicBarrier` 支持 `reset()` 方法，什么场景下会用到？
5. 如果要把 `CountDownLatch` 用 AQS 自己实现一遍，核心逻辑怎么写？

---

## 参考要点（盲答后再看）


**三大工具对比**：

| | CountDownLatch | CyclicBarrier | Semaphore |
|--|----------------|---------------|-----------|
| 模式 | 一次性，倒数到0释放 | 可循环，满员就触发 | 控制许可证数量 |
| AQS 模式 | 共享模式 | 共享模式 | 共享模式 |
| 典型场景 | 主线程等子线程全部完成 | 多个线程互相等待，一起继续 | 限流（连接池） |
| 可重置 | ❌ | ✅（reset） | ✅（release 增加许可证） |

**CountDownLatch 示例**：
```java
CountDownLatch latch = new CountDownLatch(3);
for (int i = 0; i < 3; i++) {
    new Thread(() -> { doWork(); latch.countDown(); }).start();
}
latch.await();  // 等3个线程全部完成
System.out.println("全部完成");
```

**CyclicBarrier 示例**：
```java
CyclicBarrier barrier = new CyclicBarrier(3, 
    () -> System.out.println("满3人，出发！"));  // 满员后的回调
for (int i = 0; i < 9; i++) {
    new Thread(() -> {
        System.out.println("到达");
        barrier.await();  // 等满3人
    }).start();
}
// 可循环使用：9个线程，每3个为一组触发一次
```

**Semaphore 限流示例**：
```java
Semaphore sem = new Semaphore(10);  // 最多10个并发
sem.acquire();
try {
    // 访问受限资源
} finally {
    sem.release();
}
```

**底层（都是 AQS 共享模式）**：
- CountDownLatch：state = 初始计数，`await()` 判断 state==0？
- CyclicBarrier：用 ReentrantLock + Condition 实现（不是纯 AQS！）
- Semaphore：state = 许可证数量，`acquire()` → state-1，`release()` → state+1


---

## 下一步

1. 盲答后，对比参考要点，找到卡壳的地方
2. 打开 `[[02_并发编程/04_AQS/AQS]]` 主题文档，把三个工具对应到共享模式
3. 在 Obsidian 里建双向链接：`[[08_分布式与架构/05_高可用设计/限流算法]]` 对比学习（Semaphore 是信号量限流）
4. 在 `[[13_面试训练/03_每日一题/每日一题跟踪表]]` 里勾选「今日完成」，打 1~5 分
