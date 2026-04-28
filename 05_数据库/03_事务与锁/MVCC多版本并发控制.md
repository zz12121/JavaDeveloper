# MVCC 多版本并发控制

## 这个问题为什么存在？

> 数据库并发访问时，如果只用锁（排他锁）来保证隔离性，所有读操作都要等写操作完成 → **读性能极差**（写阻塞读）。

快照读（Snapshot Read）解决了这个问题：**读操作不需要加锁**，可以读到某个时间点的「一致的数据快照」，而不会被正在写入的数据干扰。

**MVCC = Multi-Version Concurrency Control**，通过「为每行数据保存多个版本」来实现读写不阻塞。

---

## 它是怎么解决问题的？

### 核心机制：每行数据的隐藏列

InnoDB 存储引擎中，**每行数据**都有两个隐藏列：

```
┌────────────────────────────────────────────┐
│ 隐藏列                                     │
│  ├── db_trx_id (6 bytes)  // 最近修改的事务ID  │
│  ├── db_roll_ptr (7 bytes) // 回滚指针（指向undo log）│
│  └── db_row_id (6 bytes)   // 主键ID（无主键时生成）  │
├────────────────────────────────────────────┤
│ 数据列                                     │
│  id  │  name  │  balance                   │
└────────────────────────────────────────────┘
```

**关键点**：
- `db_trx_id`：谁最近改了这行（记录事务编号）
- `db_roll_ptr`：指向前一个版本（undo log 链）

**数据版本的链式结构**：

```
undo log 链（版本链）
┌─────────┐
│ v3 (最新) │ ← 当前数据
│ trx_id=30│
│ roll_ptr │──────────┐
└─────────┘           │
┌─────────┐           │
│ v2      │ ← undo log│ ← db_roll_ptr 指向
│ trx_id=20│           │
│ roll_ptr │───────────┼──┐
└─────────┘           │  │
                      │  │
┌─────────┐           │  │
│ v1 (最老)│ ← undo log│  │
│ trx_id=10│            │  │
│ roll_ptr │─── NULL    │  │
└─────────┘              │  │
                          ▼  ▼
                   ┌─────────┐
                   │ (无更早版本)
                   └─────────┘
```

**UPDATE 操作创建新版本的原理**：

```sql
UPDATE account SET balance = 200 WHERE id = 1;
```

1. 在原行数据的 `db_roll_ptr` 指向的 undo log 里，记录**旧值**（balance=100）
2. 修改原行数据为新值（balance=200）
3. 更新 `db_trx_id = 当前事务ID`
4. 旧 undo log 被保留，链式结构形成

---

### 核心机制：Read View（快照读的关键）

当执行**快照读**（`SELECT`）时，InnoDB 创建 Read View：

```java
class ReadView {
    private int creatorTrxId;    // 创建这个视图的事务ID
    private int[] minTrxIds;     // 活跃事务ID列表（未提交的事务）
    private int minTrxId;         // min(minTrxIds)
    private int maxTrxId;         // 创建 Read View 时的最大事务ID + 1
    private boolean mvccBuckets;  // 用于去重的快照事务ID集合
}
```

**可见性判断规则（重点）**：

```
一个数据版本（trx_id）对当前事务可见？

条件1：trx_id == creatorTrxId
  → 当前事务自己改的，可见

条件2：trx_id < minTrxId（最早的活跃事务ID之前）
  → 这个事务在当前 Read View 创建时已经提交了，可见

条件3：trx_id >= maxTrxId
  → 这个事务是在 Read View 创建之后才开始的，不可见

条件4：trx_id 在活跃事务列表中
  → 事务未提交，不可见

所有条件都不满足 → 从 db_roll_ptr 找上一个版本，重复判断
```

**图示**：

```
时间线
──────┼────────────────────────────────────→

事务10（提交）   事务20（活跃，未提交）   事务30（未来事务）
  │                   │                      │
  ↓                   ↓                      ↓
 trx_id=10         trx_id=20              trx_id=30

Read View 创建时：
  minTrxId = 20
  maxTrxId = 31
  活跃事务列表 = [20]

数据版本可见性：
  trx_id=10 → <20 → 可见 ✅（已提交）
  trx_id=20 → 在活跃列表中 → 不可见 ❌（未提交）
  trx_id=30 → >=31 → 不可见 ❌（ReadView之后才开始）
```

---

### 源码关键路径：快照读的执行

```sql
SELECT * FROM account WHERE id = 1;
```

**执行流程**：

