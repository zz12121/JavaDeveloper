# InnoDB 的锁机制有哪些？Next-Key Lock 是什么？

> ⚠️ **先盲答**：InnoDB 有哪些锁？行锁和表锁分别是什么？

---

## 盲答引导

1. InnoDB 支持**行锁**还是**表锁**？跟 MyISAM 有什么区别？
2. 行锁有哪几种类型？共享锁和排他锁分别是什么场景用？
3. 什么是**间隙锁（Gap Lock）**？它锁的是什么？
4. Next-Key Lock = 行锁 + 间隙锁，它解决了什么问题？

---

## 知识链提示

```
InnoDB 锁机制
  → [[06_数据库/03_事务与锁/InnoDB锁机制]]
    → 按粒度分
      → 表锁：锁整张表（MyISAM 只支持表锁）
      → 行锁：锁索引记录（InnoDB 支持，MyISAM 不支持）
        → 注意：InnoDB 行锁是**锁索引**，如果 WHERE 没走索引 → 锁全表！
    → 按模式分（行锁）
      → 共享锁（S 锁）：SELECT ... LOCK IN SHARE MODE → 读锁，别人可读不可写
      → 排他锁（X 锁）：SELECT ... FOR UPDATE / UPDATE / DELETE → 写锁，别人不可读不可写
    → 三种行锁算法
      → 记录锁（Record Lock）：锁索引记录本身
      → 间隙锁（Gap Lock）：锁索引记录之间的间隙，防止其他事务插入
      → Next-Key Lock = Record Lock + Gap Lock（默认算法，RR 级别）
        → 锁的是「当前记录 + 前面的间隙」
        → 解决了幻读问题
    → 加锁规则（经典）
      → 唯一索引 + 等值查询 → 记录锁（只锁这一行）
      → 范围查询 / 非唯一索引 → Next-Key Lock
```

---

## 核心追问

| 追问 | 考点 |
|------|------|
| 为什么 InnoDB 的 RR 级别能解决幻读？ | Next-Key Lock |
| WHERE 条件没走索引，InnoDB 会怎样？ | 锁全表（所有行都被加锁） |
| 死锁在 InnoDB 里常见吗？怎么排查？ | 看 `SHOW ENGINE INNODB STATUS` |
| 间隙锁锁的是「值」还是「范围」？ | 锁的是索引记录之间的开区间 |

---

## 参考答案要点

**三种行锁算法**：
- Record Lock：锁索引记录本身
- Gap Lock：锁间隙，防止插入
- Next-Key Lock = Record + Gap（默认，RR 级别）

**Next-Key Lock 解决幻读**：
```
SELECT * FROM orders WHERE amount > 100 FOR UPDATE;
→ 锁住 amount > 100 的所有记录 + 它们前面的间隙
→ 其他事务无法插入 amount > 100 的新记录 → 幻读解决
```

**加锁核心规则**：走索引才加行锁，不走索引 → 锁全表。

---

## 下一步

打开 [[06_数据库/03_事务与锁/InnoDB锁机制]]，对比 [[02_并发编程/11_死锁与活锁/死锁与活锁]]，补充链接：「InnoDB 的 Next-Key Lock 是 RR 级别下防止幻读的关键——它锁住记录和间隙，让其他事务无法插入新记录」。
