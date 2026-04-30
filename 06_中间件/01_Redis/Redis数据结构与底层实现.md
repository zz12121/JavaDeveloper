# Redis数据结构与底层实现

## 这个问题为什么存在？

> 你用Redis就是 `SET key value`、`GET key`，好像很简单。  
> 但面试官问："Redis的ZSet为什么用跳表而不是红黑树？""Hash是什么原因会从ZipList变成HashTable？"——答不上来。

Redis的"快"，**核心在于数据结构的选择**。不同的数据类型，在不同的数据量下，会用不同的底层实现（编码方式）。理解这些，才能：

1. **正确选型**：什么场景用Hash，什么场景用String
2. **性能调优**：为什么同一个命令，数据量不同，性能差异很大
3. **回答面试深挖**：从API层面上升到原理层面

---

## 它是怎么解决问题的？

### 核心机制：Redis的6种顶层数据结构

Redis有6种顶层数据结构（用户能看到的）：

| 顶层数据结构 | 底层实现（编码方式） | 说明 |
|-------------|---------------------|------|
| String | SDS（Simple Dynamic String） | 简单动态字符串 |
| List | ZipList（小数据） / QuickList（大数据） | 压缩列表 / 快速列表 |
| Hash | ZipList（小数据） / HashTable（大数据） | 压缩列表 / 哈希表 |
| Set | IntSet（整数且少量） / HashTable（其他） | 整数集合 / 哈希表 |
| ZSet | ZipList（小数据） / SkipList + HashTable（大数据） | 压缩列表 / 跳表+字典 |
| Bitmap/HyperLogLog/GeoSpatial | 基于String或ZSet实现 | 特殊编码 |

**关键点**：Redis会根据数据量**自动切换**底层实现。这就是`OBJECT ENCODING key`命令能看到不同编码的原因。

---

### String的底层实现：SDS（Simple Dynamic String）

**问题**：C语言的字符串（`char*`）有什么问题？

```c
// C语言字符串
char* str = "hello";
// 问题1：获取长度需要遍历（O(n)）
// 问题2：不支持二进制数据（不能包含\0）
// 问题3：字符串拼接容易造成缓冲区溢出
```

**SDS的解决思路**：

```
SDS结构（简化）
┌──────────┬──────────┬──────────┬──────────┐
│ len (4B)│ free (4B)│ buf[]    │ '\0'     │
│ 字符串长度 │ 空闲空间  │ 实际数据  │ 结尾符   │
└──────────┴──────────┴──────────┴──────────┘
```

**SDS相比C字符串的优势**：

| 维度 | C字符串 | SDS |
|------|---------|-----|
| 获取长度 | O(n)，需要遍历 | O(1)，直接读len |
| 二进制安全 | ❌ 不能包含`\0` | ✅ 可以包含任意二进制数据 |
| 缓冲区溢出 | ❌ 拼接可能溢出 | ✅ 自动检查空间（先扩容再写） |
| 内存分配次数 | 每次修改都可能重新分配 | 空间预分配 + 惰性释放 |

**SDS的空间预分配（优化写性能）**：

```
增长操作（APPEND）：
1. 检查free空间是否足够
2. 不够 → 扩容
   - 新长度 < 1MB：扩容后free = len（翻倍）
   - 新长度 >= 1MB：扩容后free = 1MB（避免浪费）
3. 修改len和free
```

**SDS的惰性空间释放（优化内存回收）**：

```
缩短操作（SETRANGE部分覆盖）：
1. 不立即释放多余空间
2. 只是修改len，多余空间记录到free中
3. 下次增长时可以直接用free空间（减少重新分配）
```

---

### List的底层实现：ZipList → QuickList

**问题**：List（列表）需要支持双端插入/删除（LPUSH/RPUSH/LPOP/RPOP），该用什么数据结构？

**小数据量时：ZipList（压缩列表）**

