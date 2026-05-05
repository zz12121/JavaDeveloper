# ThreadLocal 有什么坑？内存泄漏是怎么回事？

> ⚠️ **先盲答**：ThreadLocal 是什么？它的实现原理是什么？什么情况下会内存泄漏？

---

## 盲答引导

1. ThreadLocal 的**数据结构**是什么样的？key 和 value 分别存在哪？
2. 为什么说 ThreadLocalMap 的 Entry 持有的是**弱引用**（WeakReference）？
3. 弱引用 + 内存泄漏是什么逻辑？—— key 是弱引用会被 GC，value 不会
4. 既然有泄漏风险，为什么 JDK 不直接清理？—— 跟延迟清理的权衡有关
5. 正确的使用方式是什么？为什么要放在 finally 里 remove？

---

## 知识链提示

```
ThreadLocal 线程本地变量
  → [[ThreadLocal线程本地变量]]
    → 数据结构
      → ThreadLocalMap（Thread 类里）
        → ThreadLocal 作为 key（WeakReference）
        → value 作为强引用存在 Entry[]
          → key（ThreadLocal）被 GC → Entry.key = null
          → value 还在，但再也访问不到了 → 内存泄漏
      → Thread.currentThread() → ThreadLocalMap.getMap(this)
    → 弱引用 vs 强引用
      → 强引用：gcRoots 不可达才回收
      → 弱引用：下次 GC 就回收，不管是否可达
        → JDK 故意用弱引用做 key → 让 GC 能自动清理无用的 key
    → 内存泄漏的完整链路
      → ThreadLocal 用完 → 没有 remove()
        → Thread 存活（线程池复用）→ ThreadLocalMap 永在
        → Entry.key 被 GC → value 泄漏
    → ThreadLocal 适合场景
      → 数据库连接、Session、用户上下文
      → [[线程池]] → 线程复用 = 泄漏风险放大
```

---

## 核心追问

| 追问 | 考点 |
|------|------|
| JDK 为什么要用 WeakReference 作为 key？ | 自动清理无用 Entry |
| 如果用强引用做 key，会有什么问题？ | key 永远不回收，泄漏更严重 |
| ThreadLocal 在线程池环境下为什么更危险？ | 核心线程永不退出 |
| InheritableThreadLocal 和普通 ThreadLocal 有什么区别？ | 子线程继承父线程的值 |

---

## 参考答案要点

**ThreadLocalMap 的 Entry 用 WeakReference 持有 ThreadLocal**：是 JDK 的主动保护——当 ThreadLocal 对象不再被外部引用时，下一次 GC 会把 Entry.key 设为 null，value 变得不可达。

**泄漏的完整链路**：线程池复用线程 → Thread 长期存活 → ThreadLocalMap 长期存在 → ThreadLocal 用完没 remove → key 被 GC 但 value 还在 → value 泄漏。

**正确用法**：`try { set(); ... } finally { remove(); }`

---

## 下一步

打开 [[ThreadLocal线程本地变量]]，补充 `[[双向链接]]`：「ThreadLocal 本身不泄漏，泄漏的是 ThreadLocalMap 里的 value——特别是线程池复用线程时，这个问题会被放大」。
