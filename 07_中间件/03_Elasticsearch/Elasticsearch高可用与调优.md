# Elasticsearch 高可用与调优

## 这个问题为什么存在？

Elasticsearch 是分布式系统，涉及到**高可用**和**性能调优**两个维度。

**高可用的问题**：集群里有节点宕机了怎么办？Master 节点挂了怎么办？数据怎么保证不丢？

**性能调优的问题**：ES 用得不好，查询可以慢到几秒甚至超时。常见问题：Shard 数不合理、JVM 堆内存设置不当、热数据没命中文件系统缓存、查询写法低效……

这两个问题本质是：**如何在分布式环境下，既保证数据不丢，又保证查询性能？**

## 它是怎么解决问题的？

### 高可用架构

#### 1. Master 节点选举（ZenDiscoery / Raft）

ES 集群必须有一个 Master 节点（从 master-eligible 节点中选举）。

```
集群: 3 个 master-eligible 节点
  Node-1: Master (当前)
  Node-2: Master-eligible (正常)
  Node-3: Master-eligible (正常)

Node-1 宕机 → 剩余 2 个节点重新选举 → Node-2 成为新 Master
```

**Master 的职责**：
- 管理集群元数据（Index 创建/删除、Shard 分配）
- 不负责存储数据或处理搜索请求（如果角色分离）

**脑裂问题**（旧版 ZenDiscoery）：网络分区导致两个 Master。

**解决**（ES 7.x+）：用 **Raft 协议**（正式名称是 ES 自己的实现，类似 Raft）选举 Master，从根本上避免脑裂。

#### 2. Shard 分配与故障转移

```
Index: books (3 Primary Shard, 1 Replica)

正常状态：
  Shard-0: Primary on Node-1, Replica on Node-2
  Shard-1: Primary on Node-2, Replica on Node-3
  Shard-2: Primary on Node-3, Replica on Node-1

Node-1 宕机：
  Shard-0 的 Replica on Node-2 提升为 Primary
  集群状态: Yellow（有 Primary 但缺少 Replica）
  修复: Node-1 恢复后，重新分配 Replica
```

**关键配置**：

```yaml
### elasticsearch.yml
cluster.name: my-cluster
node.name: node-1
node.roles: [ master, data ]   # 生产环境建议分离

discovery.seed_hosts: ["node-1", "node-2", "node-3"]
cluster.initial_master_nodes: ["node-1", "node-2", "node-3"]  # 首次启动用
```

#### 3. 数据可靠性

ES 的数据可靠性靠 **Replica** 保证，但**写入默认是异步复制**的。

```json
// 写入时要求所有 Replica 确认（类似 Kafka 的 acks=all）
PUT /books/_doc/1?wait_for_active_shards=all
{
  "title": "Elasticsearch 实战"
}
```

`wait_for_active_shards=all`：等到所有活跃的 Shard 副本都确认才返回。保证数据不丢，但延迟更高。

### 性能调优

#### 调优1：JVM 堆内存设置

```
ES 是 Java 程序，运行在 JVM 上。
堆内存太小 → 频繁 GC，查询延迟高
堆内存太大 → Full GC 停顿时间长（秒级）
```

**经验法则**：

```
JVM 堆内存 ≤ 50% 的物理内存（留给文件系统缓存）
JVM 堆内存 ≤ 32GB（压缩指针失效阈值，超过 32GB 性能反而下降）
推荐: 物理内存 64GB → JVM 堆 32GB，剩余 32GB 给 OS 缓存
```

```yaml
### jvm.options
-Xms32g
-Xmx32g   # 初始值和最大值必须一样，避免运行时调整
```

**为什么 ≤ 32GB？** JVM 的**压缩指针（Compressed OOps）** 在堆 ≤ 32GB 时才生效。超过 32GB，每个对象引用从 4 字节变成 8 字节，内存使用暴涨，GC 压力更大。

#### 调优2：Shard 数规划

```
Shard 太多 → 每个 Shard 是 Lucene 实例，有内存/FD 开销，搜索时合并结果开销大
Shard 太少 → 无法并行，数据量一大就扛不住
```

**经验法则**：

```
单个 Primary Shard 大小: 10GB ~ 50GB（推荐）
总 Shard 数（集群级别）: 每 GB 堆内存不超过 20 个 Shard
  → 32GB 堆 → 最多 32×20 = 640 个 Shard
```

