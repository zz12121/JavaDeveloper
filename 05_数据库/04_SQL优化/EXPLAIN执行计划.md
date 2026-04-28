# EXPLAIN 执行计划

## 这个问题为什么存在？

> 写了一条 SQL，感觉写得没问题，但跑出来巨慢。  
> `EXPLAIN` 告诉你 MySQL **实际是怎么执行的**：用了哪个索引、扫描了多少行、是否需要文件排序。

没有 `EXPLAIN` 之前，只能靠经验猜测。  
有了 `EXPLAIN`，才能**用数据判断**优化方向。

---

## 核心字段详解

```sql
EXPLAIN SELECT * FROM orders WHERE user_id = 100 AND status = 'pending';

+----+-------------+--------+------+---------------------------+------+---------+-------+------+-------------+
| id | select_type| table  | type | key                       |rows  | filtered| Extra |     |             |
+----+-------------+--------+------+---------------------------+------+---------+-------+------+-------------+
|  1 | SIMPLE     | orders | ref  | idx_user_status           | 1523 |   100.0 | NULL  |     | Using where |
+----+-------------+--------+------+---------------------------+------+---------+-------+------+-------------+
```

---

### 1. type（访问类型）— 最重要 ⭐

按性能从好到差排序：

| type 值 | 含义 | 性能 |
|---------|------|------|
| `const` | 主键/唯一索引的等值查询，最多匹配 1 行 | ⭐⭐⭐ 最优 |
| `eq_ref` | JOIN 时，被驱动表用主键/唯一索引等值访问 | ⭐⭐⭐ |
| `ref` | 非唯一索引的等值查询 | ⭐⭐ |
| `range` | 索引范围扫描（BETWEEN、>、>=、<、<=、IN） | ⭐⭐ |
| `index` | 全索引扫描（只扫描索引，不扫描数据行） | ⭐ |
| `ALL` | **全表扫描**（扫描数据行） | ❌ 最差 |

**面试追问：什么情况下是 `ALL`？**

```sql
-- ❌ 全表扫描（user_id 没有索引）
EXPLAIN SELECT * FROM orders WHERE user_id = 100;  -- type=ALL

-- ✅ 索引查找（user_id 有索引）
EXPLAIN SELECT * FROM orders WHERE user_id = 100;  -- type=ref
```

**从 `ALL` 优化到 `ref` 的方向**：

```
ALL（全表扫）→ 加索引 → ref/eq_ref/const
```

---

### 2. key（实际使用的索引）

```sql
EXPLAIN SELECT * FROM orders WHERE user_id = 100;

-- key = idx_user_id   ← 实际用了 idx_user_id 索引
-- key = NULL          ← 没用到任何索引
```

**常见问题：建了索引但 `key=NULL`？**

```sql
-- 原因1：没有 WHERE 条件
SELECT * FROM orders;  -- 无 WHERE，不用索引（直接全表）

-- 原因2：WHERE 条件无法利用索引
SELECT * FROM orders WHERE user_id + 1 = 101;  -- 索引列参与运算

-- 原因3：MySQL 优化器认为全表扫描更快
SELECT * FROM orders WHERE user_id > 100;  -- 结果集太大
```

---

### 3. rows（预计扫描行数）

```sql
EXPLAIN SELECT * FROM orders WHERE status = 'pending';

-- rows = 1523  ← 预计扫描 1523 行
-- 如果表有 100 万行，rows=1523 说明索引很有效
-- 如果表有 1 万行，rows=10000 说明全表扫描
```

**⚠️ 重要**：`rows` 是**估算值**（基于统计信息，不是精确值），但可以用来判断数量级是否合理。

---

### 4. Extra（额外信息）— 高频考点

#### Using index（覆盖索引，不需要回表）⭐

```sql
-- user_id 有索引
EXPLAIN SELECT user_id FROM orders WHERE user_id = 100;

Extra: Using index  ✅  ← 索引覆盖了查询的所有列，不需要回表
```

**覆盖索引**：查询的所有列都在索引里，MySQL 直接从索引返回数据，**不需要访问数据行**。

