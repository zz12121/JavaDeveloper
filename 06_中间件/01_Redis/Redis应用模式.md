# Redis应用模式

## 这个问题为什么存在？

> Redis不只是"缓存"。  
> 如果用不好，缓存穿透、击穿、雪崩、热Key、大Key——个个都能让数据库崩掉。

理解Redis的**应用模式**，就是理解：
1. **怎么正确用缓存**（更新策略、穿透/击穿/雪崩）
2. **Redis能做什么**（分布式锁、排行榜、限流、消息队列）
3. **这些场景的最佳实践**是什么

---

## 它是怎么解决问题的？

### 缓存更新策略（核心）

**问题**：数据库更新了，缓存怎么办？

**四种策略**：

```
策略1：Cache Aside（旁路缓存，最常用）
┌──────────────────────────────────────┐
│ 写：                                │
│  1. 更新数据库                      │
│  2. 删除缓存（不是更新缓存！）        │
│                                      │
│ 读：                                │
│  1. 读缓存，命中→返回               │
│  2. 未命中→读数据库→写入缓存        │
└──────────────────────────────────────┘

为什么要"删除"而不是"更新"缓存？
→ 更新缓存成本高（可能需要计算）
→ 且并发写时，更新缓存可能有顺序问题（后更新的反而先完成）

策略2：Read/Write Through（穿透缓存）
┌──────────────────────────────────────┐
│ 缓存层封装了数据源的读写              │
│ 应用只和缓存交互，不直接访问数据库      │
│ Cache负责同步写数据库（Write Through）  │
└──────────────────────────────────────┘
问题：Redis本身不支持，需要自己封装

策略3：Write Behind（异步写回）
┌──────────────────────────────────────┐
│ 写：只写缓存，异步批量写数据库        │
│ 读：缓存未命中→读数据库→写入缓存     │
└──────────────────────────────────────┘
问题：异步写期间，如果缓存挂了→数据丢失

策略4：双写一致性（不推荐）
┌──────────────────────────────────────┐
│ 写：同时写数据库和缓存                │
│ 问题：并发写时，数据库和缓存可能不一致  │
└──────────────────────────────────────┘
```

**Cache Aside的最佳实践**：

```java
// 写
@Transactional
public void updateUser(User user) {
    userMapper.update(user);       // 1. 更新数据库
    redisTemplate.delete("user:" + user.getId());  // 2. 删除缓存
}

// 读
public User getUserById(Long id) {
    // 1. 读缓存
    User user = redisTemplate.opsForValue().get("user:" + id);
    if (user != null) return user;
    
    // 2. 缓存未命中，读数据库
    user = userMapper.selectById(id);
    
    // 3. 写入缓存（设置过期时间！）
    redisTemplate.opsForValue().set("user:" + id, user, 30, TimeUnit.MINUTES);
    return user;
}
```

---

### 缓存穿透、击穿、雪崩（面试三高）

| 问题 | 原因 | 解决 |
|------|------|------|
| **缓存穿透** | 查询不存在的数据（缓存和数据库都没有） | 布隆过滤器 / 缓存空值 |
| **缓存击穿** | 热点key过期瞬间，大量请求打到数据库 | 互斥锁 / 逻辑过期 |
| **缓存雪崩** | 大量key同时过期，或Redis挂了 | 过期时间加随机值 / Redis集群 |

#### 缓存穿透

```
问题场景：
攻击者不断查询"不存在的ID"（比如-1、-2、...）
→ 缓存没有，每次都查数据库
→ 数据库被拖垮

解决方案1：缓存空值
┌──────────────────────────────────────┐
│ if (db查询结果为null) {              │
│     redis.set(key, null, 5分钟);    │
│ }                                   │
└──────────────────────────────────────┘
问题：如果恶意攻击用大量不同ID → 缓存大量空值 → 内存耗尽

解决方案2：布隆过滤器
┌──────────────────────────────────────┐
│ 1. 启动时，把所有已存在的ID加载到布隆过滤器 │
│ 2. 查询时，先询问布隆过滤器          │
│    → 不存在 → 直接返回（不查数据库） │
│    → 可能存在 → 查缓存 → 查数据库    │
└──────────────────────────────────────┘
注意：布隆过滤器有误判率（说"存在"但实际不存在）
```

