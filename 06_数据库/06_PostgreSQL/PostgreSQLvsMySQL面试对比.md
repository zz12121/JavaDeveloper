# PostgreSQL vs MySQL 面试对比

## 这个问题为什么存在？

你已经学完了 MySQL 和 PostgreSQL 的核心知识，但面试时经常会被问：

> **"你们为什么用 PostgreSQL？和 MySQL 比有什么优势？"**
> **"什么场景用 MySQL，什么场景用 PostgreSQL？"**
> **"PostgreSQL 的 JSONB 和 MySQL 的 JSON 有什么本质区别？"**

这篇文章把两个数据库的核心差异总结出来，形成一套**面试可直接用的话术**。

---

## 它是怎么解决问题的？

### 一、进程模型 vs 线程模型

```
MySQL（线程模型）：
  一个线程处理一个连接
  优势：轻量，支持高并发（上万连接）
  劣势：一个线程崩溃可能导致整个进程崩溃

PostgreSQL（进程模型）：
  一个进程处理一个连接
  优势：稳定（一个连接崩溃不影响其他连接）
  劣势：并发有限（通常 < 1000 连接），需要用连接池（PgBouncer）
```

**面试话术**：

> PostgreSQL 用进程模型，稳定性更好（一个连接崩溃不影响其他连接），但并发能力有限，生产必须用连接池（如 PgBouncer）。MySQL 用线程模型，轻量，支持上万连接，适合高并发 Web 场景。如果连接数很高（如微服务架构），MySQL 更合适；如果稳定性优先（如金融系统），PostgreSQL 更合适。

---

### 二、存储引擎与 MVCC 实现

| 维度 | PostgreSQL | MySQL（InnoDB） |
|------|------------|----------------|
| 存储模型 | 堆表（索引指向 ctid） | 索引组织表（主键索引=数据） |
| MVCC 实现 | 旧版本在堆表（死元组） | 旧版本在 Undo Log（版本链） |
| 旧版本清理 | VACUUM（需要主动清理） | Purge 线程（自动清理） |
| 更新开销 | 高（DELETE + INSERT） | 低（原地更新 + Undo Log） |
| 表膨胀风险 | 高（VACUUM 不及时） | 低（Purge 自动清理） |

**面试话术**：

> PostgreSQL 的 MVCC 是把旧版本存在堆表里（xmin/xmax 标记），不自动清理，需要 VACUUM 主动清理。MySQL 的 MVCC 是把旧版本存在 Undo Log 里，后台 Purge 线程自动清理。PostgreSQL 的优势是 UPDATE 不会产生 Undo Log（对长事务更友好），劣势是需要 DBA 维护 VACUUM，否则会表膨胀。

---

### 三、索引类型与支持

| 索引类型 | PostgreSQL | MySQL（InnoDB） |
|----------|------------|----------------|
| B-tree | ✅ 默认 | ✅ 默认 |
| Hash | ✅ 支持（PG 10+ 支持 WAL） | ✅ Memory 引擎支持，InnoDB 有自适应 Hash |
| GIN（倒排索引） | ✅ 支持（JSONB、数组、全文搜索） | ❌ 不支持（只能用表达式索引） |
| GiST | ✅ 支持（几何、范围类型） | ❌ 不支持 |
| BRIN | ✅ 支持（时序数据，索引很小） | ❌ 不支持 |
| 部分索引 | ✅ 支持 | ❌ 不支持 |
| 表达式索引 | ✅ 支持 | ✅ MySQL 8.0+ 支持 |

**面试话术**：

> PostgreSQL 的索引类型远比 MySQL 丰富。最经典的是 GIN 索引，可以支持 JSONB 的任意 key 查询，而 MySQL 的 JSON 只能用表达式索引，只能查建了索引的路径。另外 PostgreSQL 支持部分索引（只对部分行建索引），对大表的查询性能提升很大。

---

### 四、JSON 支持

```sql
-- PostgreSQL JSONB（二进制存储，支持 GIN 索引）
CREATE TABLE products (attrs JSONB);
CREATE INDEX idx_attrs ON products USING gin (attrs);
SELECT * FROM products WHERE attrs @> '{"color":"red"}';  -- ✅ 用索引

-- MySQL JSON（需要表达式索引）
CREATE TABLE products (attrs JSON);
ALTER TABLE products ADD COLUMN color VARCHAR(20)
    GENERATED ALWAYS AS (attrs->>'$.color') STORED;
CREATE INDEX idx_color ON products (color);
SELECT * FROM products WHERE color = 'red';  -- ✅ 用索引
SELECT * FROM products WHERE attrs->>'$.size' = 'L';  -- ❌ 不用索引（除非建了 size 的表达式索引）
```

