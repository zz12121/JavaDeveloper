# 题目：ConcurrentLinkedQueue 和 BlockingQueue 有什么区别？各自适合什么场景？

---

## ⚠️ 先盲答

**不要看任何资料，用自己的话回答，写到纸上或心里默念也行。**

---

## 盲答引导

1. `ConcurrentLinkedQueue` 是阻塞的还是非阻塞的？它的 `offer/poll` 会阻塞吗？
2. 既然 `ConcurrentLinkedQueue` 不阻塞，消费者怎么知道队列里有新元素了？
3. `LinkedBlockingQueue` 和 `ConcurrentLinkedQueue` 底层分别是哪两种锁/无锁机制？
4. 高并发下，哪个吞吐量更高？为什么？
5. 线程池的 `workQueue` 通常用哪种？为什么？

---

## 知识链提示

这道题应该让你联想到：

- `[[CAS无锁算法]]` → ConcurrentLinkedQueue 的入队/出队全程无锁
- `[[BlockingQueue实现]]` → 两把锁 vs 一把锁
- `[[Michael-Scott算法]]` → ConcurrentLinkedQueue 使用的经典无锁队列算法
- `[[wait/notify替代方案]]` → 不阻塞就轮询，CPU 空转问题
- `[[线程池任务队列选型]]` → Array/Linked/Synchronous 各自适用

---

## 核心追问

1. `ConcurrentLinkedQueue.size()` 的时间复杂度是 O(n) 还是 O(1)？为什么？
2. 如果消费速度慢于生产速度，`ConcurrentLinkedQueue` 会 OOM 吗？
3. `BlockingQueue.take()` 阻塞时，线程是什么状态？`ConcurrentLinkedQueue` 的消费者忙等时呢？
4. `ConcurrentLinkedDeque` 是 `BlockingDeque` 的无锁版本吗？
5. Netty 的 `MpscQueue` 和 `ConcurrentLinkedQueue` 有什么关系？

---

## 参考要点（盲答后再看）

<details>
<summary>点击展开</summary>

**核心区别一句话**：BlockingQueue 用锁 + Condition 实现阻塞等待；ConcurrentLinkedQueue 用 CAS 实现无锁，不阻塞。

**对比表**：

| 维度 | ConcurrentLinkedQueue | BlockingQueue（以 Linked 为例） |
|------|----------------------|-------------------------------|
| 阻塞 | ❌ 不阻塞 | ✅ 满时 put 阻塞 / 空时 take 阻塞 |
| 底层 | CAS（无锁） | ReentrantLock + Condition（两把锁） |
| 吞吐量 | 高并发下更高 | 锁竞争下略低 |
| size() | O(n)，遍历整个队列 | O(1)，维护 count 变量 |
| 是否空等 | 不会，poll() 返回 null | take() 一直等 |
| 适合场景 | 高并发、允许忙等/轮询 | 生产者消费者标准模式 |

**ConcurrentLinkedQueue 的 CAS 核心逻辑**：
```java
// 入队（简化）
boolean offer(E e) {
    Node<E> t = tail;
    Node<E> n = new Node<>(e);
    while (true) {
        if (t.next.compareAndSet(null, n)) {
            tail.compareAndSet(t, n);  // 延迟更新 tail
            return true;
        }
        t = t.next;  // CAS 失败，重试
    }
}
```

**为什么不推荐用 ConcurrentLinkedQueue 做线程池任务队列？**
→ 线程池需要**工作线程在任务为空时阻塞等待**，而不是忙轮询。BlockingQueue 的 `take()` 正好满足。

**size() 是 O(n) 的原因**：
- ConcurrentLinkedQueue 为了无锁，size 不维护原子计数器
- 必须遍历整个队列才能计数（官方文档明确说明）

**选型建议**：
| 场景 | 推荐 |
|------|------|
| 线程池任务队列 | `ArrayBlockingQueue` / `LinkedBlockingQueue` |
| 高并发消息传递（允许丢失） | `ConcurrentLinkedQueue` |
| 需要限流 | `Semaphore` + `ConcurrentLinkedQueue` |
| 单生产者多消费者 | JCTools 的 `MpscQueue`（更优） |

</details>

---

## 下一步

1. 盲答后，对比参考要点，找到卡壳的地方
2. 打开 `[[并发队列选型]]` 文档，把无锁 vs 阻塞的选型决策树补充进去
3. 在 Obsidian 里建双向链接：`[[02_并发编程/BlockingQueue实现原理]]` ←→ 本卡片
4. 在 `[[12_面试训练/每日一题跟踪表]]` 里勾选「今日完成」，打 1~5 分
