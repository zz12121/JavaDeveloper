# Redis内存淘汰策略

## 这个问题为什么存在？

> Redis是内存数据库，内存是有限的。  
> 如果一直写入，内存终会耗尽——然后呢？是直接崩溃，还是自动清理？

没有淘汰策略的世界：

```
Redis内存达到maxmemory上限
→ 继续写入 → 报错：OOM command not allowed when used memory > 'maxmemory'
→ 客户端收到异常，业务报错
```

**内存淘汰策略就是：当内存达到上限时，Redis该怎么做？**  
是报错？还是删除一些数据腾出空间？删哪些数据？

---

## 它是怎么解决问题的？

### 核心机制：8种淘汰策略

```bash
# 配置文件设置淘汰策略
maxmemory-policy <策略>

# 设置最大内存
maxmemory 4gb
```

**8种策略分类**：

```
按淘汰范围分：
├── 只淘汰设置了过期时间的key（volatile-）
│   ├── volatile-lru：淘汰最久未访问的（LRU）
│   ├── volatile-lfu：淘汰访问频率最低的（LFU，Redis 4.0+）
│   ├── volatile-ttl：淘汰TTL（剩余存活时间）最短的
│   └── volatile-random：随机淘汰
│
├── 淘汰所有key（allkeys-）
│   ├── allkeys-lru：淘汰最久未访问的
│   ├── allkeys-lfu：淘汰访问频率最低的（Redis 4.0+）
│   └── allkeys-random：随机淘汰
│
└── 不淘汰（noeviction）
    └── 内存满时写入报错（默认策略）
```

---

### LRU vs LFU（重点）

**LRU（Least Recently Used）**：淘汰**最久没访问**的key

```
LRU原理：
- 每个key记录最近访问时间戳（lru字段，24位）
- 淘汰时，随机选5个key（采样），淘汰其中lru时间戳最小的

为什么采样而不扫描全部？
→ 全扫描太慢（O(n)），采样是O(1)的近似算法
→ 采样数量由maxmemory-samples控制（默认5，越大越精确但越慢）
```

**LFU（Least Frequently Used）**：淘汰**访问频率最低**的key（Redis 4.0+）

```
LFU原理：
- 每个key记录访问频率（lru字段的后8位）
- 频率衰减：随时间自动降低频率（避免"古老的热点"永远不被淘汰）
- 新key有个初始频率（避免新key刚进来就被淘汰）

LFU vs LRU：
├── LRU：只关心"最近是否访问过"，不关心"访问了多少次"
│   → 问题：一次性遍历全表（所有key都被访问一次）→ 所有key的LRU时间都更新了→ 淘汰策略失效
│
└── LFU：关心"访问频率"，一次性遍历的影响会随着时间衰减
    → 更适合真实场景
```

**LRU和LFU的对比**：

| 维度 | LRU | LFU |
|------|-----|-----|
| 淘汰依据 | 最近访问时间 | 访问频率 |
| Redis版本 | 一直支持 | 4.0+才支持 |
| 适合场景 | 热点明显，且热点稳定 | 频率比"最近"更能反映重要性 |
| 一次性扫描问题 | 有（扫完后所有key都变成"最近访问"） | 无（频率会衰减） |

---

### 源码关键路径：淘汰的执行

```c
// Redis处理命令前，先检查内存是否超限
int processCommand(...) {
    if (server.maxmemory) {
        // 计算需要释放多少内存
        mem_tofree = used_memory - server.maxmemory;
        // 循环淘汰，直到内存降到maxmemory以下
        while (mem_tofree > 0) {
            // 根据maxmemory-policy选择淘汰策略
            // 采样→淘汰→计算释放的内存
            retval = performEvictions(...);
        }
    }
}
```

**近似LRU的实现（重要）**：

```
Redis不用双向链表实现LRU（内存开销大），而是：
1. 每个key有个24位lru字段，记录最近访问的时间戳
2. 淘汰时，随机采样N个key（N=maxmemory-samples）
3. 淘汰这N个里面lru最小的（最久未访问的）
4. 为什么采样？→ 全扫描太慢，采样是O(1)近似算法
```

---

### TTL淘汰（volatile-ttl）

```
volatile-ttl策略：
- 只淘汰设置了过期时间的key
- 淘汰时，随机采样，比较剩余TTL
- TTL越小（越快过期），越先被淘汰

适用场景：
- 明确知道"快过期的key，不值得继续留着"
- 比如：验证码、session（都有明确的过期时间）
```

---

## 它和相似方案的本质区别是什么？

### Redis淘汰 vs Java HashMap的LRU

| 维度 | Redis淘汰策略 | Java LinkedHashMap(LRU) |
|------|---------------|------------------------|
| 实现方式 | 采样近似算法（O(1)） | 双向链表（O(1)） |
| 精确度 | 近似（可能漏掉最久未访问的） | 精确 |
| 内存开销 | 每个key只多24位（lru字段） | 每个entry多两个指针（prev/next） |
| 策略丰富度 | 8种（LRU/LFU/random/TTL） | 只有LRU（需要自己实现LFU） |