```
ZipList结构
┌──────┬──────┬──────┬──────┬──────┬──────┬──────┐
│ zlbytes│ zltail│ zllen │ entry1│ entry2│ ...  │ zlend │
│ (4B)  │ (4B)  │ (2B)  │        │        │       │ (1B) │
│ 总字节数 │ 尾节点  │ 节点数  │        │        │       │ 0xFF │
│         │ 偏移量  │        │        │        │       │       │
└──────┴──────┴──────┴──────┴──────┴──────┴──────┘

entry结构（每个元素）
┌──────┬──────┬──────┐
│ prevlen│ encoding│ data  │
│ (1-5B)│ (1-5B) │       │
│ 前节点  │ 数据类型 │ 实际   │
│ 长度   │ 和长度  │ 数据   │
└──────┴──────┴──────┘
```

**ZipList的优势**：
- **内存连续**：所有元素放在一块连续内存中，减少内存碎片
- **节省空间**：小整数用1字节编码，不需要指针
- **缓存友好**：连续内存，CPU缓存命中率高

**ZipList的问题**：
- **插入/删除需要重新分配内存**（因为内存连续）
- **查找需要遍历**（O(n)）

**大数据量时：QuickList（快速列表）**

Redis 3.2之后，List的底层实现从ZipList改为QuickList。

```
QuickList结构
┌─────────┐    ┌─────────┐    ┌─────────┐
│ quicklist│───→│ ziplist │───→│ ziplist │
│ (元数据)  │    │ (节点1)  │    │ (节点2)  │
└─────────┘    └─────────┘    └─────────┘
                 │                   │
                 ↓                   ↓
               [entry1,             [entry1,
                entry2,              entry2,
                ...]                 ...]
```

**QuickList的设计思想**：
- **ZipList的升级版**：把多个ZipList通过双向链表连接起来
- **兼顾优点**：既有ZipList的内存连续性（缓存友好），又有链表的插入/删除效率
- **可配置**：每个ZipList的大小可以通过`list-max-ziplist-size`配置

---

### Hash的底层实现：ZipList → HashTable

**小数据量时：ZipList**

```
ZipList存储Hash
┌──────┬──────┬──────┬──────┬──────┬──────┐
│ zlbytes│ ...  │ "name" │ "Tom"  │ "age"  │ "26"   │
└──────┴──────┴──────┴──────┴──────┴──────┘
说明：key和value作为两个相邻entry放在ZipList中
```

**什么时候从ZipList转HashTable？**

```bash
# 配置参数
hash-max-ziplist-entries 512  # 元素数超过512，转HashTable
hash-max-ziplist-value 64    # 任意元素的value超过64字节，转HashTable
```

**大数据量时：HashTable（哈希表）**

```
HashTable结构
┌────────────┐
│ dict       │
│ ├── ht[0]  │  ← 主哈希表
│ ├── ht[1]  │  ← 扩容时的备用哈希表
│ └── rehashidx │ ← 渐进式rehash的进度
└────────────┘

ht[0]结构
┌────────────────┐
│ table (数组)    │
│ [0] → entry1   │
│ [1] → NULL     │
│ [2] → entry2 → entry3  │ ← 链式冲突解决
│ ...            │
└────────────────┘
```

**渐进式rehash（重点）**：

```
问题：一次性rehash（把ht[0]的所有元素搬到ht[1]）会阻塞很久

解决：渐进式rehash
1. 扩容时，先分配ht[1]（大小为ht[0]的2倍）
2. 设置rehashidx = 0（开始rehash）
3. 每次对Hash的增删改查操作，顺便搬移ht[0][rehashidx]桶的所有元素到ht[1]
4. rehashidx++，直到ht[0]全部搬完
5. 释放ht[0]，把ht[1]设为ht[0]，ht[1]清空

优点：把大量搬移工作分摊到每次操作中，避免阻塞
```

---

### Set的底层实现：IntSet → HashTable

**整数且少量时：IntSet（整数集合）**

```
IntSet结构
┌─────────┬─────────┬─────────┬─────────┬─────────┐
│ encoding │ length  │ elem1   │ elem2   │ elem3   │
│ (4B)    │ (4B)    │ (1/2/4/8│ (同左)  │ (同左)  │
│          │          │  B)     │         │         │
└─────────┴─────────┴─────────┴─────────┴─────────┘

说明：
- encoding：所有元素用几位存储（2字节/4字节/8字节）
- 如果插入一个大于当前encoding的元素 → 升级（把所有元素转成更大的encoding）
- 不支持降级（一旦升级，不回退）
```

