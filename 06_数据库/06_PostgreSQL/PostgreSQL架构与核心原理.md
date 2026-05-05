# PostgreSQL 架构与核心原理

## 这个问题为什么存在？

如果你已经学过 MySQL（InnoDB），会发现 PostgreSQL 的架构设计理念有很大不同：

```
MySQL（InnoDB）：
  线程模型：一个线程处理一个连接
  存储引擎：插件式，InnoDB 是默认引擎
  物理存储：表空间（.idb 文件）
  日志：Redo Log（物理日志）+ Undo Log（回滚）

PostgreSQL：
  进程模型：一个进程处理一个连接（no shared memory for connections）
  存储：堆表（Heap）+ 索引独立存储
  日志：WAL（Write-Ahead Logging，类似 Redo Log，但是物理+逻辑混合）
  VACUUM：需要主动清理旧版本数据（类似 Undo，但是需要手动/自动清理）
```

**核心问题**：PostgreSQL 为什么用进程模型？为什么需要 VACUUM？它的存储引擎是怎么工作的？

理解 PostgreSQL 架构，才能真正用好它——特别是 **JSONB 查询优化、并发控制、VACUUM 调优** 这些 MySQL 里没有的概念。

---

## 它是怎么解决问题的？

### 一、进程模型（Process per Connection）

```
PostgreSQL 进程结构：

  postgres (主进程)
    ├── postgres (后台进程：BgWriter，负责脏页刷盘)
    ├── postgres (后台进程：Checkpointer，负责 checkpoint)
    ├── postgres (后台进程：WAL Writer，负责 WAL 刷盘)
    ├── postgres (后台进程：AutoVacuum，自动清理死元组)
    ├── postgres (后台进程：Stats Collector，统计信息收集)
    │
    ├── postgres (用户进程 1：处理连接 1 的查询)   ← 每个连接一个进程
    ├── postgres (用户进程 2：处理连接 2 的查询)
    └── postgres (用户进程 N：处理连接 N 的查询)
```

**为什么用进程，不用线程？**

| 维度 | 进程模型（PG） | 线程模型（MySQL） |
|------|----------------|-------------------|
| 稳定性 | 高（一个连接 Crash 不影响其他连接） | 中（一个线程 Crash 可能导致整个进程崩溃） |
| 并发能力 | 受 OS 进程数限制（通常 < 1000） | 高（线程更轻量，可支持上万连接） |
| 内存开销 | 大（每个进程独立内存空间） | 小（线程共享内存） |
| 利用多核 | 好（进程间天然并行） | 好（需要小心处理锁） |

**PostgreSQL 的解决方案：连接池**

因为进程模型并发连接数有限，生产环境必须用连接池：
- **PgBouncer**：轻量级连接池（推荐，支持 transaction pooling 模式）
- **Pgpool-II**：功能更强（负载均衡 + 连接池 + 复制）
- **内置连接池**（PG 14+）：性能还不够强，生产仍推荐 PgBouncer

```ini
# pgbouncer.ini 配置示例
[databases]
mydb = host=127.0.0.1 port=5432 dbname=mydb

[pgbouncer]
pool_mode = transaction    # 事务级连接池（最省连接）
max_client_conn = 1000    # 客户端最大连接数
default_pool_size = 25     # 每个后端数据库的连接池大小
```

### 二、内存架构

```
PostgreSQL 内存结构：

┌───────────────────────────────────────────────────────┐
│                  进程私有内存                           │
│  (每个连接进程独立)                                    │
│  ┌──────────┐  ┌──────────┐  ┌──────────────────┐  │
│  │ work_mem  │  │ temp_buffers│  │ maintenance_work_mem │  │
│  │(排序/哈希) │  │ (临时表)    │  │ (VACUUM/CREATE INDEX)│  │
│  └──────────┘  └──────────┘  └──────────────────┘  │
├───────────────────────────────────────────────────────┤
│                 共享内存（Shared Memory）                │
│  ┌──────────────────────────────────────────────┐     │
│  │  Shared Buffer（共享缓冲池，类似 InnoDB Buffer Pool） │
│  │  WAL Buffer（WAL 缓冲区，类似 Redo Log Buffer）    │
│  │  CLOG Buffer（事务状态日志缓冲）                   │
│  └──────────────────────────────────────────────┘     │
└───────────────────────────────────────────────────────┘
```

#### 关键参数

