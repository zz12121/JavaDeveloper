# synchronized 详解

> synchronized 是 JVM 内置的互斥机制，通过对象头 Mark Word 记录锁状态，根据竞争程度自动升级（偏向→轻量→重量），在低竞争场景下性能已接近 ReentrantLock。

---

## 这个问题为什么存在？

多个线程同时读写共享变量会产生竞态条件，最终结果与执行时序有关，不可预测。需要一个机制保证「同一时刻只有一个线程能执行某段代码」。

没有 synchronized 之前，只能用 `volatile + CAS` 手写锁，容易出错。synchronized 提供了**语言级别的互斥语义**，让这件事变得简单。

但早期 synchronized 是「重量级锁」——加锁/解锁都要从用户态切换到内核态（操作系统 mutex），成本高。JDK 6 之后引入了**锁升级机制**，让 synchronized 在「无竞争」「低竞争」场景下也能高效运行。

---

## 它是怎么解决问题的？

### 锁对象与对象头 Mark Word

synchronized 的锁信息存在 **Java 对象头（Mark Word）** 里：

```
| 锁状态   | 56 bits                          | 1 bit | 4 bits | 2 bits |
|---------|----------------------------------|--------|--------|--------|
| 无锁     | 未覆盖的 hashCode                  | 0      | 分代年龄  | 001    |
| 偏向锁   | Thread ID | Epoch | 1      | 分代年龄  | 101    |
| 轻量级锁 | 指向栈中锁记录的指针                         | 00     |
| 重量级锁 | 指向管程（monitor）的指针                        | 10     |
| GC标记   | 空                               | 11     |
```

### 锁升级全过程

```
无锁（001）
  ↓ 第一个线程进入（无竞争）
偏向锁（101）   ← 只把 Thread ID 写入 Mark Word，无 CAS
  ↓ 第二个线程尝试获取同一把锁
轻量级锁（00）  ← 在线程栈创建 Lock Record，用 CAS 抢锁
  ↓ 竞争激烈（自旋超过阈值 / 线程数超 CPU 核数）
重量级锁（10）  ← 操作系统 mutex，线程阻塞（内核态）
```

#### 偏向锁（Biased Locking）

**目标**：消除无竞争场景下的同步开销。

**原理**：第一个获取锁的线程，把 Thread ID 写入 Mark Word。后续该线程再进入同步块，只检查 Thread ID 是不是自己（无 CAS，无系统调用），开销 ≈ 0。

**偏向锁撤销（Revocation）**：

```
场景：线程 A 持有偏向锁，线程 B 来抢锁
→ JVM 需要升级为轻量级锁
→ 升级前必须撤销偏向锁：
  1. 找到全局安全点（Safepoint，所有线程暂停）
  2. 检查持有锁的线程 A 是否还活着
     - A 已死亡 → 直接撤销，对象头恢复无锁状态
     - A 还活着 → 遍历 A 的栈，找到所有锁记录，修改为轻量级锁格式
  3. 升级为轻量级锁，B 用 CAS 抢锁
```

> ⚠️ **偏向锁撤销需要 STW（Stop-The-World）**，这是它最大的性能隐患。

**Epoch 机制（批量重偏向）**：

```
问题：某个类的对象频繁发生偏向锁撤销（如两个线程交替访问同一批对象）
      → 每次撤销都要 STW，性能差。

Epoch 解决思路：
  - 每个类有一个 epoch 值（存在 Class 对象里）
  - 每个对象的 Mark Word 里也存一份 epoch 的拷贝
  - 当某个类的偏向锁撤销次数超过阈值（默认 20）：
      → 该类的 epoch + 1
      → 所有已经偏向旧 epoch 的锁，被视为「无锁」（直接重偏向，不用 STW）
  - 阈值2（默认 40）：直接禁用该类的偏向锁（升级为轻量级锁）
```

#### 轻量级锁（Lightweight Locking）

**目标**：在低竞争场景下，避免直接进内核（重量级锁）。

