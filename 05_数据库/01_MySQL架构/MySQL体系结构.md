# MySQL体系结构

## 这个问题为什么存在？

> 如果把数据库想象成一个黑盒——"我发SQL，你给我结果"——出问题的时候你根本不知道去哪一层排查。

MySQL的架构设计本质上是在解决一个问题：**如何在"查询灵活性（SQL是声明式的）"和"存储效率（磁盘IO是瓶颈）"之间做分层解耦**。

```
客户端                      Server层                        存储引擎层
  │                           │                                │
  │  SQL                     │                                │
  │  ─────────────────────►  │                                │
  │                         Parser                            │
  │                         Optimizer                         │
  │                         Executor                          │
  │                           │                                │
  │                           ─────────────────────────────►  │
  │                                                           │ InnoDB
  │                           ◄─────────────────────────────   │ MyISAM
  │                         Handler接口                        │ Memory
  │                           │                                │
  │  ◄─────────────────────  │                                │
  │  结果集                   │                                │
```

没有清晰的分层，你会遇到这些痛苦：
- SQL执行慢，不知道是网络问题、SQL写法问题、还是磁盘IO问题
- 换存储引擎（从MyISAM迁到InnoDB），应用代码要改
- 无法针对不同场景优化（OLTP用InnoDB，OLAP用Columnar引擎）

---

## 它是怎么解决问题的？

### 核心架构：三层分离

MySQL的架构可以清晰地分为三层：

```
┌─────────────────────────────────────────────────────┐
│                  客户端 (Client)                      │
│  JDBC/ODBC/MySQLi/命令行/Navicat                    │
└──────────────────────┬──────────────────────────────┘
                       │  TCP连接 (默认3306)
┌──────────────────────▼──────────────────────────────┐
│              Server层 (SQL Layer)                    │
│                                                     │
│  ┌─────────┐  ┌─────────┐  ┌─────────┐           │
│  │ Connection│  │  Parser │  │Optimizer│           │
│  │  Pool    │─▶│         │─▶│         │           │
│  └─────────┘  └────┬────┘  └────┬────┘           │
│                     │             │                 │
│                     ▼             ▼                 │
│                ┌─────────┐  ┌─────────┐           │
│                │  执行计划 │  │ Executor│           │
│                └─────────┘  └────┬────┘           │
└──────────────────────────────────┼──────────────────┘
                                   │ Handler接口
┌──────────────────────────────────▼──────────────────┐
│            存储引擎层 (Storage Engine)               │
│                                                     │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐        │
│  │ InnoDB   │  │ MyISAM   │  │ Memory   │        │
│  │(支持事务) │  │(不支持事务)│  │(内存表)  │        │
│  └──────────┘  └──────────┘  └──────────┘        │
│                                                     │
│  磁盘文件: .ibd / .myd .myi / ibdata1             │
└─────────────────────────────────────────────────────┘
```

### 第一层：客户端 (Client)

**职责**：建立和MySQL服务器的连接，发送SQL，接收结果。

```
客户端协议栈：
应用层: JDBC/ODBC/MySQLi/Python MySQLdb
  │
传输层: TCP连接 (三次握手)
  │
网络层: IP路由
  │
MySQL协议: 握手认证 → 命令请求 → 结果响应
```

**关键点**：
- MySQL默认使用 **TCP/3306** 端口
- 支持多种客户端协议：TCP/IP、Unix Socket（Linux）、Named Pipe（Windows）、Shared Memory
- 连接是 **有状态的**：每个连接有一个会话（session），保存变量、事务状态等

```sql
-- 查看当前连接
SHOW PROCESSLIST;

-- 查看连接数配置
SHOW VARIABLES LIKE 'max_connections';  -- 默认151
```

### 第二层：Server层 (SQL Layer)

这是MySQL的"大脑"，负责：
1. **解析SQL**（Parser）
2. **优化执行计划**（Optimizer）
3. **执行SQL**（Executor）
4. **管理数据库连接**（Connection Pool）

#### 2.1 连接池 (Connection Pool)

```
客户端请求 ──▶ 连接池 ──▶ 如果达到max_connections，拒绝连接
                  │
                  ▼
            复用空闲连接
            (避免频繁建连)
```

**为什么需要连接池？**

每次建立TCP连接需要：
1. TCP三次握手（1-2ms）
2. MySQL认证（用户名/密码/权限校验）
3. 分配线程资源

如果没有连接池，每次执行SQL都要建连 → **性能极差**。

