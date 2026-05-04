# HashMap

> HashMap 用哈希函数把键映射到数组索引，实现 O(1) 平均查找。JDK 8 引入红黑树解决退化问题，是 Java 中使用最频繁的集合实现，也是面试最高频的知识点。

---

## 这个问题为什么存在？

数组的痛点：查找要 O(n)（二分要 O(log n) 但要求有序）。

哈希表的目标：**把「关键字 → 存储位置」的映射直接算出来**，查找变 O(1)。

这个想法很直观，但实现时有三道硬题：
1. **哈希冲突**：不同 key 算出同一个索引怎么办？
2. **容量固定**：数组满了怎么办？
3. **极端退化**：所有 key 都落到同一个桶里，退化为链表，O(1) 变 O(n) 怎么办？

HashMap 的答案：**链表法解决冲突 + 扩容解决满桶 + 红黑树解决退化**。

---

## 它是怎么解决问题的？

### 哈希函数：扰动函数

```java
// JDK 8 源码
static final int hash(Object key) {
    int h;
    return (key == null) ? 0 : (h = key.hashCode()) ^ (h >>> 16);
}

// 计算 bucket 索引
int index = (n - 1) & hash
```

**两步哈希的设计原因**：

```
第一步：h = key.hashCode()
  → 返回 int（32 位），但对象的 hashCode() 低位信息通常不够随机
  → 高位是内存地址相关，低位更可能重复

第二步：h ^ (h >>> 16)
  → 把高 16 位异或到低 16 位，让低位也混合了高位信息
  → "扰动函数"（perturbation），让 hash 分布更均匀

第三步：(n - 1) & hash
  → n 是 2 的幂，n-1 的二进制全是 1，相当于取模
  → 位运算比 % 快得多
```

**为什么容量必须是 2 的幂？** 因为只有 2 的幂次方，`n-1` 的二进制才全是 1，`& hash` 才等价于 `% n`，且位运算更快。

### 底层数据结构演变

```
JDK 7：数组 + 链表（Entry[]，头插法）
JDK 8+：数组 + 链表 + 红黑树（Node[] → TreeNode，尾插法）
```

**为什么 JDK 8 要引入红黑树？**
```
极端情况：所有 key 的 hashCode() 相同（或设计不佳）
  → 全部落到同一个桶里
  → 链表长度很长
  → 查找从 O(1) 退化为 O(n)

红黑树：保持 O(log n) 查找
  → 链表长度 > 8 → 树化
  → 链表长度 < 6 → 退化回链表（避免在临界点反复树化/退化）
```

**为什么树化阈值是 8？**
```
泊松分布计算（hash 均匀分布时）：
  P(链表长度 = 0) = 0.6065
  P(链表长度 ≤ 6) = 0.9999
  P(链表长度 ≥ 8) = 0.00000006

  → 99.9999% 的链表长度 ≤ 8
  → 树化只在 hash 实现很差的极端情况下触发
  → 阈值 8 是「正常情况下永远不触发」的临界值
```

### put 流程

```
put(key, value)
  ├── 1. 计算 hash(key)
  ├── 2. 计算 index = (n-1) & hash
  ├── 3. tab[index] 为空？
  │     ├── 是 → 直接插入新 Node
  │     └── 否 → 遍历链表/红黑树
  │           ├── 找到相同 key（hash 相同 && equals 为 true）
  │           │     └── 覆盖 value，返回旧 value
  │           └── 没找到 → 尾插（链表）/ 插入红黑树
  │                 └── 链表长度 > 8 → treeifyBin()
  ├── 4. size++ → size > threshold？
  │     └── 是 → resize()，容量翻倍
  └── 5. afterNodeInsertion()（给 LinkedHashMap 留的钩子）
```

### resize 机制

触发条件：`size > threshold`（threshold = capacity × loadFactor）

```java
// JDK 8 扩容核心逻辑
final Node<K,V>[] resize() {
    // 1. 新容量 = 旧容量 × 2（初始 16 → 32 → 64...）
    int newCap = oldCap << 1;
    int newThr = newCap * loadFactor;

    // 2. 分配新数组
    Node<K,V>[] newTab = (Node<K,V>[]) new Node[newCap];

    // 3. 迁移元素
    for (int j = 0; j < oldCap; ++j) {
        Node<K,V> e;
        if ((e = oldTab[j]) != null) {
            // 链表拆分：看 hash 的第 (log2(旧容量)) 位
            if ((e.hash & oldCap) == 0) {
                // 该位为 0 → 留在原位置
                loTail.next = e;
            } else {
                // 该位为 1 → 移到「原位置 + 旧容量」
                hiTail.next = e;
            }
        }
    }
}
```

