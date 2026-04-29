# CAS 与原子类

> CAS（Compare-And-Swap）是 Java 并发包的底层基石——AtomicInteger、ReentrantLock、ConcurrentHashMap 的无锁读、甚至 LongAdder，底层都是 CAS。理解 CAS 是理解 java.util.concurrent 整个包的前提。

---

## 这个问题为什么存在？

### 锁的问题

synchronized 和 Lock 通过互斥来实现线程安全，但锁有几个固有缺点：

```
1. 阻塞开销：线程竞争锁失败后会被挂起（OS 级别的上下文切换），开销很大
2. 优先级反转：低优先级线程持有锁，高优先级线程被阻塞
3. 死锁风险：多把锁交叉获取时可能出现死锁
4. 无法实现无锁算法：有些场景（如计数器累加）用锁太重了
```

**CAS 提供了一种「乐观」的替代方案**：假设没有冲突，直接操作；操作完成后检查是否有冲突，有冲突就重试。

### CAS 的本质

```
CAS(V, Expected, New)
- V：要更新的内存地址（变量）
- Expected：期望的旧值
- New：要写入的新值

执行逻辑：
if (V == Expected) {
    V = New;    // 更新成功
    return true;
} else {
    return false;  // 更新失败，说明有其他线程修改了 V
}

整个过程是原子的——硬件层面（x86 的 cmpxchg 指令）保证。
```

CAS 是 CPU 提供的原子指令，不需要操作系统介入，也不需要加锁和解锁。**这是 CAS 的核心优势——无阻塞、无上下文切换。**

---

## 它是怎么解决问题的？

### Unsafe 类

Java 中 CAS 操作通过 `sun.misc.Unsafe` 类实现：

```java
// AtomicInteger 底层就是用 Unsafe
public class AtomicInteger {
    private static final Unsafe unsafe = Unsafe.getUnsafe();
    private volatile int value;  // volatile 保证可见性

    // CAS 原子更新
    public final boolean compareAndSet(int expect, int update) {
        return unsafe.compareAndSwapInt(this, valueOffset, expect, update);
    }

    // valueOffset：value 字段在对象内存中的偏移量
    private static final long valueOffset;
    static {
        valueOffset = unsafe.objectFieldOffset(AtomicInteger.class.getDeclaredField("value"));
    }
}
```

```
Unsafe 做了什么？
1. objectFieldOffset()：获取字段在对象中的内存偏移量
2. compareAndSwapInt()：调用 CPU 的 CAS 指令，原子地比较和交换

注意：Unsafe 是 JDK 内部 API，Java 9+ 推荐使用 VarHandle 替代。
但原理一样——都是通过内存偏移量直接操作内存。
```

### 原子类体系

```
java.util.concurrent.atomic
├── 基本类型
│   ├── AtomicInteger
│   ├── AtomicLong
│   └── AtomicBoolean
├── 数组类型
│   ├── AtomicIntegerArray
│   ├── AtomicLongArray
│   └── AtomicReferenceArray
├── 引用类型
│   ├── AtomicReference<T>
│   ├── AtomicStampedReference<T>   — 解决 ABA 问题
│   └── AtomicMarkableReference<T>
├── 字段更新器
│   ├── AtomicIntegerFieldUpdater
│   ├── AtomicLongFieldUpdater
│   └── AtomicReferenceFieldUpdater<T,V>
└── 累加器（Java 8+）
    ├── LongAdder
    ├── LongAccumulator
    ├── DoubleAdder
    └── DoubleAccumulator
```

### AtomicInteger 核心方法

```java
AtomicInteger count = new AtomicInteger(0);

// 原子自增
count.incrementAndGet();  // 返回新值：++count
count.getAndIncrement();  // 返回旧值：count++
count.addAndGet(5);       // 原子加 5

// CAS 更新
count.compareAndSet(10, 20);  // 如果当前值是 10，改为 20

// 普通读写（依赖 volatile 保证可见性）
int v = count.get();
count.set(42);

// 延迟更新（Lambda，Java 8+）
count.updateAndGet(x -> x * 2);        // 原子地应用函数
count.accumulateAndGet(5, (x, y) -> x + y);  // 原子地累加
```