**IntSet的优势**：
- **节省内存**：只用必要的位数存储
- **查找快**：有序数组，可以用二分查找（O(log n)）

**非整数或大量时：HashTable**

```
用HashTable存储Set：
- key = 元素值
- value = NULL（只用到key，不存value）
```

---

### ZSet的底层实现：ZipList → SkipList + HashTable

**小数据量时：ZipList**

```
ZipList存储ZSet（有序集合）
┌──────┬──────┬──────┬──────┬──────┬──────┬──────┐
│ ...  │ "Tom"  │ 85.0  │ "Jerry"│ 92.5  │ ...  │
└──────┴──────┴──────┴──────┴──────┴──────┴──────┘
说明：member和score作为两个相邻entry，按score排序
```

**大数据量时：SkipList（跳表）+ HashTable**

```
SkipList结构（多层有序链表）
┌───┐
│ L3│  →  →  →  →  →  →  →  →  │ （稀疏层，快速跳跃）
├───┤
│ L2│  →  →     →  →     →  →     │ （中间层）
├───┤
│ L1│  →  →  →  →  →  →  →  →  │ （密集层，相邻节点都连接）
├───┤
│ L0│  →  →  →  →  →  →  →  →  │ （最密层，所有节点）
└───┘
     1    2    3    4    5    6    7    8

查找过程（找值为6的节点）：
1. 从L3开始，1 → 5（下一步8超了，下降一层）
2. 从L2的5开始，5 → 7（下一步超了，下降一层）
3. 从L1的5开始，5 → 6（找到！）
平均时间复杂度：O(log n)
```

**为什么用SkipList而不是红黑树？（面试高频）**

| 维度 | 跳表（SkipList） | 红黑树（Red-Black Tree） |
|------|-----------------|--------------------------|
| 实现难度 | ⭐⭐ 简单（链表+随机层数） | ⭐⭐⭐⭐ 复杂（旋转、染色） |
| 范围查询 | ⭐⭐⭐⭐ 快（找到起点后顺序遍历） | ⭐⭐ 中（需要中序遍历） |
| 内存占用 | 稍多（每层都有指针） | 较少（只有左右子节点指针） |
| 并发控制 | ⭐⭐⭐ 相对容易（可以无锁实现） | ⭐ 难（旋转操作难以原子化） |

**Redis选择跳表的原因**：
1. **范围查询多**：ZSet的核心场景是排行榜（`ZRANGE`），跳表的范围查询效率更高
2. **实现简单**：跳表的代码量只有红黑树的几分之一，不易出错
3. **可调优**：通过调整每层的概率参数（默认1/4），可以平衡查询和内存

**HashTable的作用**：

```
跳表 + 哈希表的组合：
- 跳表：支持有序操作（ZRANGE、ZRANGEBYSCORE）
- 哈希表：支持O(1)的单点查询（ZSCORE）

两个结构通过指针共享元素，不重复存储数据
```

---

### 源码关键路径：对象的创建和编码转换

```c
// Redis中每个value都是一个robj（RedisObject）
struct redisObject {
    unsigned type:4;        // 顶层数据结构类型（String/List/Hash/Set/ZSet）
    unsigned encoding:4;     // 底层编码方式（SDS/ZipList/HashTable/SkipList...）
    unsigned lru:LRU_BITS;  // LRU时间（用于内存淘汰）
    int refcount;             // 引用计数（共享对象）
    void *ptr;               // 指向实际数据（SDS/ZipList/HashTable...）
};
```

**编码转换的触发**：

```
以Hash为例：
1. 首次插入：创建ZipList编码的Hash
2. 插入新元素：检查是否满足ZipList条件
   - 元素数 <= hash-max-ziplist-entries？
   - 所有元素的value <= hash-max-ziplist-value？
3. 不满足 → 触发转换：hashTypeConvertListpack(hash, REDIS_ENCODING_HT)
4. 转换后，所有操作都用HashTable编码
```

