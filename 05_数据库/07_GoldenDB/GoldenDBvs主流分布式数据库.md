# GoldenDB vs 主流分布式数据库

## 这个问题为什么存在？

面试时经常会被问：

> **"你们为什么选 GoldenDB？和 TiDB / OceanBase 比有什么优势？"**
> **"分布式数据库怎么选型？"**
> **"GoldenDB、TiDB、OceanBase 的核心区别是什么？"**

这篇文章把 GoldenDB 和主流分布式数据库（TiDB、OceanBase、CockroachDB）做全方位对比，形成一套**面试可直接用的话术**。

---

## 一、核心架构对比

```
GoldenDB 架构：
  GTM（全局事务管理器，集中式）
    ├── Data Node 1（MySQL 改造）
    ├── Data Node 2（MySQL 改造）
    └── Data Node N（MySQL 改造）
  → SQL 层是集中式（GTM 单点），存储层是分布式的

TiDB 架构：
  TiDB Server（无状态，可横向扩展）
    ├── PD（Placement Driver，管理元数据 + TSO）
    └── TiKV（RocksDB 引擎，可横向扩展）
  → SQL 层 + 存储层都可横向扩展

OceanBase 架构：
  RootService（总控服务，类似 PD）
    ├── ObServer（存储 + SQL，可横向扩展）
    └── ObServer（存储 + SQL，可横向扩展）
  → 存储和 SQL 在同一进程（Shared-Nothing）
```

| 维度 | GoldenDB | TiDB | OceanBase |
|------|----------|-------|------------|
| SQL 层 | 集中式（GTM 单点，可扩容但复杂） | 无状态（可横向扩展 ✅） | 无状态（RootService 可切换 ✅） |
| 存储层 | MySQL 改造（可横向扩展 ✅） | RocksDB（可横向扩展 ✅） | 自研引擎（可横向扩展 ✅） |
| 横向扩展能力 | 中（SQL 层有上限） | 强（SQL + 存储都可扩展） | 强（存储 + SQL 同进程，扩展方便） |
| 内核改造 | MySQL 改造（兼容性好） | 全新（RocksDB + Percolator） | 全新（自研引擎 + Paxos） |

**面试话术**：

> GoldenDB 的 SQL 层是集中式的（GTM 管理事务），扩展能力不如 TiDB/TiDB 的 SQL 层是无状态的，可以横向扩展。但 GoldenDB 的优势是 MySQL 协议 + 语法高度兼容，迁移成本很低。如果团队熟悉 MySQL，选 GoldenDB；如果需要更好的横向扩展能力，选 TiDB。

---

## 二、事务模型对比

| 维度 | GoldenDB | TiDB | OceanBase |
|------|----------|-------|------------|
| 事务模型 | 2PC + GTM（类似 XA） | Percolator（乐观事务） | 2PC + GTS（类似 GoldenDB） |
| 时间戳 | GTM 分配（全局单调递增） | PD 分配 TSO（混合逻辑时钟） | GTS（类似 TSO） |
| 乐观 vs 悲观 | 都支持（默认悲观） | TiDB 3.0+ 默认悲观 | 默认悲观 |
| 分布式事务性能 | 中（2PC 两次 RTT） | 中（Percolator 两次 RTT） | 中（2PC 两次 RTT） |
| 单分片优化 | ✅（优化成 1PC） | ✅（单 Region 优化成 1PC） | ✅（单分区优化成 1PC） |

#### Percolator（TiDB 的事务模型）

```
Percolator（Google BigTable 的事务模型）：
  1. 客户端向 TiKV 写 "主锁"（Primary Lock）
  2. 客户端向其他 TiKV 写 "二级锁"（指向 Primary Lock）
  3. 提交时，清理 Primary Lock（其他锁异步清理）

优势：
  - 无锁（乐观并发控制）
  - 适合读多写少的场景

劣势：
  - 写冲突时，需要重试（性能下降）
  - 大事务可能锁很多行（内存占用大）
```

**面试话术**：

