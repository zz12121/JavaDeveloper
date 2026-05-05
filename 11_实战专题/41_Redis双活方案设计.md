# Redis双活方案设计

> Redis双活核心：主从同步 + 冲突解决 + 就近读取 + 故障切换。核心矛盾是**跨机房网络延迟高，如何保证数据一致性和高可用**。

---

## Redis 双活架构

```
机房 A（主机房）               机房 B（备机房）
      │                              │
      ▼                              ▼
┌─────────────┐              ┌─────────────┐
│  Redis      │◄───────────►│  Redis      │
│  Cluster A  │  双向同步    │  Cluster B  │
│  (主写)     │              │  (备写)     │
└──────┬──────┘              └──────┬──────┘
       │                            │
       ▼                            ▼
┌─────────────┐              ┌─────────────┐
│  应用 A      │              │  应用 B      │
│  (就近读)   │              │  (就近读)   │
└─────────────┘              └─────────────┘
       │                            │
       └────────────┬───────────────┘
                   │
                   ▼
            ┌──────────┐
            │  DNS     │
            │  GSLB    │  智能调度
            └──────────┘
```

---

## 场景 A：Redis Cluster跨机房部署

### 现象

```
单机房部署，机房故障全不可用
跨机房部署，网络延迟高（1-10ms）
Redis Cluster 默认不支持跨机房感知
需要设计跨机房分片和部署方案
```

### 解决方案

```yaml
# 1. Redis Cluster 跨机房部署方案
# 方案：每个机房部署完整集群，通过双向同步保持数据一致

# 机房 A：Redis Cluster 配置
# redis-cluster-a.conf
port 7000
cluster-enabled yes
cluster-config-file nodes-a.conf
cluster-node-timeout 15000
appendonly yes
save 900 1
save 300 10
save 60 10000

# 机房 B：Redis Cluster 配置（相同）
# redis-cluster-b.conf
port 7000
cluster-enabled yes
cluster-config-file nodes-b.conf
cluster-node-timeout 15000

# 2. 双向同步工具：Redis-Shake 或自定义同步
# Redis-Shake 配置（从 A 同步到 B）
conf:
  source:
    type: standalone  # 或 cluster
    address: "redis-a-master1:7000"
    password: "xxx"
  
  target:
    type: cluster
    address: "redis-b-master1:7000,redis-b-master2:7000"
    password: "xxx"
  
  # 同步模式：全量 + 增量
  mode: all  # all=全量+增量, incremental=只增量
  
  # 过滤规则
  filter:
    # 不同步内部 key（如 _redis_cluster_）
    ignore_key_prefix:
      - "_"
      - "tmp:"
```

```java
// 3. 自定义双向同步（伪代码）
@Component
public class RedisReplicationManager {
    
    @Autowired
    private RedisTemplate<String, String> redisA;
    
    @Autowired
    private RedisTemplate<String, String> redisB;
    
    // 监听 Redis A 的 keyspace 通知，同步到 B
    @PostConstruct
    public void startSyncAtoB() {
        // 订阅 A 的 __keyevent@0__:set/del 等事件
        redisA.getConnectionFactory().getConnection()
                .pSubscribe(new MessageListener() {
                    @Override
                    public void onMessage(Message message, byte[] pattern) {
                        String key = new String(message.getBody());
                        String event = new String(pattern);
                        
                        // 同步到 B（如果是 A 写入的）
                        if (shouldSyncToB(key, event)) {
                            syncKeyToB(key);
                        }
                    }
                }, "__keyevent@*__:*".getBytes());
    }
    
    // 同步 key 到 B
    private void syncKeyToB(String key) {
        // 1. 获取 key 在 A 的值
        String value = redisA.opsForValue().get(key);
        String type = redisA.type(key);
        
        // 2. 根据类型同步到 B
        if ("string".equals(type)) {
            redisB.opsForValue().set(key, value);
        } else if ("hash".equals(type)) {
            Map<String, String> map = redisA.opsForHash().entries(key);
            redisB.opsForHash().putAll(key, map);
        }
        // ... 其他类型
    }
}
```

**跨机房部署方案对比**：
- **方案1**：两套独立集群 + 双向同步（推荐，灵活）
- **方案2**：跨机房混部（延迟高，不推荐）
- **方案3**：主从交叉部署（运维复杂，慎用）

---

## 场景 B：数据同步延迟与冲突解决

### 现象

```
机房 A 写入，机房 B 读取，可能读到旧值（延迟 1-10ms）
机房 A 和 B 同时写入同一 key → 数据冲突
网络分区，双向同步中断，数据不一致
```

