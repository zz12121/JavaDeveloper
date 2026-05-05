# SQL 优化与执行计划

## 这个问题为什么存在？

如果你已经学过 MySQL 的 EXPLAIN，会发现 PostgreSQL 的 **EXPLAIN 输出格式** 和 **执行计划选择逻辑** 有很大不同。

```
MySQL EXPLAIN：
  - 输出格式：表格（type/key/rows/Extra）
  - 执行计划选择：基于成本的优化器（Cost-Based Optimizer）
  - 慢查询日志：slow_query_log（需要手动开启）

PostgreSQL EXPLAIN：
  - 输出格式：树形结构（更直观）
  - 执行计划选择：基于成本的优化器（更精细化）
  - 慢查询分析：需要安装 pg_stat_statements 扩展
```

**核心问题**：
1. 怎么读取 PostgreSQL 的 EXPLAIN 输出？
2. 怎么定位慢查询？
3. PostgreSQL 有哪些 MySQL 没有的优化手段（如 CTE 物化、窗口函数优化）？
4. 执行计划选择错误怎么办（统计信息过期）？

理解这些，才能真正调优 PostgreSQL 查询——特别是 **复杂查询（多表 JOIN + 窗口函数）**。

---

## 它是怎么解决问题的？

### 一、EXPLAIN 基础

```sql
-- 基本用法（只显示执行计划，不真正执行）
EXPLAIN SELECT * FROM users WHERE id = 123;

-- 带实际执行时间（非常重要！真正执行，能看到实际行数/时间）
EXPLAIN ANALYZE SELECT * FROM users WHERE id = 123;

-- 只显示执行计划，不真正执行（适合 UPDATE/DELETE，避免误操作）
EXPLAIN SELECT * FROM users WHERE id = 123;
```

#### EXPLAIN 输出解读

```sql
-- 示例查询
EXPLAIN SELECT * FROM orders WHERE user_id = 123 ORDER BY created_at DESC LIMIT 10;
```

```
QUERY PLAN
----------------------------------------------------------------------------------------------------------------------------------
 Limit  (cost=0.29..2.45 rows=10 width=48)
   ->  Index Scan using idx_orders_user_id_created_at on orders
         (cost=0.29..245.67 rows=1200 width=48)
       Index Cond: (user_id = 123)
       Order by: created_at DESC
(4 rows)
```

**关键字段**：
- `cost=X..Y`：启动成本 X，总成本 Y（单位是"磁盘页读取次数"的抽象）
- `rows=N`：预计返回 N 行
- `width=N`：平均每行 N 字节
- `Index Scan`：用索引扫描（不需要回堆，如果索引覆盖所有列）
- `Seq Scan`：全表扫描（通常意味着没用索引）

#### EXPLAIN ANALYZE（实际执行）

```sql
EXPLAIN ANALYZE SELECT * FROM orders WHERE user_id = 123;
```

```
QUERY PLAN
----------------------------------------------------------------------------------------------------------------------------------
 Index Scan using idx_orders_user_id on orders
       (cost=0.29..245.67 rows=1200 width=48)
       (actual time=0.042..2.345 rows=1150 loops=1)
   Index Cond: (user_id = 123)
 Planning Time: 0.120 ms
 Execution Time: 2.500 ms
(4 rows)
```

**关键对比**：
- `rows=1200` vs `rows=1150` → 预计 1200 行，实际 1150 行（精度还可以）
- 如果差异很大（如预计 100 行，实际 10000 行）→ **统计信息过期**，需要 `ANALYZE`

### 二、常见执行计划节点类型

