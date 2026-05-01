# MVCC 与事务处理

## 这个问题为什么存在？

如果你已经学过 MySQL 的 MVCC（Undo Log 版本链 + ReadView），会发现 PostgreSQL 的 MVCC 实现**完全不同**。

```
MySQL（InnoDB）MVCC：
  旧版本存在 Undo Log 里
  Undo Log 可以被覆盖（回滚段复用）
  清理：后台 Purge 线程自动清理

PostgreSQL MVCC：
  旧版本（死元组）直接存在堆表里
  每个行版本有自己的 xmin/xmax（事务 ID）
  清理：需要 VACUUM 主动清理（不是自动的！）
```

**核心问题**：
1. PostgreSQL 怎么通过 xmin/xmax 判断行的版本可见性？
2. 为什么需要 VACUUM？AutoVacuum 是怎么工作的？
3. 事务 ID 为什么要用 32 位整数（会 wraparound）？
4. PostgreSQL 的隔离级别和 MySQL 有什么不同？

理解这些，才能用好 PostgreSQL——特别是 **VACUUM 调优**（这是 PG DBA 的核心技能）。

---

## 它是怎么解决问题的？

### 一、行版本结构（Heap Tuple Header）

PostgreSQL 的每一行数据，在堆表里都有一个 **元组头（Tuple Header）**，里面存了事务相关的信息。

```
Heap Tuple 结构：
┌───────────────────────┐
│  Tuple Header         │
│  ├── xmin  (32 bit) │  ← 插入该行的事务 ID
│  ├── xmax  (32 bit) │  ← 删除/更新该行的事务 ID（0 = 未删除）
│  ├── cmin/cmax       │  ← 同一事务内的命令序号
│  ├── t_ctid          │  ← 指向新版本行（更新时）
│  └── ...             │
├───────────────────────┤
│  用户数据（列值）      │
└───────────────────────┘
```

**插入流程**：
```sql
BEGIN;
INSERT INTO users VALUES (1, 'Alice');  -- 假设事务 ID = 100
COMMIT;
```

```
堆表里的行：
  xmin = 100   ← 插入事务 ID
  xmax = 0     ← 未被删除/更新
  data = (1, 'Alice')
```

**更新流程**（PostgreSQL 的 UPDATE = DELETE + INSERT）：

```sql
BEGIN;
UPDATE users SET name = 'Bob' WHERE id = 1;  -- 事务 ID = 101
COMMIT;
```

```
堆表里的两行：
  旧行：xmin=100, xmax=101, data=(1, 'Alice')   ← 被标记为"删除"
  新行：xmin=101, xmax=0,   data=(1, 'Bob')     ← 新版本
```

> **关键**：PostgreSQL 的 UPDATE 不是"原地更新"，而是"标记旧行删除 + 插入新行"。这就是 **堆表** 的特性。

### 二、事务 ID（XID）与可见性判断

PostgreSQL 用 **XID（32 位整数）** 标识事务，通过比较 XID 来判断行版本的可见性。

#### XID 比较规则

```
XID 是 32 位整数（0 ~ 4294967295），循环使用：
  1 → 2 → 3 → ... → 4294967295 → 0 → 1 → 2 ...

比较时，用"距离当前 XID 的年龄"：
  age = (current_xid - row_xmin) mod 2^32
  age <  2^31  → "过去"（可见）
  age >= 2^31  → "未来"（不可见）
```

```
例子：
  current_xid = 100
  row_xmin = 90    → age = 10 → 可见（过去的）
  row_xmin = 110   → age = 4294967206 → 不可见（未来的，因为是循环）
```

#### 可见性判断规则（简化）

```
对于一行（xmin, xmax），事务 TXN 能否看到这行？

  1. xmin == TXN           → 可见（自己插入的）
  2. xmin 已提交，xmax == 0 → 可见（已提交，未删除）
  3. xmin 已提交，xmax == TXN → 不可见（自己删除的，还没提交）
  4. xmin 已提交，xmax != 0 且 xmax 未提交 → 可见（删除还没提交）
  5. xmin 未提交          → 不可见（别人未提交的数据）
```

