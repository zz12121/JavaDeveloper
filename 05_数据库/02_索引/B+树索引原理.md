# B+树索引原理

## 这个问题为什么存在？

> 如果没有索引，每次查询都要全表扫描——100万行数据，最坏情况要读100万次磁盘。

索引的本质是一个**权衡**：
- **不用索引**：查询慢，但写入快（不需要维护索引结构）
- **用B+树索引**：查询快（O(log N)），但写入慢（需要维护B+树）

```
全表扫描 vs 索引查询：
100万行数据，磁盘页16KB，每页存100行 → 需要1万个页

全表扫描：读1万个页 → 约100秒 (假设每秒100次IO)
索引查询：B+树高度3层 → 读3个页 → 约0.03秒

性能差距：3000倍以上！
```

---

## 它是怎么解决问题的？

### 为什么是B+树，不是其他数据结构？

#### 对比：AVL树（平衡二叉树）

```
AVL树存储100万条数据：
- 树高度 ≈ log₂(1,000,000) ≈ 20层
- 每次查询：20次磁盘IO → 约0.2秒

问题：
- 每个节点存1个键值 + 2个指针 → 节点太小，磁盘IO利用率低
- 20次磁盘IO对于OLTP系统来说太慢了
```

#### 对比：红黑树

```
红黑树存储100万条数据：
- 树高度 ≈ 2 * log₂(1,000,000) ≈ 40层
- 每次查询：40次磁盘IO → 约0.4秒

问题：
- 比AVL树还高！
- 同样节点太小，磁盘IO利用率低
```

#### 对比：B树（B-Tree）

```
B树存储100万条数据：
- 每个节点存100个键值 + 101个指针 → 节点大小约为 100*8 + 101*8 = 1.6KB
- 树高度 ≈ log₁₀₀(1,000,000) ≈ 3层
- 每次查询：3次磁盘IO → 约0.03秒

进步：树高度降低到3层，性能大幅提升！

但是，B树有个问题：
- 内部节点也存数据 → 一个节点能存的键值变少 → 树高度可能增加
- 范围查询慢：例如 WHERE id BETWEEN 10 AND 100
  → 需要中序遍历B树 → 多次磁盘IO（数据不在连续页）
```

#### B+树（MySQL的选择）

```
B+树存储100万条数据：
- 内部节点只存键值，不存数据 → 一个节点能存更多键值
  （假设每个节点存1000个键值）
- 树高度 ≈ log₁₀₀₀(1,000,000) ≈ 2层！
- 每次查询：2~3次磁盘IO → 约0.02秒

优势：
1. 树高度更低 (2~3层) → 磁盘IO更少
2. 内部节点只存键值 → 每个节点能存更多键值 → 树更矮更胖
3. 所有数据都在叶子节点，且叶子节点用链表连接 → 范围查询极快
4. 查询性能稳定：任何键的查询路径长度相同 (树高度)
```

### B+树的物理结构

```
B+树（m=3，每个节点最多2个键值）：
                     [20, 40]
                    /    |    \
                   /     |     \
              [10,15] [25,30] [45,50]
                /   \   /   \   /   \
              (1-9)(10-15)(16-20)(21-25)(26-30)(31-40)(41-45)(46-50)
                        
内部节点：只存键值，不存数据
叶子节点：存键值和指向数据的指针（或数据本身）
叶子节点之间有双向链表：支持范围查询
```

**InnoDB的聚簇索引（主键索引）**：

```
叶子节点存完整数据行：
                     [20, 40]
                    /    |    \
               [10,15] [25,30] [45,50]
                /   \   /   \   /   \
      ┌─────┐  ┌─────┐  ┌─────┐  ┌─────┐
      │id=10│  │id=20│  │id=25│  │id=45│
      │Tom  │  │Jerry│  │Mike │  │John │
      │age=20│  │age=25│  │age=30│  │age=35│
      └─────┘  └─────┘  └─────┘  └─────┘
      ←──────────── 双向链表 ────────────→
```

**InnoDB的二级索引（非主键索引）**：

