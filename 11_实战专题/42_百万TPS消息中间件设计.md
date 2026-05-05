# 百万TPS消息中间件设计

> 百万TPS核心：顺序写盘 + 零拷贝 + 分区 + 副本同步。核心矛盾是**高吞吐（百万QPS）与高可靠（不丢消息）的平衡**。

---

## 消息中间件整体架构（类似 Kafka）

```
生产者 × N ──→  Broker Cluster  ──→  消费者 × N
                    │
         ┌──────────┼──────────┐
         ▼          ▼          ▼
    Broker-1    Broker-2    Broker-3
    (Leader)     (Follower)  (Follower)
         │          │          │
         └──────────┼──────────┘
                    ▼
              ZooKeeper/Controller
              (元数据/选举)
```

---

## 场景 A：存储设计（顺序写/零拷贝）

### 现象

```
随机写磁盘：寻道时间长，吞吐 < 1MB/s
需要顺序写：追加写入，吞吐 > 100MB/s
百万 TPS 需要高吞吐存储引擎
```

### 解决方案

```java
// 1. 顺序写实现：追加写入日志文件
public class CommitLog {
    private final RandomAccessFile raf;
    private final FileChannel channel;
    private volatile long writePosition = 0;
    
    public CommitLog(String filePath) throws IOException {
        File file = new File(filePath);
        this.raf = new RandomAccessFile(file, "rw");
        this.channel = raf.getChannel();
    }
    
    // 顺序写入消息（追加模式）
    public synchronized AppendResult append(Message msg) throws IOException {
        // 1. 构造消息格式：[msgLen][msgBody][CRC]
        byte[] msgBytes = serialize(msg);
        int totalLen = 4 + msgBytes.length + 4;  // msgLen(4) + body + crc(4)
        
        ByteBuffer buffer = ByteBuffer.allocate(totalLen);
        buffer.putInt(msgBytes.length);  // 消息长度
        buffer.put(msgBytes);             // 消息体
        buffer.putInt(crc32(msgBytes));   // CRC 校验
        
        buffer.flip();
        
        // 2. 写入文件通道（顺序写）
        long offset = writePosition;
        channel.position(writePosition);
        channel.write(buffer);
        writePosition += totalLen;
        
        // 3. 异步刷盘（或同步刷盘，根据配置）
        if (flushImmediately) {
            channel.force(false);  // fsync
        }
        
        return new AppendResult(offset, totalLen);
    }
    
    // 读取消息（通过 offset 定位）
    public Message read(long offset, int size) throws IOException {
        ByteBuffer buffer = ByteBuffer.allocate(size);
        channel.position(offset);
        channel.read(buffer);
        buffer.flip();
        return deserialize(buffer.array());
    }
}

// 2. 零拷贝发送：用 sendfile 系统调用（Java NIO transferTo）
public class ZeroCopySender {
    
    // 用 FileChannel.transferTo 实现零拷贝（底层调用 sendfile）
    public void sendFile(SocketChannel socketChannel, long offset, long size) 
            throws IOException {
        FileChannel fileChannel = new FileInputStream("commitlog.0").getChannel();
        
        // 零拷贝：数据直接从文件到 socket，不经过用户态
        long transferred = fileChannel.transferTo(offset, size, socketChannel);
        
        if (transferred != size) {
            log.warn("零拷贝传输不完整: {}/{}", transferred, size);
        }
    }
}

// 3. PageCache 优化：利用操作系统缓存
// Linux 会缓存文件页（PageCache），读取热点数据时走内存
// Kafka 依赖 PageCache，简化存储引擎设计
```

**存储优化要点**：
- **顺序写**：追加写入，避免寻道（吞吐提升 100 倍）
- **零拷贝**：sendfile 系统调用，减少 2 次用户态/内核态拷贝
- **PageCache**：依赖 OS 缓存，热数据读内存，冷数据读磁盘

---

## 场景 B：分区与并行消费

### 现象

```
单分区只能被一个消费者消费（并行度=1）
想要百万 TPS，必须多分区 + 多消费者并行
分区数 = 最大并行度
```

### 解决方案

