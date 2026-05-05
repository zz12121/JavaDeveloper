# Elasticsearch 查询与聚合

## 这个问题为什么存在？

用 Elasticsearch 不只是为了"搜一下"。在实际业务中，你会遇到两类需求：

1. **搜索（Search）**：找文档，按相关性排序（`match`、`term`、Bool 组合等）
2. **分析（Analytics）**：统计数据，比如"过去 30 天的订单金额总和"、"每个分类下的商品数量"——这是 **聚合（Aggregation）**。

关系型数据库用 `GROUP BY` + 聚合函数（`SUM`、`COUNT`、`AVG`）做分析。但 ES 的聚合比 SQL 强得多——它支持**嵌套聚合**、**管道聚合**，而且在**海量数据**下性能依然很好（得益于分布式并行计算）。

所以这个问题本质是：**如何高效地在海量非结构化数据里同时做搜索和分析？**

## 它是怎么解决问题的？

### 查询类型概览

ES 的查询分为两大类：

```
Query DSL
├── 叶子查询（Leaf Query）: 只查一个字段
│   ├── match (全文搜索)
│   ├── term (精确匹配)
│   ├── range (范围)
│   └── exists (字段是否存在)
│
└── 复合查询（Compound Query）: 组合多个叶子查询
    ├── bool (最常用：must/should/must_not/filter)
    ├── boosting (降低某些文档评分)
    └── constant_score (固定评分)
```

### 核心查询详解

#### 1. Match 查询（全文搜索标准用法）

```json
GET /books/_search
{
  "query": {
    "match": {
      "content": {
        "query": "分布式事务",
        "operator": "and"  // "分布式" AND "事务"，默认是 "or"
      }
    }
  }
}
```

**执行流程**：
1. 对 `"分布式事务"` 做分词 → `["分布式", "事务"]`
2. 查倒排索引，找到包含这些词的文档
3. 用 BM25 算法计算相关性评分
4. 按评分降序返回

**`operator: and` vs `or`**：
- `or`（默认）：包含"分布式"或"事务"的文档都能匹配（召回率高，精确度低）
- `and`：必须同时包含"分布式"和"事务"（召回率低，精确度高）

#### 2. Bool 查询（组合多个条件）

```json
GET /books/_search
{
  "query": {
    "bool": {
      "must": [          // 必须匹配，贡献评分
        { "match": { "content": "分布式" } }
      ],
      "should": [        // 应该匹配，匹配了加分（不影响是否入选）
        { "match": { "title": "实战" } }
      ],
      "must_not": [      // 必须不匹配
        { "term": { "status": 0 } }
      ],
      "filter": [        // 必须匹配，不贡献评分（利用缓存，快！）
        { "range": { "price": { "gte": 50, "lte": 200 } } }
      ]
    }
  }
}
```

**四个子句的语义区别**：

| 子句 | 是否影响入选 | 是否贡献评分 | 是否使用缓存 |
|-------|------------|------------|------------|
| `must` | 是 | 是 | 否 |
| `should` | 否* | 是 | 否 |
| `must_not` | 是 | 否 | 否 |
| `filter` | 是 | 否 | **是**（BitSet 缓存） |

> *`should` 在 `must` 或 `filter` 存在时不影响入选，纯粹加分；如果没有 `must`/`filter`，则 `should` 至少匹配一个才入选。

**为什么 `filter` 快？** `filter` 不计算评分，结果可以被缓存为 **BitSet**（每个 Segment 一个 BitSet，1 表示文档匹配，0 表示不匹配）。下次同样条件直接查 BitSet，不用再遍历倒排列表。

#### 3. Term 查询（精确匹配）

```json
GET /books/_search
{
  "query": {
    "term": {
      "status": 1  // status 是 keyword 类型（精确值）
    }
  }
}
```

**注意**：`term` 查询不做分词，直接找倒排索引里有没有精确的词项。

- 对 `keyword` 类型字段：正确用法
- 对 `text` 类型字段：**大概率查不到**（因为 text 字段存的是分词后的词项，不是原始文本）

**正确做法**：需要精确匹配时用 `keyword` 子字段：

```json
GET /books/_search
{
  "query": {
    "term": {
      "author.keyword": "张三"  // 用 .keyword 子字段
    }
  }
}
```

