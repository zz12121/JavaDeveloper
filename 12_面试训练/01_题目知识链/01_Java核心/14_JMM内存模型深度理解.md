# 题目：Java 内存模型（JMM）是什么？它解决了什么问题？和 JVM 内存结构是一回事吗？

---

## ⚠️ 先盲答

**不要看任何资料，用自己的话回答，写到纸上或心里默念也行。**

---

## 盲答引导

1. JMM 和 JVM 运行时数据区（堆、栈、方法区）是同一个东西吗？如果不是，区别在哪？
2. 什么叫「可见性」问题？一个线程修改了变量，另一个线程一定立刻能看到吗？
3. `volatile` 关键字的本质是什么？它保证了哪几点？
4. happens-before 规则有哪些？写出至少 3 条。
5. double-check 单例模式为什么需要 volatile？不加会出什么问题？

---

## 知识链提示

这道题应该让你联想到：

- `[[volatile原理]]` → 内存屏障、禁止指令重排
- `[[CPU缓存一致性]]` → MESI 协议，Store Buffer，Invalid Queue
- `[[happens-before]]` → JMM 的核心抽象，比"锁和volatile"更好记
- `[[指令重排]]` → 编译器重排、CPU 乱序执行
- `[[double-check单例]]` → 经典可见性+原子性综合题

---

## 核心追问

1. JMM 的八大操作（lock/unlock/read/write/load/store/use/assign）你还记得吗？
2. `volatile` 能保证复合操作的原子性吗？比如 `i++`？
3. happens-before 规则中，"线程启动"、"线程终止"、"中断"各有什么保证？
4. 64位数据类型（long/double）在 32 位 JVM 上读写是原子的吗？volatile 能解决吗？
5. `synchronized` 能保证可见性吗？它和 `volatile` 的可见性保证有什么不同？

---

## 参考要点（盲答后再看）

<details>
<summary>点击展开</summary>

**JMM vs JVM 内存结构（常混淆）**：
- JVM 内存结构：堆、栈、方法区——描述的是**内存分区**
- JMM：定义了线程和主内存之间的抽象关系——描述的是**可见性规则**
- 两者完全不是一个层次的东西

**三大问题**：
| 问题 | 含义 |
|------|------|
| 可见性 | 一个线程修改了共享变量，其他线程不一定立刻看到 |
| 原子性 | 操作是否不可中断（i++ 不是原子的） |
| 有序性 | 编译器和 CPU 可能重排指令 |

**volatile 的保证**（JMM 层面）：
1. 可见性：写操作立刻刷新到主内存，读操作从主内存读
2. 禁止指令重排：在读/写前后插入内存屏障
3. **不保证原子性**

**happens-before 规则（重点记忆）**：
1. 程序次序规则：同一个线程内，前面的操作 happens-before 后面的
2. volatile 规则：写 happens-before 读
3. synchronized 规则：unlock happens-before 后面的 lock
4. 线程启动：thread.start() happens-before 新线程的第一个操作
5. 线程终止：线程的所有操作 happens-before 其他线程检测到它终止
6. 传递性：A hb B，B hb C → A hb C

**double-check 单例（经典题）**：
```java
private static volatile Singleton instance;  // 必须 volatile
private Singleton() {}
public static Singleton getInstance() {
    if (instance == null) {                    // 第一次检查
        synchronized (Singleton.class) {
            if (instance == null) {            // 第二次检查
                instance = new Singleton();    // ⚠️ 这里会指令重排
            }
        }
    }
    return instance;
}
// 问题：new Singleton() 分三步：
// 1. 分配内存  2. 初始化对象  3. 指向内存地址
// 2和3可能重排，另一个线程拿到未初始化的对象 → volatile 禁止重排
```

</details>

---

## 下一步

1. 盲答后，对比参考要点，找到卡壳的地方
2. 打开 `[[JMM内存模型]]` 主题文档，把 happens-before 规则整理成表格
3. 在 Obsidian 里建双向链接：`[[02_并发编程/volatile原理]]` ←→ 本卡片
4. 在 `[[12_面试训练/每日一题跟踪表]]` 里勾选「今日完成」，打 1~5 分