```java
// 1. 分区设计：Topic 分为多个 Partition
// 写：按 key hash 或轮询选择分区
public class Producer {
    
    private final List<Partition> partitions;
    
    // 发送消息到 Topic（选择分区）
    public Future<RecordMetadata> send(String topic, String key, String value) {
        // 1. 获取 Topic 的 Partition 列表
        List<Partition> partitions = metadata.getPartitions(topic);
        
        // 2. 选择分区（有 key 用 hash，无 key 轮询）
        int partitionIndex;
        if (key != null) {
            partitionIndex = Math.abs(key.hashCode()) % partitions.size();
        } else {
            partitionIndex = nextRoundRobinIndex(topic);
        }
        
        Partition target = partitions.get(partitionIndex);
        
        // 3. 发送到选定的分区
        return sendToPartition(target, key, value);
    }
}

// 2. 消费者组：多个消费者并行消费不同分区
// Kafka Consumer Group 模型
public class ConsumerGroup {
    
    // 一个分区只能被同一个 Consumer Group 内的一个消费者消费
    // 分区数 >= 消费者数时，并行度 = 消费者数
    // 分区数 < 消费者数时，会有消费者空闲
    
    public void subscribe(String topic, String groupId) {
        // 1. 加入 Consumer Group（通过心跳向 Coordinator 注册）
        joinGroup(groupId);
        
        // 2. 分区分配（Range 或 RoundRobin 策略）
        List<Partition> assigned = assignPartitions(topic, groupId);
        
        // 3. 拉取分配到的分区消息
        for (Partition partition : assigned) {
            fetchMessages(partition);
        }
    }
}

// 3. 分区分配策略
// Range：按分区范围分配（可能导致不均衡）
// RoundRobin：轮询分配（更均衡）
// Sticky：尽量保持原有分配（减少重平衡开销）
```

```java
// 4. 并行消费实现
@Component
public class ParallelConsumer {
    
    // 每个分区对应一个消费线程
    private final Map<Integer, ExecutorService> partitionExecutors = new ConcurrentHashMap<>();
    
    public void startConsume(String topic, int partitionCount, String groupId) {
        for (int partition = 0; partition < partitionCount; partition++) {
            final int p = partition;
            
            // 每个分区一个线程（保证分区内有序）
            ExecutorService executor = Executors.newSingleThreadExecutor();
            partitionExecutors.put(partition, executor);
            
            executor.submit(() -> {
                KafkaConsumer<String, String> consumer = createConsumer(groupId);
                consumer.assign(Collections.singleton(
                        new TopicPartition(topic, p)));
                
                while (true) {
                    ConsumerRecords<String, String> records = consumer.poll(Duration.ofMillis(100));
                    for (ConsumerRecord<String, String> record : records) {
                        processRecord(record);  // 处理消息
                    }
                    consumer.commitSync();  // 提交 offset
                }
            });
        }
    }
}
```

**分区 vs 并行度**：
- 分区数 = N → 最大并行度 = N（一个分区只能被一个消费者消费）
- 消费者数 > 分区数 → 多余消费者空闲
- 推荐：分区数 = 消费者数（充分利用资源）

---

## 场景 C：副本同步与ISR

### 现象

```
单副本：Broker 宕机，数据丢失
多副本：高可靠，但写入延迟增加
需要权衡：acks=1（快，可能丢）vs acks=-1（慢，可靠）
ISR（In-Sync Replicas）机制：只等同步副本确认
```

### 解决方案

```java
// 1. ISR 维护：Broker 端跟踪同步副本
public class ReplicaManager {
    
    private final Map<Integer, PartitionReplica> replicas = new ConcurrentHashMap<>();
    
    // ISR：与 Leader 保持同步的副本集合
    private final Set<Integer> inSyncReplicas = new CopyOnWriteArraySet<>();
    
    // Leader 处理写入请求
    public WriteResult write(Message msg, short acks, int timeoutMs) {
        // 1. 写入本地日志
        AppendResult result = commitLog.append(msg);
        
        // 2. 如果 acks=0，立即返回（不等待副本）
        if (acks == 0) {
            return WriteResult.success(result.offset());
        }
        
        // 3. 等待副本同步
        if (acks == -1) {
            // 等待所有 ISR 副本确认
            boolean allSynced = waitForReplicas(
                    inSyncReplicas, result.offset(), timeoutMs);
            if (!allSynced) {
                return WriteResult.timeout();
            }
        } else if (acks == 1) {
            // 只等待 Leader 确认（默认）
            // 已经写入本地，直接返回
        }
        
        return WriteResult.success(result.offset());
    }
    
    // 跟踪副本同步进度（Follower 拉取日志）
    public void onFollowerFetch(int replicaId, long fetchedOffset) {
        PartitionReplica replica = replicas.get(replicaId);
        replica.updateFetchOffset(fetchedOffset);
        
        // 判断是否仍在 ISR 中（落后不超过阈值）
        long lag = commitLog.getWritePosition() - fetchedOffset;
        if (lag < replicaLagThreshold) {
            inSyncReplicas.add(replicaId);  // 落后少，加入 ISR
        } else {
            inSyncReplicas.remove(replicaId);  // 落后多，踢出 ISR
        }
    }
}

// 2. Follower 副本同步（拉模式）
public class FollowerReplica {
    
    private final int leaderBrokerId;
    private long fetchOffset = 0;
    
    // 定时从 Leader 拉取新消息
    @Scheduled(fixedDelay = 100)  // 每 100ms 拉一次
    public void fetchFromLeader() {
        // 1. 向 Leader 发送 FETCH 请求
        FetchRequest request = new FetchRequest(leaderBrokerId, fetchOffset);
        FetchResponse response = sendFetchRequest(request);
        
        // 2. 写入本地日志
        for (Message msg : response.getMessages()) {
            commitLog.append(msg);
            fetchOffset += msg.getSize();
        }
        
        // 3. 向 Leader 汇报进度（更新 ISR 状态）
        sendFetchOffsetReport(leaderBrokerId, fetchOffset);
    }
}
```

