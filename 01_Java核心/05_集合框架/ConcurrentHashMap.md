# ConcurrentHashMap

> HashMap 在并发环境下会数据丢失（JDK 7 甚至会死循环）。ConcurrentHashMap 是 Java 为高并发场景设计的线程安全 Map，从 JDK 7 的分段锁演进到 JDK 8 的 CAS + synchronized，锁粒度从「一段桶」细化为「一个桶」。

---

## 这个问题为什么存在？

HashMap 不是线程安全的：

```java
// 问题 1：并发 put 导致数据丢失
// 两个线程同时 put 到同一个空桶，都认为桶为空，后写入的覆盖先写入的

// 问题 2：JDK 7 并发 resize 导致死循环
// 头插法 + 多线程 → 链表环形引用 → get() 死循环

// 问题 3：size 不准确
// 多线程同时 put/remove，size 的读写没有同步
```

**那用 `Collections.synchronizedMap()` 行不行？**
```java
// synchronizedMap 的实现：每个方法都 synchronized 整个 map
public synchronized V put(K key, V value) { ... }
public synchronized V get(Object key) { ... }

// 问题：锁粒度太粗
// 线程 A 在 put → 整个 map 被锁住
// 线程 B 在 get → 也要等 A 释放锁
// 结果：读写互斥，并发度极低
```

**核心问题**：怎么让 Map 在高并发下既安全又高效？ConcurrentHashMap 的答案：**缩小锁的粒度**。

---

## 它是怎么解决问题的？

### JDK 7：分段锁（Segment）

```
ConcurrentHashMap
  └── Segment[]（默认 16 段）
        ├── Segment[0]  → HashEntry[] → 链表
        ├── Segment[1]  → HashEntry[] → 链表
        ├── ...
        └── Segment[15] → HashEntry[] → 链表
```

**核心思想**：把整个 Map 分成 16 段（Segment），每段有独立的锁。

```java
// put 流程
put(key, value)
  ├── 1. hash(key) → 定位到 Segment
  ├── 2. lock Segment（ReentrantLock）
  ├── 3. 在 Segment 内部 put（线程安全）
  └── 4. unlock Segment
```

**优点**：不同线程操作不同 Segment 时，完全并行。

**缺点**：
- 并发度上限是 Segment 数量（默认 16），不能动态扩展
- Segment 内部还是数组+链表，没有红黑树

### JDK 8：CAS + synchronized（桶级别锁）

JDK 8 彻底抛弃了 Segment，改为**锁单个 bucket**：

```java
// JDK 8 的 put 流程（简化）
final V putVal(K key, V value, boolean onlyIfAbsent) {
    // 1. 计算 hash
    int hash = spread(key.hashCode());

    // 2. 定位到 bucket
    for (Node<K,V>[] tab = table;;) {
        Node<K,V> f;
        int n, i, fh;

        if (tab == null || (n = tab.length) == 0)
            tab = initTable();           // 延迟初始化

        else if ((f = tabAt(tab, i = (n - 1) & hash)) == null) {
            // 3. bucket 为空 → CAS 插入（无锁）
            if (casTabAt(tab, i, null, new Node<>(hash, key, value)))
                break;
        }
        else if ((fh = f.hash) == MOVED)
            tab = helpTransfer(tab, f);   // 4. 正在扩容 → 帮忙扩容
        else {
            // 5. bucket 不为空 → synchronized 锁头节点
            synchronized (f) {
                // 链表或红黑树操作（单线程，安全）
                if (fh >= 0) {
                    // 链表操作
                } else if (f instanceof TreeBin) {
                    // 红黑树操作
                }
            }
        }
    }
    addCount(1L, binCount);  // 6. 更新 size
}
```

**JDK 7 vs JDK 8 对比**：

| 维度 | JDK 7 | JDK 8 |
|------|-------|-------|
| 锁粒度 | Segment（一段 bucket）| 单个 bucket |
| 并发度 | 最多 16（Segment 数量）| 理论上无上限（table 长度）|
| 数据结构 | 数组 + 链表 | 数组 + 链表 + 红黑树 |
| 锁实现 | ReentrantLock | synchronized（JDK 6 后性能已优化）|
| 空桶插入 | 也要获取 Segment 锁 | CAS 无锁插入 |
| null key/value | 不允许 | 不允许 |

---

## 深入原理

### 为什么 JDK 8 选择 synchronized 而不是 ReentrantLock？

JDK 7 用 ReentrantLock，JDK 8 改回 synchronized，原因：

```
JDK 6 之前：synchronized 是重量级锁（OS 级别互斥），性能差
JDK 6 之后：synchronized 引入了偏向锁、轻量级锁、自旋锁等优化
JDK 8：synchronized 性能已接近 ReentrantLock

选择 synchronized 的理由：
1. 内存占用更小（ReentrantLock 需要额外对象头）
2. JVM 可以对 synchronized 做更多优化（锁消除、锁粗化、偏向锁）
3. synchronized 的语义更简单，不容易出错（不用手动 unlock）
```

### 为什么 bucket 级别的 synchronized 不是性能瓶颈？

```
大多数情况下，hash 足够均匀，不同线程操作的 bucket 很少冲突
真正冲突时，synchronized 的时间极短（只是链表/树操作）
总体效果：读写操作几乎完全并行
```

JDK 8 的 ConcurrentHashMap 在大多数场景下性能接近 HashMap（只在极少数 bucket 冲突时才有锁竞争）。

### CAS 是什么？

