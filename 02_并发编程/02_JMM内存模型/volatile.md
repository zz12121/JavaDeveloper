# volatile

> volatile 是 JMM 提供的轻量级可见性保障——通过内存屏障强制刷新缓存，通过禁止指令重排保证有序性。但它不保证复合操作的原子性。

---

## 这个问题为什么存在？

CPU 多级缓存导致同一变量在不同核心上可能有不同副本。一个线程写入新值后，其他线程可能永远读到旧值。

没有 volatile 之前，保证可见性只能用 [[02_并发编程/03_锁机制|synchronized]]（重量级）或 Lock。volatile 提供了一种更轻量的方式——不需要加锁，就能让写入对其他线程立即可见，同时禁止特定的指令重排。

---

## 它是怎么解决问题的？

### 硬件层：MESI 缓存一致性协议

```
CPU Core 0          CPU Core 1
  L1 Cache    ←→    L1 Cache
      ↓                  ↓
  L2 Cache    ←→    L2 Cache
      ↓                  ↓
    L3 Cache (共享)
      ↓
    主内存
```

MESI 定义了缓存行的 4 种状态：

| 状态 | 含义 | 触发条件 |
|------|------|----------|
| **M**（Modified） | 缓存行只在我这里，且已修改 | 我写了，别人没有 |
| **E**（Exclusive） | 缓存行只在我这里，未修改 | 我读了，别人没读 |
| **S**（Shared） | 多个核心都有，都未修改 | 多个核心都读了 |
| **I**（Invalid） | 缓存行无效 | 别的核写了，我的副本作废 |

**volatile 写在硬件层做了什么？**

在 x86 上，JVM 对 volatile 写插入 `Lock` 前缀指令：
1. 当前核心的缓存行**立即刷回主内存**
2. 其他核心上对应的缓存行**被标记为 Invalid**（需要重新读）

这保证了：**一个线程写，其他线程立即可见**。

### JVM 层：内存屏障（Memory Barrier）

volatile 在读写前后插入内存屏障，禁止指令重排序：

```
volatile 写：
  StoreStore Barrier   ← 保证前面的普通写操作先完成
  [写 volatile 变量]
  StoreLoad Barrier    ← 保证写完成后再执行后续的读（最贵的屏障）

volatile 读：
  [读 volatile 变量]
  LoadLoad Barrier    ← 保证 volatile 读在后面的读之前完成
  LoadStore Barrier   ← 保证 volatile 读在后面的写之前完成
```

四种屏障的作用：

| 屏障 | 作用 | 代价 |
|------|------|------|
| StoreStore | 前面的 store 完成后再执行后面的 store | 低 |
| StoreLoad | store 完成后再执行后续的 load（最贵） | 高 |
| LoadLoad | 前面的 load 完成后再执行后面的 load | 低 |
| LoadStore | 前面的 load 完成后再执行后面的 store | 低 |

### 源码层面的实现

```java
volatile int flag = 0;

// 编译成字节码后，字段带有 ACC_VOLATILE 标志
// HotSpot 源码 bytecodeInterpreter.cpp:
//   if (cache->is_volatile()) {
//       OrderAccess::storeload();  // 插入内存屏障
//   }

// Unsafe 提供更底层的 volatile 操作
Unsafe unsafe = Unsafe.getUnsafe();
long offset = unsafe.objectFieldOffset(MyClass.class.getDeclaredField("flag"));
unsafe.putObjectVolatile(obj, offset, value);   // volatile 写
Object val = unsafe.getObjectVolatile(obj, offset);  // volatile 读
```

[[02_并发编程/05_并发容器|ConcurrentHashMap]] 的 `table` 引用就是 volatile 的，保证扩容时新数组对所有线程可见。

### volatile 的内存语义（JMM 层面）

volatile 写 happens-before 后续 volatile 读。这意味着 volatile 写之前的所有写操作，对 volatile 读之后的所有操作可见：

```java
volatile boolean flag = false;
int value = 0;

// 线程A
value = 42;         // ① 普通写
flag = true;          // ② volatile 写

// 线程B
if (flag) {          // ③ volatile 读
    System.out.println(value);  // ④ 保证输出 42
}
```

推导：① hb ②（程序顺序）→ ② hb ③（volatile 规则）→ ③ hb ④（程序顺序）→ ① hb ④。这就是 [[02_并发编程/02_JMM内存模型/JMM内存模型详解|happens-before]] 推导的实际应用。

