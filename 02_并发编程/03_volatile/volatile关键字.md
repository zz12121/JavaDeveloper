# volatile 关键字

## 这个问题为什么存在？

> CPU 有多级缓存（L1/L2/L3），每个核心的缓存是独立的。  
> 一个线程修改变量，其他线程**可能永远看不到新值**（缓存不一致）。

这就是**内存可见性**问题。

没有 `volatile` 之前，程序员需要用 `synchronized`（重量级）或者 `Lock` 来保证可见性，代价太大。  
`volatile` 提供了一种**轻量级**的可见性保证，同时禁止指令重排序。

---

## 它是怎么解决问题的？

### 核心机制：MESI 协议 + 内存屏障

#### 硬件层：CPU 缓存一致性（MESI 协议）

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

**MESI** 是缓存一致性协议，定义了缓存行的 4 种状态：

| 状态 | 含义 | 触发条件 |
|------|------|----------|
| **M**（Modified） | 缓存行只在我这里，且已修改 | 我写了，别人没有 |
| **E**（Exclusive） | 缓存行只在我这里，未修改 | 我读了，别人没读 |
| **S**（Shared） | 缓存行在多个核心，都未修改 | 多个核心都读了 |
| **I**（Invalid） | 缓存行无效，需要重新读取 | 别的核写了，我的副本作废 |

**`volatile` 写操作在硬件层做了什么？**

> 写 `volatile` 变量时，JVM 会插入 `Lock` 前缀指令（x86）。  
> 这个指令的作用：  
> 1. 把当前核心的缓存行**立即刷回主内存**  
> 2. 其他核心上对应的缓存行**被标记为 Invalid**（需要重新读）  

这保证了：**一个线程写，其他线程立即可见**。

---

#### JVM 层：内存屏障（Memory Barrier）

`volatile` 在读写前后插入内存屏障，禁止指令重排序：

```
volatile 写：
  StoreStore Barrier   ← 保证前面的写操作先完成
  ... 写 volatile 变量 ...
  StoreLoad Barrier    ← 保证写操作对其他 CPU 可见（最重）

volatile 读：
  ... 读 volatile 变量 ...
  LoadLoad Barrier    ← 保证后面的读操作在 volatile 读之后
  LoadStore Barrier   ← 保证后面的写操作在 volatile 读之后
```

**为什么需要禁止重排序？**

```java
// 双重检查锁的单例（经典坑）
class Singleton {
    private static Singleton instance;

    static Singleton getInstance() {
        if (instance == null) {               // ①
            synchronized (Singleton.class) {
                if (instance == null)
                    instance = new Singleton(); // ②
            }
        }
        return instance;
    }
}
```

**问题在 ②**：`new Singleton()` 不是原子操作，分三步：

```
1. 分配内存空间
2. 初始化对象（调用构造方法）
3. 把引用指向内存空间
```

**步骤 2 和 3 可能被重排序**！  
线程 A 执行到「3 完成、2 未完成」，线程 B 在 ① 看到 `instance != null`，直接返回一个**未初始化完成的对象**（空指针崩溃）。

**解决**：`private static volatile Singleton instance;`

`volatile` 禁止了步骤 2 和 3 的重排序，保证对象完全初始化后才对别的线程可见。

---

### 源码层面的使用

```java
// Java 层面
volatile int flag = 0;

// 编译成字节码后，flags 里多了 ACC_VOLATILE
// 在 hotspot 源码里：
// bytecodeInterpreter.cpp:
//  if (cache->is_volatile()) {
//      OrderAccess::storeload();  // 插入内存屏障
//  }
```

**`Unsafe` 类提供了更底层的 `volatile` 操作**：

```java
Unsafe unsafe = Unsafe.getUnsafe();
long offset = unsafe.objectFieldOffset(MyClass.class.getDeclaredField("flag"));

// volatile 写
unsafe.putObjectVolatile(obj, offset, value);

// volatile 读
Object val = unsafe.getObjectVolatile(obj, offset);
```

`ConcurrentHashMap` 里的 `table`（哈希表引用）就是 `volatile` 的，保证扩容时对新表的可见性。

---

## 它和相似方案的本质区别是什么？

### volatile vs synchronized

| 维度 | volatile | synchronized |
|------|----------|---------------|
| **原子性** | ❌ 不保证（`i++` 不是原子） | ✅ 保证 |
| **可见性** | ✅ 保证 | ✅ 保证 |
| **有序性** | ✅ 禁止重排序 | ✅ 保证（临界区内有序） |
| **性能** | 轻量级（内存屏障） | 重量级（锁升级后好很多） |
| **适用场景** | 状态标志、double-check | 复合操作（i++） |

**为什么 `i++` 不是原子的？**

```java
volatile int i = 0;

// 线程 A 和 B 同时执行 i++
// 实际步骤：
// 1. 读 i（两个线程都读到 0）
// 2. 加 1（两个线程都得到 1）
// 3. 写回 i（两个线程都写 1，丢失了一次递增）
```

`volatile` 保证**读到的和写入的都立即可见**，但不保证**读→改→写**是原子的。  
这种「读→改→写」需要 `synchronized` 或 `AtomicInteger`。

---

### volatile 的内存语义 vs happens-before

`volatile` 在 JMM（Java 内存模型）里的 guarantees：

```
写 volatile 变量 happens-before 后续读这个变量
```

**实际含义**：