```postgresql.conf
# 共享内存（最关键）
shared_buffers = 4GB          # 推荐：物理内存的 25%~40%

# WAL 相关
wal_buffers = 16MB            # WAL 缓冲区，默认 -1（自动 = shared_buffers 的 1/32）

# 进程私有内存
work_mem = 64MB               # 每个操作（排序/哈希）的内存，注意：并发操作会翻倍！
maintenance_work_mem = 512MB  # VACUUM / CREATE INDEX 的内存

# 连接数
max_connections = 100         # 配合连接池使用，不要设太大（进程模型限制）
```

**为什么 work_mem 要小心设置？**

```
假设：work_mem = 64MB，max_connections = 100
      每个连接可能有 3 个并发排序操作
      → 峰值内存 = 100 × 3 × 64MB = 19.2GB ！

建议：
  - 用连接池限制并发连接数（如 PgBouncer 限制为 20）
  - work_mem 设小一点（如 16MB），让临时文件落地而不是 OOM
```

### 三、物理存储：堆表（Heap）与 TOAST

#### 堆表结构

PostgreSQL 用 **堆表（Heap）** 存储数据，和 MySQL 的 **索引组织表（IOT）** 不同。

```
MySQL InnoDB（索引组织表）：
  主键索引的叶子节点 = 数据行
  二级索引的叶子节点 = 主键值 → 需要回表

PostgreSQL（堆表）：
  数据存在堆表里（Heap File），每个行有一个 ctid（块号 + 行号）
  索引的叶子节点 = ctid（指向堆表的行位置）
  → 所有索引都是"二级索引"，都需要"回堆"（index-only scan 除外）
```

```
PostgreSQL 表的物理文件：
  $PGDATA/base/<database_oid>/<relfile_node>.0
  $PGDATA/base/<database_oid>/<relfile_node>.1
  ...

  每个表至少有一个文件，文件超过 1GB 会自动分裂（.0, .1, .2...）
  （这个值和 MySQL 的 96GB 一个表空间文件不同）
```

#### TOAST（The Oversized-Attribute Storage Technique）

PostgreSQL 的页面（Page）大小和 MySQL 一样是 **8KB**，但行不能跨页面存储。

**问题**：如果一个 `VARCHAR(10000)` 或 `JSONB` 字段很大，一行超过 8KB 怎么办？

**TOAST 机制**：
```
1. 检测：行超过 ~2KB（TOAST_TUPLE_THRESHOLD），触发 TOAST
2. 压缩：先尝试压缩字段（用 LZ4 或 PGLZ）
3. 行外存储：压缩后还太大，把字段值存到专门的 TOAST 表（行外存储）
4. 主表行里只存一个指针（18 字节）指向 TOAST 表
```

```sql
-- 查看表的 TOAST 表
SELECT relname, reltoastrelid FROM pg_class WHERE relname = 'my_table';
-- reltoastrelid ≠ 0 表示有 TOAST 表

-- TOAST 策略（每个字段可以单独设置）
CREATE TABLE example (
    id    int,
    content TEXT      TOAST,  -- 默认：先压缩，压缩不了就行外存储
    short  TEXT      TOAST (STORAGE = MAIN),  -- 尽量行内存储，不行就压缩
    data   JSONB     TOAST (STORAGE = EXTERNAL)  -- 不压缩，直接行外存储（支持部分读取）
);
```

**为什么 JSONB 查询快？** JSONB 存储时做了二进制优化，支持 GIN 索引，且 TOAST 策略可以让大 JSONB 不压缩（EXTERNAL），支持部分读取。

### 四、WAL（Write-Ahead Logging）

WAL 是 PostgreSQL 的 **预写日志**（类似 MySQL 的 Redo Log），保证**持久性（Durability）**。

```
WAL 的核心原理（和 Redo Log 一样）：
  1. 修改数据前，先写 WAL（顺序写，快）
  2. 提交事务时，确保 WAL 刷盘（fsync）
  3. 数据页（Shared Buffer）可以异步刷盘（由BgWriter/Checkpointer 负责）
  → 崩溃恢复时，重放 WAL 就能恢复到崩溃前状态
```

#### WAL 和 Redo Log 的关键区别

| 维度 | PostgreSQL WAL | MySQL Redo Log |
|------|-----------------|----------------|
| 日志类型 | 物理+逻辑混合 | 纯物理日志（数据页修改） |
| 复制方式 | 物理复制（WAL 流复制） | 逻辑复制（ binlog）或物理复制（Clone Plugin） |
| 归档 | 原生支持（archive_command） | 需要外部工具（mysqlbinlog） |
| 表空间 | 每个数据库有独立的 WAL 流 | 全局共享 binlog |

