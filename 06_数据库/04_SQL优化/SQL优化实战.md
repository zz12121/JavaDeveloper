# SQL优化实战

## 这个问题为什么存在？

> 知道索引原理，但遇到实际SQL还是不知道怎么优化。
> 理论懂了，实战不会。

**核心问题**：从"知道"到"会用"，中间隔着大量的实战经验。

---

## 它是怎么解决问题的？

### 场景1：大分页查询（LIMIT offset, size）

**问题SQL**：

```sql
-- 分页查询，翻到最后一页时极慢
SELECT * FROM orders ORDER BY id LIMIT 1000000, 20;
-- 需要跳过1000000行，然后返回20行
-- 执行过程：扫描1000020行，丢掉前1000000行，返回最后20行
-- 越翻越慢
```

**优化方案1：使用覆盖索引+延迟关联**

```sql
-- 先通过覆盖索引快速定位ID，再回表取数据
SELECT * FROM orders a
JOIN (SELECT id FROM orders ORDER BY id LIMIT 1000000, 20) b
ON a.id = b.id;
-- 子查询只用索引（覆盖索引），不需要回表
-- 外层JOIN只回表20次（而不是1000020次）
```

**优化方案2：使用游标分页（推荐）**

```sql
-- 记录上次查询的最后一条ID
SELECT * FROM orders WHERE id > 1234567 ORDER BY id LIMIT 20;
-- 直接用索引定位，不需要跳过行
-- 但缺点是不能"跳页"（只能上一页/下一页）
```

**优化方案3：业务限制**

```
不允许跳到最后一页（比如只允许翻前100页）
→ 99%的业务场景，用户不会翻到100页以后
```

### 场景2：范围查询 + 排序

**问题SQL**：

```sql
SELECT * FROM orders 
WHERE user_id = 123 
  AND created_at > '2024-01-01'
ORDER BY created_at DESC
LIMIT 20;
```

**索引设计**：

```sql
-- 错误：只给user_id加索引
CREATE INDEX idx_user_id ON orders(user_id);
-- 执行过程：用user_id过滤 → 回表 → filesort（ORDER BY created_at）

-- 正确：联合索引
CREATE INDEX idx_user_created ON orders(user_id, created_at);
-- 执行过程：索引直接包含排序字段 → 不需要filesort
```

**但有问题**：如果`created_at`是范围查询，联合索引的后续字段无法利用索引排序。

```sql
-- 索引：(user_id, created_at)
WHERE user_id = 123 AND created_at > '2024-01-01' 
ORDER BY created_at DESC
-- created_at是范围查询，ORDER BY还是可能filesort
```

**优化**：如果业务允许，把范围查询改成等值查询。

```sql
-- 如果只需要最近7天的数据：
WHERE user_id = 123 
  AND created_at BETWEEN '2024-01-01' AND '2024-01-07'
-- 还是范围查询，但范围缩小了
```

### 场景3：JOIN优化（驱动表选择）

**问题SQL**：

```sql
SELECT * FROM orders o
JOIN users u ON o.user_id = u.id
WHERE u.vip_level = 1
LIMIT 20;
```

**驱动表选择原则**：

```
驱动表（第一张表）的选择：
1. 尽量选结果集小的表作为驱动表
2. 如果被驱动表有索引，可以选大表作为驱动表（Nested Loop Join）
```

**优化**：

```sql
-- 错误：选orders作为驱动表（大表）
-- EXPLAIN显示：table=orders, type=ALL（全表扫描）

-- 正确：选users作为驱动表（小表，且有索引）
-- 给users.vip_level加索引
CREATE INDEX idx_vip_level ON users(vip_level);

-- EXPLAIN显示：
-- 1. table=users, type=ref（用vip_level索引）
-- 2. table=orders, type=ref（用user_id索引）
```

**JOIN优化核心**：

```
1. 被驱动表的JOIN字段必须有索引
2. 驱动表尽量选结果集小的
3. 避免JOIN的WHERE条件中有函数运算（索引失效）
```

### 场景4：子查询 vs JOIN

**问题SQL**：

```sql
-- 子查询：找出有订单的用户
SELECT * FROM users 
WHERE id IN (SELECT user_id FROM orders);
```

**优化**：改成JOIN

```sql
-- JOIN通常比子查询快（优化器更容易优化）
SELECT DISTINCT u.* 
FROM users u
JOIN orders o ON u.id = o.user_id;
```

**但有例外**：如果子查询的表很小，JOIN的表很大，子查询可能更快。

### 场景5：COUNT(*) 优化

**问题SQL**：

```sql
-- 大表的COUNT(*)极慢
SELECT COUNT(*) FROM orders;
-- 全表扫描或全索引扫描
```