```
1. 创建 Read View（快照）
2. 读取最新数据行（trx_id=30）
3. 判断：trx_id=30 在 ReadView 之后 → 不可见
4. 顺着 db_roll_ptr 找上一个版本（trx_id=20）
5. 判断：trx_id=20 在活跃列表中 → 仍不可见
6. 继续找（trx_id=10）
7. 判断：trx_id=10 < minTrxId(20) → 可见 ✅
8. 返回 balance=100（旧版本的值）
```

**这就是「快照读」的本质**：读到的是「**最近已提交**事务修改的版本」，而不是最新数据。

---

### Read View 的生成时机：RR vs RC

| 隔离级别 | Read View 生成时机 | 效果 |
|----------|------------------|------|
| **RC（Read Committed）** | **每次 SELECT** 都生成新的 Read View | 每次读都能看到已提交的最新数据 |
| **RR（Repeatable Read）** | **事务开始时**生成一个 Read View，**整个事务复用** | 整个事务看到的数据版本固定 |

**RC 的问题（不可重复读）**：

```sql
-- 事务A（RC）
SELECT balance FROM account WHERE id=1;  -- 第一次读到 100（ReadView1）
                                              -- 此时事务B提交，balance=200
SELECT balance FROM account WHERE id=1;  -- 第二次读到 200（ReadView2，新快照）❌
-- 同一事务内，两次读结果不一样
```

**RR 的解决**：

```sql
-- 事务A（RR）
BEGIN;
SELECT balance FROM account WHERE id=1;  -- 生成 ReadView，整个事务用它
                                              -- 事务B提交，但ReadView不变
SELECT balance FROM account WHERE id=1;  -- 仍读到 100 ✅（可重复读）
COMMIT;
```

---

## 它和相似方案的本质区别是什么？

### MVCC + 锁 vs 仅用锁

| 方案 | 读操作 | 写操作 | 并发度 |
|------|--------|--------|--------|
| 仅用锁 | 加读锁（阻塞写） | 加写锁（阻塞读写） | 低 |
| MVCC | 不加锁，读快照 | 写时加锁 + 创建新版本 | 高 |

**MVCC 的代价**：需要维护多版本数据（undo log 链），占用更多存储空间。  
但换来的是**读完全不阻塞写，写完全不阻塞读**。

---

### 快照读 vs 当前读

| 类型 | SQL 示例 | 读什么 |
|------|---------|--------|
| **快照读** | `SELECT ...` | 读 ReadView 可见的版本（可能是旧数据） |
| **当前读** | `SELECT ... LOCK IN SHARE MODE` | 读取最新已提交数据 + 加锁 |
| **当前读** | `SELECT ... FOR UPDATE` | 读取最新已提交数据 + 排他锁 |
| **当前读** | `INSERT/UPDATE/DELETE` | 当前读（加 X 锁） |

**当前读为什么不能 MVCC？**

> 当前读是为了**检测锁冲突**或**保证最新数据**。  
> 如果当前读用 MVCC，可能会读到「正在被其他事务修改但未提交」的脏数据。

**一个重要误解**：

```sql
-- 这条 SELECT 是不是快照读？
SELECT * FROM account WHERE id = 1 FOR UPDATE;
-- ❌ 不是！加了 FOR UPDATE，是当前读（加排他锁）
-- ✅ 只有普通 SELECT 才是快照读
```

---

## 正确使用方式

### 1. 理解 MVCC 在实际开发中的作用

MVCC 对你来说是透明的——InnoDB 自动处理。  
但你需要知道**哪些 SQL 会触发当前读**：

```sql
-- 快照读（MVCC）
SELECT * FROM orders WHERE user_id = 100;          -- 普通 SELECT
SELECT * FROM orders WHERE user_id = 100 LOCK IN SHARE MODE;  -- 加共享锁（仍是快照读）

-- 当前读（需要最新数据）
SELECT * FROM orders WHERE id = 1 FOR UPDATE;  -- 排他锁
INSERT INTO orders (...) VALUES (...);           -- 写，加 X 锁
UPDATE orders SET status = 'paid' WHERE id = 1; -- 写，加 X 锁
DELETE FROM orders WHERE id = 1;                 -- 写，加 X 锁
```

---

### 2. 正确理解 RR 下的「幻读」

**RR 级别下，快照读不会幻读，但当前读会幻读**：

