# MongoDB 索引与查询优化

## 这个问题为什么存在？

MongoDB 在数据量增大时，查询性能会急剧下降：

```
没有索引时（全集合扫描 COLSCAN）：
  db.orders.find({ userId: 12345 })
  → 扫描所有文档（假设 1000 万条），找到匹配的记录
  → 耗时：几秒到几十秒（取决于数据量）

有索引后（索引扫描 IXSCAN）：
  db.orders.createIndex({ userId: 1 })
  → 直接通过 B 树索引定位到 userId=12345 的文档
  → 耗时：几毫秒
```

**索引的作用和 MySQL 一样**：用额外的存储空间 + 写入开销，换取查询性能的数量级提升。

但 MongoDB 的索引类型和优化策略和 MySQL 有显著不同——尤其是**多键索引（数组索引）**和**聚合管道优化**，是 MongoDB 独有的重点。

---

## 它是怎么解决问题的？

### 一、MongoDB 索引类型

```
┌──────────────────────────────────────────────────────────────┐
│                MongoDB 索引类型一览                            │
│                                                              │
│  1. 单字段索引（Single Field）                               │
│     db.col.createIndex({ userId: 1 })                       │
│     → 最常用，B 树结构，支持精确匹配和范围查询              │
│                                                              │
│  2. 复合索引（Compound）                                     │
│     db.col.createIndex({ userId: 1, createdAt: -1 })        │
│     → 最左前缀原则（和 MySQL 一样）                         │
│                                                              │
│  3. 多键索引（Multikey）← MongoDB 独有！                    │
│     db.col.createIndex({ tags: 1 })                         │
│     → 数组字段自动创建多键索引                              │
│     → 一个文档在索引里有多个条目（数组有几个元素就有几个）   │
│                                                              │
│  4. 文本索引（Text）                                        │
│     db.col.createIndex({ content: "text" })                 │
│     → 支持全文搜索（但中文分词弱，生产用 ES 更好）          │
│                                                              │
│  5. 地理空间索引（2dsphere）                                │
│     db.col.createIndex({ location: "2dsphere" })            │
│     → 支持附近的人、地理围栏等 LBS 查询                    │
│                                                              │
│  6. 哈希索引（Hashed）                                      │
│     db.col.createIndex({ userId: "hashed" })                │
│     → 哈希分片时自动创建，等值查询快，不支持范围查询        │
│                                                              │
│  7. 部分索引（Partial）                                     │
│     db.col.createIndex({ userId: 1 }, { partialFilterExpression: { status: "active" } }) │
│     → 只对满足条件的文档建索引（节省空间）                   │
│                                                              │
│  8. TTL 索引（Time-To-Live）                                │
│     db.col.createIndex({ createdAt: 1 }, { expireAfterSeconds: 3600 }) │
│     → 自动删除过期文档（适合日志、验证码等临时数据）         │
└──────────────────────────────────────────────────────────────┘
```

#### 多键索引（Multikey Index）详解

这是 MongoDB 最有特色的索引类型：

```javascript
// 文档有数组字段
{
  "username": "zhangsj",
  "tags": ["Java", "MongoDB", "微服务"]
}

// 对 tags 建索引
db.users.createIndex({ tags: 1 })

// 查询：会用到多键索引
db.users.find({ tags: "MongoDB" })
// → 索引里有 3 条记录指向同一个文档
// → 查询效率和高基数的单字段索引一样快
```

```
多键索引的限制：
  - 复合索引里，最多只能有一个字段是数组类型
    ✅ { userId: 1, tags: 1 }   → tags 是数组，OK（只有一个数组字段）
    ❌ { tags: 1, categories: 1 } → 两个数组字段，报错
  - 数组字段的索引条目数 = 数组元素个数
    → 数组很大时（如 tags 有 1000 个元素），索引条目暴增
    → 写入性能下降，索引变大
```

---

### 二、复合索引与最左前缀原则

