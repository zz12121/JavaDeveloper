# Redis分布式锁实现

## 这个问题为什么存在？

> 分布式环境下，多个服务实例要互斥访问同一资源（如扣库存、定时任务），单机锁（synchronized）完全失效。Redis基于内存、高性能、支持原子操作，是**分布式锁的首选方案**。

但Redis分布式锁有很多坑：锁超时、释放了别人的锁、主从切换锁丢失。问题是：**怎么正确地用Redis实现分布式锁？**

---

## 它是怎么解决问题的？

### 核心机制：SET NX EX 一条命令

```
加锁：
  SET lock:order:123 <uuid> NX EX 30
  → key不存在才设置成功（互斥性）
  → 30秒后自动过期（防止死锁）

释放锁：
  先比较value（是不是自己加的锁）
  再删除key
  → 必须用Lua脚本保证原子性
```

```java
// ❌ 错误：两步操作，不是原子的
String value = UUID.randomUUID().toString();
if ("OK".equals(jedis.set("lock:key", value, "NX", "EX", 30))) {
    // 业务执行...
    // 问题：这里如果GC停顿超过30秒，锁已经超时
    // 别的客户端已经加了新锁，这里会删除别人的锁！
    if (value.equals(jedis.get("lock:key"))) {
        jedis.del("lock:key");  // 非原子操作，可能删除别人的锁
    }
}

// ✅ 正确：用Lua脚本，原子操作
String lua = """
    if redis.call('get', KEYS[1]) == ARGV[1] then
        return redis.call('del', KEYS[1])
    else
        return 0
    end
    """;
jedis.eval(lua, Collections.singletonList("lock:key"),
                Collections.singletonList(value));
```

**为什么要用Lua脚本**：`GET` + `DEL` 是两步操作，中间可能被打断（GC、网络延迟），导致删除别人的锁。

### watchdog：自动续期，解决"锁超时但业务没执行完"

```
T0: 加锁成功，超时30秒
T10: watchdog线程启动，检查锁是否还持有
T20: 锁还剩10秒，watchdog自动续期到30秒
T30: 业务执行完，释放锁，watchdog停止
```

```java
// Redisson的watchdog机制（简化版）
public class Watchdog {
    private final ScheduledExecutorService executor =
            Executors.newSingleThreadScheduledExecutor();
    private final String key;
    private final String value;
    private volatile boolean running = true;

    public void start() {
        executor.scheduleAtFixedRate(() -> {
            if (!running) return;
            // 锁还存在，且是当前客户端的，就续期
            String lua = """
                if redis.call('get', KEYS[1]) == ARGV[1] then
                    return redis.call('expire', KEYS[1], ARGV[2])
                else
                    return 0
                end
                """;
            jedis.eval(lua,
                    Collections.singletonList(key),
                    Arrays.asList(value, "30"));
        }, 10, 10, TimeUnit.SECONDS);  // 每10秒续期一次
    }

    public void stop() {
        running = false;
    }
}
```

### Redlock：多节点加锁（解决主从切换锁丢失）

```
单节点问题：
  客户端A在master加锁成功 → master挂了，还没同步给slave
  → slave晋升为master → 客户端B也能加锁成功 → 两个客户端同时持有锁！

Redlock解决方案：
  向N个独立Redis节点加锁（无主从关系）
  超过半数（N/2+1）成功，才认为加锁成功
```

```java
// Redlock算法（简化逻辑）
public boolean tryLockRedlock(List<Jedis> nodes, String key, String value, int expireSeconds) {
    int successes = 0;
    long startTime = System.currentTimeMillis();

    for (Jedis node : nodes) {
        try {
            String result = node.set(key, value, "NX", "EX", expireSeconds);
            if ("OK".equals(result)) successes++;
        } catch (Exception e) {
            // 节点不可用，跳过
        }
    }

    long elapsedTime = System.currentTimeMillis() - startTime;
    // 超过半数成功，且总耗时小于锁超时时间（锁还有效）
    return successes >= nodes.size() / 2 + 1
            && elapsedTime < expireSeconds * 1000;
}
```

