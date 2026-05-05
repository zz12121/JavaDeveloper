# 分布式ID生成

## 这个问题为什么存在？

> 单体时代，数据库自增ID够用。但分布式环境下，**分库分表、多机房部署、数据合并**让自增ID不再适用。问题是：**如何在分布式环境下生成全局唯一、趋势有序、高性能的ID？**

没有分布式ID，你会遇到：
- 分库分表后，两个库的订单ID冲突
- 数据合并时，ID重复导致覆盖
- 业务增长后，ID生成成为性能瓶颈

---

## 它是怎么解决问题的？

### 方案一：UUID/GUID

```
UUID v4：随机生成，36位字符串
格式：550e8400-e29b-41d4-a716-446655440000
```

```java
String id = UUID.randomUUID().toString();
// 优点：本地生成，无网络开销，保证唯一
// 缺点：太长（36字符），无序，作为DB主键索引分裂严重
```

**为什么无序是问题**：B+树索引要求有序插入，无序导致**页分裂**，索引维护成本高。

### 方案二：数据库自增（号段模式优化）

```
原始方案：每次需要ID → 访问数据库 → 获得一个ID（频繁访问DB，瓶颈）
号段模式：每次需要ID → 从内存号段取 → 号段快用完时，异步拉取下一段
```

```java
// 号段模式核心逻辑
public class SegmentIdGenerator {
    private volatile long maxId;   // 号段上限
    private volatile long currentId = 0;
    private final int step = 1000;  // 每次从DB拿1000个

    public long nextId() {
        if (currentId >= maxId) {
            // 号段用完，从DB获取下一段
            maxId = db.getNextSegment(step);
            currentId = maxId - step;
        }
        return ++currentId;
    }
}
```

**美团Leaf** 就是这个思路：DB存号段起始值，应用内存缓存号段，减少DB压力。

### 方案三：雪花算法（Snowflake）

```
ID结构（64位）：
  0 | 41位时间戳 | 10位机器ID | 12位序列号
    |←───────── 毫秒内唯一 ─────────→|
```

```java
public class SnowflakeIdGenerator {
    private final long workerIdBits = 10L;
    private final long maxWorkerId = ~(-1L << workerIdBits); // 1023
    private final long sequenceBits = 12L;
    private final long workerIdShift = sequenceBits;          // 12
    private final long timestampLeftShift = sequenceBits + workerIdBits; // 22

    private long workerId;      // 机器ID（0~1023）
    private long sequence = 0L; // 毫秒内序列号
    private long lastTimestamp = -1L;

    public synchronized long nextId() {
        long timestamp = System.currentTimeMillis();
        if (timestamp < lastTimestamp) {
            throw new RuntimeException("时钟回拨，拒绝生成ID");
        }
        if (timestamp == lastTimestamp) {
            // 同一毫秒内，序列号自增
            sequence = (sequence + 1) & ~(-1L << sequenceBits);
            if (sequence == 0) {
                // 序列号用完，等待下一毫秒
                timestamp = waitNextMillis(lastTimestamp);
            }
        } else {
            sequence = 0;  // 新的毫秒，序列号重置
        }
        lastTimestamp = timestamp;

        return ((timestamp - 1609459200000L) << timestampLeftShift)
                | (workerId << workerIdShift)
                | sequence;
    }
}
```

**核心设计**：用时间戳保证**趋势有序**，用机器ID保证**分布式唯一**，用序列号保证**同一毫秒内不冲突**。

---

## 它和相似方案的本质区别是什么？

| 方案 | 有序性 | 性能 | 依赖外部存储 | 时钟依赖 | 适用场景 |
|---|---|---|---|---|---|
| UUID v4 | ❌ 完全无序 | 高（本地生成） | 无 | 无 | 临时标识，不推荐做主键 |
| 数据库自增 | ✅ 严格有序 | 低（每次访问DB） | MySQL | 无 | 小系统，单库 |
| 号段模式 | ✅ 趋势有序 | 高（内存分配） | MySQL | 无 | 内网系统，Leaf默认方案 |
| 雪花算法 | ✅ 趋势有序 | 极高（无网络IO） | 无 | ✅ 依赖时钟 | 高并发，开源首选 |
| 类雪花（UidGenerator） | ✅ 趋势有序 | 极高 | 无 | ✅ 解决时钟回拨 | 对时钟敏感的场景 |

**本质区别**：
- **有序性**：UUID无序，导致索引分裂；雪花算法有序，索引友好
- **性能瓶颈**：数据库方案瓶颈在DB；雪花算法瓶颈在**时钟精度**（毫秒级）
- **时钟依赖**：雪花算法依赖时钟，时钟回拨是致命问题；数据库方案无此问题

---

## 正确使用方式

### 雪花算法：配置workerId

```yaml
# 方式1：基于ZooKeeper分配workerId（推荐）
# 每个服务启动时，从ZK的/worker-ids节点申请一个序号
worker:
  id: ${zk.worker.id}

# 方式2：基于配置文件（简单但容易冲突）
snowflake:
  worker-id: 1   # 手动配置，扩容时需要规划
```

### Leaf号段模式：双缓冲优化

```
Leaf号段优化：
  当前号段使用到 10% 时，异步加载下一段
  内存中始终有号段可用，避免号段耗尽时阻塞
```

```java
// Leaf核心：双Buffer设计
class DoubleBuffer {
    Segment current;  // 当前号段
    Segment next;     // 下一号段（异步加载中）

    void nextSegment() {
        if (current.getUsage() < 0.1) {
            // 使用到10%，异步加载下一个号段
            asyncLoadNext();
        }
        if (current.isExhausted() && next != null) {
            current = next;  // 切换号段（无感知）
        }
    }
}
```

---

## 边界情况和坑

### 坑1：雪花算法的时钟回拨

```
场景：机器时钟发生了回退（NTP同步、手动修改时间）
后果：可能生成重复ID
```

**解决方案**：
1. **直接抛异常**（Snowflake默认方案）—— 简单，但影响可用性
2. **等待时钟追上来**（Leaf方案）—— 阻塞一段时间，等时钟恢复
3. **用ZooKeeper时间戳**（百度UidGenerator）—— 不用系统时钟，用ZK的时间

### 坑2：号段模式的号段耗尽

```
场景：DB宕机，号段用完，无法获取下一段
后果：服务不可用
```

**解决方案**：
1. **双号段缓冲**（Leaf方案）—— 当前号段用到10%就异步加载下一段
2. **本地文件缓存**（Leaf方案）—— DB宕机时，从本地文件恢复上次的号段

### 坑3：workerId冲突

```
场景：两台机器配置了相同的workerId
后果：生成相同的ID（时间戳+序列号都相同时）
```

**解决方案**：
1. **用ZooKeeper分配workerId**（推荐）—— 由ZK保证唯一
2. **用Redis分配workerId** —— 基于INCR，简单但依赖Redis

---