### 聚合（Aggregation）

聚合是在查询结果的基础上做统计分析，分为四大类：

```
Aggregation
├── Metric（指标聚合）: 计算数字指标
│   ├── sum / avg / min / max / value_count
│   └── stats (一次性返回 count/sum/avg/min/max)
│
├── Bucket（桶聚合）: 分组
│   ├── terms (按词项分组，类似 GROUP BY)
│   ├── range (按范围分组)
│   └── date_histogram (按时间间隔分组)
│
├── Pipeline（管道聚合）: 对聚合结果再做计算
│   ├── bucket_sort (对桶排序)
│   └── cumulative_sum (累计和)
│
└── Matrix（矩阵聚合）: 多字段统计（少用）
```

#### 示例1：Metric + Bucket 组合

```json
GET /orders/_search
{
  "size": 0,           // 不返回原始文档，只要聚合结果
  "aggs": {
    "by_category": {   // 聚合名称（自定义）
      "terms": {
        "field": "category.keyword",
        "size": 10      // 返回 Top 10 分类
      },
      "aggs": {         // 在桶内再聚合（嵌套聚合）
        "total_sales": {
          "sum": { "field": "amount" }
        }
      }
    }
  }
}
```

**结果解读**：

```json
"aggregations": {
  "by_category": {
    "buckets": [
      { "key": "手机", "doc_count": 500, "total_sales": { "value": 5000000 } },
      { "key": "电脑", "doc_count": 300, "total_sales": { "value": 3000000 } }
    ]
  }
}
```

#### 示例2：Date Histogram（按时间分组）

```json
GET /orders/_search
{
  "size": 0,
  "aggs": {
    "sales_over_time": {
      "date_histogram": {
        "field": "create_time",
        "calendar_interval": "day",  // 按天分组
        "format": "yyyy-MM-dd"
      },
      "aggs": {
        "daily_total": { "sum": { "field": "amount" } }
      }
    }
  }
}
```

**适用场景**：时序数据分析（订单量趋势、访问量曲线等），是 Kibana 可视化的基础。

### 源码关键路径：Query 执行流程

```
Coordinating Node 收到搜索请求
  → 将请求转发到所有相关 Shard（Primary 或 Replica）
  → 每个 Shard 本地执行：
      → 遍历倒排列表（或查 BitSet 缓存）
      → 计算评分（BM25）
      → 本地 Top N（优先队列，只保留评分最高的 N 条）
  → 协调节点汇总所有 Shard 的 Top N
  → 全局排序，取最终 Top N
  → Fetch 阶段：回到各 Shard 取完整文档内容
```

**关键优化**：每个 Shard 只返回 Top N（不是全部匹配文档），协调节点汇总后再排序。这避免了在网络中传输大量数据。

**问题**：如果 N=10，有 5 个 Shard，协调节点要汇总 5×10=50 条数据再排序。这可能导致**不准确**（某个 Shard 的第 11 条可能比另一个 Shard 的第 1 条评分更高，但没被传上来）。

**解决**：`?"search_type=dfs_query_then_fetch"` （不推荐，慢）或用更强的硬件 / 调整 Shard 数。

## 深入原理

### ES 聚合 vs MySQL GROUP BY

| 维度 | MySQL GROUP BY | ES Aggregation |
|------|----------------|---------------|
| 数据量 | 千万级开始变慢 | 百亿级依然可以（分布式并行） |
| 嵌套分析 | 不支持（要子查询） | 原生支持（嵌套聚合） |
| 管道处理 | 不支持 | 支持（Pipeline Aggregation） |
| 时序分析 | 需要复杂 SQL | date_histogram 一行搞定 |
| 性能 | 单机，大表慢 | 分布式，并行计算 |

**本质区别**：MySQL 的聚合是"单机批处理"，ES 的聚合是"分布式并行计算 + 倒排索引加速"。数据量大了之后，MySQL 做不了的事，ES 可以做。

### Query  then Fetch vs  DFS Query then Fetch

| 模式 | 说明 | 精确度 | 性能 |
|------|------|--------|------|
| Query then Fetch（默认） | 各 Shard 独立计算评分，协调节点汇总 | 可能有误差（各 Shard 的 IDF 不同） | 快 |
| DFS Query then Fetch | 预先计算全局 IDF，再分发到各 Shard | 精确 | 慢（多一次 Round-Trip） |