**本质区别**：Redis的LRU是**近似算法**，牺牲精确度换性能和内存效率。

---

### 过期删除 vs 内存淘汰

| 维度 | 过期删除（主动/被动） | 内存淘汰（maxmemory-policy） |
|------|---------------------|----------------------------|
| 触发时机 | key过期时（主动删除/被动删除） | 内存达到maxmemory时 |
| 删除范围 | 只删过期的key | 可以删没过期的key（allkeys-策略） |
| 是否阻塞 | 主动删除是定时任务（可配置） | 在执行命令前同步淘汰（可能阻塞） |

**两者是配合关系**：
- 过期删除：清理"已经过期"的key
- 内存淘汰：内存不够时，清理"没过期但不重要"的key

---

## 正确使用方式

### 1. 根据业务场景选择淘汰策略

```
场景1：纯缓存（允许丢失）
→ 用allkeys-lru或allkeys-lfu
→ 内存满就淘汰，不需要持久化这些缓存

场景2：缓存+持久化混合（部分key不能丢）
→ 给重要key不设过期时间
→ 用volatile-lru（只淘汰设了过期时间的key）
→ 没设过期时间的key不会被淘汰

场景3：严格不允许丢数据
→ 用noeviction（内存满就报错）
→ 配合持久化（AOF+RDB），内存满时扩容或分片
```

---

### 2. 合理配置采样精度

```bash
# 提高采样精度（默认5）
maxmemory-samples 10

# 代价：每次淘汰多选5个key，CPU开销增大
# 建议：5-10之间，太大反而影响性能
```

---

### 3. 监控淘汰情况

```bash
# 查看淘汰统计
INFO stats

# 关键指标：
# evicted_keys：累计淘汰的key数量
# 如果evicted_keys增长很快 → 内存不够，需要扩容或优化淘汰策略
```

---

## 边界情况和坑

### 坑1：淘汰时阻塞（最大坑）

```
现象：
- Redis突然卡顿几百毫秒
- 慢日志显示：EVICT命令（其实是淘汰逻辑）耗时高

原因：
- 内存达到maxmemory后，每次写入都要先淘汰一些key
- 如果淘汰策略是LRU/LFU，需要采样、比较
- 如果需要淘汰大量key才能腾出空间 → 这次命令会阻塞很久

解决：
1. 提前预警：监控used_memory，超过maxmemory的80%就告警
2. 选用更高效淘汰策略（LFU比LRU快？不一定，看场景）
3. 增加maxmemory-samples（提高精度，减少反复淘汰的次数）
4. 最根本：扩容或使用Redis Cluster分片
```

---

### 坑2：LRU近似算法的精确度问题

```
现象：
- 明明有些key很久没访问，却没被淘汰
- 反而淘汰了"可能还有用"的key

原因：
- Redis的LRU是采样近似算法，不是精确LRU
- 采样数量（maxmemory-samples）太小，导致"最久未访问的key"没被采样到

解决：
- 增大maxmemory-samples（比如从5调到10）
- 或者改用LFU（对采样不敏感，因为频率比"最近"更稳定）
```

---

### 坑3：写时复制（COW）导致内存超预期

```
现象：
- maxmemory设了4GB
- 但实际内存用到6GB才触发淘汰

原因：
- BGSAVE或BGREWRITEAOF时，fork子进程
- 写时复制（COW）：父进程修改的页面会被复制
- 复制出来的页面也占用内存，但不算在maxmemory里？

实际上是算的。Redis的maxmemory统计的是Redis进程分配的总内存（包括COW复制的页面）。

解决：
- maxmemory不要设成100%物理内存
- 预留30-50%给COW、AOF缓冲区、客户端缓冲区等
```

---

### 坑4：big key淘汰导致阻塞

```
现象：
- 淘汰一个big key（比如一个有100万个field的Hash）
- 这次淘汰耗时几百毫秒（阻塞）

原因：
- 淘汰=删除
- 删除big key是O(n)操作（需要释放所有子元素）
- 删除期间，Redis主线程阻塞

解决：
1. 避免big key（拆分）
2. Redis 4.0+支持lazyfree（异步删除）
   lazyfree-lazy-eviction yes  # 淘汰时异步删除
3. 或者：业务层面控制key的大小
```

---

## 我的理解

内存淘汰策略是Redis"高可用"的重要一环——**允许丢一些数据，好过直接崩溃**。

**核心要点**：

1. **LRU vs LFU**：LRU关心"最近"，LFU关心"频率"。LFU更适合真实场景（避免一次性扫描污染LRU时间）

2. **近似算法**：Redis的LRU/LFU都是采样近似，不是精确算法。牺牲精确度换性能和内存效率。

3. **淘汰时机**：每次写入前，如果内存超了，同步淘汰（可能阻塞）。这是Redis"延时"的一个来源。

4. **big key问题**：淘汰=删除，删除big key会阻塞。Redis 4.0+的lazyfree可以异步删除。

