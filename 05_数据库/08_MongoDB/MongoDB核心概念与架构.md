# MongoDB 核心概念与架构

## 这个问题为什么存在？

随着业务形态变化，关系型数据库的局限性越来越明显：

```
关系型数据库（MySQL/PostgreSQL）的痛点：
  - 表结构固定，加字段要 ALTER TABLE（大表锁表，耗时）
  - 一对多关系要 JOIN，数据量大时性能差
  - 水平扩展困难（分库分表复杂，ShardingSphere 也要维护）
  - 半结构化数据（JSON、嵌套对象）存起来很别扭

MongoDB 的解决方案：
  - 文档模型（Document）→ 数据结构灵活，无需预定义 Schema
  - 天然支持嵌套对象和数组 → 一对多关系直接嵌入，不用 JOIN
  - 内置分片（Sharding）→ 水平扩展开箱即用
  - 丰富的查询语言 → 支持复杂查询、聚合管道（Aggregation Pipeline）
```

> MongoDB 不是"替代品"，而是**不同场景下的不同选择**。交易类数据用 MySQL，内容/日志/物联网数据用 MongoDB，各取所长。

---

## 它是怎么解决问题的？

### 一、核心概念

```
┌──────────────────────────────────────────────────────────────┐
│                MongoDB 核心概念 vs 关系型数据库                │
│                                                              │
│  MongoDB           →  MySQL                                 │
│  ──────────────────────────────────────────────────────    │
│  Database          →  Database                             │
│  Collection        →  Table（表）                           │
│  Document          →  Row（行）                             │
│  Field             →  Column（列）                           │
│  Index             →  Index                                │
│  _id               →  主键（自动生成 ObjectId）               │
└──────────────────────────────────────────────────────────────┘
```

#### 文档（Document）

MongoDB 的文档是 BSON 格式（Binary JSON），比 JSON 支持更多数据类型。

```json
// MongoDB 文档示例（用户信息）
{
  "_id": ObjectId("507f1f77bcf86cd799439011"),
  "username": "zhangsj",
  "email": "zhangsj@example.com",
  "age": 28,
  "tags": ["Java", "MongoDB", "微服务"],
  "address": {
    "city": "北京",
    "district": "海淀区"
  },
  "orders": [
    { "orderId": 1001, "total": 299, "date": ISODate("2024-01-15") },
    { "orderId": 1002, "total": 599, "date": ISODate("2024-02-20") }
  ],
  "createdAt": ISODate("2024-01-01T00:00:00Z")
}
```

```
BSON 比 JSON 多支持的类型：
  - ObjectId（12 字节唯一 ID）
  - Date（日期类型，精确到毫秒）
  - BinData（二进制数据）
  - Int32 / Int64 / Decimal128（精确小数，适合金额）
  - Null / Boolean / String / Array / Object

为什么用 BSON 而不是 JSON？
  - 二进制编码 → 解析更快（JSON 要逐字符解析，BSON 有长度前缀）
  - 支持更多类型 → Decimal128 精确存金额，不会像 float 有精度问题
  - 长度前缀 → 遍历字段 O(1)，JSON 需要遍历到目标字段
```

#### 集合（Collection）

Collection 相当于关系型数据库的表，但**没有固定 Schema**。

```javascript
// 同一个 Collection 里可以存不同结构的文档
db.users.insertOne({ name: "Alice", age: 25 })
db.users.insertOne({ name: "Bob", email: "bob@test.com", hobbies: ["reading"] })
// 都能成功插入，MongoDB 不强制 Schema 一致性

// 但生产环境建议用 Schema Validation 约束
db.createCollection("users", {
  validator: {
    $jsonSchema: {
      bsonType: "object",
      required: ["username", "email"],
      properties: {
        username: { bsonType: "string" },
        email: { bsonType: "string", pattern: "^.+@.+$" },
        age: { bsonType: "int", minimum: 0, maximum: 150 }
      }
    }
  }
})
```

---

### 二、存储引擎：WiredTiger

MongoDB 3.2 之后默认使用 **WiredTiger** 存储引擎，这是 MongoDB 高性能的关键。

