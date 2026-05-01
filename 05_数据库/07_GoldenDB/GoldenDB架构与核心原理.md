# GoldenDB 架构与核心原理

## 这个问题为什么存在？

GoldenDB 是**中兴通讯自研的分布式数据库**，基于 MySQL 深度改造，主要面向 **金融核心系统**（银行核心、信用卡系统）。

```
典型使用场景：
  - 银行核心系统（替代 IBM DB2 + 小型机）
  - 信用卡系统（高并发交易 + 强一致性）
  - 需要 MySQL 协议兼容，但又要分布式能力的场景

为什么不用 TiDB / OceanBase？
  - GoldenDB 对 MySQL 协议兼容更好（业务迁移成本低）
  - 金融级高可用（RPO=0，RTO < 30s）
  - 支持 "灰度迁移"（从 MySQL 无缝切换到 GoldenDB）
```

**核心问题**：
1. GoldenDB 的分布式架构是怎么设计的（和 TiDB/OceanBase 有什么不同）？
2. 分片规则是什么？全局事务怎么保证一致性？
3. 扩容怎么做到不中断业务？
4. 金融场景下的高可用是怎么保证的？

---

## 它是怎么解决问题的？

### 一、整体架构（Shared-Nothing）

```
GoldenDB 集群架构：

                    ┌─────────────────────────────────┐
                    │         GTM（全局事务管理器）        │
                    │  分配全局事务 ID、全局时间戳        │
                    └──────────────┬──────────────────┘
                                       │
                    ┌─────────────────────────────────┐
                    │         GTM（备，高可用）          │
                    └──────────────┬──────────────────┘
                                       │
        ┌────────────────────────────┼────────────────────────────┐
        │                          │                          │
  ┌─────▼─────┐          ┌─────▼─────┐          ┌─────▼─────┐
  │ Data Node 1│          │ Data Node 2│          │ Data Node 3│
  │ (MySQL 改造)│          │ (MySQL 改造)│          │ (MySQL 改造)│
  │ Shard 1~64 │          │ Shard 65~128│          │ Shard 129~192│
  └──────┬─────┘          └──────┬─────┘          └──────┬─────┘
         │                        │                        │
  ┌─────▼─────┐          ┌─────▼─────┐          ┌─────▼─────┐
  │ 备 Data 1 │          │ 备 Data 2 │          │ 备 Data 3 │
  └────────────┘          └────────────┘          └────────────┘

关键组件：
  GTM（Global Transaction Manager）：全局事务管理器，类似 TiDB 的 PD
  Data Node：数据节点（MySQL 改造，存储分片数据）
  GTM 高可用：GTM 主宕机，备 GTM 接管（RPO=0）
```

#### 和 TiDB 架构对比

| 维度 | GoldenDB | TiDB |
|------|----------|-------|
| SQL 层 | GTM（集中式） | TiDB Server（无状态，可横向扩展） |
| 存储层 | Data Node（MySQL 改造） | TiKV（RocksDB 引擎） |
| 事务管理 | GTM 集中管理（单点瓶颈？） | PD + TSO（时间戳服务） |
| MySQL 兼容 | 很好（协议 + 语法高度兼容） | 好（协议兼容，部分语法不支持） |
| 金融场景优化 | 很多（灰度迁移、数据校验） | 较少 |

**GoldenDB 的优势**：MySQL 协议兼容更好，迁移成本极低。

### 二、分片规则（Sharding）

GoldenDB 支持多种分片策略：

```
分片规则类型：
  1. Hash 分片（默认，最常用）
     → 分片键取 Hash，均匀分布
     → 适合：用户 ID、订单 ID（均匀分布）

  2. Range 分片
     → 按范围分片（如：user_id 1~1000000 → Shard 1）
     → 适合：时间序列数据（按日期分片）

  3. List 分片
     → 按枚举值分片（如：city='北京' → Shard 1）
     → 适合：有明显的地域/类别特征

  4. 全局表（广播表）
     → 每个 Data Node 都存完整副本
     → 适合：小表（如：字典表、配置表）
```

#### 分布式事务（2PC 改造）