| 节点类型 | 说明 | 什么时候出现 |
|----------|------|--------------|
| `Seq Scan` | 全表扫描 | 没用索引，或表很小（< 1000 行） |
| `Index Scan` | 索引扫描（可能回堆） | 用了索引，但需要取不在索引里的列 |
| `Index Only Scan` | 索引覆盖扫描（不回堆） | 索引包含所有查询列，且 VM 干净 |
| `Bitmap Heap Scan` | 位图扫描（先扫索引，再批量回堆） | 条件返回多行（如 `user_id IN (1,2,3)`） |
| `Nested Loop` | 嵌套循环 Join | 小表驱动大表，内表有索引 |
| `Hash Join` | 哈希 Join | 大表 Join 大表，内存足够 |
| `Merge Join` | 合并 Join | 两表都已按 Join 键排序 |
| `Sort` | 排序（内存或磁盘） | ORDER BY，且无法用索引排序 |
| `HashAggregate` | 哈希聚合 | GROUP BY，内存足够 |
| `GroupAggregate` | 分组聚合 | GROUP BY，且已按分组键排序 |

#### Index Scan vs Index Only Scan

```
Index Scan：
  1. 从索引拿到 ctid 列表
  2. 逐个回堆取数据（需要检查 MVCC 可见性）
  → 慢（Heap 访问是随机 IO）

Index Only Scan：
  1. 从索引拿到 ctid 列表
  2. 不回堆，直接从索引返回数据
  3. 但需要检查 Visibility Map（VM）："这个页面所有元组都对所有人可见吗？"
     → 如果 VM 说"是"，直接返回（快）
     → 如果 VM 说"否"，回堆检查可见性（慢，退化成 Index Scan）
```

**让 Index Only Scan 真正快的关键**：定期 VACUUM，保持 VM 干净。

### 三、pg_stat_statements（慢查询分析）

PostgreSQL 的慢查询分析需要安装 `pg_stat_statements` 扩展（类似 MySQL 的 `performance_schema`）。

```sql
-- 安装扩展（只需一次，所有数据库都能用）
CREATE EXTENSION pg_stat_statements;

-- 查看最慢的查询（按总执行时间排序）
SELECT query, calls, total_time, mean_time, rows
FROM pg_stat_statements
ORDER BY total_time DESC
LIMIT 10;

-- 查看最慢的查询（按平均执行时间排序）
SELECT query, calls, total_time, mean_time, rows
FROM pg_stat_statements
ORDER BY mean_time DESC
LIMIT 10;

-- 重置统计（重新开始计数）
SELECT pg_stat_statements_reset();
```

#### pg_stat_statements 配置

```postgresql.conf
# 开启 pg_stat_statements
shared_preload_libraries = 'pg_stat_statements'
pg_stat_statements.track = all          # 跟踪所有查询（包括嵌套查询）
pg_stat_statements.max = 10000         # 最多跟踪 10000 条不同查询
```

### 四、执行计划选择错误（统计信息过期）

```
现象：某个查询突然变慢（从 100ms → 10s）
原因：pg_statistics 过期，优化器选了错误的执行计划
      如：选了 Nested Loop（实际返回 100 万行，应该用 Hash Join）

解决：
  1. 手动更新统计信息
     ANALYZE my_table;
  2. 如果表非常大，只更新特定列
     ANALYZE my_table (user_id, created_at);
  3. 修改统计信息采样比例（让统计信息更准确）
     ALTER TABLE my_table ALTER COLUMN user_id SET STATISTICS 1000;
     (默认 100，范围 0~10000，越高越准确但 ANALYZE 越慢)
```

#### 强制使用某个执行计划（不推荐，应该让优化器自己选）

```sql
-- 强制用 Index Scan（通过 "禁用" Seq Scan）
BEGIN;
SET LOCAL enable_seqscan = off;   -- 只允许 Index Scan
SELECT * FROM users WHERE id = 123;
COMMIT;  -- 恢复默认设置

-- 或者，修改表的统计信息（欺骗优化器）
ALTER TABLE users SET (n_distinct = 1000000);  -- 告诉优化器 user_id 有 100 万个不同值
```

**为什么 "不推荐" 强制指定执行计划？**
→ 数据分布变化时，强制计划可能变得更差。应该让优化器基于最新统计信息选择。

### 五、PostgreSQL 独有优化手段

#### 1. CTE 物化（WITH 子句）

