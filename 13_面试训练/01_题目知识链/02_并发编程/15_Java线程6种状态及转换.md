# 题目：Java 线程有哪几种状态？它们之间是怎么转换的？

---

## ⚠️ 先盲答

**不要看任何资料，用自己的话回答，写到纸上或心里默念也行。**

---

## 盲答引导

1. Java 线程的 6 种状态是什么？分别用中文和英文说出来。
2. `Blocked` 和 `Waiting` 有什么区别？各是什么代码导致的？
3. `t.start()` 之后线程一定立刻运行吗？`Runnable` 状态意味着什么？
4. `Thread.sleep()` 和 `Object.wait()` 对锁的影响有什么不同？
5. 线程执行完后，还能再 `start()` 一次吗？

---

## 知识链提示

这道题应该让你联想到：

- `线程状态转换图` → 6 种状态的完整流转路径
- `synchronized阻塞` → Blocked 状态只由 synchronized 引起
- `[[wait/notify]]` → Waiting / Timed_Waiting 的入口
- `[[02_并发编程/08_线程池/线程池]]` → 为什么线程池的线程是复用的，不会 TERMINATED
- `jstack分析` → 线上排查时看到的线程状态对应这6种

---

## 核心追问

1. 下面代码，线程 A 调用 `wait()` 后，状态是什么？B 拿到锁后，A 的状态变成什么？
2. `Thread.yield()` 会让线程进入什么状态？`Thread.sleep(0)` 呢？
3. `LockSupport.park()` 让线程进入什么状态？和 `wait()` 有什么区别？
4. 为什么 `RUNNABLE` 包含了传统 OS 的「就绪」和「运行」两种状态？
5. `synchronized` 阻塞的线程，interrupt() 后状态怎么变？

---

## 参考要点（盲答后再看）


**6 种状态（必须背熟）**：

| 状态 | 进入原因 | 退出方式 |
|------|---------|---------|
| `NEW` | 创建后未 start | start() → RUNNABLE |
| `RUNNABLE` | 就绪或运行中 | 拿到 CPU 时间片就运行 |
| `BLOCKED` | 等 synchronized 锁 | 拿到锁 → RUNNABLE |
| `WAITING` | wait() / join() / park() | 被 notify()/unpark() → RUNNABLE |
| `TIMED_WAITING` | sleep(time) / wait(time) / join(time) | 超时或被唤醒 → RUNNABLE |
| `TERMINATED` | run() 执行完毕或异常退出 | 终态，不可再 start |

**状态转换图（核心）**：
```
NEW → start() → RUNNABLE ⇄ (CPU调度) ⇄ RUNNING
                    ↓ BLOCKED（等 synchronized 锁）
                    ↓ WAITING（wait/join/park）
                    ↓ TIMED_WAITING（sleep/time_wait）
RUNNABLE → run()结束 → TERMINATED
```

**BLOCKED vs WAITING（高频辨析）**：
| | BLOCKED | WAITING |
|--|---------|----------|
| 原因 | 等 synchronized 锁 | 调用 wait()/join()/park() |
| 唤醒 | 锁被释放，自动竞争 | 必须被 notify()/unpark() |
| 释放锁 | 是（synchronized 块结束） | 是（wait() 释放持有的锁） |

**sleep vs wait（经典题）**：
```java
synchronized (obj) {
    Thread.sleep(1000);  // 抱着锁睡觉！不会释放锁
    obj.wait(1000);      // 释放锁，等 1 秒或被唤醒后重新竞争锁
}
```

**线程不能重复 start**：
```java
Thread t = new Thread(()->{});
t.start();   // ✅
t.start();   // ❌ IllegalThreadStateException（线程已 TERMINATED）
```


---

## 下一步

1. 盲答后，对比参考要点，找到卡壳的地方
2. 打开 `线程状态` 主题文档，手画状态转换图
3. 在 Obsidian 里建双向链接：`[[10_计算机基础/02_操作系统/进程与线程]]` 关联学习
4. 在 `[[13_面试训练/03_每日一题/每日一题跟踪表]]` 里勾选「今日完成」，打 1~5 分