### AtomicInteger.incrementAndGet() 底层

```java
// AtomicInteger 源码
public final int incrementAndGet() {
    return unsafe.getAndAddInt(this, valueOffset, 1) + 1;
}

// Unsafe.getAndAddInt
public final int getAndAddInt(Object o, long offset, int delta) {
    int v;
    do {
        v = getIntVolatile(o, offset);  // 读取当前值（volatile 读）
    } while (!compareAndSwapInt(o, offset, v, v + delta));
    // ↑ 自旋（spin）——CAS 失败就重试，直到成功
    return v;
}
```

**这就是 CAS 的经典模式：读取 → 计算 → CAS 更新 → 失败则重试。**

### LongAdder：CAS 的优化（Java 8+）

```
AtomicLong 的问题：
高并发下所有线程都在 CAS 竞争同一个 value → 大量 CAS 失败 → CPU 空转

LongAdder 的解决方案：分散竞争

AtomicLong：
所有线程 → CAS 竞争同一个 value

LongAdder：
所有线程 → CAS 各自的 Cell[]（分散到不同槽位）
           base（低竞争时直接更新 base）

             Cell[0]  Cell[1]  Cell[2]  ...  Cell[n]
              ↑        ↑        ↑             ↑
            线程A    线程B    线程C          线程N

sum() 时 = base + Cell[0] + Cell[1] + ... + Cell[n]
```

```java
LongAdder adder = new LongAdder();
adder.increment();       // 原子 +1
adder.add(5);            // 原子 +5
long total = adder.sum(); // 获取总和（不是强一致的快照）
```

```
LongAdder vs AtomicLong：
- 写多读少（高并发计数）→ LongAdder（分散竞争，性能好）
- 读多写少 / 需要强一致性 → AtomicLong（每个操作都立即全局可见）
- LongAdder.sum() 返回的不是精确的快照——求和过程中可能有更新
- AtomicLong.get() 返回的是精确的当前值

LongAccumulator：LongAdder 的泛化版本，支持自定义运算
new LongAccumulator((x, y) -> Math.max(x, y), Long.MIN_VALUE)
```

### AtomicReference

```java
AtomicReference<String> ref = new AtomicReference<>("initial");

ref.set("updated");
ref.compareAndSet("initial", "new");  // CAS 更新引用

// 延迟更新
ref.updateAndGet(old -> old + "!");
```

### AtomicStampedReference：解决 ABA 问题

**ABA 问题**：

```
线程A：读取值 A → 准备 CAS(A, C)
线程B：A → B → A（值又变回了 A）
线程A：CAS 比较，发现是 A，更新成功 → 但中间被改过！

大部分场景下 ABA 不是问题（值一样就行），
但如果"被改过"这个事实本身有影响，就需要 AtomicStampedReference。
```

```java
// 用版本号（stamp）检测 ABA
AtomicStampedReference<Integer> ref = new AtomicStampedReference<>(100, 0);

int stamp = ref.getStamp();       // 获取当前版本号
ref.compareAndSet(100, 101, stamp, stamp + 1);
//                           ↑期望的stamp  ↑新的stamp

// 即使值从 100→200→100，stamp 已经从 0→1→2
// compareAndSet(100, 101, 0, 1) 会失败——因为 stamp 已经不是 0 了
```

### AtomicFieldUpdater：原子更新已有类的字段

```java
// 不修改已有类的代码，让某个字段支持原子操作
public class User {
    volatile int score;  // 必须是 volatile
}

AtomicIntegerFieldUpdater<User> updater =
    AtomicIntegerFieldUpdater.newUpdater(User.class, "score");

User user = new User();
updater.incrementAndGet(user);  // 原子 +1
```