**PostgreSQL 不需要 ReadView！**

```
MySQL（InnoDB）：
  需要 ReadView（活跃事务列表）来判断哪些版本可见
  → 快照太大时，创建 ReadView 很慢

PostgreSQL：
  只需要比较 XID（xmin < current_xid = 可见）
  → 不需要 ReadView，快照很小
  → 但需要维护事务状态（CLOG）
```

### 三、事务状态与 CLOG

PostgreSQL 把每个事务的状态存在 **CLOG（Commit Log）** 里（类似 MySQL 的 Undo Log 里的 trx_id，但是 CLOG 是集中存储的）。

```
事务状态（2 bit/事务）：
  00 = IN_PROGRESS（进行中）
  01 = COMMITTED（已提交）
  10 = ABORTED（已回滚）
  11 = 子事务已提交

CLOG 存在 $PGDATA/pg_xact/ 目录里（每个事务占 2 bit，很紧凑）
```

**为什么 CLOG 很重要？**

可见性判断时，需要知道"xmin 的事务有没有提交"——这个信息就在 CLOG 里。

如果 CLOG 损坏（断电/磁盘故障），PostgreSQL 无法判断行的可见性，会报错或返回错误数据。

### 四、VACUUM——PostgreSQL 独有的机制

因为旧版本行（死元组）留在堆表里，需要**主动清理**。

#### 为什么需要 VACUUM？

```
没有 VACUUM 的后果：
  1. 表膨胀：死元组占用磁盘空间，不释放
  2. 查询变慢：扫描时要跳过死元组（虽然可见性判断会跳过，但 IO 还是要读这些页面）
  3. XID wraparound：XID 循环使用，如果不冻结（FREEZE）旧元组，
     会导致数据"消失"（事务 ID 回卷）
```

#### VACUUM 做了什么？

```sql
VACUUM my_table;   -- 清理死元组，释放空间给"本表"（不是返还 OS）
VACUUM FULL my_table;  -- 锁表，重建整个表，空间返还 OS（慎用！）
```

```
VACUUM 流程：
  1. 扫描堆表，找出死元组（xmax 已提交，且没有其他事务需要看这些旧版本）
  2. 标记死元组的空间为"可重用"（不是马上释放给 OS）
  3. 更新统计信息（pg_stat_user_tables）
  4. 更新可见性映射（Visibility Map，加速 Index-Only Scan）
  5. 如果 FREEZE，把旧元组的 xmin 设为 FrozenXID（防止 XID wraparound）
```

#### AutoVacuum（自动清理）

生产环境**必须开启 AutoVacuum**（默认是开启的）。

```postgresql.conf
autovacuum = on                 # 开启 AutoVacuum（默认 on）
autovacuum_max_workers = 3       # 同时运行的 AutoVacuum 进程数
autovacuum_naptime = 1min        # 检查间隔

# 触发 VACUUM 的阈值
autovacuum_vacuum_threshold = 50       # 至少 50 个死元组
autovacuum_vacuum_scale_factor = 0.2   # 死元组超过表大小的 20% 就触发

# 触发 ANALYZE 的阈值
autovacuum_analyze_threshold = 50
autovacuum_analyze_scale_factor = 0.1  # 变更超过表大小 10% 就触发
```

**大表的 AutoVacuum 调优**：

```sql
-- 对大表，降低 scale_factor（让 AutoVacuum 更积极）
ALTER TABLE big_table SET (
    autovacuum_vacuum_scale_factor = 0.05,   -- 5% 就触发（默认 20%）
    autovacuum_analyze_scale_factor = 0.02    -- 2% 就触发 ANALYZE
);
```

### 五、事务隔离级别

PostgreSQL 支持四种标准隔离级别，但实现和 MySQL 有差异。