**加锁过程**（在线程栈里操作）：

```
线程执行 monitorenter：
1. 在线程栈帧里创建一个「锁记录（Lock Record）」
2. 把对象头 Mark Word 复制到锁记录里（Displaced Mark Word）
3. 用 CAS 把对象头的 Mark Word 替换为「指向锁记录的指针」
   - CAS 成功 → 加锁成功（轻量级锁状态）
   - CAS 失败 → 说明有竞争，走锁升级逻辑
```

**解锁过程**：

```
1. 用 CAS 把 Displaced Mark Word 写回对象头
2. CAS 成功 → 解锁成功
3. CAS 失败 → 说明锁已经膨胀为重量级锁，用重量级锁的方式解锁
```

**自旋优化（Spin Loop）**：

```
场景：轻量级锁 CAS 失败（说明有竞争），但持有锁的线程可能很快释放
→ JVM 让当前线程「自旋」（while 循环不断重试 CAS），不立即阻塞
→ 自旋超过阈值（默认 10 次，JDK 6 之后自适应）→ 升级为重量级锁
```

#### 重量级锁（Heavyweight Locking）

**目标**：处理高竞争场景，让拿不到锁的线程阻塞（不占用 CPU）。

**实现**：依赖操作系统的 `pthread_mutex`（互斥量），涉及**用户态 → 内核态**切换。

```
monitorenter（重量级锁路径）：
1. 通过对象头找到 ObjectMonitor（C++ 对象）
2. 调用 pthread_mutex_lock() → 操作系统互斥量
3. 如果锁被占用 → 线程加入 _EntryList（等待队列），阻塞（park）
4. 锁释放时 → 操作系统唤醒等待队列中的下一个线程（unpark）
```

**ObjectMonitor 关键字段**（hotspot 源码 `objectMonitor.hpp`）：

```
class ObjectMonitor {
    volatile intptr_t  _header;       // 原始 Mark Word
    volatile void*     _owner;        // 当前持有锁的线程
    volatile jint      _recursions;   // 重入次数
    ObjectWaiter*      _EntryList;    // 等待获取锁的线程队列
    ObjectWaiter*      _WaitSet;      // 调用了 wait() 的线程集合
}
```

> **升级方向只能升，不能降**：偏向锁 → 轻量级锁 → 重量级锁。
> JDK 15 之后，偏向锁默认禁用（`-XX:-UseBiasedLocking`），原因是现代 CPU 上偏向锁的 STW 开销比轻量级锁的 CAS 还大。

---

## 深入原理

### synchronized vs ReentrantLock

| 维度 | synchronized | ReentrantLock |
|------|---------------|----------------|
| 用法 | 关键字，自动释放 | 手动 `lock()` / `unlock()`（必须 finally） |
| 公平性 | 只支持非公平 | 可选公平/非公平（构造器传 `true`） |
| 等待可中断 | ✗ | ✓（`lockInterruptibly()`） |
| 尝试获取锁 | ✗ | ✓（`tryLock()` / `tryLock(timeout)`） |
| 条件变量 | 只有 1 个（wait/notify） | 多个（Condition） |
| 性能 | JDK 6+ 已高度优化 | 高竞争时略优 |
| 锁升级 | ✓（偏向→轻量→重量） | ✗（直接是 AQS 实现） |

**设计哲学差异**：

```

synchronized：JVM 全权负责（你不能干预锁的过程）
  - 优点：简单，不会忘记释放
  - 缺点：功能有限（不能中断、不能尝试获取、只能非公平）

ReentrantLock：把锁的控制权交给程序员
  - 优点：功能强（可中断、可超时、可公平、可多条件）
  - 缺点：必须手动释放（忘了就死锁）
```

### 源码层面：monitorenter / monitorexit

synchronized 编译成字节码后：

