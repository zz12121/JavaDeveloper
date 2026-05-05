# JWT 与 OAuth2

> 无状态认证（JWT）解决了 Session 在分布式环境下的共享难题，OAuth2 则定义了"第三方应用如何安全地获取用户授权"的标准流程。理解这两者的本质区别——JWT 是 Token 格式，OAuth2 是授权协议——是做技术选型的关键。

---

## 这个问题为什么存在？

### Session 在分布式环境下的困境

传统 Web 使用 Session-Cookie 认证：用户登录后，服务端创建 Session 存在内存中，客户端持有 Session ID（Cookie）。

```
单体应用（1 台服务器）：
  用户 → Tomcat A → Session 在 Tomcat A 内存中 → OK

分布式应用（多台服务器）：
  用户 → Nginx → Tomcat A（登录，Session 在 A）
  用户 → Nginx → Tomcat B（Session 不在 B → 未认证！）
```

解决 Session 共享的常见方案（Spring Session + Redis）需要：
1. 额外部署 Redis 集群
2. 每次请求都查 Redis 获取 Session → 网络开销
3. Session 的序列化/反序列化 → CPU 开销
4. Redis 本身需要维护高可用

JWT 提供了一种完全不同的思路：**不存 Session，把用户信息编码进 Token 本身**。服务端不需要存储任何状态，收到 Token 后自己验证签名就能确认用户身份——天然支持分布式。

### 第三方登录的授权难题

"用微信登录"这个需求看起来简单，实际涉及一个根本性的安全矛盾：

```
矛盾：
  用户要授权第三方应用访问自己的数据（头像、昵称...）
  但用户不能把自己的微信密码告诉第三方应用（那太危险了）
  也不能把访问令牌直接给第三方（无法控制权限范围和有效期）

  → 需要一个"授权中间人"——OAuth2 就是这个标准
```

---

## 它是怎么解决问题的？

### JWT 的结构：自包含的用户凭证

```
Header.Payload.Signature

eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIiwibmFtZSI6IkpvaG4gRG9lIiwiaWF0IjoxNTE2MjM5MDIyfQ.SflKxwRJSMeKKF2QT4fwpMeJf36POk6yJV_adQssw5c
│                       │                                                                  │
Header (Base64)         Payload (Base64)                                                    Signature
```

三部分各自用 Base64URL 编码，中间用 `.` 分隔：

**Header** — 签名算法声明：
```json
{
    "alg": "HS256",   // 签名算法：HS256(对称)/RS256(非对称)/ES256
    "typ": "JWT"       // 固定为 JWT
}
```

**Payload** — 实际数据（标准声明 + 自定义声明）：
```json
{
    "sub": "user123",          // Subject（用户ID）
    "iss": "auth.example.com", // Issuer（签发者）
    "exp": 1715000000,         // Expiration（过期时间）
    "iat": 1714000000,         // Issued At（签发时间）
    "jti": "a1b2c3d4e5",       // JWT ID（唯一标识，防重放）
    "userId": 1001,            // 自定义声明
    "roles": ["ROLE_ADMIN"]
}
```

**Signature** — 防篡改签名：
```
HMACSHA256(
    base64UrlEncode(Header) + "." + base64UrlEncode(Payload),
    secret    ← 对称加密用密钥，非对称加密用私钥
)
```

**为什么 Payload 用 Base64 而不是加密？** 因为 JWT 的设计目标不是保密，而是**防篡改**。任何拿到 Token 的人都能解码 Payload 看到内容（所以绝对不能放密码、手机号等敏感信息），但如果没有密钥就无法伪造签名——修改 Payload 的任何内容后，Signature 验证会失败。

### JWT 认证流程

```
① 用户提交用户名密码
    ↓
② 服务端验证通过，生成 JWT（Header.Payload.Signature）
    ↓
③ 返回 JWT 给客户端
    ↓
④ 客户端存储 JWT（localStorage / 内存 / HttpOnly Cookie）
    ↓
⑤ 后续请求在 Header 中携带 JWT → Authorization: Bearer <token>
    ↓
⑥ 服务端 JWT 过滤器拦截请求，验证签名 + 检查过期时间
    ↓
⑦ 验证通过 → 从 Payload 提取用户信息 → 设置到 SecurityContext
    ↓
⑧ 请求到达 Controller（和 Session 认证一样的后续流程）
```

Spring Security 整合 JWT 的关键组件是一个自定义的 `JwtAuthenticationFilter`（继承 `OncePerRequestFilter`），插入到 `UsernamePasswordAuthenticationFilter` 之前执行。详见 [[04_Spring生态/05_SpringSecurity/Spring Security核心原理]] 中的过滤器链位置。

### Token 刷新机制（双 Token）