```sql
-- CTE（公用表表达式）
WITH active_users AS (
    SELECT * FROM users WHERE status = 'active'
)
SELECT * FROM active_users WHERE created_at > '2024-01-01';
```

```
PostgreSQL 11 及之前：
  CTE 会被"物化"（Materialize），相当于临时表
  → 好处：CTE 只执行一次，多次引用不重复计算
  → 坏处：优化器无法把 CTE "内联"到主查询，可能无法用索引

PostgreSQL 12+：
  CTE 默认"内联"（不物化），和优化器融合成一条执行计划
  → 更好（可以用索引，可以选择更好 Join 顺序）
  → 但如果 CTE 被多次引用，还是会自动物化
```

**强制物化（PG 12+）**：

```sql
WITH active_users AS MATERIALIZED (   -- 强制物化
    SELECT * FROM users WHERE status = 'active'
)
SELECT * FROM active_users u1
JOIN active_users u2 ON u1.id <> u2.id;  -- 多次引用，只计算一次
```

#### 2. 窗口函数优化

PostgreSQL 的窗口函数（Window Function）非常强大，但容易写出慢查询。

```sql
-- 查询：每个用户的最近 10 个订单
SELECT *
FROM (
    SELECT *,
           ROW_NUMBER() OVER (PARTITION BY user_id ORDER BY created_at DESC) AS rn
    FROM orders
) t
WHERE rn <= 10;
```

**优化**：确保 `PARTITION BY` 和 `ORDER BY` 有索引。

```sql
CREATE INDEX idx_orders_user_id_created_at
ON orders (user_id, created_at DESC);
```

#### 3. 分页优化（类似 MySQL 的 "延迟关联"）

```sql
-- ❌ 慢：OFFSET 越大越慢（需要扫描 + 跳过 N 行）
SELECT * FROM orders ORDER BY created_at DESC LIMIT 10 OFFSET 100000;

-- ✅ 快：用游标分页（Keyset Pagination）
SELECT * FROM orders
WHERE created_at < '2024-03-01 10:00:00'   -- 上一页的最后一行的时间
ORDER BY created_at DESC
LIMIT 10;
```

---

## 它和相似方案的本质区别是什么？

### PostgreSQL 优化 vs MySQL 优化

| 维度 | PostgreSQL | MySQL（InnoDB） |
|------|------------|----------------|
| EXPLAIN 输出 | 树形结构（直观） | 表格（type/key/rows/Extra） |
| 执行计划选择 | 更精细化（支持更多 Join 算法） | 较简单（Nested Loop / Hash Join / Batch Key Access） |
| 慢查询分析 | pg_stat_statements（需要安装扩展） | slow_query_log（内置） |
| 分页优化 | 游标分页（Keyset Pagination） | 延迟关联（覆盖索引 + 回表） |
| 窗口函数 | 强大（所有标准窗口函数） | 支持（MySQL 8.0+） |
| CTE | PG 12+ 默认内联（更快） | 不支持 CTE 内联（总是物化） |

**本质区别**：

1. **PostgreSQL 优化器更强大**（支持更多 Join 算法、窗口函数优化），但 **统计信息更重要**（统计信息过期会导致严重性能问题）
2. **MySQL 优化器更简单**，但 **覆盖索引** 很容易用（不需要 VM 维护）

---

## 正确使用方式

### 正确用法

**1. 用 EXPLAIN ANALYZE 分析慢查询（不光是 EXPLAIN）**

```sql
-- ✅ 正确：用 ANALYZE 看实际执行时间
EXPLAIN ANALYZE SELECT * FROM orders WHERE user_id = 123;

-- ❌ 错误：只用 EXPLAIN（可能统计信息过期，执行计划选择错误）
EXPLAIN SELECT * FROM orders WHERE user_id = 123;
```

**为什么正确**：EXPLAIN 只看预计，EXPLAIN ANALYZE 看实际执行时间，能发现统计信息过期的问题。

**2. 开启 pg_stat_statements，定期分析慢查询**

