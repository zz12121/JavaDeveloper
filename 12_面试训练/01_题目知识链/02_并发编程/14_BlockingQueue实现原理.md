# 题目：BlockingQueue 是怎么实现的？Array 和 Linked 两个实现有什么区别？

---

## ⚠️ 先盲答

**不要看任何资料，用自己的话回答，写到纸上或心里默念也行。**

---

## 盲答引导

1. `ArrayBlockingQueue` 和 `LinkedBlockingQueue` 的底层数据结构分别是什么？
2. 入队操作（`put()`）在队列满时会怎样？是抛异常还是阻塞？
3. BlockingQueue 用到了 `Condition`，它和 `wait/notify` 有什么关系？
4. `put()` 和 `offer()` 有什么区别？`take()` 和 `poll()` 呢？
5. 线程池里用的是哪种 BlockingQueue？为什么这么选？

---

## 知识链提示

这道题应该让你联想到：

- `[[ReentrantLock与Condition]]` → BlockingQueue 的阻塞实现基础
- `[[生产者消费者模式]]` → BlockingQueue 是最经典的实现方式
- `[[线程池任务队列]]` → Array vs Linked vs SynchronousQueue 选型
- `[[两把锁优化]]` → LinkedBlockingQueue 用 takeLock + putLock 提高并发
- `[[SynchronousQueue]]` → 直接传递，不存元素

---

## 核心追问

1. `ArrayBlockingQueue` 为什么只用一把锁（put 和 take 共用）？
2. `LinkedBlockingQueue` 的「两把锁」是什么意思？为何并发性能更高？
3. `SynchronousQueue` 的容量是多少？为什么线程池用它？
4. `PriorityBlockingQueue` 是有序的，它是怎么保证顺序的？
5. 下面代码有什么问题？
   ```java
   BlockingQueue<Integer> q = new LinkedBlockingQueue<>();
   q.put(null);  // ？？
   ```

---

## 参考要点（盲答后再看）

<details>
<summary>点击展开</summary>

**BlockingQueue 核心：Condition 等待/唤醒**：
```java
// ArrayBlockingQueue.put() 简化逻辑
public void put(E e) throws InterruptedException {
    checkNotNull(e);
    final ReentrantLock lock = this.lock;
    lock.lockInterruptibly();
    try {
        while (count == items.length)   // 队列满
            notFull.await();           // 等待 notFull.signal()
        enqueue(e);
        notEmpty.signal();             // 唤醒等待 take 的线程
    } finally {
        lock.unlock();
    }
}
```

**两大实现对比**：

| 维度 | ArrayBlockingQueue | LinkedBlockingQueue |
|------|-------------------|--------------------|
| 底层 | 数组（固定容量） | 链表（可选容量，默认 Integer.MAX_VALUE） |
| 锁 | 一把锁（put/take 互斥） | 两把锁（putLock / takeLock） |
| 吞吐量 | 较低 | 较高（读/写并发） |
| 内存 | 预分配，内存紧凑 | 动态分配节点，内存开销大 |

**常用方法对比**：

| 行为 | 抛异常 | 返回特殊值 | 阻塞 | 超时 |
|------|--------|------------|------|------|
| 入队 | add(e) | offer(e) | **put(e)** | offer(e, timeout) |
| 出队 | remove() | poll() | **take()** | poll(timeout) |

**线程池选型（重点）**：
| 队列 | 适用线程池类型 |
|------|----------------|
| `ArrayBlockingQueue` | 固定容量，防止 OOM |
| `LinkedBlockingQueue` | 无界（默认），可能 OOM ⚠️ |
| `SynchronousQueue` | newCachedThreadPool（直接传递，不缓冲） |
| `PriorityBlockingQueue` | 需要按优先级执行任务 |

**SynchronousQueue 的特殊性**：
- 容量 = 0，每一个 put 必须等待一个 take（反之亦然）
- 适合「直接交付」场景，线程池用它避免任务堆积

</details>

---

## 下一步

1. 盲答后，对比参考要点，找到卡壳的地方
2. 打开 `[[BlockingQueue]]` 主题文档，把 Array vs Linked 的锁机制补充完整
3. 在 Obsidian 里建双向链接：`[[02_并发编程/线程池核心参数]]` 关联学习（任务队列选型）
4. 在 `[[12_面试训练/每日一题跟踪表]]` 里勾选「今日完成」，打 1~5 分