```
普通查询：
  索引 → 回表查数据行 → 返回      （需要 2 次查找）

覆盖索引：
  索引 → 直接返回（无需回表）     （只需要 1 次查找）
```

#### Using index condition（索引下推 ICP）⭐

```sql
-- 联合索引 (user_id, status)
EXPLAIN SELECT * FROM orders WHERE user_id = 100 AND status LIKE 'pend%';

Extra: Using index condition  ✅
```

**ICP（Index Condition Pushdown）**：在索引遍历过程中，**把 WHERE 条件下推到存储引擎层**（在索引内部过滤 `status LIKE 'pend%'`），而不是等到 Server 层再过滤。

```
ICP 之前：索引找到 user_id=100 的所有行 → 回表 → Server 层过滤 status
ICP 之后：索引内部过滤 user_id=100 AND status LIKE 'pend%' → 回表（更少的行）
```

#### Using where（需要在 Server 层过滤）

```sql
EXPLAIN SELECT * FROM orders WHERE user_id = 100;

Extra: Using where  ⚠️  ← 需要在 Server 层根据 WHERE 过滤
```

> 这个字段单独出现时，不一定是问题（正常现象）。  
> 但如果和 `type=ALL` 一起出现 → 全表扫描 + 过滤 → 性能差。

#### Using filesort（文件排序）⚠️

```sql
EXPLAIN SELECT * FROM orders WHERE user_id = 100 ORDER BY create_time;

Extra: Using filesort  ⚠️  ← 需要在磁盘/内存中排序
```

**filesort 的原理**：

```
MySQL Server 层：
  1. 根据索引找到数据行（或全表扫描）
  2. 把需要排序的字段加载到内存（Sort Buffer）
  3. 快速排序（内存足够时）或外部排序（内存不够时，用磁盘文件）
  4. 返回排序结果

Sort Buffer 大小由 sort_buffer_size 控制（默认 256KB）
```

**优化方向**：

```sql
-- ❌ 用 filesort（extra using filesort）
SELECT * FROM orders WHERE user_id = 100 ORDER BY create_time;

-- ✅ 建覆盖索引，避免 filesort
ALTER TABLE orders ADD INDEX idx_uid_ctime(user_id, create_time);
-- 查询变为：Using index（覆盖索引），直接按索引顺序返回，无需排序

-- ✅ 或在应用层排序（如果数据量不大）
-- ✅ 或增大 sort_buffer_size（治标不治本）
```

#### Using temporary（使用临时表）⚠️

```sql
-- GROUP BY 或 DISTINCT 导致
EXPLAIN SELECT user_id, COUNT(*) FROM orders GROUP BY user_id;

Extra: Using temporary  ⚠️  ← 需要临时表
```

**常见原因**：

```sql
-- GROUP BY 的列没有索引
GROUP BY user_id;  -- user_id 无索引 → 用临时表分组

-- ✅ 优化：建索引
ALTER TABLE orders ADD INDEX idx_user_id(user_id);
```

---

### 5. select_type（查询类型）

| select_type | 含义 |
|-------------|------|
| `SIMPLE` | 简单 SELECT（无 UNION/子查询） |
| `PRIMARY` | 外层查询（最外层的 SELECT） |
| `SUBQUERY` | 子查询（FROM 之外的子查询） |
| `DERIVED` | 派生表（FROM 里的子查询，生成临时表） |
| `UNION` | UNION 的第二个及后续 SELECT |
| `UNION RESULT` | UNION 的结果集 |

```sql
EXPLAIN SELECT * FROM orders WHERE user_id = (
    SELECT id FROM users WHERE name = '张三'
);

-- id=1, select_type=PRIMARY  ← 外层查询
-- id=2, select_type=SUBQUERY  ← 子查询
```

---

### 6. key_len（索引使用的字节数）