**ISR 机制要点**：
- **ISR**：与 Leader 保持同步（落后 < threshold）的副本集合
- **acks=-1**：等待所有 ISR 副本确认（最可靠）
- **acks=1**：只等 Leader 确认（兼顾速度与可靠性）
- **副本踢出**：落后太多（如超过 10 秒数据）被踢出 ISR

---

## 场景 D：Controller高可用

### 现象

```
Controller 负责分区分配、Leader 选举
Controller 单点故障 → 无法分配分区、无法选举
需要 Controller 高可用：故障自动切换
```

### 解决方案

```java
// 1. Controller 选举：基于 ZooKeeper 临时节点
public class ControllerElector {
    
    private final String controllerPath = "/kafka/controller";
    private final ZooKeeper zk;
    private volatile boolean isController = false;
    
    // 竞选 Controller（谁先创建临时节点谁就是 Controller）
    public void elect() {
        try {
            // 尝试创建临时节点（只有一个能成功）
            zk.create(controllerPath, 
                      getBrokerId().getBytes(),
                      ZooDefs.Ids.OPEN_ACL_UNSAFE,
                      CreateMode.EPHEMERAL);
            
            // 创建成功 → 我是 Controller
            onBecomeController();
            
        } catch (KeeperException.NodeExistsException e) {
            // 节点已存在 → 别人是 Controller
            watchControllerChange();  // 监听 Controller 变化
        }
    }
    
    // 成为 Controller
    private void onBecomeController() {
        isController = true;
        log.info("成为 Controller: brokerId={}", getBrokerId());
        
        // 1. 初始化 Controller 上下文（分区状态、ISR 等）
        loadControllerContext();
        
        // 2. 监听 Broker 变化（处理 Broker 上下线）
        watchBrokerChanges();
        
        // 3. 监听分区状态变化
        watchPartitionChanges();
    }
    
    // 监听 Controller 变化（我是 Follower 时）
    private void watchControllerChange() {
        try {
            zk.exists(controllerPath, new Watcher() {
                @Override
                public void process(WatchedEvent event) {
                    if (event.getType() == Event.EventType.NodeDeleted) {
                        // Controller 节点删除（原 Controller 故障）
                        log.info("Controller 故障，重新选举");
                        elect();  // 重新竞选
                    }
                }
            });
        } catch (Exception e) {
            log.error("监听 Controller 失败", e);
        }
    }
}

// 2. Controller 故障处理：Leader 重新选举
public class PartitionLeaderElection {
    
    // 当 Partition 的 Leader 宕机，触发重新选举
    public void onLeaderFailure(int partitionId) {
        // 1. 从 ISR 中选择新 Leader（优先选第一个）
        List<Integer> isr = getIsr(partitionId);
        if (isr.isEmpty()) {
            log.error("ISR 为空，无法选举 Leader: partition={}", partitionId);
            return;
        }
        
        int newLeaderId = isr.get(0);
        
        // 2. 更新 ZooKeeper 中的 Leader 信息
        String leaderPath = "/kafka/partitions/" + partitionId + "/leader";
        try {
            zk.setData(leaderPath, String.valueOf(newLeaderId).getBytes(), -1);
        } catch (Exception e) {
            log.error("更新 Leader 失败", e);
        }
        
        // 3. 通知所有副本切换 Leader
        notifyLeaderChange(partitionId, newLeaderId);
    }
}
```