```
限制：
1. 字段必须是 volatile（保证可见性）
2. 字段不能是 private（对子类不可见时无法访问）
3. 不能操作 static 字段
4. 不如直接用 AtomicXxx 方便——主要用于已有类无法修改的情况
```

---

## 和相似方案的区别

### CAS vs synchronized

| 维度 | CAS | synchronized |
|------|-----|--------------|
| 机制 | 乐观（无锁，冲突重试） | 悲观（加锁，互斥访问） |
| 阻塞 | 不阻塞（自旋） | 阻塞（OS 线程挂起） |
| 上下文切换 | 无 | 有 |
| CPU 开销 | 高竞争时空转浪费 CPU | 低竞争时几乎无开销 |
| 适用场景 | 低~中竞争，轻量操作 | 高竞争，复杂临界区 |
| 死锁 | 不可能 | 可能 |
| 复合操作 | 不支持（单个变量 CAS） | 支持（任意代码块） |

```
选择原则：
- 简单的读-改-写操作（计数器、状态标志）→ CAS（原子类）
- 复杂的临界区（多个变量的协调）→ synchronized / Lock
- 极高并发计数 → LongAdder
```

### AtomicLong vs LongAdder vs LongAccumulator

| 维度 | AtomicLong | LongAdder | LongAccumulator |
|------|-----------|-----------|-----------------|
| 一致性 | 强一致（每次操作全局可见） | 最终一致（sum() 是近似值） | 最终一致 |
| 高并发性能 | 差（所有线程竞争一个 value） | 好（分散到 Cell 数组） | 好 |
| 运算 | 加减 | 加减 | 自定义二元运算 |
| 精确 get | ✓ | ✗（sum 是快照，不精确） | ✗ |
| 适用场景 | 读多写少，需要精确值 | 高并发计数 | 高并发自定义聚合 |

---

## 正确使用方式

### 1. 计数器场景

```java
// ✗ synchronized 计数器（重）
int count = 0;
synchronized (this) { count++; }

// ✓ AtomicLong 计数器
AtomicLong count = new AtomicLong(0);
count.incrementAndGet();

// ✓✓ LongAdder 计数器（高并发最优）
LongAdder count = new LongAdder();
count.increment();
long total = count.sum();  // 定期读取即可
```

### 2. 状态机场景

```java
AtomicInteger state = new AtomicInteger(0);  // 0=初始, 1=处理中, 2=完成

// CAS 尝试从 0 → 1
if (state.compareAndSet(0, 1)) {
    try {
        doWork();
        state.set(2);  // 完成
    } catch (Exception e) {
        state.set(0);  // 失败回退
    }
}
// 其他线程 CAS 失败 → 说明已被其他线程处理，跳过
```

### 3. 避免在循环中过度 CAS

```java
// 如果 CAS 重试次数过多，说明竞争激烈
int retries = 0;
while (!cas成功 && retries++ < MAX_RETRIES) {
    // 自旋等待
}
if (retries >= MAX_RETRIES) {
    // 降级为锁
    synchronized (lock) { ... }
}
```

### 4. AtomicReference 实现无锁栈

```java
class ConcurrentStack<E> {
    private AtomicReference<Node<E>> top = new AtomicReference<>();

    void push(E item) {
        Node<E> newNode = new Node<>(item);
        Node<E> oldTop;
        do {
            oldTop = top.get();
            newNode.next = oldTop;
        } while (!top.compareAndSet(oldTop, newNode));
    }

    E pop() {
        Node<E> oldTop;
        do {
            oldTop = top.get();
            if (oldTop == null) return null;
        } while (!top.compareAndSet(oldTop, oldTop.next));
        return oldTop.item;
    }

    static class Node<E> {
        final E item;
        Node<E> next;
        Node(E item) { this.item = item; }
    }
}
```

---

## 边界情况和坑

### 1. ABA 问题

前面已详细说明。**记住**：大部分场景 ABA 无害，只有在"值被修改过"这个事实本身有语义意义时才需要 AtomicStampedReference。

