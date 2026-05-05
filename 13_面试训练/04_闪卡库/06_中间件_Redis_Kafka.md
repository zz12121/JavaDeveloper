# 闪卡库：06_中间件_Redis_Kafka

> 使用说明：本闪卡库涵盖 Redis 与 Kafka 核心知识点，可导入 Obsidian Spaced Repetition 插件或 Anki。

---

## 1. Redis 数据结构

**Q: Redis 的 SDS 相比 C 字符串有哪些优势？**

**A:**
SDS（Simple Dynamic String）是 Redis 的自定义字符串结构：
```
struct sdshdr {
    int len;      // 已使用字节数 O(1) 获取长度
    int free;     // 剩余空间
    char buf[];   // 字节数组
}
```

优势：
1. **O(1) 获取长度**：`len` 字段记录，C 字符串需要遍历 O(n)
2. **杜绝缓冲区溢出**：修改前检查 `free` 空间，不够自动扩容
3. **减少内存重分配**：空间预分配（双倍扩容）+ 惰性空间释放
4. **二进制安全**：不依赖 `\0` 判断结尾，可存任意二进制数据
5. **兼容 C 字符串**：`buf` 末尾存 `\0`，可复用部分 C 字符串函数

**Tags:** #Redis #SDS #数据结构

---

**Q: Redis 的底层数据结构有哪些？分别用在什么场景？**

**A:**
| 数据结构 | 底层实现 | 典型使用 |
|---------|---------|---------|
| String | int / embstr / raw | 计数器、缓存、分布式锁 |
| List | quicklist（3.2+） | 消息队列、时间线 |
| Hash | ziplist / hashtable | 对象存储（用户资料） |
| Set | intset / hashtable | 标签、共同好友 |
| ZSet | ziplist / skiplist+dict | 排行榜、延迟队列 |
| Bitmap | SDS（位操作） | 签到、活跃用户统计 |
| HyperLogLog | 12KB 数据结构 | UV 统计（去重计数） |
| Stream | Rax 树 + Listpack | 消息队列（类似 Kafka） |

关键设计：
- **ziplist**（紧凑数组）：小数据量时节省内存，数据增大后自动转成 hashtable/skiplist
- **skiplist**（跳表）：ZSet 的有序实现，范围查询 O(log n)

**Tags:** #Redis #数据结构 #底层实现

---

**Q: 跳表的原理？为什么 ZSet 用跳表而不是红黑树？**

**A:**
跳表是**多层有序链表**，每层是下一层的"快速通道"：
```
L3: 1 → 9
L2: 1 → 5 → 9
L1: 1 → 3 → 5 → 7 → 9
L0: 1 → 2 → 3 → 4 → 5 → 6 → 7 → 8 → 9
```
查找过程：从最高层开始，向右走到下一个更大值就下降一层，平均 O(log n)。

**Redis 选跳表的原因：**
1. **范围查询友好**：跳表找到范围起点后，沿着最底层链表遍历即可
2. **实现简单**：跳表层数随机生成，代码量远小于红黑树
3. **内存友好**：跳表节点包含多层指针，但 ZSet 场景内存开销可接受

**Tags:** #Redis #跳表 #ZSet

---

## 2. Redis 持久化

**Q: RDB 和 AOF 的区别？各自优缺点？**

**A:**
```
RDB（Redis Database Backup）：
  - 定时生成内存快照，存为 .rdb 二进制文件
  - 触发：SAVE（阻塞）/ BGSAVE（fork 子进程）
  - 恢复快，但会丢失两次快照之间的数据

AOF（Append Only File）：
  - 记录每一条写命令，以 Redis 协议格式追加到文件
  - 刷盘策略：always（每条都fsync）/ everysec（每秒，推荐）/ no（依赖OS）
  - AOF 重写：定期合并冗余命令
```

对比：
| 维度 | RDB | AOF |
|------|-----|-----|
| 恢复速度 | 快 | 慢（重放命令） |
| 数据丢失 | 可能丢失较多 | 最多丢 1 秒 |
| 文件大小 | 小（二进制压缩） | 大（文本协议） |

**生产推荐**：混合持久化（Redis 4.0+）
- `aof-use-rdb-preamble yes`
- AOF 重写时，先写 RDB 快照，再追加 AOF 增量命令

**Tags:** #Redis #RDB #AOF #持久化

---

## 3. Redis 主从与高可用

**Q: Redis 主从复制的全量同步和增量同步流程？**