```
┌──────────────────────────────────────────────────────────────┐
│                  WiredTiger 核心设计                          │
│                                                              │
│  1. 文档存储 → 压缩存储（Snappy/Zlib/Zstd）                  │
│     → 通常能压缩 50-70%，大幅节省磁盘空间                   │
│                                                              │
│  2. 内存缓存（Cache）→ 默认占物理内存的 50%-1GB              │
│     → 热数据在内存，读写快                                   │
│                                                              │
│  3. Checkpoint（检查点）→ 每 60 秒或 2GB 数据刷盘           │
│     → 定期将内存数据持久化到磁盘                             │
│                                                              │
│  4. Journal（预写日志）→ 类似 MySQL 的 Redo Log             │
│     → 每次写操作先写 Journal，保证宕机不丢数据               │
│                                                              │
│  5. 多版本并发控制（MVCC）→ 类似 InnoDB 的 MVCC             │
│     → 读不阻塞写，写不阻塞读                                 │
└──────────────────────────────────────────────────────────────┘
```

#### WiredTiger vs InnoDB 对比

| 维度 | WiredTiger | InnoDB |
|------|-----------|--------|
| 压缩 | 原生支持（Snappy/Zlib/Zstd） | 需要 Barracuda 格式 + 页压缩 |
| MVCC | 快照读（Snapshot） | Undo Log + ReadView |
| 锁粒度 | 文档级锁（WiredTiger） | 行级锁 |
| 缓存 | Cache（内存，默认 50%） | Buffer Pool（内存，默认 75%） |
| 日志 | Journal（类似 Redo Log） | Redo Log + Undo Log |

---

### 三、副本集（Replica Set）架构

副本集是 MongoDB 的高可用方案，类似 MySQL 的主从复制，但更智能。

```
┌──────────────────────────────────────────────────────────────┐
│                   MongoDB 副本集架构                          │
│                                                              │
│  Primary（主节点）                                           │
│    ↓ 异步复制                                                │
│  Secondary（从节点）× N                                     │
│    ↓ 异步复制                                                │
│  Arbiter（仲裁节点，可选，不存数据，只参与投票）              │
│                                                              │
│  写操作 → 只能发到 Primary                                   │
│  读操作 → 默认发到 Primary，可配置发到 Secondary（最终一致） │
│                                                              │
│  自动故障转移：                                              │
│    Primary 挂了 → 剩余节点选举新 Primary（Raft 协议变种）    │
│    → 通常 10 秒内完成切换                                    │
└──────────────────────────────────────────────────────────────┘
```

#### 选举机制

```
触发选举的场景：
  1. Primary 宕机
  2. 网络分区，Primary 失联
  3. 手动维护（rs.stepDown()）

选举规则（Raft 协议变种）：
  - 每个节点有 priority（优先级，默认 1，0 表示永远不参与选举）
  - 有投票权的节点（votes: 1）参与选举，Arbiter 只有投票权
  - 获得多数派（N/2 + 1）选票的节点成为新 Primary

隐藏节点（Hidden Replica Set Member）：
  - priority: 0，votes: 0
  - 对外不可见，专用于备份或离线分析（不影响线上读性能）
```

#### 写关注（Write Concern）和读关注（Read Concern）

```javascript
// 写关注：写入成功后，需要确认多少个节点
db.users.insertOne(
  { name: "Alice" },
  { writeConcern: { w: "majority", wtimeout: 5000 } }
)
// w: 1        → 只要 Primary 写入成功就返回（最快，但可能丢数据）
// w: "majority" → 大多数节点写入成功才返回（推荐，平衡性能和可靠性）
// w: N         → N 个节点写入成功才返回（最安全，但慢）

// 读关注：读到的数据的一致性级别
db.users.find().readConcern("majority")
// "local"       → 读最新数据（可能读到未提交的数据，最快）
// "majority"    → 读已被大多数节点确认的数据（推荐）
// "linearizable"→ 线性一致性（最强，但性能最差，适合金融场景）
```

---

### 四、分片集群（Sharded Cluster）架构

当数据量超过单机容量时，需要分片（Sharding）。MongoDB 的分片是**内置能力**，不需要第三方中间件。

