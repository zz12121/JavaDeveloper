# Redis 在项目中常用的应用场景有哪些？

> ⚠️ **先盲答**：Redis 除了做缓存，还能干什么？

---

## 盲答引导

1. Redis 做缓存时，和 MySQL 的配合模式是什么？—— Cache Aside / Read Through / Write Through
2. Redis 做分布式锁，有哪些坑？—— SETNX + TTL + 续期
3. Redis 做 Session 共享，和 Memcached 比有什么优势？
4. Redis 的 BitMap / HyperLogLog / Geo 分别适合什么场景？

---

## 知识链提示

```
Redis 应用模式
  → [[07_中间件/01_Redis/Redis应用模式]]
    → 缓存模式
      → Cache Aside（旁路缓存，最常用）
        → 读：先读缓存 → 命中返回，未命中 → 读 DB → 写缓存 → 返回
        → 写：先写 DB → 删除缓存（不是更新）
          → 为什么删除而不是更新？ → 更新缓存可能产生脏数据
      → Read Through：缓存负责读 DB（应用层无感知）
      → Write Through：写 DB + 写缓存（同步，性能差）
    → 分布式锁
      → [[08_分布式与架构/03_分布式锁/Redis分布式锁实现]] → SETNX + TTL + 看门狗续期
    → 会话存储（Session）
      → 分布式环境下，多台应用服务器共享 Session
      → 替换黏性 Session（Stick Session）
      → Spring Session + Redis
    → 计数器
      → INCR：微博点赞数 / 接口调用次数
      → DECR：库存扣减（注意：不是原子，先 DECR 再判断是否 < 0）
    → 排行榜
      → ZSet：ZINCRBY + ZREVRANGE（粉丝数/游戏积分）
    → 分布式队列
      → List：LPUSH + BRPOP（阻塞 pop）
    → BitMap / HyperLogLog / Geo
      → BitMap：签到 / 用户在线状态（节省内存）
      → HyperLogLog：UV 统计（误差 ~0.81%，内存极小）
      → Geo：附近的人 / 附近商家
```

---

## 核心追问

| 追问 | 考点 |
|------|------|
| 为什么写操作是「删除缓存」而不是「更新缓存」？ | 并发下可能脏缓存（Thread A 写 DB → Thread B 写缓存 → Thread A 删除 → 脏）|
| 缓存穿透怎么解决？ | 布隆过滤器 + 缓存空值（null）|
| 缓存击穿怎么解决？ | 互斥锁（SETNX）/ 热点数据永不过期 |
| 缓存雪崩怎么解决？ | TTL 随机 + 热点数据永不过期 + 多级缓存 |

---

## 参考答案要点

**缓存模式的黄金法则**：写操作**删除缓存**（不是更新），读操作**先缓存后数据库**。

**缓存三问题**：
- **穿透**：布隆过滤器挡掉不存在的数据
- **击穿**：热点数据过期瞬间大量请求打 DB → 互斥锁
- **雪崩**：大量数据同时过期 → TTL 随机 + 热点永不过期

---

## 下一步

打开 [[07_中间件/01_Redis/Redis应用模式]]，对比 [[11_实战专题/04_Redis缓存设计实战]]（如果有的话），补充链接：「缓存三剑客（穿透/击穿/雪崩）的共同本质是——缓存失效时，请求直接打 DB，雪崩更是大量缓存同时失效」。
