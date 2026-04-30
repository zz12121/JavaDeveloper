# InnoDB锁机制

## 这个问题为什么存在？

> 两个事务同时修改同一行数据，结果会怎样？

```sql
-- 场景：并发扣减库存
-- 库存=1，两个用户同时下单

-- T1
START TRANSACTION;
SELECT stock FROM products WHERE id = 1;  -- 读到 stock=1
-- 准备扣减：stock = stock - 1

-- T2（在T1提交前执行）
START TRANSACTION;
SELECT stock FROM products WHERE id = 1;  -- 也读到 stock=1
UPDATE products SET stock = stock - 1 WHERE id = 1;
COMMIT;

-- T1（继续执行）
UPDATE products SET stock = stock - 1 WHERE id = 1;
COMMIT;
-- 结果：stock = -1（超卖！）
```

**锁就是为了防止这种并发问题**。通过"互斥"机制，保证同一时刻只有一个事务能修改某行数据。

---

## 它是怎么解决问题的？

### 锁的分类体系

```
InnoDB锁分类
├── 按粒度分
│   ├── 表级锁（MyISAM常用，InnoDB很少用）
│   └── 行级锁（InnoDB核心，支持高并发）
├── 按功能分
│   ├── 共享锁（S锁，读锁）
│   └── 排他锁（X锁，写锁）
└── 按算法分（行锁的三种实现）
    ├── 记录锁（Record Lock）：锁住索引记录
    ├── 间隙锁（Gap Lock）：锁住索引记录之间的间隙
    └── 临键锁（Next-Key Lock）= Record Lock + Gap Lock
```

### 共享锁（S锁）vs 排他锁（X锁）

| 锁类型 | 作用 | 加锁方式 | 兼容性 |
|--------|------|---------|--------|
| **共享锁（S锁）** | 读锁，其他事务可以再加S锁，但不能加X锁 | `SELECT...LOCK IN SHARE MODE` | 兼容S锁，不兼容X锁 |
| **排他锁（X锁）** | 写锁，其他事务不能加任何锁 | `SELECT...FOR UPDATE`、INSERT、UPDATE、DELETE | 不兼容任何锁 |

**兼容性矩阵**：

```
        |  S锁  |  X锁
--------|-------|-------
S锁     |  兼容  |  冲突
X锁     |  冲突  |  冲突
```

```sql
-- T1：加排他锁
START TRANSACTION;
SELECT * FROM users WHERE id = 1 FOR UPDATE;

-- T2：尝试加锁
SELECT * FROM users WHERE id = 1 LOCK IN SHARE MODE;  -- 阻塞，等待T1释放锁
SELECT * FROM users WHERE id = 1 FOR UPDATE;            -- 阻塞，等待T1释放锁
SELECT * FROM users WHERE id = 1;                      -- 快照读，不加锁，立即返回
```

### 意向锁（Intention Locks）

**问题**：表级锁和行级锁如何共存？

```sql
-- T1：对某一行加行级排他锁
START TRANSACTION;
SELECT * FROM users WHERE id = 1 FOR UPDATE;  -- 行级X锁

-- T2：想对整个表加表级共享锁
LOCK TABLES users READ;  -- 需要检查表中每一行是否有冲突的锁 → 效率低
```

**解决**：意向锁（表级锁的"标记"）

```
意向锁是表级锁，用于"标记"表中是否有行级锁。

两种意向锁：
- IS（Intention Shared）：事务打算对表中的某些行加S锁
- IX（Intention Exclusive）：事务打算对表中的某些行加X锁

加行级S锁前，必须先加表级IS锁
加行级X锁前，必须先加表级IX锁
```

**兼容性矩阵（加入意向锁）**：

```
          IS      IX      S       X
IS       兼容    兼容    兼容    冲突
IX       兼容    兼容    冲突    冲突
S        兼容    冲突    兼容    冲突
X        冲突    冲突    冲突    冲突
```

**关键点**：
- 意向锁是InnoDB**自动加的**，不需要用户干预
- 意向锁的目的是**提高表级锁的检查效率**（不需要逐行检查，只看表级意向锁）

### 行锁的三种算法

这是InnoDB锁机制最核心的部分。

#### 1. 记录锁（Record Lock）

```
锁住索引记录本身。

示例：
索引值：1, 5, 10, 15, 20

Record Lock on 10 → 只锁住值=10的这一行
```

```sql
START TRANSACTION;
-- 对id=10这一行加记录锁
UPDATE users SET name = 'Tom' WHERE id = 10;
-- 其他事务不能修改id=10这行，但可以修改其他行
```

#### 2. 间隙锁（Gap Lock）