```
┌──────────────────────────────────────────────────────────────┐
│                MongoDB 分片集群架构                            │
│                                                              │
│                    ┌─────────────┐                           │
│                    │   Mongos    │  ← 路由层（无状态，可多实例）│
│                    │  (Router)   │                           │
│                    └──────┬──────┘                           │
│                           │                                  │
│            ┌──────────────┼──────────────┐                  │
│            ↓              ↓              ↓                    │
│      Shard A        Shard B        Shard C                  │
│    (分片1)         (分片2)         (分片3)                  │
│    [Primary         [Primary         [Primary                │
│     +Secondary]     +Secondary]     +Secondary]              │
│                                                              │
│            └──────────────┬──────────────┘                  │
│                           │                                  │
│                    ┌──────▼──────┐                           │
│                    │   Config    │  ← 元数据（分片路由信息） │
│                    │  Server     │                           │
│                    └─────────────┘                           │
└──────────────────────────────────────────────────────────────┘
```

#### 分片键（Shard Key）选择

分片键是决定数据分布的关键，选错了几乎无法更改。

```
分片键的要求：
  1. 基数高（cardinality 高）→ 能均匀分布到多个分片
  2. 不单调递增 → 避免所有新数据写入同一个分片（热点问题）
  3. 尽量覆盖常用查询 → 查询时能定位到具体分片，不用广播查询

常见分片键策略：
  ✅ userId（基数高，查询常用，但不是单调递增的）
  ✅ 订单表的 { userId, orderId }（复合分片键，基数更高）
  ❌ _id（ObjectId 包含时间戳，单调递增，会导致热点）
  ❌ 性别/状态（基数低，数据分布不均）
```

#### 分片策略

| 策略 | 说明 | 适用场景 |
|------|------|---------|
| **范围分片（Range）** | 按分片键的值范围分布 | 范围查询多（如时间范围） |
| **哈希分片（Hash）** | 对分片键做哈希，均匀分布 | 写入均匀性要求高 |
| **Zone/Tag 分片** | 手动指定某些数据落在特定分片 | 多数据中心、冷热数据分离 |

```javascript
// 启用分片
sh.enableSharding("mydb")
sh.shardCollection("mydb.orders", { userId: 1, orderId: 1 })

// 查看分片分布
db.orders.getShardDistribution()
```

#### 分片 vs 副本集

```
副本集（Replica Set）：
  目的：高可用（HA）+ 读扩展
  数据：每个节点存全量数据
  写入：只写 Primary

分片集群（Sharded Cluster）：
  目的：水平扩展（存储 + 写入 + 读取）
  数据：每个分片存部分数据
  写入：根据分片键路由到对应分片

生产环境通常是：分片 + 副本集 组合使用
  → 每个 Shard 是一个 Replica Set（既有扩展又有高可用）
```

---

## 它和相似方案的本质区别是什么？

### MongoDB vs MySQL/PostgreSQL

| 维度 | MongoDB | MySQL/PostgreSQL |
|------|---------|-----------------|
| 数据模型 | 文档（BSON，灵活 Schema） | 关系表（固定 Schema） |
| 事务 | 4.0+ 支持多文档事务（有性能代价） | 原生支持，成熟稳定 |
| JOIN | 不支持（用 $lookup 模拟，性能差） | 原生支持，优化器成熟 |
| 水平扩展 | 内置分片，开箱即用 | 需要 ShardingSphere 等中间件 |
| 查询语言 | MongoDB Query Language（JSON 风格） | SQL |
| 适用场景 | 内容管理、物联网、实时分析、日志 | 交易系统、财务系统、强事务场景 |
| 写入性能 | 高（无事务开销时） | 中（有事务开销） |
| 一致性 | 最终一致（可配置为强一致） | 强一致（ACID） |

```
本质区别：数据建模思路不同

关系型数据库：
  用户表 → 订单表 → 订单明细表（一对多要拆表，用外键关联）
  → 写的时候方便（INSERT 一张表），读的时候要 JOIN

MongoDB：
  用户文档里直接嵌入订单数组（一对多直接嵌入）
  → 读的时候方便（一次查询拿到所有数据），写的时候要更新整个文档
```

