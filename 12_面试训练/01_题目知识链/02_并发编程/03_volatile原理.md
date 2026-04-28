# volatile 解决了什么问题？它是如何实现的？

> ⚠️ **先盲答**：volatile 关键字的作用是什么？它在什么场景下需要用？

---

## 盲答引导

1. volatile 和 synchronized 都是 Java 并发关键字，它们解决的**问题一样吗**？
2. volatile 保证了什么？**没保证什么**？
3. volatile 写操作之后，为什么后续读一定能读到新值？—— 底层靠什么？
4. 单例模式中 double-check 为什么需要 volatile？

---

## 知识链提示

```
volatile 的作用
  → [[volatile关键字]]
    → [[JMM内存模型]] → 8种 Happens-Before 规则
      → volatile 写 happens-before 后续 volatile 读
        → 禁止指令重排序：编译器/CPU 可能重排
          → 内存屏障：storestore / storeload / loadstore / loadload
            → x86 的 MFENCE / SFENCE / LFENCE
        → 强制刷新缓存：写操作把数据从线程本地缓存刷到主存
          → 后续读从主存取，不走本地缓存
    → volatile 的局限性
      → 不保证原子性：i++ 这种 read-modify-write 不是原子的
        → [[CAS与原子类]] → 用自旋 CAS 解决
        → [[synchronized关键字]] → 用互斥解决
  → double-check 单例
    → [[JVM类加载机制]] → new Object() 不是原子操作
      → 分配内存 → 调用构造方法 → 建立引用
      → 2和3可能重排 → 其他线程可能拿到未构造完的对象
      → volatile 禁止构造方法重排
```

---

## 核心追问

| 追问 | 考点 |
|------|------|
| Happens-Before 是什么意思？它和「时间先后」有什么区别？ | JMM 语义 |
| volatile 和普通变量的区别仅靠禁止重排序吗？ | 缓存刷新机制 |
| volatile 能替代 synchronized 吗？什么情况下不能？ | 原子性缺口 |
| 双重检查锁单例中，volatile 去掉会怎样？ | 对象创建重排 |

---

## 参考答案要点

**volatile 的两个作用**：
1. **禁止指令重排序**：通过内存屏障实现（StoreStore / LoadLoad 等）
2. **保证可见性**：volatile 写会强制把本地缓存刷到主存，后续 volatile 读从主存取

**volatile 不保证原子性**：i++ 这种操作仍需要 synchronized 或 CAS。

**double-check 中的 volatile**：防止 `new Object()` 指令重排（分配内存 → 赋值引用 → 调用构造），导致其他线程拿到半初始化对象。

---

## 下一步

打开 [[volatile关键字]] 文档，对比 [[JMM内存模型]]，补充 `[[双向链接]]`：「volatile 的可见性靠的是内存屏障把本地缓存刷到主存，这背后是 JMM 的 Happens-Before 规则在保证」。
