# JMM 内存模型

> JMM 定义了线程与内存的交互规则——每个线程有私有工作内存，线程间只能通过主内存间接通信。happens-before 规则是推导可见性的核心工具。

---

## 这个问题为什么存在？

现代 CPU 的速度远超内存，为此引入了多级缓存（L1/L2/L3）。每个 CPU 核心有自己的缓存副本，导致一个核心写入的值对另一个核心不可见（缓存不一致）。同时，编译器和 CPU 为了提高执行效率会重排指令顺序。

如果没有统一的规范，程序员需要了解每种 CPU 架构的缓存协议才能写正确的并发代码——这不可能。JMM 就是这个抽象层，它在硬件之上提供了一套**可推导的可见性保证**。

---

## 它是怎么解决问题的？

### 主内存与工作内存

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

JMM 定义了 8 种原子操作（lock、unlock、read、load、use、assign、store、write）来控制主内存和工作内存之间的数据交互。但实际开发中不需要直接使用这些操作——通过 [[02_并发编程/02_JMM内存模型/volatile|volatile]]、[[02_并发编程/03_锁机制/锁机制|synchronized]] 等高级语义间接使用。

### happens-before 规则

happens-before 是 JMM 给程序员的**可见性推导工具**。

**定义**：如果操作 A happens-before 操作 B，那么 A 的执行结果对 B 可见，且 A 的执行顺序排在 B 之前。

```
8 条 happens-before 规则：

1. 程序顺序规则
   同一线程中，前面的操作 hb 后面的操作
   （注意：不意味着不能重排——如果重排后单线程结果不变，JMM 允许重排）

2. 监视器锁规则
   unlock 操作 hb 后续对同一锁的 lock 操作
   （synchronized 的可见性保证来源于此）

3. volatile 变量规则
   volatile 写 hb 后续对同一变量的 volatile 读
   （volatile 的可见性保证来源于此）

4. volatile 传递性
   如果 A hb B，且 B hb C，那么 A hb C

5. start() 规则
   Thread.start() hb 该线程内的所有操作

6. join() 规则
   线程内的所有操作 hb Thread.join() 的返回

7. interrupt() 规则
   Thread.interrupt() hb 被中断线程检测到中断事件

8. 终结规则
   对象构造函数执行结束 hb finalize() 的开始
```

**实战推演**：

```java
int x = 0;
volatile boolean flag = false;

// 线程1
x = 42;               // C
flag = true;          // D（volatile 写）

// 线程2
if (flag) {           // E（volatile 读）
    System.out.println(x);  // F
}
```

可见性推导链：
1. C hb D（程序顺序规则）
2. D hb E（volatile 规则）
3. E hb F（程序顺序规则）
4. 传递性：C → D → E → F，所以 **C hb F**
5. 结论：线程1 对 x 的修改（x=42）对线程2 可见

### 重排序

三种类型的重排序：

| 类型 | 说明 | 示例 |
|------|------|------|
| **编译器重排序** | 编译器在不改变单线程语义的前提下调整语句顺序 | 语句 A 和 B 无数据依赖，编译器调整先后 |
| **指令级并行重排序** | CPU 乱序执行，无依赖的指令并行执行 | load 和 store 同时发出 |
| **内存系统重排序** | CPU 缓存和写缓冲区导致写操作顺序和代码不一致 | store A 先发但 store B 先到主内存 |

JMM 的基本原则：**不管怎么重排，单线程执行结果不能改变**（as-if-serial 语义）。但多线程下，重排可能导致其他线程看到不一致的状态——这正是需要 volatile 和 synchronized 的原因。

### JMM 对 final 字段的特殊保证

Java 5 之后，JMM 对 final 字段提供了初始化安全性：

```java
public class Safe {
    private final int x;

    public Safe() {
        x = 42;  // 构造器中对 final 赋值
    }
    // 构造器结束后，其他线程一定能看到 x = 42
    // 不需要任何同步
}
```

**前提条件**：
1. 构造器内完成初始化
2. 构造器内**不要泄露 this 引用**
3. 对象引用对其他线程可见后，final 字段的值一定可见

```java
// 违反第 2 条的例子：
public class Unsafe {
    final int x;
    Unsafe() {
        x = 42;
        new Thread(() -> System.out.println(this.x)).start();
        // this 在构造器内就被其他线程访问——x 可能还是 0
    }
}
```

final 保证的是**引用本身**的可见性，不保证引用指向对象内容的可见性。`final List<String> items` 的 items 引用不能变，但 list 的内容可以被其他线程修改。

### 可见性机制对比

volatile 详细分析见 [[02_并发编程/02_JMM内存模型/JMM内存模型详解|JMM内存模型详解]]，synchronized 和 Lock 的详细说明见 [[02_并发编程/03_锁机制/锁机制|锁机制]]。