### MongoDB vs Elasticsearch

| 维度 | MongoDB | Elasticsearch |
|------|---------|---------------|
| 定位 | 通用文档数据库 | 搜索引擎 |
| 查询 | 精确查询快，全文搜索弱 | 全文搜索极强（倒排索引 + BM25） |
| 聚合分析 | 支持（Aggregation Pipeline） | 支持（更强，近实时） |
| 事务 | 支持（多文档事务） | 不支持（近实时，不保证强一致） |
| 适用场景 | 主数据存储 | 搜索/日志/分析 |

```
生产架构（常见组合）：
  MongoDB（主存储）
    ↓ 同步（CDC / Chang Streams）
  Elasticsearch（搜索引擎）

  用户写入数据 → MongoDB（保证数据不丢）
  用户搜索数据 → Elasticsearch（全文搜索体验好）
```

### MongoDB vs Redis

| 维度 | MongoDB | Redis |
|------|---------|-------|
| 持久化 | 磁盘 + 内存 | 内存为主，AOF/RDB 持久化 |
| 查询能力 | 丰富（支持复杂查询、聚合） | 简单（K-V，复杂查询需客户端处理） |
| 数据大小 | 无限制（超过内存会 swap） | 受内存限制 |
| 适用场景 | 主存储、文档数据 | 缓存、计数器、Session |

---

## 正确使用方式

### 正确用法

**1. 合理设计文档结构（嵌入 vs 引用）**

```javascript
// ✅ 正确：一对少，直接嵌入（读性能好）
{
  "_id": ObjectId("..."),
  "username": "zhangsj",
  "orders": [
    { "orderId": 1001, "total": 299 },  // 嵌入订单（用户订单通常 < 100 个）
  ]
}
// → 查询用户信息时，订单数据一起返回，不用额外查询

// ❌ 错误：一对多，也嵌入（文档会无限膨胀）
{
  "username": "zhangsj",
  "posts": [ /* 1 万个帖子！*/ ]  // 文档大小超过 16MB 限制
}
// → MongoDB 单个文档最大 16MB，超过了会写入失败

// ✅ 正确：一对多，用引用（类似关系型的 JOIN）
// users 集合
{ "_id": ObjectId("..."), "username": "zhangsj" }

// posts 集合
{ "userId": ObjectId("..."), "title": "MongoDB 教程", "content": "..." }
// → 查询时用 $lookup 关联，或者应用层分两次查询
```

**嵌入 vs 引用的决策树**：

```
关系是一对少（< 几百个）？
  → 是：直接嵌入（读性能好）
  → 否：用引用（避免文档过大）

数据需要独立访问？
  → 是：用引用（可以单独查询）
  → 否：直接嵌入

需要事务保证原子性？
  → 是：直接嵌入（MongoDB 事务只保证单个文档的原子性，4.0+ 才支持多文档）
  → 否：都可以
```

**2. 连接池配置（Java 客户端）**

```java
// ✅ 正确：配置合理的连接池
MongoClientOptions options = MongoClientOptions.builder()
    .connectionsPerHost(100)          // 每个主机的连接数（默认 100）
    .threadsAllowedToBlockForConnectionMultiplier(5)  // 最大等待连接数 = 100 × 5
    .maxWaitTime(10000)              // 获取连接最大等待时间（10 秒）
    .connectTimeout(10000)           // 建立连接超时（10 秒）
    .socketTimeout(30000)           // 读写超时（30 秒）
    .build();

MongoClient client = new MongoClient(
    Arrays.asList(
        new ServerAddress("mongo1:27017"),
        new ServerAddress("mongo2:27017")
    ),
    options
);
```

**为什么正确**：MongoDB 的连接是**一对一 TCP 连接**，不是像 MySQL 那样的连接池复用。连接数过多会消耗大量资源，过少会导致请求排队。

**3. 用 Projection 减少网络传输**

