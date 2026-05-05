# MVCC 的实现原理是什么？它解决了什么问题？

> ⚠️ **先盲答**：MVCC 是什么？它解决了什么问题？怎么实现的？

---

## 盲答引导

1. MVCC 的全称是什么？它的核心思想是什么？
2. 快照读、当前读 分别是什么？能举个例子吗？
3. undo log 在 MVCC 里扮演什么角色？
4. Read View 是什么？它怎么判断一行数据的哪个版本对当前事务可见？

---

## 知识链提示

```
MVCC 多版本并发控制
  → [[06_数据库/03_事务与锁/MVCC多版本并发控制]]
    → 核心思想：不加锁的读，通过版本链实现
      → 每行数据有多个历史版本（undo log 链）
      → 读操作读哪个版本 → 由 Read View 决定
    → 核心数据结构
      → 隐藏列：trx_id（最后修改的事务ID）、roll_pointer（指向 undo log）
      → undo log 链：旧版本数据通过 roll_pointer 串联
      → Read View：当前事务能看到的「活跃事务列表」
        → m_ids：当前活跃的（未提交的）事务 ID 列表
        → min_trx_id：最小活跃事务 ID
        → max_trx_id：下一个将被分配的事务 ID
        → creator_trx_id：创建 Read View 的事务 ID
    → 可见性判断算法
      → trx_id == creator_trx_id → 自己改的，可见
      → trx_id < min_trx_id → 已提交，可见
      → trx_id >= max_trx_id → 未来事务，不可见
      → trx_id 在 m_ids 里 → 活跃事务未提交，不可见
      → 否则 → 已提交，可见
    → RC vs RR 的区别
      → RC：每次读都生成新的 Read View → 能读到其他事务已提交的修改
      → RR：事务开始时生成一次 Read View，整个事务用同一个 → 可重复读
```

---

## 核心追问

| 追问 | 考点 |
|------|------|
| undo log 会不会无限增长？ | purge 线程清理已无引用的 undo log |
| 当前读（SELECT ... FOR UPDATE）走 MVCC 吗？ | 不走，走锁 |
| 为什么 RR 级别下还会出现幻读？ | 当前读不受 MVCC 保护 |
| MySQL 8.0 对 MVCC 有什么优化？ | 暂无重大影响 |

---

## 参考答案要点

**MVCC 本质**：一行数据保留多个历史版本，读操作根据 Read View 判断该读哪个版本。

**Read View 判断可见性**：
```
数据版本 trx_id = 100
Read View: m_ids={100, 101}, min=100, max=102

→ trx_id(100) 在 m_ids 里 → 未提交 → 不可见 → 顺着 undo log 链找上一个版本
```

**RC vs RR**：
- RC：每次 SELECT 都生成新 Read View → 能读到别人已提交的
- RR：事务开始时生成 Read View，整个事务不变 → 可重复读

---

## 下一步

打开 [[06_数据库/03_事务与锁/MVCC多版本并发控制]]，对比 undo log（如果知识库有这个节点），补充链接：「MVCC 靠 undo log 版本链 + Read View 实现非锁定读，RC 和 RR 的核心区别就是 Read View 的生成时机」。