**A:**
```
全量同步（第一次或偏移量不在复制积压缓冲区）：
  1. slave 发送 PSYNC ? -1
  2. master 返回 +FULLRESYNC <replid> <offset>
  3. master fork 子进程生成 RDB 快照
  4. master 将 RDB 发给 slave
  5. slave 清空旧数据，加载 RDB
  6. master 将复制缓冲区中的写命令发给 slave（增量追赶）

增量同步（slave 断线重连）：
  1. slave 发送 PSYNC <replid> <offset>
  2. master 检查 repl_backlog_buffer 中是否有该 offset 之后的数据
     → 有：发送 +CONTINUE，增量同步
     → 没有：发送 +FULLRESYNC，全量同步
```

关键配置：`repl-backlog-size`（复制积压缓冲区大小）和 `repl-diskless-sync`（无盘复制）

**Tags:** #Redis #主从复制 #PSYNC

---

**Q: 哨兵（Sentinel）的工作原理？**

**A:**
Sentinel 是 Redis 高可用方案，监控 master 并在故障时自动切换：
```
三个核心功能：
  1. 监控（Monitoring）：每秒向 master/slave 发送 PING
  2. 通知（Notification）：实例不可达时通知管理员
  3. 自动故障转移（Automatic Failover）：master 下线后，选一个 slave 升为 master

故障判定：
  - 主观下线（SDOWN）：单个 Sentinel 发现超时
  - 客观下线（ODOWN）：多个 Sentinel 达成共识
  - 选 leader Sentinel 执行故障转移（Raft 算法）
```

**Tags:** #Redis #Sentinel #高可用 #故障转移

---

**Q: Redis Cluster 的槽位是怎么分配和迁移的？**

**A:**
Redis Cluster 有 **16384 个槽位**，每个 key 通过 CRC16 算法映射到槽位：
```
HASH_SLOT = CRC16(key) % 16384
```

**迁移流程**：
```
1. 目标节点设置 importing 状态
2. 源节点设置 migrating 状态
3. 源节点逐个迁移 slot 上的 key（MIGRATE 命令）
4. 所有 slot 迁移完成后，通知集群更新槽位映射
```

**重定向机制**：
- **MOVED**：槽位永久迁移，客户端更新缓存
- **ASK**：槽位正在迁移，临时重定向（不更新客户端缓存）

**Tags:** #Redis #Cluster #槽位 #数据迁移

---

## 4. 缓存问题

**Q: 缓存穿透、击穿、雪崩的区别与解决方案？**

**A:**
```
穿透：请求不存在的数据，缓存和 DB 都没有
击穿：热点 key 过期瞬间，大量请求直击 DB
雪崩：大量 key 同时过期，或缓存服务宕机
```

| 问题 | 解决方案 |
|------|---------|
| 穿透 | 1. 布隆过滤器过滤无效 key<br>2. 缓存空值（TTL 短）<br>3. 接口层参数校验 |
| 击穿 | 1. 热点 key 不设过期时间<br>2. 互斥锁<br>3. 逻辑过期：异步更新 |
| 雪崩 | 1. 过期时间加随机值（错峰过期）<br>2. 多级缓存<br>3. 缓存集群高可用 |

**Tags:** #Redis #缓存穿透 #缓存击穿 #缓存雪崩

---

**Q: 布隆过滤器的原理？误判率怎么控制？**

**A:**
布隆过滤器用**二进制数组 + 多个哈希函数**判断元素是否存在：
```
添加：k 个哈希函数计算 → k 个位置 → 设为 1
查询：检查 k 个位置
  → 全部为 1？可能存在（有误判率）
  → 有一个为 0？一定不存在
```

**误判率公式**：
```
P ≈ (1 - e^(-kn/m))^k
  m = 位数组大小
  n = 预计元素数量
  k = 哈希函数个数
```

Redis 中使用：`BF.RESERVE myfilter 0.01 100000`（误判率 1%，预计 10 万元素）

**Tags:** #Redis #布隆过滤器 #缓存穿透

---

## 5. 分布式锁

**Q: Redis 分布式锁的正确实现？Redlock 的问题？**

**A:**
**基础版**：`SET lock_key unique_value NX PX 30000`

**Redlock 算法**：
```
1. 客户端获取当前时间戳 T1
2. 依次向 N 个独立的 Redis master 发送 SET NX PX 命令
3. 计算获取锁耗时 = T2 - T1
4. 当且仅当：成功获取超过半数（N/2+1）的锁，且总耗时 < 锁超时时间 → 成功
5. 锁的有效时间 = 初始超时时间 - 获取锁耗时
```

**Redlock 的争议（Martin Kleppmann 批评）**：
- 依赖系统时钟（时钟漂移会导致锁失效）
- 发生 GC STW 或网络延迟时，锁可能提前过期

**生产推荐**：Redisson 的 `RLock`，内置 watchdog 续租 + Lua 脚本原子操作

**Tags:** #Redis #分布式锁 #Redlock #Redisson

---