```sql
-- 查看连接池状态
SHOW STATUS LIKE 'Threads_%';
-- Threads_connected: 当前打开的连接数
-- Threads_running: 当前正在运行的线程数
```

**Thread Cache**（线程缓存）：
```
新连接到达 ──▶ 查看thread_cache是否有空闲线程
                │
                ├── 有 ──▶ 复用线程 (快)
                │
                └── 无 ──▶ 创建新线程 (慢)
```

```sql
SHOW VARIABLES LIKE 'thread_cache_size';  -- 默认8-100
```

#### 2.2 Parser（解析器）

**职责**：把SQL字符串转换成解析树（Parse Tree）。

```
SQL: "SELECT * FROM users WHERE id = 1"

          Parser
            │
            ▼
    ┌───────────────┐
    │   SELECT      │
    │   ├── columns │─── ["*"]
    │   ├── FROM    │─── ["users"]
    │   └── WHERE   │─── ["id", "=", "1"]
    └───────────────┘
```

**两步解析**：
1. **词法分析**（Lexical Analysis）：把SQL拆成token
   ```
   "SELECT" → 关键字
   "*"       → 通配符
   "FROM"    → 关键字
   "users"   → 表名
   "WHERE"   → 关键字
   "id"      → 列名
   "="       → 操作符
   "1"       → 常量
   ```

2. **语法分析**（Syntax Analysis）：检查SQL是否符合语法规则
   ```
   ✗ "SELECT * FORM users"  → 语法错误 (FORM应为FROM)
   ✗ "SELECT * FROM"        → 语法错误 (缺少表名)
   ✓ "SELECT * FROM users"   → 语法正确
   ```

**如果语法错误，MySQL会立即返回错误，不会继续往下走**。

#### 2.3 Optimizer（优化器）—— 最关键的部分

**职责**：基于成本（Cost-Based）选择最优执行计划。

```
解析树 ──▶ Optimizer ──▶ 执行计划
            │
            ├── 选择索引 (用哪个索引？)
            ├── JOIN顺序 (哪张表先查？)
            ├── 子查询优化 (IN vs EXISTS？)
            └── 重写查询 (简化条件)
```

**为什么需要优化器？**

同一条SQL，可以有多种执行方式，性能差异巨大：
```sql
-- 示例：三表JOIN
SELECT *
FROM orders o
JOIN customers c ON o.customer_id = c.id
JOIN products p ON o.product_id = p.id
WHERE o.order_date > '2024-01-01';

-- 可能的执行顺序：
-- 方案1: 先扫orders (100万行) → JOIN customers → JOIN products
-- 方案2: 先扫products (1000行) → 反向JOIN → ...
-- 方案3: 利用索引，先过滤order_date，再JOIN
```

优化器的目标是：**估算每种方案的成本（IO次数 + CPU时间），选最便宜的**。

**成本模型**：
```
总成本 = IO成本 + CPU成本

IO成本：
  - 全表扫描：需要读多少页（Page）到内存？
  - 索引扫描：需要遍历多少索引节点？

CPU成本：
  - 多少行需要比较？
  - 多少次函数调用？
```

**查看优化器决策**：
```sql
-- 开启优化器跟踪
SET optimizer_trace="enabled=on";

-- 执行你的SQL
SELECT * FROM users WHERE age > 20;

-- 查看优化器的决策过程
SELECT * FROM information_schema.OPTIMIZER_TRACE\G
```

输出是一个JSON，包含：
- `considered_execution_plans`：考虑过的执行计划
- `best_access_path`：最终选择的访问路径
- `rows_estimated`：估算的行数

#### 2.4 Executor（执行器）

**职责**：按照执行计划，调用存储引擎的接口，获取/修改数据。

```
执行计划 ──▶ Executor ──▶ 调用Handler接口 ──▶ 存储引擎
                │                                   │
                ├── 读取一行数据 ◄──────────────────┤
                ├── 过滤条件 (WHERE)                │
                ├── 排序 (ORDER BY)                 │
                ├── 分组 (GROUP BY)                 │
                └── 返回结果 ◄──────────────────────┘
```

**Executor和存储引擎的交互是通过Handler接口**：
```
Executor: "给我users表的第一行"
  │
  ▼
Handler接口: storage_engine->rnd_next()
  │
  ▼
InnoDB: 从Buffer Pool读取(或磁盘加载) → 返回一行
```

**为什么需要Executor？**

存储引擎只负责"怎么存、怎么取"，不负责"业务逻辑"：
- WHERE条件过滤 → Executor做
- JOIN逻辑 → Executor做
- 排序、分组 → Executor做（复杂排序可能用临时表）