#### 缓存击穿

```
问题场景：
热点key（比如首页推荐）突然过期
→ 这一瞬间，大量请求发现缓存过期
→ 全部打到数据库

解决方案1：互斥锁（Redis分布式锁）
┌──────────────────────────────────────┐
│ if (缓存未命中) {                    │
│     if (RedisLock.tryLock(key)) {   │
│         // 只有一个线程查数据库        │
│         data = db.query();           │
│         redis.set(key, data);        │
│         RedisLock.unlock(key);       │
│     } else {                        │
│         // 其他线程等待（或重试）      │
│         Thread.sleep(50);            │
│         return getData(key);  // 重试  │
│     }                               │
│ }                                   │
└──────────────────────────────────────┘

解决方案2：逻辑过期（热门数据）
┌──────────────────────────────────────┐
│ 缓存不设置TTL，而是在value中存过期时间 │
│ 发现逻辑过期时，开新线程重建缓存        │
│ 当前请求返回旧数据（不阻塞）          │
└──────────────────────────────────────┘
适合：热门数据，允许短暂不一致
```

#### 缓存雪崩

```
问题场景1：大量key同时过期
→ 这一瞬间，所有请求都打到数据库

解决：过期时间加随机值
┌──────────────────────────────────────┐
│ redis.set(key, value,              │
│     TTL + random(0, 300));  // 加随机秒数 │
└──────────────────────────────────────┘

问题场景2：Redis挂了
→ 所有请求都打到数据库 → 数据库也挂了

解决：Redis集群（主从+哨兵或Cluster）
```

---

### 分布式锁（Redis经典应用）

**问题**：分布式系统，多个实例同时修改同一资源 → 数据不一致

**Redis分布式锁的实现**：

```java
// 加锁（SET key value NX EX timeout）
public boolean tryLock(String key, String requestId, int expireSeconds) {
    String result = jedis.set(key, requestId, "NX", "EX", expireSeconds);
    return "OK".equals(result);
}

// 解锁（Lua脚本，保证原子性）
public boolean unlock(String key, String requestId) {
    String lua = `
        if redis.call("get", KEYS[1]) == ARGV[1] then
            return redis.call("del", KEYS[1])
        else
            return 0
        end
    `;
    Object result = jedis.eval(lua, Collections.singletonList(key), 
                             Collections.singletonList(requestId));
    return "1".equals(result.toString());
}
```

**为什么解锁要用Lua脚本？**

```
错误方式：
1. if (redis.get(key).equals(requestId)) {  // 判断
2.     redis.del(key);                       // 删除
}
问题：判断和删除是两个操作，不是原子的
→ 在1和2之间，锁过期了，被别的线程抢走
→ 然后当前线程执行del → 把别人的锁删了

正确方式：用Lua脚本，把判断和删除打包成原子操作
```

**Redisson的看门狗（Watch Dog）机制**：

```
问题：锁的过期时间设多长？
- 设太短：业务没执行完，锁就过期了（别的线程抢走）
- 设太长：如果持有锁的实例挂了，别人要等很久才能抢锁

Redisson的解决：看门狗
┌──────────────────────────────────────┐
│ 1. 加锁时默认设30秒过期                │
│ 2. 启动一个后台线程（看门狗）           │
│ 3. 每隔10秒（过期时间的1/3）检查锁还在 │
│ 4. 如果还在，延长过期时间（重置为30秒） │
│ 5. 直到业务执行完，主动释放锁           │
└──────────────────────────────────────┘
```

---

### 排行榜（ZSet的典型应用）

```java
// 用户得分
ZADD leaderboard 85 "user:1000"
ZADD leaderboard 92 "user:1001"
ZADD leaderboard 78 "user:1002"

// 查询Top 10
ZREVRANGE leaderboard 0 9 WITHSCORES

// 查询用户排名
ZREVRANK leaderboard "user:1000"  // 从0开始

// 查询用户分数
ZSCORE leaderboard "user:1000"
```

**为什么用ZSet？**
- 自动按score排序（跳表保证O(log n)的插入和查询）
- 支持范围查询（ZRANGEBYSCORE）
- 支持排名查询（ZRANK/ZREVRANK）

---

### 限流（滑动窗口 / 令牌桶）

**固定窗口限流（简单但有问题）**：