```
锁住索引记录之间的"间隙"，防止其他事务在这个间隙插入数据。

示例：
索引值：1, 5, 10, 15, 20

Gap Lock on (5, 10) → 锁住5和10之间的间隙
                        → 不能插入值=6,7,8,9的行
```

```sql
START TRANSACTION;
-- REPEATABLE READ级别下，范围查询会加Gap锁
SELECT * FROM users WHERE id > 5 AND id < 10 FOR UPDATE;
-- 锁住(5, 10)这个间隙
-- 其他事务不能插入id=6,7,8,9的行 → 防止幻读
```

**Gap锁只在REPEATABLE READ及以上级别生效**。READ COMMITTED级别下，InnoDB不加Gap锁（除了外键和唯一性检查）。

#### 3. 临键锁（Next-Key Lock）= Record Lock + Gap Lock

```
InnoDB的默认行锁算法（RR级别下）。

Next-Key Lock锁住：索引记录本身 + 该记录之前的间隙。

示例：
索引值：1, 5, 10, 15, 20

Next-Key Lock on 10 → 锁住(5, 10]（间隙+记录本身）
```

**为什么叫"临键锁"？**
- 锁住当前键（Record Lock）
- 锁住当前键之前的间隙（Gap Lock）

```sql
-- 索引值：1, 5, 10, 15, 20
START TRANSACTION;
-- 查询id<12的行，会加Next-Key Lock
SELECT * FROM users WHERE id < 12 FOR UPDATE;
-- 锁住：(-∞, 1], (1, 5], (5, 10], (10, 15]
-- 注意：15不在结果集中，但(10, 15]被锁住了

-- 其他事务不能插入id=11, 12, 13, 14的行 → 防止幻读
```

**Next-Key Lock是InnoDB在RR级别防止幻读的关键**。

### 加锁规则总结

| SQL | 索引类型 | 隔离级别 | 加锁方式 |
|-----|---------|---------|---------|
| `SELECT...FROM`（普通查询） | 任意 | 任意 | 不加锁（快照读） |
| `SELECT...FOR UPDATE` | 主键/唯一索引+等值查询 | RC/RR | Record Lock |
| `SELECT...FOR UPDATE` | 主键/唯一索引+范围查询 | RR | Next-Key Lock |
| `SELECT...FOR UPDATE` | 非唯一索引 | RR | Next-Key Lock + Gap Lock |
| `SELECT...FOR UPDATE` | 无索引 | RR | 锁全表（所有行+间隙） |
| `UPDATE`/`DELETE` | 主键/唯一索引 | RC/RR | Record Lock |
| `UPDATE`/`DELETE` | 非唯一索引 | RR | Next-Key Lock |
| `INSERT` | 任意 | RC/RR | Record Lock（插入的行） |

---

## 它和相似方案的本质区别是什么？

### InnoDB行锁 vs MyISAM表锁

| 维度 | InnoDB（行锁） | MyISAM（表锁） |
|------|----------------|----------------|
| 锁粒度 | 行级（只锁相关行） | 表级（锁整张表） |
| 并发性能 | 高（不同行互不干扰） | 低（任何写操作锁整表） |
| 死锁 | 可能（需要死锁检测） | 不可能（表级锁，顺序加锁） |
| 适用场景 | OLTP（高并发写入） | OLAP（少量写入、大量查询） |

**本质区别**：InnoDB支持行级锁，并发性能远高于MyISAM。这也是为什么InnoDB成为MySQL默认存储引擎。

### Record Lock vs Gap Lock vs Next-Key Lock

| 锁类型 | 锁住范围 | 目的 | 适用场景 |
|--------|---------|------|---------|
| Record Lock | 索引记录本身 | 防止别的事务修改这行 | 等值查询（唯一索引） |
| Gap Lock | 索引记录之间的间隙 | 防止别的事务在间隙插入（防止幻读） | 范围查询（RR级别） |
| Next-Key Lock | 间隙+记录本身 | Record Lock + Gap Lock | InnoDB默认行锁算法（RR级别） |

**为什么需要三种锁？**
- 等值查询只需要Record Lock（锁住已存在的行即可）
- 范围查询需要Gap Lock（防止别的事务插入新行，导致幻读）
- Next-Key Lock是RR级别下的默认算法，同时解决"修改已有行"和"防止插入新行"两个问题

---

## 正确使用方式

### 1. 避免锁全表（索引的重要性）

```sql
-- ❌ 危险：没有索引，锁全表
START TRANSACTION;
UPDATE users SET status = 2 WHERE name = 'Tom';
-- name字段没有索引 → InnoDB需要全表扫描 → 锁住所有行和间隙
-- 其他事务任何写入都会被阻塞！

-- ✅ 正确：给name字段加索引
CREATE INDEX idx_name ON users(name);
START TRANSACTION;
UPDATE users SET status = 2 WHERE name = 'Tom';
-- 只锁住name='Tom'的行 → 其他行不受影响
```