和 MySQL 一样，MongoDB 的复合索引遵循**最左前缀原则**。

```javascript
// 创建复合索引
db.orders.createIndex({ userId: 1, status: 1, createdAt: -1 })
// 索引键顺序：userId（升序）→ status（升序）→ createdAt（降序）

// ✅ 能用到索引的查询
db.orders.find({ userId: 123 })                          // 用前 1 个键
db.orders.find({ userId: 123, status: "PAID" })          // 用前 2 个键
db.orders.find({ userId: 123, status: "PAID", createdAt: { $gt: ISODate("2024-01-01") } })  // 用全部 3 个键
db.orders.find({ userId: 123 }).sort({ createdAt: -1 })  // 索引覆盖排序

// ❌ 用不到索引的查询
db.orders.find({ status: "PAID" })                       // 没有 userId（最左前缀）
db.orders.find({ userId: { $gt: 100 }, status: "PAID" }) // userId 是范围查询，后面的 status 用不到索引

// ✅ 索引排序优化（不需要额外排序）
db.orders.find({ userId: 123 }).sort({ status: 1, createdAt: -1 })
// → 和索引顺序一致（userId 精确匹配后，按 status 升序、createdAt 降序）
// → 不需要内存排序（stage 里没有 SORT）

// ❌ 索引排序不匹配（需要额外 SORT）
db.orders.find({ userId: 123 }).sort({ createdAt: -1, status: 1 })
// → 和索引顺序不一致，需要内存排序
```

#### ESR 原则（Equality → Sort → Range）

MongoDB 官方推荐的复合索引字段顺序：

```
ESR = Equality（等值查询）→ Sort（排序字段）→ Range（范围查询）

示例：
  查询：{ userId: 123, status: "PAID" }.sort({ createdAt: -1 }).limit(20)
  最优索引：{ userId: 1, status: 1, createdAt: -1 }
           ↑等值        ↑等值        ↑排序

  查询：{ userId: 123, createdAt: { $gt: ISODate("2024-01-01") } }
  最优索引：{ userId: 1, createdAt: -1 }
           ↑等值        ↑范围（放最后）
```

---

### 三、查询执行计划（explain）

MongoDB 的 `explain()` 类似 MySQL 的 `EXPLAIN`，是索引优化的核心工具。

```javascript
// 查看执行计划
db.orders.find({ userId: 123, status: "PAID" }).explain("executionStats")

// 输出关键字段解读：
{
  "queryPlanner": {
    "winningPlan": {
      "stage": "FETCH",
      "inputStage": {
        "stage": "IXSCAN",          // ✅ 用了索引（好的）
        "keyPattern": { "userId": 1, "status": 1 },
        "indexName": "userId_1_status_1"
      }
    }
  },
  "executionStats": {
    "nReturned": 100,               // 返回了 100 条
    "executionTimeMillis": 5,         // 耗时 5ms（好！）
    "totalKeysExamined": 100,        // 索引扫描了 100 个条目
    "totalDocsExamined": 100,        // FETCH 阶段扫描了 100 个文档
    // totalDocsExamined ≈ nReturned → 索引覆盖得好
    // totalDocsExamined >> nReturned → 索引不好，回表次数多
  }
}
```

#### 执行阶段（Stage）解读

| Stage | 含义 | 好不好 |
|-------|------|--------|
| `IXSCAN` | 索引扫描 | ✅ 好 |
| `COLLSCAN` | 全集合扫描 | ❌ 坏（数据量大时） |
| `FETCH` | 根据索引指针取文档 | ⚠️ 正常（不可避免） |
| `SORT` | 内存排序 | ❌ 坏（应该用索引排序） |
| `PROJECTION` | 投影（只返回部分字段） | ✅ 好 |
| `LIMIT` | 限制返回数量 | ✅ 好 |
| `SKIP` | 跳过文档（分页用） | ⚠️ `skip` 大页数时很慢 |