**面试话术**：

> PostgreSQL 的 JSONB 是二进制存储，支持 GIN 索引，可以查询任意 key，非常灵活。MySQL 的 JSON 需要建"生成列 + 索引"，只能查建了索引的路径，不够灵活。如果业务需要存复杂的半结构化数据（如电商商品属性），PostgreSQL 更适合。

---

### 五、事务与隔离级别

| 隔离级别 | PostgreSQL | MySQL（InnoDB） |
|----------|------------|----------------|
| Read Uncommitted | 实际 = Read Committed（PG 不支持脏读） | ✅ 支持（但没人用） |
| Read Committed（默认） | ✅ 每条语句获取新快照 | ✅ 每条语句获取新快照 |
| Repeatable Read | ✅ 整个事务用同一个快照，**防幻读** | ✅ 第一次读建立 ReadView，但当前读不防幻读 |
| Serializable | ✅ 用谓词锁（不是快照） | ✅ 用间隙锁（Next-Key Lock） |

**面试话术**：

> PostgreSQL 的 Repeatable Read 是真正防幻读的（整个事务用同一个快照，其他事务插入的新行不可见）。MySQL 的 RR 对"快照读"防幻读，但对"当前读"（SELECT ... FOR UPDATE）不防幻读，需要间隙锁。PostgreSQL 的 RR 更容易遇到序列化失败（40001 错误），需要应用层重试。

---

### 六、复制与高可用

| 维度 | PostgreSQL | MySQL |
|------|------------|-------|
| 复制方式 | 物理复制（WAL 流复制） | 逻辑复制（binlog）或 MGR |
| 复制延迟 | 低（物理复制，并行回放） | 可能高（单线程回放，MySQL 5.7+ 支持并行复制） |
| 高可用方案 | Patroni + etcd（自动故障转移） | MHA、Orchestrator、InnoDB Cluster |
| 读写分离 | 需要中间件（Pgpool-II） | 需要中间件（MyCat、ProxySQL） |

**面试话术**：

> PostgreSQL 的流复制是物理复制（WAL 直接回放），延迟很低，且支持并行回放。MySQL 的 binlog 复制是逻辑复制（SQL 回放），延迟可能较高，但 MySQL 5.7+ 支持并行复制，差距在缩小。高可用方案：PostgreSQL 常用 Patroni + etcd（自动故障转移），MySQL 常用 InnoDB Cluster（基于 Group Replication）。

---

### 七、性能与适用场景

```
MySQL 更适合：
  - 高并发简单读写（Web 应用、电商）
  - 团队熟悉 MySQL（文档多，DBA 多）
  - 需要成熟的读写分离/分库分表方案

PostgreSQL 更适合：
  - 复杂查询（多表 JOIN、窗口函数、CTE）
  - 数据分析（OLAP，支持并行查询）
  - 需要 GIS/JSONB/全文搜索
  - 需要更强的事务隔离（RR 防幻读）
```

**面试话术**：

> 选型要看场景。如果是典型的 Web 应用（高并发简单读写），MySQL 更合适（线程模型，支持高并发，生态成熟）。如果是复杂查询（多表 JOIN、窗口函数、数据分析），或者需要 GIS/JSONB/全文搜索，PostgreSQL 更合适（查询优化器更强大，索引类型更丰富）。现在很多互联网公司（如 Instagram、Uber）都是 MySQL + PostgreSQL 混用，各取所长。

---

## 正确使用方式

### 正确用法

**1. JSONB 查询用 GIN 索引（PostgreSQL）**

```sql
CREATE INDEX idx_data_gin ON my_table USING gin (data);
-- 可以对 data 的任意 key 做条件查询
SELECT * FROM my_table WHERE data @> '{"status":"active"}';
```

**2. 分页用游标分页（Keyset Pagination），不用 OFFSET**

```sql
-- PostgreSQL / MySQL 都适用
SELECT * FROM orders
WHERE created_at < '2024-03-01 10:00:00'
ORDER BY created_at DESC
LIMIT 10;
```

**3. PostgreSQL 必须用连接池（PgBouncer）**

```ini
# pgbouncer.ini
[databases]
mydb = host=127.0.0.1 port=5432

[pgbouncer]
pool_mode = transaction
max_client_conn = 1000
default_pool_size = 25
```

### 错误用法及后果

**错误1：PostgreSQL 的 max_connections 设太大（如 1000）**

**后果**：内存爆炸（每个连接进程占用 ~10MB），上下文切换开销巨大。

**修复**：设 `max_connections = 100`，用 PgBouncer 连接池。

**错误2：MySQL 的 RR 隔离级别下，认为完全防幻读**