```java
// CAS（Compare-And-Swap）：原子操作，无锁
// 三个参数：内存地址 V，旧值 A，新值 B
// 如果 V 处的值 == A，则更新为 B，返回 true
// 如果 V 处的值 != A，说明被其他线程修改了，返回 false

// ConcurrentHashMap 中的 CAS 用法（Unsafe 类）
static final <K,V> boolean casTabAt(Node<K,V>[] tab, int i,
                                       Node<K,V> c, Node<K,V> v) {
    return U.compareAndSetObject(tab, ((long)i << ASHIFT) + ABASE, c, v);
}
```

CAS 是乐观锁——不先加锁，直接尝试更新，失败则重试。适用于冲突少的场景（大多数 bucket 为空的情况）。

### 并发扩容：transfer 协作

JDK 8 的扩容是一个**多线程协作**的过程：

```
线程 A 触发扩容
  ├── 创建新数组（2 倍容量）
  ├── 把旧数组分成若干段（默认每段 16 个 bucket）
  ├── 线程 A 处理自己负责的段
  └── 标记：table[i] = ForwardingNode（MOVED 状态）

线程 B 来 put，发现 ForwardingNode
  ├── 不阻塞等待
  └── helpTransfer() — 加入扩容，帮助处理其他段
```

**多线程协作扩容的好处**：
- 扩容速度随线程数线性增长
- 不阻塞其他线程的读写（帮忙扩容的线程完成后才返回）

### size() 的实现

```java
// JDK 7：统计所有 Segment 的 size（需要锁所有 Segment）
// JDK 8：LongAdder（Striped64）——无锁统计

// LongAdder 的核心思想
// 把一个 long 值分散到多个 cell 里
// 每个线程更新自己的 cell（无竞争）
// size() = base + 所有 cell 的值

base（CAS 更新，无竞争时用）
  ├── cell[0]
  ├── cell[1]
  ├── cell[2]
  └── ...

// 好处：多线程并发 add 时，各自更新不同的 cell，完全无锁
// 代价：size() 不保证 100% 精确（但实时性比 JDK 7 的「锁全 Segment」好得多）
```

---

## 正确使用方式

### ConcurrentHashMap vs 其他方案

```
需要线程安全的 Map？
├── 读多写少 → ConcurrentHashMap（推荐）
├── 高并发读写 → ConcurrentHashMap（推荐）
├── 需要排序 → ConcurrentSkipListMap（跳表实现，有序）
├── 低并发、简单同步 → Collections.synchronizedMap()
└── 不需要线程安全 → HashMap（不要画蛇添足）
```

### 正确处理 null 问题

```java
ConcurrentHashMap<String, String> map = new ConcurrentHashMap<>();

// ❌ 不允许 null key
map.put(null, "value");  // NullPointerException

// ❌ 不允许 null value
map.put("key", null);    // NullPointerException
```

**为什么禁止 null？** Doug Lea 的解释：并发场景下 `get(key)` 返回 null 有歧义——是 key 不存在，还是 value 本身是 null？如果允许 null value，需要 `containsKey()` 才能区分，增加了使用复杂度。索性禁止。

**替代方案**：用 Optional 或特殊 sentinel 值：
```java
map.put("key", Optional.empty());  // 用 Optional 表示可能不存在
```

### computeIfAbsent：线程安全的「懒加载」

```java
// ❌ 不是原子操作
if (!map.containsKey("key")) {
    map.put("key", expensiveCompute("key"));  // 可能重复计算
}

// ✅ 原子操作，线程安全
map.computeIfAbsent("key", k -> expensiveCompute(k));
```

`computeIfAbsent` 保证同一个 key 只会计算一次，多线程环境下也是安全的。

---

## 边界情况和坑

### 坑 1：组合操作不是原子的

```java
ConcurrentHashMap<String, Integer> map = new ConcurrentHashMap<>();

// ❌ 非原子操作
if (!map.containsKey("key")) {
    map.put("key", map.getOrDefault("key", 0) + 1);
}

// ✅ 原子操作
map.merge("key", 1, Integer::sum);

// ✅ 或用 computeIfAbsent
map.compute("key", (k, v) -> v == null ? 1 : v + 1);
```

**成因**：ConcurrentHashMap 只保证单个方法（put/get/remove）的原子性。多个方法组合时，中间可能被其他线程插入。

### 坑 2：迭代器是弱一致性的

```java
ConcurrentHashMap<String, String> map = new ConcurrentHashMap<>();
map.put("a", "1");

// 遍历同时另一个线程修改
for (String key : map.keySet()) {
    // 可能看到也可能看不到新元素
    // 不会抛 ConcurrentModificationException
}
```

**成因**：ConcurrentHashMap 的迭代器是弱一致性的——它反映的是创建迭代器时或之后的某个时刻的状态，不保证看到所有最新修改。这是性能和一致性的 trade-off。

### 坑 3：size() 不是精确的

```java
ConcurrentHashMap<String, String> map = new ConcurrentHashMap<>();

// 多线程并发 put/remove
// 此时 map.size() 的返回值只是近似值
// 不是完全精确的
```

**成因**：JDK 8 用 LongAdder 统计 size，多线程各自更新不同的 cell，sum 时可能有微小误差。但如果需要精确值，可以用 `mappingCount()`（返回 long）。

### 坑 4：JDK 7 的 ConcurrentHashMap 在 Java 8 代码中

```java
// JDK 7
ConcurrentHashMap<String, String> map = new ConcurrentHashMap<>(16, 0.75f, 16);
// 第三个参数是 concurrencyLevel（Segment 数量）

// JDK 8
ConcurrentHashMap<String, String> map = new ConcurrentHashMap<>(16, 0.75f, 16);
// 第三个参数仍然存在但已废弃，不再影响 Segment 数量（因为已经没有 Segment 了）
```

**迁移注意**：如果从 JDK 7 迁移到 JDK 8，不要依赖 concurrencyLevel 参数来控制并发度。JDK 8 的并发度由 table 大小决定。