```javascript
// ❌ 深度分页问题（和 MySQL 的 LIMIT 10000, 20 一样慢）
db.orders.find().sort({ _id: 1 }).skip(10000).limit(20)
// → 要扫描前 10000 条，然后丢弃，非常慢

// ✅ 正确：用游标分页（Range 分页）
var lastId = ObjectId("...")  // 上一页最后一条的 _id
db.orders.find({ _id: { $gt: lastId } }).sort({ _id: 1 }).limit(20)
// → 直接用索引定位，不需要 SKIP
```

---

### 四、聚合管道（Aggregation Pipeline）优化

MongoDB 的聚合管道是比 `find()` 更强大的查询工具，类似 SQL 的 `GROUP BY` + 子查询。

```javascript
// 聚合管道示例：统计每个用户的订单总金额
db.orders.aggregate([
  { $match: { status: "PAID" } },           // ① 过滤（能用索引）
  { $group: {
      _id: "$userId",
      totalAmount: { $sum: "$amount" },
      count: { $sum: 1 }
  }},
  { $sort: { totalAmount: -1 } },           // ③ 排序
  { $limit: 10 }                             // ④ 取前 10
])
```

#### 聚合管道优化规则

MongoDB 的聚合优化器会自动重排阶段，但了解规则有助于写出高效管道：

```
优化规则 1：$match 和 $project 尽量提前
  → 尽早过滤数据，减少后续阶段处理的数据量

优化规则 2：如果 $match 在 $unwind 之后，
  → 优化器会自动把 $match 移到 $unwind 之前（如果条件不涉及展开字段）

优化规则 3：$sort + $match 可以只用索引
  → 如果 $match 的字段和 $sort 的字段有复合索引，效率最高

优化规则 4：避免 $unwind 大数组
  → $unwind 会把一个文档变成 N 个文档（N = 数组长度）
  → 数组很大时，内存和性能压力巨大
  → 用 $filter 或 $map 在数组内操作，避免 $unwind
```

```javascript
// ❌ 慢：$unwind 大数组
db.users.aggregate([
  { $unwind: "$orders" },  // 如果 orders 数组有 1000 个元素，文档膨胀 1000 倍
  { $match: { "orders.status": "PAID" } }
])

// ✅ 快：用 $filter 在数组内过滤
db.users.aggregate([
  { $project: {
      username: 1,
      paidOrders: {
        $filter: {
          input: "$orders",
          as: "order",
          cond: { $eq: ["$$order.status", "PAID"] }
        }
      }
  }}
])
```

#### 聚合管道的内存限制

```
默认限制：每个阶段最多使用 100MB 内存
超过限制报错：Exceeded memory limit for $group

解决方案：
  1. 加 allowDiskUse: true（用磁盘临时文件，慢但能跑）
     db.orders.aggregate([...], { allowDiskUse: true })

  2. 优化管道，尽早 $match 和 $project（减少数据量）

  3. 用索引覆盖 $sort（避免内存排序）
```

---

### 五、索引策略与最佳实践

#### 5.1 索引覆盖查询（Covered Query）

```javascript
// ❌ 需要 FETCH（回表）
db.orders.find(
  { userId: 123, status: "PAID" },
  { _id: 0, userId: 1, status: 1, total: 1 }
)
// → 索引里没有 total 字段，需要回表取文档

// ✅ 索引覆盖（不需要 FETCH）
db.orders.createIndex({ userId: 1, status: 1, total: 1 })
// → 查询所需字段全部在索引里，直接返回，不需要回表
// → executionStats 里 docsExamined = 0（没有回表！）
```

#### 5.2 写多读少的场景，索引要克制

```
索引的代价：
  - 每次写入（INSERT/UPDATE/DELETE）都要更新所有相关索引
  - 索引越多，写入越慢
  - 索引占用磁盘空间

经验法则：
  - 写多读少（如日志、事件流）→ 索引尽可能少（只保留必要的查询索引）
  - 读多写少（如配置表、字典表）→ 可以适当多建索引
  - 复合索引优于多个单字段索引（一个复合索引可以服务多个查询）
```

