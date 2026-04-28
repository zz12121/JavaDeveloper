# AQS 抽象队列同步器

## 这个问题为什么存在？

> Java 没有提供「通用的锁」让开发者直接用，只提供了 `synchronized` 和 `wait/notify`。  
> 但 `synchronized` 不够灵活——**不能中断、不能超时、不能尝试获取、不能多个条件变量**。

AQS（AbstractQueuedSynchronizer）就是为了解决这个问题而生的：
- 它是一个**模板方法框架**，把「线程排队」这件事做透了
- 上层只需要实现「尝试获取/释放资源」的逻辑
- 常见的 `ReentrantLock`、`CountDownLatch`、`Semaphore`、`ReentrantReadWriteLock` 全部基于 AQS

**一句话理解**：AQS = 一个 `volatile int state` + 一个 CLH 双向队列 + 一套入队/出队/唤醒的模板方法。

---

## 它是怎么解决问题的？

### 核心机制

```
AQS 核心结构
┌─────────────────────────────────────────────┐
│  state: volatile int    ← 同步状态        │
│  head: Node             ← 队列头（哑元）   │
│  tail: Node             ← 队列尾           │
│  exclusiveOwnerThread   ← 独占模式持有线程 │
├─────────────────────────────────────────────┤
│  CLH 双向队列（FIFO）                      │
│  Node {                                 │
│    prev, next      ← 双向指针              │
│    thread          ← 排队的线程             │
│    waitStatus      ← 节点状态               │
│      0=初始, -1=SIGNAL, -2=CONDITION     │
│  }                                        │
└─────────────────────────────────────────────┘
```

#### state 的含义（由子类定义）

| 子类 | state 含义 |
|------|------------|
| `ReentrantLock` | 0=未锁定，>0=已重入次数 |
| `CountDownLatch` | 剩余计数 |
| `Semaphore` | 剩余许可数 |
| `ReentrantReadWriteLock` | 高16位读计数，低16位写计数 |

#### 两套模版方法

AQS 把「获取/释放」拆成两套，由子类选择性实现：

```
独占模式（exclusive）：
  tryAcquire(arg)     ← 尝试获取（子类实现）
  tryRelease(arg)     ← 尝试释放（子类实现）

共享模式（shared）：
  tryAcquireShared(arg)   ← 尝试获取（返回值≥0表示成功）
  tryReleaseShared(arg)   ← 尝试释放
```

---

### 源码关键路径：acquire（独占获取）

```java
// AbstractQueuedSynchronizer.java
public final void acquire(int arg) {
    if (!tryAcquire(arg) &&          // ① 先尝试获取（子类实现）
        acquireQueued(
            addWaiter(Node.EXCLUSIVE), arg))  // ② 获取失败，入队
        selfInterrupt();
}
```

**详细流程（面试追问重点）**：

```
线程 A 调用 lock()
  │
  ├─ tryAcquire(1) → 成功 → 设置 exclusiveOwnerThread = A → 返回
  │
  └─ tryAcquire(1) → 失败（被B持有）
       │
       ├─ addWaiter()：把 A 包装成 Node，CAS 追加到队尾
       │   如果 CAS 失败（并发入队），用 for(;;) 自旋重试
       │
       └─ acquireQueued()：自旋尝试获取，失败则 park
            │
            ├─ 前驱是 head → 再 tryAcquire 一次（机会窗口）
            │   └─ 成功 → 把自己设为 head，返回
            │
            └─ 前驱不是 head → shouldParkAfterFailedAcquire
                把前驱的 waitStatus 设为 SIGNAL（-1）
                └─ 下次循环 → parkAndCheckInterrupt() → LockSupport.park()
```

**为什么前驱的 waitStatus 要设为 SIGNAL？**

> SIGNAL 的含义是：「我（前驱节点）释放锁的时候，记得唤醒后继节点」。  
> 这样前驱释放时，看到 waitStatus = -1，就知道需要 `LockSupport.unpark(后继线程)`。

---

### 源码关键路径：release（独占释放）

```java
public final boolean release(int arg) {
    if (tryRelease(arg)) {        // ① 尝试释放（子类实现）
        Node h = head;
        if (h != null && h.waitStatus != 0)
            unparkSuccessor(h);   // ② 唤醒后继节点
        return true;
    }
    return false;
}
```

