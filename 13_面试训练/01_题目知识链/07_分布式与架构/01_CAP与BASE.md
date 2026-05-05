# CAP 定理和 BASE 理论是什么？

> ⚠️ **先盲答**：CAP 是什么？三个字母分别代表什么？分布式系统只能同时满足两个？

---

## 盲答引导

1. CAP 的三个特性是什么？—— Consistency / Availability / Partition Tolerance
2. 为什么 P（分区容错性）是必须满足的？—— 网络分区不可避免
3. CP 系统和 AP 系统分别是什么？举几个例子
4. BASE 理论的核心是什么？—— Basically Available / Soft state / Eventually consistent

---

## 知识链提示

```
CAP 与 BASE
  → [[08_分布式与架构/01_分布式基础/CAP定理与BASE理论]]
    → CAP 三选二
      → C（Consistency）：所有节点同一时刻看到相同数据
      → A（Availability）：每个请求都能在有限时间内得到响应
      → P（Partition Tolerance）：分区（网络故障）发生时，系统仍能运行
      → 现实：P 必须满足，网络分区不可避免 → 只能在 C 和 A 之间权衡
    → CP 系统
      → ZooKeeper / HBase / Redis Cluster（某些场景）
      → 牺牲可用性：分区时，可能部分节点不可用
    → AP 系统
      → Eureka / Cassandra / DynamoDB
      → 牺牲强一致性：分区时，各节点数据可能短暂不一致
  → [[08_分布式与架构/01_分布式基础/CAP定理与BASE理论]]
    → 核心理念：强一致性在分布式系统中代价太高 → 接受最终一致性
    → 三要素
      → Basically Available：保证核心功能可用（降级）
      → Soft State：允许数据存在中间状态（不要求每时刻都一致）
      → Eventually Consistent：经过一段时间后，数据最终一致
    → BASE vs ACID
      → ACID：强一致性，事务是原子的（传统单机数据库）
      → BASE：最终一致性，性能优先（分布式系统）
```

---

## 核心追问

| 追问 | 考点 |
|------|------|
| Zookeeper 是 CP 还是 AP？ | CP，分区时牺牲可用性，Leader 选举期间不可用 |
| Redis 主从复制是 CAP 的哪个？ | AP（主从异步复制，不保证一致性） |
| BASE 理论中「最终一致性」是多久？ | 取决于业务允许的延迟，没有固定时间 |
| 为什么分布式系统必须选 P？ | 网络分区不可避免，放弃 P = 放弃分布式 |

---

## 参考答案要点

**CAP 本质**：P 必须满足 → 实际是在 C 和 A 之间选择。

| 系统类型 | 例子 | 特点 |
|---------|------|------|
| CP | ZooKeeper / HBase | 分区时 Leader 不可用，服务暂停 |
| AP | Eureka / Cassandra | 分区时各节点独立运行，数据最终一致 |

**BASE = 放弃强一致，换取可用性和性能**。

---

## 下一步

打开 [[08_分布式与架构/01_分布式基础/CAP定理与BASE理论]]，对比 [[08_分布式与架构/01_分布式基础/CAP定理与BASE理论]]，补充链接：「CAP 定理告诉我们「不能全都要」，BASE 理论告诉我们「放弃强一致也没那么可怕」——大多数互联网系统选择 AP + 最终一致性」。