**Redlock争议**：Martin Kleppmann（DDIA作者）认为Redlock不可靠（系统时钟问题），Antirez（Redis作者）反驳。实际生产中，**大部分场景不需要Redlock**，用单节点 + watchdog足够。

---

## 它和相似方案的本质区别是什么？

已在`分布式锁原理.md`中详细对比，核心区别：

- **Redis锁**：性能极高，但主从切换可能丢锁
- **ZooKeeper锁**：CP系统，强一致，不会丢锁，但性能差
- **数据库锁**：最简单，但性能最差

**Redis锁内部对比：单节点 vs Redlock**

| | 单节点Redis锁 | Redlock |
|---|---|---|
| 性能 | 极高（1次RTT） | 低（N次RTT） |
| 可靠性 | 主从切换可能丢锁 | 不会丢锁（多数派确认） |
| 复杂度 | 低 | 高（需要多个独立节点） |
| 时钟依赖 | 无 | 有（依赖系统时钟） |
| 适用场景 | 大部分业务（可接受偶尔丢锁） | 对一致性要求极高的场景 |

---

## 正确使用方式

### 推荐：直接用Redisson客户端

```java
// Redisson封装了所有细节：加锁、watchdog、释放锁
RLock lock = redissonClient.getLock("lock:order:123");

try {
    // 加锁，30秒超时，watchdog自动续期
    lock.lock(30, TimeUnit.SECONDS);
    // 业务处理...
    processOrder();
} finally {
    if (lock.isHeldByCurrentThread()) {
        lock.unlock();  // 释放锁，停止watchdog
    }
}
```

### 手动实现：严格遵循"加锁用SET NX EX，释放用Lua"

```java
public class RedisDistributedLock {
    private final Jedis jedis;
    private final String key;
    private final String value = UUID.randomUUID().toString();

    public boolean lock(long expireSeconds) {
        String result = jedis.set(key, value, "NX", "EX", expireSeconds);
        return "OK".equals(result);
    }

    public void unlock() {
        String lua = """
            if redis.call('get', KEYS[1]) == ARGV[1] then
                return redis.call('del', KEYS[1])
            else
                return 0
            end
            """;
        jedis.eval(lua, Collections.singletonList(key),
                        Collections.singletonList(value));
    }
}
```

---

## 边界情况和坑

### 坑1：锁超时，但业务没执行完

```
场景：
  T0: 加锁成功，超时30秒
  T20: 发生Full GC，停顿了15秒
  T35: GC结束，业务继续 → 但锁已经超时被删除了！
  T36: 业务执行完，调用unlock() → 删除了别人的锁！
```

**解决方案**：
1. **watchdog自动续期**（推荐，Redisson默认开启）
2. **锁超时时间设长一点**（如60秒），但治标不治本
3. **业务幂等**（最终兜底，就算重复执行也不出问题）

### 坑2：Redis主从切换导致锁丢失

```
场景：
  客户端A在master加锁成功
  master还没同步给slave，就挂了
  slave晋升为新master，客户端B在新master上加锁成功
  → 两个客户端同时持有锁！
```

**解决方案**：
1. **接受风险**（大部分业务可以容忍，锁的是"偶尔重复执行"）
2. **用ZooKeeper锁**（CP系统，强一致，不会丢锁）
3. **用Redlock**（但性能差，且有时钟依赖问题）

### 坑3：value不是唯一标识，释放了别人的锁

```
场景：
  客户端A加锁成功，value="uuid-A"
  客户端A业务执行慢，锁超时了
  客户端B加锁成功，value="uuid-B"
  客户端A业务执行完，调用unlock()
  → 如果直接del，会把客户端B的锁删了！
```

**解决方案**：
1. **加锁时value用UUID**（每个客户端唯一）
2. **释放锁时用Lua脚本**，先比较value再删除

---