```
叶子节点存主键值（不是指向数据的指针！）：
                     [20, 40]
                    /    |    \
               [10,15] [25,30] [45,50]
                /   \   /   \   /   \
      ┌─────┐  ┌─────┐  ┌─────┐  ┌─────┐
      │age=20│  │age=25│  │age=30│  │age=35│
      │id=10 │  │id=20 │  │id=25 │  │id=45 │
      └─────┘  └─────┘  └─────┘  └─────┘
      ←──────────── 双向链表 ────────────→

查询：SELECT * FROM users WHERE age = 20;
1. 通过idx_age找到 age=20 的所有主键 (id=10)
2. 回表：根据主键id=10，去聚簇索引查完整数据
```

### B+树的插入和删除（索引维护）

#### 插入（可能导致页分裂）

```
插入过程：
1. 找到要插入的叶子节点
2. 如果叶子节点有空位 → 直接插入
3. 如果叶子节点已满 → 页分裂：
   a. 创建新页
   b. 把原页的一半数据移到新页
   c. 在父节点插入新页的键值
   d. 如果父节点也满了 → 递归分裂

页分裂的问题：
- 性能开销：需要移动数据、更新父节点
- 空间浪费：分裂后，两个页平均只用了50%的空间
- 碎片：频繁分裂导致索引碎片
```

#### 删除（可能导致页合并）

```
删除过程：
1. 找到要删除的记录
2. 删除记录
3. 如果叶子节点利用率 < 50% → 页合并：
   a. 和相邻页合并
   b. 在父节点删除对应键值
   c. 如果父节点也 < 50% → 递归合并

页合并的触发条件：
- InnoDB参数：innodb_fill_factor (默认100，即100%满才分裂)
- 删除导致利用率低，才会合并
```

---

## 它和相似方案的本质区别是什么？

### B+树 vs 哈希索引

```
                     B+树索引                  哈希索引
─────────────────────────────────────────────────────────────
等值查询             O(log N)                    O(1)
范围查询             ✓ (叶子节点链表)             ✗ (需要全表扫描)
排序查询             ✓ (索引有序)                 ✗
前缀匹配             ✓ (最左前缀)                 ✗
索引大小             较大                        小
适用场景             大多数场景                   KV查询 (=、IN)
```

**为什么InnoDB默认用B+树，而不是哈希？**

- 业务查询大多需要范围查询（WHERE age > 20）
- 哈希索引不支持范围查询 → 局限性太大
- B+树的O(log N)已经足够快（2~3次IO）

**但是**，Memory引擎支持哈希索引：

```sql
CREATE TABLE user_cache (
  id INT PRIMARY KEY,
  data TEXT
) ENGINE=Memory USING HASH;
-- 只支持等值查询，不支持范围查询
```

### B+树 vs 全文索引 (Fulltext Index)

```
                     B+树索引                  全文索引
─────────────────────────────────────────────────────────────
适用查询             等值、范围、前缀           全文搜索 (MATCH...AGAINST)
例如                 WHERE name = 'Tom'        WHERE MATCH(content) AGAINST('MySQL')
性能               快                          快 (但需要建立全文索引)
索引大小             较小                        大 (需要存词频、位置)
```

**什么时候用全文索引？**

```sql
-- ✗ 慢：LIKE '%关键词%' (无法利用B+树索引)
SELECT * FROM articles WHERE content LIKE '%MySQL%';

-- ✓ 快：全文索引
ALTER TABLE articles ADD FULLTEXT INDEX idx_content (content);
SELECT * FROM articles WHERE MATCH(content) AGAINST('MySQL');
```

### 聚簇索引 vs 非聚簇索引

```
                    聚簇索引 (InnoDB主键)       非聚簇索引 (MyISAM)
─────────────────────────────────────────────────────────────
数据存储            索引和数据在一起            索引和数据分离
                    (叶子节点存完整数据)        (叶子节点存行号)
主键查询            快 (一次IO)                慢 (两次IO：先读索引，再读数据)
二级索引            需要回表 (查两次索引)      不需要回表 (直接拿到行号)
索引大小            较大 (数据存在主键索引里)    较小
```

**为什么InnoDB用聚簇索引？**

- 大多数查询是通过主键查询 → 一次IO就能拿到数据
- 二级索引虽然需要回表，但主键查询是最高频的