```sql
-- 事务A（RR）
BEGIN;

-- 快照读：不幻读
SELECT * FROM orders WHERE user_id = 100;  -- 读到 3 条
                                              -- 事务B插入了 1 条
SELECT * FROM orders WHERE user_id = 100;  -- 仍读到 3 条（ReadView 不变）

-- 当前读：幻读！
SELECT * FROM orders WHERE user_id = 100 FOR UPDATE;  -- 读到 4 条 ❌
COMMIT;
```

**为什么 `SELECT FOR UPDATE` 产生幻读？**

> `FOR UPDATE` 是当前读，需要对扫描到的行加锁。  
> 扫描过程中，其他事务插入了新行 → 新行也满足 `WHERE` 条件 → 也被锁定 → 返回结果包含新行。

**解决幻读**：RR + `Next-Key Lock`（记录锁 + 间隙锁）

```sql
SELECT * FROM orders WHERE user_id = 100 FOR UPDATE;
-- InnoDB 会锁定 user_id=100 的所有行 + 相邻的间隙
-- 防止其他事务在间隙中插入新数据 → 解决幻读
```

---

## 边界情况和坑

### 1. 长事务导致 undo log 膨胀

```sql
-- ❌ 危险：开启长事务
BEGIN;
-- 业务处理（耗时 1 小时）
SELECT * FROM orders WHERE ...;  -- 每次都生成 ReadView（RC）或复用 ReadView（RR）
-- 这 1 小时内，事务B对同一行的大量修改，
-- 都会生成 undo log 版本链，
-- 但长事务不提交，这些 undo log 无法被 purge 清理！
-- → undo log 膨胀 → 存储空间暴涨
```

**解决**：

```sql
-- 生产环境：设置事务超时
SET innodb_lock_wait_timeout = 30;  -- 锁等待超时
SET SESSION MAX_EXECUTION_TIME = 5000;  -- 查询超时（MySQL 8.0+）

-- 监控长事务
SELECT * FROM information_schema.INNODB_TRX
WHERE trx_started < NOW() - INTERVAL 1 HOUR;
```

---

### 2. MVCC 不解决所有并发问题

```sql
-- ❌ MVCC 对「当前读」的写冲突无能为力

事务A：                      事务B：
SELECT balance               SELECT balance
FROM account                 FROM account
WHERE id=1;                 WHERE id=1;
-- 都读到 100                   都读到 100

UPDATE account               UPDATE account
SET balance = balance - 50   SET balance = balance - 30
WHERE id=1;                  WHERE id=1;
-- balance = 100-50 = 50       -- balance = 100-30 = 70 ❌
-- 丢失了事务A的更新！
```

**MVCC 只解决「读写不阻塞」，不解决「写写冲突」**。  
写写冲突靠**行锁（排他锁）**解决。

---

### 3. RR 下 first-read-then-update 的陷阱

```sql
-- ❌ RR 下容易写出「先读后写」的并发问题
BEGIN;
SELECT balance FROM account WHERE id=1;  -- 读到 100（快照）
if (balance >= 100) {
    UPDATE account SET balance = balance - 100;  -- 余额扣减
}
COMMIT;

-- 事务A 和 事务B 同时读到 balance=100
-- 都通过了 if 判断
-- 都执行了扣款 → 余额可能变成负数（或者少扣了一次）
```

**解决**：用 `SELECT ... FOR UPDATE` 当前读（获取排他锁），或者乐观锁版本号。

---

### 4. Read View 的创建开销

```sql
-- RC 下，每次普通 SELECT 都创建 Read View
-- 高并发短查询场景，Read View 创建开销不可忽视

-- MySQL 8.0.3+ 默认 RC 隔离级别（之前默认 RR）
-- 如果你的应用不需要 RC 的「最新已提交」语义，
-- 切换到 RR 可以减少 Read View 创建次数（事务内只创建一次）
```

---

## 我的理解

MVCC 的本质是**「读不阻塞写，写不阻塞读」**——通过保存数据的多个版本，让读操作始终能拿到一个「一致性快照」，而不需要等待写锁释放。

**核心三要素**：
1. **隐藏列**（`db_trx_id` + `db_roll_ptr`）→ 构成版本链
2. **undo log** → 保存历史版本数据
3. **Read View** → 判断「当前事务能看到哪个版本」

**面试追问高发区**：
1. Read View 的可见性判断（四个条件）
2. RR 和 RC 的区别（Read View 生成时机不同）
3. 当前读 vs 快照读的区别
4. 为什么 UPDATE 会创建新版本（undo log 链的原理）
5. MVCC 能否完全解决幻读（RR 下当前读仍有幻读问题）

---