#### WAL 配置

```postgresql.conf
# WAL 刷盘策略（关键！）
fsync = on                    # 必须 = on，否则可能丢数据
synchronous_commit = on       # on = 提交时等 WAL 刷盘（最安全，稍慢）
                               # off = 延迟刷盘（快，但 Crash 可能丢最近 1 个事务）
                               # local = 只等本地刷盘（同步复制时有用）

# WAL 文件管理
wal_level = replica           # replica = 支持复制和备份（推荐）
                               # minimal = 只写崩溃恢复需要的日志（不支持复制）
min_wal_size = 1GB
max_wal_size = 4GB           # WAL 文件自动回收阈值
```

### 五、Checkpoint（检查点）

Checkpoint 是 PostgreSQL 的 **脏页刷盘机制**（类似 MySQL 的 "刷脏页"）。

```
Checkpoint 流程：
  1. 将 Shared Buffer 里所有脏页写到磁盘
  2. 写一个 Checkpoint 记录到 WAL
  3. 更新 pg_control 文件（记录最新 Checkpoint 的 WAL 位置）
  4. 旧的 WAL 文件可以被回收（如果不再需要用于崩溃恢复）

崩溃恢复时：
  1. 从最后一次 Checkpoint 的位置开始
  2. 重放 WAL（Redo）
  → Checkpoint 越频繁，崩溃恢复越快（但要写的脏页越多，写入放大）
```

#### Checkpoint 调优

```postgresql.conf
checkpoint_timeout = 15min    # Checkpoint 间隔（默认 5min，建议 15min）
max_wal_size = 4GB           # WAL 增长超过此值，强制 Checkpoint
checkpoint_completion_target = 0.9  # Checkpoint 刷盘速度（0.9 = 用 90% 的 timeout 时间慢慢刷）
```

**为什么 checkpoint_completion_target 要设 0.9？**

```
Checkpoint 刷盘时会产生大量 IO，如果刷太快，会和正常查询抢 IO，导致查询变慢。

checkpoint_completion_target = 0.9 表示：
  用 90% 的 checkpoint_timeout 时间来刷盘 → IO 更平滑，查询不受影响
  代价：崩溃恢复时可能要多重放一点 WAL
```

---

## 它和相似方案的本质区别是什么？

### PostgreSQL vs MySQL（架构层面）

| 维度 | PostgreSQL | MySQL（InnoDB） |
|------|------------|----------------|
| 连接模型 | 进程（稳定，但并发有限） | 线程（轻量，支持高并发） |
| 存储模型 | 堆表（索引指向 ctid） | 索引组织表（主键索引=数据） |
| 事务状态 | 在堆表行里（xmin/xmax） | 在 Undo Log 里（历史版本链） |
| 旧版本清理 | VACUUM（需要主动清理） | 自动（Undo Log 被覆盖/清理） |
| WAL/Redo | WAL（物理+逻辑） | Redo Log（物理） |
| 复制 | 物理复制（WAL 流复制） | binlog 逻辑复制（或 MGR 组复制） |
| 主从延迟 | 低（物理复制，并行回放） | 可能高（单线程回放，MySQL 5.7+ 支持并行复制） |

**本质区别**：

1. **MySQL 是"为 Web 应用设计的"**：线程模型、连接池简单、主从复制成熟
2. **PostgreSQL 是"为复杂查询和数据分析设计的"**：进程模型稳定、堆表适合多种索引、MVCC 实现更精细（xmin/xmax）

---

## 正确使用方式

### 正确用法

**1. 生产环境必须用连接池（PgBouncer）**

```ini
# pgbouncer.ini
[pgbouncer]
pool_mode = transaction      # 事务级连接池（最省连接）
max_client_conn = 1000      # 前端最大连接数
default_pool_size = 25      # 后端连接池大小（根据 CPU 核数调整）
server_reset_query = DISCARD ALL  # 连接复用时清理会话状态
```

**为什么正确**：PostgreSQL 进程模型，每个连接 = 一个进程，1000 个连接 = 1000 个进程，内存和上下文切换开销巨大。连接池把 1000 个前端连接复用成 25 个后端连接。

**2. shared_buffers 设为物理内存的 25%~40%**

```postgresql.conf
# 物理内存 16GB 的服务器
shared_buffers = 4GB        # 25%
effective_cache_size = 12GB  # 告诉优化器：OS 页面缓存 + Shared Buffer 总共能缓存多少数据
```

