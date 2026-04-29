# JMM 内存模型

> JMM（Java Memory Model）是 Java 并发编程的理论基石。它不是"JVM 的内存布局"（那是堆/栈/方法区），而是一套**规范**——规定线程之间如何通过内存进行交互。理解 JMM 是理解 volatile、synchronized、final 等关键字语义的前提。

---

## 这个问题为什么存在？

### 现代硬件的多层缓存架构

为什么多线程会出现"一个线程写了变量，另一个线程看不到"这种诡异问题？根源在硬件：

```
CPU 的速度 >> 内存的速度
为了弥补这个差距，CPU 引入了多层缓存：

CPU Core 0                CPU Core 1
┌──────────┐              ┌──────────┐
│ L1 Cache │              │ L1 Cache │
├──────────┤              ├──────────┤
│ L2 Cache │              │ L2 Cache │
├──────────┴──────────────┴──────────┤
│           L3 Cache (共享)           │
├────────────────────────────────────┤
│             主内存 (RAM)           │
└────────────────────────────────────┘

线程 A 在自己的 L1 中修改了变量 x
线程 B 从自己的 L1 读取变量 x → 读到的是旧值！
```

这导致了两个问题：
1. **缓存一致性问题**：多个 CPU 缓存中的同一份数据可能不一致
2. **指令重排问题**：CPU 和编译器为了提高执行效率，可能调整指令执行顺序

### JMM 要解决什么？

JMM 的目标是：**为程序员提供一套内存可见性保证**，让程序员在不了解底层硬件细节的情况下，也能编写正确的并发程序。

JMM 提出的解决方案：

```
1. 抽象出「主内存」和「工作内存」的概念
   - 主内存 = 所有变量存储的地方（对应物理内存/硬件缓存）
   - 工作内存 = 每个线程私有的内存（对应 CPU 寄存器/缓存）

2. 定义 8 种内存操作（lock、unlock、read、load、use、assign、store、write）
   控制主内存和工作内存之间的数据交互

3. 定义 happens-before 规则
   告诉程序员：在什么条件下，一个线程的操作结果对另一个线程可见

4. 提供 volatile、synchronized、final 等关键字
   让程序员能控制内存的可见性和有序性
```

---

## 它是怎么解决问题的？

### 主内存 vs 工作内存

```
┌─────────────────────────────────────────────┐
│                  主内存                      │
│         （所有共享变量存储在这里）              │
│                                             │
│   x = 0                                     │
└───────┬───────────────────────┬─────────────┘
        │ store / write         │ read / load
        ↓                       ↑
┌───────────────┐     ┌───────────────┐
│  线程A 工作内存 │     │  线程B 工作内存 │
│               │     │               │
│  x 的副本      │     │  x 的副本      │
│  assign: x=1  │     │  use: 读取x   │
│               │     │               │
└───────────────┘     └───────────────┘

线程A 执行 x = 1：
1. assign：线程A 工作内存中 x = 1
2. store：从工作内存传到主内存
3. write：写入主内存

线程B 读取 x：
1. read：从主内存读取到工作内存
2. load：存入工作内存
3. use：使用这个值
```

**关键规则**：
- 线程不能直接读写主内存变量，必须通过工作内存中转
- 线程之间的工作内存互相不可见——只能通过主内存间接通信
- 这就是为什么一个线程的修改，另一个线程"看不到"

### happens-before 规则

happens-before 是 JMM 的核心概念，也是理解所有并发语义的关键。

**定义**：如果操作 A happens-before 操作 B，那么 A 的执行结果对 B 可见，且 A 的执行顺序排在 B 之前。

```
8 条 happens-before 规则：

1. 程序顺序规则
   同一个线程中，前面的操作 happens-before 后面的操作
   （注意：这不意味着不能重排——如果重排后结果不变，JMM 允许重排）

2. 监视器锁规则
   unlock 操作 happens-before 后续对同一锁的 lock 操作
   （synchronized 的可见性保证就来源于此）

3. volatile 变量规则
   volatile 写 happens-before 后续对同一变量的 volatile 读
   （volatile 的可见性保证就来源于此）

4. 传递性
   A happens-before B，B happens-before C → A happens-before C

5. start() 规则
   Thread.start() happens-before 该线程内的所有操作

6. join() 规则
   线程内的所有操作 happens-before Thread.join() 的返回

7. interrupt() 规则
   Thread.interrupt() happens-before 被中断线程检测到中断事件

8. 终结规则
   对象构造函数执行结束 happens-before finalize() 的开始
```

**happens-before 实战推演**：

```java
int x = 0;            // A
volatile boolean flag = false;  // B

// 线程1
x = 42;               // C
flag = true;          // D（volatile 写）

// 线程2
if (flag) {           // E（volatile 读）
    System.out.println(x);  // F
}
```