**Controller 高可用**：
- **选举**：基于 ZK 临时节点（或 KRaft 模式，Kafka 2.8+）
- **故障检测**：临时节点删除 → 触发重新选举
- **分区管理**：Controller 故障期间，分区不可用（直到新 Controller 选出）

---

## 核心参数估算

```
百万 TPS 硬件需求：
  单 Broker 吞吐：10万 TPS（取决于磁盘和 CPU）
  百万 TPS → 需要 10 个 Broker
  
磁盘需求：
  每条消息 1KB，百万 TPS → 每秒 1GB 写入
  保留 7 天 → 7 × 24 × 3600 × 1GB = 604TB
  3 副本 → 1.8PB 总存储（可用 EC 纠删码降低成本）
  
网络需求：
  百万 TPS × 1KB = 1GB/s = 8Gbps 入站 + 8Gbps 出站
  万兆网卡（10Gbps）够用：10Gbps ≈ 1.25GB/s
```

---

## 涉及知识点

| 概念 | 所属域 | 关键点 |
|------|--------|--------|
| 顺序写盘 | 06_中间件/03_消息队列 | 追加写、吞吐量提升 100x |
| 零拷贝 sendfile | 06_中间件/03_消息队列 | 内核态直接传输、减少拷贝 |
| Kafka 分区 | 06_中间件/03_消息队列 | 并行度、分区分配策略 |
| ISR 机制 | 06_中间件/03_消息队列 | 同步副本、acks=-1、高可靠 |
| Controller 选举 | 06_中间件/03_消息队列 | ZK 临时节点、故障切换 |
| PageCache | 操作系统 | OS 文件缓存、读写加速 |

---

## 追问链

### 追问 1：百万 TPS 需要多少 Broker？

> "取决于单 Broker 性能：1. **顺序写盘**：单 Broker 约 10万 TPS（消息 1KB）。2. **百万 TPS**：需要 10 个 Broker（不考虑副本）。3. **3 副本**：需要 30 个 Broker（保证高可靠）。4. **冗余**：建议 33-35 个 Broker（留 10% 余量）。"

### 追问 2：零拷贝为什么快？

> "传统拷贝：磁盘 → 内核缓冲区 → 用户缓冲区 → Socket 缓冲区 → 网卡（4 次拷贝）。零拷贝（sendfile）：磁盘 → 内核缓冲区 → Socket 缓冲区 → 网卡（3 次拷贝，少了一次用户态拷贝）。如果是 DMA **sendfile**：2 次拷贝（内核缓冲 → 网卡，不进 Socket 缓冲）。Kafka 用零拷贝技术，吞吐提升 2-3 倍。"

### 追问 3：acks=0/1/-1 怎么选？

> "**acks=0**：不等待确认（最快，可能丢消息）。场景：日志采集、指标上报。**acks=1**：只等 Leader 确认（推荐，速度和可靠性平衡）。场景：大部分业务。**acks=-1**：等所有 ISR 副本确认（最可靠，最慢）。场景：金融交易、审计日志。"

### 追问 4：Controller 故障期间怎么办？

> "影响：1. **无法创建 Topic**。2. **无法选举 Leader**（分区状态不变）。3. **已有分区正常读写**（Producer/Consumer 直接连接 Broker）。恢复：1. ZK 检测到临时节点删除（Session 超时）。2. 触发重新选举。3. 新 Controller 接管，恢复管理功能。总故障时间：5-10 秒（ZK Session 超时）。"

---

## 排查 Checklist

```
□ 顺序写生效了吗？ → 磁盘写入模式为 append only
□ 零拷贝启用了吗？ → sendfile 系统调用（Java NIO transferTo）
□ 分区数合理吗？ → 分区数 ≥ 消费者数（充分利用并行度）
□ ISR 正常吗？ → 检查 ISR 列表，有无副本踢出
□ acks 配置正确吗？ → 业务场景决定（0/1/-1）
□ Controller 选举成功吗？ → ZK 节点 /kafka/controller 存在
□ 副本同步延迟大吗？ → 监控 replica.lag 指标
□ PageCache 命中率高吗？ → OS 缓存命中率 > 80%
□ 磁盘空间够吗？ → 监控磁盘使用率 < 85%
```

---

## 我的实战笔记

-（待补充，项目中的真实经历）