### 解决方案

```java
// 1. 冲突解决：版本号（Vector Clock 简化版）
// 每个 key 带版本号，解决冲突时取版本高的
@Service
public class VersionedRedisService {
    
    private static final String VERSION_PREFIX = "_ver:";
    
    // 写入时带版本号（CAS 语义）
    public boolean putWithVersion(String key, String value, int expectedVersion) {
        String versionKey = VERSION_PREFIX + key;
        
        // Lua 脚本：原子更新（版本检查 + 写入 + 版本+1）
        String luaScript = 
            "local currentVer = redis.call('GET', KEYS[2]) " +
            "if (not currentVer or tonumber(currentVer) == tonumber(ARGV[1])) then " +
            "   redis.call('SET', KEYS[1], ARGV[2]) " +
            "   redis.call('SET', KEYS[2], tonumber(ARGV[1]) + 1) " +
            "   return 1 " +
            "else " +
            "   return 0 " +  // 版本冲突
            "end";
        
        RedisScript<Long> script = new DefaultRedisScript<>(luaScript, Long.class);
        Long result = redisTemplate.execute(script, 
                Arrays.asList(key, versionKey), 
                String.valueOf(expectedVersion), value);
        
        return result == 1;
    }
    
    // 读取时返回值和版本
    public ValueWithVersion getWithVersion(String key) {
        String versionKey = VERSION_PREFIX + key;
        
        // 用 Lua 保证读取的原子性
        String luaScript = 
            "return {redis.call('GET', KEYS[1]), redis.call('GET', KEYS[2])}";
        
        RedisScript<List> script = new DefaultRedisScript<>(luaScript, List.class);
        List<Object> result = redisTemplate.execute(script, 
                Arrays.asList(key, versionKey));
        
        String value = (String) result.get(0);
        Integer version = Integer.valueOf((String) result.get(1));
        
        return new ValueWithVersion(value, version);
    }
}

// 2. 冲突解决：时间戳（最后写入胜出）
// 写入时带时间戳，冲突时取时间戳大的
public class TimestampedRedisService {
    
    // 写入：value 格式为 "timestamp|actual_value"
    public void putWithTimestamp(String key, String value) {
        long timestamp = System.currentTimeMillis();
        String tsValue = timestamp + "|" + value;
        // 写入到本机房
        localRedis.set(key, tsValue);
        // 异步同步到对端（带时间戳）
        syncToRemote(key, tsValue);
    }
    
    // 同步到对端时，比较时间戳
    public void syncToRemote(String key, String tsValue) {
        // 对端用 Lua 脚本比较时间戳，只更新更晚的时间戳
        String luaScript = 
            "local current = redis.call('GET', KEYS[1]) " +
            "if (not current) then " +
            "   redis.call('SET', KEYS[1], ARGV[1]) " +
            "   return 1 " +
            "end " +
            "local currentTs = tonumber(string.match(current, '^(%d+)|')) " +
            "local newTs = tonumber(string.match(ARGV[1], '^(%d+)|')) " +
            "if (newTs > currentTs) then " +
            "   redis.call('SET', KEYS[1], ARGV[1]) " +
            "   return 1 " +
            "else " +
            "   return 0 " +  // 时间戳旧的，不更新
            "end";
        
        remoteRedis.execute(new DefaultRedisScript<>(luaScript), 
                Collections.singletonList(key), tsValue);
    }
}
```

**同步延迟优化**：
- **同机房优先**：写入本机房，同步对端（1-2ms）
- **监控延迟**：`redis-cli info replication` 查看 `master_link_status`
- **容忍延迟**：读操作允许短暂不一致（CAP 理论，选 AP）

---

## 场景 C：就近读取策略

### 现象

```
应用部署在多个机房
读取 Redis 时，跨机房访问（延迟 10-50ms）
用户体验差，RT 变高
应该就近读取本机房 Redis
```

### 解决方案