可见性推导链：
1. C happens-before D（程序顺序规则）
2. D happens-before E（volatile 规则：写 happens-before 后续的读）
3. E happens-before F（程序顺序规则）
4. 由传递性：C → D → E → F，所以 C happens-before F
5. 结论：**线程1 对 x 的修改（x=42）对线程2 可见**

### 重排序

**编译器重排序**：编译器在不改变单线程语义的前提下调整语句顺序。

**指令级并行重排序**：CPU 采用乱序执行技术，只要不依赖数据，指令可以并行执行。

**内存系统重排序**：CPU 缓存和写缓冲区可能导致写操作的执行顺序和代码顺序不一致。

```
// 源代码
int a = 1;  // A
int b = 2;  // B

// 可能被重排序为
int b = 2;  // B 先执行
int a = 1;  // A 后执行

单线程下结果一样 → JMM 允许这种重排
多线程下可能出问题：

// 线程1
int a = 1;
int b = 2;
volatile boolean ready = true;

// 线程2
if (ready) {
    // 能看到 a=1 和 b=2 吗？
    // 答案：能——因为 volatile 写 happens-before volatile 读
    // volatile 之前的所有写操作，对 volatile 读之后的操作可见
}
```

**volatile 的内存屏障（Memory Barrier）**：

```
volatile 写操作前插入 StoreStore 屏障
volatile 写操作后插入 StoreLoad 屏障
volatile 读操作后插入 LoadLoad + LoadStore 屏障

屏障的作用：禁止屏障前后的指令重排

StoreStore：确保前面的写操作完成，再执行后面的写
StoreLoad：确保写完成后再执行后续的读（最昂贵的屏障）
LoadLoad：确保前面的读完成，再执行后面的读
LoadStore：确保前面的读完成，再执行后面的写
```

### JMM 对 final 字段的特殊保证

Java 5 之后，JMM 对 final 字段提供了初始化安全性保证：

```java
public class Safe {
    private final int x;

    public Safe() {
        x = 42;  // 构造器中对 final 赋值
    }
    // 构造器结束后，其他线程一定能看到 x = 42
    // 不需要任何同步
}

// 只要不泄露 this 引用（构造器内启动线程/注册监听器等）
// final 字段的可见性由 JMM 保证
```

```
final 的可见性保证前提：
1. 构造器内完成初始化
2. 构造器内不要泄露 this 引用
3. 对象引用对其他线程可见后，final 字段的值一定可见

如果违反第 2 条：
public class Unsafe {
    final int x;
    Unsafe() {
        x = 42;
        new Thread(() -> System.out.println(this.x)).start();
        // this 在构造器内就被其他线程访问——x 可能还是 0
    }
}
```

### as-if-serial 语义

```
JMM 的基本原则：不管怎么重排序，单线程执行结果不能改变。
这叫 as-if-serial 语义。

但不保证多线程下的正确性——这是并发编程需要同步的根本原因。
```

---

## 和相似方案的区别

### JMM vs C++ 内存模型

| 维度 | JMM | C++ Memory Model |
|------|-----|-----------------|
| 标准化 | JSR-133（2004） | C++11（2011） |
| 核心概念 | happens-before | sequenced-before / synchronizes-with |
| 安全级别 | 不安全（默认允许重排） | 不安全（默认允许重排） |
| 可见性控制 | volatile / synchronized / final | atomic / memory_order / fence |
| 复杂度 | 相对简单（8 条规则） | 更灵活但更复杂（6 种 memory_order） |
| 实际使用 | 开发者感知较强 | 开发者通常不需要直接使用 |

### JMM 下的可见性机制对比

| 机制 | 可见性 | 有序性 | 原子性 | 阻塞 |
|------|--------|--------|--------|------|
| volatile | ✓（强制刷新主内存） | ✓（禁止重排） | 仅写读原子 | ✗ |
| synchronized | ✓（锁释放时刷新） | ✓（锁内禁止重排） | ✓（互斥） | ✓ |
| final | ✓（初始化后不可变） | — | — | — |
| Atomic* | ✓（volatile 语义） | ✓（volatile 语义） | ✓（CAS） | ✗ |
| Lock | ✓（unlock 时刷新） | ✓（lock/unlock 有序） | ✓（互斥） | ✓ |

---

## 正确使用方式

### 1. 用 volatile 保证可见性，但不要用 volatile 保证原子性

```java
// ✓ volatile 正确用法：状态标志
volatile boolean shutdown = false;

// 线程1
while (!shutdown) {
    doWork();
}

// 线程2
shutdown = true;  // 对线程1 立即可见

// ✗ volatile 错误用法：计数器
volatile int count = 0;
count++;  // 不是原子操作！仍然有竞态条件
// 改用 AtomicInteger
```

### 2. 用 happens-before 推导可见性

```java
// 当面试官问"这个场景线程能看到最新值吗？"，用 happens-before 推导：

class Config {
    private volatile boolean initialized = false;
    private Map<String, String> config;

    void init() {
        config = loadConfig();     // A
        initialized = true;        // B（volatile 写）
    }

    String getValue(String key) {
        if (initialized) {          // C（volatile 读）
            return config.get(key); // D
        }
        return null;
    }
}

// 推导：A hb B（程序顺序），B hb C（volatile），C hb D（程序顺序）
// 传递性：A hb D → getValue() 一定能看到 config 的完整初始化
```

