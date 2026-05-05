# Lock 详解

> ReentrantLock 和 ReadWriteLock 是 JUC（java.util.concurrent.locks）的核心实现，底层基于 AQS。相比 synchronized，它们提供了可中断、可超时、公平锁、多条件变量等高级特性。

---

## 这个问题为什么存在？

synchronized 能做的：互斥访问、可重入、自动释放锁。

synchronized 做不到的：

- 响应中断——线程在等锁时不能被中断
- 超时获取——不能指定"最多等 5 秒，拿不到就算了"
- 公平/非公平切换——只能非公平
- 尝试获取——不能"试一下拿不到就返回 false"
- 读写分离——读读互斥（浪费性能）
- 多条件变量——一个锁只能一个 wait/notify

ReentrantLock 及配套锁就是为填补这些空白而生。

---

## 它是怎么解决问题的？

### Lock 接口

```java
public interface Lock {
    void lock();                           // 阻塞获取锁
    void lockInterruptibly()               // 可中断地获取锁
        throws InterruptedException;
    boolean tryLock();                     // 非阻塞尝试获取锁
    boolean tryLock(long time, TimeUnit unit) // 超时获取锁
        throws InterruptedException;
    void unlock();                         // 释放锁
    Condition newCondition();              // 创建条件变量
}
```

### ReentrantLock 基本用法

```java
ReentrantLock lock = new ReentrantLock();

lock.lock();
try {
    // 临界区
    criticalSection();
} finally {
    lock.unlock();  // 必须在 finally 中释放！
}
```

> 为什么必须在 finally 中 unlock？
> 如果在临界区内抛异常，不执行 unlock() → 锁永远不释放 → 其他线程永远阻塞。
> 这是和 synchronized 的一个关键区别——synchronized 会自动释放锁，ReentrantLock 必须手动释放。

### 可中断获取锁

```java
ReentrantLock lock = new ReentrantLock();

lock.lockInterruptibly();  // 等待锁的过程中可以被 interrupt
// 如果被中断 → 抛 InterruptedException

// 对比 synchronized：
synchronized (obj) {
    // 线程在等锁时，interrupt() 不会让它停止等待
    // 只是等拿到锁后 interrupt 标志还是 true
}
```

**这是 ReentrantLock 相比 synchronized 最实用的优势之一**——避免线程在等锁时无法响应取消。

### 超时获取锁

```java
ReentrantLock lock = new ReentrantLock();

if (lock.tryLock(5, TimeUnit.SECONDS)) {
    try {
        // 拿到锁了，执行操作
    } finally {
        lock.unlock();
    }
} else {
    // 5 秒内没拿到锁，执行降级逻辑
    fallbackStrategy();
}
```

**应用场景**：避免死锁——给锁获取设置超时，超时后可以释放已持有的其他锁。

### 公平锁 vs 非公平锁

```java
// 公平锁：按等待时间排队，先来后到
ReentrantLock fairLock = new ReentrantLock(true);

// 非公平锁（默认）：新来的线程可以直接插队尝试获取锁
ReentrantLock unfairLock = new ReentrantLock(false);
```

```
公平锁 vs 非公平锁：

非公平锁（默认）：
- 新线程来了直接尝试 CAS 抢锁
- 抢不到再去队列排队
- 优势：吞吐量高（减少线程切换）
- 劣势：可能饿死等待久的线程

公平锁：
- 新线程来了直接去队尾排队
- 优势：不会饿死（严格先来后到）
- 劣势：吞吐量低（每次都要入队出队）

为什么默认非公平？
实际测试中，非公平锁的吞吐量比公平锁高 5~10 倍。
```

### Condition 条件变量

synchronized 只有一个等待队列（wait/notify），ReentrantLock 可以创建多个 Condition：

```java
ReentrantLock lock = new ReentrantLock();
Condition notEmpty = lock.newCondition();  // 非空条件
Condition notFull = lock.newCondition();   // 非满条件

// 生产者
lock.lock();
try {
    while (count == buffer.length) {
        notFull.await();  // 满了就等待
    }
    buffer[putIndex] = item;
    notEmpty.signal();    // 通知消费者
} finally {
    lock.unlock();
}

// 消费者
lock.lock();
try {
    while (count == 0) {
        notEmpty.await(); // 空了就等待
    }
    T item = buffer[takeIndex];
    notFull.signal();     // 通知生产者
} finally {
    lock.unlock();
}
```

```
Condition vs Object.wait/notify：

| 维度 | wait/notify | Condition |
|------|-------------|-----------|
| 数量 | 每个 synchronized 一个 | 一个 Lock 可以多个 |
| 等待/唤醒 | wait() / notify() | await() / signal() |
| 中断响应 | 不响应 | 支持中断 |
| 超时等待 | wait(timeout) | await(timeout, unit) |
| 精确唤醒 | notifyAll() 全部唤醒 | signal() 精确唤醒指定条件 |
```

### ReentrantReadWriteLock 读写锁

```java
ReentrantReadWriteLock rwLock = new ReentrantReadWriteLock();

// 读锁（共享锁）——多个线程可以同时持有
rwLock.readLock().lock();
try {
    // 读操作
} finally {
    rwLock.readLock().unlock();
}

// 写锁（排他锁）——只有一个线程可以持有
rwLock.writeLock().lock();
try {
    // 写操作
} finally {
    rwLock.writeLock().unlock();
}
```

```
读写锁的规则：
1. 读-读：不互斥（共享）→ 适合读多写少场景
2. 读-写：互斥
3. 写-读：互斥
4. 写-写：互斥

锁降级：持有写锁 → 获取读锁 → 释放写锁 ✓（允许）
锁升级：持有读锁 → 获取写锁 ✗（会死锁！）

为什么不支持锁升级？
线程 A 持有读锁，想升级为写锁
线程 B 也持有读锁，也想升级为写锁
双方互相等待对方释放读锁 → 死锁
```

### StampedLock（Java 8+）

读写锁的优化版，支持乐观读：

```java
StampedLock sl = new StampedLock();

// 乐观读：不加读锁，只验证写锁是否被获取过
long stamp = sl.tryOptimisticRead();
int value = readData();  // 不加锁，直接读
if (!sl.validate(stamp)) {  // 验证期间有没有写操作
    stamp = sl.readLock();  // 验证失败，降级为悲观读锁
    value = readData();
    sl.unlockRead(stamp);
}

// 锁转换
long stamp = sl.readLock();
try {
    // 读的过程中发现需要写
    long ws = sl.tryConvertToWriteLock(stamp);
    if (ws != 0) {
        stamp = ws;  // 成功转换为写锁
    } else {
        sl.unlockRead(stamp);
        stamp = sl.writeLock();  // 失败，重新获取写锁
    }
    // 写操作...
} finally {
    sl.unlock(stamp);
}
```

```
StampedLock vs ReentrantReadWriteLock：

| 维度 | ReentrantReadWriteLock | StampedLock |
|------|----------------------|-------------|
| 读锁模式 | 悲观读（加锁） | 悲观读 + 乐观读 |
| 锁重入 | ✓ | ✗ |
| Condition | ✓ | ✗ |
| 读写锁转换 | 支持降级 | 支持所有转换 |
| 性能 | 中等 | 高（乐观读无锁） |
| API 复杂度 | 低 | 高 |
```