```sql
-- 示例执行流程：SELECT * FROM users WHERE age > 20 AND age < 30;
/*
1. Executor调用 handler->index_read() 定位到 age>20 的第一行
2. 循环：
   a. 从存储引擎取一行
   b. Executor检查 WHERE条件 (age < 30?)
   c. 如果满足，加入结果集
   d. 调用 handler->rnd_next() 取下一行
3. 直到不满足条件，返回结果集给客户端
*/
```

### 第三层：存储引擎层 (Storage Engine)

**职责**：负责数据的存储和提取。

```
Server层 ──▶ Handler接口 ──▶ 存储引擎
                               │
                               ├── InnoDB (默认，支持事务)
                               ├── MyISAM (不支持事务，只读快)
                               ├── Memory (内存表，重启丢失)
                               ├── CSV (文本存储)
                               └── Archive (归档，只支持INSERT/SELECT)
```

**为什么存储引擎是可插拔的？**

不同的业务场景需要不同的存储特性：
- **OLTP**（联机事务处理）：需要事务、行锁、崩溃恢复 → InnoDB
- **OLAP**（联机分析处理）：只读查询，不需要事务 → MyISAM/Columnar
- **临时数据**：重启后丢失没关系 → Memory
- **数据归档**：只插入，不修改 → Archive

**通过Handler接口解耦**：
```
Server层 ──▶ Handler接口 (统一API)
               │
               ├── create()    创建表
               ├── open()      打开表
               ├── read_row()  读一行
               ├── write_row() 写一行
               ├── update_row()修改一行
               ├── delete_row()删除一行
               └── close()     关闭表
```

每种存储引擎实现这套接口，Server层不关心底层实现。

#### InnoDB vs MyISAM（面试高频）

```
                     InnoDB                    MyISAM
─────────────────────────────────────────────────────────────
事务支持               ✓ (ACID)                   ✗
外键支持               ✓                          ✗
行锁                  ✓ (并发高)                 ✗ (表锁)
崩溃恢复              ✓ (Redo Log)               ✗
全文索引              ✓ (5.6+)                   ✓
索引类型              聚簇索引                    非聚簇索引
SELECT性能            稍慢 (维护事务开销)          快 (无事务开销)
INSERT/UPDATE性能     稍慢 (写Redo/Undo)         快
适用场景              OLTP                        OLAP/只读
```

**为什么InnoDB是默认引擎（MySQL 5.5+）？**

因为大多数互联网业务是 **OLTP**（高并发读写，需要事务保证），InnoDB的设计目标就是解决这个问题。

---

## 它和相似方案的本质区别是什么？

### MySQL vs PostgreSQL

```
                     MySQL                      PostgreSQL
─────────────────────────────────────────────────────────────
架构                 插件式存储引擎              统一存储层
事务引擎             只有InnoDB支持              所有表都支持
JSON支持             有限 (5.7+)                完整支持 (9.4+)
窗口函数             支持 (8.0+)                完整支持 (9.3+)
复制                  主从复制                   流复制 (更灵活)
扩展性                一般                       高 (支持自定义类型/函数)
适用场景              Web应用，简单快捷           复杂业务，需要高级特性
```

**为什么大多数公司选MySQL？**

1. **生态成熟**：所有语言都有成熟的MySQL驱动
2. **简单易用**：配置简单，资料多
3. **性能稳定**：InnoDB经过大量生产环境验证
4. **云服务支持**：AWS RDS、阿里云RDS主要支持MySQL

**什么时候选PostgreSQL？**

- 需要复杂查询（窗口函数、CTE递归）
- 需要地理信息（PostGIS）
- 需要自定义类型和函数
- 不需要考虑分库分表（单机性能强）

### MySQL vs NoSQL (MongoDB/Cassandra)

```
                     MySQL (关系型)              NoSQL (非关系型)
─────────────────────────────────────────────────────────────
schema              固定 (ALTER TABLE修改)       灵活 (JSON文档)
事务                 强一致性                     最终一致性 (多数)
JOIN                 支持                         不支持 (需要应用层做)
扩展性               垂直扩展 (单机性能)          水平扩展 (分片)
查询语言             SQL (标准化)                 专有API
适用场景             结构化数据，复杂查询         半结构化数据，简单读写
```

**为什么微服务架构中，有时用NoSQL？**

- **用户行为日志**：字段不固定，用MongoDB的文档模型
- **购物车**：KV存储，Redis更合适
- **消息流**：时序数据，Cassandra更适合

**但是**，90%的业务场景，MySQL + Redis 足够。

---

