# 题目：ConcurrentHashMap 在 JDK7 和 JDK8 中的实现有什么区别？为什么 JDK8 放弃了分段锁？

---

## ⚠️ 先盲答

**不要看任何资料，用自己的话回答，写到纸上或心里默念也行。**

---

## 盲答引导

1. JDK7 的 ConcurrentHashMap 为什么叫"分段锁"？Segment 是什么？
2. JDK8 之后用的是什么机制保证线程安全？CAS + synchronized 分别用在什么场景？
3. 为什么 JDK8 认为分段锁的锁粒度还是太粗了？
4. ConcurrentHashMap 的 size() 方法在 JDK7 和 JDK8 中分别怎么实现的？有什么坑？
5. 有了 ConcurrentHashMap，还要不要用 Collections.synchronizedMap？

---

## 知识链提示

这道题应该让你联想到：

- `[[HashMap底层结构]]` → CHM 的基础是 HashMap（数组+链表+红黑树）
- `[[synchronized锁升级]]` → JDK8 中 CHM 用 synchronized 锁单个桶，锁升级对它有影响吗？
- `[[CAS操作]]` → 无锁化的核心，但 ABA 问题怎么处理？
- `[[分段锁vs细粒度锁]]` → 设计演进背后的权衡
- `[[size()的精确性]]` → JDK7 用 tryLock 多次重试，JDK8 用 CounterCell

---

## 核心追问

1. JDK8 中，CHM 的 put 操作什么情况下用 CAS，什么情况下用 synchronized？
2. 红黑树化阈值为什么是 8？退化阈值为什么是 6？
3. CHM 支持 null 键值吗？为什么这么设计？
4. JDK7 的 Segment 继承 ReentrantLock，JDK8 直接用 synchronized，哪个性能更好？为什么？
5. 并发度（concurrencyLevel）参数在 JDK7 和 JDK8 中意义一样吗？

---

## 参考要点（盲答后再看）

<details>
<summary>点击展开</summary>

**JDK7：分段锁（Segment）**
```
ConcurrentHashMap
  └── Segment[]  (继承 ReentrantLock，默认16个)
        └── HashEntry[]  (每个Segment独立一个哈希表)
```
- 锁粒度：每个 Segment 独立加锁，支持 16 个线程并发写
- 缺陷：锁粒度仍然偏粗，且 Segment 数量初始化后不可扩容

**JDK8：CAS + synchronized（锁单个桶）**
```
ConcurrentHashMap
  └── Node[] table  (和 HashMap 结构一致)
       └── 每个桶头节点用 synchronized 锁
       └── 无冲突时用 CAS 插入
```
- 锁粒度：精确到单个桶（table[i]），并发度 = 桶数量
- size()：用 CounterCell[] 分散计数，避免竞争

**为什么放弃分段锁？**
1. 分段锁的并发度固定（初始化指定），无法动态扩展
2. 单个 Segment 内的所有条目仍然串行访问
3. JDK8 的 synchronized 已经过锁升级优化，性能接近 ReentrantLock
4. CAS 无锁化在低冲突时性能更好

**关键源码逻辑（put）**：
```java
// JDK8 putVal 核心逻辑（简化）
if (tab == null 或 桶为空) {
    CAS 创建新节点  // 无锁
} else {
    synchronized (桶头节点) {  // 只锁这个桶
        插入或更新
    }
}
```

</details>

---

## 下一步

1. 盲答后，对比参考要点，找到卡壳的地方
2. 打开 `[[ConcurrentHashMap]]` 主题文档，把 JDK7/JDK8 差异补充完整
3. 在 Obsidian 里建双向链接：`[[07_中间件/Redis线程模型]]` 对比参考（Redis 也是单线程+IO多路复用）
4. 在 `[[12_面试训练/每日一题跟踪表]]` 里勾选「今日完成」，打 1~5 分