```sql
-- MySQL RR 隔离级别
BEGIN;
SELECT * FROM orders WHERE status = 'pending' FOR UPDATE;
-- 其他事务可以插入 status='pending' 的订单（幻读！）
-- 需要间隙锁才能真正防幻读
```

**修复**：用 `Serializable` 隔离级别，或者确保查询用了间隙锁。

---
---

## 深入原理

### PostgreSQL 为什么选进程模型？历史原因

PostgreSQL 诞生于 1986 年（UC Berkeley），当时操作系统的线程支持还不成熟（POSIX 线程 1995 年才标准化）。PostgreSQL 继承了 Ingres 的进程架构，每个连接 fork 一个进程。

**优势**：进程间内存隔离，一个连接崩溃（如段错误）不影响其他连接。
**劣势**：进程比线程重，每个连接约 3-10MB 内存。

MySQL 诞生于 1995 年，当时线程模型已成熟，选择了更轻量的线程模型。

### MVCC 两种实现路径的本质区别

| 维度 | PostgreSQL（堆表 + 死元组） | MySQL InnoDB（聚簇索引 + Undo Log） |
|------|----------------------------|--------------------------------|
| 旧版本存在哪里？ | 堆表里（xmin/xmax 标记） | Undo Log 里（版本链） |
| 新版本存在哪里？ | 堆表（UPDATE = DELETE + INSERT） | 聚簇索引（原地更新，旧版本进 Undo） |
| 如何清理旧版本？ | VACUUM 主动清理 | Purge 线程自动清理 |
| 对长事务的影响 | 长事务导致 VACUUM 无法清理（死元组堆积） | 长事务导致 Undo Log 膨胀（但 Purge 能处理） |

### 隔离级别实现差异：快照 vs 锁

```sql
-- PostgreSQL：快照隔离（SI）
-- 整个事务用一个快照（xmin/xmax 比较）
BEGIN ISOLATION LEVEL REPEATABLE READ;
SELECT * FROM orders;  -- 建立快照
-- 其他事务插入的订单，对当前事务不可见 → 防幻读

-- MySQL InnoDB：快照读 + 当前读
BEGIN;
SELECT * FROM orders;              -- 快照读（ReadView）
SELECT * FROM orders FOR UPDATE;  -- 当前读（读最新 + 加锁，不防幻读）
```

---

## 边界情况和坑

### 坑 1：PostgreSQL 的 max_connections 设置陷阱

```ini
# postgresql.conf
max_connections = 1000   # ❌ 严重错误！
```
**后果**：每个连接进程占用约 10MB 内存，1000 个连接 = 10GB 内存，加上每个连接的 CPU 上下文切换，性能急剧下降。

**正确做法**：设 ，用 PgBouncer 连接池（pool_size = CPU核数 × 2）。

---

### 坑 2：MySQL 的 RR 隔离级别不完全防幻读

```sql
-- MySQL，RR 隔离级别
BEGIN;
SELECT * FROM orders WHERE status = 'pending';  -- 快照读，12 条记录
-- 另一个事务：INSERT INTO orders VALUES (... status='pending' ...); COMMIT;
SELECT * FROM orders WHERE status = 'pending';  -- 还是 12 条（快照读，防幻读）
SELECT * FROM orders WHERE status = 'pending' FOR UPDATE;  -- 13 条！（当前读，幻读！）
```
**面试考点**：MySQL 的 RR 只对「快照读」防幻读，「当前读」需要间隙锁才能真正防幻读。

---

### 坑 3：PostgreSQL 的 VACUUM 不及时导致表膨胀

```sql
-- 查看表膨胀情况
SELECT schemaname, tablename,
       pg_size_pretty(pg_total_relation_size(schemaname||'.'||tablename)) AS size,
       n_dead_tup AS dead_tuples
FROM pg_stat_user_tables
ORDER BY n_dead_tup DESC;
```
**后果**：死元组不清理 → 表文件越来越大 → 查询变慢（扫描更多数据页）。
**修复**：调优 AutoVacuum（），或手动 。

---

### 坑 4：混用 MySQL 和 PostgreSQL 时的数据类型差异

| MySQL 类型 | PostgreSQL 近似类型 | 注意 |
|-----------|-------------------|------|
|  |  | ✅ 直接映射 |
|  |  | ✅ 一致 |
|  |  | ⚠️ MySQL DATETIME 不带时区，PG TIMESTAMP 带时区 |
|  |  | ✅ 一致 |
|  |  | ⚠️ PG 的 JSONB 支持 GIN 索引，MySQL 的 JSON 不支持 |
|  |  | ⚠️ MySQL 用 TINYINT(1) 存布尔，迁移到 PG 要改类型 |

