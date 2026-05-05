# Redis常见问题

## 这个问题为什么存在？

> Redis用起来简单，但**生产环境的坑**都在细节里。  
> 热Key、大Key、过期策略、内存碎片、集群抖动——这些面试官能追问半小时。

掌握这些"常见问题"，才能：
1. **生产环境不出事**（提前规避）
2. **面试答得上来**（不只是"知道"，要"理解为什么"）

---

## 它是怎么解决问题的？

### 热Key问题（高频访问单个Key）

**现象**：
```
某个key（比如首页推荐）访问量极高（每秒10万次）
→ 单个Redis实例扛不住（CPU打满）
→ 客户端超时，业务报错
```

**解决方案**：

**方案1：本地缓存副本**
```java
// 本地用Caffeine缓存热Key副本
LoadingCache<String, String> localCache = Caffeine.newBuilder()
    .maximumSize(1000)
    .expireAfterWrite(10, TimeUnit.SECONDS)
    .build(key -> redisTemplate.opsForValue().get(key));

// 读：先读本地缓存，未命中再读Redis
String value = localCache.get("hot:key");
```

**方案2：Redis Cluster，Key拆分**
```bash
# 把hot:key拆成10个副本
hot:key:1, hot:key:2, ..., hot:key:10

# 读时随机选一个
random = ThreadLocalRandom.current().nextInt(10);
String value = jedis.get("hot:key:" + random);
```

**方案3：主从读取（临时方案）**
```
如果是主从架构，热Key可以打到从节点
→ 但主从延迟可能导致读到旧值
```

---

### 大Key问题（单个Key太大）

**现象**：
```
一个Hash有1000万个field
→ 删除时阻塞（O(n)操作，可能几百毫秒）
→ 网络传输慢（一次读几个MB）
→ 集群迁移时，单个key太大无法迁移（Redis Cluster限制：单个key不能超过512MB）
```

**识别大Key**：
```bash
# Redis自带命令
redis-cli --bigkeys

# 输出示例：
# [SWEEPING THE WHOLE KEYS]: 1000000 keys, 10 big keys found
# [Big Hash key]: user:1000:friends has 1000000 fields
```

**解决方案**：

**方案1：拆分大Key**
```bash
# 原：user:1000:friends（1000万个friendId）
# 拆：user:1000:friends:part1（每批1万元素）
#     user:1000:friends:part2
#     ...

# 读：先算在哪一批，再读
part = friendId % 10
jedis.hget("user:1000:friends:part" + part, friendId)
```

**方案2：Redis 4.0+ 异步删除**
```bash
# redis.conf
lazyfree-lazy-eviction yes   # 淘汰时异步删除
lazyfree-lazy-expire yes    # 过期时异步删除
lazyfree-lazy-server-del yes # 显式删除（DEL命令）也异步
```

---

### 过期策略（Redis怎么删除过期Key）

**问题**：如果每次key过期都立即删除 → CPU开销大  
如果一直不删除 → 内存浪费

**Redis的过期策略：惰性删除 + 定期删除**

```
惰性删除（Lazy Expire）：
┌──────────────────────────────────────────────┐
│ 访问某个key时，检查是否过期                          │
│   → 过期：删除，返回null                            │
│   → 未过期：返回数据                                │
└──────────────────────────────────────────────┘
优点：CPU友好（不主动扫描）
缺点：如果key一直不被访问 → 内存泄漏

定期删除（Active Expire）：
┌──────────────────────────────────────────────┐
│ 定时任务（每秒10次，即每100ms一次）                │
│  1. 随机选20个设置了过期时间的key                   │
│  2. 删除已过期的key                                │
│  3. 如果超过25%的key已过期 → 再随机选20个（循环）│
└──────────────────────────────────────────────┘
优点：防止惰性删除的"内存泄漏"
缺点：定时任务有开销
```

**过期策略的配置**：
```bash
# redis.conf
hz 10  # 定时任务频率（每秒10次，默认）
# 调大hz → 过期扫描更频繁 → 内存更及时释放，但CPU开销更大
```

---

### 内存碎片问题

**现象**：
```
Redis实际使用内存（used_memory）只有2GB
但RSS（Redis进程占用的物理内存）有4GB
→ 内存碎片率高（>50%）
```

**原因**：
```
内存分配器（jemalloc）分配内存时，会有碎片
→ 频繁更新、删除key，导致内存碎片
```

**监控碎片率**：
```bash
INFO memory

# 关键指标：
# used_memory: 实际使用的内存（计算用）
# used_memory_rss: 操作系统分配给Redis的物理内存（RSS）
# mem_fragmentation_ratio: used_memory_rss / used_memory

# mem_fragmentation_ratio > 1.5 → 碎片率高，需要清理
```

**解决碎片**：
```bash
# Redis 4.0+ 支持碎片清理
memory purge  # 手动清理碎片（会阻塞）

# 或者配置自动清理
# redis.conf
activedefrag yes
active-defrag-ignore-bytes 100mb     # 碎片超过100MB才清理
active-defrag-threshold-lower 10      # 碎片率超过10%才清理
active-defrag-threshold-upper 100     # 碎片率超过100%全力清理
```

---

### 集群抖动问题（Redis Cluster）

**现象**：
```
Redis Cluster中，某个主节点挂了
→ 哨兵（或Cluster自动故障转移）选举从节点为新主
→ 故障转移期间（几秒），部分请求失败
→ 客户端报"CLUSTERDOWN the cluster is down"
```

**原因**：
```
故障转移需要时间：
1. 主观下线 → 客观下线（几秒）
2. 从节点选举（几百毫秒）
3. 新主节点接管槽（几百毫秒）
4. 客户端更新路由（依赖客户端实现）
```