**面试高频追问**：
1. Redis的淘汰策略有哪些？（8种，按volatile/allkeys分类）
2. LRU和LFU的区别？（LRU看最近访问时间，LFU看访问频率）
3. Redis的LRU是精确的吗？（不是，是采样近似算法）
4. 淘汰时会阻塞吗？（会，在主线程同步淘汰）

---

## 面试话术

**Q：Redis的内存淘汰策略有哪些？你们生产环境用哪种？**

"Redis有8种淘汰策略，可以分为三类：

**第一类：只淘汰设置了过期时间的key（volatile-前缀）**
- volatile-lru：淘汰最久未访问的
- volatile-lfu：淘汰访问频率最低的（Redis 4.0+）
- volatile-ttl：淘汰TTL最短的（最快过期的）
- volatile-random：随机淘汰

**第二类：淘汰所有key（allkeys-前缀）**
- allkeys-lru：淘汰最久未访问的
- allkeys-lfu：淘汰访问频率最低的
- allkeys-random：随机淘汰

**第三类：不淘汰**
- noeviction：内存满就报错（默认策略）

**我们生产环境的选型**：
- 如果是纯缓存场景（允许丢失），用`allkeys-lfu`
- 如果是缓存+持久化混合（重要数据不能丢），给重要key不设过期时间，用`volatile-lfu`（只淘汰设了过期时间的key）
- 关键配置：`maxmemory-samples 10`（提高采样精度）+ `lazyfree-lazy-eviction yes`（异步删除，避免阻塞）"

**Q：Redis的LRU是精确的吗？为什么不用精确LRU？**

"Redis的LRU是**近似算法**，不是精确的。

**为什么不用精确LRU？**
精确LRU需要维护一个双向链表（按访问时间排序），每次访问都要移动节点到表头。这需要：
1. 每个key多两个指针（prev/next）→ 内存开销大
2. 每次访问都要修改链表 → CPU开销

**Redis的近似LRU**：
1. 每个key只用24位记录最近访问时间戳（lru字段）
2. 淘汰时，随机采样N个key（N=`maxmemory-samples`，默认5）
3. 淘汰这N个里面lru时间戳最小的
4. 为什么采样？→ O(1)操作，不需要维护链表

**精确度问题**：
- 采样数量越大，越精确，但CPU开销也越大
- 默认5次采样，在工业界已经够用了（误差在可接受范围）

Redis 4.0+更推荐用LFU，因为LFU对采样的敏感度比LRU低（频率比'最近访问时间'更稳定）。"

**Q：如果Redis内存满了，会发生什么？**

"取决于`maxmemory-policy`的配置：

**如果是`noeviction`（默认）**：
- 所有写命令报错：OOM command not allowed
- 读命令正常
- 这是最安全但最不实用的策略

**如果是其他策略（lru/lfu/random/ttl）**：
1. Redis在执行写命令前，先检查内存是否超过`maxmemory`
2. 如果超过，根据策略淘汰一些key，直到内存降到`maxmemory`以下
3. 然后再执行当前的写命令

**注意**：淘汰操作是在**主线程**同步执行的，如果一次需要淘汰很多big key，会阻塞（Redis 4.0+可以开启`lazyfree-lazy-eviction`异步删除）。

生产环境建议：
1. 设置合理的`maxmemory`（不要设为100%物理内存，预留30%给COW等）
2. 选用`allkeys-lfu`或`volatile-lfu`
3. 开启`lazyfree-lazy-eviction yes`（异步删除）
4. 监控`evicted_keys`指标，如果增长过快说明内存不够"

---

## 本文总结

| 策略类型 | 具体策略 | 淘汰范围 | 适用场景 |
|---------|---------|---------|---------|
| volatile-（只淘汰设了过期时间的） | volatile-lru | 最久未访问 | 缓存场景，且区分"可丢"和"不可丢" |
| ^ | volatile-lfu | 访问频率最低 | 同上，但更适合真实场景 |
| ^ | volatile-ttl | TTL最短 | 明确知道"快过期的不重要" |
| ^ | volatile-random | 随机 | 不推荐 |
| allkeys-（淘汰所有key） | allkeys-lru | 最久未访问 | 纯缓存，允许丢任何数据 |
| ^ | allkeys-lfu | 访问频率最低 | 纯缓存，推荐（Redis 4.0+） |
| ^ | allkeys-random | 随机 | 不推荐 |
| 不淘汰 | noeviction | 不淘汰，写入报错 | 数据绝对不能丢 |

**核心要点**：
1. LRU是近似算法（采样），不是精确LRU
2. LFU比LRU更适合真实场景（避免一次性扫描污染）
3. 淘汰是在主线程同步执行的，可能阻塞（big key问题）
4. Redis 4.0+开启`lazyfree-lazy-eviction`可以异步删除

**面试关键**：不只是背8种策略，要理解**为什么用近似算法**（内存和CPU的权衡），以及**LFU相比LRU的优势**（对采样不敏感，更适合真实场景）。
