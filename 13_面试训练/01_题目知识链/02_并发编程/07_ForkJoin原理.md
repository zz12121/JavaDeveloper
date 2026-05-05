# Fork/Join 框架的原理是什么？它和普通线程池有什么区别？

> ⚠️ **先盲答**：Fork/Join 是什么？它用来解决什么问题？

---

## 盲答引导

1. Fork/Join 的**分治思想**是什么意思？什么场景下适合用它？
2. ForkJoinPool 和普通线程池（ThreadPoolExecutor）核心区别是什么？
3. **工作窃取（Work-Stealing）** 是什么？为什么它比普通队列高效？
4. 什么是 ForkJoinTask？RecursiveTask 和 RecursiveAction 有什么区别？

---

## 知识链提示

```
Fork/Join 框架
  → [[ForkJoin框架]]
    → 核心思想：分治（Divide and Conquer）
      → 大任务 → 拆成小任务 → 并行执行 → 合并结果
      → 典型场景：归并排序、并行遍历、大数据量计算
    → ForkJoinPool vs ThreadPoolExecutor
      → 普通线程池：任务队列是共享的，所有线程抢同一个队列
        → [[阻塞队列]] → 争抢有开销
      → ForkJoinPool：每个线程有自己的双端队列
        → 工作窃取：自己的队列空了 → 从其他线程队列尾部偷任务
        → 减少争抢 + 利用多核
    → 工作窃取细节
      → 双端队列：自己从头部取（本地优先），从尾部偷（减少竞争）
      → 任务粒度：任务太小则分治开销大于并行收益
        → 用阈值控制：任务 < 阈值 → 顺序执行
```

---

## 核心追问

| 追问 | 考点 |
|------|------|
| 工作窃取会导致一个任务被多个线程处理吗？ | 不会，每个任务只被一个线程认领 |
| ForkJoinPool 是怎么实现「任务窃取」的？ | 双端队列 + CAS |
| 什么情况下 Fork/Join 比普通线程池慢？ | 任务太小、合并开销大、竞争激烈 |
| ForkJoinPool 的 commonPool 是什么？ | ForkJoinPool.commonPool() 共享池 |

---

## 参考答案要点

**Fork/Join 本质**：分治 + 工作窃取。

**和普通线程池的区别**：
- 普通线程池：所有线程共享一个任务队列，抢锁争用
- ForkJoinPool：每个线程有自己的队列 + 工作窃取，减少争用

**工作窃取流程**：
```
线程A队列：空 → 从线程B队列尾部偷一个任务 → 执行
```

**RecursiveTask vs RecursiveAction**：前者有返回值，后者没有。

---

## 下一步

打开 [[ForkJoin框架]]，补充 `[[双向链接]]`：「ForkJoin 的高效来自工作窃取——空了的线程去偷别人的任务，而不是所有人抢一个队列」。
