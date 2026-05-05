# MongoDB 事务与一致性

## 这个问题为什么存在？

MongoDB 早期版本（3.x 及之前）**只支持单文档原子性**，跨文档操作没有事务保证：

```
MongoDB 3.x 的问题：
  场景：用户下单，需要：
    1. 在 orders 集合插入订单
    2. 在 inventory 集合扣减库存
    3. 在 users 集合更新用户积分

  问题：步骤 1 成功了，步骤 2 失败了 → 数据不一致！
  → 没有事务回滚机制，只能靠应用层补偿（复杂且不可靠）

MySQL 对比：
  START TRANSACTION;
    INSERT orders ...;
    UPDATE inventory SET stock = stock - 1 ...;
  COMMIT;  -- 要么全成功，要么全失败
  → 天生支持 ACID
```

**MongoDB 4.0**（2018 年）开始支持多文档事务，**4.2**（2019 年）支持分片集群上的事务，**5.0**（2021 年）支持原生时间序列集合 + 进一步优化事务性能。

但 **MongoDB 的事务有性能代价**，不能像 MySQL 那样随意使用。

---

## 它是怎么解决问题的？

### 一、单文档原子性（不需要事务）

MongoDB 的单个文档操作是**天然原子**的，这是和关系型数据库最大的使用习惯差异。

```javascript
// ✅ 单文档操作天然原子（不需要事务）
db.orders.updateOne(
  { _id: ObjectId("..."), status: "PENDING" },
  { $set: { status: "PAID" }, $inc: { version: 1 } }
)
// → 这个操作要么完全成功，要么完全失败（原子性）
// → 不需要事务！

// ✅ 用嵌入模型避免多文档事务
{
  "_id": ObjectId("..."),
  "status": "PENDING",
  "items": [ ... ],
  "total": 299,
  "inventoryUpdated": false  // 嵌入库存状态
}
// → 订单和库存状态在同一个文档里，一次写入原子完成
```

```
为什么单文档原子性就够了？
  → MongoDB 的文档模型允许把相关数据嵌入同一个文档
  → 关系型数据库要拆多张表，所以需要跨行/跨表事务
  → MongoDB 通过合理的文档建模，大部分场景不需要多文档事务
```

---

### 二、多文档事务（4.0+）

```javascript
// MongoDB 4.0+ 多文档事务（类似 MySQL 的事务）
const session = db.getMongo().startSession()
session.startTransaction({
  readConcern: { level: "majority" },
  writeConcern: { w: "majority" },
  readPreference: "primary"
})

try {
  // 步骤 1：插入订单
  db.orders.insertOne(
    { userId: 123, total: 299, status: "PAID" },
    { session }
  )

  // 步骤 2：扣减库存
  db.inventory.updateOne(
    { productId: 456, stock: { $gte: 1 } },
    { $inc: { stock: -1 } },
    { session }
  )

  // 步骤 3：更新用户积分
  db.users.updateOne(
    { userId: 123 },
    { $inc: { points: 10 } },
    { session }
  )

  session.commitTransaction()  // 提交事务
  print("事务提交成功")

} catch (e) {
  session.abortTransaction()   // 回滚事务
  print("事务失败，已回滚：" + e)
}
```

#### Java 中的多文档事务

```java
@Transactional  // Spring 声明式事务，自动处理 MongoDB 事务
public void createOrderWithTransaction(Order order) {
    mongoTemplate.insert(order);

    Update update = new Update().inc("stock", -order.getQuantity());
    mongoTemplate.updateFirst(
        query(where("productId").is(order.getProductId()).and("stock").gte(order.getQuantity())),
        update,
        Product.class
    );

    // 如果这里的任何操作失败，Spring 会自动回滚整个事务
}
```

---

### 三、读关注（Read Concern）和写关注（Write Concern）

MongoDB 的事务隔离级别通过 **Read Concern** 和 **Write Concern** 共同控制。

#### 读关注（Read Concern）

控制读操作能看到什么样的数据：