## 正确使用方式

### 1. 选择合适的数据类型

```sql
-- ✗ 错误：用字符串存手机号
CREATE TABLE users (
  phone VARCHAR(20)  -- 浪费空间，无法利用索引特性
);

-- ✓ 正确：用BIGINT存手机号
CREATE TABLE users (
  phone BIGINT UNSIGNED  -- 固定8字节，支持范围查询
);

-- ✗ 错误：用DATETIME存时间戳
CREATE TABLE orders (
  created_at DATETIME  -- 时区问题！
);

-- ✓ 正确：用TIMESTAMP或INT(秒级时间戳)
CREATE TABLE orders (
  created_at TIMESTAMP  -- 自动转换时区
  -- 或者用 INT UNSIGNED (Unix时间戳，跨语言通用)
);
```

### 2. 合理设置连接池大小

```
连接池大小 = CPU核心数 * 2 + 磁盘数

示例：
- 4核CPU，1块磁盘 → 连接池大小 = 4*2+1 = 9
- 但实际中，考虑：
  - 网络延迟（请求可能在等IO）
  - 建议：小网站 10-20，大网站 100-200
```

**为什么不能无限大？**

- 每个连接占用内存（线程栈、网络缓冲区）
- 上下文切换开销（线程太多，CPU时间片碎片化）
- InnoDB内部有锁竞争（连接太多，锁等待变多）

```sql
-- 查看当前连接占用内存
SHOW STATUS LIKE 'Bytes_sent';
SHOW STATUS LIKE 'Bytes_received';

-- 每个连接的理论内存占用
SELECT @@sort_buffer_size + @@join_buffer_size + @@read_buffer_size;
```

### 3. 使用PreparedStatement防止SQL注入

```java
// ✗ 错误：字符串拼接 (SQL注入风险)
String sql = "SELECT * FROM users WHERE name = '" + name + "'";
Statement stmt = conn.createStatement();
ResultSet rs = stmt.executeQuery(sql);

// 如果name = "admin' OR '1'='1"
// 最终SQL: SELECT * FROM users WHERE name = 'admin' OR '1'='1'
// 绕过认证！

// ✓ 正确：PreparedStatement (预编译，参数化查询)
String sql = "SELECT * FROM users WHERE name = ?";
PreparedStatement pstmt = conn.prepareStatement(sql);
pstmt.setString(1, name);  // 自动转义特殊字符
ResultSet rs = pstmt.executeQuery();
```

**为什么PreparedStatement更快？**

1. **预编译**：SQL只需要解析一次，后续复用执行计划
2. **减少网络传输**：如果执行多次，只需要传参数，不需要传完整SQL
3. **避免SQL注入**：参数和SQL分离，数据库知道哪部分是命令、哪部分是数据

### 4. 理解字符集和排序规则

```sql
-- 查看字符集
SHOW CHARACTER SET;

-- 查看排序规则
SHOW COLLATION WHERE Charset = 'utf8mb4';

-- utf8mb4_bin vs utf8mb4_general_ci
-- bin: 二进制比较 (区分大小写，速度快)
-- general_ci: 不区分大小写 (Case Insensitive)
```

**为什么要用utf8mb4，而不是utf8？**

- MySQL的`utf8`只支持3字节UTF-8字符（基本多文种平面）
- Emoji表情是4字节（U+1F600 😀），用`utf8`会报错
- `utf8mb4`才是完整的UTF-8（最多4字节）

```sql
-- ✗ 错误：用utf8
CREATE TABLE messages (
  content VARCHAR(500) CHARACTER SET utf8
);
-- INSERT INTO messages VALUES ('Hello 😀');  -- 报错！

-- ✓ 正确：用utf8mb4
CREATE TABLE messages (
  content VARCHAR(500) CHARACTER SET utf8mb4
);
-- INSERT INTO messages VALUES ('Hello 😀');  -- 成功！
```

---

## 边界情况和坑

### 坑1：连接池泄漏 (Connection Leak)

```java
// ✗ 错误：忘记关闭连接
public void queryUser(int id) {
    Connection conn = dataSource.getConnection();
    PreparedStatement pstmt = conn.prepareStatement("SELECT * FROM users WHERE id = ?");
    pstmt.setInt(1, id);
    ResultSet rs = pstmt.executeQuery();
    // 如果这里抛出异常，连接永远不会归还给连接池！
}

// ✓ 正确：用try-with-resources
public void queryUser(int id) {
    try (Connection conn = dataSource.getConnection();
         PreparedStatement pstmt = conn.prepareStatement("SELECT * FROM users WHERE id = ?")) {
        pstmt.setInt(1, id);
        try (ResultSet rs = pstmt.executeQuery()) {
            // 处理结果
        }
    } catch (SQLException e) {
        // 处理异常
    }
}
```

