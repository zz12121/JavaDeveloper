# 题目：CAS 是什么？ABA 问题是什么？如何解决？

---

## ⚠️ 先盲答

**不要看任何资料，用自己的话回答，写到纸上或心里默念也行。**

---

## 盲答引导

1. CAS 的全称是什么？它是一条 CPU 指令吗？Java 里怎么用 CAS？
2. CAS 有哪三个操作数？「比较并交换」具体比较的是什么？
3. 什么叫 ABA 问题？举个具体的例子说明它为什么会造成隐患。
4. `AtomicStampedReference` 是怎么解决 ABA 的？它的 stamp 是什么？
5. CAS 的「自旋」是什么意思？高并发下会有什么问题？

---

## 知识链提示

这道题应该让你联想到：

- `Unsafe类` → Java 直接调用 native CAS 的入口
- `[[13_面试训练/01_题目知识链/02_并发编程/11_CAS操作与ABA问题]]` → 版本号思想，数据库乐观锁也用
- `[[02_并发编程/05_CAS与原子类/CAS与原子类]]` → AtomicInteger/AtomicReference 底层都是 CAS
- `自旋锁` → CAS + 循环，高并发下 CPU 开销大
- `LongAdder分段思想` → 缓解 CAS 热点问题的方案

---

## 核心追问

1. `AtomicInteger.incrementAndGet()` 的源码是怎么写的？为什么叫「Unsafe」？
2. CAS 失败后会怎么做？一直重试会有什么问题？
3. `AtomicMarkableReference` 和 `AtomicStampedReference` 有什么区别？
4. 数据库乐观锁的 version 字段和 CAS 的版本号思想一样吗？
5. `synchronized` 在 JDK6 之后为什么比 CAS 在某些情况下性能更好？

---

## 参考要点（盲答后再看）


**CAS 本质**：Compare-And-Swap，是一条 CPU 原子指令（cmpxchg）。
```java
// AtomicInteger 核心逻辑
public final int incrementAndGet() {
    int current;
    do {
        current = value;           // 读当前值
    } while (!compareAndSet(current, current + 1));  // CAS 失败就重试
    return current + 1;
}
```

**ABA 问题（经典场景）**：
```
时刻1：线程A读到 value=A
时刻2：线程B把 value 改成 B，又改回 A
时刻3：线程A执行 CAS，发现 value 还是 A → 成功！但实际中间发生过变化
```
→ 如果业务逻辑只关心「值是否变化」，ABA 无所谓；
→ 如果业务逻辑关心「值有没有被别人动过」，ABA 就是隐患（如链表头插法）。

**AtomicStampedReference 解决 ABA**：
```java
// 不仅比较值，还比较版本号（stamp）
compareAndSet(expectedRef, newRef, expectedStamp, newStamp);
```

**CAS 的局限**：
| 问题 | 说明 |
|------|------|
| ABA | 值被改了又改回来，CAS 无感知 |
| 循环开销 | 高并发下大量线程自旋，浪费 CPU |
| 单变量限制 | CAS 只能保证一个变量的原子性（AtomicReference 可包装多个变量） |

**Unsafe 类**：
- Java 不直接暴露 CAS，通过 `sun.misc.Unsafe`（JDK8）或 `VarHandle`（JDK9+）
- 名字叫「Unsafe」是因为可以直接操作内存地址，非常危险


---

## 下一步

1. 盲答后，对比参考要点，找到卡壳的地方
2. 打开 `[[13_面试训练/01_题目知识链/02_并发编程/11_CAS操作与ABA问题]]` 主题文档，把 ABA + AtomicStampedReference 整理进去
3. 在 Obsidian 里建双向链接：`[[02_并发编程/04_AQS/AQS]]` ←→ 本卡片（AQS 底层也是 CAS）
4. 在 `[[13_面试训练/03_每日一题/每日一题跟踪表]]` 里勾选「今日完成」，打 1~5 分