```java
// 1. 就近读取：根据机房路由 Redis 连接
@Service
public class RegionalRedisService {
    
    // 按机房注入不同的 RedisTemplate
    @Autowired
    @Qualifier("redisA")
    private RedisTemplate<String, String> redisA;
    
    @Autowired
    @Qualifier("redisB")
    private RedisTemplate<String, String> redisB;
    
    // 获取当前机房的 Redis（就近读取）
    public RedisTemplate<String, String> getLocalRedis() {
        String localRegion = System.getProperty("region");  // 启动时指定 -Dregion=A
        if ("B".equals(localRegion)) {
            return redisB;
        }
        return redisA;  // 默认 A
    }
    
    // 读取：就近
    public String get(String key) {
        return getLocalRedis().opsForValue().get(key);
    }
    
    // 写入：双写（或只写主机房，由同步工具复制到备机房）
    public void put(String key, String value) {
        String localRegion = System.getProperty("region");
        
        if ("A".equals(localRegion)) {
            // 主机房：写本地 + 异步写备机房
            redisA.opsForValue().set(key, value);
            asyncWriteToRemote(redisB, key, value);
        } else {
            // 备机房：写本地 + 异步写主机房（双向写）
            redisB.opsForValue().set(key, value);
            asyncWriteToRemote(redisA, key, value);
        }
    }
    
    private void asyncWriteToRemote(
            RedisTemplate<String, String> remoteRedis, 
            String key, String value) {
        // 异步写入，不阻塞主流程
        CompletableFuture.runAsync(() -> {
            try {
                remoteRedis.opsForValue().set(key, value);
            } catch (Exception e) {
                log.error("异步写远程Redis失败: key={}", key, e);
                // 记录失败，待重试（如放入 MQ）
            }
        });
    }
}
```

```java
// 2. DNS/GSLB 智能调度：用户就近接入
// DNS 配置：根据用户 IP 返回最近的机房入口
// 示例：使用 AWS Route53 或阿里云 DNS 的智能解析

// 应用层：健康检查和故障切换
@Component
public class RedisHealthChecker {
    
    @Scheduled(fixedRate = 5000)  // 每5秒检查一次
    public void checkHealth() {
        checkRedisHealth("A", redisA);
        checkRedisHealth("B", redisB);
    }
    
    private void checkRedisHealth(String region, RedisTemplate<String, String> redis) {
        try {
            String result = redis.execute((RedisCallback<String>) connection -> {
                connection.ping();
                return "PONG";
            });
            
            if (!"PONG".equals(result)) {
                onRedisDown(region);
            }
        } catch (Exception e) {
            onRedisDown(region);
        }
    }
    
    // Redis 故障：切换读取到健康机房
    private void onRedisDown(String region) {
        log.error("Redis {} 故障，切换读取到另一机房", region);
        // 更新路由表：强制所有读取走健康机房
        routingTable.markDown(region);
    }
}
```

---

## 场景 D：故障切换

### 现象

```
机房 A 故障（断网、断电、火灾）
应用无法连接机房 A 的 Redis
需要自动切换到机房 B
切换过程要快（秒级），数据不丢
```

### 解决方案

```java
// 1. 故障检测与自动切换
@Component
public class RedisFailoverManager {
    
    private volatile String activeRegion = "A";  // 当前活跃机房
    private final Object lock = new Object();
    
    @Autowired
    private RedisTemplate<String, String> redisA;
    
    @Autowired
    private RedisTemplate<String, String> redisB;
    
    // 获取当前可用的 Redis（故障时自动切换）
    public RedisTemplate<String, String> getActiveRedis() {
        String current = activeRegion;  // volatile 读，保证可见性
        
        if ("A".equals(current)) {
            if (isHealthy(redisA)) {
                return redisA;
            }
            // A 故障，切换到 B
            switchToRegion("B");
            return redisB;
        } else {
            if (isHealthy(redisB)) {
                return redisB;
            }
            // B 也故障（极端情况），切回 A（可能恢复了）
            switchToRegion("A");
            return redisA;
        }
    }
    
    // 切换机房（带锁，防止并发切换）
    private void switchToRegion(String newRegion) {
        synchronized (lock) {
            if (!newRegion.equals(activeRegion)) {
                log.warn("Redis 故障切换：{} -> {}", activeRegion, newRegion);
                activeRegion = newRegion;
                // 触发告警
                alarmService.send("Redis 已切换到机房 " + newRegion);
            }
        }
    }
    
    private boolean isHealthy(RedisTemplate<String, String> redis) {
        try {
            redis.execute((RedisCallback<Boolean>) connection -> {
                connection.ping();
                return true;
            });
            return true;
        } catch (Exception e) {
            return false;
        }
    }
}

// 2. 数据补偿：故障恢复后同步丢失的数据
// 方案：写入时记录 WAL（Write-Ahead Log）到 MQ
@Component
public class WalWriter {
    
    @Autowired
    private RocketMQTemplate mqTemplate;
    
    // 写入 Redis 前，先写 WAL 到 MQ
    public void putWithWal(String key, String value) {
        // 1. 构造 WAL 消息
        WalMsg msg = new WalMsg(key, value, System.currentTimeMillis());
        
        // 2. 发送到 MQ（为了高可靠，用事务消息）
        TransactionSendResult result = mqTemplate.sendMessageInTransaction(
                "topic_redis_wal", msg, null);
        
        if (result.getLocalTransactionState() == LocalTransactionState.COMMIT_MESSAGE) {
            // 3. 写入 Redis
            redisTemplate.opsForValue().set(key, value);
        }
    }
}

// 3. 故障恢复后，消费 WAL 补齐数据
@Component
@RocketMQMessageListener(
        topic = "topic_redis_wal",
        consumerGroup = "redis_wal_consumer"
)
public class WalConsumer implements RocketMQListener<WalMsg> {
    
    @Override
    public void onMessage(WalMsg msg) {
        // 故障恢复后，回放 WAL，补齐丢失的数据
        try {
            redisTemplate.opsForValue().set(msg.getKey(), msg.getValue());
        } catch (Exception e) {
            log.error("WAL 回放失败", e);
            throw new RuntimeException(e);  // 重试
        }
    }
}
```