---

## 深入原理

synchronized 的详细说明见 [[02_并发编程/03_锁机制|锁机制]]。

| 维度 | volatile | synchronized |
|------|----------|----------|
| 原子性 | ❌ 不保证（`i++` 不是原子） | ✅ 保证 |
| 可见性 | ✅ 保证 | ✅ 保证 |
| 有序性 | ✅ 禁止重排 | ✅ 临界区有序 |
| 性能 | 轻量级（内存屏障） | 重量级（锁升级后好很多） |
| 阻塞 | 不阻塞 | 互斥阻塞 |
| 适用场景 | 状态标志、DCL | 复合操作（i++） |

**为什么 volatile 不保证原子性？**

volatile 保证的是**单个读操作**和**单个写操作**各自的可见性。但 `i++` 是"读→改→写"三步操作：

```java
volatile int i = 0;

// 线程A 和 B 同时执行 i++：
// 1. 读 i → 两个线程都读到 0
// 2. 加 1 → 两个线程都得到 1
// 3. 写回 i → 两个线程都写 1，丢失了一次递增
```

需要原子性就用 [[02_并发编程/04_CAS与原子类|AtomicInteger]] 或 synchronized。

---

## 正确使用方式

### 1. 状态标志（最经典场景）

```java
class Task implements Runnable {
    volatile boolean stopped = false;

    public void stop() { stopped = true; }

    public void run() {
        while (!stopped) {
            doWork();
        }
    }
}
```

没有 volatile，`stopped` 可能被缓存在寄存器中，其他线程调用 `stop()` 后工作线程可能永远看不到——死循环。

### 2. DCL 单例模式

```java
class Singleton {
    private static volatile Singleton instance;  // 必须 volatile

    static Singleton getInstance() {
        if (instance == null) {                  // 第一次检查（无锁）
            synchronized (Singleton.class) {
                if (instance == null) {          // 第二次检查（有锁）
                    instance = new Singleton();   // 指令重排风险
                }
            }
        }
        return instance;
    }
}
```

`new Singleton()` 分三步：分配内存 → 调用构造器 → 引用赋值。步骤 2 和 3 可能被重排成"分配内存 → 引用赋值 → 调用构造器"。线程 B 第一次检查时看到非 null 但对象未初始化完成。volatile 的 StoreLoad 屏障禁止了这个重排。

### 3. 独立观察（读多写少）

```java
volatile int latestTemperature;

void sensorThread() {
    while (true) {
        latestTemperature = readSensor();  // 写
        Thread.sleep(1000);
    }
}

void displayThread() {
    while (true) {
        int temp = latestTemperature;  // 读（总是最新值）
        display(temp);
    }
}
```

一个线程写、多个线程读的场景，volatile 是最轻量的可见性保障。不适合写多读多或复合操作的场景。

---

## 边界情况和坑

### 1. volatile 不能保证复合操作原子性（最常见的误解）

```java
volatile int count = 0;
count++;  // ❌ 读-改-写，不是原子的！

// 正确：用 AtomicInteger
AtomicInteger count = new AtomicInteger(0);
count.incrementAndGet();  // CAS，原子操作
```

### 2. volatile 不适合复合条件（check-then-act）

```java
volatile int lower = 0;
volatile int upper = 10;

void setLower(int value) {
    if (value < upper)   // 检查通过
        lower = value;    // 但检查和赋值之间 upper 可能被其他线程改了
}
```

线程 A 执行 `setLower(5)`，检查 `5 < 10` 通过；线程 B 把 upper 改成 4；线程 A 继续写 `lower = 5`，此时 `lower(5) > upper(4)`，约束被破坏。需要 synchronized 包裹"检查+设置"。

### 3. long/double 的 torn read

32 位 JVM 上，非 volatile 的 long/double 读写可能被拆为两次 32 位操作。其他线程可能读到"高 32 位新值 + 低 32 位旧值"的拼接值。64 位 JVM 上默认原子，但规范不保证——防御性编程仍然建议共享的 long/double 加 volatile。

### 4. volatile 不能用于事务语义

```java
volatile int balance = 100;
void transfer(int amount) {
    if (balance >= amount) {  // 检查
        balance -= amount;      // 扣减——但两步之间可能被其他线程打断
    }
}
```

两个线程同时看到 balance=100，都通过检查，各扣 80，结果 balance=-60 而非抛出余额不足。需要 synchronized 或 AtomicReference（CAS 循环）。
