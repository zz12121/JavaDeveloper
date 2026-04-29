# ReentrantLock 与显式锁

> synchronized 是 Java 内置的锁机制，简单好用。但当需要可中断、可超时、可公平、可读写分离时，synchronized 力不从心。ReentrantLock 和 java.util.concurrent.locks 包就是为此而生——提供更灵活、更强大的显式锁控制。

---

## 这个问题为什么存在？

### synchronized 的局限

```
synchronized 能做的：
✓ 互斥访问
✓ 可重入
✓ 自动释放锁

synchronized 做不到的：
✗ 响应中断——线程在等锁时不能被中断
✗ 超时获取——不能指定"最多等 5 秒，拿不到就算了"
✗ 公平/非公平切换——只能非公平
✗ 尝试获取——不能"试一下拿不到就返回 false"
✗ 读写分离——读读互斥（浪费性能）
✗ 多条件变量——一个锁只能一个 wait/notify
```

**ReentrantLock 诞生就是为了填补这些空白。** 它是 synchronized 的增强版，底层基于 AQS（AbstractQueuedSynchronizer）实现。

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

```
为什么必须在 finally 中 unlock？
如果在临界区内抛异常，不释放锁 → 其他线程永远拿不到锁 → 死锁。
这是和 synchronized 的一个区别——synchronized 会自动释放锁，
ReentrantLock 必须手动释放。
```

### 可中断获取锁

```java
ReentrantLock lock = new ReentrantLock();

// 线程A
lock.lockInterruptibly();  // 等待锁的过程中可以被 interrupt
// 如果被中断 → 抛 InterruptedException

// 对比 synchronized
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
// new ReentrantLock() 默认非公平
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
公平锁的"严格排队"增加了上下文切换的开销。
而且大多数场景下不需要公平——偶尔插队对业务影响很小。

什么时候用公平锁？
线程持有锁的时间很长，竞争激烈，且有严格的公平性要求。
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

Condition 的本质优势：精准控制线程的等待和唤醒。
ArrayBlockingQueue 底层就用两个 Condition 实现生产者-消费者模式。
```

### ReentrantLock 的可重入性

```java
ReentrantLock lock = new ReentrantLock();

lock.lock();
lock.lock();  // 同一线程第二次获取 → 成功，计数器 +1
// holdCount = 2

lock.unlock();  // holdCount = 1
lock.unlock();  // holdCount = 0，真正释放锁
```

```
可重入（Reentrant）的含义：
同一线程可以多次获取同一把锁，不会死锁。
每次 lock() 计数器 +1，每次 unlock() 计数器 -1。
计数器归零时锁才真正释放。

获取重入次数：
lock.getHoldCount()      // 当前线程的重入次数
lock.isHeldByCurrentThread()  // 当前线程是否持有锁
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

// 写锁（排他锁）——只有一个线程可以持有，且读锁和写锁互斥
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
线程A 持有读锁，想升级为写锁
线程B 也持有读锁，也想升级为写锁
双方互相等待对方释放读锁 → 死锁

正确做法：先释放读锁，再获取写锁。
```

```
StampedLock（Java 8+）——读写锁的优化版：

1. 支持乐观读：不加读锁，只验证写锁是否被获取过
   long stamp = sl.tryOptimisticRead();
   int value = readData();  // 不加锁，直接读
   if (!sl.validate(stamp)) {  // 验证期间有没有写操作
       stamp = sl.readLock();  // 验证失败，降级为悲观读锁
       value = readData();
       sl.unlockRead(stamp);
   }

2. 支持锁转换：乐观读 → 写锁（tryConvertToWriteLock）
3. 不支持重入
4. 性能比 ReentrantReadWriteLock 好很多（读操作几乎无开销）

适用场景：读远多于写，且读的数据量不大
不适用场景：需要重入、需要 Condition
```

### 锁的选择指南