```javascript
// ❌ 错误：查整个文档（网络传输大量无用数据）
db.users.find({ username: "zhangsj" })
// → 返回整个文档（可能包含几百 KB 的嵌入数据）

// ✅ 正确：只返回需要的字段（Projection）
db.users.find(
  { username: "zhangsj" },
  { username: 1, email: 1, _id: 0 }  // 只返回 username 和 email
)
// → 网络传输量大幅减少，查询更快
```

### 错误用法及后果

**错误1：不做分片键规划，数据分布不均**

```javascript
// 错误：用 _id（ObjectId 包含时间戳，单调递增）做分片键
sh.shardCollection("mydb.orders", { _id: 1 })
// → 新写入的数据都落在同一个分片（Chunk），形成热点
// → 其他分片空闲，写入性能上不去

// 正确：用复合分片键，基数高且不单调
sh.shardCollection("mydb.orders", { userId: 1, _id: "hashed" })
```

**错误2：在 MongoDB 里做复杂聚合，不用 Elasticsearch**

```javascript
// 错误：用 MongoDB 做全文搜索
db.posts.find({ $text: { $search: "MongoDB 教程" } })
// → MongoDB 的全文索引功能弱，不支持中文分词，搜索体验差

// 正确：搜索场景用 Elasticsearch，MongoDB 只做主存储
// 数据同步：MongoDB Change Streams → Kafka → Elasticsearch
```

**错误3：过度依赖多文档事务**

```javascript
// 错误：用多文档事务保证跨集合一致性（性能差）
session = db.getMongo().startSession()
session.startTransaction()
db.orders.insertOne({ ... }, { session })
db.inventory.updateOne({ ... }, { $inc: { stock: -1 } }, { session })
session.commitTransaction()
// → 多文档事务需要加锁，并发性能下降
// → MongoDB 的事务不如 MySQL 成熟，高并发场景慎用

// 正确：用嵌入模型 + 单个文档原子操作
// 订单和库存放在同一个文档里，一次写入原子完成
```

---

## 边界情况和坑

### 坑1：ObjectId 的时间戳泄露

**现象**：有人通过 ObjectId 推断出文档的创建时间，甚至遍历 _id 爬取数据。

```javascript
// ObjectId 结构（12 字节）：
// 4 字节时间戳 + 5 字节随机值 + 3 字节递增计数器
// → 前 4 字节是创建时间，可以直接解析

ObjectId("507f1f77bcf86cd799439011").getTimestamp()
// → ISODate("2024-01-01T00:00:00Z")  ← 创建时间泄露！

// 防御：用 UUID 或自定义 ID 代替 ObjectId
db.users.insertOne({ _id: UUID(), ... })
```

### 坑2：游标超时（Cursor Timeout）

**现象**：遍历大结果集时，报错 `Cursor not found`。

```javascript
// 错误：默认游标 10 分钟超时，遍历慢的话游标会被关闭
db.orders.find().forEach(doc => {
  // 处理每个文档（可能很慢）
})

// 正确：设置 noCursorTimeout（但要记得手动关闭游标）
var cursor = db.orders.find().noCursorTimeout()
try {
  while (cursor.hasNext()) {
    var doc = cursor.next()
    // 处理文档...
  }
} finally {
  cursor.close()  // 必须手动关闭，否则游标永远不释放
}
```

### 坑3：索引构建阻塞写操作

**现象**：在大集合上建索引，导致整个集合无法写入（MongoDB 4.2 之前）。

```javascript
// 错误（MongoDB 4.2 之前）：前台建索引，阻塞所有写操作
db.orders.createIndex({ userId: 1 })
// → 集合被锁，所有写入被阻塞，线上事故！

// 正确：后台建索引（MongoDB 4.2+ 默认就是后台）
db.orders.createIndex({ userId: 1 }, { background: true })
// 或者用 MongoDB 4.4+ 的在线索引构建（完全不阻塞写）
// → 自动在后台构建，不阻塞读写
```

### 坑4：64 位整数精度丢失（Java/JSON 交互）

**现象**：Java 读取 MongoDB 的 Long 类型，转 JSON 给前端后，精度丢失。