```sql
-- 安装扩展
CREATE EXTENSION pg_stat_statements;

-- 每周分析一次最慢的查询
SELECT query, calls, total_time, mean_time
FROM pg_stat_statements
ORDER BY total_time DESC
LIMIT 20;
```

**为什么正确**：PostgreSQL 没有内置慢查询日志（需要手动配置 `log_min_duration_statement`），pg_stat_statements 是最方便的分析工具。

**3. 大表定期 ANALYZE（保持统计信息新鲜）**

```sql
-- 对大表，降低 autovacuum_analyze_scale_factor
ALTER TABLE big_table SET (
    autovacuum_analyze_scale_factor = 0.02  -- 2% 变更就触发 ANALYZE
);
```

**为什么正确**：统计信息过期会导致执行计划选择错误，定期 ANALYZE 能避免这个问题。

**4. 分页用游标分页（Keyset Pagination），不用 OFFSET**

```sql
-- ✅ 正确：游标分页（假设按 created_at 排序）
SELECT * FROM orders
WHERE created_at < '2024-03-01 10:00:00'
ORDER BY created_at DESC
LIMIT 10;

-- ❌ 错误：OFFSET 分页（越翻越慢）
SELECT * FROM orders
ORDER BY created_at DESC
LIMIT 10 OFFSET 100000;
```

### 错误用法及后果

**错误1：从不 ANALYZE，导致执行计划选择错误**

```
现象：查询突然变慢（从 100ms → 10s）
原因：统计信息过期，优化器认为回表成本很低（实际很高）
后果：选了 Nested Loop（实际应该选 Hash Join），性能暴跌
```

**修复**：
```sql
ANALYZE my_table;
```

**错误2：CTE 被多次执行（PG 11 及之前）**

```sql
-- ❌ 慢（PG 11 及之前）：CTE 被物化，但多次引用会多次扫描物化表
WITH active_users AS (
    SELECT * FROM users WHERE status = 'active'
)
SELECT * FROM active_users u1
JOIN active_users u2 ON u1.id <> u2.id;
```

**修复**（PG 12+）：CTE 默认内联，多次引用会自动物化，没问题。
**修复**（PG 11 及之前）：把 CTE 改成子查询，或者强制把结果存到临时表。

**错误3：窗口函数没索引，导致全表排序**

```sql
-- ❌ 慢：没索引，需要全表排序
SELECT *,
       ROW_NUMBER() OVER (PARTITION BY user_id ORDER BY created_at)
FROM orders;
```

**修复**：建索引 `(user_id, created_at)`。

---

## 边界情况和坑

### 坑1：统计信息采样比例太低，导致估算不准确

```
PostgreSQL 的 ANALYZE 是"采样"统计（不是全表扫描）
默认采样比例：100（从表中随机取 100 个页面）

如果表非常大（亿级），采样 100 个页面可能不够
→ 统计信息不准确 → 执行计划选择错误
```

**解决**：
```sql
-- 提高采样比例（0~10000，越高越准确但 ANALYZE 越慢）
ALTER TABLE big_table ALTER COLUMN user_id SET STATISTICS 1000;
ANALYZE big_table;
```

### 坑2：pg_stat_statements 吃内存，且重启后数据丢失

```
pg_stat_statements 存在共享内存里
`pg_stat_statements.max = 10000` → 约占用 40MB 内存

重启 PostgreSQL → pg_stat_statements 数据清空
→ 需要重新积累统计信息（至少 1 天）
```

**解决**：
1. 定期导出 pg_stat_statements 数据到表（历史分析）
2. 用 `pg_gather` 或 `pgBadger` 做更长期的慢查询分析

### 坑3：复杂查询的 Join 顺序选择错误

```
PostgreSQL 的优化器在 Join 很多表时（如 10+ 表），
可能因为"组合爆炸"，选择了一个不是最优的 Join 顺序

解决：
  1. 用 `EXPLAIN (ANALYZE, BUFFERS)` 查看每个 Join 的实际成本
  2. 手动指定 Join 顺序（用子查询 + 嵌套 Loop）
  3. 或者升级到 PG 16+（优化器更强大）
```

---
