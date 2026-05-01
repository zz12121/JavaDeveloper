# DNS 域名解析

> **核心认知**：DNS（Domain Name System）是互联网的"电话簿"——人类记域名（www.baidu.com），机器需要 IP 地址（14.215.177.38），DNS 负责翻译。看似简单的一次查询，背后涉及递归、迭代、缓存、负载均衡等机制。

---

## 1. DNS 基础概念

### 1.1 域名层级结构

```
www.example.com.
│   │       │    └── 根域（Root Domain），用 "." 表示，全球 13 组根服务器
│   │       └────── 顶级域（TLD）：com / cn / org / net / edu / gov
│   └────────────── 二级域（SLD）：example.com
└────────────────── 三级域（子域）：www.example.com / mail.example.com
```

**域名的读取方向**：从右到左（从根域开始，逐级解析）。

### 1.2 DNS 服务器类型

| 服务器类型 | 职责 | 举例 |
|-----------|------|------|
| 根域名服务器 | 知道所有 TLD 服务器的地址 | 全球 13 组（A~M），实际通过 Anycast 部署数百台 |
| 顶级域名服务器 | 管理该 TLD 下的所有域名 | .com 服务器知道 example.com 的权威 DNS |
| 权威域名服务器 | 存储域名的最终记录（A/CNAME/MX） | example.com 的 NS 服务器 |
| 本地域名服务器 | 代理客户端发起查询，缓存结果 | 运营商 DNS（114.114.114.114）或公共 DNS（8.8.8.8） |

---

## 2. DNS 解析流程

### 2.1 完整解析过程

```
浏览器访问 www.example.com

  1. 查浏览器缓存
     ├── 命中 → 直接返回 IP
     └── 未命中 ↓

  2. 查操作系统缓存（hosts 文件 + DNS Client 缓存）
     ├── 命中 → 返回 IP
     └── 未命中 ↓

  3. 查本地域名服务器（LDNS）
     ├── LDNS 缓存命中 → 返回 IP
     └── 缓存未命中 ↓

  4. LDNS 向根域名服务器查询
     → 根服务器返回 .com 顶级域服务器的地址

  5. LDNS 向 .com 顶级域服务器查询
     → TLD 服务器返回 example.com 权威服务器的地址

  6. LDNS 向 example.com 权威服务器查询
     → 权威服务器返回 www.example.com 的 A 记录（IP 地址）

  7. LDNS 缓存结果，返回给客户端
  8. 客户端缓存结果
```

### 2.2 递归查询 vs 迭代查询

| 类型 | 说明 | 谁在做工作 |
|------|------|-----------|
| **递归查询** | 客户端问 LDNS："帮我解析 www.example.com"，LDNS 负责一路查到底 | LDNS（替客户端跑腿） |
| **迭代查询** | LDNS 问根服务器，根说"你去问 .com"；LDNS 问 .com，.com 说"你去问权威" | LDNS 自己一步步问 |

**实际流程**：客户端 → LDNS 是**递归**；LDNS → 根/TLD/权威 是**迭代**。

---

## 3. DNS 记录类型

| 记录类型 | 说明 | 举例 |
|---------|------|------|
| **A** | 域名 → IPv4 地址 | `www.example.com → 93.184.216.34` |
| **AAAA** | 域名 → IPv6 地址 | `www.example.com → 2606:2800:220:1:...` |
| **CNAME** | 域名 → 另一个域名（别名） | `cdn.example.com → cdn.provider.com` |
| **MX** | 邮件交换记录（邮件服务器） | `example.com → mail.example.com` |
| **NS** | 域名 → 权威 DNS 服务器 | `example.com → ns1.dnsprovider.com` |
| **TXT** | 文本记录（SPF、DKIM、域名验证） | `example.com → "v=spf1 include:..."` |
| **SRV** | 服务定位记录 | `_sip._tcp.example.com → 10 60 5060 sip.example.com` |
| **PTR** | IP → 域名（反向解析） | `93.184.216.34 → www.example.com` |
| **SOA** | 起始授权记录（区域管理信息） | 包含主 NS、管理员邮箱、序列号、刷新间隔等 |

