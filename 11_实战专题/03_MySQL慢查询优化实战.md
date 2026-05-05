# MySQL 慢查询优化实战

> 慢查询不是"加个索引"就完了。真正的功力在于：**能从 explain 的输出看出优化器是怎么想的，以及它为什么「想错了」。**

---

## 排查框架

```
发现慢查询 → explain 分析 → 判断瓶颈类型 → 施加对应优化 → 验证效果
```

瓶颈类型速查：

```
                  慢查询
                 /      \
            全表扫描      索引扫描但慢
           /      \        /       \
        无可用索引  有索引但没用  索引命中但返回行多  锁等待
           |          |          |              |
        加索引      查索引失效原因  改查询/覆盖索引  看锁信息
```

---

## 场景 A：索引失效的常见陷阱

### 现象

```
有一条 SQL 加了索引但还是全表扫描：type = ALL，rows = 200 万
```

### 问题 SQL

```sql
-- 订单表有 idx_create_time 索引
SELECT * FROM orders 
WHERE DATE(create_time) = '2026-04-28';  -- ❌ 对索引列用了函数

-- 用户表有 idx_name_age 索引
SELECT * FROM user 
WHERE age = 25 AND name LIKE '%张%';  -- ❌ 左模糊

-- 商品表有 idx_category_status 索引
SELECT * FROM product 
WHERE category = '手机' OR status = 0;  -- ❌ OR 前后字段不同
```

### 根因：索引失效的 6 种经典情况

| 情况 | 示例 | 原因 |
|------|------|------|
| 对列使用函数 | `WHERE DATE(create_time) = '...'` | 函数作用于列，索引无法使用 |
| 隐式类型转换 | `WHERE phone = 13800138000`（phone 是 varchar） | MySQL 隐式转了类型 |
| 左模糊 | `WHERE name LIKE '%张'` | B+树无法从左边开始匹配 |
| 不符合最左前缀 | 联合索引(a,b,c)，查询条件只有 (c) | B+树按 a→b→c 排序 |
| OR 连接不同字段 | `WHERE a = 1 OR b = 2`（a 和 b 不在同一个索引） | 优化器无法同时走两个索引 |
| 使用 != 或 NOT IN | `WHERE status != 0` | 范围太大，优化器放弃索引 |

### 解决方案

```sql
-- 1. 避免对列使用函数：改写等价条件
-- ❌ WHERE DATE(create_time) = '2026-04-28'
-- ✅ WHERE create_time >= '2026-04-28 00:00:00' AND create_time < '2026-04-29 00:00:00'

-- 2. 注意类型匹配
-- ❌ WHERE phone = 13800138000   -- phone 是 varchar
-- ✅ WHERE phone = '13800138000'

-- 3. 避免 NOT IN，改用 LEFT JOIN + IS NULL 或 EXISTS
-- ❌ WHERE id NOT IN (SELECT user_id FROM orders)
-- ✅ WHERE NOT EXISTS (SELECT 1 FROM orders WHERE orders.user_id = user.id)

-- 4. OR 改为 UNION（各自走各自索引）
SELECT * FROM product WHERE category = '手机'
UNION
SELECT * FROM product WHERE status = 0;
```

---

## 场景 B：索引用上了但还是慢（回表太多）

### 现象

```
explain 显示 type = ref，key = idx_user_id，rows = 50000
索引命中了，但 50000 行都回表，还是很慢
```

### 根因

二级索引 → 回聚簇索引取整行数据（回表）。如果命中行数太多，回表代价 > 全表扫描，优化器会放弃索引。

### 解决方案

```sql
-- 方案1：覆盖索引（只查索引列，不回表）
-- ❌ SELECT * FROM orders WHERE user_id = 123  -- 回表取所有列
-- ✅ SELECT id, user_id, status, amount FROM orders WHERE user_id = 123
--    建立 idx_user_id_status_amount 联合索引，完全覆盖查询列

-- 方案2：减少返回行数
-- ❌ SELECT * FROM orders WHERE user_id = 123 ORDER BY create_time LIMIT 100000
-- ✅ 加分页 + 索引排序
--    建立 idx_user_id_create_time 联合索引

-- 方案3：延迟关联（先走覆盖索引取 ID，再关联回表）
SELECT o.* FROM orders o
INNER JOIN (
    SELECT id FROM orders 
    WHERE user_id = 123 AND status = 1
    ORDER BY create_time DESC
    LIMIT 1000
) t ON o.id = t.id;
```

---

## 场景 C：深分页优化

### 现象

```sql
-- 第 10 万页
SELECT * FROM orders 
WHERE status = 1 
ORDER BY create_time DESC 
LIMIT 1000000, 20;  -- 扫描 1000020 行，丢弃 1000000 行
```

越往后翻越慢，因为 MySQL 必须先扫描并丢弃前面的所有行。

### 解决方案

```sql
-- 方案1：游标分页（推荐，适合瀑布流/时间线）
-- 前端传上一页最后一条的 create_time
SELECT * FROM orders 
WHERE status = 1 AND create_time < '2026-04-27 15:30:00'
ORDER BY create_time DESC 
LIMIT 20;

-- 方案2：子查询优化（适合必须跳页的场景）
SELECT * FROM orders o
INNER JOIN (
    SELECT id FROM orders 
    WHERE status = 1 
    ORDER BY create_time DESC 
    LIMIT 1000000, 20
) t ON o.id = t.id;
-- 子查询走覆盖索引（只取 id），速度快很多

-- 方案3：es/searchAfter（海量数据）
-- 导入 Elasticsearch，用 search_after 做深度分页
```