```javascript
// 读关注的级别
db.orders.find().readConcern("local")
// local    → 读最新数据（可能读到未提交的，类似 READ UNCOMMITTED）
// majority → 读已被大多数节点确认的数据（推荐，类似 READ COMMITTED）
// linearizable → 线性一致性（最强，但性能最差，适合金融场景）
// snapshot → 快照读（事务内用，保证可重复读）
```

#### 写关注（Write Concern）

控制写操作需要多少节点确认：

```javascript
db.orders.insertOne(
  { userId: 123, total: 299 },
  { writeConcern: { w: 1 } }       // 只要 Primary 写入就返回（快，但可能丢数据）
)

db.orders.insertOne(
  { userId: 123, total: 299 },
  { writeConcern: { w: "majority", wtimeout: 5000 } }  // 大多数节点确认（推荐）
)

db.orders.insertOne(
  { userId: 123, total: 299 },
  { writeConcern: { w: 3 } }       // 3 个节点确认（最安全，但慢）
)
```

#### 事务中的组合

```javascript
session.startTransaction({
  readConcern: { level: "snapshot" },        // 事务内快照读（可重复读）
  writeConcern: { w: "majority" }           // 提交时大多数节点确认
})
// → 这个组合提供了类似 MySQL RR（Repeatable Read）的隔离级别
```

---

### 四、MongoDB 事务隔离级别

MongoDB 的事务隔离级别和 MySQL 不同，它没有"可串行化"这么强的隔离级别：

```
MongoDB 事务隔离级别：
  ┌─────────────────────────────────────────────────────┐
  │ 隔离级别              │ 脏读 │ 不可重复读 │ 幻读  │
  │───────────────────────│──────│──────────│──────│
  │ readConcern: local    │ 可能 │ 可能      │ 可能  │
  │ readConcern: majority │ 不会 │ 可能      │ 可能  │
  │ readConcern: snapshot │ 不会 │ 不会      │ 不会* │
  └─────────────────────────────────────────────────────┘
  * snapshot 在单个集合内防幻读，跨分片有限制
```

```
和 MySQL 对比：
  MySQL      →  READ UNCOMMITTED / READ COMMITTED / REPEATABLE READ / SERIALIZABLE
  MongoDB    →  local / majority / snapshot / linearizable（linearizable 是读关注，不是隔离级别）

  MongoDB 没有 SERIALIZABLE 隔离级别
  → 需要严格串行化场景，要用应用层加锁（findAndModify 原子操作）
```

---

### 五、Change Stream（变更流）

MongoDB 4.0+ 的 Change Stream 是**监听数据变更**的强大功能，类似 MySQL 的 Binlog。

```javascript
// 监听 orders 集合的变更
const changeStream = db.orders.watch()

changeStream.on("change", (next) => {
  // next 包含所有变更信息
  print(JSON.stringify(next))

  // 示例输出：
  // {
  //   "_id": { ... },                           // 恢复令牌（resume Token）
  //   "operationType": "insert",                // 操作类型：insert/update/delete/replace
  //   "ns": { "db": "mydb", "coll": "orders" },
  //   "documentKey": { "_id": ObjectId("...") },
  //   "fullDocument": { ... }                  // 变更后的完整文档（需配置）
  // }
})

// 只监听"已支付"的订单变更
const pipeline = [
  { $match: { "fullDocument.status": "PAID" } }
]
const changeStream = db.orders.watch(pipeline)
```

#### Change Stream 的典型用途

| 场景 | 说明 |
|------|------|
| **数据同步** | MongoDB → Elasticsearch / 数据仓库 |
| **实时通知** | 订单状态变更 → 推送用户 |
| **缓存失效** | 数据变更 → 删除 Redis 缓存 |
| **审计日志** | 记录所有数据变更（合规要求） |
| **事件驱动架构** | 数据变更触发下游服务 |

```java
// Java 中使用 Change Stream（Spring Data MongoDB）
@ChangeStreamListener
public void onOrderChange(ChangeStreamEvent<Order> event) {
    switch (event.getOperationType()) {
        case INSERT:
            // 同步到 Elasticsearch
            elasticsearchTemplate.save(event.getBody());
            break;
        case UPDATE:
            // 删除缓存
            redisTemplate.delete("order:" + event.getBody().getId());
            break;
    }
}
```