**什么时候用 DFS？** 数据量不大、对评分精确度要求极高时。绝大多数场景用默认就够了。

## 正确使用方式

### 正确用法

**1. 搜索 + 聚合分开写（不是必须，但清晰）**

```json
GET /orders/_search
{
  "size": 10,           // 返回 10 条文档
  "query": {
    "range": { "create_time": { "gte": "2024-01-01" } }
  },
  "aggs": {
    "daily": {
      "date_histogram": {
        "field": "create_time",
        "calendar_interval": "day"
      }
    }
  }
}
```

**为什么正确**：ES 允许在同一请求里同时做搜索和聚合，非常方便。但如果只需要聚合结果（不需要原始文档），设 `"size": 0` 可以省掉 Fetch 阶段的开销。

**2. 使用 `filter` 代替 `must` 做精确过滤**

```json
// 较慢（要计算评分，不缓存）
"must": [ { "term": { "status": 1 } } ]

// 较快（不计算评分，结果会被缓存）
"filter": [ { "term": { "status": 1 } } ]
```

**为什么正确**：`status=1` 这种精确过滤不需要评分，`filter` 上下文不计算评分，且结果可以被 BitSet 缓存，性能更好。

**3. 使用 `keyword` 字段做 Terms 聚合**

```json
// 错误：对 text 字段直接做 terms 聚合（会报异常或结果不准）
"aggs": {
  "by_author": {
    "terms": { "field": "author" }  // author 是 text 类型，会报错！
  }
}

// 正确：用 .keyword 子字段
"aggs": {
  "by_author": {
    "terms": { "field": "author.keyword" }
  }
}
```

**为什么正确**：text 字段被分词了，聚合会在"词项"上分组（比如"张三"被分成"张"和"三"，聚合结果也是"张"和"三"，没意义）。`keyword` 字段保留原始值，适合分组。

### 错误用法及后果

**错误1：深度分页用 `from + size`**

```json
GET /books/_search
{
  "from": 10000,
  "size": 10
}
```

**后果**：每个 Shard 要准备 `from + size` 条数据，协调节点要汇总 `shard数 × (from + size)` 条再排序。翻页越深，性能越差。

**修复**：用 `search_after`（推荐）或 `scroll`（适合导出）。

**错误2：聚合的 `size` 设置太大**

```json
"aggs": {
  "by_word": {
    "terms": { "field": "content", "size": 100000 }  // 返回 10 万条聚合结果！
  }
}
```

**后果**：内存暴涨（要在内存里维护 10 万个 Bucket），可能导致 OOM。

**修复**：`size` 设置合理值（10~100），或改用 `sampler` 聚合限制样本数。

## 边界情况和坑

### 坑1：聚合结果不准确（近似算法）

**现象**：`terms` 聚合返回的 Top N，有时和实际的全量 Top N 有偏差。

**原因**：每个 Shard 只返回本 Shard 的 Top N，协调节点汇总时可能遗漏。比如某个词在 Shard-1 排第 101 名（没被上报），但在全局排第 10 名。

**解决**：

```json
"aggs": {
  "by_category": {
    "terms": {
      "field": "category.keyword",
      "size": 10,
      "shard_size": 100  // 每个 Shard 返回 Top 100，减小误差
    }
  }
}
```

### 坑2：`fielddata` 开启后内存爆炸

```json
// 对 text 字段做聚合，ES 会要求开启 fielddata（非常耗内存）
PUT /books/_mapping
{
  "properties": {
    "content": {
      "type": "text",
      "fielddata": true  // 警告：非常耗内存！
    }
  }
}
```

**后果**：`fielddata` 要把倒排索引**反转**（变成正排）存在内存里，大字段可能直接 OOM。

**修复**：永远不要对 text 字段开启 `fielddata`，用 `keyword` 子字段代替。

### 坑3：查询里有 `"*"` 通配符，性能极差

```json
GET /books/_search
{
  "query": {
    "wildcard": { "title": "*搜索*" }  // 通配符在前，无法使用倒排索引
  }
}
```

**后果**：要扫描所有词项，性能等同于全表扫描。

**修复**：用 `match` 查询（会用倒排索引），或考虑 ngram 分词器支持前缀/中缀搜索。