```
1. synchronized 优先——简单、不容易出错
   - 大多数场景够用
   - Java 6 之后偏向锁/轻量级锁优化，性能差距很小

2. 需要 ReentrantLock 的场景：
   - 可中断获取锁（lockInterruptibly）
   - 超时获取锁（tryLock with timeout）
   - 公平锁
   - 多条件变量（Condition）
   - 需要尝试获取（tryLock）

3. 需要 ReentrantReadWriteLock 的场景：
   - 读多写少（缓存、配置读取）
   - 读操作远多于写操作

4. 需要 StampedLock 的场景：
   - 读远多于写，且需要极致性能
   - 不需要重入和 Condition
```

---

## 和相似方案的区别

### ReentrantLock vs synchronized

| 维度 | synchronized | ReentrantLock |
|------|-------------|---------------|
| 锁释放 | 自动（JVM 保证） | 手动（finally 中 unlock） |
| 可中断 | 不支持 | lockInterruptibly() |
| 超时 | 不支持 | tryLock(timeout) |
| 公平性 | 非公平 | 可选公平/非公平 |
| 条件变量 | 单个（wait/notify） | 多个（Condition） |
| 尝试获取 | 不支持 | tryLock() |
| 实现层面 | JVM 内置（monitor） | Java API（基于 AQS） |
| 性能 | Java 6+ 偏向锁优化后接近 | 略优（高竞争下） |
| 推荐度 | 优先使用 | 需要高级特性时使用 |

### ReentrantReadWriteLock vs StampedLock

| 维度 | ReentrantReadWriteLock | StampedLock |
|------|----------------------|-------------|
| 读锁模式 | 悲观读（加锁） | 悲观读 + 乐观读 |
| 锁重入 | ✓ | ✗ |
| Condition | ✓ | ✗ |
| 读写锁转换 | 支持降级 | 支持所有转换 |
| 性能 | 中等 | 高（乐观读无锁） |
| API 复杂度 | 低 | 高 |
| 数据竞争检测 | 无 | validate(stamp) |

---

## 正确使用方式

### 1. 永远在 finally 中释放锁

```java
ReentrantLock lock = new ReentrantLock();
lock.lock();
try {
    criticalSection();
} finally {
    lock.unlock();  // 必须！即使抛异常也要释放
}
```

### 2. 不要在 lock() 之前做可能失败的准备

```java
// ✗ 如果 initResource() 抛异常，锁永远不释放
lock.lock();
initResource();  // 可能在 lock 后、try 前抛异常
try {
    criticalSection();
} finally {
    lock.unlock();
}

// ✓ 正确写法
lock.lock();
try {
    initResource();  // 在 try 内
    criticalSection();
} finally {
    lock.unlock();
}
```

### 3. 用 tryLock 避免死锁

```java
ReentrantLock lock1 = new ReentrantLock();
ReentrantLock lock2 = new ReentrantLock();

// 按固定顺序获取锁（避免死锁的最佳实践）
// 但如果必须按不确定顺序获取：
while (true) {
    if (lock1.tryLock()) {
        try {
            if (lock2.tryLock()) {
                try {
                    doWork();
                    break;  // 成功获取两把锁
                } finally {
                    lock2.unlock();
                }
            }
        } finally {
            lock1.unlock();
        }
    }
    Thread.sleep(100);  // 短暂等待后重试
}
```

### 4. 读写锁的标准模板

```java
class ThreadSafeCache<K, V> {
    private final Map<K, V> cache = new HashMap<>();
    private final ReentrantReadWriteLock rwLock = new ReentrantReadWriteLock();

    V get(K key) {
        rwLock.readLock().lock();
        try {
            return cache.get(key);
        } finally {
            rwLock.readLock().unlock();
        }
    }

    void put(K key, V value) {
        rwLock.writeLock().lock();
        try {
            cache.put(key, value);
        } finally {
            rwLock.writeLock().unlock();
        }
    }

    // 锁降级：写锁 → 读锁
    V computeIfAbsent(K key, Function<K, V> loader) {
        rwLock.readLock().lock();
        try {
            V value = cache.get(key);
            if (value == null) {
                // 释放读锁，获取写锁
                rwLock.readLock().unlock();
                rwLock.writeLock().lock();
                try {
                    // 双重检查
                    value = cache.get(key);
                    if (value == null) {
                        value = loader.apply(key);
                        cache.put(key, value);
                    }
                    // 锁降级：获取读锁后再释放写锁
                    rwLock.readLock().lock();
                } finally {
                    rwLock.writeLock().unlock();
                }
            }
            return value;
        } finally {
            rwLock.readLock().unlock();
        }
    }
}
```