```sql
-- 设置事务隔离级别
BEGIN ISOLATION LEVEL Repeatable Read;
-- 或者全局设置
SET default_transaction_isolation = 'repeatable read';
```

| 隔离级别 | PostgreSQL 实现 | 脏读 | 不可重复读 | 幻读 |
|----------|----------------|------|------------|------|
| Read Uncommitted | 实际 = Read Committed（PG 不支持脏读） | ❌ | ✅ | ✅ |
| Read Committed（默认） | 每条语句获取新快照 | ❌ | ✅ | ✅ |
| Repeatable Read | 事务开始时获取快照，整个事务用同一个快照 | ❌ | ❌ | ❌（PG 的 RR 防幻读！） |
| Serializable | 用谓词锁（Predicate Lock）实现（不是快照！） | ❌ | ❌ | ❌ |

#### PostgreSQL 的 Repeatable Read 为什么防幻读？

```
MySQL（InnoDB）：
  Repeatable Read 用 "第一次读建立的 ReadView"
  → 新插入的行（XID > ReadView 的 max_trx_id）不可见 → 防幻读

但 MySQL 的 RR 实际上**不完全防幻读**（当前读 + 间隙锁才是完全防）

PostgreSQL：
  Repeatable Read 用 "事务开始时的 XID 快照"
  → 整个事务期间，快照不变
  → 其他事务插入的新行（XID > 快照的 XID）不可见
  → 真正的防幻读（不需要间隙锁）
```

**代价**：PostgreSQL 的 RR 和 Serializable 更容易遇到 **序列化失败（40001 错误）**，需要应用层重试。

```sql
-- PostgreSQL 的 RR/Serializable 需要应用层处理重试
BEGIN ISOLATION LEVEL Repeatable Read;
UPDATE accounts SET balance = balance - 100 WHERE id = 1;
-- 如果其他事务也修改了 id=1，这里会报：
-- ERROR: 40001: could not serialize access due to concurrent update
-- 应用需要捕获这个错误，重试整个事务
```

---

## 它和相似方案的本质区别是什么？

### PostgreSQL MVCC vs MySQL InnoDB MVCC

| 维度 | PostgreSQL | MySQL（InnoDB） |
|------|------------|----------------|
| 旧版本存储位置 | 堆表（死元组） | Undo Log（回滚段） |
| 清理机制 | VACUUM（主动） | Purge 线程（自动） |
| 快照大小 | 很小（只要 XID） | 大（活跃事务列表） |
| 更新开销 | 高（INSERT + DELETE） | 低（原地更新 + Undo Log） |
| 表膨胀风险 | 高（VACUUM 不及时） | 低（Purge 自动清理） |
| 长事务影响 | 严重（阻止 VACUUM 清理） | 中等（Undo Log 占用增加） |

**本质区别**：

1. **PostgreSQL 的 MVCC 更简单、更通用**（不需要维护 Undo Log），但**运维成本更高**（需要 VACUUM）
2. **MySQL 的 MVCC 性能更好**（更新是原地操作），但 **Undo Log 管理复杂**（回滚段大小有限）

---

## 正确使用方式

### 正确用法

**1. 开启 AutoVacuum，并对大表单独调优**

```sql
-- 查看 AutoVacuum 是否在运行
SELECT * FROM pg_stat_activity WHERE query LIKE '%autovacuum%';

-- 对大表降低触发阈值
ALTER TABLE big_table SET (
    autovacuum_vacuum_scale_factor = 0.05,
    autovacuum_vacuum_threshold = 5000
);
```

**为什么正确**：大表（百万/千万级）20% 的死元组非常多，等 AutoVacuum 触发时，表已经很膨胀了。降低 scale_factor 让 VACUUM 更积极。

**2. 避免长事务（会阻止 VACUUM 清理）**

```sql
-- 查看长事务
SELECT pid, usename, query_start, state, query
FROM pg_stat_activity
WHERE state != 'idle'
  AND now() - query_start > interval '5 minutes';
```

