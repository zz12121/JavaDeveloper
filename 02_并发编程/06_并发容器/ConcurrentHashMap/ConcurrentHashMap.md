# ConcurrentHashMap 核心原理

## 这个问题为什么存在？

Hashtable 和 `Collections.synchronizedMap()` 的做法是：对整个 Map 加一把锁。任何线程做任何操作，都要先拿到这把锁。

这带来一个根本性问题：**读操作本来不需要互斥，却被锁住了。**

```
两个线程同时读不同 key：
  Thread A: get("key1") → 需要获取锁 ✗（不需要却要等）
  Thread B: get("key2") → 需要获取锁 ✗（和 Thread A 的 key 毫无关系）

结果：两个完全不冲突的操作，被同一把锁串行化了。
```

问题是：`Hashtable` 的锁粒度是「整个 Map」，而真正会冲突的，只是「同一个桶（bucket）里的写操作」。

所以问题的本质是：**如何把锁的粒度，缩小到「真正会冲突的最小范围」**。这就是 ConcurrentHashMap 要解决的核心问题。

---

## 它是怎么解决问题的？

### JDK 7：分段锁（Segment）

JDK 7 的做法是把一个大 Map 拆成 N 个小的 Segment，每个 Segment 是一把独立的 ReentrantLock。

```
ConcurrentHashMap（JDK 7）
├── Segment[0]  ← ReentrantLock，管一堆桶
│   ├── HashEntry[0] → HashEntry[1] → ...
│   └── ...
├── Segment[1]  ← 另一把锁
└── ...
```

**关键设计思想**：不同 Segment 的写操作互不干扰，最多支持「Segment 数量」个线程并发写。

但这个方法有局限：
- Segment 数量固定（默认 16），并发度无法动态扩展
- 每个 Segment 内部还是一把锁，同一个 Segment 内的写操作仍然串行

---

### JDK 8：CAS + synchronized（桶级别锁）

JDK 8 彻底重构了实现，锁粒度精确到「单个桶的头节点」。

```
Node[] table                 ← volatile 数组，保证可见性
├── [0] Node → Node → ...   ← 链表（或红黑树）
├── [1] Node               ← synchronized(这个节点)
├── [2] ForwardingNode     ← 扩容时的特殊标记
└── ...
```

**核心设计决策**：为什么用 `synchronized` 而不是 `ReentrantLock`？

不是因为性能（两者在 JDK 8 性能接近），而是因为：
1. `synchronized` 是 JVM 内置的，JIT 可以做更多优化（锁消除、锁粗化、偏向锁/轻量级锁升级）
2. `synchronized` 不需要手动释放，不会漏写 `unlock()`
3. 锁的粒度已经缩小到「一个桶头节点」，竞争极低，`synchronized` 的开销可以忽略

#### put() 的完整流程

```
put(key, value)
│
├── 1. 计算 hash，定位桶索引
│
├── 2. table == null？
│     是 → CAS 初始化 table（无锁）
│
├── 3. 桶 == null？
│     是 → CAS 放入新 Node（无锁，这是无竞争时的快速路径）
│
├── 4. 桶头节点 hash == MOVED（-1）？
│     是 → helpTransfer()，帮忙迁移数据（多线程协作扩容）
│
└── 5. synchronized(桶头节点)
       ├── 遍历链表（或红黑树）
       │     找到 key 相同 → 替换 value
       │     没找到 → 追加到链表末尾（尾插法，JDK 8 改了）
       └── 链表长度 >= 8 且 table.length >= 64
              → treeifyBin()，转红黑树
```

**为什么要有这么多条路径？**

因为设计目标是「尽量无锁」：
- 空桶插入：CAS（无锁）
- 桶不为空但无竞争：synchronized 范围极小（只锁一个桶头）
- 扩容时：多线程协作，不是单线程扛

#### get() 为什么不需要加锁

```
get(key)
│
├── 计算 hash，定位桶
├── 桶头节点匹配？→ 直接返回
├── 桶头节点 hash < 0？
│     → 是 ForwardingNode → 去新 table 里找
│     → 是红黑树节点 → TreeNode.find()
└── 否则遍历链表
```

**根本原理**：Node 的 `val` 和 `next` 都是 `volatile` 的。

```java
static class Node<K,V> {
    final int hash;
    final K key;
    volatile V val;           // ← 写线程写入后，读线程立即可见
    volatile Node<K,V> next;  // ← 链表结构变更也立即可见
}
```

`volatile` 的读在 x86 架构上，和普通的读性能几乎一样（不需要额外的内存屏障指令）。所以 get() 在高并发下和没有锁的单线程 HashMap 性能接近。

**这是整个设计的精髓**：读操作完全无锁，靠 volatile 保证可见性；只有真正有冲突的写操作，才需要加锁。

---

### size() 为什么是近似值

```
size() 不能遍历全表计数（太慢，且遍历过程中 table 还在变）

JDK 8 的做法（和 LongAdder 完全一致）：
  ├── baseCount：CAS 更新的基础计数（低并发时只用这个）
  └── CounterCell[]：高并发时，线程分散到不同的 CounterCell 里计数

最终 size = baseCount + Σ(CounterCell[i].value)
```

**为什么不做精确计数？**

因为 ConcurrentHashMap 的设计目标是「高并发读写的 Map」，要支持的是：多个线程同时 put、同时 get、同时 remove。在这种场景下，要做出精确、且和某个时刻的快照一致的 size()，代价极高（需要全局锁或者用快照隔离）。

而实际使用场景中，`size()` 的返回值几乎从来不需要精确——你关心的是「大概有多少」，而不是「此刻精确是 1000 还是 1001」。