**Shard 数一旦设定，不能直接修改！** 要修改只能 Reindex（重建索引）。

#### 调优3：Hot Threads 与慢查询监控

```json
// 查看慢查询（Slow Log）
PUT /books/_settings
{
  "index.search.slowlog.threshold.query.warn": "10s",
  "index.search.slowlog.threshold.query.info": "5s",
  "index.search.slowlog.threshold.fetch.warn": "5s"
}

// 查看热线程（哪个线程 CPU 高）
GET /_nodes/hot_threads
```

#### 调优4：使用文件系统缓存（OS Cache）

```
ES 的倒排索引文件（.tip / .doc / .pos 等）会被操作系统缓存到内存。
热数据在 OS 缓存里 → 查询走内存，微秒级延迟。
热数据不在 OS 缓存里 → 查询要走磁盘，毫秒级延迟。
```

**为什么 JVM 堆不超过 50%？** 剩下的内存给操作系统，用于文件系统缓存，这是 ES 查询快的关键之一。

### 源码关键路径：Master 选举

ES 7.x+ 使用 **Coordinator** 模块（基于 Raft 协议）做 Master 选举：

```
节点启动 → 加入集群（向已知 Master 或候选节点发送 Join 请求）
         → 如果没找到 Master，发起选举
         → 所有 master-eligible 节点投票
         → 获得超过半数投票的节点成为 Master
         → 其他节点接受该 Master
```

**为什么超过半数？** 防止脑裂（Split-Brain）。网络分区时，少数派无法选出 Master（拿不到超过半数的票）。

## 深入原理

### ES 集群 vs Redis Cluster

| 维度 | ES 集群 | Redis Cluster |
|------|----------|----------------|
| 选举协议 | Raft（类） | Gossip + Failover |
| 数据分片 | Shard（自动分配） | Slot（手动/自动分配） |
| 查询路由 | 协调节点转发 | 客户端直接计算目标节点 |
| 水平扩展 | 增加节点，Rebalance Shard | 增加节点，Reshard（麻烦） |

**本质区别**：ES 的集群管理更"中心化"（有 Master 节点协调），Redis Cluster 更"去中心化"（Gossip 协议，每个节点知道其他节点）。ES 的元数据管理更强（复杂的 Shard 分配策略），Redis Cluster 的路由更简单（客户端计算 Slot）。

### ES 调优 vs MySQL 调优

| 维度 | MySQL 调优 | ES 调优 |
|------|-------------|----------|
| 核心 | 索引设计、SQL 优化、Buffer Pool | Shard 规划、JVM 堆、OS 缓存 |
| 内存使用 | Buffer Pool（数据缓存） | OS Cache（文件系统缓存）+ JVM 堆 |
| 并行度 | 有限（单查询用多线程） | 原生（Shard 级并行） |

**本质区别**：MySQL 调优更关注"怎么让单次查询更快"（索引、执行计划），ES 调优更关注"怎么让分布式并行更高效"（Shard 规划、减少合并开销）。

## 正确使用方式

### 正确用法

**1. 生产环境 Master 节点和数据节点分离**

```yaml
### Master 节点（3 个，保证奇数，避免脑裂）
node.roles: [ master ]

### Data 节点（多个，负责存储和查询）
node.roles: [ data ]

### Ingest 节点（可选，预处理 Pipeline）
node.roles: [ ingest ]

### Coordinating 节点（只路由请求，不存数据）
node.roles: [ ]   # 不设置任何角色 = 纯协调节点
```

**为什么正确**：Master 节点负责集群元数据管理，如果被搜索请求拖垮，整个集群不可用。分离后，Master 轻量级，稳定性高。

**2. 使用 Index Lifecycle Management (ILM) 管理时序数据**

```json
// 创建 ILM 策略：热 → 温 → 冷 → 删除
PUT /_ilm/policy/logs_policy
{
  "policy": {
    "phases": {
      "hot": {
        "actions": {
          "rollover": { "max_size": "50gb", "max_age": "30d" }
        }
      },
      "warm": {
        "min_age": "30d",
        "actions": { "allocate": { "number_of_replicas": 0 } }
      },
      "cold": {
        "min_age": "60d",
        "actions": { "freeze": {} }
      },
      "delete": {
        "min_age": "90d",
        "actions": { "delete": {} }
      }
    }
  }
}
```