**为什么正确**：PostgreSQL 的 VACUUM 不能清理"长事务开始后产生的死元组"（因为长事务可能还需要看这些旧版本）。长事务会导致表严重膨胀。

**3. 用 PREPARE TRANSACTION 做两阶段提交（分布式事务）**

```sql
-- 开启两阶段提交（需要 max_prepared_transactions > 0）
BEGIN;
UPDATE accounts SET balance = balance - 100 WHERE id = 1;
PREPARE TRANSACTION 'txn_001';  -- 第一阶段：准备
-- 此时事务状态持久化到磁盘，即使 Crash 也不会丢失
COMMIT PREPARED 'txn_001';     -- 第二阶段：提交
```

**4. 监控 XID 使用情况，防止 wraparound**

```sql
-- 查看每个数据库的 XID 年龄（应该 < 1 亿，接近 10 亿会强制只读）
SELECT datname, age(datfrozenxid) FROM pg_database
ORDER BY age(datfrozenxid) DESC;
```

### 错误用法及后果

**错误1：从未 VACUUM，导致表膨胀**

```
现象：表数据只有 10GB，但磁盘占用 200GB
原因：大量 UPDATE/DELETE 产生死元组，从未 VACUUM
后果：
  1. 查询变慢（扫描更多页面）
  2. 磁盘空间浪费
  3. XID wraparound → 数据库强制进入只读模式
```

**修复**：
```sql
VACUUM FREEZE my_table;  -- 紧急清理 + 冻结
-- 长期方案：确保 AutoVacuum 正常运行
```

**错误2：在 Repeatable Read 隔离级别下不处理序列化失败**

```java
// ❌ 错误：不处理重试
try (Connection conn = dataSource.getConnection()) {
    conn.setTransactionIsolation(Connection.TRANSACTION_REPEATABLE_READ);
    // 如果报 40001 错误，这里会直接抛异常，数据不一致
}
```

```java
// ✅ 正确：处理重试
for (int retry = 0; retry < 3; retry++) {
    try {
        // 执行事务
        break;  // 成功，跳出重试循环
    } catch (SQLException e) {
        if ("40001".equals(e.getSQLState())) {
            continue;  // 序列化失败，重试
        }
        throw e;
    }
}
```

**错误3：默认隔离级别（Read Committed）下，业务逻辑有不可重复读**

```sql
-- 事务 1
BEGIN;
SELECT balance FROM accounts WHERE id = 1;  -- 返回 1000
-- 此时事务 2 修改了 balance = 500，并提交
SELECT balance FROM accounts WHERE id = 1;  -- 返回 500（不可重复读！）
COMMIT;
```

**修复**：用 `Repeatable Read` 隔离级别（PostgreSQL 的 RR 防幻读）。

---

## 边界情况和坑

### 坑1：XID Wraparound（事务 ID 回卷）

```
XID 是 32 位整数，循环使用
如果旧元组的 xmin 距离当前 XID 超过 2^31（约 21 亿）
  → 会被认为是"未来的"数据 → 不可见 → 数据"丢失"！
```

**PostgreSQL 的防御机制**：
1. **FREEZE 操作**：把旧元组的 xmin 设为 `FrozenXID`（特殊值 2，永远可见）
2. **AutoVacuum** 会自动 FREEZE（当 `age(datfrozenxid) > vacuum_freeze_min_age`）
3. **紧急模式**：如果 XID 年龄超过 `autovacuum_freeze_max_age`（默认 2 亿），数据库强制进入只读模式，保护数据

**监控**：
```sql
-- 应该 < autovacuum_freeze_max_age（默认 2 亿）
SELECT datname, age(datfrozenxid) FROM pg_database;
```

### 坑2：VACUUM FULL 锁表，导致业务中断

```
VACUUM FULL：
  → 对表加排他锁（ACCESS EXCLUSIVE LOCK）
  → 所有读写都被阻塞（包括 SELECT！）
  → 大表可能需要几小时
```

