# 什么是 JMM？它解决了什么问题？

> ⚠️ **先盲答**：JMM 是什么？它和 JVM 运行时数据区是一回事吗？

---

## 盲答引导

1. JMM 的全称是什么？它和「JVM 运行时数据区」有什么区别？
2. CPU 缓存和主内存的关系是什么？为什么需要缓存？
3. 什么是**可见性**问题？—— 一个线程改了变量，其他线程看不到
4. Happens-Before 是什么？它能保证什么？

---

## 知识链提示

```
JMM 内存模型
  → [[内存模型]]
    → 为什么需要 JMM
      → CPU 多核缓存架构：每个核有自己的 L1/L2 缓存，共享主内存
      → 线程 A 在核 1 改了变量，线程 B 在核 2 可能还是旧值（缓存未刷新）
      → JMM 规定了「什么情况下可以看到其他线程的修改」
    → 三大特性
      → 可见性：线程 A 改了 x，其他线程能立即看到
        → [[volatile关键字]] → 强制刷缓存
      → 原子性：操作要么全成功要么全失败（不被其他线程打断）
        → synchronized / CAS
      → 有序性：代码顺序按程序员意图执行
        → volatile / synchronized 禁止指令重排序
    → Happens-Before 规则（8条）
      → 程序顺序规则：同一线程内，前面的操作 happens-before 后面的
      → volatile 规则：volatile 写 happens-before 后续的 volatile 读
      → 传递性：A happens-before B，B happens-before C → A happens-before C
        → [[volatile关键字]] → H-B 规则之一
```

---

## 核心追问

| 追问 | 考点 |
|------|------|
| Happens-Before 是「时间先后」的意思吗？ | 不是，时间上可能先发生，但 JMM 不保证可见性 |
| volatile 是怎么保证可见性的？ | 写操作后强制刷主存，读操作强制从主存取 |
| synchronized 保证了哪些 JMM 特性？ | 原子性 + 可见性 + 有序性 |
| double-check 单例为什么要用 volatile？ | 防止构造方法重排 |

---

## 参考答案要点

**JMM vs JVM 运行时数据区**：
- JVM 数据区：JVM 运行时内存的具体布局
- JMM：一种规范，定义线程间「什么时候能看到彼此的修改」

**JMM 解决的核心问题**：多核 CPU 缓存不一致 → 通过缓存一致性协议 + 内存屏障解决。

**Happens-Before**：不是指时间上的先后，而是「JMM 保证的结果上的可见性」。

---

## 下一步

打开 [[内存模型]]，对比 [[volatile关键字]]，补充链接：「volatile 之所以能保证可见性，是因为它触发了 JMM 的「volatile 规则」——写 happens-before 读，这个保证是靠内存屏障强制刷新 CPU 缓存实现的」。