**优化方案1：使用更小的索引**

```sql
-- InnoDB在执行COUNT(*)时，会选最小的索引来扫描
-- 所以可以给一个很小的列建索引（比如一个SMALLINT列）
CREATE INDEX idx_small ON orders(status);  -- status是TINYINT
SELECT COUNT(*) FROM orders;  -- 用idx_small索引，扫描行数一样，但索引页更小
```

**优化方案2：用Redis计数**

```
订单数、用户数等计数，可以存在Redis中：
- 新增订单：Redis incr orders:count
- 删除订单：Redis decr orders:count
- 查询总数：Redis get orders:count

优点：O(1)查询
缺点：数据可能不一致（需要定期从数据库修正）
```

**优化方案3：使用汇总表**

```sql
-- 建一张汇总表
CREATE TABLE orders_count (
    date DATE PRIMARY KEY,
    cnt INT
);

-- 每天定时任务，把当天的订单数写入汇总表
-- 查询时：SUM(cnt)即可
```

---

## 它和相似方案的本质区别是什么？

### 延迟关联 vs 直接查询

| 维度 | 直接查询（LIMIT 1000000, 20） | 延迟关联 |
|------|-----------------------------|---------|
| 扫描行数 | 1000020行 | 20行（索引） + 20行（回表） |
| 回表次数 | 20次 | 20次 |
| 性能 | 极差（越后面越慢） | 好很多 |
| 适用场景 | 小偏移量（前几页） | 大偏移量（深分页） |

**本质区别**：延迟关联先通过覆盖索引快速定位ID，再回表取数据，避免扫描大量不需要的行。

### 游标分页 vs 传统分页（LIMIT offset, size）

| 维度 | 传统分页 | 游标分页（WHERE id > last_id） |
|------|---------|-------------------------------|
| 性能 | 偏移量越大越慢 | 稳定（始终用索引定位） |
| 跳页 | 支持（可以跳到第N页） | 不支持（只能上一页/下一页） |
| 实时性 | 差（数据变化会导致结果不一致） | 好（基于固定的ID，不会重复/遗漏） |
| 适用场景 | 后台管理系统（需要跳页） | 移动端/前端（只上一页/下一页） |

**本质区别**：传统分页是"跳过N行"，游标分页是"记住上次的位置"。

---

## 正确使用方式

### 优化决策流程

拿到一条慢 SQL 时，按以下顺序决策：

```
1. EXPLAIN 看执行计划 → 定位瓶颈（全表扫描？filesort？临时表？）
2. 加索引/调整索引 → 解决 80% 的性能问题
3. 改写 SQL（子查询→JOIN、避免 SELECT *、覆盖索引）
4. 架构层面优化（分页策略、COUNT 方案、读写分离）
```

### 三条核心原则

1. **先 EXPLAIN，再优化**。不要凭直觉加索引，用数据说话
2. **覆盖索引优先**。查询只涉及索引列时，不需要回表，性能最优
3. **减少扫描行数**。所有优化的本质都是让 MySQL 扫更少的行

---

## 边界情况和坑

### 坑1：延迟关联反而变慢

```
现象：
- 用了延迟关联，但查询反而变慢了

原因：
- 子查询返回的结果集很大（比如LIMIT 1000000, 10000）
- JOIN的开销反而更大

解决：
- 如果延迟关联的结果集>1000行，考虑用游标分页
- 或者限制分页深度（不允许查太后面的页）
```

### 坑2：JOIN的被驱动表没索引

```sql
-- 错误：被驱动表没索引
SELECT * FROM orders o
JOIN users u ON o.user_id = u.id;
-- 如果users.id没有索引（不可能，id是主键）
-- 或者JOIN条件写错了字段

-- 检查：EXPLAIN的type字段
-- 如果type=ALL，说明被驱动表全表扫描 → 性能极差
```

### 坑3：游标分页的ID不是连续的

```
现象：
- 用WHERE id > last_id分页
- 但中间有删除的行，导致"漏数据"

本质：
- 这不是Bug，是业务选择
- 如果业务不允许漏数据，不能用游标分页
- 或者，用创建时间分页（但可能有重复数据）
```

### 坑4：COUNT(*)在不同存储引擎的表现

```sql
-- MyISAM：COUNT(*)是O(1)（维护了一个计数器）
SELECT COUNT(*) FROM t;  -- 极快

-- InnoDB：COUNT(*)是O(N)（需要扫描索引）
SELECT COUNT(*) FROM t;  -- 慢（大表）
```

**为什么InnoDB不维护计数器？**
因为MVCC，不同事务看到的行数可能不同（快照读），无法维护一个"全局正确"的计数器。

---