```
GoldenDB 的分布式事务（基于 2PC 改造）：

  Phase 1（Prepare）：
    GTM 向所有参与 Data Node 发 Prepare
    Data Node 写 Undo Log，返回 YES/NO

  Phase 2（Commit）：
    所有 Data Node 返回 YES → GTM 发 Commit
    任一 Data Node 返回 NO → GTM 发 Rollback

  区别（ vs 标准 2PC）：
    - GTM 有超时机制（防止阻塞）
    - 支持 "TRY_COMMIT"（尽量提交，允许部分失败）
    - 有后台 "事务回收线程"（清理悬挂事务）
```

**为什么不是 XA（标准 2PC）？**

```
标准 XA 的问题：
  1. 阻塞（TM Crash 后，所有 RM 阻塞）
  2. 单点故障（TM 是单点）
  3. 性能差（2 次网络 RTT）

GoldenDB 的改造：
  1. GTM 高可用（主备，RPO=0）
  2. 超时机制（防止阻塞）
  3. 局部优化（单分片事务，优化成 1PC）
```

### 三、全局时间戳（GTS）

GoldenDB 用 **GTM 分配全局时间戳**（类似 Google Spanner 的 TrueTime，但是软件实现）。

```
全局时间戳作用：
  1. 分布式事务的全局顺序（解决 "金鱼缸" 问题）
  2. MVCC 的全局快照（跨节点读一致性）
  3. 死锁检测（全局等待图）

GTM 分配时间戳：
  单调递增的 64 位整数
  → 高 32 位：物理时间（秒级）
  → 低 32 位：序列号（同一秒内的递增）
```

**GoldenDB 的 MVCC（跨节点一致性读）**：

```
问题：事务 T1 在 Node 1 写，事务 T2 在 Node 2 读
      Node 2 怎么知道 T1 的修改是否对 T2 可见？

解决：GTM 分配 "全局快照"（Snapshot Timestamp）
  T2 开始时有全局快照 ST
  → 只看 "提交时间戳 < ST" 的版本
  → 和 PostgreSQL 的 MVCC 类似，但是全局的
```

### 四、扩容机制（在线扩容）

```
扩容流程（以 Hash 分片为例）：

  1. 准备新节点（如：从 3 节点扩容到 4 节点）
  2. 计算新分片映射（Hash 槽从 3 个 → 4 个）
  3. 数据迁移（在线，不中断业务）：
     a. 源节点：标记 "待迁移" 的数据
     b. 迁移数据到目标节点
     c. 增量同步（迁移期间的新写入）
  4. 切换路由（GTM 更新路由表）
  5. 清理源节点（删除已迁移的数据）

关键：扩容期间，业务不中断（路由切换是原子操作）
```

#### 一致性 Hash（减少数据迁移）

```
标准 Hash 扩容：
  N → 2N，需要迁移几乎所有数据（大约 N/(N+1) 比例）

一致性 Hash：
  把 Hash 空间组织成 "环"
  → 扩容时，只迁移受影响的分片（大约 1/N 的数据）
  → 但 GoldenDB 用 "扩槽" 方式（类似 Redis Cluster）
```

### 五、高可用设计（金融级）

```
GoldenDB 的高可用目标：
  RPO = 0（零数据丢失）
  RTO < 30s（故障恢复时间 < 30 秒）

实现手段：
  1. 强同步复制（类似 MySQL 的 semi-sync，但是默认强制）
     → 主节点写成功 + 至少 1 个备节点 ACK = 提交成功
     → RPO = 0（任何故障不丢数据）

  2. GTM 高可用（主备，RPO=0）
     → 主 GTM Crash → 备 GTM 接管（< 5s）

  3. 自动故障转移（类似 MHA，但是集成在 GTM）
     → 检测主节点故障 → 提升备节点 → 更新路由

  4. 异地多活（高级功能）
     → 同城 3 中心（生产中心 + 同城灾备 + 异地灾备）
```

---

## 它和相似方案的本质区别是什么？

### GoldenDB vs TiDB vs OceanBase

| 维度 | GoldenDB | TiDB | OceanBase |
|------|----------|-------|------------|
| 内核 | MySQL 改造 | TiKV（RocksDB） | 自研（OceanBase 2.0+ 用 Paxos） |
|  SQL 兼容 | MySQL（高度兼容） | MySQL（协议兼容，部分语法不支持） | MySQL/Oracle（双兼容） |
| 事务模型 | 2PC + GTM | Percolator（乐观事务） | 2PC + GTS |
| 分片 | 支持（Hash/Range/List） | 自动（PD 管理） | 自动（RootService 管理） |
| 金融优化 | 很多（灰度迁移、数据校验） | 较少 | 很多（蚂蚁金服场景打磨） |
| 社区版 | ❌ 不开源（商业产品） | ✅ 开源（Apache 2.0） | ✅ 开源（Mulan PubL 2.0） |
| 典型用户 | 银行（中信、民生） | 互联网公司 | 蚂蚁金服、网商银行 |

