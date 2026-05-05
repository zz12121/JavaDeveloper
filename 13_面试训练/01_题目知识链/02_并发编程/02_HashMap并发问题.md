# HashMap 在并发场景下有哪些问题？

> ⚠️ **先盲答**：不要看答案，先用自己的话列举「并发下 HashMap 会出什么问题」。

---

## 盲答引导

1. 两个线程同时 put，**可能发生什么**？
2. resize 时具体会怎样？哪一步出问题？
3. JDK 7 和 JDK 8 在并发 resize 上的表现有什么不同？
4. 有没有其他并发安全的 Map 可以用？各自特点是什么？

---

## 知识链提示

```
HashMap 并发问题
  → [[HashMap底层实现]] → 数组 + 链表/红黑树
    → put 流程：hash → 寻址 → 插入
      → resize 流程：新建数组 → 迁移元素
        → JDK 7：头插法 → 并发迁移时链表会成环
          → [[ConcurrentHashMap]] 怎么解决？ → JDK 7 用了 Segment 分段锁
        → JDK 8：尾插法 + synchronized 头节点 → 仍可能丢数据但不环
  → 并发安全替代方案
    → Hashtable（全局锁）→ 性能差
    → Collections.synchronizedMap（全局锁）→ 性能差
    → ConcurrentHashMap（JDK 7 分段锁，JDK 8 CAS+synchronized）→ 推荐
    → ConcurrentSkipListMap（跳表，并发安全有序）→ 有序场景
```

---

## 核心追问

| 追问 | 考点 |
|------|------|
| JDK 7 resize 成环的具体过程是什么？ | 数据结构 + 并发 |
| ConcurrentHashMap JDK 7 和 JDK 8 本质区别是什么？ | 分段锁 vs CAS+syn |
| ConcurrentHashMap 的 size() 准不准？为什么？ | 并发计数近似值 |
| 什么时候应该用 ConcurrentSkipListMap 而不是 ConcurrentHashMap？ | 有序需求 |

---

## 参考答案要点

**JDK 7 头插法**：resize 时，A 线程迁移到新数组，B 线程也在迁移，链表方向被反转，可能成环 → get 时死循环 CPU 100%。

**JDK 8 尾插法**：解决了成环问题，但仍有丢数据风险（put 时覆盖）。

**正确选择**：并发场景只用 `ConcurrentHashMap`，不要用 `HashMap`。

---

## 下一步

打开 [[HashMap底层实现]] 文档，添加一条 `[[双向链接]]`：「并发下 HashMap 会成环，这个坑JDK 8 用尾插法部分解决了，但根本解法是换 ConcurrentHashMap」。
