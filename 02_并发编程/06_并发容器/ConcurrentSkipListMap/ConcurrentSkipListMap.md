# ConcurrentSkipListMap

> ConcurrentSkipListMap 是 Java 中唯一的并发有序 Map。它基于跳表（SkipList）实现，在保证线程安全的同时提供了按键排序和范围查询的能力。理解跳表的结构和并发改造方式，是理解"并发数据结构设计"的绝佳案例。

---

## 这个问题为什么存在？

### ConcurrentHashMap 的局限

```
ConcurrentHashMap 解决了高并发 Map 的问题，但它有一个根本性限制：

→ 不保证顺序。key 的迭代顺序取决于 hash 值和桶的位置，每次可能不同

很多业务场景需要"有序 Map"：
- 排行榜：按分数排序取 Top N
- 时间线：按时间戳排序，查询某个时间范围的数据
- 滑动窗口：按时间范围统计指标
- 区间查询：age > 18 && age < 30

TreeMap 可以排序，但不是线程安全的
Collections.synchronizedMap(new TreeMap<>()) 性能差（全表锁）

需要的是：并发安全 + 有序 + 高性能
→ ConcurrentSkipListMap
```

---

## 它是怎么解决问题的？

### 跳表（SkipList）原理

跳表是一种基于有序链表的"快速通道"数据结构，通过多层索引实现 O(log n) 的查找效率。

```
构建过程：从底层有序链表开始，随机向上层"提拉"节点

初始有序链表（Level 0）：
1 → 3 → 5 → 7 → 9

随机决定每个节点是否出现在上层（50% 概率）：
Level 2:  1 ──────────────────────── 9
Level 1:  1 ──── 3 ─────────────── 9
Level 0:  1 → 3 → 5 → 7 → 9

每层都是有序链表，上层是下层的"快速通道"，跨度更大
```

#### 查找过程

```
查找 key = 7：

Level 2: 1 → 9（7 < 9，往下走）
           ↓
Level 1: 1 → 3 → 9（7 < 9，往下走）
              ↓
Level 0: 1 → 3 → 5 → 7 ✓ 找到！

步骤数 = 3，而普通链表需要 4 步
数据量大时差距更明显：100 万个元素，链表要 50 万步（平均），跳表只要 ~20 步
```

#### 为什么用跳表而不是红黑树？

```
              跳表                    红黑树
──────────────────────────────────────────────────
插入/删除/查找  O(log n)               O(log n)
实现复杂度      简单（链表 + 随机层数）   复杂（旋转 + 变色 + 6种情况）
并发友好度      ✅ 局部修改，影响少节点    ❌ 旋转可能重平衡大量节点
范围查询        ✅ 链表天然支持          需要中序遍历
内存开销        较高（多层指针）          较低
确定性          随机层数（概率保证）       确定性平衡

关键区别在并发：
跳表插入一个节点，只修改相邻节点的指针（局部操作）
红黑树插入可能触发旋转，涉及多个节点（大范围操作）
→ 跳表更容易实现无锁并发
```

### 并发实现原理

```
ConcurrentSkipListMap 的并发策略：

核心数据结构：
  Node<K,V>[] head  —  每层链表的头节点
  volatile long     —  跳表的版本号（用于并发控制）

插入过程（CAS 无锁）：
1. 从最高层开始，逐层找到插入位置的前驱节点
2. 在最底层（Level 0）插入新节点
3. 随机决定新节点的层数
4. 从 Level 1 开始逐层插入（CAS 更新前驱节点的 next 指针）

  Before:    ... → prev → next → ...
  After:     ... → prev → newNode → next → ...
                    ↑ CAS(prev.next, next, newNode)

如果 CAS 失败（其他线程已经修改了 prev.next）：
→ 重新遍历找到新的前驱节点，重试 CAS（自旋）

删除过程（逻辑删除 + 物理删除两阶段）：
1. 逻辑删除：CAS 将节点的 value 设为 null（标记为已删除）
2. 物理删除：从底向上，CAS 将前驱节点的 next 跳过已删除节点

为什么要两阶段？
→ 直接 CAS 删除 next 指针，可能影响正在遍历的线程
→ 先标记（value = null），让其他线程知道这个节点"即将消失"
→ 然后物理删除，不影响正确性
```

