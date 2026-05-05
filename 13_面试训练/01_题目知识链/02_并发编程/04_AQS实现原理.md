# AQS 的实现原理是什么？它是如何实现同步的？

> ⚠️ **先盲答**：AQS 是什么？它的核心数据结构是什么？获取锁和释放锁的流程是怎样的？

---

## 盲答引导

1. AQS 的全称是什么？**独占模式**和**共享模式**有什么区别？
2. AQS 内部的**核心状态**和**等待队列**分别是什么数据结构？
3. 线程拿锁失败后会怎样？它在队列里是**怎么排队的**？
4. `tryAcquire` / `tryRelease` 这些方法是干什么的？为什么 AQS 不直接实现它们？

---

## 知识链提示

```
AQS 抽象队列同步器
  → [[02_并发编程/04_AQS/AQS]]
    → 核心组成
      → state（volatile int）：同步状态，由子类决定语义
        → ReentrantLock：state = 重入次数
        → Semaphore：state = 许可证数量
        → CountDownLatch：state = 倒计时值
      → CLH 队列（双向链表）：存等待锁的线程节点
        → Node（waitStatus）：CANCELLED / SIGNAL / CONDITION / PROPAGATE
        → 入队：tail 添加新节点，prev 指向前驱
        → 自旋等待：前驱节点释放锁时，当前节点被唤醒
    → 模板方法模式
      → ReentrantLock与显式锁：lock() → tryAcquire() → AQS 实现
        → 公平锁：检查队列是否有前驱节点
        → 非公平锁：直接 CAS 抢锁，抢不到再入队
      → [[13_面试训练/01_题目知识链/02_并发编程/13_AQS三剑客]]：await() → tryAcquireShared()
      → [[13_面试训练/01_题目知识链/02_并发编程/13_AQS三剑客]]：acquire() → tryAcquireShared()
```

---

## 核心追问

| 追问 | 考点 |
|------|------|
| CLH 队列为什么要用双向链表？ | 入队效率 + 取消节点 |
| 什么叫「模板方法模式」？AQS 里哪些方法是模板方法？ | 设计模式 |
| 为什么非公平锁效率通常更高？ | 减少线程切换 |
| AQS 的自旋等待是什么意思？CPU 不会空转吗？ | park/unpark 机制 |

---

## 参考答案要点

**核心数据结构**：
- `state`：volatile int，子类自定义语义
- `CLH 队列`：双向链表，每个节点代表一个等待线程

**获取锁流程**（以 ReentrantLock 为例）：
```
tryAcquire() → CAS 改 state 成功 → 获得锁
     ↓ 失败
addWaiter() → 创建 Node，CAS 入队到 tail
     ↓
acquireQueued() → 自旋检查前驱是否是 head
  → 是 → 再次 tryAcquire()
  → 否 → park 等待前驱唤醒
```

**模板方法**：AQS 定义骨架（acquire / release），子类实现 `tryAcquire / tryRelease`，自己决定锁的语义。

---

## 下一步

打开 [[02_并发编程/04_AQS/AQS]] 文档，对比 ReentrantLock与显式锁，补充链接：「ReentrantLock 是 AQS 最典型的实现，非公平锁直接 CAS 抢锁，公平锁多一个 hasQueuedPredecessors() 检查」。