**本质区别**：

1. **GoldenDB 是 "MySQL 的分布式增强"，TiDB/OceanBase 是 "重新设计的分布式数据库"**
2. GoldenDB 的迁移成本最低（MySQL 协议 + 语法高度兼容）
3. TiDB 的生态最好（开源，社区活跃），OceanBase 的金融场景打磨最深

---

## 正确使用方式

### 正确用法

**1. 选好分片键（非常重要！）**

```sql
-- ✅ 好：用 user_id 做分片键（均匀分布，大部分查询命中单分片）
CREATE TABLE orders (
    order_id BIGINT PRIMARY KEY,
    user_id BIGINT NOT NULL,
    ...
) SHARDED BY HASH(user_id);

-- ❌ 差：用 order_id 做分片键（订单查询通常用 user_id，会全分片扫描）
CREATE TABLE orders (
    order_id BIGINT PRIMARY KEY,
    user_id BIGINT NOT NULL,
    ...
) SHARDED BY HASH(order_id);
```

**为什么正确**：分布式数据库最核心的设计是 "分片键选择"。选好了，大部分查询命中单分片（快）；选不好，全分片扫描（慢，网络开销大）。

**2. 全局表（广播表）存小表**

```sql
-- 字典表、配置表 → 做成全局表（每个节点都有完整副本）
CREATE TABLE dict_city (
    city_id INT PRIMARY KEY,
    city_name VARCHAR(50)
) GLOBAL;  -- 全局表（广播到所有节点）

-- 查询（不需要跨节点 JOIN，快）
SELECT * FROM orders o JOIN dict_city c ON o.city_id = c.city_id
WHERE o.user_id = 123;  -- 命中单分片 + 本地 JOIN（快）
```

**3. 避免分布式事务（尽量让事务命中单分片）**

```sql
-- ✅ 好：事务里所有操作都命中同一个 user_id（单分片 → 1PC，快）
BEGIN;
UPDATE orders SET status = 'paid' WHERE order_id = 100 AND user_id = 123;
UPDATE user_account SET balance = balance - 100 WHERE user_id = 123;
COMMIT;

-- ❌ 差：事务里操作了不同 user_id（跨分片 → 2PC，慢 + 可能失败）
BEGIN;
UPDATE orders SET status = 'paid' WHERE order_id = 100 AND user_id = 123;
UPDATE user_account SET balance = balance - 100 WHERE user_id = 456;  -- 不同分片！
COMMIT;  -- 分布式事务（2PC），性能差
```

### 错误用法及后果

**错误1：分片键选错，导致全分片扫描**

```sql
-- ❌ 错误：用 order_id 做分片键
CREATE TABLE orders (...) SHARDED BY HASH(order_id);

-- 查询（大部分查询用 user_id，全分片扫描！）
SELECT * FROM orders WHERE user_id = 123;  -- 全分片扫描（慢）
```

**后果**：
1. 查询要访问所有分片（网络开销大）
2. 响应时间 = 最慢的分片（木桶效应）
3. 分片优势完全丧失

**修复**：重新建表，用 `user_id` 做分片键（可能需要数据迁移）。

**错误2：在大表上做跨分片 JOIN**

```sql
-- ❌ 错误：orders 和 products 分片键不同 → 跨分片 JOIN（慢）
SELECT * FROM orders o
JOIN products p ON o.product_id = p.product_id
WHERE o.user_id = 123;
```

**后果**：需要把 `products` 的数据从所有分片拉到协调节点（网络 + 内存开销大）。

**修复**：
1. 把 `products` 做成全局表（广播表）
2. 或者让 `products` 和 `orders` 用相同的分片键（数据同节点，本地 JOIN）

**错误3：频繁用 `SELECT *`（放大网络传输）**

```sql
-- ❌ 错误：SELECT *（所有列都传输，网络开销大）
SELECT * FROM orders WHERE user_id = 123;

-- ✅ 正确：只查需要的列
SELECT order_id, status, created_at FROM orders WHERE user_id = 123;
```

---