```
和 ConcurrentHashMap 的对比：

                    ConcurrentSkipListMap      ConcurrentHashMap
──────────────────────────────────────────────────────────────
底层结构            跳表（多层链表）            数组 + 链表/红黑树
排序                ✅ 按 key 自然排序           ❌ 无序
范围查询            ✅ subMap/headMap/tailMap   ❌ 不支持
查找复杂度          O(log n)                   O(1)（平均）
插入复杂度          O(log n)                   O(1)（平均）
内存开销            较高（多层指针）            较低
CAS 粒度            节点级别                    桶级别
null key/value      ❌ 不允许                   ❌ 不允许
```

---

## 核心 API

### 基本操作

```java
ConcurrentSkipListMap<String, Integer> map = new ConcurrentSkipListMap<>();

// 基本操作（和普通 Map 一样）
map.put("banana", 2);
map.put("apple", 1);
map.put("cherry", 3);

// 按自然顺序遍历（字典序）
map.forEach((k, v) -> System.out.println(k + ": " + v));
// apple: 1, banana: 2, cherry: 3

// 并发安全操作
map.putIfAbsent("apple", 99);     // 已存在，不覆盖
map.replace("banana", 20);         // 替换
map.computeIfAbsent("date", k -> 4);  // 不存在时计算
```

### 有序操作（SkipListMap 独有能力）

```java
ConcurrentSkipListMap<Integer, String> scores = new ConcurrentSkipListMap<>();
scores.put(85, "Alice");
scores.put(92, "Bob");
scores.put(78, "Charlie");
scores.put(95, "Diana");
scores.put(88, "Eve");

// 首尾操作
scores.firstKey();    // 78（最小 key）
scores.lastKey();     // 95（最大 key）
scores.pollFirstEntry();  // 移除并返回最小的 entry
scores.pollLastEntry();   // 移除并返回最大的 entry

// 范围查询
ConcurrentNavigableMap<Integer, String> topStudents = scores.subMap(90, true, 100, true);
// {92=Bob, 95=Diana}（90~100 分的学生）

ConcurrentNavigableMap<Integer, String> belowAverage = scores.headMap(80, true);
// {78=Charlie}（80 分以下的）

ConcurrentNavigableMap<Integer, String> aboveAverage = scores.tailMap(85, true);
// {85=Alice, 88=Eve, 92=Bob, 95=Diana}（85 分及以上的）
```

### 实战：排行榜系统

```java
public class Leaderboard {
    // 按分数倒序（Comparator.reverseOrder）
    private final ConcurrentSkipListMap<Integer, String> board =
        new ConcurrentSkipListMap<>(Comparator.reverseOrder());

    public void updateScore(String player, int newScore) {
        // 移除旧分数（如果有）
        board.values().remove(player);
        // 添加新分数
        board.put(newScore, player);
        // 注意：如果有同分玩家，后 put 的会覆盖先 put 的
        // 生产环境应用 Map<Integer, Set<String>>
    }

    // 获取 Top N
    public List<Map.Entry<Integer, String>> getTopN(int n) {
        return board.entrySet().stream()
            .limit(n)
            .collect(Collectors.toList());
    }

    // 获取某个分数段的玩家
    public List<Map.Entry<Integer, String>> getByScoreRange(int min, int max) {
        return board.subMap(max, true, min, true).entrySet().stream()
            .collect(Collectors.toList());
    }
}
```

### 实战：滑动窗口统计

```java
public class SlidingWindowCounter {
    // 按时间戳排序
    private final ConcurrentSkipListMap<Long, Long> window =
        new ConcurrentSkipListMap<>();

    public void record(long timestamp, long count) {
        window.put(timestamp, window.getOrDefault(timestamp, 0L) + count);
    }

    // 统计最近 N 分钟的数据
    public long sumLastMinutes(int minutes) {
        long cutoff = System.currentTimeMillis() - minutes * 60_000L;
        // 移除过期数据
        window.headMap(cutoff, false).clear();
        // 统计窗口内的总和
        return window.values().stream().mapToLong(Long::longValue).sum();
    }

    // 获取当前窗口大小
    public int windowSize() {
        return window.size();
    }
}
```