**解决**：
1. 用 `pg_repack`（第三方工具，可以在线重建表，不长时间锁表）
2. 或者在维护窗口执行 VACUUM FULL

### 坑3：函数/触发器里的隐式事务

```sql
-- PostgreSQL 的函数默认在一个事务里运行
CREATE FUNCTION transfer() RETURNS void AS $$
BEGIN
    UPDATE accounts SET balance = balance - 100 WHERE id = 1;
    UPDATE accounts SET balance = balance + 100 WHERE id = 2;
    -- 如果这里报错，整个函数回滚（事务自动回滚）
END;
$$ LANGUAGE plpgsql;
```

**注意**：PostgreSQL 没有 `COMMIT` 在里面（除非用 `dblink` 或 `postgres_fdw` 访问外部数据库）。

---

## 面试话术

**Q1：PostgreSQL 的 MVCC 是怎么实现的？和 MySQL 有什么不同？**

> PostgreSQL 的 MVCC 是把旧版本行（死元组）直接存在堆表里，每行有 xmin/xmax 标记插入/删除事务 ID，通过 XID 比较判断可见性。MySQL 的 MVCC 是把旧版本存在 Undo Log 里，通过 ReadView 判断可见性。PostgreSQL 的优势是不需要维护 Undo Log，但劣势是需要 VACUUM 主动清理死元组，运维成本更高。

**Q2：为什么 PostgreSQL 需要 VACUUM？AutoVacuum 是怎么触发的？**

> 因为 MVCC 的旧版本留在堆表里，不清理会导致表膨胀、查询变慢、XID wraparound。AutoVacuum 后台进程会自动清理：当死元组数量超过 `autovacuum_vacuum_threshold + 表大小 × autovacuum_vacuum_scale_factor` 时触发。大表建议降低 scale_factor（如 0.05），让 VACUUM 更积极。

**Q3：PostgreSQL 的 Repeatable Read 为什么能防幻读？**

> PostgreSQL 的 RR 在事务开始时创建一个 XID 快照，整个事务期间都用这个快照。其他事务插入的新行（XID > 快照的 XID）对当前事务不可见，所以不会出现幻读。但代价是更容易遇到序列化失败（40001 错误），需要应用层重试。

**Q4：什么是 XID Wraparound，怎么预防？**

> XID 是 32 位整数，循环使用。如果旧元组的 xmin 距离当前 XID 超过 21 亿，会被认为是"未来的"数据，导致数据不可见（相当于数据丢失）。预防：确保 AutoVacuum 正常运行（会自动 FREEZE 旧元组），监控 `age(datfrozenxid)`，应该远低于 2 亿。

**Q5：PostgreSQL 的事务隔离级别有哪些？默认是哪个？**

> 四种：Read Uncommitted（实际等于 Read Committed）、Read Committed（默认）、Repeatable Read（PG 的 RR 防幻读）、Serializable（用谓词锁）。默认是 Read Committed，但业务需要可重复读时应该用 Repeatable Read。

---

## 本文总结

| 核心概念 | 要点 |
|----------|------|
| **行版本（xmin/xmax）** | 每行有插入/删除事务 ID，通过 XID 比较判断可见性 |
| **MVCC 实现** | 旧版本存在堆表（死元组），不需要 Undo Log |
| **VACUUM** | 必须定期清理死元组，防止表膨胀和 XID wraparound |
| **AutoVacuum** | 生产必须开启，大表要单独调低 scale_factor |
| **事务隔离级别** | RR 防幻读（不需要间隙锁），但可能序列化失败，需要重试 |
| **XID Wraparound** | XID 32 位会循环，必须 FREEZE 旧元组，监控 age(datfrozenxid) |

**PostgreSQL MVCC 的核心权衡**：更简单（无 Undo Log）、更通用（所有隔离级别都用同一套机制），但运维更复杂（需要 VACUUM）。

---