**排查方法**：
```sql
-- 查看连接状态
SHOW PROCESSLIST;
-- 如果大量连接是 Sleep 状态，且时间长 → 可能是连接泄漏

-- 查看每个线程的内存占用
SELECT * FROM information_schema.PROCESSLIST WHERE COMMAND = 'Sleep';
```

### 坑2：max_allowed_packet 限制

```sql
-- 报错：Packet for query is too large (xxxxx > 4194304)
-- 原因：一次插入的数据超过 max_allowed_packet (默认4MB)

-- 解决：
SET GLOBAL max_allowed_packet = 64 * 1024 * 1024;  -- 设置为64MB

-- 或者在my.cnf中配置：
[mysqld]
max_allowed_packet = 64M
```

**典型场景**：
- 批量INSERT：一次插入1000行，可能超过4MB
- 存储大文本/BLOB：文章内容、图片（虽然不建议存数据库）

### 坑3：时区问题

```sql
-- 场景：应用服务器在北京时间 (UTC+8)，数据库在UTC时间
-- 插入 TIMESTAMP 字段，会自动转换时区！

-- 应用服务器 (UTC+8):
INSERT INTO orders (created_at) VALUES ('2024-01-01 10:00:00');
-- MySQL (UTC) 存储: '2024-01-01 02:00:00'  (减去8小时)

-- 查询时，又会自动转换回来：
SELECT created_at FROM orders;
-- 返回: '2024-01-01 10:00:00'  (加上8小时)
```

**坑点**：
- 如果应用服务器和数据库的时区设置不一致，时间会错乱
- 建议：数据库和应用时区保持一致（都用UTC，或都用UTC+8）

```sql
-- 查看时区设置
SELECT @@time_zone, @@system_time_zone;

-- 设置时区 (建议在my.cnf中配置)
SET GLOBAL time_zone = '+8:00';
```

### 坑4：SQL_MODE 不一致导致的数据截断

```sql
-- 场景：开发环境 (sql_mode='') vs 生产环境 (sql_mode='STRICT_TRANS_TABLES')

-- 开发环境 (不严格)：
INSERT INTO users (name) VALUES ('abcdefghijklmnopqrstuvwxyzabcdefghijklmnopqrstuvwxyz');
-- name字段是VARCHAR(20)，但插入了52个字符
-- 结果：自动截断为前20个字符，不报错！

-- 生产环境 (严格模式)：
INSERT INTO users (name) VALUES ('abcdefghijklmnopqrstuvwxyzabcdefghijklmnopqrstuvwxyz');
-- 报错：Data too long for column 'name'
```

**解决**：开发和生产环境保持一致的 `sql_mode`。

```sql
-- 查看sql_mode
SELECT @@sql_mode;

-- 建议的配置：
SET GLOBAL sql_mode = 'STRICT_TRANS_TABLES,NO_ZERO_IN_DATE,NO_ZERO_DATE,ERROR_FOR_DIVISION_BY_ZERO,NO_ENGINE_SUBSTITUTION';
```

---

## 我的理解

MySQL的架构设计精髓在于 **分层解耦**：

1. **Server层负责"怎么执行"**：解析SQL、优化执行计划、协调存储引擎
2. **存储引擎层负责"怎么存"**：InnoDB关注事务和崩溃恢复，MyISAM关注只读性能

这种分层带来的好处：
- **可插拔**：可以根据业务选择存储引擎
- **职责清晰**：Server层优化和存储引擎优化可以独立进行
- **易于理解**：出问题时，能快速定位是哪一层的问题

**类比**：
- Server层就像"餐厅前台"：接单、安排座位、协调后厨
- 存储引擎就像"后厨"：中餐厅、西餐厅、日料店，各有各的做法，但都提供"做菜"服务

**面试时的回答思路**：
- 先说三层架构（Client → Server → Storage Engine）
- 然后重点讲Server层的四个组件（Connection Pool、Parser、Optimizer、Executor）
- 最后讲为什么存储引擎是可插拔的（Handler接口，不同场景选不同引擎）
- 如果面试官追问，再深入讲Optimizer的成本模型，或者InnoDB vs MyISAM的区别

---

*MySQL的架构是理解所有数据库操作的基础。不理解架构，就无法理解"为什么这条SQL慢"、"为什么加了索引没用"、"为什么事务没回滚"。*