**高频面试**：
- **A 记录 vs CNAME**：A 记录直接解析到 IP；CNAME 解析到另一个域名（不能用于根域名）
- **CNAME 链**：cdn.example.com → CDN 服务商域名 → CDN 节点 IP（最多建议 3~4 层）

---

## 4. DNS 缓存

### 4.1 多级缓存

```
浏览器 DNS 缓存（Chrome: chrome://net-internals/#dns）
  → 操作系统 DNS 缓存
    → 路由器 DNS 缓存
      → ISP 本地域名服务器缓存
        → 权威域名服务器（最终答案）
```

### 4.2 TTL（Time To Live）

每条 DNS 记录都有 TTL 值，表示缓存的有效时间：

```
TTL 太短 → DNS 查询频繁，增加延迟
TTL 太长 → IP 变更后生效慢（比如服务器迁移）

常见设置：
  - 正常业务：300s（5分钟）~ 3600s（1小时）
  - DNS 故障切换：60s（快速切换）
  - 极少变动的记录：86400s（1天）
```

### 4.3 如何清除 DNS 缓存

```bash
# Windows
ipconfig /flushdns

# macOS
sudo dscacheutil -flushcache
sudo killall -HUP mDNSResponder

# Linux (systemd-resolved)
sudo systemd-resolve --flush-caches

# Linux (nscd)
sudo nscd -i hosts
```

---

## 5. DNS 负载均衡

### 5.1 DNS 轮询（Round Robin）

最简单的负载均衡方式——一个域名对应多个 IP：

```
; example.com 的 DNS 记录
example.com.  300  IN  A  192.168.1.1
example.com.  300  IN  A  192.168.1.2
example.com.  300  IN  A  192.168.1.3
```

DNS 服务器返回 IP 的顺序轮转，客户端依次访问不同服务器。

**缺点**：
1. 不考虑服务器实际负载（某台服务器可能已经很忙了）
2. DNS 缓存导致分配不均（运营商缓存、浏览器缓存会让同一客户端一直访问同一 IP）
3. 无法感知服务器故障（DNS 不知道服务器是否存活）

### 5.2 智能 DNS（GeoDNS）

根据客户端的地理位置返回不同的 IP：

```
北京用户访问 → 解析到北京机房 IP
上海用户访问 → 解析到上海机房 IP
海外用户访问 → 解析到海外 CDN 节点
```

**实现方式**：
- 运营商提供：如阿里云 DNS、Cloudflare
- 自建：Bind 的 `view` 功能 + GeoIP 数据库

### 5.3 权重 DNS

为不同的记录设置权重：

```
example.com.  300  IN  A  192.168.1.1  ; 权重 70%（主）
example.com.  300  IN  A  192.168.1.2  ; 权重 30%（备）
```

---

## 6. DNS 安全问题

### 6.1 DNS 劫持

**原理**：在 DNS 查询的某个环节（如 ISP、路由器、恶意软件），将域名解析到恶意 IP。

```
正常：www.bank.com → 93.184.216.34
劫持：www.bank.com → 1.2.3.4（钓鱼网站）
```

**防御**：
- 使用可信的 DNS 服务器（8.8.8.8、114.114.114.114、阿里 DNS 223.5.5.5）
- 使用 HTTPS（即使 DNS 被劫持，TLS 证书验证会失败）
- DNSSEC（DNS Security Extensions）

### 6.2 DNS 污染

**原理**：在 DNS 查询的路径上（通常在防火墙/GFW 层），伪造 DNS 响应包，让客户端收到错误的解析结果。

**与 DNS 劫持的区别**：
- 劫持：修改 DNS 服务器上的记录
- 污染：不修改记录，而是在传输过程中插入伪造响应

### 6.3 DNS 放大攻击（DNS Amplification Attack）

**原理**：利用 DNS 的 UDP 特性和 EDNS0（支持大响应包），攻击者伪造源 IP 向 DNS 服务器发送查询请求，DNS 服务器将大量响应数据发送到被攻击的目标。

```
攻击者 → 发送小查询（伪造源IP=受害者） → 开放 DNS 递归服务器
                                                 ↓
受害者 ← 收到大量 DNS 响应数据（放大 50~100 倍）
```