```sql
-- 联合索引 (user_id INT, status VARCHAR(20))
EXPLAIN SELECT * FROM orders WHERE user_id = 100 AND status = 'pending';

key_len = 4 + 20*3 + 2 = 68  ← 用了多少索引字节
-- user_id: 4 字节（INT）
-- status:  VARCHAR(20) → 20*3(utf8mb4) + 2(变长) = 62 字节
-- 如果 key_len = 4，说明只用了 user_id 部分，没用 status
```

**用途**：判断联合索引使用了多少列。

---

## 实战：常见 SQL 的 EXPLAIN 分析

### 案例 1：慢查询 → 加索引优化

```sql
-- 原始查询（type=ALL，rows=100000，全表扫描）
EXPLAIN SELECT * FROM orders WHERE user_id = 100 AND status = 'pending';

-- type=ALL, rows=100000 ❌

-- 加索引
ALTER TABLE orders ADD INDEX idx_user_status(user_id, status);

-- 再次分析（type=ref, rows=15，走了索引）
EXPLAIN SELECT * FROM orders WHERE user_id = 100 AND status = 'pending';

-- type=ref, key=idx_user_status, rows=15 ✅
```

### 案例 2：ORDER BY 导致 filesort → 覆盖索引

```sql
-- 原查询（filesort）
EXPLAIN SELECT order_id, status FROM orders WHERE user_id = 100 ORDER BY create_time;
-- Extra: Using where; Using filesort ❌

-- 建覆盖索引
ALTER TABLE orders ADD INDEX idx_uid_ctime(user_id, create_time, order_id, status);

-- 再次分析（Using index）
EXPLAIN SELECT order_id, status FROM orders WHERE user_id = 100 ORDER BY create_time;
-- type=ref, key=idx_uid_ctime, Extra: Using index ✅
```

### 案例 3：子查询 → 改写为 JOIN

```sql
-- ❌ 子查询（可能先执行子查询，再 JOIN）
EXPLAIN SELECT * FROM orders WHERE user_id IN (
    SELECT id FROM users WHERE city = '北京'
);

-- type=SUBQUERY（子查询先执行）❌

-- ✅ 改写为 JOIN（MySQL 会优化）
EXPLAIN SELECT o.* FROM orders o
INNER JOIN users u ON o.user_id = u.id
WHERE u.city = '北京';

-- type=ref（JOIN，被驱动表用索引）✅
```

---

## 边界情况和坑

### 1. EXPLAIN 的 rows 是估算值，不精确

```sql
-- 表数据变化后，统计信息未更新
ANALYZE TABLE orders;  -- 强制更新统计信息

-- 为什么不精确？
-- MySQL 用「采样估算」统计行数（不是逐行统计）
-- 数据分布不均匀时，估算偏差很大
```

### 2. EXPLAIN 不看触发器/存储过程

```sql
-- EXPLAIN 只能分析 SELECT/UPDATE/DELETE 的单条语句
-- 不能分析触发器、存储过程里的逻辑
```

### 3. `EXPLAIN ANALYZE`（MySQL 8.0+）更详细

```sql
EXPLAIN ANALYZE SELECT * FROM orders WHERE user_id = 100;
-- 会显示实际耗时、实际扫描行数（比 EXPLAIN 更准）
```

---

## 我的理解

`EXPLAIN` 的核心是**找到「性能瓶颈在哪里」**：

1. **`type`**：判断是索引查还是全表扫（`ALL` 是最危险的信号）
2. **`key`**：确认实际用了哪个索引（和建的是否一致）
3. **`rows`**：判断扫描了多少行（和表规模对比）
4. **`Extra`**：找到具体问题（filesort、temporary、using where）

**优化的标准路径**：
```
EXPLAIN 分析 → 发现 type=ALL → 加索引 → 再 EXPLAIN → type=ref → 继续排查 Extra
```

**面试追问高发区**：
1. type 的 6 种值（const/eq_ref/ref/range/index/ALL）按性能排序
2. Using filesort 的原理和优化（覆盖索引）
3. Using temporary 的原因（GROUP BY 无索引）
4. Using index condition（ICP）的原理
5. key_len 的含义（判断联合索引用了几列）

---
