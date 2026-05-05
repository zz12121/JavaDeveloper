# Redis 缓存设计实战

> 缓存不是银弹。用得好是性能倍增器，用不好是线上故障的温床。

---

## 核心问题框架

```
              缓存问题
             /    |    \
          穿透   击穿   雪崩
            |      |      |
        布隆/空值  热点key过期  批量key过期/硬件故障
```

---

## 场景 A：缓存穿透（数据不存在）

### 现象

```
接口响应慢
Redis：miss
DB：大量查询（同一不存在的数据）
DB 压力骤增
```

### 根因

查询一个 **DB 和缓存都不存在** 的数据，每次都打到 DB。比如恶意爬虫、id 自增遍历。

### 解决方案

```java
// 方案1：缓存空值（简单但有缺陷）
public User getUser(Long id) {
    String key = "user:" + id;
    String json = redis.get(key);
    if (json != null) {
        if ("null".equals(json)) return null;  // 空值缓存
        return JSON.parseObject(json, User.class);
    }
    
    User user = db.queryById(id);
    if (user == null) {
        redis.setex(key, 5 * 60, "null");  // 缓存空值，过期时间短
    } else {
        redis.setex(key, 30 * 60, JSON.toJSONString(user));
    }
    return user;
}
```

```java
// 方案2：布隆过滤器（推荐，适合海量数据）
public class BloomFilterCache {
    private static final BloomFilter<Long> bloom = 
        BloomFilter.create(Funnels.longFunnel(), 1_000_000, 0.01);
    
    public User getUser(Long id) {
        // 1. 先检查布隆过滤器
        if (!bloom.mightContain(id)) {
            return null;  // 一定不存在，直接返回
        }
        
        // 2. 查缓存
        String key = "user:" + id;
        User user = getFromCache(key);
        if (user != null) return user;
        
        // 3. 查 DB
        user = db.queryById(id);
        if (user != null) {
            putToCache(key, user);
            bloom.put(id);  // 布隆过滤器记录
        }
        return user;
    }
}
```

**对比**：

| 方案 | 适用场景 | 缺点 |
|------|---------|------|
| 缓存空值 | 数据量小、更新不频繁 | 大量空值占用内存 |
| 布隆过滤器 | 海量数据、查询不存在多 | 有误判率（可接受）、无法删除 |

---

## 场景 B：缓存击穿（热点 key 过期）

### 现象

```
某一个热点 key 过期瞬间
大量请求同时打到 DB
DB 被打爆
```

### 根因

热点 key 过期瞬间，N 个请求同时发现缓存 miss，都去查 DB。

### 解决方案

```java
// 方案1：互斥锁（简单有效）
public User getUser(Long id) {
    String key = "user:" + id;
    String json = redis.get(key);
    if (json != null) {
        return JSON.parseObject(json, User.class);
    }
    
    // 获取锁，只有一个请求查 DB
    String lockKey = "lock:user:" + id;
    String lockVal = UUID.randomUUID().toString();
    if (redis.setnx(lockKey, lockVal, 10)) {
        try {
            User user = db.queryById(id);
            redis.setex(key, 30 * 60, JSON.toJSONString(user));
            return user;
        } finally {
            // 释放锁时检查是自己加的锁
            if (lockVal.equals(redis.get(lockKey))) {
                redis.del(lockKey);
            }
        }
    } else {
        // 没拿到锁，短暂等待后重试
        Thread.sleep(50);
        return getUser(id);
    }
}
```

```java
// 方案2：逻辑永不过期（推荐，热点数据）
public User getUser(Long id) {
    String key = "user:" + id;
    String json = redis.get(key);
    if (json != null) {
        User user = JSON.parseObject(json, User.class);
        // 检查是否快过期，快过期就异步续命
        if (user != null && isAboutToExpire(key)) {
            refreshAsync(key, id);  // 异步更新，不阻塞
        }
        return user;
    }
    
    User user = db.queryById(id);
    redis.setex(key, 24 * 60 * 60, JSON.toJSONString(user));
    return user;
}
```

---

## 场景 C：缓存雪崩（批量 key 过期/故障）

### 现象

```
大量 key 同时过期
大量请求同时 miss
DB 被打爆
或者：Redis 宕机
所有请求直接打 DB
```

### 根因

1. **批量过期**：大量 key 设置了相同的过期时间
2. **Redis 故障**：主从切换期间请求打到 DB

### 解决方案

```java
// 1. 过期时间加随机偏移量（解决批量过期）
for (String key : keys) {
    redis.setex(key, BASE_TTL + random.nextInt(300), value);
    // 基础 30 分钟 + 0~5 分钟随机偏移
}

// 2. 多级缓存（Redis + 本地缓存）
@Cacheable(cacheNames = "user", key = "#id")
public User getUser(Long id) {
    // 实际查 Redis 或本地缓存
}

// 3. Redis 故障时的降级
public User getUser(Long id) {
    try {
        return getFromRedis(id);
    } catch (RedisException e) {
        // Redis 挂了，降级到 DB（带限流）
        return getFromDbWithRateLimit(id);
    }
}
```