性能对比：

| 方案 | 10万页耗时 | 适用场景 |
|------|-----------|---------|
| LIMIT offset | 3-5s | ❌ 不适合深分页 |
| 游标分页 | 5ms | ✅ 瀑布流/时间线 |
| 子查询优化 | 200ms | ✅ 必须跳页 |
| Elasticsearch | 10ms | ✅ 海量数据 |

---

## 场景 D：JOIN 优化

### 现象

```
多表 JOIN 的 SQL 执行时间 5-10s
explain 显示驱动表全表扫描
```

### 根因

小表驱动大表的原则被违反了，或者 JOIN 字段没有索引。

### 解决方案

```sql
-- 1. 确保 JOIN 字段有索引
-- 小表的 join_column 上建索引

-- 2. 小表驱动大表（MySQL 优化器通常能自动判断，但 SQL 写法有影响）
-- ❌ 大表 LEFT JOIN 小表（如果只需要交集，不要用 LEFT JOIN）
-- ✅ 小表 INNER JOIN 大表

-- 3. 减少 JOIN 的表数量
-- ❌ 5张表 JOIN
-- ✅ 拆成 2次查询，或用冗余字段减少 JOIN

-- 4. 反范式设计（用空间换时间）
-- 高频查询的字段直接冗余到主表，避免 JOIN
```

---

## EXPLAIN 关键字段速查

| 字段 | 含义 | 好的值 | 差的值 |
|------|------|--------|--------|
| type | 访问类型 | const > eq_ref > ref > range > index | ALL（全表扫描） |
| key | 实际使用的索引 | 有值 | NULL |
| rows | 预估扫描行数 | 小 | 大（>1万要注意） |
| filtered | 过滤比例 | 高（接近100%） | 低 |
| Extra | 额外信息 | Using index（覆盖索引） | Using filesort / Using temporary |

**Extra 的红灯信号**：
- `Using filesort`：额外排序，需要优化 ORDER BY
- `Using temporary`：使用了临时表，通常是因为 GROUP BY 和 ORDER BY 字段不一致
- `Using where`：在索引过滤后还需要 where 过滤（正常，但 rows 大就要注意）

---

## 索引设计原则

```
1. 查询需求驱动：WHERE / ORDER BY / GROUP BY 中出现频率高的列优先
2. 区分度高优先：区分度 = COUNT(DISTINCT col) / COUNT(*)，越高越好
3. 联合索引：最左前缀原则，把区分度高的列放前面
4. 覆盖索引：把 SELECT 的列也放进联合索引，避免回表
5. 控制索引数量：单表索引不超过 5-6 个，多了影响写入性能
6. 短索引：前缀索引（如 VARCHAR(50) 只取前 20 字符）
```

---

## 涉及知识点

| 概念 | 所属域 | 关键点 |
|------|--------|--------|
| B+树索引结构 | 05_数据库/02_索引原理 | 为什么不用 B 树/红黑树/哈希 |
| InnoDB 存储结构 | 05_数据库/01_存储引擎 | 聚簇索引 vs 二级索引 |
| 事务与隔离级别 | 05_数据库/03_事务 | MVCC 实现、间隙锁 |
| SQL 执行流程 | 05_数据库/04_SQL优化 | 解析→优化→执行 |
| 分库分表 | 07_分布式与架构 | 数据量大了怎么办 |

---

## 追问链

### 追问 1：联合索引 (a,b,c)，WHERE b=1 AND c=2 能走索引吗？

> "不能走这个联合索引。B+树按 a→b→c 排序，没有 a 的条件，无法确定 b 的起始位置。但优化器可能选择走其他索引或全表扫描。如果这个查询频率很高，需要单独建 (b,c) 联合索引。"

### 追问 2：什么时候不该加索引？

> "1. 区分度很低的列（如性别、状态只有两三个值）。2. 数据量很小的表（几百行，全表扫描更快）。3. 频繁更新的列（每次更新都要维护索引）。4. WHERE 中从不出现的列。一句话：**索引是空间换时间，写入频繁的表索引要克制。**"

### 追问 3：线上突然出现慢查询怎么办？

> "1. 先看 slow_query_log 找到具体 SQL。2. explain 分析执行计划。3. 看是索引问题还是数据量问题。4. 如果是索引问题，加索引（`ALTER TABLE ADD INDEX`，MySQL 8.0+ 支持在线加索引不锁表）。5. 如果是数据量问题，考虑归档历史数据或分表。6. 临时止血可以用 force index 指定索引，或用缓存扛。"

### 追问 4：怎么监控慢查询？

> "配置 `slow_query_log = ON` + `long_query_time = 1`（超过1秒记录）。配合 `pt-query-digest`（Percona Toolkit）定期分析慢查询日志，生成 Top N 报告。也可以用 Prometheus + Grafana，通过 MySQL exporter 采集 `mysql_global_status_slow_queries`。"

---

## 排查 Checklist

```
□ 开了慢查询日志吗？ → slow_query_log / long_query_time
□ explain 的 type 是什么？ → ALL 说明全表扫描
□ 索引失效了吗？ → 检查 6 种失效情况
□ rows 多吗？ → 超过 1 万行要注意
□ Extra 有 filesort/temporary 吗？ → 需要优化
□ 是不是深分页？ → LIMIT offset 过大
□ JOIN 字段有索引吗？ → 驱动表的 join_column
□ 表数据量多大？ → 超过千万考虑分表
```

---

## 我的实战笔记

-（待补充，项目中的真实经历）