---

## 和相似方案的区别

### ConcurrentSkipListMap vs TreeMap

```
                    ConcurrentSkipListMap    TreeMap
──────────────────────────────────────────────────────
线程安全              ✅ CAS 无锁              ❌
排序                  ✅                      ✅
范围查询              ✅                      ✅
查找性能              O(log n)               O(log n)
null key/value        ❌                     ✅ 允许 null value
迭代器                弱一致性                fail-fast
性能（单线程）         略慢（CAS 开销）        略快（无并发控制）
```

### ConcurrentSkipListSet

```java
// ConcurrentSkipListSet 内部就是 ConcurrentSkipListMap
// value 固定为 Boolean.TRUE（和 newKeySet 类似的设计）

ConcurrentSkipListSet<String> set = new ConcurrentSkipListSet<>();
// 等价于：
ConcurrentSkipListMap<String, Boolean> map = new ConcurrentSkipListMap<>();

// 有序 Set 的典型用途：
// - 去重且需要排序的场景
// - 延迟队列中按时间排序的任务集合
// - 需要范围查询的集合
```

---

## 正确使用方式

### 适用场景

```
✅ 适合：
- 需要按键排序的并发 Map
- 需要范围查询（排行榜、时间线、滑动窗口）
- 读多写少的有序数据
- 需要快速获取 min/max 的场景

❌ 不适合：
- 不需要排序 → ConcurrentHashMap 性能更好
- 大量写操作 → 跳表插入 O(log n) 且有 CAS 重试开销
- 需要存 null key/value → 不支持
```

### 性能调优

```
1. 自定义 Comparator
   → 默认按 key 自然排序
   → 如果 key 是自定义类，必须实现 Comparable 或传入 Comparator

2. 调整期望并发级别（基本不需要）
   → 构造函数可以指定 expected size 和 parallelism
   → 但跳表不像 CHM 有分段锁，parallelism 影响不大

3. 注意 GC
   → 删除操作是逻辑删除 + 物理删除
   → 高并发删除场景下，被标记删除的节点可能短暂存活
   → GC 压力比 CHM 略大
```

---

## 边界情况和坑

### 坑 1：同分玩家覆盖

```java
// 反例：排行榜中同分玩家会被覆盖
ConcurrentSkipListMap<Integer, String> rank = new ConcurrentSkipListMap<>();
rank.put(100, "Alice");
rank.put(100, "Bob");  // Alice 被覆盖了！

// 正确做法：value 用集合
ConcurrentSkipListMap<Integer, Set<String>> rank = new ConcurrentSkipListMap<>();
rank.computeIfAbsent(100, k -> new ConcurrentSkipListSet<>()).add("Alice");
rank.computeIfAbsent(100, k -> new ConcurrentSkipListSet<>()).add("Bob");
// 100 = [Alice, Bob] ✓
```

### 坑 2：subMap 返回的是视图

```java
ConcurrentSkipListMap<Integer, String> map = new ConcurrentSkipListMap<>();
map.put(1, "A"); map.put(2, "B"); map.put(3, "C");

ConcurrentNavigableMap<Integer, String> sub = map.subMap(1, 3);
// sub 是 map 的视图，不是副本
sub.put(2, "B2");  // 会修改原始 map！
// map.get(2) == "B2"

// 修改原始 map 也影响视图
map.put(2, "B3");
// sub.get(2) == "B3"

// 如果需要独立副本：
Map<Integer, String> copy = new HashMap<>(sub);
```

### 坑 3：Comparator 和 Comparable 冲突

```java
// 如果 key 实现了 Comparable，又传了 Comparator
// Comparator 优先
ConcurrentSkipListMap<String, Integer> map =
    new ConcurrentSkipListMap<>(Comparator.reverseOrder());
map.put("a", 1);
map.put("z", 2);
// 遍历顺序：z, a（倒序）
```

---