```
问题：JWT 签发后在过期前一直有效，无法撤回。如果 Access Token 有效期太长，被盗后风险大。

解决方案：双 Token 机制

Access Token（短有效期，如 30 分钟）
  → 携带在请求头中，用于访问 API
  → 过期后前端拦截 401 响应，自动触发刷新

Refresh Token（长有效期，如 7 天）
  → 存储在 HttpOnly Cookie 中（防 XSS）
  → 仅用于调用 /auth/refresh 接口换取新的 Access Token
  → Refresh Token 过期 → 跳转登录页重新认证

流程：
登录 → 获得 Access Token + Refresh Token
  → Access Token 正常使用
  → Access Token 过期 → 前端拦截 401 → 用 Refresh Token 请求 /auth/refresh
  → 服务端验证 Refresh Token → 签发新的 Access Token（可选：同时轮换 Refresh Token）
  → Refresh Token 也过期 → 重新登录
```

双 Token 的本质是**用 Refresh Token 的"长但可控"来换取 Access Token 的"短且安全"**。Access Token 即使被盗，30 分钟后就失效了。Refresh Token 存在 HttpOnly Cookie 中，JS 无法读取，XSS 无法窃取。

### OAuth2 授权码模式：第三方登录的标准流程

```
四个角色：
  Resource Owner（资源所有者）= 你（微信用户）
  Client（第三方应用）= 某网站（想用微信登录）
  Authorization Server（授权服务器）= 微信开放平台
  Resource Server（资源服务器）= 微信用户信息 API
```

```
① 用户点击"微信登录"
   Client → Authorization Server
   GET /oauth/authorize?response_type=code&client_id=xxx&redirect_uri=xxx&state=xyz
    ↓
② 用户在微信页面确认授权
   Authorization Server → Client（回调 redirect_uri）
   https://client.com/callback?code=AUTH_CODE&state=xyz
    ↓
③ Client 后端用 code 换 Token（服务端到服务端，code 只能用一次）
   Client → Authorization Server
   POST /oauth/token { grant_type=authorization_code, code, client_id, client_secret, redirect_uri }
    ↓
④ 返回 Access Token
   Authorization Server → Client
   { access_token, token_type, expires_in, refresh_token }
    ↓
⑤ Client 用 Access Token 访问资源
   Client → Resource Server
   GET /api/userinfo  Authorization: Bearer <access_token>
```

**为什么需要 code 中转？** code 通过浏览器前端传递（用户可见），但 Token 通过服务端后端获取（用户不可见）。如果 Token 直接通过浏览器 URL 回传，任何人看到浏览器历史记录就能拿到 Token。code 只是临时凭证，一次性使用，即使泄露也无法获取 Token。

OAuth2 还支持其他模式：
- **客户端模式**（Client Credentials）：服务器对服务器调用，无用户参与
- **密码模式**（Resource Owner Password）：信任度高的第一方应用，直接传用户名密码
- **隐式模式**（Implicit）：已不推荐，OAuth2.1 中被废弃

### OAuth2 和 JWT 的关系

```
OAuth2 ≠ JWT

OAuth2 是授权框架（协议）：定义"如何授权"
JWT 是 Token 格式（数据结构）：定义"Token 长什么样"

OAuth2 的 Access Token 可以是：
- JWT（自包含，Resource Server 可自行验证签名）← 微服务最常用
- 不透明字符串（Opaque Token，需到 Auth Server 验证）← 更安全但每次都要回调
```

OAuth2 定义的是授权流程（用 code 换 Token、用 Token 访问资源），但 Token 本身长什么样、里面放什么数据，OAuth2 不管——这部分由 JWT 或其他 Token 格式定义。

---

## 深入原理

### 对称签名（HS256）vs 非对称签名（RS256）

```
HS256（对称）：
  签名和验证用同一个密钥（secret）
  → 所有微服务都必须持有 secret
  → secret 泄露 = 所有 Token 都能被伪造
  → 适合单体应用，部署简单

RS256（非对称）：
  私钥签名，公钥验证
  → Authorization Server 持有私钥（签发 Token）
  → Resource Server（微服务）只需公钥（验证 Token）
  → 私钥不离开 Auth Server，安全性更高
  → 适合微服务架构
```

微服务场景下推荐 RS256 的原因：如果 10 个微服务都用 HS256，每个服务都要配置相同的 secret——任何一个服务被攻破，secret 就泄露了，攻击者可以伪造任意用户的 Token。RS256 下只有 Auth Server 有私钥，微服务被攻破只能拿到公钥（只能验证不能伪造）。

### Session vs JWT 的本质区别

| 维度 | Session + Cookie | JWT |
|------|-----------------|-----|
| **存储位置** | 服务端（内存/Redis） | 客户端（Token 自包含） |
| **状态** | 有状态 | 无状态 |
| **水平扩展** | 需要共享存储（Redis） | 天然支持 |
| **Token 失效** | 服务端可随时销毁 Session | 签发后无法主动失效 |
| **安全风险** | CSRF（Cookie 自动发送） | XSS（localStorage 可被读取） |
| **性能** | 每次请求查 Redis | 本地验证签名，无网络开销 |
| **适用场景** | 传统 Web、需要强控制 | 前后端分离、微服务、移动端 |