### 2. CAS 自旋的开销

```
高并发下 CAS 自旋的问题：
- 多个线程反复 CAS 失败 → CPU 空转（busy-wait）
- 每次失败都重新从内存读取 → 缓存一致性流量增加（bus traffic）
- 最终效果：大量 CPU 时间浪费在无效的自旋上

解决方案：
1. LongAdder 分散竞争
2. 限制自旋次数，超限降级为锁
3. 使用 Backoff 策略（失败后随机等待一小段时间再重试）
```

### 3. 原子类不能保证复合操作的原子性

```java
AtomicInteger count = new AtomicInteger(0);

// 以下复合操作不是原子的：
// 场景：count 增到 10 时执行某操作
if (count.get() == 10) {  // A：读取
    doSomething();          // B：条件满足才执行
}
// 线程A 读到 10，还没执行 B
// 线程B 把 count 改成了 11
// 线程A 继续执行 B → 逻辑错误

// 正确做法
int prev = count.getAndIncrement();
if (prev == 9) {  // 刚从 9 变成 10 的那个线程执行
    doSomething();
}
```

### 4. LongAdder.sum() 不是精确快照

```java
LongAdder adder = new LongAdder();
adder.increment();

// sum() 遍历 base + Cell[] 求和
// 求和过程中可能有其他线程在更新 Cell
// 所以返回的是"某个时刻的近似值"

// 如果需要精确的全局快照 → 用 AtomicLong
```

### 5. AtomicIntegerFieldUpdater 的可见性问题

```java
// AtomicFieldUpdater 底层是反射 + CAS
// 反射访问可能触发 security manager 检查
// 在模块化系统（Java 9+）中需要 open 模块

// java --add-opens java.base/java.util.concurrent.atomic=ALL-UNNAMED
```

### 6. false sharing（伪共享）

```
CPU 缓存行（Cache Line）通常是 64 字节。
如果两个 AtomicLong 在内存中相邻（相差不到 64 字节），
它们会被加载到同一个缓存行。

线程A 修改 AtomicLong1 → 使线程B 缓存中的整行失效
线程B 修改 AtomicLong2 → 使线程A 缓存中的整行失效
→ 即使两个变量无关，也会互相导致缓存失效

LongAdder 的 Cell[] 通过 @Contended 注解（Java 8+）在 Cell 之间
插入填充字节，避免伪共享：

@jdk.internal.vm.annotation.Contended
static final class Cell {
    volatile long value;
    // 编译器会自动填充到 64 字节（或 128 字节）
}
```

---

## 我的理解

CAS 是 Java 并发包的 DNA。理解 CAS，就理解了为什么 Atomic 类是线程安全的、为什么 ReentrantLock 比 synchronized 更灵活、为什么 ConcurrentHashMap 读操作不需要加锁。

**CAS 的核心认知**：

1. **CAS 是乐观锁**——假设没有冲突，失败再重试。适合冲突少的场景
2. **CAS 本身只保证单个变量的原子操作**——复合操作需要 CAS + 循环（如 incrementAndGet），但多个变量的协调仍然需要锁
3. **CAS 的性能优势来自无阻塞**——没有 OS 上下文切换，但高并发下的自旋 CPU 开销不能忽视
4. **LongAdder 是 CAS 的工程优化**——通过空间换时间（Cell 数组），将竞争分散到多个槽位

**面试中 CAS 的高频考点**：

1. **CAS 原理**（比较并交换、CPU cmpxchg 指令）
2. **CAS 的三个问题**（ABA / 自旋开销 / 只能保证单个变量原子性）
3. **AtomicInteger 底层实现**（Unsafe + volatile + CAS 循环）
4. **AtomicLong vs LongAdder**（强一致 vs 最终一致、性能差异、伪共享）
5. **ABA 问题的解决方案**（AtomicStampedReference / 版本号）
6. **CAS vs synchronized**（乐观 vs 悲观、适用场景）
7. **AtomicFieldUpdater 的使用场景和限制**