---

## 它和相似方案的本质区别是什么？

### Redis数据结构 vs Java集合框架

| 维度 | Redis数据结构 | Java集合（HashMap/ArrayList） |
|------|--------------|-------------------------------|
| 设计目标 | 内存数据库，持久化，网络访问 | 单机内存，JVM堆内 |
| 编码转换 | 支持（根据数据量自动切换） | 不支持（创建时确定类型） |
| 内存优化 | ZipList/IntSet等压缩编码 | 无（每个对象都有对象头开销） |
| 持久化 | 支持（RDB/AOF） | 不支持（需要手动序列化） |

**本质区别**：Redis的数据结构是为**内存效率和网络访问**优化的，Java集合是为**单机内存操作**优化的。

---

## 正确使用方式

### 1. 利用编码特性优化内存

```bash
# 查看key的编码
OBJECT ENCODING myhash
# 输出："ziplist" 或 "hashtable"

# 如果看到"hashtable"，考虑是否可以优化为ziplist
# 方法：减少hash-max-ziplist-entries和hash-max-ziplist-value的配置值
```

**优化建议**：
- Hash的field-value对尽量小（<64字节）
- Hash的元素数尽量控制在512以内
- 这样可以一直用ZipList编码，节省内存

---

### 2. 避免大Key（编码转换的副作用）

```
问题：一个Hash有1000万个field
→ 编码一定是HashTable
→ 内存占用大
→ 删除时阻塞（需要逐个释放哈希表节点）

解决：
- 拆分大Hash：按field的hash取模，拆成多个小Hash
- 例如：user:1000:info → user:1000:info:part1, user:1000:info:part2
```

---

### 3. ZSet的范围查询优化

```bash
# ✅ 好：利用跳表的有序性
ZRANGE leaderboard 0 10 WITHSCORES  # O(log n + k)，k=11

# ❌ 差：用String模拟排序（需要排序时拿回客户端排序）
SET user:1000:score 85
# 要查排行榜 → 需要拿回所有数据，在客户端排序 → O(n log n)
```

---

## 边界情况和坑

### 坑1：编码转换导致性能抖动

```
现象：
- 一个Hash，一直用ZipList，操作很快
- 某次插入了一个大value（>64字节）
- 触发编码转换（ZipList → HashTable）
- 转换过程阻塞（需要把所有元素从ZipList复制到HashTable）
- 这次操作的RT突然变长（从微秒级到毫秒级）

解决：
1. 提前规划数据大小，避免触发意外转换
2. 监控编码类型（OBJECT ENCODING），发现转换及时优化
```

---

### 坑2：ZipList的级联更新问题

```
问题：ZipList中每个entry都存储了prevlen（前一个entry的长度）
→ 如果前一个entry的长度发生了变化（比如从253字节变成254字节）
→ prevlen的存储从1字节变成5字节
→ 当前entry的长度也变了
→ 连锁反应：后面所有entry的prevlen都可能要更新
→ 最坏情况：O(n)的级联更新

Redis的解决：
- Redis 5.0引入ListPack（紧凑列表）替代ZipList
- ListPack中每个entry只记录"自身长度"，不记录"前一个长度"
- 遍历时自己计算前一个entry的起始位置
- 避免了级联更新问题
```

---

### 坑3：IntSet升级的开销

```
现象：
- IntSet原来用2字节存储所有元素（encoding=INTSET_ENC_INT16）
- 插入一个大的整数（>32767）
- 触发升级：所有元素从2字节转成4字节或8字节
- 这次插入会变慢（需要重新分配内存+搬移所有元素）

解决：
- 如果知道数据范围，提前用较大的encoding（但Redis不支持手动设置encoding）
- 或者接受这个开销（升级是一次性的，之后就不会再升级了）
```

---

## 我的理解

Redis数据结构的设计精髓是**"空间效率"和"时间效率"的权衡**：

1. **小数据用紧凑编码**（ZipList/IntSet）→ 省内存，但操作稍慢
2. **大数据用高性能编码**（HashTable/SkipList）→ 费内存，但操作快
3. **自动切换** → 用户无感知，但要知道原理才能调优