#### 5.3 不要在低基数字段上建 B 树索引

```javascript
// ❌ 不好的索引：gender（只有 2 个值）
db.users.createIndex({ gender: 1 })
// → 索引选择性差，过滤效果差，查询优化器可能选择不用索引

// ✅ 好的索引：userId（每个用户唯一）
db.users.createIndex({ userId: 1 })
// → 选择性好，索引过滤效果好

// 低基数字段的正确用法：放在复合索引的后面
db.orders.createIndex({ userId: 1, status: 1 })
// → status 虽然基数低，但和 userId 组合后选择性很好
```

---

## 它和相似方案的本质区别是什么？

### MongoDB 索引 vs MySQL 索引

| 维度 | MongoDB | MySQL（InnoDB） |
|------|---------|-----------------|
| 索引结构 | B 树（类似 B+树，但实现不同） | B+树 |
| 复合索引 | 最左前缀原则（和 MySQL 一样） | 最左前缀原则 |
| 数组索引 | **多键索引（独有）** | 不支持（需要中间表） |
| 部分索引 | 支持（partialFilterExpression） | MySQL 8.0+ 支持（部分索引） |
| 哈希索引 | 支持（Hashed，用于分片） | Memory 引擎支持，InnoDB 有自适应哈希索引 |
| 全文索引 | 支持（但中文弱） | 支持（但中文需要 ngram 插件） |
| 执行计划 | `explain("executionStats")` | `EXPLAIN ANALYZE` |

```
本质区别：MongoDB 的多键索引是关系型数据库没有的

MySQL 要支持"标签"查询：
  → 要建中间表：user_tags(user_id, tag_id)，然后 JOIN
  → 查询慢，索引复杂

MongoDB 支持"标签"查询：
  → tags 是数组，直接建多键索引
  → db.users.find({ tags: "MongoDB" })  → 走索引，快
```

### MongoDB 聚合 vs SQL GROUP BY

| 维度 | MongoDB Aggregation | SQL GROUP BY |
|------|-------------------|---------------|
| 表达能力 | 极强（支持数组操作、$unwind、$facet 等） | 中等（复杂分析需要子查询或 CTE） |
| 性能 | 取决于管道优化，内存受限 | 优化器成熟，但复杂查询难写 |
| 学习曲线 | 陡峭（类 JSON 语法，不直观） | 平缓（声明式 SQL） |
| 适用场景 | 文档内数组聚合、多级分组、数据转换 | 传统聚合分析 |

```javascript
// MongoDB 聚合：统计每个用户的订单金额分布
db.orders.aggregate([
  { $bucket: {
      groupBy: "$amount",
      boundaries: [0, 100, 500, 1000, Infinity],
      default: "other",
      output: {
        count: { $sum: 1 },
        users: { $addToSet: "$userId" }
      }
  }}
])
// → SQL 需要 CASE WHEN + GROUP BY，写法更复杂
```

---

## 正确使用方式

### 正确用法

**1. 用 explain 验证索引效果**

```javascript
// ✅ 正确：建索引前先用 explain 看执行计划
db.orders.find({ userId: 123, status: "PAID" }).explain("executionStats")
// → 如果 stage 是 COLLSCAN，说明没用索引，需要建索引
// → 如果 totalDocsExamined >> nReturned，说明索引不够好

// 建索引后再次 explain，确认 stage 变成 IXSCAN
db.orders.createIndex({ userId: 1, status: 1 })
db.orders.find({ userId: 123, status: "PAID" }).explain("executionStats")
```

**2. 复合索引遵循 ESR 原则**