---

## 它和相似方案的本质区别是什么？

### MongoDB 事务 vs MySQL 事务

| 维度 | MongoDB（4.0+） | MySQL（InnoDB） |
|------|-----------------|-----------------|
| 单文档原子性 | 天生支持 | 行级锁保证 |
| 多文档事务 | 4.0+ 支持（有性能代价） | 天生支持（成熟稳定） |
| 隔离级别 | snapshot（类似 RR） | RR（默认）/ RC / Serializable |
| 锁粒度 | 文档级锁（WiredTiger） | 行级锁（InnoDB） |
| 事务性能 | 中等（有开销） | 高（优化成熟） |
| 分片事务 | 4.2+ 支持（有一定延迟） | 需要分库分表中间件（如 Seata） |
| 适用场景 | 单文档模型优先，事务为辅 | 强事务场景首选 |

```
本质区别：设计哲学不同

MySQL：
  → 假设你需要事务，默认提供 ACID
  → 数据建模时鼓励规范化（NF1/NF2/NF3）
  → JOIN + 事务保证数据一致性

MongoDB：
  → 假设大多数场景不需要跨文档事务
  → 通过嵌入模型把相关数据放在一个文档里
  → 单文档原子性 + Change Stream 事件驱动 → 最终一致性
  → 只有真正需要时才用多文档事务（有性能代价）
```

### MongoDB 事务 vs Redis 事务

| 维度 | MongoDB 事务 | Redis 事务（MULTI/EXEC） |
|------|--------------|--------------------------|
| 原子性 | 完全支持（回滚） | 不支持回滚（EXEC 前全部执行） |
| 隔离性 | snapshot 隔离级别 | 无隔离（EXEC 前不执行，EXEC 时一次性执行） |
| 一致性 | ACID 保证 | 不保证（某个命令失败不影响其他命令） |
| 适用场景 | 复杂业务事务 | 简单批量操作 |

---

## 正确使用方式

### 正确用法

**1. 优先用嵌入模型，避免多文档事务**

```javascript
// ❌ 不推荐：用多文档事务保证跨集合一致性
session.startTransaction()
db.orders.insertOne({ userId: 123, items: [...] }, { session })
db.inventory.updateOne({ productId: 456 }, { $inc: { stock: -1 } }, { session })
session.commitTransaction()
// → 事务有性能开销，能避免就避免

// ✅ 推荐：用嵌入模型，单文档原子操作
db.orders.insertOne({
  userId: 123,
  items: [ { productId: 456, quantity: 1, stockBefore: 100, stockAfter: 99 } ],
  status: "PAID"
})
// → 一次写入，原子完成，不需要事务
```

**2. 事务要尽量短小**

```javascript
// ❌ 错误：事务里做慢操作
session.startTransaction()
db.orders.insertOne({ ... }, { session })
sendEmail()              // 发送邮件（慢，阻塞事务）
callExternalAPI()        // 调用外部 API（更慢）
session.commitTransaction()
// → 事务持锁时间长，影响并发性能

// ✅ 正确：事务只做数据库操作，外部操作放外面
session.startTransaction()
db.orders.insertOne({ ... }, { session })
session.commitTransaction()

// 事务提交后再做外部操作
sendEmail()
callExternalAPI()
```

**3. 用 Write Concern + Read Concern 保证一致性**

```javascript
// ✅ 正确：金融场景，用最强一致性保证
session.startTransaction({
  readConcern: { level: "majority" },   // 读大多数节点确认的数据
  writeConcern: { w: "majority" }       // 写大多数节点确认
})
// → 不会出现"读到了没提交的数据"或"写入后节点挂了数据丢失"
```

### 错误用法及后果

**错误1：在高并发场景滥用多文档事务**

```javascript
// 错误：每个请求都开事务（性能暴跌）
app.post("/api/order", (req, res) => {
  const session = db.getMongo().startTransaction()
  // ... 事务操作
  session.commitTransaction()
})
// → 每个请求都开事务，WiredTiger 的快照数量暴增
// → 内存占用升高，性能下降 50% 以上

// 正确：只有真正需要跨文档原子性时才用事务
// 其他场景用嵌入模型 + 单文档原子操作
```