---

## 边界情况和坑

### 1. unlock 没有持有锁时抛 IllegalMonitorStateException

```java
ReentrantLock lock = new ReentrantLock();
lock.unlock();  // IllegalMonitorStateException！
// 当前线程没有持有锁就 unlock → 运行时异常
```

### 2. 忘记 unlock 导致死锁

```
最常见的 ReentrantLock 错误：
lock.lock();
doSomething();  // 抛异常
// 没有 finally { lock.unlock(); }
// → 锁永远不释放 → 其他线程永远阻塞

synchronized 不会有这个问题——方法异常退出时 JVM 自动释放 monitor。
```

### 3. 读写锁的写饥饿

```
ReentrantReadWriteLock 默认非公平模式可能导致写饥饿：

大量读线程持续持有读锁 → 写线程永远获取不到写锁
因为读锁是共享的，新的读线程可以不断加入

解决方案：
1. 用公平模式（构造时 new ReentrantReadWriteLock(true)）
2. 降低读操作的持有时间
3. 考虑用 StampedLock 的乐观读
```

### 4. tryLock 的误导

```java
// tryLock() 非公平模式下会"插队"
// 即使队列中有其他线程在等待，新来的线程也可能成功获取锁
// 这可能导致等待已久的线程继续等待（不公平）

// 如果需要尊重等待队列：
// 不要用无参 tryLock()，用 tryLock(0, TimeUnit.SECONDS)
// 超时为 0 意味着"只在锁空闲时获取，不插队"
```

### 5. Condition 的 signal vs signalAll

```java
// signal()：只唤醒一个等待线程
// signalAll()：唤醒所有等待线程

// 用 signal() 还是 signalAll()？
// 如果只关心"有资源了"，唤醒一个就够 → signal()
// 如果多个线程在等不同条件 → signal() 精确唤醒
// 如果不确定 → signalAll() 更安全（但可能唤醒不必要的线程）

// 注意：和 notify() 一样，signal() 不会立即释放锁
// 被唤醒的线程在 await() 返回前需要重新获取锁
```

### 6. StampedLock 不支持重入

```java
StampedLock sl = new StampedLock();

sl.writeLock();  // 获取写锁
sl.writeLock();  // 死锁！同一线程再次获取 → 阻塞

// StampedLock 的设计取舍：为了性能放弃了重入
// 如果需要重入 → 用 ReentrantReadWriteLock
```

---

## 我的理解

ReentrantLock 是 Java 并发工具箱中最常用的锁。理解 ReentrantLock 的关键是理解它和 synchronized 的**取舍关系**：

**synchronized 的优势是简单**：JVM 自动管理锁的获取和释放，不容易出错。Java 6 之后经过偏向锁、轻量级锁、自旋锁等优化，性能和 ReentrantLock 非常接近。

**ReentrantLock 的优势是灵活**：可中断、可超时、公平/非公平、多条件变量——这些特性在复杂并发场景中是刚需。

**面试中 ReentrantLock 的高频考点**：

1. **ReentrantLock vs synchronized**（几乎必问，需要从多个维度对比）
2. **公平锁 vs 非公平锁**（默认非公平、为什么、各自的优缺点）
3. **ReentrantLock 底层原理**（基于 AQS、CLH 队列——和 AQS 章节联动）
4. **Condition vs wait/notify**（多条件变量、精确唤醒）
5. **读写锁**（读读共享、读写互斥、锁降级、写饥饿）
6. **StampedLock**（乐观读、锁转换、不支持重入）
7. **锁的正确使用**（finally unlock、tryLock 避免死锁）