**为什么MyISAM不用聚簇索引？**

- MyISAM不支持事务 → 不需要聚簇索引的"数据即索引"特性
- 非聚簇索引更简单，适合只读场景

---

## 正确使用方式

### 1. 选择合适的列建索引

```sql
-- ✓ 适合建索引的列：
-- 1. WHERE条件中经常出现的列
WHERE age = 20           → 给age建索引
WHERE name LIKE 'Tom%'   → 给name建索引

-- 2. JOIN条件中的列
SELECT * FROM orders JOIN users ON orders.user_id = users.id
→ 给orders.user_id建索引

-- 3. ORDER BY / GROUP BY中的列
SELECT * FROM users ORDER BY age
→ 给age建索引 (避免filesort)

-- ✗ 不适合建索引的列：
-- 1. 选择性低的列 (重复值多)
SELECT * FROM users WHERE gender = 'M';  -- gender只有M/F → 索引效果差

-- 2. 很少查询的列
-- 如果某个列从不出现在WHERE/JOIN/ORDER BY中 → 不需要建索引

-- 3. 小表 (几百行) → 全表扫描更快
```

### 2. 利用覆盖索引（不需要回表）

```sql
-- ✗ 慢：需要回表
CREATE INDEX idx_age ON users(age);
SELECT * FROM users WHERE age > 20;
-- 先用idx_age找到主键 → 再回表查聚簇索引 → 两次IO

-- ✓ 快：覆盖索引
CREATE INDEX idx_age_name ON users(age, name);
SELECT age, name FROM users WHERE age > 20;
-- idx_age_name包含了age和name → 不需要回表 → 一次IO

-- 检查是否用了覆盖索引
EXPLAIN SELECT age, name FROM users WHERE age > 20;
-- Extra: Using index (覆盖索引)
```

### 3. 前缀索引（减少索引大小）

```sql
-- ✗ 问题：VARCHAR(255)建索引，索引太大
CREATE INDEX idx_name ON users(name);
-- name最长255字符 → 索引也存255字符 → 每个节点能存的键值变少 → 树变高

-- ✓ 解决：前缀索引
CREATE INDEX idx_name ON users(name(20));  -- 只索引前20个字符
-- 索引大小减少 → 每个节点能存更多键值 → 树更矮

-- 问题：前缀索引不能用于覆盖索引 (无法拿到完整列值)
SELECT name FROM users WHERE name LIKE 'Tom%';
-- idx_name只存前20字符 → 还是需要回表拿完整name
```

### 4. 联合索引的顺序（最左前缀原则）

```sql
-- 建立联合索引
CREATE INDEX idx_age_name ON users(age, name);

-- ✓ 可以用索引的查询：
WHERE age = 20                     -- 用了age部分
WHERE age = 20 AND name = 'Tom'   -- 用了age+name部分
WHERE age > 20                     -- 用了age部分 (范围查询)
WHERE age = 20 ORDER BY name       -- 用了age+name (索引有序)

-- ✗ 不能用索引的查询：
WHERE name = 'Tom'                 -- 没有age，违反最左前缀
WHERE name LIKE '%Tom'             -- 前缀模糊查询，索引失效

-- 原则：
-- 1. 最左前缀：查询条件必须包含索引的最左列
-- 2. 范围查询后的列不能用索引：
     WHERE age > 20 AND name = 'Tom'
     → 只能用age部分，name不能用索引 (因为age是范围查询)
```

---

## 边界情况和坑

### 坑1：索引合并（Index Merge）—— 有时候是性能杀手

```sql
-- 场景：WHERE条件中有多个独立索引
CREATE INDEX idx_age ON users(age);
CREATE INDEX idx_name ON users(name);

-- 查询：
SELECT * FROM users WHERE age = 20 OR name = 'Tom';

-- InnoDB可能用索引合并：
-- 1. 用idx_age找到 age=20 的所有行
-- 2. 用idx_name找到 name='Tom' 的所有行
-- 3. 合并结果 (去重)

-- 问题：
-- - 需要扫描两个索引 → IO次数多
-- - 合并结果需要临时表 → 性能差

-- 解决：建立联合索引
CREATE INDEX idx_age_name ON users(age, name);
-- 然后用UNION改写查询：
SELECT * FROM users WHERE age = 20
UNION ALL
SELECT * FROM users WHERE name = 'Tom' AND age != 20;
```