JWT 最大的优势是**无状态**——服务端不需要存储任何东西。但这也是它的劣势：一旦签发就无法撤回（在过期前始终有效）。需要主动失效时只能额外维护 Token 黑名单（Redis），这又引入了状态——所以 JWT + Redis 黑名单本质上退化了部分无状态优势。

---

## 正确使用方式

### JWT 存储方案的选择

```
方案一：Access Token 存 localStorage
  ✅ 前端操作方便
  ❌ JS 可读取 → XSS 攻击可直接窃取

方案二：Access Token 存 HttpOnly Cookie
  ✅ JS 无法读取 → 防 XSS
  ❌ Cookie 自动发送 → 有 CSRF 风险（但 JWT 场景已关闭 CSRF）

方案三（推荐）：Access Token 存内存 + Refresh Token 存 HttpOnly Cookie
  ✅ Access Token 不在持久存储中 → 页面关闭即清除
  ✅ Refresh Token 在 HttpOnly Cookie 中 → JS 无法窃取
  ✅ 兼顾安全与体验
```

### OAuth2 授权码模式的 state 参数

```
回调 URL 中的 state 参数用于防止 CSRF 攻击：
1. 生成随机 state 值，存入 Session
2. 重定向到授权服务器时携带 state
3. 回调时检查返回的 state 是否匹配

如果不校验 state：
攻击者可以构造恶意链接 → 用户点击后自动跳转到授权页面
→ 授权成功后 code 被发送到攻击者的 redirect_uri → 攻击者获取 code
→ 攻击者用 code 换取 Token → 冒充用户身份
```

### Spring Authorization Server 的使用

```java
// 依赖（Spring Boot 3.x）
// spring-boot-starter-oauth2-resource-server  ← Resource Server（验证 Token）
// spring-security-oauth2-authorization-server ← Authorization Server（签发 Token）

// Resource Server 配置（验证 JWT Token）
http.authorizeHttpRequests(auth -> auth.anyRequest().authenticated())
    .oauth2ResourceServer(oauth2 -> oauth2
        .jwt(jwt -> jwt.jwkSetUri("https://auth-server/oauth2/jwks")));
```

Spring Authorization Server 是 Spring 官方提供的 OAuth2.1 授权服务器实现，替代了已废弃的 Spring Security OAuth2（旧版由社区维护）。`jwks`（JSON Web Key Set）端点提供公钥，Resource Server 用公钥验证 JWT Token 的签名。

---

## 边界情况和坑

### JWT 无法主动失效的应对

```
场景：用户修改了密码（或被管理员禁用），但已签发的 JWT 还没过期
     → 用户仍然可以用旧 Token 访问 API

应对方案：
1. 短有效期 + Refresh Token（减少暴露窗口）
2. Token 版本号（Payload 中加 version 字段，修改密码时 version+1）
   → 验证 Token 时对比数据库中的 version，不匹配则拒绝
3. Redis Token 黑名单（用户主动退出/修改密码时将 Token 加入黑名单）
   → 每次验证 Token 时检查黑名单 → 引入了状态依赖
```

### Payload 中放敏感信息的安全风险

```
❌ 错误：在 Payload 中放密码、手机号、身份证号
{"sub": "user123", "password": "123456", "phone": "13800138000"}

Payload 只是 Base64 编码，不是加密！
任何人用 Base64 解码工具就能看到全部内容：
  echo "eyJzdWIiOiIxMjM0NTY3ODkwIiwicGFzc3dvcmQiOiIxMjM0NTYifQ==" | base64 -d
  → {"sub":"1234567890","password":"123456"}

✅ 正确：只放必要的标识信息
{"sub": "user123", "roles": ["ROLE_ADMIN"]}
```

### HTTPS 是 JWT 的硬性前提

JWT Token 在网络上传输（通过 Authorization Header），如果不走 HTTPS，中间人可以直接截获 Token——无论 HS256 还是 RS256 都无法防止网络层的窃听。JWT 的签名机制只保证 Token 没有被篡改，不保证传输过程的安全。

### OAuth2 隐式模式的安全问题

```
OAuth2.1 已废弃隐式模式，原因：
  Token 直接在 URL Fragment 中返回（#access_token=...）
  URL Fragment 会留在浏览器历史记录中
  → 任何能查看浏览器历史的人都可能获取 Token

替代方案：
  SPA 应用使用 Authorization Code + PKCE（Proof Key for Code Exchange）
  → 即使没有 client_secret，通过 code_verifier / code_challenge 也能安全获取 Token
```
