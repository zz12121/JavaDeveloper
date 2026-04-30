# Elasticsearch 核心概念与架构

## 这个问题为什么存在？

在传统关系型数据库（MySQL/Oracle）里，如果你想做"全文搜索"——比如搜索文章内容里包含"分布式事务"的所有文档——你会发现这事非常难做。

MySQL 的 `LIKE '%分布式事务%'` 无法使用索引，只能全表扫描。数据量一大（千万级），搜索一次要几秒甚至几十秒。

更深层的问题：**关系型数据库是为"精确查询"设计的**（WHERE id=1，WHERE status IN (1,2)），不是为"模糊匹配"和"相关性排序"设计的。

要解决"海量数据的全文搜索"问题，需要一种完全不同的数据结构——**倒排索引（Inverted Index）**，而这正是 Elasticsearch（基于 Lucene）的核心。

所以这个问题本质是：**如何在海量非结构化文本数据里，快速找到"最相关"的文档？**

## 它是怎么解决问题的？

### 核心架构

Elasticsearch 是一个**分布式 RESTful 搜索和分析引擎**，底层是 Lucene（一个全文搜索引擎库）。

```
┌─────────────────────────────────────────────┐
│               Elasticsearch 集群              │
│                                             │
│  ┌─────────┐  ┌─────────┐  ┌─────────┐  │
│  │  Node-1  │  │  Node-2  │  │  Node-3  │  │
│  │  Master   │  │  Data    │  │  Data    │  │
│  │  Candidate│  │         │  │         │  │
│  └────┬─────┘  └────┬─────┘  └────┬─────┘  │
│       └────────┬──────┘             │          │
│                └────────┬────────────┘          │
│                         ↓                       │
│                    Index (索引)                  │
│                    ↓                             │
│              ┌──────┴──────┐                    │
│              │   Shard-1    │  (Primary)        │
│              │   Shard-2    │  (Primary)        │
│              └──────────────┘                    │
└─────────────────────────────────────────────┘
```

### 核心概念

#### 1. Index（索引）≈ 数据库里的"表"

但 Index 里的数据**不需要预先定义严格的 Schema**（虽然可以定义 Mapping）。

```
MySQL:    Database → Table → Row → Column
Elasticsearch: Cluster → Index → Document → Field
```

#### 2. Document（文档）≈ 数据库里的"行"

Document 是 JSON 格式，不需要预先定义字段（动态 Mapping）。

```json
// 一个 Document
{
  "id": 1,
  "title": "Elasticsearch 实战",
  "content": "Elasticsearch 是一个分布式搜索引擎...",
  "author": "张三",
  "create_time": "2024-01-01"
}
```

#### 3. Shard（分片）—— 分布式的基础

一个 Index 可以拆成多个 Shard，每个 Shard 是一个**独立的 Lucene 索引**。

```
Index: books (3 个 Primary Shard)
  ├── Shard-0 (存储在 Node-1)
  ├── Shard-1 (存储在 Node-2)
  └── Shard-2 (存储在 Node-3)
```

**为什么要分片？**
- **并行**：不同 Shard 可以并行搜索，提高吞吐量
- **分布**：数据分布到不同节点，突破单机存储上限

**Shard 一旦设定，不能直接修改数量**（但可以借助 Reindex API 重建索引）。

#### 4. Replica（副本）

每个 Primary Shard 可以有多个 Replica（副分片）。

```
Shard-0:
  Primary   → Node-1 (负责读写)
  Replica-1 → Node-2 (只负责读，Primary 挂了可以提升为 Primary)
  Replica-2 → Node-3
```

**副本的价值**：
- **高可用**：Primary 挂了，Replica 可以提升为 Primary
- **提高读吞吐**：Replica 可以处理读请求（写请求只能到 Primary）

#### 5. Node 角色

| 角色 | 说明 |
|------|------|
| Master-eligible | 有资格被选为 Master 节点（负责集群元数据管理） |
| Data | 存储数据、处理搜索请求（最常见） |
| Ingest | 预处理文档（Pipeline） |
| Coordinating | 协调节点（转发请求、汇总结果） |