```
MongoDB 的 NumberLong("9223372036854775807")
  → Java 读取为 long（正确）
  → Jackson 序列化为 JSON：9223372036854775807
  → JavaScript 解析 JSON：9223372036854776000（精度丢失！）
  → 前端显示的 ID 和数据库不一致

解决方案：
  1. 用 String 存 Long（牺牲数值运算能力）
  2. 前端用 BigInt 解析（需要前端配合）
  3. 用 MongoDB 的 Decimal128 存金额（避免浮点精度问题）
```

---

## 面试话术

**Q：MongoDB 和 MySQL 怎么选？**
"看数据特征和一致性要求。交易、财务、强事务场景用 MySQL（ACID 保证好）。内容管理、物联网设备数据、用户行为日志、社交关系等半结构化数据用 MongoDB（Schema 灵活、写入性能好、水平扩展方便）。实际项目一般是组合使用：MySQL 存核心交易数据，MongoDB 存行为日志和半结构化数据。"

**Q：MongoDB 的副本集是怎么工作的？**
"副本集由 1 个 Primary 和多个 Secondary 组成，Primary 负责所有写入，Secondary 异步复制数据。Primary 挂了，剩余节点自动选举新 Primary（基于 Raft 协议变种，通常 10 秒内完成）。写关注（Write Concern）可以控制写入的可靠性：w:1 只写 Primary 就返回（快但有丢数据风险），w:majority 写大多数节点才返回（推荐）。"

**Q：分片键怎么选？**
"分片键决定数据分布，选错几乎无法更改。好的分片键要满足：基数高（能均匀分布）、不单调递增（避免热点问题）、尽量覆盖常用查询（避免广播查询）。实践中常用 `userId`（基数高）或 `{userId, _id: hashed}` 复合分片键。绝对不要用自增 ID 或 ObjectId 做分片键，会导致写入热点。"

**Q：MongoDB 支持事务吗？**
"4.0 开始支持多文档事务，但有性能代价。单文档操作天生是原子性的（不需要事务）。多文档事务需要加锁，并发性能会下降，高并发场景要谨慎使用。如果可以，尽量用嵌入模型把相关数据放在一个文档里，避免多文档事务。如果一定要跨文档一致性，可以考虑用 Change Stream 做最终一致性。"

**Q：MongoDB 的索引和 MySQL 有什么不同？**
"MongoDB 支持多种索引类型：单字段索引、复合索引、多键索引（数组字段）、文本索引（全文搜索）、地理空间索引（2dsphere）。和 MySQL 一样，复合索引有最左前缀原则。不同的是 MongoDB 还有 TTL 索引（自动过期文档，适合日志场景）和部分索引（只对满足条件的文档建索引，节省空间）。索引调优用 `explain("executionStats")` 看执行计划。"

---

## 本文总结

**MongoDB** 是文档型 NoSQL 数据库，核心要点：

- **文档模型**：BSON 格式，Schema 灵活，支持嵌套对象和数组，适合半结构化数据
- **存储引擎**：WiredTiger（压缩存储 + MVCC + Journal 日志）
- **副本集**：1 Primary + N Secondary，自动故障转移，Write Concern 控制可靠性
- **分片集群**：内置水平扩展，Mongos 路由 + 分片 + Config Server，分片键选择是关键
- **数据建模**：嵌入（一对少）vs 引用（一对多），嵌入读性能好，引用写性能好
- **事务**：单文档原子性（天生），多文档事务（4.0+，有性能代价）
- **适用场景**：内容管理、物联网、实时分析、日志；不适用：强事务、复杂 JOIN 场景

**高频面试考点**：副本集选举机制、分片键选择策略、嵌入 vs 引用、Write Concern/Read Concern、索引类型、MongoDB vs MySQL 对比。

---

**关联文档**：
- [[MySQL体系结构]]（关系型 vs 文档型架构对比）
- [[索引原理与优化]]（MongoDB 索引 vs B+树索引）
- [[MVCC与事务处理]]（WiredTiger MVCC vs InnoDB MVCC）
- [[SQL优化与执行计划]]（MongoDB explain vs EXPLAIN）
- [[Elasticsearch核心概念与架构]]（MongoDB 主存储 + ES 搜索引擎组合架构）