**为什么正确**：PostgreSQL 依赖 OS 的页面缓存（不同于 MySQL，InnoDB 自己管理缓冲池）。shared_buffers 设太大，会和 OS 页面缓存"抢内存"，反而更慢。

**3. 定期 VACUUM，或者配置 AutoVacuum**

```sql
-- 手动 VACUUM（不推荐，应该用 AutoVacuum）
VACUUM (VERBOSE, ANALYZE) my_table;

-- 查看 AutoVacuum 是否在工作
SELECT * FROM pg_stat_activity WHERE query LIKE '%autovacuum%';
```

**为什么正确**：PostgreSQL 的 MVCC 会产生"死元组"（旧版本行），不清理会导致：
1. 表膨胀（死元组占用空间）
2. 查询变慢（扫描时要跳过死元组）
3. 事务 ID 回卷（XID  wraparound，最严重，可能导致数据损坏）

**4. 用 pg_stat_statements 监控慢查询**

```sql
-- 开启 pg_stat_statements
CREATE EXTENSION pg_stat_statements;

-- 查看最慢的查询
SELECT query, mean_time, calls, total_time
FROM pg_stat_statements
ORDER BY mean_time DESC
LIMIT 10;
```

### 错误用法及后果

**错误1：max_connections 设太大（如 1000）**

**后果**：
1. 内存爆炸（每个连接进程占用 ~10MB 私有内存）
2. 上下文切换开销巨大（1000 个进程抢 CPU）
3. 性能严重下降

**修复**：设 `max_connections = 100`，用 PgBouncer 连接池。

**错误2：关闭 fsync（为了性能）**

```postgresql.conf
fsync = off   # ❌ 绝对不要这样做！
```

**后果**：OS 崩溃或断电时，已提交的事务可能丢失（WAL 没刷盘）。数据损坏，无法恢复。

**例外**：测试环境批量导入数据时，可以临时关 fsync，导入完再打开。

**错误3：从不 VACUUM，导致表膨胀**

```
现象：表的数据量只有 10GB，但磁盘占用 100GB
原因：大量 UPDATE/DELETE 产生了死元组，没清理
后果：
  1. 查询变慢（扫描更多页面）
  2. 磁盘空间浪费
  3. 严重时会 XID wraparound，数据库强制停止
```

**修复**：
1. 确保 AutoVacuum 开启（`autovacuum = on`）
2. 对大表手动设置 Vacuum 参数：
```sql
ALTER TABLE my_table SET (autovacuum_vacuum_scale_factor = 0.05);  -- 5% 死元组就触发 VACUUM
```

---

## 边界情况和坑

### 坑1：XID Wraparound（事务 ID 回卷）

```
PostgreSQL 的 XID（事务 ID）是 32 位整数（约 40 亿）
XID 是循环使用的：
  XID = 1 → 2 → 3 → ... → 4294967295 → 0 → 1 (循环)

问题：如果旧事务的 XID 比新事务的 XID "未来"（因为循环），
      数据库会认为旧事务的数据是"未来的"，不可见 → 数据丢失！
```

**防御机制**：
1. **AutoVacuum** 会自动冻结（FREEZE）旧元组（把 xmin 设为特殊的 FrozenXID）
2. 如果 AutoVacuum 来不及冻结，数据库会强制进入 **只读模式**（保护数据）
3. 监控：`SELECT * FROM pg_foreign_data_wrappers;` 查看 XID 使用情况

**解决**：
```sql
-- 手动冻结（紧急时）
VACUUM FREEZE my_table;

-- 监控 XID 剩余量（应该 > 1 亿才安全）
SELECT age(datfrozenxid) FROM pg_database;
```

### 坑2：死锁检测和超时

```
MySQL：默认等待 50 秒（innodb_lock_wait_timeout）
PostgreSQL：默认等待 **永远**（直到死锁检测发现死锁，然后报错）
```

**后果**：应用程序卡死，连接池耗尽。

**修复**：
```postgresql.conf
deadlock_timeout = 1s          # 1 秒后检测死锁（默认 1s）
lock_timeout = 5000             # 单个锁等待最多 5 秒（需要应用层设置）
statement_timeout = 30000       # 单个语句最多执行 30 秒
```

### 坑3：执行计划选择错误（统计信息过期）

```
现象：某个查询突然变慢（从 100ms → 10s）
原因：pg_statistics 过期，优化器选了错误的执行计划（如 Nested Loop 而不是 Hash Join）
```

**修复**：
```sql
-- 更新统计信息
ANALYZE my_table;

-- 或者全局更新
ANALYZE;
```

---
