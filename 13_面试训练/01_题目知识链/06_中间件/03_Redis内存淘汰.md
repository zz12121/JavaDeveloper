# Redis 内存淘汰策略有哪些？

> ⚠️ **先盲答**：Redis 内存满了（maxmemory 达到）会怎样？有哪些淘汰策略？

---

## 盲答引导

1. Redis 可以作为缓存，也可以作为数据库—— 淘汰策略在这两种场景有什么不同？
2. 8 种淘汰策略分别是什么？—— 按「过期键 / 全部键」+「LRU / LFU / random / TTL」组合
3. LRU 和 LFU 的区别是什么？—— 最近最少用 vs 最不常用
4. 为什么 Redis 不用真实的 LRU（用近似 LRU）？—— 性能 + 内存

---

## 知识链提示

```
Redis 内存淘汰
  → [[Redis内存淘汰策略]]
    → 8 种策略（maxmemory-policy）
      → noeviction（默认）：不淘汰，写满报错
      → 只淘汰设置了过期时间的键
        → volatile-lru：最近最少用
        → volatile-lfu：最不常用
        → volatile-random：随机
        → volatile-ttl：TTL 最小的先淘汰
      → 淘汰所有键（不管有没有设置过期时间）
        → allkeys-lru
        → allkeys-lfu
        → allkeys-random
    → LRU vs LFU
      → LRU（Least Recently Used）：按「最近访问时间」淘汰
        → 缺点：短时间内大量冷数据可能被误认为热数据
      → LFU（Least Frequently Used，Redis 4.0+）：按「访问频率」淘汰
        → 用计数器记录访问次数，随时间衰减
        → 更适合访问模式有热点的场景
    → 近似 LRU（Redis 的实现）
      → 不维护全部键的 LRU 链表（内存开销大）
      → 随机采样 N 个键（默认 5 个），淘汰其中 LRU 最大的
      → 效果接近真实 LRU，内存开销小
```

---

## 核心追问

| 追问 | 考点 |
|------|------|
| allkeys-lru 和 volatile-lru 怎么选？ | 只做缓存用 allkeys，持久化数据用 volatile |
| LFU 的计数器怎么衰减的？ | 随时间指数衰减（1 分钟没访问 → 减半）|
| Redis 内存达到 maxmemory，新的写请求会阻塞吗？ | 会返回 OOM 错误（noeviction 时）|
| 如何监控 Redis 内存使用？ | INFO memory / redis-cli --stat |

---

## 参考答案要点

**8 种策略速记**：
- `noeviction`：不淘汰（默认）
- `volatile-*`：只淘汰带过期时间的
- `allkeys-*`：淘汰所有键
- `*-lru / *-lfu / *-random / *-ttl`：按不同算法

**LRU vs LFU**：
- LRU：看「多久没访问」
- LFU：看「访问频率」（更准确反映热点）

---

## 下一步

打开 [[Redis内存淘汰策略]]，补充 `[[双向链接]]`：「LRU 和 LFU 的核心区别在于——LRU 只关心『最近』，LFU 关心『频率』，后者对热点数据的判断更准确」。
