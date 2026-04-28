# HTTP协议详解

## 这个问题为什么存在？

> HTTP 是明文传输，中间人可以窃听、篡改、冒充。问题是：**怎么在明文协议上构建安全传输，同时性能又不能太差？**

HTTPS = HTTP + TLS（以前叫 SSL）。在 HTTP 和 TCP 之间加了一层**加密 + 认证 + 完整性保护**。

## HTTP 的核心机制

### HTTP/1.0 → 1.1 → 2.0 → 3.0 演进

```
HTTP/1.0：短连接，每个请求一个 TCP 连接
HTTP/1.1：持久连接（Connection: keep-alive），管道化（Pipelining）
HTTP/2：多路复用（一个 TCP 连接并发多个请求），头部压缩（HPACK）
HTTP/3：基于 UDP（QUIC），解决 TCP 队头阻塞
```

### HTTP/1.1 的队头阻塞（Head-of-Line Blocking）

```
连接1：[请求1 ][响应1    ]  ← 必须等响应1完成才能发请求2
连接2：[请求2][响应2]
连接3：[请求3][响应3]  ← 浏览器对每个域名最多开 6 个连接
```

HTTP/2 用**多路复用**解决：一个 TCP 连接上并发多个请求/响应（用 Stream ID 区分）。

### Cookie vs Session

```
Cookie：存在客户端（浏览器）
  - 每次请求自动带上（HTTP 头部）
  - 大小受限（4KB）
  - 可被客户端修改（不安全）

Session：存在服务端
  - Session ID 存在 Cookie 里
  - 服务端存数据（Redis / 内存）
  - 客户端只存一个 ID（安全）
```

## HTTPS / TLS 握手

### TLS 1.2 握手流程（2-RTT）

```
客户端 → Server Hello（支持的密码套件）─────────────▶
                                                  服务器
         ◀──── Server Hello（选定密码套件）+ 证书 ─────
                                                   
         → Client Key Exchange（用证书公钥加密 预主密钥）─▶
         → Change Cipher Spec（后面开始加密）─────────▶
         → Finished（加密后的握手验证）─────────────▶
                                                   
         ◀──── Change Cipher Spec + Finished ────────────
                                                   
         → HTTP 请求（加密）───────────────────────▶
```

**ECDHE 密钥交换（推荐）**：

```
客户端生成：随机数 Ra
服务器生成：随机数 Rb + 椭圆曲线参数
双方交换：椭圆曲线公钥
   → 双方各自算出相同的预主密钥（ECDHE 特性）
   → 即使私钥泄露，历史会话也无法解密（前向安全性 PFS）
```

### 前向安全性（PFS）

```
非 PFS（RSA 密钥交换）：
  私钥泄露 → 历史所有会话都能解密（因为预主密钥用私钥加密的）

PFS（ECDHE 密钥交换）：
  每次握手用临时密钥对（Ephemeral）
  私钥泄露 → 历史会话无法解密（临时密钥已丢弃）
```

### TLS 1.3 握手（1-RTT）

```
客户端 → Client Hello（密码套件 + 密钥共享）────────────▶
                                                   
         ◀──── Server Hello + 证书 + Finished ────────────
                                                   
         → Finished ────────────────────────────────▶
```

**比 TLS 1.2 少一次往返**：Server Hello 直接带上证书和 Finished（1-RTT）。

### 证书链验证

```
浏览器收到证书：
  1. 用 CA 公钥验证证书签名
  2. 检查证书有效期
  3. 检查证书是否被吊销（CRL / OCSP）
  4. 检查域名匹配（SAN 或 CN）
```

## 它和相似方案的本质区别是什么？

| | HTTP/1.1 | HTTP/2 | HTTP/3（QUIC） |
|---|---|---|---|
| 传输层 | TCP | TCP | UDP |
| 队头阻塞 | 有（TCP 层） | 有（TCP 层） | ❌ 无（UDP 无队头阻塞）|
| 多路复用 | ❌ | ✅（Stream ID） | ✅（Stream ID） |
| 头部压缩 | ❌ | HPACK | QPACK |
| 握手 RTT | 1（TCP）+ 0 | 1（TCP）+ 0 | 1（QUIC 内置 TLS）|

### TLS vs IPSec vs WireGuard

| | TLS（HTTPS） | IPSec（VPN） | WireGuard |
|---|---|---|---|
| 层级 | 应用层 | 网络层 | 网络层 |
| 加密范围 | 仅应用数据 | 整个 IP 包 | 整个 IP 包 |
| 配置复杂度 | 低（证书） | 高（IKE） | 低（公钥） |
| 应用 | HTTPS、API | VPN | VPN、隧道 |

## 正确使用方式

### Nginx 配置 HTTPS（TLS 1.2+）

```nginx
server {
    listen 443 ssl http2;
    server_name example.com;

    ssl_certificate /path/to/cert.pem;
    ssl_certificate_key /path/to/key.pem;

    ssl_protocols TLSv1.2 TLSv1.3;  # 不用 TLS 1.0/1.1
    ssl_ciphers HIGH:!aNULL:!MD5;   # 强加密套件
    ssl_prefer_server_ciphers on;

    # HSTS（强制 HTTPS）
    add_header Strict-Transport-Security "max-age=31536000" always;
}
```

### Java 客户端信任自签名证书（开发环境）

```java
// ⚠️ 生产环境不要用，自签名证书有中间人攻击风险
TrustManager[] trustAll = new TrustManager[] {
    new X509TrustManager() {
        public void checkClientTrusted(X509Certificate[] chain, String authType) {}
        public void checkServerTrusted(X509Certificate[] chain, String authType) {}
        public X509Certificate[] getAcceptedIssuers() { return new X509Certificate[]{}; }
    }
};
SSLContext sc = SSLContext.getInstance("TLS");
sc.init(null, trustAll, new SecureRandom());
HttpsURLConnection.setDefaultSSLSocketFactory(sc.getSocketFactory());
```

## 边界情况和坑

### TLS 握手失败的常见原因

1. **证书过期**：检查 `openssl x509 -in cert.pem -text -noout`
2. **SNI（Server Name Indication）**：一个 IP 上多个域名，必须在 Client Hello 里带上域名
3. **证书链不完整**：中间 CA 证书没装，浏览器不认

### HTTP/2 的 TCP 层队头阻塞

HTTP/2 解决了**应用层**的队头阻塞，但**TCP 层**的丢包仍然会阻塞所有 Stream。

```
TCP 丢了一个包 → 所有 HTTP/2 Stream 都等重传
```

HTTP/3（QUIC）在 UDP 上实现，彻底解决队头阻塞。

### 证书更新的零停机

```
旧证书快过期 → 申请新证书（Let's Encrypt）
              → 替换证书文件
              → Nginx reload（不中断连接）
```

用 `certbot` 自动更新：
```bash
certbot renew --dry-run  # 测试自动更新
```

## 我的理解

HTTPS 的核心价值是**加密 + 认证 + 完整性**。面试最常被追问的是：

1. **TLS 握手流程**（1.2 是 2-RTT，1.3 是 1-RTT）
2. **前向安全性（PFS）**：ECDHE 密钥交换，临时密钥对，私钥泄露也不影响历史会话
3. **HTTP/2 vs HTTP/3**：HTTP/2 仍有 TCP 队头阻塞，HTTP/3 用 QUIC（UDP）彻底解决
