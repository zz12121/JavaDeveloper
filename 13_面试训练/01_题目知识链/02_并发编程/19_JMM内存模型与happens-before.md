# 题目：什么是 JMM（Java 内存模型）？happens-before 规则是什么？用它如何推导可见性？

---

## ⚠️ 先盲答

**不要看任何资料，用自己的话回答。**

---

## 盲答引导

1. JMM 和 JVM 内存布局（堆/栈/方法区）是一回事吗？区别在哪里？
2. 线程的工作内存和主内存是什么关系？为什么一个线程的写入另一个线程看不到？
3. happens-before 的定义是什么？它保证的是什么？
4. happens-before 和"物理时间上的先后"是一回事吗？
5. volatile 写 hb 后续的 volatile 读——这句话怎么理解？

---

## 知识链提示

这道题应该让你联想到：

- `CPU 缓存一致性` → 为什么需要 JMM
- `as-if-serial 语义` → 编译器/CPU 重排但单线程结果不变
- `volatile` → 可见性 + 有序性，但不保证原子性
- `synchronized` → unlock 时刷新到主内存
- `final 初始化安全` → Java 5 引入的新保证

---

## 核心追问

1. 为什么 long/double 的非 volatile 读写可能读到"撕裂"的值？
2. `synchronized` 的可见性保证发生在 unlock 和后续 lock 之间——为什么不是 lock 时？
3. happens-before 规则有 8 条，列出其中 4 条并说明各解决什么问题。
4. 下面代码，线程 B 一定能打印 x=42 吗？为什么？
   ```java
   // 线程A
   x = 42;
   flag = true;  // volatile

   // 线程B
   if (flag) {   // volatile 读
       System.out.println(x);
   }
   ```
5. 构造器内泄露 this 引用会破坏 final 的初始化安全吗？具体怎么破坏？

---

## 参考要点（盲答后再看）

**JMM vs JVM 内存布局**：

```
JVM 内存布局（物理划分）：
  堆：对象分配
  栈：方法调用栈帧
  方法区：类信息

JMM 内存模型（抽象规范）：
  主内存：所有共享变量
  工作内存：每个线程的私有缓存/寄存器

JMM 是规范，不等于实际内存分区
→ HotSpot 中工作内存可能是 CPU 寄存器 + L1/L2 缓存
```

**happens-before 定义**：

> 如果 A hb B，则 A 的执行结果对 B 可见，且 A 的执行顺序排在 B 之前。

**⚠️ 不等于物理时间上的先后**——两个 CPU 可以并行执行，只要 B 最终看到 A 的正确结果。

**8 条规则**：

```
1. 程序顺序规则：同一线程中，前面的 hb 后面的
2. 监视器锁规则：unlock hb 后续同一锁的 lock
3. volatile 规则：volatile 写 hb 后续 volatile 读
4. start 规则：Thread.start() hb 线程内所有操作
5. join 规则：线程内所有操作 hb Thread.join() 返回
6. interrupt 规则：interrupt() hb 被中断线程检测到中断
7. 终结规则：构造函数结束 hb finalize() 开始
8. 传递性：A hb B 且 B hb C → A hb C
```

**volatile 可见性推导**：

```java
int x = 0;
volatile boolean flag = false;

// 线程A                    // 线程B
x = 42;                   if (flag) {
flag = true;                  System.out.println(x);
}                             }

// 推导：
// A: C(x=42) hb D(flag=true)  ← 程序顺序
// D hb E(flag读)              ← volatile 规则
// E hb F(x读)                 ← 程序顺序
// 传递性：C hb F → 线程B 一定看到 x=42
```

**final 初始化安全（Java 5+）**：

```java
public class Safe {
    private final int x;
    public Safe() { x = 42; }  // 构造器结束，其他线程一定看到 x=42
}

// ⚠️ 前提：不要在构造器内泄露 this 引用
// new Thread(() -> System.out.println(this.x)).start(); ← 危险！
```

**可见性机制对比**：

| 机制 | 可见性 | 有序性 | 原子性 | 阻塞 |
|------|--------|--------|--------|------|
| volatile | ✅ | ✅ | 仅读写 | ❌ |
| synchronized | ✅ | ✅ | ✅ | ✅ |
| Atomic* | ✅ | ✅ | ✅ | ❌ |
| Lock | ✅ | ✅ | ✅ | ✅ |

---

## 下一步

1. 盲答后，对比参考要点
2. 打开 `[[02_并发编程/02_JMM内存模型/JMM内存模型详解]]` 补充细节
3. 关联：`[[02_并发编程/02_JMM内存模型/volatile]]` 和 `[[02_并发编程/03_锁机制/锁机制]]`
4. 在 `[[13_面试训练/03_每日一题/每日一题跟踪表]]` 打卡