> TiDB 用 Percolator 模型（Google 的 BigTable 事务模型），是乐观事务（写的时候不加锁，提交时检查冲突）。GoldenDB 和 OceanBase 用 2PC + 全局时间戳，默认悲观事务（写的时候加锁）。乐观事务适合读多写少，悲观事务适合写多读少。

---

## 三、MySQL 兼容性对比

| 维度 | GoldenDB | TiDB | OceanBase |
|------|----------|-------|------------|
| MySQL 协议兼容 | ✅ 很好（几乎无缝迁移） | ✅ 好（大部分兼容，部分语法不支持） | ✅ 好（支持 MySQL 模式） |
| MySQL 语法兼容 | ✅ 很好（基于 MySQL 改造） | ⚠️ 中（大部分兼容，部分函数不支持） | ⚠️ 中（MySQL 模式，但和 GoldenDB 比稍差） |
| Oracle 兼容 | ❌ 不支持 | ❌ 不支持 | ✅ 支持（Oracle 模式，语法兼容 90%+） |
| 迁移成本 | 很低（几乎不改代码） | 中（可能需要改部分 SQL） | 中（MySQL 模式下迁移成本低） |
| 工具生态 | MySQL 生态（Navicat、mysqldump 都能用） | MySQL 生态（但部分工具可能不兼容） | MySQL + Oracle 生态 |

**面试话术**：

> GoldenDB 的 MySQL 兼容性是最好的（基于 MySQL 改造），迁移几乎不改代码，Navicat、mysqldump 这些工具都能直接用。TiDB 的兼容性也不错，但部分 MySQL 函数不支持（如 `GROUP_CONCAT` 有长度限制）。OceanBase 支持 MySQL 和 Oracle 双模式，但 Oracle 模式更成熟。如果迁移成本是首要考虑，选 GoldenDB。

---

## 四、金融场景适配对比

| 维度 | GoldenDB | TiDB | OceanBase |
|------|----------|-------|------------|
| 灰度迁移 | ✅ 支持（双写 + 校验） | ⚠️ 需要第三方工具 | ⚠️ 需要第三方工具 |
| 数据校验 | ✅ 内置（全量 + 增量校验） | ⚠️ 需要第三方工具 | ⚠️ 需要第三方工具 |
| 强同步复制（RPO=0） | ✅ 默认（金融级） | ✅ 支持（Sync Log Replication） | ✅ 支持（Paxos 三副本） |
| 同城双活 | ✅ 支持 | ✅ 支持（Placement Rules） | ✅ 支持（Primary Zone） |
| 异地多活 | ✅ 支持（高级功能） | ⚠️ 有限支持 | ✅ 支持 |
| 典型金融用户 | 中信银行、民生银行 | 北京银行、微众银行 | 蚂蚁金服、网商银行 |

**面试话术**：

> GoldenDB 是专门为金融场景设计的，内置了灰度迁移和数据校验工具（从 MySQL 迁移到 GoldenDB 不停机）。TiDB 和 OceanBase 也有金融案例，但迁移工具需要第三方（如 TICDC、OceanBase 迁移服务）。如果项目是银行核心系统替换（IBM DB2 → 分布式数据库），GoldenDB 的经验更丰富。

---

## 五、开源与商业模式对比

| 维度 | GoldenDB | TiDB | OceanBase |
|------|----------|-------|------------|
| 是否开源 | ❌ 不开源（商业产品） | ✅ Apache 2.0（开源） | ✅ Mulan PubL 2.0（开源） |
| 社区活跃度 | ❌ 无社区（只有官方支持） | ✅ 很高（GitHub 36k+ Stars） | ✅ 高（GitHub 8k+ Stars） |
| 学习资料 | ⚠️ 较少（主要官方文档） | ✅ 很多（社区文章、书） | ✅ 较多（官方文档 + 社区） |
| 商业支持 | 中兴通讯（原厂支持） | PingCAP（原厂支持） | 蚂蚁金服（原厂支持） |
| 价格 | 商业授权（闭源，价格较高） | 开源免费（企业版收费） | 开源免费（企业版收费） |

