# ReentrantLock 和 synchronized 有什么区别？

> ⚠️ **先盲答**：两者都是锁，它们的核心区别是什么？什么情况下选 ReentrantLock 而不是 synchronized？

---

## 盲答引导

1. 从**使用方式**上，两者有什么区别？（需要手动解锁吗？）
2. 从**功能特性**上，synchronized 没有、ReentrantLock 有的特性是什么？
3. 从**性能**上，JDK 6 之后两者差距大吗？哪个更好？
4. 从**底层实现**上，两者的等待方式有什么不同？

---

## 知识链提示

```
ReentrantLock vs synchronized
  → ReentrantLock与显式锁
    → 功能差异
      → ReentrantLock：可中断、可超时、公平锁
      → synchronized：不可中断、不可超时、非公平（JVM 控制）
    → 底层实现
      → synchronized：JVM 内置，编译后是 monitorenter/monitorexit
        → synchronized关键字 → JDK 6 优化：偏向锁/轻量级锁/重量级锁
      → ReentrantLock：基于 AQS，JDK 实现
        → [[02_并发编程/04_AQS/AQS]] → tryAcquire() CAS + CLH 队列
    → 性能对比
      → JDK 6 前：synchronized 性能差
      → JDK 6 后：锁升级机制让 synchronized 接近 ReentrantLock
      → JDK 15+：轻量级锁竞争激烈仍会膨胀
    → 选型建议
      → 需要 lock.lockInterruptibly() → 必须 ReentrantLock
      → 需要 tryLock(timeout) → 必须 ReentrantLock
      → 需要公平锁 → ReentrantLock(true)
      → 普通同步块 → synchronized 足够，代码更简洁
```

---

## 核心追问

| 追问 | 考点 |
|------|------|
| ReentrantLock 的公平锁和非公平锁，内部实现有什么区别？ | 公平锁多一步检查队列 |
| synchronized 在 JDK 6 之后做了哪些优化？ | 锁升级过程 |
| tryLock() 和 lock() 的区别是什么？ | 非阻塞获取 |
| ReentrantLock 如何保证可重入？ | state 计数器 |

---

## 参考答案要点

| 对比维度 | synchronized | ReentrantLock |
|---------|-------------|----------------|
| 获取/释放 | 自动（JVM 控制） | 必须手动 unlock() |
| 可中断 | ❌ | ✅ lockInterruptibly() |
| 可超时 | ❌ | ✅ tryLock(timeout) |
| 公平锁 | ❌ | ✅ new ReentrantLock(true) |
| 多条件 Condition | ❌（只有 wait/notify） | ✅ newCondition() |
| 底层 | monitorenter + OS mutex | AQS + CAS |
| 代码简洁 | ✅ | ❌ |

**选型原则**：功能需求驱动——需要可中断/超时/多条件 → ReentrantLock；否则 synchronized 更简洁。

---

## 下一步

打开 ReentrantLock与显式锁，对比 synchronized关键字，补充 `双向链接`：「synchronized 是 JVM 内置锁，ReentrantLock 是 JDK 层面的实现，功能更丰富但代码更繁琐」。