## 6. Redis 线程模型

**Q: Redis 为什么单线程还这么快？Redis 6.0 的多线程是怎么回事？**

**A:**
**Redis 单线程快的原因**：
1. **纯内存操作**：纳秒级延迟
2. **IO 多路复用**：epoll/kqueue，单线程处理大量并发连接
3. **避免上下文切换**：单线程无锁竞争
4. **高效数据结构**：SDS、跳表、hashtable 都是 O(1) 或 O(log n)

**Redis 6.0 多线程（IO 多线程）**：
- **命令执行仍然是单线程**（保证原子性）
- **网络 IO 改为多线程**：解析命令、写回结果并行处理
- 配置：`io-threads 4`（建议 CPU 核数，不超过 8）

**Tags:** #Redis #单线程 #IO多路复用 #多线程

---

## 7. Kafka 基础架构

**Q: Kafka 的架构核心概念？**

**A:**
```
核心概念：
  Broker      — Kafka 服务器节点
  Topic       — 消息主题（逻辑分类）
  Partition   — Topic 的物理分片，提高并行度
  Replica     — Partition 的副本（高可用）
  Leader      — 负责读写的主副本
  Follower    — 从 Leader 同步数据的副本
  ISR         — In-Sync Replicas（与 Leader 保持同步的副本集合）
  Consumer Group — 消费者组，组内每个 Partition 只被一个 Consumer 消费
```

**Tags:** #Kafka #架构 #核心概念

---

**Q: Kafka 的高吞吐量是怎么做到的？**

**A:**
Kafka 高吞吐的四大设计：
```
1. 顺序写磁盘：消息追加到 log 文件末尾，利用 OS Page Cache
2. 零拷贝（Zero-Copy）：sendfile() 系统调用，数据不经过应用层
3. 批量操作：producer 批量发送，consumer 批量拉取
4. 消息压缩：producer 端压缩（snappy/gzip/lz4/zstd）
5. 分区并行：多个 Partition 可以并行生产和消费
```

Kafka 单机能做到每秒几十万条消息吞吐。

**Tags:** #Kafka #高吞吐 #零拷贝 #顺序写

---

## 8. Kafka 消息可靠性

**Q: Kafka 的消息丢失场景与解决方案？**

**A:**
**可能丢失消息的场景**：
```
Producer 端：
  - acks=0：不等待 broker 确认，直接丢失
  - acks=1：只等 leader 写入，leader 宕机且未同步给 follower → 丢失

Broker 端：
  - leader 宕机，follower 还没同步 → 数据丢失
  - 异步刷盘，宕机时 page cache 中数据丢失

Consumer 端：
  - 自动提交 offset，消费失败但 offset 已提交
```

**最强可靠性配置**：
```
Producer：acks=all, retries=Integer.MAX_VALUE, max.in.flight.requests.per.connection=1
Broker：replication.factor>=3, min.insync.replicas>1
Consumer：关闭自动提交，手动提交 offset
```

**Tags:** #Kafka #消息丢失 #可靠性

---

**Q: Kafka 怎么保证消息不重复消费（幂等性）？**

**A:**
**重复消费的原因**：
- consumer 消费成功但未提交 offset → 重启后重新消费
- 分区 rebalance → 分区分配给其他 consumer → 可能重复消费

**解决方案（多级防御）**：
```
1. Producer 幂等性（Kafka 0.11+）
   enable.idempotence = true
   → 每个 producer 有唯一 PID + 序列号
   → broker 缓存 (PID, seq) 去重

2. 业务幂等（最可靠）
   → 消费者端用唯一业务 ID 去重
   → Redis SET NX / 数据库唯一索引 / 乐观锁版本号

3. 事务消息（EOS）
   → isolation.level = read_committed
   → producer 开启事务：begin → send → commit
```

**Tags:** #Kafka #幂等性 #重复消费 #EOS

---

**Q: Kafka 怎么保证消息顺序？**

**A:**
**Kafka 的顺序保证层级**：
```
1. 全局有序 → ❌ Kafka 不支持（多 partition 并行）
2. 分区有序 → ✅ 同一个 partition 内消息有序
3. 局部有序 → ✅ 相同 key 的消息路由到同一 partition
```

**实现方案**：
```
方案一：单 partition（简单但失去并行度）
  → Topic 只设一个 partition

方案二：相同 key 路由到同一 partition（推荐）
  → producer.send(new ProducerRecord<>(topic, orderId, message))
  → hash(key) % numPartitions → 相同 key 进同一分区

保证同一分区内有序：
  max.in.flight.requests.per.connection = 1
  → 禁用 producer 并发发送，确保顺序
```

**Tags:** #Kafka #消息顺序 #分区

---

*生成时间：2026-05-05*