```java
// 限制：每60秒最多100次请求
String key = "limit:" + userId + ":" + currentTimeMillis() / 60000;
Long count = jedis.incr(key);
if (count == 1) jedis.expire(key, 60);
if (count > 100) return "被限流了";
```

**问题**：临界问题（第59秒和第1秒可以各通过100次，实际2秒内通过了200次）

**滑动窗口限流（Redis 6.2+的ZSet实现）**：

```java
// 用ZSet记录请求时间戳（score=时间戳，member=唯一ID）
ZADD limit:user:1000 <timestamp> <requestId>
// 移除时间窗口之前的记录
ZREMRANGEBYSCORE limit:user:1000 0 <now - windowSize>
// 统计窗口内请求数
Long count = jedis.zcard("limit:user:1000");
if (count > maxRequests) return "被限流了";
```

---

## 它和相似方案的本质区别是什么？

### Redis缓存 vs 本地缓存（Caffeine/Guava Cache）

| 维度 | Redis缓存 | 本地缓存 |
|------|-----------|---------|
| 位置 | 远程（网络开销） | 本地JVM堆内（无网络开销） |
| 一致性 | 多实例间一致 | 每个实例独立，可能不一致 |
| 容量 | 大（可以超出单机内存） | 受JVM堆限制 |
| 适用场景 | 共享缓存、分布式锁 | 只读配置、热点数据本地副本 |

**最佳实践**：多级缓存
```
本地缓存（Caffeine） → Redis缓存 → 数据库
    ↓（命中）         ↓（命中）
   直接返回           返回+写入本地缓存
```

---

## 正确使用方式

### 1. 缓存预热

```java
// 系统启动时，把热点数据加载到Redis
@PostConstruct
public void warmUpCache() {
    List<User> hotUsers = userMapper.selectHotUsers();
    for (User user : hotUsers) {
        redisTemplate.opsForValue().set("user:" + user.getId(), user, 30, TimeUnit.MINUTES);
    }
}
```

### 2. 避免大Key

```
问题：一个Hash有1000万个field → 删除时阻塞（O(n)）
解决：拆分大Key
┌──────────────────────────────────────┐
│ 原：user:1000:friends（1000万个friendId） │
│ 拆：user:1000:friends:part1（每批1万元素） │
│     user:1000:friends:part2            │
└──────────────────────────────────────┘
```

### 3. 避免热Key

```
问题：某个key访问量极高（比如首页推荐）→ 单个Redis实例扛不住

解决1：本地缓存副本
→ 应用本地用Caffeine缓存热Key的副本

解决2：Redis Cluster，把热Key复制到多个实例
→ 读时随机选一个副本

解决3：Key拆分
→ 把hotkey拆成hotkey:1、hotkey:2、...、hotkey:10
→ 读时随机选一个
```

---

## 边界情况和坑

### 坑1：缓存与数据库的一致性（双写问题）

```
场景：
1. 线程A删除缓存
2. 线程B读缓存，未命中
3. 线程B读数据库（旧值）
4. 线程A更新数据库（新值）
5. 线程B把旧值写入缓存
→ 缓存是旧值，数据库是新值

解决：延迟双删
┌──────────────────────────────────────┐
│ 1. 删除缓存                            │
│ 2. 更新数据库                         │
│ 3. 睡眠1秒（等读取线程完成）           │
│ 4. 再次删除缓存                       │
└──────────────────────────────────────┘
问题：睡眠1秒不优雅，且不是100%可靠

商业方案：订阅binlog（Canal），异步删除缓存
```

### 坑2：Redis分布式锁的过期时间问题

```
问题：业务执行时间 > 锁的过期时间
→ 锁过期了，业务还没执行完
→ 别的线程抢到锁，两个线程同时执行业务

解决1：Redisson看门狗（自动续期）
解决2：预估业务最大执行时间，设置足够长的过期时间
```

### 坑3：Lua脚本阻塞Redis

```
问题：Lua脚本中有大循环或复杂计算
→ Redis是单线程，Lua脚本执行期间阻塞所有其他请求

解决：
1. Lua脚本要尽量简单（只做Redis命令的组合）
2. 避免在Lua中做复杂计算
3. 如果必须复杂计算，考虑放到客户端做
```

---