**面试话术**：

> GoldenDB 是商业产品（不开源），优势是原厂支持（中兴通讯），适合对"原厂支持"有要求的金融客户。TiDB 和 OceanBase 都开源，社区活跃，学习资料多，适合有技术能力的团队（可以自己解决问题）。如果预算充足且需要原厂支持，选 GoldenDB；如果团队技术能力强，选 TiDB 或 OceanBase。

---

## 六、性能对比（典型场景）

```
性能对比（参考，具体看场景）：
  1. 简单读写（点查、按主键更新）：
     GoldenDB ≈ TiDB ≈ OceanBase（差距不大）

  2. 复杂查询（多表 JOIN、子查询）：
     TiDB > OceanBase > GoldenDB
     （TiDB 的 TiDB Server 优化器更强大）

  3. 写入密集型（如：批量导入）：
     OceanBase > TiDB > GoldenDB
     （OceanBase 的写入优化更好）

  4. 金融交易场景（高并发小事务）：
     GoldenDB ≈ OceanBase > TiDB
     （GoldenDB 和 OceanBase 的悲观事务更适合）
```

**面试话术**：

> 性能要看场景。简单读写（点查、按主键更新）三者差距不大。复杂查询（多表 JOIN）TiDB 更强（优化器更强大）。金融交易场景（高并发小事务）GoldenDB 和 OceanBase 更适合（悲观事务）。实际选型应该做 POC（概念验证），用自己的业务场景测试。

---

## 七、选型建议（面试可以直接用）

```
选型考虑因素：
  1. MySQL 兼容性要求高？       → GoldenDB
  2. 需要开源 + 社区活跃？    → TiDB / OceanBase
  3. 金融核心系统（银行、保险）？ → GoldenDB（经验更丰富）
  4. 互联网业务（高并发、复杂查询）？ → TiDB
  5. Oracle 迁移？              → OceanBase（Oracle 模式）
  6. 团队技术能力强？          → TiDB / OceanBase
  7. 需要原厂支持（金融客户常见）？ → GoldenDB
```

**面试标准回答**：

> 分布式数据库选型要看场景。如果是金融核心系统（银行、保险），GoldenDB 的经验最丰富（中信银行、民生银行的案例），且 MySQL 兼容性很好，迁移成本低。如果是互联网业务（高并发、复杂查询），TiDB 更合适（优化器强大、社区活跃）。如果是 Oracle 迁移，OceanBase 有优势（Oracle 模式）。实际选型应该做 POC，用自己的业务场景测试。

---

## 本文总结

| 对比维度 | GoldenDB | TiDB | OceanBase |
|----------|----------|-------|------------|
| 架构 | GTM 集中式 + Data Node | TiDB Server + TiKV | RootService + ObServer |
| 事务模型 | 2PC + GTM | Percolator（乐观事务） | 2PC + GTS |
| MySQL 兼容 | ✅ 很好 | ✅ 好 | ✅ 好（MySQL 模式） |
| Oracle 兼容 | ❌ | ❌ | ✅（Oracle 模式） |
| 金融适配 | ✅ 很好（灰度迁移、数据校验） | ⚠️ 一般 | ✅ 很好（蚂蚁金服打磨） |
| 是否开源 | ❌ 商业闭源 | ✅ Apache 2.0 | ✅ Mulan PubL 2.0 |
| 典型用户 | 中信银行、民生银行 | 北京银行、微众银行 | 蚂蚁金服、网商银行 |
| 适合场景 | 金融核心、MySQL 迁移 | 互联网业务、复杂查询 | Oracle 迁移、金融场景 |

**面试核心话术**：GoldenDB 适合金融核心系统（MySQL 兼容 + 灰度迁移），TiDB 适合互联网业务（开源 + 复杂查询优化），OceanBase 适合 Oracle 迁移（双模式兼容）。选型看场景，实际应该做 POC 测试。

---