**生产环境建议**：Master 节点和数据节点**分离**，避免 Master 节点被搜索请求拖垮。

### 写入流程（Index 一个文档）

```
客户端 → Coordinating Node (协调节点)
  → 根据文档 ID 的 Hash，路由到对应的 Primary Shard 所在的 Data Node
  → Primary Shard 写入成功
  → 同步复制到所有 Replica Shard
  → 返回成功给客户端
```

**路由规则**（默认）：

```
shard = hash(_routing) % number_of_primary_shards
默认 _routing = _id (文档 ID)
```

**可以自定义路由**（让相同属性的文档落在同一个 Shard，提高查询效率）：

```json
// 自定义 routing（比如按 user_id 路由）
PUT /orders/_doc/1?routing=user_123
{
  "order_id": 1,
  "user_id": 123,
  ...
}
```

### 搜索流程（Search）

```
客户端 → Coordinating Node
  → 将搜索请求转发到所有相关 Shard（Primary 或 Replica 都行）
  → 每个 Shard 本地搜索，返回结果（文档 ID + 评分）
  → Coordinating Node 汇总所有 Shard 的结果
  → 全局排序，取 Top N
  → 回到每个 Shard 取完整的 Document 内容（二次查询）
  → 返回给客户端
```

**Query Then Fetch 两阶段**：

1. **Query 阶段**：每个 Shard 返回文档 ID + 评分（不返回完整内容），协调节点汇总后排序
2. **Fetch 阶段**：根据排序结果，回到对应 Shard 取完整文档内容

### 源码关键路径：Lucene 索引写入

Elasticsearch 底层是 Lucene，Lucene 的写入核心是 `IndexWriter`：

```java
// Lucene 写入流程（简化）
IndexWriter writer = new IndexWriter(directory, config);

// 1. 文档被分析（Analyzer）：分词、去停用词、转小写...
Document doc = new Document();
doc.add(new TextField("content", "Elasticsearch is cool", Field.Store.YES));

// 2. 写入内存缓冲区（RAM Buffer）
writer.addDocument(doc);

// 3. Refresh：内存缓冲区 → 写入新 Segment（可被搜索，但没刷盘）
// Elasticsearch 默认每秒 Refresh 一次（near real-time）
writer.commit();  // 或等待自动 Refresh

// 4. Flush：Segment 从内存 → 写入磁盘
// 5. Merge：多个小 Segment 合并为大 Segment（后台进行）
```

**关键点**：Elasticsearch 默认 **1 秒 Refresh**，所以文档写入后**最多 1 秒**才能被搜索到（Near Real-Time，近实时）。

## 它和相似方案的本质区别是什么？

### Elasticsearch vs MySQL 全文搜索

| 维度 | MySQL (Fulltext Index) | Elasticsearch |
|------|------------------------|---------------|
| 索引结构 | 倒排索引（有限支持） | 倒排索引（完整支持） |
| 相关性评分 | 支持（BM25） | 支持（BM25 / TF-IDF） |
| 分布式 | 不支持（单节点） | 原生支持（Shard + Replica） |
| 查询语法 | 简单（MATCH AGAINST） | 丰富（Match / Bool / Aggregation） |
| 适用场景 | 小数据量、简单搜索 | 海量数据、复杂搜索 + 分析 |

**本质区别**：MySQL 全文索引是"附加功能"，Elasticsearch 是"为搜索而生"。数据量超过百万、需要复杂搜索条件或聚合分析时，MySQL 做不了，只能用 ES。

### Elasticsearch vs Solr（另一个基于 Lucene 的搜索引擎）