```javascript
// 查询场景：按 userId 查，按创建时间排序，分页
db.orders.find({ userId: 123 })
  .sort({ createdAt: -1 })
  .limit(20)

// ✅ 最优索引（ESR：等值 → 排序 → 无范围）
db.orders.createIndex({ userId: 1, createdAt: -1 })

// 查询场景：按状态 + 时间范围查
db.orders.find({
  status: "PAID",
  createdAt: { $gt: ISODate("2024-01-01") }
}).sort({ createdAt: -1 })

// ✅ 最优索引（ESR：等值 → 排序 → 范围（范围放最后））
db.orders.createIndex({ status: 1, createdAt: -1 })
```

**3. 用部分索引节省空间**

```javascript
// 场景：订单表有 1000 万条，其中 90% 是"已完成"状态，查询只查"待支付"和"已支付"
// ❌ 全量索引（浪费 90% 的索引空间）
db.orders.createIndex({ userId: 1, status: 1 })

// ✅ 部分索引（只索引活跃订单，节省空间）
db.orders.createIndex(
  { userId: 1, createdAt: -1 },
  { partialFilterExpression: { status: { $in: ["PENDING", "PAID"] } } }
)
// → 索引大小减少 90%，查询性能不变
```

### 错误用法及后果

**错误1：在低基数字段上建单独索引**

```javascript
// 错误：status 只有 5 种状态，建索引效果差
db.orders.createIndex({ status: 1 })
// → 查询优化器可能选择不用这个索引（回表成本太高）
// → 白建了索引，还拖慢写入

// 正确：把低基数字段放在复合索引的后面
db.orders.createIndex({ userId: 1, status: 1 })
```

**错误2：索引建太多，写入性能暴跌**

```
场景：某集合有 20 个索引（每个查询都建一个索引）
后果：
  - 每次 INSERT 要更新 20 个索引 → 写入延迟从 5ms 涨到 50ms
  - 索引占用磁盘空间 是数据本身的 2-3 倍
  - 索引缓存命中率下降（内存不够装下所有索引）

修复：合并索引（用复合索引代替多个单字段索引）
```

**错误3：用 `$or` 导致索引失效**

```javascript
// ❌ 慢：$or 可能导致全表扫描
db.orders.find({
  $or: [
    { userId: 123, status: "PAID" },
    { userId: 456, status: "PAID" }
  ]
})
// → MongoDB 对 $or 的索引使用不够智能，可能不走索引

// ✅ 快：改写为 $in
db.orders.find({
  userId: { $in: [123, 456] },
  status: "PAID"
})
// → 可以用复合索引 { userId: 1, status: 1 }
```

---

## 边界情况和坑

### 坑1：索引创建阻塞（MongoDB 4.2 之前）

**现象**：在大集合（千万级）上建索引，整个集合无法写入。

**原因**：MongoDB 4.2 之前，建索引默认是前台（foreground）模式，会阻塞所有写操作。

```javascript
// MongoDB 4.2+ 默认是后台构建，不阻塞写
// 但如果索引很大，还是会影响性能

// 正确：在流量低峰期建索引，或者用滚动构建
// 1. 在 Secondary 上建索引（不影
// 2. 建完后切换 Primary，再在原来的 Primary 上建索引
```

### 坑2：TTL 索引删除不及时

**现象**：设置了 TTL 索引，但过期文档没有及时删除。

**原因**：TTL 索引的删除是**后台线程定期执行**的（默认每 60 秒检查一次），不是实时删除。

```javascript
// TTL 索引：
db.logs.createIndex({ createdAt: 1 }, { expireAfterSeconds: 3600 })
// → 文档过期后，最多 60 秒 + 1 小时 = 最多 2 小时才被删除

// 如果需要精确控制删除时机，不要用 TTL 索引
// 用定时任务手动删除：
db.logs.deleteMany({ createdAt: { $lt: new Date(Date.now() - 3600 * 1000) } })
```

### 坑3：复合索引字段顺序错误，导致索引失效