**`unparkSuccessor` 的关键细节**：

```java
private void unparkSuccessor(Node node) {
    int ws = node.waitStatus;
    if (ws < 0)
        compareAndSetWaitStatus(node, ws, 0);  // 清零

    Node s = node.next;
    if (s == null || s.waitStatus > 0) {  // >0 = CANCELLED
        s = null;
        // 从 tail 向前找，找到最靠前的非CANCELLED节点
        for (Node t = tail; t != null && t != node; t = t.prev)
            if (t.waitStatus <= 0)
                s = t;
    }
    if (s != null)
        LockSupport.unpark(s.thread);
}
```

**为什么从 tail 向前找，而不是用 `node.next`？**

> 入队时，`addWaiter` 是先 `CAS tail`，再设置 `prev/next` 指针的。  
> 在并发场景下，`node.next` 可能还没被设置（指向 null），但 `prev` 指针一定已经设置好了（因为 `prev` 在 CAS 之前就设了）。  
> 所以从 tail 往前找是**安全的**，用 `next` 可能漏掉节点。

---

### Condition：AQS 的「条件变量」

`synchronized` 只有一把「隐式条件」，AQS 的 `ConditionObject` 支持**多个条件变量**：

```java
ReentrantLock lock = new ReentrantLock();
Condition notEmpty = lock.newCondition();  // 条件1：队列非空
Condition notFull = lock.newCondition();   // 条件2：队列未满

// 线程 A
lock.lock();
while (queue.isEmpty())
    notEmpty.await();   // 释放锁，进入 Condition 队列
// ... 消费 ...
notFull.signal();
lock.unlock();

// 线程 B
lock.lock();
while (queue.isFull())
    notFull.await();
// ... 生产 ...
notEmpty.signal();
lock.unlock();
```

**Condition 队列 vs AQS 队列**：

```
线程调用 await() 时：
  AQS队列（获取锁的队列）        Condition队列（等待条件的队列）
  ┌─────┐                        ┌─────┐
  │head │                        │first│
  ├─────┤                        ├─────┤
  │node1│                        │node2│  ← 调用await的线程
  └─────┘                        └─────┘
     ↑                                │
     │   signal()时被转移到AQS队列    │
     └────────────────────────────────┘
```

**`await()` 的底层流程**：
1. 把当前线程包装成 Node，加入 Condition 队列
2. 释放 `state`（= 完全释放锁，因为可重入）
3. `LockSupport.park()` 挂起
4. 被 `signal()` 唤醒后，重新 `acquire`（重新竞争锁）
5. 获取成功后，从 Condition 队列移除

---

## 它和相似方案的本质区别是什么？

### AQS（ReentrantLock）vs synchronized

| 维度 | synchronized | ReentrantLock（AQS） |
|------|--------------|----------------------|
| **实现层** | JVM 内置（C++） | Java 代码（AQS） |
| **中断响应** | ❌ 不支持 `lockInterruptibly` | ✅ 支持 |
| **超时获取** | ❌ | ✅ `tryLock(timeout)` |
| **公平锁** | ❌ 只支持非公平 | ✅ 构造参数 `fair=true` |
| **条件变量** | ❌ 只有 `wait/notify`（1个） | ✅ 多个 `Condition` |
| **尝试获取** | ❌ | ✅ `tryLock()` |
| **性能（JDK 6+）** | 锁升级优化，低竞争相当 | 高竞争时更优（自旋+CAS） |

**为什么 synchronized 不支持中断？**

> `synchronized` 是 JVM 内置的，它的阻塞是操作系统级别的（互斥量）。  
> Java 代码无法「打断」一个正在等 `monitorenter` 的线程。  
> 而 AQS 是用 `LockSupport.park()` 挂起的，`park` 响应 `interrupt()`。

---

### 独占模式 vs 共享模式

```java
// 独占：同一时刻只有一个线程能获取
ReentrantLock lock = new ReentrantLock();
lock.lock();   // acquire(1)

// 共享：多个线程可以同时获取
Semaphore sem = new Semaphore(10);
sem.acquire();  // acquireShared(1) — 只要 state ≥ 1 就能获取
```

**共享模式的 `doAcquireShared` 有个关键优化**：