**JDK 7 vs JDK 8 扩容对比**：

| 维度 | JDK 7 | JDK 8 |
|------|-------|-------|
| 插入方式 | 头插法（会反转链表顺序）| 尾插法 |
| 扩容时 rehash | 每个元素重新算 hash | 看某一位是 0 还是 1，无需重新算 |
| 并发问题 | 头插法 + 多线程 → **链表环形引用 → 死循环** | 尾插法解决了环形引用（但 HashMap 仍不是线程安全的）|

**JDK 8 扩容的「位判断」优化**：
```
假设旧容量 16（二进制 10000），扩容到 32（二进制 100000）

迁移某个节点时，只看 hash 的第 5 位（log2(16) = 4，即从 0 数第 5 位）：
  该位为 0 → 新索引 = 旧索引（在低半区）
  该位为 1 → 新索引 = 旧索引 + 旧容量（在高半区）

例：旧索引 5，hash 第 5 位为 1
  新索引 = 5 + 16 = 21
```

---

## 深入原理

### 负载因子的 trade-off

```
loadFactor = 0.75（HashMap 默认值）

0.5 → 空间利用率低，但碰撞少，查找快
0.75 → 综合最优（时间与空间的平衡点）
1.0 → 空间利用率高，但碰撞多，链表长，查找退化
```

**为什么是 0.75？** 这是一个经验值。泊松分布的计算显示：当负载因子为 0.75 时，哈希碰撞的概率在可控范围内。再高的话，碰撞概率急剧上升。

### 为什么 null 可以作为 HashMap 的 key？

```java
// HashMap 允许一个 null key
map.put(null, "value");  // ✅
map.put(null, "value2"); // ✅ 覆盖

// 源码：hash(null) 返回 0，固定放在 index = 0 的桶里
static final int hash(Object key) {
    return (key == null) ? 0 : (h = key.hashCode()) ^ (h >>> 16);
}
```

**但 ConcurrentHashMap 不允许 null key**，因为多线程环境下 `get(key) == null` 有歧义：是 key 不存在，还是 value 本身是 null？Doug Lea 选择禁止 null 来消除歧义。

### HashMap 的线程安全问题

```java
// 场景 1：并发 put 导致数据丢失
// 两个线程同时 put 到同一个空桶，都认为桶为空，后写入的覆盖先写入的

// 场景 2：JDK 7 并发 resize 导致死循环
// 多线程同时扩容，头插法反转链表顺序，可能导致环形引用
// JDK 8 用尾插法解决了环形引用，但仍有数据丢失等问题

// 结论：HashMap 不是线程安全的，并发场景用 ConcurrentHashMap
```

### HashMap 内存布局

```
每个 Node 的内存开销（64 位 JVM）：
  对象头：16 bytes（mark word + class pointer）
  hash：4 bytes
  key 引用：8 bytes
  value 引用：8 bytes
  next 引用：8 bytes
  对齐填充：4 bytes
  总计：约 48 bytes per entry

HashMap 本身：
  对象头：16 bytes
  table 引用：8 bytes
  size/int/threshold 等字段：~20 bytes
  总计：约 48 bytes
```

大数据量场景（> 1000 万条），HashMap 的内存开销不可忽视，需要考虑分库分表或专门的 KV 存储。

---

## 正确使用方式

### 初始化容量计算

```java
// ❌ 默认容量 10，要经历多次扩容才能达到最终大小
Map<String, String> map = new HashMap<>();

// ✅ 预估元素数量，避免扩容
// 公式：capacity = 期望元素数 / 负载因子 + 1
int expectedSize = 1000;
int capacity = (int) (expectedSize / 0.75f) + 1;
Map<String, String> map = new HashMap<>(capacity);
```

### 自定义对象作为 key