**经验规则**：
- 所有WHERE条件中的字段，尽量有索引
- 没有索引的UPDATE/DELETE会锁全表，并发性能极差

### 2. 控制锁的持有时间

```sql
-- ❌ 错误：在事务中做无关操作，延长锁持有时间
START TRANSACTION;
SELECT * FROM orders WHERE id = 1 FOR UPDATE;  -- 加锁
-- 做一些复杂的业务计算（10秒）
UPDATE orders SET status = 2 WHERE id = 1;
COMMIT;  -- 10秒后才释放锁

-- ✅ 正确：事务尽量短
-- 先做完业务计算
-- 再开启事务，快速加锁→修改→提交
START TRANSACTION;
SELECT * FROM orders WHERE id = 1 FOR UPDATE;
UPDATE orders SET status = 2 WHERE id = 1;
COMMIT;  -- 锁持有时间极短
```

### 3. 查看锁等待情况

```sql
-- 查看当前锁等待
SELECT * FROM performance_schema.data_locks;
SELECT * FROM performance_schema.data_lock_waits;

-- 查看InnoDB状态（包含最近的死锁信息）
SHOW ENGINE INNODB STATUS;

-- 查看事务和锁
SELECT * FROM information_schema.innodb_trx;
SELECT * FROM information_schema.innodb_locks;  -- MySQL 8.0前
```

---

## 边界情况和坑

### 坑1：死锁（Deadlock）

**什么是死锁？**

```
T1：持有资源A，等待资源B
T2：持有资源B，等待资源A
→ 相互等待，永远无法继续执行
```

**示例**：

```sql
-- 索引值：1, 2

-- T1
START TRANSACTION;
UPDATE t SET name = 'A' WHERE id = 1;  -- 持有id=1的X锁

-- T2
START TRANSACTION;
UPDATE t SET name = 'B' WHERE id = 2;  -- 持有id=2的X锁

-- T1（继续执行）
UPDATE t SET name = 'C' WHERE id = 2;  -- 等待T2释放id=2的X锁

-- T2（继续执行）
UPDATE t SET name = 'D' WHERE id = 1;  -- 等待T1释放id=1的X锁
--> 死锁！
```

**InnoDB的死锁检测**：
- InnoDB会检测死锁，并**回滚一个事务**（通常是持有最少行锁的事务）
- 错误信息：`Deadlock found when trying to get lock; try restarting transaction`

**避免死锁的方法**：
1. **以固定顺序访问资源**：所有事务都先访问id=1，再访问id=2
2. **缩小事务范围**：事务越短，持有锁的时间越短，死锁概率越低
3. **使用低隔离级别**：RC级别不加Gap锁，减少锁范围
4. **设置锁等待超时**：`innodb_lock_wait_timeout`（默认50秒）

```sql
-- 以固定顺序访问（避免死锁）
-- T1和T2都先锁id=1，再锁id=2 → 不会死锁
START TRANSACTION;
SELECT * FROM t WHERE id = 1 FOR UPDATE;
SELECT * FROM t WHERE id = 2 FOR UPDATE;
-- do something
COMMIT;
```

### 坑2：RC级别下的幻读

```sql
-- READ COMMITTED级别

-- T1
START TRANSACTION;
SELECT * FROM users WHERE age > 20;  -- 读到5行（快照读）

-- T2
START TRANSACTION;
INSERT INTO users VALUES (NULL, 25, 'Tom');
COMMIT;

-- T1
SELECT * FROM users WHERE age > 20 FOR UPDATE;  -- 读到6行（当前读，幻读！）
COMMIT;
```

**RC级别下，Gap锁不生效，无法防止幻读**。如果需要防止幻读，用RR级别。

### 坑3：无索引导致锁全表

```sql
-- users表的name字段没有索引

START TRANSACTION;
UPDATE users SET status = 2 WHERE name = 'Tom';  -- 锁全表！
-- 其他任何写入都会被阻塞
```

**排查方法**：
```sql
-- 查看执行计划，确认是否走了索引
EXPLAIN UPDATE users SET status = 2 WHERE name = 'Tom';
-- type=ALL → 全表扫描 → 锁全表
-- type=ref/range → 索引扫描 → 只锁相关行
```

### 坑4：Gap锁导致的"莫名阻塞"

```sql
-- RR级别

-- T1
START TRANSACTION;
SELECT * FROM users WHERE id > 5 AND id < 10 FOR UPDATE;
-- 锁住了(5, 10)这个间隙

-- T2（阻塞！）
INSERT INTO users VALUES (8, 25, 'Tom');
-- 被T1的Gap锁阻塞，即使id=8这行原本不存在！
```