**面试高频追问**：
1. 为什么ZSet用跳表而不是红黑树？（范围查询+实现简单）
2. Redis的HashTable扩容时怎么避免阻塞？（渐进式rehash）
3. ZipList有什么问题？Redis怎么解决的？（级联更新 → ListPack）
4. SDS相比C字符串有什么优势？（O(1)获取长度+二进制安全+避免缓冲区溢出）

---

## 面试话术

**Q：Redis的ZSet为什么用跳表而不是红黑树？**

"ZSet需要支持两种操作：
1. **单点查询**（ZSCORE）：O(1)用哈希表实现
2. **范围查询**（ZRANGE/ZRANGEBYSCORE）：需要有序结构

范围查询场景下，跳表比红黑树有优势：
- **范围查询效率高**：跳表找到起点后，可以顺着最底层链表顺序遍历，CPU缓存友好；红黑树需要中序遍历，指针跳转多，缓存不友好
- **实现简单**：跳表的代码量只有红黑树的几分之一，不容易出bug
- **可调优**：通过调整每层的概率（默认1/4），可以平衡查询性能和内存占用

Redis的ZSet实际是用**跳表+哈希表**组合实现的：跳表负责有序操作，哈希表负责O(1)的单点查询。两个结构共享元素，不重复存储。"

**Q：Redis的HashTable是怎么扩容的？会不会阻塞？**

"Redis的HashTable扩容用的是**渐进式rehash**，不会一次性阻塞。

具体流程：
1. 扩容时，先分配一个大小为原表2倍的新哈希表（ht[1]）
2. 设置rehashidx=0，表示开始rehash
3. **每次对Hash的增删改查操作，都顺带把ht[0][rehashidx]桶的所有元素搬到ht[1]**
4. rehashidx++，继续处理下一个桶
5. 后台还会有一个定时任务，空闲时批量搬移（加快rehash进度）
6. 搬移完成后，释放ht[0]，把ht[1]设为ht[0]

这样，大量搬移工作被分摊到每次操作中，避免了长时间阻塞。

但注意：在rehash期间，增删改查操作需要同时操作ht[0]和ht[1]（先查ht[0]，找不到再查ht[1]）。"

**Q：Redis有哪些底层编码方式？它们分别在什么情况下使用？**

"Redis的6种顶层数据结构，根据数据量大小，会自动选择不同的底层编码：

1. **String**：固定用SDS（简单动态字符串）
2. **List**：小数据用ZipList，大数据用QuickList
3. **Hash**：小数据用ZipList，大数据用HashTable
4. **Set**：整数且少量用IntSet，其他用HashTable
5. **ZSet**：小数据用ZipList，大数据用SkipList+HashTable

切换条件可以通过配置参数控制，比如：
- `hash-max-ziplist-entries 512`：Hash元素数超过512，转HashTable
- `hash-max-ziplist-value 64`：Hash任意value超过64字节，转HashTable

了解这些，可以帮我们优化Redis的内存使用：尽量让数据保持在紧凑编码（ZipList/IntSet），避免过早触发编码转换。"

---

## 本文总结

| 数据结构 | 小数据编码 | 大数据编码 | 切换条件 |
|---------|-----------|-----------|---------|
| String | SDS | - | - |
| List | ZipList | QuickList | list-max-ziplist-size |
| Hash | ZipList | HashTable | hash-max-ziplist-entries/value |
| Set | IntSet | HashTable | set-max-intset-entries |
| ZSet | ZipList | SkipList+HashTable | zset-max-ziplist-entries/value |

**核心要点**：
1. **SDS**：O(1)获取长度，二进制安全，空间预分配+惰性释放
2. **ZipList**：内存连续，省空间，但有级联更新问题（Redis 5.0+用ListPack解决）
3. **渐进式rehash**：避免HashTable扩容时阻塞
4. **跳表vs红黑树**：跳表范围查询更快，实现更简单
5. **编码转换**：了解切换条件，优化内存使用

**面试核心**：不只是知道Redis有什么数据结构，更要理解**为什么这样设计**——这是对"空间效率"和"时间效率"的权衡。
