# EXPLAIN 执行计划怎么看？哪些字段最重要？

> ⚠️ **先盲答**：EXPLAIN 是什么？它能告诉我们什么信息？

---

## 盲答引导

1. EXPLAIN 的输出有哪些关键字段？—— 至少说出 5 个
2. `type` 字段的取值有哪些？性能从好到差怎么排？
3. `key` 和 `possible_keys` 的区别是什么？
4. `rows` 字段代表什么？它越小越好吗？

---

## 知识链提示

```
EXPLAIN 执行计划
  → [[EXPLAIN执行计划]]
    → 核心字段
      → id：查询序号，越大越先执行（子查询）
      → select_type：查询类型（SIMPLE / PRIMARY / SUBQUERY / DERIVED）
      → table：访问的表
      → partitions：命中哪些分区
      → type ⭐（最重要）：访问类型
        → system > const > eq_ref > ref > range > index > ALL
        → const：主键/唯一索引等值查询，最多返回一行
        → ref：非唯一索引等值查询，可能多行
        → range：索引范围扫描（BETWEEN / IN / > <）
        → index：全索引扫描（比 ALL 好，因为索引文件通常比数据文件小）
        → ALL：全表扫描，最差
      → possible_keys：可能使用的索引
      → key ⭐：实际使用的索引（NULL = 没走索引！）
      → key_len：索引使用的字节数（可判断是否用了联合索引的全部列）
      → ref：索引的哪些列被使用了
      → rows ⭐：预估扫描行数（越小越好）
      → filtered：存储引擎返回的数据在经过过滤后，剩下多少满足查询条件的比例
      → Extra ⭐：附加信息
        → Using index：覆盖索引，不需要回表
        → Using where：在存储引擎之后，Server 层做过滤
        → Using filesort：需要额外排序（ORDER BY 没走索引）
        → Using temporary：需要临时表（GROUP BY 没走索引）
    → 优化目标
      → type 至少到 range，最好到 ref
      → key 不为 NULL
      → Extra 没有 Using filesort / Using temporary
```

---

## 核心追问

| 追问 | 考点 |
|------|------|
| type=index 和 type=ALL 有什么区别？ | index 扫的是索引，ALL 扫的是数据 |
| 覆盖索引在 EXPLAIN 里怎么看出来？ | Extra: Using index |
| key_len 怎么算出来的？ | 各列最大长度 + NULL 标记（1字节）+ 变长字段标记 |
| 为什么有时候 possible_keys 有值但 key 是 NULL？ | 优化器判断全表扫描更快 |

---

## 参考答案要点

**最重要 4 个字段**：`type`、`key`、`rows`、`Extra`。

**type 性能排序**（记住这个顺序）：
```
system ≈ const > eq_ref > ref > range > index > ALL
  ↑                                        ↑
最优                                    最差（全表扫描）
```

**Extra 里的危险信号**：
- `Using filesort`：需要额外排序，考虑给 ORDER BY 建索引
- `Using temporary`：需要临时表，考虑给 GROUP BY 建索引

---

## 下一步

打开 [[EXPLAIN执行计划]]，对比 [[索引设计原则]]，补充链接：「EXPLAIN 是优化 SQL 的第一步——先看 type 是不是 ALL，再看 Extra 有没有 filesort/temporary，最后看 rows 估算是否合理」。