**故障切换策略**：
- **检测**：每 5 秒 ping（或心跳）
- **切换**：连续 3 次失败 → 自动切换（15秒）
- **恢复**：原机房恢复后，手动切回（避免频繁切换）

---

## 核心参数估算

```
双活延迟估算：
  同城双活：1-2ms 延迟，可忽略
  异地双活：10-50ms 延迟，需要就近读取
  
吞吐量：
  单 Redis 分片：10万 QPS
  双活集群：每机房 10 分片 → 100万 QPS/机房
  
故障切换时间：
  检测：5s × 3 = 15s
  切换：1s（更新路由表）
  总 RTO（恢复时间目标）：< 20s
  
数据丢失（RPO）：
  主机房故障瞬间，可能有 0-1s 数据未同步 → RPO < 1s
```

---

## 涉及知识点

| 概念 | 所属域 | 关键点 |
|------|--------|--------|
| Redis Cluster | 06_中间件/01_Redis | 分片、主从、故障转移 |
| Redis Replication | 06_中间件/01_Redis | 主从同步、PSYNC、复制偏移量 |
| 冲突解决 | 07_分布式与架构/04_分布式事务 | 版本号、时间戳、最后写入胜出 |
| GSLB/DNS | 07_分布式与架构/03_高并发 | 智能调度、就近接入 |
| 故障切换 | 07_分布式与架构/02_高可用 | 健康检查、自动切换、RTO/RPO |

---

## 追问链

### 追问 1：双活和主备有什么区别？

> "**主备**：主机房读写，备机房只读（或全备）。主机房故障，备机房接管（需要手动或自动切换）。**双活**：两个机房都可读写，互相备份。双活更复杂（要解决冲突），但 RTO 更短（就近读取无需切换）。"

### 追问 2：双写会不会导致数据不一致？

> "会。解决方案：1. **版本号**：写时带版本，冲突时取版本高的。2. **时间戳**：冲突时取时间戳新的。3. **单一写入点**：只有主机房可写，备机房只同步（降级为主备）。4. **业务层去重**：用业务唯一键（如订单号）识别重复数据。"

### 追问 3：跨机房延迟怎么解决？

> "架构优化：1. **就近读写**：应用读本机房 Redis（1-2ms），写操作也优先本机房。2. **异步同步**：写本机房成功即返回，异步同步到对端（容忍短暂不一致）。3. **终极方案**：单元化部署，用户流量按 UID 分片到固定机房，完全避免跨机房（推荐）。"

### 追问 4：Redis 故障切换期间数据会丢吗？

> "取决于方案：1. **双写（双向同步）**：故障切换不会丢数据（两边都有完整数据）。2. **主备（单向同步）**：主机房故障，备机房可能丢最后 1-2 秒数据（未同步部分）。3. **WAL 补偿**：写 Redis 前先写 MQ（WAL），故障恢复后回放补齐。"

---

## 排查 Checklist

```
□ 双活同步正常吗？ → 检查双向同步工具状态
□ 同步延迟多大？ → master_link_status / 复制偏移量
□ 冲突有解决吗？ → 版本号/时间戳机制生效
□ 就近读取生效吗？ → 监控跨机房访问量
□ 故障切换测试了吗？ → 模拟机房 A 故障，验证自动切换
□ 切换时间 < 20s 吗？ → 检查 RTO
□ 数据丢失 < 1s 吗？ → 检查 RPO
□ DNS/GSLB 配置正确吗？ → 用户就近接入测试
□ WAL 补偿机制启用吗？ → MQ 消费延迟监控
```

---

## 我的实战笔记

-（待补充，项目中的真实经历）