### 3. double-checked locking 的正确写法

```java
class Singleton {
    private static volatile Singleton instance;  // 必须加 volatile！

    static Singleton getInstance() {
        if (instance == null) {                  // 第一次检查（无锁）
            synchronized (Singleton.class) {
                if (instance == null) {          // 第二次检查（有锁）
                    instance = new Singleton();   // 这里有指令重排风险
                }
            }
        }
        return instance;
    }
}
```

```
为什么必须加 volatile？

instance = new Singleton() 不是原子操作，分为三步：
1. 分配内存空间
2. 调用构造器初始化
3. 将引用指向内存地址

指令重排可能导致 1→3→2 的顺序：
- 线程A 执行了 1 和 3（instance 不为 null，但对象未初始化）
- 线程B 第一次检查发现 instance != null，直接返回
- 线程B 使用未初始化的对象 → NPE 或其他异常

volatile 禁止了 1→3→2 的重排，保证了安全。
```

---

## 边界情况和坑

### 1. volatile 不能保证复合操作的原子性

```java
volatile int count = 0;

// 以下操作都不是原子的：
count++;           // 读-改-写，三步操作
count = count + 1; // 同上
if (count == 0) {} // 检查-操作，两步操作
```

volatile 只保证"读"和"写"各自的可见性，不保证"读-改-写"作为一个整体的原子性。需要原子性就用 AtomicInteger 或 synchronized。

### 2. 64 位变量的非原子写

```java
// Java 规范：对非 volatile 的 long/double 的写操作
// 可能被拆分为两次 32 位写操作

class Config {
    long timestamp;  // 非 volatile

    // 线程A 写入
    timestamp = 0x00000001_FFFFFFFF;  // 高32位 = 1，低32位 = -1

    // 线程B 可能读到：
    // 0x00000001_00000000  （高32位已更新，低32位还是旧值）
    // 0x00000000_FFFFFFFF  （低32位已更新，高32位还是旧值）
    // 这叫「半写」（torn read）
}
```

**防御**：对 long/double 的共享变量使用 volatile 或 AtomicLong。

### 3. happens-before 不等于实际执行顺序

```
happens-before 保证的是可见性和有序性，不是物理执行时间。

A happens-before B：
- A 的结果对 B 可见 ✓
- A 的结果按代码顺序排在 B 之前 ✓
- A 在物理时间上先于 B 执行 ✗（不保证！）

示例：
int a = 1;  // A
int b = 2;  // B
// A happens-before B（程序顺序规则）
// 但 A 和 B 可能在不同 CPU 上并行执行
// 只要 B 看到 a=1 的结果，就算满足 happens-before
```

### 4. synchronized 的可见性不是"实时的"

```java
// 线程A
synchronized (lock) {
    x = 42;
}  // unlock 时将 x 刷新到主内存

// 线程B
// 在线程A unlock 之前读取 x → 不保证看到 42
// 在线程A unlock 之后，线程B lock 同一个锁 → 保证看到 42
```

synchronized 的可见性保证发生在 unlock 和后续 lock 之间。**两个线程如果不同步访问同一个锁，synchronized 不提供任何可见性保证。**

### 5. final 字段引用的可变性

```java
class Container {
    final List<String> items;  // 引用不可变

    Container() {
        items = new ArrayList<>();
        items.add("initial");  // 构造器内可以修改
    }
}

// items 引用不可变（不能 items = new ArrayList<>()）
// 但 items 指向的 List 内容可变（可以 items.add("new")）
// final 只保证引用本身的可见性，不保证引用指向对象内容的可见性
```

---

## 我的理解

JMM 是 Java 并发编程最难理解、也最重要的概念。很多人背下了 happens-before 的 8 条规则，但遇到实际问题时不会推导。

**理解 JMM 的关键不在于记住规则，而在于建立「心智模型」**：

1. **每个线程有自己的工作内存副本**——不要假设线程A的写入线程B能立即看到
2. **编译器和CPU会重排序**——除非有可见性保障（volatile/synchronized/final），否则不要假设执行顺序
3. **happens-before 是推导可见性的工具**——面试时用 hb 链条推导，比凭直觉回答可靠得多
4. **volatile 解决可见性和有序性，不解决原子性**——复合操作需要原子类或锁

**面试中 JMM 的高频考点**：

1. **happens-before 规则**（几乎必问，要求能推导可见性）
2. **volatile 语义**（可见性 + 有序性，不保证原子性）
3. **指令重排**（三种重排类型、DCL 中 volatile 的作用）
4. **主内存 vs 工作内存**（JMM 的抽象模型）
5. **final 的可见性保证**（初始化安全性、构造器泄露 this）
6. **64 位变量的 torn read 问题**
