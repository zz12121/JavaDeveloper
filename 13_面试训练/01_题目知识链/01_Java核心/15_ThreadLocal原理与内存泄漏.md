# 题目：ThreadLocal 是怎么实现的？为什么会有内存泄漏？如何正确使用时避免泄漏？

---

## ⚠️ 先盲答

**不要看任何资料，用自己的话回答，写到纸上或心里默念也行。**

---

## 盲答引导

1. ThreadLocal 的 `set(value)` 是把值存在 ThreadLocal 对象里，还是存在 Thread 对象里？
2. Thread 对象里有一个 `threadLocals` 字段，它的类型是什么？底层是 Map 吗？
3. ThreadLocalMap 的 key 是什么？是强引用还是弱引用？为什么这样设计？
4. 如果线程一直不结束（比如线程池核心线程），ThreadLocal 里的 value 会被 GC 回收吗？
5. 使用 ThreadLocal 后，为什么强烈建议调用 `remove()`？

---

## 知识链提示

这道题应该让你联想到：

- `四种引用类型` → 弱引用（WeakReference）在 ThreadLocalMap 中的应用
- `[[02_并发编程/08_线程池/线程池]]` → 核心线程不退，value 永远不被回收
- `[[01_Java核心/05_集合框架/HashMap]]` → ThreadLocalMap 用线性探测法，不是链表
- `InheritableThreadLocal` → 子线程如何继承父线程的 ThreadLocal
- `Spring事务上下文` → TransactionSynchronizationManager 用 ThreadLocal 存连接

---

## 核心追问

1. ThreadLocal 的哈希冲突怎么解决？和 HashMap 的链地址法有什么不同？
2. ThreadLocalMap 的 key 是弱引用，GC 后 key 变成 null，这时候 value 还在吗？谁来清理？
3. `InheritableThreadLocal` 是在什么时候把父线程的值传给子线程的？
4. 线程池场景下，Task1 设了 ThreadLocal，Task2 没有设，会读到 Task1 的值吗？
5. Netty 的 `FastThreadLocal` 和 JDK 的 ThreadLocal 有什么区别？

---

## 参考要点（盲答后再看）


**存储位置（重点）**：
```java
// Thread 类里有：
ThreadLocal.ThreadLocalMap threadLocals = null;
```
每个 Thread 自己持有一个 Map，ThreadLocal 只是 key。不是存在 ThreadLocal 对象里！

**ThreadLocalMap 结构**：
- key：ThreadLocal 对象（被 WeakReference 包装）
- value：你 set 进去的对象
- 哈希冲突解决：**线性探测法**（挨个往后找空位），不是链表

**内存泄漏的根本原因**：
```
ThreadRef → Thread → ThreadLocalMap → Entry[] 
                                    ↓
                              key(WeakReference) → ThreadLocal对象
                              value(强引用) → 业务对象  ← 泄漏点
```
- key 是弱引用：ThreadLocal 外部没有强引用时，GC 会把 key 回收（entry.key == null）
- value 是强引用：**只要线程不死，value 永远可达，无法回收**
- 线程池核心线程几乎不死 → 累积泄漏

**正确用法**：
```java
try {
    threadLocal.set(value);
    // ... 业务逻辑
} finally {
    threadLocal.remove();  // 必须！
}
```

**ThreadLocalMap 的清理机制**：
- `set/get/remove` 时顺带清理 key==null 的 entry（但不是万能的）
- 不能依赖自动清理，必须手动 `remove()`

**InheritableThreadLocal**：
- 在 `Thread.init()` 时，把父线程的 inheritableThreadLocals 复制给子线程
- 局限：线程池场景下，任务是在已有的线程里跑的，不会触发复制


---

## 下一步

1. 盲答后，对比参考要点，找到卡壳的地方
2. 打开 `[[02_并发编程/12_ThreadLocal/ThreadLocal线程本地变量]]` 主题文档，画出 Thread → ThreadLocalMap → Entry 的引用关系图
3. 在 Obsidian 里建双向链接：`[[02_并发编程/08_线程池/线程池]]` 关联学习（线程池 + ThreadLocal 是经典坑）
4. 在 `[[13_面试训练/03_每日一题/每日一题跟踪表]]` 里勾选「今日完成」，打 1~5 分