```java
class Person {
    String name;
    int age;

    @Override
    public boolean equals(Object o) {
        if (this == o) return true;
        if (!(o instanceof Person)) return false;
        Person person = (Person) o;
        return age == person.age && Objects.equals(name, person.name);
    }

    @Override
    public int hashCode() {
        return Objects.hash(name, age);
    }
}
```

**规则**：
1. **重写 equals 必须重写 hashCode**
2. **相等的对象必须有相等的 hashCode**（反过来不要求）
3. **参与 equals 比较的字段必须都参与 hashCode 计算**
4. **存入 Map 后不要修改 key 的字段**（否则 hashCode 变了，找不到了）

### 不可变 key 最佳实践

```java
// 最佳实践：用不可变对象作为 key
record PersonKey(String name, int age) {}  // Java 14+
// record 自动生成 equals/hashCode/toString，且字段不可变

// 或用 final 字段
public final class PersonKey {
    private final String name;
    private final int age;
    // 只有 getter，没有 setter
    // 构造后字段不可变 → hashCode 不会变
}
```

### HashMap vs 其他 Map 实现的选择

```
需要键值映射？
├── 线程安全？
│   ├── 高并发 → ConcurrentHashMap
│   └── 低并发 → Collections.synchronizedMap()
├── 需要保持插入顺序？ → LinkedHashMap
├── 需要按 key 排序？ → TreeMap
├── 需要 LRU 淘汰？ → LinkedHashMap(accessOrder=true)
└── 普通场景 → HashMap（默认选这个）
```

---

## 边界情况和坑

### 坑 1：只重写 equals 不重写 hashCode

```java
class Person {
    String name;
    @Override public boolean equals(Object o) {
        return o instanceof Person && ((Person) o).name.equals(name);
    }
    // 忘了 hashCode！
}

Map<Person, String> map = new HashMap<>();
Person p = new Person("Alice");
map.put(p, "value");
map.get(p);  // 可能返回 null！
```

**成因**：`hashCode()` 继承自 `Object`，默认返回内存地址。两次 `new Person("Alice")` 内存地址不同 → `hashCode()` 不同 → 哈希到不同的桶 → `get` 时在正确的桶里找不到。

### 坑 2：修改 key 后导致内存泄漏

```java
Map<List<Integer>, String> map = new HashMap<>();
List<Integer> key = new ArrayList<>(List.of(1, 2, 3));
map.put(key, "value");
key.add(4);  // 修改了 key！
map.get(key);  // null —— 找不到了
// 但 key 对应的 entry 还在 HashMap 里，无法被 GC → 内存泄漏
```

**成因**：修改 key 导致 `hashCode()` 改变，原来的 entry 还在旧桶里，新的 `hashCode` 对应的桶里找不到。这个 entry 永远不会被访问到，也无法被 GC。

### 坑 3：size 为 1 的 HashMap

```java
Map<String, String> map = new HashMap<>(1);  // 指定容量 1
map.put("a", "1");
map.put("b", "2");  // 触发扩容
```

**成因**：`new HashMap<>(1)` 设置的是初始容量为 1，但实际 table 大小是 `tableSizeFor(1) = 1`。放入第一个元素后 `size > threshold` 立即触发扩容。

如果确定只放少量元素，不如直接用容量公式计算：
```java
int capacity = (int) Math.ceil(expectedSize / 0.75);
```

### 坑 4：负载因子不是越高越好

```
loadFactor = 0.9 的问题：
- 碰撞概率急剧上升
- 链表变长，查找从 O(1) 退化为 O(n)
- 在极端 hashCode 实现下（所有 key 都落在同一桶），性能退化到 O(n)
- 扩容频率降低节省的时间，被碰撞查找浪费的时间抵消，甚至更差
```

### 坑 5：HashMap 的 Integer key 缓存问题

```java
Map<Integer, String> map = new HashMap<>();
map.put(1, "one");
map.put(new Integer(1), "one");  // JDK 5+ 自动装箱

// Integer 缓存范围 [-128, 127]
Integer a = 100;
Integer b = 100;
System.out.println(a == b);  // true（同一个对象）
Integer c = 200;
Integer d = 200;
System.out.println(c == d);  // false（不同对象，但 equals 为 true）
```

这对 HashMap 的 `get` 没有影响（HashMap 用 `equals` 比较），但如果用 `==` 比较 key 就会出 bug。**永远用 `equals` 比较 Integer**。