如果真的需要精确计数，正确的做法是：用 `AtomicLong` 在每次插入/删除时精确增减，而不是靠遍历 Map 来计数。

---

## 它和相似方案的本质区别是什么？

### 和 Hashtable 的本质区别

| | Hashtable | ConcurrentHashMap（JDK 8） |
|--|-----------|-----------------------------|
| 锁粒度 | 整个 Map 一把锁 | 桶级别，不同桶的写不互斥 |
| 读操作 | 需要获取锁 | 无锁，volatile 读 |
| 写操作 | 全表互斥 | 只有同一个桶的写才互斥 |
| 扩容 | 单线程 | 多线程协作 |

本质区别：**是否承认「不同桶的操作不该互斥」**。Hashtable 不承认，所以全表一把锁；ConcurrentHashMap 承认，所以把锁粒度降到桶级别。

### 和 synchronizedMap 的本质区别

`synchronizedMap` 只是给所有操作套了一层 `synchronized`，本质上和 Hashtable 一样，只是锁的是传入的 Map 对象。

ConcurrentHashMap 的区别在于：**它从数据结构层面就为并发设计，而不是在普通 Map 外面套一层锁**。

---

## 正确使用方式

### 复合操作必须用原子方法

```java
ConcurrentHashMap<String, Integer> map = new ConcurrentHashMap<>();

// 错误：containsKey 和 put 之间，其他线程可以插进来
if (!map.containsKey("key")) {
    map.put("key", 1);  // 这里可能覆盖其他线程的写入
}

// 正确：putIfAbsent 是原子的
map.putIfAbsent("key", 1);

// 正确：computeIfAbsent 也是原子的，且只在 key 不存在时才计算 value
map.computeIfAbsent("key", k -> expensiveCompute(k));
```

**为什么 `computeIfAbsent` 要避免嵌套调用同一个 Map？**

JDK 8 的实现中，`computeIfAbsent` 会锁住当前桶。如果计算过程里又去操作同一个 Map（哪怕是不同 key），而那个 key 恰好在同一个桶里，就会造成死锁（自己等自己的锁）。

JDK 9 修复了这个问题，但写代码时仍然应该避免这种嵌套：

```java
// 危险：嵌套操作同一个 Map
map.computeIfAbsent("key1", k -> {
    return map.get("key2");  // 可能死锁（JDK 8）
});

// 安全：先算好，再放进去
Value v = expensiveCompute(key);
map.putIfAbsent(key, v);
```

### key 和 value 为什么不能是 null

```java
// HashMap 允许：
map.put("key", null);    // OK
map.put(null, "value");  // OK

// ConcurrentHashMap 不允许：
map.put("key", null);    // NullPointerException
map.put(null, "value");  // NullPointerException
```

**根本原因**：并发环境下，`get(key)` 返回 null 有两种可能的含义：
1. key 不存在
2. key 存在，但 value 就是 null

在单线程的 HashMap 里，你可以先用 `containsKey()` 区分这两种情况。但在并发环境下，`containsKey()` 和 `get()` 之间，其他线程可能插入或删除了这个 key，你永远无法得到确定的答案。

ConcurrentHashMap 选择：**不允许 value 为 null，这样 `get()` 返回 null 就 unambiguously 表示「key 不存在」**。

（key 不能为 null 是历史原因：Hashtable 就不允许，ConcurrentHashMap 沿用了这个设计。）

---

## 边界情况和坑

### 坑 1：size() 不是精确的

```java
// 不要这样写：
if (map.size() == 0) {
    // 在并发环境下，这一刻 size 可能是 0，但下一刻就不是了
}

// 正确做法：
if (!map.isEmpty()) {  // isEmpty() 同样不是精确的，但语义比 size()==0 更合适
    ...
}
```

**成因**：size() 是高并发下的近似值（baseCount + CounterCell 数组的和），在调用 size() 和返回结果之间，可能有其他线程正在修改 Map。这是设计上的有意取舍，不是 bug。

### 坑 2：遍历时其他线程可以并发修改

```java
// 这是正确的，ConcurrentHashMap 的迭代器是弱一致性的
for (Map.Entry<String, Integer> e : map.entrySet()) {
    // 遍历过程中，其他线程的 put/remove 不会影响这次遍历
    // 但遍历到的数据，不一定是「这一刻」Map 的完整快照
}
```

**成因**：ConcurrentHashMap 的迭代器是「弱一致性」的——它反映的是迭代器创建时，Map 的一个瞬时状态。之后 Map 的修改，迭代器可能看到，也可能看不到。这是为了避免遍历时需要全局锁。

如果你需要强一致性的遍历，正确的做法是：**先克隆，再遍历**（但注意克隆本身也有成本）：

```java
// 强一致性遍历（先快照，再遍历）
Map<String, Integer> snapshot = new HashMap<>(map);  // 全量复制
for (Map.Entry<String, Integer> e : snapshot.entrySet()) {
    // 这里的快照是强一致的
}
```

### 坑 3：扩容期间性能抖动

ConcurrentHashMap 扩容时，数据要从旧 table 搬到新 table。JDK 8 支持多线程协作扩容（`helpTransfer`），但搬迁数据本身是有代价的——在扩容期间，部分 put() 调用会额外承担搬迁工作，导致延迟增加。

**应对方法**：
- 初始化时，通过构造函数给一个合理的初始容量，避免频繁扩容
- `concurrencyLevel` 参数在 JDK 8 里已经没有实际意义（锁粒度已经和这个无关了），不要迷信它

---