**防御**：
- DNS 服务器关闭递归查询（仅允许内部使用）
- 限制响应速率
- 启用 DNSSEC

### 6.4 DNSSEC

**原理**：对 DNS 响应进行数字签名，客户端可以验证响应是否被篡改。

```
DNSSEC 的签名链：
根域名服务器的公钥 → 验证 TLD 服务器的签名
TLD 服务器的公钥 → 验证权威服务器的签名
权威服务器的公钥 → 验证具体 DNS 记录的签名
```

---

## 7. HTTPDNS

### 7.1 传统 DNS 的问题

1. **缓存劫持**：运营商 DNS 缓存被污染
2. **调度不准确**：LDNS 的 IP 不一定代表客户端的真实位置
3. **解析延迟**：递归查询需要多次网络往返

### 7.2 HTTPDNS 原理

**绕过传统 DNS，直接通过 HTTP/HTTPS 协议向 DNS 服务商查询**：

```
传统 DNS：客户端 → UDP:53 → LDNS → 根 → TLD → 权威
HTTPDNS：客户端 → HTTPS:443 → HTTPDNS 服务（如阿里云/腾讯云）→ 权威
```

**优势**：
1. 使用 HTTPS，防止劫持和污染
2. 服务端可以获取客户端真实 IP，精确调度
3. 跨平台统一调度（App 内嵌 HTTPDNS SDK）

**缺点**：
1. 需要接入 SDK，浏览器无法使用
2. 增加了 DNS 服务商的依赖

---

## 8. 常用 DNS 命令

```bash
# dig 查询（推荐，信息最全）
dig www.example.com
dig www.example.com +trace          # 查看完整解析过程
dig www.example.com @8.8.8.8        # 指定 DNS 服务器
dig example.com MX                  # 查询 MX 记录
dig example.com ANY                 # 查询所有记录

# nslookup（简单查询）
nslookup www.example.com
nslookup -type=NS example.com       # 查询 NS 记录

# host
host www.example.com

# macOS 专用
dscacheutil -q host www.example.com
```

---

## 9. 面试高频问题

### Q1: DNS 用的是 TCP 还是 UDP？

**答**：默认使用 **UDP（端口 53）**。
- DNS 查询通常数据量很小（< 512 字节），UDP 更快
- **区域传输**（主从 DNS 同步数据）使用 TCP，因为数据量大，需要可靠传输
- 当 UDP 响应超过 512 字节时，会截断并标记 TC 位，客户端改用 TCP 重试

### Q2: 为什么 DNS 这么容易出问题？如何排查？

**答**：DNS 是多级缓存 + 递归/迭代查询，任何一环都可能出问题。
排查步骤：
1. `nslookup` 或 `dig` 确认是否能解析
2. 检查 `/etc/resolv.conf` 或系统 DNS 设置
3. 清除本地 DNS 缓存
4. 检查防火墙是否阻止了 UDP:53
5. 使用 `dig +trace` 追踪完整解析链路

### Q3: 什么是 DNS 预解析？有什么用？

**答**：
```html
<!-- 让浏览器提前解析域名，减少后续请求的 DNS 延迟 -->
<link rel="dns-prefetch" href="//cdn.example.com">
```
页面中如果有第三方资源（CDN、统计、广告），浏览器在解析当前页面时就可以预先解析这些域名，用户点击时就不需要再等 DNS 查询。

### Q4: DNS 负载均衡和 Nginx 负载均衡有什么区别？

**答**：

| 维度 | DNS 负载均衡 | Nginx 负载均衡 |
|------|------------|---------------|
| 层级 | 应用层之前（域名解析阶段） | 应用层（HTTP 请求阶段） |
| 粒度 | 粗（按域名/IP 分配） | 细（按请求 URL/Header 分配） |
| 健康检查 | 无法感知服务状态 | 可以主动检查 |
| 灵活性 | TTL 限制切换速度 | 实时切换 |
| 适用场景 | 全局负载均衡（跨机房/跨地域） | 单机房内多实例负载均衡 |

> **面试加分项**：能画出完整的 DNS 解析流程图（浏览器缓存→OS缓存→LDNS→根→TLD→权威），能解释 HTTPDNS 的原理和适用场景。