**解决方案**：

**方案1：客户端重试机制**
```java
// JedisCluster自动重试
JedisCluster jedis = new JedisCluster(nodes, 
    2000,  // timeout
    2000,  // infinite sof timeout
    3);    // maxRedirections（重试次数）

// 内部会自动处理MOVED重定向和重试
```

**方案2：多副本读（降低主节点压力）**
```
读请求可以打到从节点（牺牲一致性，换可用性）
→ 配置：JedisCluster设置`readFromReplicas()`
```

---

### 网络带宽问题

**现象**：
```
Redis吞吐量高（每秒10万次操作）
→ 网络带宽打满（1000Mbps网卡 → 125MB/s）
→ 客户端超时
```

**解决方案**：

**方案1：压缩数据**
```java
// 存储时压缩
byte[] compressed = Snappy.compress(value.getBytes());
jedis.set(key.getBytes(), compressed);

// 读取时解压
byte[] data = jedis.get(key.getBytes());
String value = new String(Snappy.uncompress(data));
```

**方案2：Pipeline（批量操作）**
```java
// 不用Pipeline：每次操作都要等网络RTT
for (int i = 0; i < 10000; i++) {
    jedis.set("key:" + i, "value:" + i);  // 1万次网络往返
}

// 用Pipeline：批量发送，一次网络往返
Pipeline p = jedis.pipelined();
for (int i = 0; i < 10000; i++) {
    p.set("key:" + i, "value:" + i);
}
p.sync();  // 一次网络往返，执行1万次操作
```

---

## 它和相似方案的本质区别是什么？

### Redis 4.0 之前的删除 vs Redis 4.0+ 的异步删除

| 维度 | Redis < 4.0（同步删除） | Redis 4.0+（异步删除） |
|------|--------------------------|------------------------|
| 删除大Key | 主线程阻塞（可能几百毫秒） | 后台线程删除（主线程不阻塞） |
| 配置 | - | `lazyfree-lazy-server-del yes` |
| 适用场景 | 小Key为主 | 有大Key的场景 |

**本质区别**：Redis 4.0+把"删除"这个慢操作放到后台线程，避免阻塞主线程。

---

## 正确使用方式

### 1. 监控关键指标

```bash
# 监控脚本（每分钟执行）
#!/bin/bash
redis-cli INFO stats | grep -E "total_connections_received|instantaneous_ops_per_sec|rejected_connections|expired_keys|evicted_keys"
redis-cli INFO memory | grep -E "used_memory_human|used_memory_rss|mem_fragmentation_ratio"
redis-cli INFO replication | grep -E "role|connected_slaves|master_repl_offset"
```

**关键告警阈值**：
- `mem_fragmentation_ratio > 1.5` → 碎片率高
- `rejected_connections > 0` → 连接数超了
- `evicted_keys` 增长快 → 内存不够，需要扩容

---

### 2. 合理设置过期时间

```bash
# ❌ 不推荐：大量key同时过期
SET key value EX 3600  # 整点过期

# ✅ 推荐：过期时间加随机值
SET key value EX $((3600 + RANDOM % 300))  # 3600±300秒随机
```

---

### 3. 使用Pipeline但要注意

```java
// ✅ 正确：Pipeline批量操作，但要控制批次大小
Pipeline p = jedis.pipelined();
for (int i = 0; i < 10000; i++) {
    p.set("key:" + i, "value:" + i);
    if (i % 1000 == 0) {  // 每1000条一批
        p.sync();
    }
}
p.sync();  // 最后一批

// ❌ 错误：Pipeline一次发送太多命令（可能超过client-output-buffer-limit）
Pipeline p = jedis.pipelined();
for (int i = 0; i < 1000000; i++) {  // 100万条一次发送
    p.set("key:" + i, "value:" + i);
}
p.sync();  // 可能超时或内存溢出
```

---

## 边界情况和坑

### 坑1：Pipeline和事务的区别

```
Pipeline：
- 目的：减少网络RTT（批量发送命令）
- 不保证原子性（命令是一条条执行的）
- 适合：批量写入/读取

事务（MULTI/EXEC）：
- 目的：保证原子性（一组命令要么都执行，要么都不执行）
- 会阻塞其他客户端的请求（事务执行期间）
- 适合：需要原子性的操作（比如转账）
```

---

### 坑2：Redis Cluster不支持多Key操作（跨槽）

```java
// ❌ Redis Cluster中，以下操作会报错（key不在同一个槽）
jedis.mset("key1", "value1", "key2", "value2");  // CROSSSLOT error

// ✅ 解决：用hash tag（强制放到同一个槽）
jedis.mset("{user:1000}:name", "Tom", "{user:1000}:age", "26");
// {user:1000}是hash tag，CRC16计算槽时只用花括号内的内容
```

---

### 坑3：主从延迟导致读取到旧值

```
问题：
- 主节点写入成功
- 从节点还没同步（异步复制）
- 客户端从从节点读取 → 读到旧值

解决：
1. 写后读 → 强制读主节点（业务层判断）
2. 从节点读 → 用`WAIT`命令（等待从节点同步）
   WAIT 1 5000  # 等待至少1个从节点同步，超时5秒
3. 接受"最终一致性"（大部分场景可以接受）
```

---

### 坑4：Redis满时的行为

```bash
# maxmemory-policy = noeviction（默认）
# → 内存满时，写命令报错：OOM command not allowed

# maxmemory-policy = allkeys-lru
# → 内存满时，淘汰最久未访问的key

# 如果Redis内存快满了：
# 1. 提前告警（比如80%时）
# 2. 扩容（增加maxmemory）
# 3. 或者淘汰策略（如果允许丢数据）
```

---