**为什么正确**：日志类时序数据，越旧的数据访问频率越低。ILM 自动管理数据生命周期，节省存储和计算资源。

**3. 使用 Bulk API 批量写入**

```json
// 错误：一条条写入（每次都是网络 Round-Trip）
POST /books/_doc/1 { ... }
POST /books/_doc/2 { ... }

// 正确：批量写入（一次请求多条）
POST /_bulk
{"index": {"_index": "books", "_id": 1}}
{"title": "Elasticsearch 实战", ...}
{"index": {"_index": "books", "_id": 2}}
{"title": "Lucene 原理", ...}
```

**为什么正确**：减少网络 Round-Trip，提高吞吐。推荐 `bulk.size` 5MB~15MB（太小则 Round-Trip 开销大，太大则内存压力大）。

### 错误用法及后果

**错误1：Shard 数设置太多**

```
3GB 数据，设了 100 个 Primary Shard → 每个 Shard 只有 30MB
```

**后果**：
- 每个 Shard 是 Lucene 实例，有固定的内存开销（FST 前缀树、缓存等）
- 搜索时协调节点要合并 100 个 Shard 的结果，开销大
- JVM 堆压力大，可能 OOM

**修复**：遵循"单个 Shard 10GB~50GB"原则。3GB 数据用 1 个 Shard 就够了。

**错误2：JVM 堆内存超过 32GB**

```yaml
### 错误
-Xms48g
-Xmx48g
```

**后果**：压缩指针失效，每个对象引用从 4 字节变成 8 字节，内存使用暴涨，GC 压力更大，性能反而**不如 32GB**。

**修复**：JVM 堆 ≤ 32GB，多余的内存留给操作系统做文件系统缓存。

**错误3：热数据不在 OS 缓存里，查询走磁盘**

```
原因：JVM 堆设置太大（比如 60GB），OS 缓存只剩一点点
后果：查询要走磁盘，延迟从微秒级变成毫秒级
```

**修复**：JVM 堆不超过物理内存的 50%，保证有足够内存给 OS 缓存。

## 边界情况和坑

### 坑1：Replica 数 + Primary 数 > 节点数，副本无法分配

```
3 个节点，Index 设置: 1 Primary + 2 Replica = 3 个副本
  → 每个 Primary 需要 2 个 Replica，总共需要 3 个节点存副本
  → 如果 1 个节点宕机，只剩 2 个节点，Replica 无法分配，集群状态 Yellow
```

**修复**：`number_of_replicas` ≤ `节点数 - 1`。3 个节点最多设 `replicas=2`。

### 坑2：Shard 数不能修改，数据量大了怎么办

```
创建 Index 时设了 3 个 Shard，后来数据量从 30GB 涨到 300GB
→ 每个 Shard 100GB，超过推荐上限（50GB）
```

**解决**：用 **Rollover + Alias** 管理数据增长。

```json
// 1. 创建初始 Index 并绑定 Alias
PUT /logs-000001
PUT /logs-000001/_alias/logs

// 2. 数据增长触发 Rollover（50GB 或 30 天自动新建 Index）
POST /logs/_rollover
{
  "conditions": { "max_size": "50gb", "max_age": "30d" }
}
// 自动创建 logs-000002，并切换 Alias 指向新 Index

// 3. 查询时只用 Alias（自动覆盖所有关联 Index）
GET /logs/_search  ← 自动查 logs-000001, logs-000002, ...
```

### 坑3：Master 节点脑裂（旧版 ES 7.x 之前）

**现象**：网络分区，两个机房之间网络断了，每个机房都选出了自己的 Master。

**后果**：两个 Master 各自管理集群，数据不一致（脑裂）。

**解决**（ES 7.x+ 已根本解决）：用 Raft 协议选举，要求超过半数选票，网络分区时少数派无法选出 Master。

**旧版（5.x/6.x）缓解方案**：

```yaml
discovery.zen.minimum_master_nodes: 2  # 至少 2 个 master-eligible 节点才选举
### 公式: (master_eligible_nodes / 2) + 1
### 3 个 master-eligible → 设 2
```