```java
volatile boolean flag = false;
int value = 0;

// 线程 A
value = 42;         // ①
flag = true;          // ②（volatile 写）

// 线程 B
if (flag) {          // ③（volatile 读）
    System.out.println(value);  // ④ 保证输出 42
}
```

**为什么 `value = 42` 对线程 B 可见？**

> `flag = true`（volatile 写）之前的写操作，会**连同 volatile 写一起，被刷到主内存**。  
> 线程 B 读 `flag`（volatile 读）时，**会把其他变量也一起重新加载**。  
> 这是由 JMM 的「**volatile 写读内存语义**」保证的。

---

## 正确使用方式

### 1. 状态标志（最经典）

```java
class Task implements Runnable {
    volatile boolean stopped = false;

    public void stop() {
        stopped = true;   // 其他线程立即可见
    }

    public void run() {
        while (!stopped) {
            // 工作循环
        }
    }
}
```

**为什么必须 `volatile`？**

> 没有 `volatile`，`stopped` 可能被缓存在 CPU 寄存器和 L1 Cache 中，  
> 其他线程调用 `stop()` 修改后，工作线程**可能永远看不到新值**（死循环）。

---

### 2. double-check 单例（最经典 2）

```java
class Singleton {
    private static volatile Singleton instance;  // 必须 volatile

    static Singleton getInstance() {
        if (instance == null) {                  // ① 第一次检查
            synchronized (Singleton.class) {
                if (instance == null)              // ② 第二次检查
                    instance = new Singleton();    // ③
            }
        }
        return instance;
    }
}
```

**为什么必须 `volatile`？（再解释一遍）**

> ③ 不是原子操作（分配内存 → 初始化 → 引用赋值）。  
> 如果重排序成「分配内存 → 引用赋值 → 初始化」，  
> 线程 B 在 ① 看到 `instance != null`，直接返回，但对象还没初始化完 → 崩溃。  
> `volatile` 禁止这个重排序。

---

### 3. 独立观察（每轮读取最新值）

```java
// 一个线程写，多个线程读（读多写少场景）
volatile int latestTemperature;

void sensorThread() {
    while (true) {
        latestTemperature = readSensor();  // 写
        Thread.sleep(1000);
    }
}

void displayThread() {
    while (true) {
        int temp = latestTemperature;      // 读（总是最新值）
        display(temp);
    }
}
```

---

## 边界情况和坑

### 1. volatile 不保证原子性（最常见的误解）

```java
// ❌ 错误认知：volatile 能保证 i++ 线程安全
volatile int count = 0;

void increment() {
    count++;   // 不是原子的！多线程下会丢失更新
}

// ✅ 正确：用 AtomicInteger
AtomicInteger count = new AtomicInteger(0);
void increment() {
    count.incrementAndGet();  // CAS，原子操作
}
```

---

### 2. volatile 不适合复合条件

```java
// ❌ 错误：volatile 不能保证复合操作的原子性
volatile int lower = 0;
volatile int upper = 10;

void setLower(int value) {
    if (value < upper)   // ① 检查
        lower = value;    // ② 设置（但①和②之间，upper 可能被别的线程改了）
}

void setUpper(int value) {
    if (value > lower)
        upper = value;
}
```

> 线程 A 执行 `setLower(5)`，检查 `5 < upper(10)` 通过后，  
> 线程 B 执行 `setUpper(4)`，把 `upper` 改成了 4。  
> 线程 A 继续执行 `lower = 5`，此时 `lower(5) > upper(4)`，破坏了约束。

**解决**：用 `synchronized` 把 `检查+设置` 包成原子操作。

---

### 3. long 和 double 的 non-atomic treatment

```java
// 在 32 位 JVM 上，long/double 的读写可能不是原子的！
long value = 0xFFFFFFFFL;

// 线程 A 写高 32 位，还没写低 32 位
// 线程 B 读到的可能是「高 32 位新值 + 低 32 位旧值」
// → 读到一个完全错误的值

// ✅ 解决：volatile long value（保证 64 位原子读写）
volatile long value = 0xFFFFFFFFL;
```

> 64 位 JVM 上，long/double 的读写**默认是原子的**，不需要 `volatile`。  
> 但规范里 32 位 JVM 不保证，所以**防御性编程**仍然建议加 `volatile`。

---

### 4. volatile 不能用于构建「事务」

```java
// ❌ 错误：用 volatile 模拟事务
volatile int balance = 100;

void transfer(int amount) {
    if (balance >= amount) {    // ①
        balance -= amount;        // ②
    }
}

// 线程 A 和 B 同时执行，都通过了 ①（balance=100，amount=80）
// 结果：balance = 20（应该是 100-80-80 = -60，但没检查出来）
```

`volatile` 只能保证**单个读写**的可见性，不能保证**多个操作**的事务性。  
需要 `synchronized` 或 `AtomicReference`（CAS 循环）。

---

## 我的理解

`volatile` 的本质是**告诉编译器和 CPU：「这个变量可能被其他线程改，每次用都要从内存重新读，每次写完都要立即刷回内存」**。

它的**适用场景非常窄**：
- ✅ 状态标志（`stopped = true`）
- ✅ double-check 单例
- ✅ 独立观察（读多写少）
- ❌ 复合操作（`i++`、`check-then-act`）
- ❌ 事务语义（转账、库存扣减）

面试时，`volatile` 常和以下知识点一起考：
1. JMM 内存模型（主内存 vs 工作内存）
2. happens-before 规则
3. 单例模式的 N 种写法（饿汉/懒汉/双重检查/枚举）
4. `synchronized` vs `volatile` vs `AtomicXXX`

---