```java
synchronized(obj) {
    // 临界区
}

// 字节码：
  monitorenter   // 进入同步块
  ...            // 临界区字节码
  monitorexit    // 正常退出
  ...            // 异常处理 → 也有一个 monitorexit（保证异常时也能释放）
```

HotSpot 源码执行路径（`interpreterRuntime.cpp`）：

```
InterpreterRuntime::monitorenter(JavaThread* thread, BasicObjectLock* lock) {
    Handle obj = lock->obj();
    // 1. 快速路径（fast path）：偏向锁 / 轻量级锁
    if (UseBiasedLocking && obj->mark()->has_bias_pattern()) {
        // 偏向锁逻辑
    }
    // 2. 快速路径失败 → 慢速路径（slow path）：膨胀为重量级锁
    ObjectSynchronizer::slow_enter(...)
}
```

---

## 正确使用方式

### 1. 同步粒度尽可能小

```java
// 坏：整个方法同步
public synchronized void process(List<String> data) {
    List<Record> records = queryFromDB();  // 不涉及共享资源，不需要锁
    for (Record r : records) {
        sharedMap.put(r.key(), r.value());
    }
    logger.info("done");  // 不需要锁
}

// 好：只同步真正需要保护的临界区
public void process(List<String> data) {
    List<Record> records = queryFromDB();
    synchronized (this) {
        for (Record r : records) {
            sharedMap.put(r.key(), r.value());
        }
    }
    logger.info("done");
}
```

### 2. 用私有锁对象

```java
class UserService {
    // 好：私有锁，外部无法绕过
    private final Object lock = new Object();

    public void updateUser(int id) {
        synchronized (lock) { ... }
    }
}

// 坏：在 public 的 this 上同步，外部代码可以故意用同一把锁制造死锁
public synchronized void method() { ... }  // 等价于 synchronized (this)
```

### 3. 理解 synchronized 是可重入的

```java
public synchronized void a() {
    b();  // ✓ 可重入：同一线程可以多次获取同一把锁
}

public synchronized void b() {
    // 不会死锁：JVM 记录重入次数，unlock 次数 == 重入次数时才真正释放
}
```

---

## 边界情况和坑

### 1. 锁对象被修改（最经典的坑）

```java
class Service {
    private String lockKey = "abc";

    public void method() {
        synchronized (lockKey) {   // ⚠️ 危险！
            lockKey = "def";      // 锁对象变了！下一个线程用 "def" 做锁，不同步！
        }
    }
}
```

**解释**：synchronized 锁定的是**对象（内存地址）**，不是「引用变量名」。`lockKey = "def"` 让引用指向了另一个对象，后续线程拿的是不同的锁，互斥失效。

**修复**：用 `private final Object lock = new Object()`，保证锁对象引用不变。

### 2. wait() / notify() 必须在 synchronized 块内调用

```java
Object lock = new Object();

lock.wait();  // ❌ IllegalMonitorStateException

// ✓ 必须在 synchronized 块内
synchronized (lock) {
    lock.wait();  // 释放 lock，线程进入 _WaitSet
}
```

**原因**：wait() 释放锁 + 挂起线程，这两个操作必须是原子的，否则会有竞态条件。synchronized 保证了这个原子性。

### 3. JDK 15+ 偏向锁默认关闭

```
JDK 15 之前：-XX:+UseBiasedLocking（默认开启）
JDK 15 及之后：-XX:-UseBiasedLocking（默认关闭）
```

影响：如果应用跑在 JDK 17（LTS），synchronized 直接从轻量级锁开始，偏向锁阶段被跳过。

### 4. 锁粒度太大导致死锁

```java
// 线程 A
synchronized (lock1) {
    Thread.sleep(100);
    synchronized (lock2) { ... }
}

// 线程 B
synchronized (lock2) {
    Thread.sleep(100);
    synchronized (lock1) { ... }
}
// 死锁：A 持有 lock1 等 lock2，B 持有 lock2 等 lock1
```

**修复**：所有线程按**固定顺序**获取锁（破坏「循环等待」条件）。