**理解**：Gap锁锁住的是"间隙"，不只是"已存在的行"。这是防止幻读的必要手段。

---

## 我的理解

InnoDB的锁机制是"悲观锁"的实现——假设会发生并发冲突，提前加锁保护。

**锁的设计哲学**：

```
粒度越细 → 并发性能越高 → 实现越复杂
- 表锁：粒度粗，并发低，实现简单
- 行锁：粒度细，并发高，实现复杂
- 间隙锁：防止幻读，但增加了锁冲突概率
```

**记忆技巧**：
- **S锁**（Shared）：共享锁，读锁，不互斥
- **X锁**（eXclusive）：排他锁，写锁，全互斥
- **IS/IX锁**：意向锁，表级"标记"，提高加表锁的效率
- **Record Lock**：锁住已存在的行
- **Gap Lock**：锁住行之间的空隙，防止插入
- **Next-Key Lock**：Record + Gap，InnoDB默认算法

**最重要的实践教训**：
1. **一定要有索引**：无索引=锁全表，并发性能极差
2. **事务要短**：减少锁持有时间，降低死锁概率
3. **固定顺序访问资源**：避免死锁
4. **根据需求选择隔离级别**：RC（高并发）vs RR（防幻读）

---

## 面试话术

**Q：InnoDB有哪些类型的锁？**

"InnoDB的锁可以分为几个层次：

**按粒度分**：表级锁和行级锁。InnoDB主要使用行级锁，表级锁主要用于意向锁（IS/IX）和DDL操作。

**按功能分**：共享锁（S锁）和排他锁（X锁）。S锁之间兼容，S锁和X锁互斥，X锁之间互斥。

**按算法分（行锁的实现）**：
- Record Lock：锁住索引记录本身
- Gap Lock：锁住索引记录之间的间隙，防止别的事务插入
- Next-Key Lock：Record Lock + Gap Lock，是InnoDB在RR级别下的默认行锁算法

面试追问：'Next-Key Lock是怎么防止幻读的？'
回答：'Next-Key Lock不仅锁住已存在的行（Record Lock部分），还锁住行之间的间隙（Gap Lock部分）。当执行范围查询并加锁时，别的事务无法在这些间隙插入新行，从而避免了幻读。'"

**Q：什么是死锁？怎么避免？**

"死锁是指两个或多个事务相互等待对方持有的锁，导致所有事务都无法继续执行。

InnoDB会自动检测死锁，并回滚一个事务（通常是持有最少行锁的那个），让其他事务继续执行。

避免死锁的方法：
1. **以固定顺序访问资源**：所有事务都按照相同的顺序加锁，不会产生循环等待
2. **缩小事务范围**：事务越短，持有锁的时间越短，死锁概率越低
3. **使用低隔离级别**：RC级别不加Gap锁，锁的范围更小
4. **设置锁等待超时**：`innodb_lock_wait_timeout`，超过时间自动回滚"

**Q：为什么RR级别能防止幻读，RC级别不能？**

"因为RR级别下，InnoDB加Gap锁（间隙锁），锁住索引记录之间的空隙，防止别的事务在这些空隙插入新行。

RC级别下，InnoDB不加Gap锁（除了外键和唯一性检查），所以别的事务可以在范围查询的间隙插入新行，导致幻读。

这也是为什么RR级别的并发性能比RC略低——Gap锁增加了锁冲突的概率。"

---

## 本文总结

| 锁类型 | 锁住范围 | 目的 | 适用场景 |
|--------|---------|------|---------|
| 共享锁（S锁） | 读锁 | 允许并发读，阻塞写 | `SELECT...LOCK IN SHARE MODE` |
| 排他锁（X锁） | 写锁 | 阻塞所有读写 | `SELECT...FOR UPDATE`、写操作 |
| 意向锁（IS/IX） | 表级"标记" | 提高表锁检查效率 | InnoDB自动加，无需干预 |
| 记录锁（Record） | 索引记录本身 | 防止别的事务修改这行 | 等值查询（唯一索引） |
| 间隙锁（Gap） | 索引记录之间的间隙 | 防止别的事务插入（防幻读） | 范围查询（RR级别） |
| 临键锁（Next-Key） | 间隙+记录本身 | Record+Gap，防幻读 | InnoDB默认行锁算法（RR级别） |

**核心要点**：
1. InnoDB支持行级锁，并发性能远高于MyISAM
2. RR级别下，Next-Key Lock防止幻读
3. 无索引的UPDATE/DELETE会锁全表
4. 避免死锁：固定顺序访问资源、缩小事务范围
5. 查看锁等待：`performance_schema.data_locks`
