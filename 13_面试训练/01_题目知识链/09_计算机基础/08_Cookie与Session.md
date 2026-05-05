# 题目：Cookie 和 Session 的区别是什么？ 分布式 Session 是怎么做的？

---

## ⚠️ 先盲答

**不要看任何资料，用自己的话回答，写到纸上或心里默念也行。**

说出 Cookie 和 Session 各自存在哪里、能存什么数据、有什么大小限制。

---

## 盲答引导

1. Cookie 是存在浏览器还是服务器？Session 呢？
2. Cookie 的大小限制是多少？能存对象吗？
3. Session 的默认实现存在服务器内存里，这是什么意思？服务重启会怎样？
4. 分布式系统里（多台服务器），Session 怎么共享？有几种方案？
5. 为什么说「把 Session 存在 Redis 里」是目前最主流的方案？有什么坑？

---

## 知识链提示

这道题应该让你联想到：

- `[[Cookie机制]]` → 浏览器存储，每次请求自动带上
- `[[Session机制]]` → 服务器内存，用 SessionID（Cookie 里）查找
- `[[分布式Session]]` → Session 复制 / Session 粘连 / 集中存储（Redis）
- `[[JWT]]` → 不用 Session 的无状态认证方案
- `[[Session固定攻击]]` → 登录后不换 SessionID 的安全漏洞

---

## 核心追问

1. 如果浏览器禁用了 Cookie，Session 还能用吗？怎么传 SessionID？
2. Session 的默认超时时间是多少？怎么修改？
3. 用 Redis 存 Session，Key 怎么设计？TTL 怎么设置？
4. JWT（JSON Web Token）和 Session + Cookie 的核心区别是什么？各自适合什么场景？
5. 为什么说「Session 不适合移动互联网（App）」？App 里怎么做用户认证？

---

## 参考要点（盲答后再看）

<details>
<summary>点击展开</summary>

**Cookie vs Session**：

| | Cookie | Session |
|--|--------|---------|
| 存储位置 | 浏览器（客户端） | 服务器内存 / Redis |
| 大小限制 | 约 4KB（每个 Cookie） | 无限制（服务器内存够就行） |
| 数据类型 | 只能存字符串 | 可以存任意对象 |
| 安全性 | 较低（存在客户端，可被篡改） | 较高（存在服务器） |
| 传输开销 | 每次 HTTP 请求都带 Cookie | 只传 SessionID（存在 Cookie 里） |

**Session 工作流程**：

```
1. 第一次访问：
   服务器创建 Session → 生成 SessionID → 通过 Cookie 返回给浏览器
   （Set-Cookie: JSESSIONID=ABC123）

2. 后续访问：
   浏览器自动在请求头里带 Cookie: JSESSIONID=ABC123
   服务器根据 SessionID 找到对应的 Session 对象
```

**分布式 Session 方案**：

```
方案1：Session 复制（不推荐）
  - 每台服务器都复制全量 Session
  - 缺点：网络开销大，服务器内存占用高

方案2：Session 粘连（不推荐）
  - 负载均衡器固定把某用户请求路由到同一台服务器
  - 缺点：服务器宕机 → Session 丢失

方案3：集中存储（推荐 ★★★）
  - Session 存在 Redis / Memcached
  - 所有服务器都从 Redis 读写 Session
  - 优点：服务器无状态，可水平扩展
  - 缺点：多一次 Redis 查询（通常 1ms 内）
```

**JWT vs Session**：

```
Session + Cookie：
  - 有状态（服务器存 Session）
  - 适合传统 Web 应用（浏览器）

JWT（无状态）：
  - 服务器不存任何状态（Token 里包含所有信息）
  - 适合：移动互联网（App）/ 微服务 / 跨域 SSO
  - 缺点：Token 无法主动失效（只能等过期，或维护黑名单）
```

**浏览器禁用 Cookie 的应对**：

```java
// URL 重写（非常落伍的方式）
http://example.com/path;jsessionid=ABC123

// 现在主流：直接用 JWT（存在 localStorage，请求时放 Authorization 头）
fetch('/api/user', {
  headers: { 'Authorization': 'Bearer ' + jwtToken }
})
```

</details>

---

## 下一步

1. 盲答后，对比参考要点，找到卡壳的地方
2. 打开 `[[09_计算机基础/Cookie与Session]]` 主题文档
3. 在 Obsidian 里建双向链接
4. 在 `[[12_面试训练/每日一题跟踪表]]` 里勾选「今日完成」，打 1~5 分
