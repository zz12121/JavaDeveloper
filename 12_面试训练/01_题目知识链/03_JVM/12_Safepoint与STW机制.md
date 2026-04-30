# 题目：Safepoint 是什么？Stop-The-World 是怎么发生的？

---

## ⚠️ 先盲答

**不要看任何资料，用自己的话回答，写到纸上或心里默念也行。**

---

## 盲答引导

1. 什么叫「Safepoint」？线程跑到哪个位置才可以「安全」地停下来？
2. GC 要让所有线程进入 Safepoint 才能开始，这个过程叫什么？
3. 偏向锁撤销为什么要 STW？其他锁升级也需要 STW 吗？
4. `jstack` 能打印线程栈，它触发了什么机制？
5. 什么叫「主动中断」（active interrupt）？VM Thread 是怎么让线程停下来的？

---

## 知识链提示

这道题应该让你联想到：

- `[[Stop-The-World]]` → GC 停顿的本质
- `[[OopMap]]` → 在 Safepoint 位置，JVM 才能准确知道栈上哪些位置是引用
- `[[偏向锁撤销]]` → 典型的 STW 场景
- `[[jstack/jmap触发机制]]` → 这些工具都需要进入 Safepoint
- `[[ZGC无Safepoint]]` → 着色指针让 ZGC 不需要全局 Safepoint

---

## 核心追问

1. Safepoint 通常设置在哪里？（方法调用、循环边界、异常抛出点）
2. 线程处于 `Blocked`（等锁）状态时，能进入 Safepoint 吗？
3. 如果有一个线程一直在跑 `while(true)` 且没有任何函数调用，它会永远不进入 Safepoint 吗？
4. `XX:+SafepointTimeout` 是干什么的？用来排查什么问题？
5. ZGC 为什么不需要让所有线程都停在 Safepoint？

---

## 参考要点（盲答后再看）

<details>
<summary>点击展开</summary>

**Safepoint 定义**：代码中某些特定位置，线程在这里停下来时，JVM 的堆状态是「可观察且一致的」，可以安全地进行 GC。

**Safepoint 位置**（JIT 编译代码/解释器）：
- 方法调用返回点
- 循环跳转点（有界循环，JDK10+）
- 异常抛出点

**进入 Safepoint 的过程**（核心机制）：
```
1. VM Thread 发起 GC 请求
2. 设置「全局锁」（Safepoint Locks）
3. 每个应用线程：
   - 解释器：取下一条字节码前检查 Safepoint 标志
   - JIT 代码：方法返回/循环跳转时检查
   - 如果线程在阻塞（synchronized）→ 已经「在 Safepoint」
4. 所有线程都到达 Safepoint → 开始 GC
```

**OopMap（关键概念）**：
- 在 Safepoint 位置，JIT 会生成一张「栈上引用映射表」（OopMap）
- GC 根据这个表准确知道栈上哪些位置是对象引用，不会漏标

**偏向锁撤销的 STW**（经典场景）：
```java
// 只有一个线程用锁 → 偏向模式（无 CAS）
// 第二个线程来竞争 → 需要撤销偏向 → STW（即使应用线程很多）
```

**线程跑长循环不进 Safepoint（隐患）**：
```java
// JDK9 之前：这种循环不会检查 Safepoint！
while (true) {  /* 空循环，没有函数调用 */ }

// JDK10+：C2 编译器会在长循环里插入 Safepoint 检查
```

**ZGC 的不同之处**：
- 不需要全局 Safepoint（只让触发 GC 的线程暂停）
- 通过「着色指针 + 读屏障」，并发标记不需要 "停止所有线程"

</details>

---

## 下一步

1. 盲答后，对比参考要点，找到卡壳的地方
2. 打开 `[[Safepoint与STW]]` 主题文档，画出「进入 Safepoint」的完整时序
3. 在 Obsidian 里建双向链接：`[[03_JVM/G1垃圾收集详细过程]]` ←→ 本卡片（Mixed GC 需要初始标记，触发 Safepoint）
4. 在 `[[12_面试训练/每日一题跟踪表]]` 里勾选「今日完成」，打 1~5 分