| 维度 | Elasticsearch | Solr |
|------|----------------|-------|
| 分布式 | 原生支持，配置简单 | 需要 SolrCloud（较复杂） |
| 近实时搜索 | 1 秒（默认 Refresh 间隔） | 支持，但配置复杂 |
| 社区和生态 | 非常活跃，周边丰富 | 较活跃，但生态小 |
| 适用场景 | 大数据、实时搜索、日志分析 | 传统搜索场景（电商商品搜索） |

**为什么选 ES 不选 Solr？** 最重要的原因：**ES 的分布式和近实时搜索比 Solr 好用太多**。加上 ELK（Elasticsearch + Logstash + Kibana）生态，日志分析场景几乎被 ES 垄断。

## 正确使用方式

### 正确用法

**1. 合理设置 Shard 数（非常重要）**

```
Shard 数 = 数据量 / 单个 Shard 的合理大小
推荐：单个 Shard 大小 10GB ~ 50GB
```

```json
// 创建 Index 时设置 Shard 数
PUT /books
{
  "settings": {
    "number_of_shards": 3,        // Primary Shard 数（设定后很难改）
    "number_of_replicas": 1        // 每个 Primary 有 1 个 Replica
  }
}
```

**为什么**：Shard 数太少 → 无法并行，数据量一大就扛不住；Shard 数太多 → 每个 Shard 太小（比如 1GB），造成资源浪费（每个 Shard 是一个 Lucene 实例，有内存开销），且搜索时合并结果的开销变大。

**经验值**：单个 Shard 10GB~50GB 是最优范围。

**2. Mapping 要提前定义（不要依赖动态 Mapping）**

```json
// 错误：让 ES 自动推断类型（可能推断错）
PUT /books/_doc/1
{
  "price": "100"  // ES 推断为 text 类型，但实际上应该是 numeric！
}

// 正确：提前定义 Mapping
PUT /books
{
  "mappings": {
    "properties": {
      "title":    { "type": "text", "analyzer": "ik_max_word" },
      "price":    { "type": "double" },
      "create_time": { "type": "date" }
    }
  }
}
```

**为什么正确**：动态 Mapping 有时会推断错类型（比如把数字推断为 text），导致后续查询出错或性能差。

**3. 使用 IK 分词器（中文搜索必备）**

```json
// 默认标准分词器（对中文不友好）
"我爱中国" → ["我", "爱", "中", "国"]  // 单字分词，没意义

// IK 分词器
"我爱中国" → ["我", "爱", "中国"]  // ik_smart：最粗粒度
"我爱中国" → ["我", "爱", "中国", "我爱", "爱我中华"]  // ik_max_word：最细粒度
```

```json
PUT /books
{
  "settings": {
    "analysis": {
      "analyzer": {
        "default": { "type": "ik_max_word" }
      }
    }
  }
}
```

**为什么正确**：中文不能按字分词，要按词分词。IK 分词器是 ES 中文分词的事实标准。

### 错误用法及后果

**错误1：Shard 数设置太多，JVM 堆压力暴增**

```
3GB 数据，设了 100 个 Shard → 每个 Shard 只有 30MB
```

**后果**：每个 Shard 是一个 Lucene 实例，有自己的内存开销（FST 前缀树、缓存等）。Shard 太多 → JVM 堆压力大 → 频繁 GC → 查询延迟飙升。

**修复**：遵循"单个 Shard 10GB~50GB"原则，3GB 数据用 1 个 Shard 就够了。

**错误2：一次查询太多 Shard，协调节点被打爆**

```json
// 错误：查询会扫 1000 个 Shard
GET /logs_2020_01,logs_2020_02,...,logs_2024_12/_search
```

**后果**：协调节点要向 1000 个 Shard 发请求、汇总结果，CPU 和内存压力极大，可能导致 OOM。

**修复**：用 Index Alias + Rollover 管理时序数据，查询时只查相关 Index。

**错误3：`_all` 字段或 `wildcard` 查询，性能极差**

```json
// 错误：通配符查询，无法使用索引
GET /books/_search
{
  "query": {
    "wildcard": { "title": "*搜索*" }
  }
}
```