**错误2：事务超时没有处理**

```javascript
// 错误：事务默认 60 秒超时，超时后自动终止
session.startTransaction()
// ... 做一些慢操作（超过 60 秒）
session.commitTransaction()  // 报错：Transaction timed out
// → 事务已被终止，需要重新执行

// 正确：设置合理的超时时间，并在代码中处理超时
session.startTransaction({ maxCommitTimeMS: 30000 })  // 30 秒超时
try {
  // ... 快速完成事务操作
  session.commitTransaction()
} catch (e) {
  session.abortTransaction()
  // 重试逻辑...
}
```

**错误3：在分片集群上用事务，没有考虑性能**

```javascript
// 错误：跨分片事务（性能差）
session.startTransaction()
db.orders.insertOne({ userId: 123, shardKey: "shardA" }, { session })
db.products.insertOne({ productId: 456, shardKey: "shardB" }, { session })
session.commitTransaction()
// → 跨分片事务需要 2PC（两阶段提交），延迟高

// 正确：让相关数据存储在同一分片
// 用 userId 做分片键，订单和用户信息在同一分片
// → 事务不需要跨分片，性能好
```

---

## 边界情况和坑

### 坑1：事务中的快照读可能读到旧数据

**现象**：事务开始后，其他事务提交了新数据，当前事务读不到。

```javascript
// Session A
sessionA.startTransaction({ readConcern: { level: "snapshot" } })
db.orders.find({ userId: 123 })  // 读到 0 条

// Session B（另一个会话）
db.orders.insertOne({ userId: 123, total: 299 })  // 插入了一条

// Session A（继续）
db.orders.find({ userId: 123 })  // 还是读到 0 条！（快照读，可重复读）
sessionA.commitTransaction()
```

**这是特性，不是 Bug**：`snapshot` 隔离级别保证可重复读，事务内读到的数据是一致的。

---

### 坑2：Change Stream 的恢复令牌会过期

**现象**：用旧的恢复令牌（resume Token）恢复 Change Stream，报错。

```javascript
// Change Stream 的 resume Token 依赖 Oplog
// Oplog 的大小有限（默认占用 5% 磁盘空间）
// 如果 Oplog 被覆盖，旧的 resume Token 就无效了

// 正确：定期保存 resume Token 到持久化存储
const lastToken = getLastTokenFromDB()  // 从数据库读取上次的位置
const changeStream = db.orders.watch([], { resumeAfter: lastToken })

changeStream.on("change", (next) => {
  saveTokenToDB(next._id)  // 处理完后保存新的 resume Token
})
```

---

### 坑3：WiredTiger 缓存压力导致事务失败

**现象**：在高并发事务场景下，报错 `Transaction was aborted, please retry`。

**原因**：WiredTiger 的缓存（默认占内存 50%）满了，事务无法分配快照内存。

```javascript
// 解决方案：
// 1. 增大 WiredTiger 缓存（需要重启）
//    storage.wiredTiger.engineConfig.cacheSizeGB: 容机器内存的 50%-1GB

// 2. 减小事务范围（减少事务内操作的文档数）

// 3. 用重试逻辑（事务失败自动重试）
function runTransactionWithRetry(db, txnFn) {
  while (true) {
    const session = db.getMongo().startSession()
    try {
      session.startTransaction()
      txnFn(session)
      session.commitTransaction()
      break
    } catch (e) {
      if (e.hasErrorLabel("TransientTransactionError")) {
        print("事务临时失败，重试...")
        continue  // 重试
      }
      throw e
    }
  }
}
```

---

**关联文档**：
- [[06_数据库/08_MongoDB/MongoDB核心概念与架构]]（副本集、分片、WiredTiger 存储引擎）
- [[06_数据库/03_事务与锁/ACID实现原理]]（MySQL 的 ACID 实现，对比 MongoDB）
- [[06_数据库/06_PostgreSQL/MVCC与事务处理]]（PostgreSQL 的 MVCC，对比 MongoDB 事务）
- [[06_数据库/08_MongoDB/MongoDB索引与查询优化]]（事务对索引的影响）