```java
// 4. 服务熔断 + 限流
@RestController
public class UserController {
    @Autowired
    private RateLimiter rateLimiter;
    
    public User getUser(Long id) {
        if (!rateLimiter.tryAcquire()) {
            throw new ServiceUnavailableException("系统繁忙");
        }
        return userService.getUser(id);
    }
}
```

---

## 场景 D：数据一致性问题

### 核心矛盾

```
缓存（Redis）与 DB（MySQL）数据不同步
```

### 解决方案

```java
// 方案1：Cache Aside（最常用）
// 读：先缓存，后 DB
public User getUser(Long id) {
    User user = redis.get("user:" + id);
    if (user == null) {
        user = db.queryById(id);
        redis.setex("user:" + id, 30 * 60, user);
    }
    return user;
}

// 写：先 DB，后删除缓存（注意顺序！）
public void updateUser(User user) {
    db.update(user);
    redis.del("user:" + user.getId());  // 删除缓存，不是更新
    // 下次读取会从 DB 加载新数据到缓存
}
```

```java
// 方案2：延迟双删（解决并发问题）
public void updateUser(User user) {
    db.update(user);
    redis.del("user:" + user.getId());  // 1. 先删缓存
    
    try {
        Thread.sleep(100);  // 2. 等待并发请求写完
    } catch (InterruptedException e) {}
    
    redis.del("user:" + user.getId());  // 3. 再删一次
}
```

```java
// 方案3：订阅 Binlog（Canal，适合大厂）
// MySQL Binlog → Canal → Kafka → 消费更新 Redis
// 保证最终一致，但有延迟
```

**一致性级别对比**：

| 方案 | 一致性 | 延迟 | 复杂度 |
|------|--------|------|--------|
| Cache Aside | 最终一致 | 毫秒级 | 低 |
| 延迟双删 | 最终一致 | 百毫秒级 | 中 |
| Canal + Kafka | 最终一致 | 秒级 | 高 |
| 分布式事务 | 强一致 | 高 | 高 |

---

## 涉及知识点

| 概念 | 所属域 | 关键点 |
|------|--------|--------|
| Redis 数据结构 | 06_中间件/01_Redis | String/Hash/Set 选择 |
| Redis 持久化 | 06_中间件/01_Redis | RDB/AOF 与故障恢复 |
| Redis 主从 | 06_中间件/01_Redis | 哨兵/集群 |
| 布隆过滤器 | 02_并发编程/扩展 | 原理、误判率 |
| 分布式锁 | 07_分布式与架构 | Redisson 实现 |

---

## 追问链

### 追问 1：Redis 和 Memcached 怎么选？

> "Redis 支持更多数据结构（String/Hash/List/Set/ZSet），功能更丰富。Memcached 只有 String，但纯内存、无持久化开销，更简单。如果需要缓存数据结构、持久化、集群，用 Redis。如果只需要简单的 kv 缓存、用完就走，用 Memcached。"

### 追问 2：Redis 内存满了怎么办？

> "1. 配置 `maxmemory-policy` 淘汰策略（volatile-lru/allkeys-lru 等）。2. 热点数据设置过期时间。3. 定期巡检大 key（`redis-cli --bigkeys`）。4. 数据分片（Twemproxy/Codis/Redis Cluster）分散压力。5. 考虑把大 value 存到对象存储（OSS/S3）。"

### 追问 3：怎么保证 Redis 高可用？

> "1. 主从复制（异步复制，可能丢数据）。2. 哨兵模式（自动故障转移）。3. Redis Cluster（数据分片 + 主从）。4. 跨机房部署（两地三中心）。实际选型取决于对可用性和一致性的取舍。"

### 追问 4：热点 key 怎么发现和处理？

> "发现：1. `redis-cli --hotkeys` 监控高频 key。2. 业务埋点上报。处理：1. 多副本分散请求（读写分离）。2. 本地缓存兜底。3. 对热点 key 的 value 拆分（如 userinfo 拆成 base + detail）。"

---

## 排查 Checklist

```
□ 数据不存在？ → 布隆过滤器 或 缓存空值
□ 热点 key 过期？ → 互斥锁 或 逻辑永不过期
□ 批量 key 过期？ → 过期时间加随机偏移
□ Redis 故障？ → 多级缓存 + 服务熔断降级
□ 数据不一致？ → Cache Aside + 延迟双删
□ 大 key 内存占用？ → redis-cli --bigkeys 巡检
□ 热点 key 压力？ → 多副本/本地缓存
□ 需要持久化？ → Redis vs Memcached 选型
```

---

## 我的实战笔记

-（待补充，项目中的真实经历）