## 边界情况和坑

### 坑1：分布式事务的 "悬挂事务"

```
问题：2PC 的 Phase 1 完成后，GTM Crash
      → 所有参与节点都不知道该 Commit 还是 Rollback
      → 事务"悬挂"（阻塞资源）

GoldenDB 的解决方案：
  1. 事务回收线程（后台线程，定期扫描悬挂事务）
  2. 根据 GTM 的 "事务状态日志" 决定 Commit 还是 Rollback
  3. 人工干预接口（DBA 可以手动清理悬挂事务）
```

### 坑2：热点数据（同一分片请求量太大）

```
问题：用 user_id 做分片键，但 user_id=1 是 VIP 用户
      → 该 VIP 的所有数据都在同一个分片
      → 该分片成为热点（CPU/IO 打满）

解决：
  1. 用 "复合分片键"（如：user_id + 订单类型）
  2. 或者做 "二级分片"（VIP 用户单独分片）
```

### 坑3：GTM 成为瓶颈（集中式事务管理）

```
问题：所有事务都要找 GTM 拿全局时间戳
      → GTM 成为瓶颈（吞吐量上限）

GoldenDB 的优化：
  1. GTM 批量分配时间戳（一次分配一批，减少 RTT）
  2. 本地事务优化（单分片事务，不经过 GTM）
  3. GTM 集群（高级功能，多个 GTM 分担负载）
```

---

## 面试话术

**Q1：GoldenDB 的架构是怎么样的？**

> GoldenDB 是 Shared-Nothing 架构，核心组件有 GTM（全局事务管理器，分配全局时间戳和事务 ID）和 Data Node（MySQL 改造的数据节点，存储分片数据）。GTM 是集中式的（类似 TiDB 的 PD，但是集中管理事务），Data Node 可以横向扩展。金融级高可用：RPO=0（强同步复制），RTO < 30s（自动故障转移）。

**Q2：GoldenDB 和 TiDB 的核心区别是什么？**

> 三个核心区别：1. 内核不同（GoldenDB 是 MySQL 改造，TiDB 是 RocksDB 引擎）；2. 事务模型不同（GoldenDB 用 2PC + GTM，TiDB 用 Percolator 乐观事务）；3. MySQL 兼容性（GoldenDB 更好，迁移成本更低）。GoldenDB 的优势是金融场景优化（灰度迁移、数据校验），TiDB 的优势是开源生态。

**Q3：分片键怎么选？选错了怎么办？**

> 分片键选择原则：1. 大部分查询的条件列（避免全分片扫描）；2. 均匀分布（避免热点）；3. 尽量让事务命中单分片（避免分布式事务）。选错了只能重新建表 + 数据迁移（GoldenDB 支持在线扩容，但迁移量取决于数据大小）。

**Q4：GoldenDB 怎么保证金融级高可用（RPO=0）？**

> 用强同步复制：主节点写成功 + 至少 1 个备节点 ACK = 提交成功。这样任何故障（主节点 Crash、磁盘损坏）都不会丢数据（RPO=0）。GTM 本身也是主备高可用（RPO=0）。故障检测 + 自动切换 < 30s（RTO < 30s）。

**Q5：什么场景不适合用 GoldenDB？**

> 1. 需要开源（GoldenDB 是商业产品，不开源）；2. 不需要 MySQL 协议兼容（TiDB 或 OceanBase 可能更合适）；3. 数据量不大（单机 MySQL 能搞定，不需要分布式）；4. 团队没有 DBA 支持（GoldenDB 的运维比单机 MySQL 复杂很多）。

---

## 本文总结

| 核心概念 | 要点 |
|----------|------|
| **架构** | GTM（全局事务管理）+ Data Node（MySQL 改造），Shared-Nothing |
| **分片** | Hash（默认）/Range/List/全局表（广播表） |
| **分布式事务** | 2PC 改造（GTM 管理，支持单分片优化成 1PC） |
| **MVCC** | GTM 分配全局快照（跨节点一致性读） |
| **扩容** | 在线扩容（数据迁移 + 增量同步 + 原子切换路由） |
| **高可用** | RPO=0（强同步复制），RTO < 30s（自动故障转移） |

**GoldenDB 的定位**：金融核心系统的 MySQL 分布式替代方案，优势是 MySQL 高度兼容 + 金融级高可用，劣势是不开源 + 生态不如 TiDB。

---