### 坑2：索引选择性太低，优化器不用索引

```sql
-- 场景：gender列只有M/F两个值
CREATE INDEX idx_gender ON users(gender);

-- 查询：
SELECT * FROM users WHERE gender = 'M';
-- 返回50%的行 → 优化器认为"全表扫描更快" → 不用索引

-- 检查索引选择性：
SELECT COUNT(DISTINCT gender) / COUNT(*) AS selectivity FROM users;
-- 选择性 = 0.5 (极低，不适合建索引)

-- 什么列适合建索引？
-- 选择性 > 10% 的列 (一般来说)
SELECT COUNT(DISTINCT age) / COUNT(*) AS selectivity FROM users;
-- 选择性 = 0.8 (高，适合建索引)
```

### 坑3：页分裂导致性能下降

```
现象：
- INSERT性能逐渐变慢
- 索引占用空间比预期大

原因：
- 主键是UUID (无序) → 插入时频繁页分裂
- 页分裂导致碎片 → 空间利用率低

解决：
1. 用自增主键 (有序插入，减少页分裂)
   CREATE TABLE users (
     id BIGINT AUTO_INCREMENT PRIMARY KEY,  -- ✓
     ...
   );

2. 如果必须用UUID，用UUIDv7 (有序UUID)
   -- UUIDv7 = 时间戳 + 随机数 → 大致有序

3. 定期优化表 (重组索引)
   OPTIMIZE TABLE users;
   -- 注意：会锁表，建议在低峰期执行
```

### 坑4：索引条件下推（Index Condition Pushdown, ICP）

```sql
-- 场景：联合索引，但WHERE条件中有些无法用索引
CREATE INDEX idx_age_name ON users(age, name);

-- 查询：
SELECT * FROM users WHERE age > 20 AND name LIKE '%Tom';

-- 没有ICP (MySQL 5.6之前)：
-- 1. 用idx_age找到 age>20 的所有行 (假设1万行)
-- 2. 回表，读取完整数据
-- 3. 在Server层过滤 name LIKE '%Tom'
-- → 问题：回表了1万行，但可能只有10行满足条件

-- 有ICP (MySQL 5.6+)：
-- 1. 用idx_age找到 age>20 的所有索引记录
-- 2. 在存储引擎层，直接过滤 name LIKE '%Tom' (利用索引中的name值)
-- 3. 只有满足条件的索引记录，才回表
-- → 优化：可能只需要回表10行

-- 查看是否用了ICP
EXPLAIN SELECT * FROM users WHERE age > 20 AND name LIKE '%Tom';
-- Extra: Using index condition (用了ICP)
```

---

## 我的理解

B+树索引是MySQL性能的核心。关键点：

1. **为什么是B+树？**
   - 树高度低 (2~3层) → 磁盘IO少
   - 叶子节点链表 → 范围查询快
   - 内部节点只存键值 → 每个节点能存更多键值 → 树更矮

2. **聚簇索引 vs 二级索引**
   - 聚簇索引：主键索引，叶子节点存完整数据
   - 二级索引：非主键索引，叶子节点存主键值 → 需要回表

3. **索引优化原则**
   - 覆盖索引：索引包含查询的所有列 → 不需要回表
   - 最左前缀：查询条件必须包含索引的最左列
   - 选择性：选择性低的列不适合建索引

**面试回答思路**：
- 先说为什么选B+树（对比AVL、红黑树、B树）
- 然后讲B+树的结构（内部节点、叶子节点、链表）
- 最后讲聚簇索引和二级索引的区别，以及回表的概念
- 如果面试官追问，再深入讲页分裂、索引合并、ICP

**类比**：
- B+树就像字典的目录：
  - 内部节点 = 目录的大类（A、B、C...）
  - 叶子节点 = 具体的单词和解释
  - 链表 = 单词按字母顺序排列，可以连续查找

---

*索引是数据库优化的第一手段。理解B+树，你才能知道"为什么这个查询慢"、"怎么建索引才能生效"、"为什么优化器不用我建的索引"。*