| 机制 | 可见性 | 有序性 | 原子性 | 阻塞 |
|------|--------|--------|--------|------|
| volatile | ✓ 强制刷新 | ✓ 禁止重排 | 仅读写原子 | ✗ |
| synchronized | ✓ 释放时刷新 | ✓ 临界区有序 | ✓ 互斥 | ✓ |
| Atomic\* | ✓ volatile 语义 | ✓ volatile 语义 | ✓ CAS | ✗ |
| Lock | ✓ unlock 时刷新 | ✓ lock/unlock 有序 | ✓ 互斥 | ✓ |
| final | ✓ 初始化安全 | — | — | — |

---

## 深入原理

### JMM vs C++ 内存模型

| 维度 | JMM | C++ Memory Model |
|------|-----|-----------------|
| 标准化 | JSR-133（2004） | C++11（2011） |
| 核心概念 | happens-before | sequenced-before / synchronizes-with |
| 可见性控制 | volatile / synchronized / final | atomic / memory_order / fence |
| 复杂度 | 相对简单（8 条规则） | 更灵活但更复杂（6 种 memory_order） |

### happens-before ≠ 实际执行顺序

```
A happens-before B：
- A 的结果对 B 可见 ✓
- A 的结果按代码顺序排在 B 之前 ✓
- A 在物理时间上先于 B 执行 ✗（不保证！）
```

happens-before 是一种偏序关系，保证的是可见性和有序性，不是物理时间上的先后。两个 CPU 完全可能并行执行 A 和 B，只要 B 最终看到 A 的正确结果。

### synchronized 的可见性发生时机

synchronized 的可见性保证发生在 **unlock 和后续 lock 之间**。两个线程如果不同步访问同一个锁，synchronized 不提供任何可见性保证。

```java
// 线程A
synchronized (lock) {
    x = 42;
}  // unlock 时将 x 刷新到主内存

// 线程B：在 A unlock 之前读取 x → 不保证看到 42
// 线程B：在 A unlock 之后，lock 同一个锁 → 保证看到 42
```

---

## 正确使用方式

### 1. 用 happens-before 推导可见性

当需要判断"这个场景线程能看到最新值吗？"，用 happens-before 链条推导，比凭直觉可靠得多：

```java
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

// 推导：A hb B（程序顺序）→ B hb C（volatile）→ C hb D（程序顺序）
// 传递性：A hb D → getValue() 一定能看到 config 的完整初始化
```

### 2. double-checked locking 必须加 volatile

```java
class Singleton {
    private static volatile Singleton instance;  // 必须加 volatile！

    static Singleton getInstance() {
        if (instance == null) {
            synchronized (Singleton.class) {
                if (instance == null) {
                    instance = new Singleton();
                }
            }
        }
        return instance;
    }
}
```

`new Singleton()` 分三步：分配内存 → 调用构造器 → 引用赋值。步骤 2 和 3 可能被重排成"分配内存 → 引用赋值 → 调用构造器"。线程 B 第一次检查时可能看到非 null 但未初始化完成的对象。volatile 禁止了这个重排。详见 [[02_并发编程/02_JMM内存模型/volatile|volatile]] 的 DCL 分析。

### 3. 构造器内不要泄露 this

```java
// ✗ this 在构造器内被其他线程访问
public class Bad {
    Bad() {
        eventBus.register(this);  // this 泄露，final 字段可能未初始化完
    }
}

// ✓ 在构造器外注册
Bad bad = new Bad();
eventBus.register(bad);
```

---

## 边界情况和坑

### 1. 64 位变量的非原子写（torn read）

Java 规范允许对非 volatile 的 long/double 的写操作被拆分为两次 32 位写。其他线程可能读到高 32 位是新值、低 32 位是旧值——一个完全错误的值。

```java
long timestamp;  // 非 volatile
// 线程A: timestamp = 0x00000001_FFFFFFFF
// 线程B 可能读到: 0x00000001_00000000（半写）
```

**防御**：共享的 long/double 使用 [[02_并发编程/02_JMM内存模型/volatile|volatile]] 或 AtomicLong。64 位 JVM 上默认原子，但规范不保证——防御性编程仍然建议加 volatile。

### 2. happens-before 不保证物理执行顺序

```java
int a = 1;  // A
int b = 2;  // B
// A hb B（程序顺序规则）
// 但 A 和 B 可能在不同 CPU 上并行执行
// 只要 B 看到 a=1 的结果，就算满足 happens-before
```

不要用 happens-before 来推理物理时间，它只保证结果可见性。

### 3. final 只保证引用可见性，不保证内容

```java
class Container {
    final List<String> items;

    Container() {
        items = new ArrayList<>();
        items.add("initial");  // 构造器内可以修改
    }
}
// items 引用不可变，但 items 的内容可变
// 其他线程看到 items 后，items.add() 的结果不一定可见
// 需要额外的同步才能安全修改 list 内容
```