**后果**：通配符在前（如 `*搜索`）无法使用倒排索引，只能全表扫描，性能极差。

**修复**：用 `match` 查询（会使用倒排索引），或者如果真的需要通配符，考虑 ngram 分词器。

## 边界情况和坑

### 坑1：Refresh 间隔 vs 写入吞吐的权衡

**现象**：写入量很大时，频繁 Refresh（默认 1 秒）会导致大量小 Segment，Merge 压力变大，写入吞吐下降。

**解决**：大量写入前，调大 Refresh 间隔：

```json
PUT /books/_settings
{
  "refresh_interval": "30s"  // 30 秒 Refresh 一次，减少小 Segment 产生
}
// 写入完成后改回 "1s"
```

### 坑2：深分页问题（Deep Pagination）

```json
// 错误：翻到 10001 页，每次都要扫描前 10000 条
GET /books/_search
{
  "from": 10000,
  "size": 10
}
```

**后果**：ES 要为每个 Shard 准备 `from + size` 条数据，协调节点要汇总 `shard数 × (from + size)` 条数据再排序。翻页越深，性能越差，到 `from=10000` 基本就死了。

**解决**：
- 用 `search_after`（推荐）：基于上一页最后一条的排序值，往下翻页
- 用 `Scroll API`（适合导出全量数据，不适合实时翻页）

```json
// search_after 翻页（无状态，不占用资源）
GET /books/_search
{
  "size": 10,
  "sort": ["_id"],  // 必须包含排序字段
  "search_after": ["上一页最后一条的 _id 值"]
}
```

### 坑3：Replica 设置不合理，写入性能差

```
number_of_replicas = 2  → 每条写入要同步复制到 2 个 Replica
```

**后果**：写入延迟 = Primary 写入 + 2 个 Replica 写入。Replica 越多，写入越慢。

**解决**：写入高峰期临时调小 `number_of_replicas`，写入完成后再调回来。或者用 Bulk API 批量写入（减少网络 Round-Trip）。

## 面试话术

**Q：Elasticsearch 和 MySQL 怎么选？**
"MySQL 擅长事务和精确查询，Elasticsearch 擅长全文搜索和复杂聚合。实际架构是：数据写 MySQL（保证事务），然后通过 Canal 或业务双写同步到 ES（提供搜索）。两者是互补，不是替代。"

**Q：ES 的写入流程是怎样的？**
"客户端发写入请求到协调节点，协调节点根据路由规则（默认是文档 ID 的 Hash）找到对应的 Primary Shard，写入成功后同步复制到所有 Replica，最后返回成功。整个流程是同步的，保证写入成功后数据已经在 Primary + Replica 上都有了。"

**Q：ES 怎么保证近实时搜索？**
"写入的数据先放在内存缓冲区，默认每秒 Refresh 一次，把内存数据写入一个新的 Segment（倒排索引文件），这时数据才能被搜索到。所以是 Near Real-Time，不是 Real-Time。"

**Q：深分页有什么问题？怎么解决？**
"用 from + size 做深分页，ES 要扫描前 N 条数据，协调节点要汇总大量数据再排序，性能极差。解决：用 search_after（基于排序值翻页，推荐）或 Scroll API（适合全量导出）。"

## 本文总结

Elasticsearch 是**为全文搜索而生的分布式引擎**，核心数据结构是倒排索引（Inverted Index）。

核心概念：Index（类似于表）、Document（类似于行，JSON 格式）、Shard（分片，并行的基础）、Replica（副本，高可用 + 提高读吞吐）。

写入流程：协调节点路由 → Primary Shard 写入 → 同步复制到 Replica → 返回。

搜索流程：Query 阶段（每个 Shard 返回 ID + 评分） → Fetch 阶段（取完整文档）。

**最重要的最佳实践**：Shard 数要合理规划（单个 Shard 10GB~50GB），不要用动态 Mapping（提前定义 Mapping），中文要用 IK 分词器。

深分页用 `search_after` 解决，不要用 `from + size`。