> 当一个线程获取共享锁成功，且还有剩余许可时，  
> 它会**主动唤醒后继的共享节点**（传播式唤醒），  
> 而不需要等释放时才唤醒。

这个优化叫 **「共享传播」**（propagate），防止「信号丢失」。

---

## 正确使用方式

### ReentrantLock 的标准写法

```java
ReentrantLock lock = new ReentrantLock();

public void safeMethod() {
    lock.lock();            // 或 lockInterruptibly()
    try {
        // ... 业务逻辑 ...
    } finally {
        lock.unlock();     // 必须在 finally 中释放！
    }
}
```

**为什么 `unlock()` 必须在 `finally` 里？**

> 如果业务逻辑抛异常，没执行 `unlock()`，这把锁就**永远不释放**（其他线程全部死等）。  
> `finally` 保证无论是否抛异常，都会执行释放。

---

### CountDownLatch 的正确使用

```java
CountDownLatch latch = new CountDownLatch(3);  // 计数=3

// 线程1、2、3 完成任务后
latch.countDown();

// 主线程等待
latch.await();   // state 变成 0 才返回
```

**`await()` 的底层**：调用 `acquireShared(1)`，发现 `state > 0` → 入队挂起。  
**`countDown()` 的底层**：调用 `releaseShared(1)`，`state--`，变成 0 时唤醒队列。

---

## 边界情况和坑

### 1. 忘记在 finally 中 unlock

```java
// ❌ 错误：业务逻辑抛异常，锁永远不释放
lock.lock();
doSomething();   // 可能抛异常
lock.unlock();

// ✅ 正确
lock.lock();
try {
    doSomething();
} finally {
    lock.unlock();
}
```

---

### 2. Condition 的 await 要用 while 循环

```java
// ❌ 错误：被虚假唤醒后，条件仍不满足
if (!condition)
    condition.await();

// ✅ 正确：while 循环检查
while (!condition)
    condition.await();
```

> **虚假唤醒**（spurious wakeup）：操作系统层面的 `wait` 可能在没有 `signal` 的情况下返回。  
> 虽然 `Condition.await()` 在 Java 层面已经处理了这个问题，但**规范上仍然要求用 while 循环**。

---

### 3. 公平锁的性能陷阱

```java
// 公平锁：严格按照入队顺序获取锁
ReentrantLock fairLock = new ReentrantLock(true);

// 非公平锁：新来的线程可以先抢锁（默认）
ReentrantLock unfairLock = new ReentrantLock(false);
```

**为什么非公平锁性能更好？**

> 假设线程 A 释放锁，此时线程 B 正好在 `lock()`（还没入队）。  
> 非公平锁允许 B **直接抢到锁**（不需要入队 → 出队的开销）。  
> 公平锁强制 B 必须先入队，轮到它才能获取，上下文切换更多。

**但非公平锁可能导致饥饿**（某线程一直抢不到）。

---

### 4. tryAcquire / tryRelease 必须保证线程安全

```java
// ❌ 错误：state 的读写没有保证原子性
protected boolean tryAcquire(int arg) {
    if (state == 0) {        // 线程A和B同时判断成功
        state = 1;           // 两个线程都进来了
        return true;
    }
    return false;
}

// ✅ 正确：用 CAS 或volatile+同步块
protected boolean tryAcquire(int arg) {
    if (compareAndSetState(0, 1)) {
        setExclusiveOwnerThread(Thread.currentThread());
        return true;
    }
    return false;
}
```

AQS 提供的 `compareAndSetState()` 是原子操作（底层 `Unsafe.compareAndSwapInt`）。

---

## 我的理解

AQS 的设计精髓在于**「把排队和唤醒做通用，把获取逻辑留给子类」**。

- `state` 是核心状态，含义由子类定义（这是模板方法模式的体现）
- CLH 队列保证了 FIFO 公平性（虽然非公平锁允许插队，但入队后还是 FIFO）
- `LockSupport.park/unpark` 是底层原语，比 `wait/notify` 更灵活（不需要持有锁）

**面试时容易被追问到源码层**，核心就这几点：
1. `acquireQueued` 的自旋优化（只有前驱是 head 才尝试获取）
2. `unparkSuccessor` 为什么从 tail 往前找
3. Condition 的 await/signal 底层是两个队列的转移
4. 共享模式的「传播式唤醒」

---