```javascript
// 索引：{ a: 1, b: 1, c: 1 }
// 查询：{ a: 1, c: 1 }  → 只能用索引的前 1 个字段（a），c 用不到索引

// 如果查询是：
//   { a: 1, b: 1, c: 1 }       → 全用上 ✅
//   { a: 1, b: 1 }             → 用上前 2 个 ✅
//   { a: 1 }                   → 用上第 1 个 ✅
//   { b: 1 }                   → 用不上 ❌（不遵循最左前缀）
//   { a: 1, c: 1 }             → 只用上第 1 个 ⚠️（c 用不上）
```

### 坑4：地理空间索引的精度问题

**现象**：`$near` 查询返回的结果距离不准确。

**原因**：`2d` 索引（平面几何）有精度问题，应该用 `2dsphere`（球面几何）。

```javascript
// ❌ 错误：用 2d 索引（平面，适合小范围）
db.places.createIndex({ location: "2d" })

// ✅ 正确：用 2dsphere（球面，适合全球范围）
db.places.createIndex({ location: "2dsphere" })
// location 字段格式：{ type: "Point", coordinates: [经度, 纬度] }
```

---

## 面试话术

**Q：MongoDB 的索引和 MySQL 有什么不同？**
"最大的不同是 MongoDB 支持多键索引（数组字段索引），这是关系型数据库没有的。另外 MongoDB 有部分索引（只对满足条件的文档建索引）和 TTL 索引（自动过期文档），MySQL 需要自己实现。复合索引的最左前缀原则和 MySQL 一样。MongoDB 的 `explain()` 对应 MySQL 的 `EXPLAIN`，但输出格式不同。"

**Q：复合索引的字段顺序怎么选？**
"遵循 ESR 原则：Equality（等值查询）放最前，Sort（排序字段）放中间，Range（范围查询）放最后。原因是索引是 B 树结构，精确匹配可以快速定位，排序字段如果和索引顺序一致就不需要额外排序，范围查询会让后面的字段无法使用索引，所以放最后。"

**Q：聚合管道怎么优化？**
"三个要点：第一，`$match` 和 `$project` 尽量提前，尽早减少数据量；第二，避免对大数组做 `$unwind`，用 `$filter` 或 `$map` 在数组内操作；第三，注意内存限制（默认 100MB），超过要加 `allowDiskUse: true`，但最好是从管道设计上减少数据量。"

**Q：MongoDB 深度分页怎么优化？**
"不能用 `skip()` 做大数量分页，因为 `skip` 要扫描并丢弃前面的所有文档，性能是 O(N) 的。正确做法是用**游标分页**（Range 分页）：记录上一页最后一条的 `_id` 或排序字段值，下一页查询用 `$gt` 直接定位。这样性能是 O(1) 的，不受页码影响。"

---

## 本文总结

**MongoDB 索引与查询优化**核心要点：

- **索引类型**：单字段、复合、多键（数组）、文本、地理空间、哈希、部分、TTL
- **复合索引**：最左前缀原则，ESR（等值→排序→范围）设计原则
- **执行计划**：`explain("executionStats")` 看 `stage`（IXSCAN 好，COLLSCAN 坏）、`totalDocsExamined`、`executionTimeMillis`
- **聚合管道优化**：`$match`/`$project` 提前、避免大数组 `$unwind`、注意 100MB 内存限制
- **深度分页**：用游标分页（`$gt`）代替 `skip()`
- **索引策略**：写多读少要克制索引数量，低基数字段不要单独建索引，用复合索引覆盖查询

**高频面试考点**：复合索引设计（ESR）、多键索引原理、`explain()` 解读、聚合管道优化、深度分页优化。

---

**关联文档**：
- [[MongoDB核心概念与架构]]（存储引擎、WiredTiger、副本集）
- [[B+树索引原理]]（MongoDB B树 vs MySQL B+树对比）
- [[SQL优化与执行计划]]（MongoDB explain vs MySQL EXPLAIN 对比）
- [[MongoDB事务与一致性]]（索引对事务性能的影响）
