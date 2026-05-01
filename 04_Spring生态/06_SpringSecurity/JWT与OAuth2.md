# JWT 与 OAuth2

> JWT（JSON Web Token）是目前最流行的无状态认证方案，OAuth2 是授权框架标准。面试高频在于 JWT 的结构、优缺点、与 Session 的对比、以及 OAuth2 的授权码模式流程。

---

## 一、JWT 核心原理

### 1.1 JWT 结构

```
Header（头部）.Payload（载荷）.Signature（签名）

例子：
eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIiwibmFtZSI6IkpvaG4gRG9lIiwiaWF0IjoxNTE2MjM5MDIyfQ.SflKxwRJSMeKKF2QT4fwpMeJf36POk6yJV_adQssw5c

Header:   eyJhbGciOiJIUzI1NiJ9     → {"alg": "HS256"}
Payload:  eyJzdWIiOiIxMjM0NTY3ODkw... → {"sub": "1234567890", "name": "John Doe", "iat": 1516239022}
Signature: SflKxwRJSMeKKF2QT4fw... → HMACSHA256(base64UrlEncode(Header) + "." + base64UrlEncode(Payload), secret)
```

### 1.2 Header（头部）

```json
{
    "alg": "HS256",      // 签名算法：HS256/HS384/HS512/RS256/RS512/ES256
    "typ": "JWT"          // Token 类型，固定为 JWT
}
```

| 签名算法 | 类型 | 特点 | 适用场景 |
|---------|------|------|---------|
| **HS256** | 对称加密（HMAC） | 一个密钥，速度快 | 单体应用 |
| **RS256** | 非对称加密（RSA） | 公钥验证/私钥签名，更安全 | 微服务 |
| **ES256** | 非对称加密（ECDSA） | 更短密钥、更高性能 | 高安全要求 |

### 1.3 Payload（载荷）— 标准声明与自定义声明

```json
{
    // 标准声明（Registered Claims）
    "iss": "auth.example.com",     // Issuer（签发者）
    "sub": "user123",              // Subject（主题，通常是用户ID）
    "aud": "api.example.com",      // Audience（接收方）
    "exp": 1715000000,             // Expiration（过期时间）
    "nbf": 1714000000,             // Not Before（生效时间）
    "iat": 1714000000,             // Issued At（签发时间）
    "jti": "a1b2c3d4e5",           // JWT ID（唯一标识，防重放）

    // 自定义声明（Public Claims）
    "userId": 1001,
    "username": "zhangsan",
    "roles": ["ROLE_ADMIN", "ROLE_USER"],
    "nickname": "张三"
}
```

> **注意**：Payload 只是 Base64 编码（不是加密），任何人都可以解码。**不要在 Payload 中放敏感信息**（如密码、手机号）。

### 1.4 Signature（签名）— 防篡改机制

```
HMACSHA256(
    base64UrlEncode(Header) + "." + base64UrlEncode(Payload),
    secret    ← 密钥（对称）/ 私钥（非对称）
)
```

**签名的作用**：保证 Header 和 Payload 没有被篡改。如果修改了 Payload 的任何内容，签名验证会失败。

---

## 二、JWT 认证流程

### 2.1 完整认证流程

```
① 用户提交用户名密码
       ↓
② 服务端验证通过，生成 JWT
   → Header.Payload.Signature
       ↓
③ 返回 JWT 给客户端
       ↓
④ 客户端存储 JWT（localStorage / Cookie）
       ↓
⑤ 后续请求在 Header 中携带 JWT
   → Authorization: Bearer <token>
       ↓
⑥ 服务端过滤器拦截，验证 JWT 签名和过期时间
       ↓
⑦ 验证通过，从 JWT 中提取用户信息，设置到 SecurityContext
       ↓
⑧ 请求到达 Controller
```

### 2.2 Spring Security 整合 JWT

```java
// ① JWT 工具类
@Component
public class JwtTokenProvider {
    @Value("${jwt.secret}")
    private String secret;

    @Value("${jwt.expiration}")
    private long expiration; // 毫秒

    // 生成 Token
    public String generateToken(Authentication authentication) {
        UserDetails userDetails = (UserDetails) authentication.getPrincipal();
        Date now = new Date();
        Date expiryDate = new Date(now.getTime() + expiration);

        return Jwts.builder()
            .setSubject(userDetails.getUsername())
            .setIssuedAt(now)
            .setExpiration(expiryDate)
            .signWith(Keys.hmacShaKeyFor(secret.getBytes()), SignatureAlgorithm.HS256)
            .claim("roles", userDetails.getAuthorities())
            .compact();
    }

    // 从 Token 中提取用户名
    public String getUsernameFromToken(String token) {
        return Jwts.parserBuilder()
            .setSigningKey(secret.getBytes())
            .build()
            .parseClaimsJws(token)
            .getBody()
            .getSubject();
    }

    // 验证 Token
    public boolean validateToken(String token) {
        try {
            Jwts.parserBuilder()
                .setSigningKey(secret.getBytes())
                .build()
                .parseClaimsJws(token);
            return true;
        } catch (ExpiredJwtException e) {
            // Token 已过期
        } catch (UnsupportedJwtException | MalformedJwtException e) {
            // Token 格式错误
        } catch (SignatureException e) {
            // 签名不匹配（被篡改）
        }
        return false;
    }
}
```

```java
// ② JWT 过滤器（每次请求执行）
public class JwtAuthenticationFilter extends OncePerRequestFilter {

    @Autowired
    private JwtTokenProvider jwtTokenProvider;

    @Autowired
    private UserDetailsService userDetailsService;

    @Override
    protected void doFilterInternal(HttpServletRequest request,
                                    HttpServletResponse response,
                                    FilterChain filterChain) throws ServletException, IOException {
        try {
            // 从 Header 中提取 Token
            String jwt = getJwtFromRequest(request);

            if (StringUtils.hasText(jwt) && jwtTokenProvider.validateToken(jwt)) {
                // 从 Token 提取用户名
                String username = jwtTokenProvider.getUsernameFromToken(jwt);

                // 加载用户详情（验证用户是否仍然有效）
                UserDetails userDetails =
                    userDetailsService.loadUserByUsername(username);

                // 创建已认证的 Authentication 对象
                UsernamePasswordAuthenticationToken authentication =
                    new UsernamePasswordAuthenticationToken(
                        userDetails, null, userDetails.getAuthorities());

                authentication.setDetails(
                    new WebAuthenticationDetailsSource().buildDetails(request));

                // 设置到 SecurityContext
                SecurityContextHolder.getContext().setAuthentication(authentication);
            }
        } catch (Exception ex) {
            logger.error("Could not set user authentication in security context", ex);
        }

        filterChain.doFilter(request, response);
    }

    private String getJwtFromRequest(HttpServletRequest request) {
        String bearerToken = request.getHeader("Authorization");
        if (StringUtils.hasText(bearerToken) && bearerToken.startsWith("Bearer ")) {
            return bearerToken.substring(7);
        }
        return null;
    }
}
```

### 2.3 Token 刷新机制

```
问题：JWT 过期后用户需要重新登录？体验不好。
方案：双 Token 机制（Access Token + Refresh Token）

Access Token（短有效期，如 30 分钟）
  → 携带在请求头中，访问 API
Refresh Token（长有效期，如 7 天）
  → 存储在 HttpOnly Cookie 中，仅用于刷新 Access Token
```

```
流程：
① 用户登录 → 返回 Access Token + Refresh Token
② Access Token 过期 → 前端拦截 401 → 用 Refresh Token 请求 /auth/refresh
③ 服务端验证 Refresh Token → 签发新的 Access Token（可选：同时刷新 Refresh Token）
④ 如果 Refresh Token 也过期 → 重新登录
```

---

## 三、JWT 优缺点分析

### 3.1 优势

| 优势 | 说明 |
|------|------|
| **无状态** | 服务端不需要存储 Session，方便水平扩展 |
| **跨域支持** | Token 放在 Header 中，天然支持 CORS |
| **移动端友好** | 不依赖 Cookie，适合 App/小程序 |
| **微服务共享** | 微服务间只需共享密钥/公钥，无需共享 Session |
| **CDN 友好** | 静态资源的认证可通过 Header 传递 |

### 3.2 劣势与解决方案

| 劣势 | 说明 | 解决方案 |
|------|------|----------|
| **无法主动失效** | Token 签发后在过期前一直有效，无法撤销 | 短有效期 + Refresh Token；或维护 Token 黑名单（Redis） |
| **Token 过大** | 自定义声明多时，Header 体积增大 | 精简 Payload，只放必要字段 |
| **安全风险** | XSS 攻击可窃取 localStorage 中的 Token | 存 HttpOnly Cookie；或 Token 短有效期 |
| **续期复杂** | 不像 Session 自动续期 | Refresh Token 机制 |
| **无法服务端踢人** | 无法强制用户下线 | Token 版本号 + Redis 黑名单 |

---

## 四、Session vs JWT 对比

| 维度 | Session + Cookie | JWT |
|------|-----------------|-----|
| **存储位置** | 服务端（内存/Redis/数据库） | 客户端（localStorage/Cookie） |
| **状态** | 有状态 | 无状态 |
| **水平扩展** | 需要 Session 共享（Redis） | 天然支持 |
| **安全性** | CSRF 风险；HttpOnly 防 XSS | XSS 风险；不受 CSRF 影响 |
| **移动端** | Cookie 管理不便 | Header 传递，天然友好 |
| **Token 失效** | 服务端可随时销毁 | 无法主动失效（需额外机制） |
| **性能** | 每次查 Redis | 无需查询，自包含 |
| **适用场景** | 传统 Web、SSO | 前后端分离、微服务、移动端 |

**选型建议**：
- **单体/传统 Web**：Session-Cookie 更简单（Spring Security 默认）
- **前后端分离 + 微服务**：JWT（主流方案）
- **高安全要求（金融/支付）**：短有效期 JWT + Redis Token 管理

---

## 五、OAuth2 授权框架

### 5.1 四种角色

| 角色 | 说明 | 例子 |
|------|------|------|
| **Resource Owner** | 资源所有者（用户） | 你（微信用户） |
| **Client** | 第三方应用 | 某网站（想用微信登录） |
| **Authorization Server** | 授权服务器 | 微信开放平台 |
| **Resource Server** | 资源服务器 | 微信用户信息 API |

### 5.2 四种授权模式

#### 模式一：授权码模式（Authorization Code）— 最安全、最常用

```
① 用户点击"微信登录"
    Client → Authorization Server
    GET /oauth/authorize?response_type=code&client_id=xxx&redirect_uri=xxx&scope=read&state=xyz
       ↓
② 用户在微信页面确认授权
    Authorization Server → Client（回调 redirect_uri）
    https://client.com/callback?code=AUTH_CODE&state=xyz
       ↓
③ Client 用 code 换 Token（服务端到服务端，code 只能用一次）
    Client → Authorization Server
    POST /oauth/token { grant_type=authorization_code, code=AUTH_CODE, client_id, client_secret, redirect_uri }
       ↓
④ 返回 Access Token + Refresh Token
    Authorization Server → Client
    { access_token, token_type, expires_in, refresh_token, scope }
       ↓
⑤ Client 用 Access Token 访问资源
    Client → Resource Server
    GET /api/userinfo  Authorization: Bearer <access_token>
```

> **为什么需要 code 这一步？** code 通过浏览器前端传递（用户可见），但 Token 通过服务端后端获取（用户不可见），防止 Token 泄露。

#### 模式二：客户端模式（Client Credentials）— 服务器对服务器

```
Client → Authorization Server
POST /oauth/token { grant_type=client_credentials, client_id, client_secret }
    ↓
返回 Access Token（无 Refresh Token，无用户身份）
    ↓
Client → Resource Server
Authorization: Bearer <access_token>
```

> **适用场景**：微服务间调用、后台服务访问 API。无用户参与。

#### 模式三：密码模式（Resource Owner Password Credentials）

```
Client → Authorization Server
POST /oauth/token { grant_type=password, username, password, scope }
    ↓
返回 Access Token + Refresh Token
```

> **适用场景**：高信任度的第一方应用（自己的前端 + 自己的后端）。第三方应用不应使用。

#### 模式四：隐式模式（Implicit）— 已不推荐

```
Client → Authorization Server
GET /oauth/authorize?response_type=token&client_id=xxx&redirect_uri=xxx
    ↓
直接在 URL Fragment 中返回 Token（不经过服务端）
redirect_uri#access_token=TOKEN&token_type=Bearer&expires_in=3600
```

> **已被 OAuth2.1 废弃**：Token 暴露在 URL 中，安全性差。

### 5.3 四种模式对比

| 维度 | 授权码 | 客户端 | 密码 | 隐式 |
|------|--------|--------|------|------|
| **安全性** | 最高 | 高 | 中 | 低（已废弃） |
| **用户参与** | 需要 | 不需要 | 需要 | 需要 |
| **Access Token** | 服务端获取 | 服务端获取 | 服务端获取 | 前端获取 |
| **Refresh Token** | 有 | 无 | 有 | 无 |
| **适用场景** | 第三方登录 | 服务间调用 | 信任客户端 | 纯前端 SPA（已弃用） |

---

## 六、OAuth2 vs JWT 关系

```
OAuth2 ≠ JWT

OAuth2 是授权框架（协议）
JWT 是 Token 格式（数据结构）

OAuth2 定义了"如何授权"，JWT 定义了"Token 长什么样"

OAuth2 的 Access Token 可以是：
- JWT（自包含，Resource Server 可自行验证）  ← 当前主流
- 不透明字符串（Opaque Token，需到 Auth Server 验证）  ← 更安全但性能差
```

### 6.1 组合方案对比

| 方案 | Access Token | Refresh Token | 特点 |
|------|-------------|---------------|------|
| **OAuth2 + JWT** | JWT | JWT 或 Opaque | 微服务最常用，RS 验证 Token 无需回调 Auth Server |
| **OAuth2 + Opaque** | 随机字符串 | 随机字符串 | 更安全，但每次都需查 Auth Server（Redis/DB） |
| **纯 JWT（无 OAuth2）** | JWT | JWT | 简单方案，自有认证体系 |

---

## 七、Spring Authorization Server

### 7.1 新旧框架对比

```
旧：Spring Security OAuth2（已废弃，社区维护到 2.x）
新：Spring Authorization Server（Spring 官方维护，OAuth2.1 标准）
```

### 7.2 快速集成（Spring Boot 3.x）

```java
// 依赖
// spring-boot-starter-oauth2-resource-server  ← Resource Server
// spring-security-oauth2-authorization-server ← Authorization Server

// Resource Server 配置（验证 JWT Token）
http.authorizeHttpRequests(auth -> auth
    .anyRequest().authenticated())
    .oauth2ResourceServer(oauth2 -> oauth2
        .jwt(jwt -> jwt.jwkSetUri("https://auth-server/oauth2/jwks")));
```

---

## 八、面试高频问题

### Q1：JWT 能被伪造吗？

> JWT 使用签名机制防篡改：使用密钥（HS256）或私钥（RS256）对 Header+Payload 生成签名。没有密钥就无法生成有效签名，所以无法伪造。但 **Payload 是 Base64 编码的，不是加密的**，任何人都可以解码查看。所以不要放敏感信息。此外要防止 JWT 被窃取（XSS 攻击），建议用 HttpOnly Cookie 或短有效期。

### Q2：JWT 过期了怎么办？怎么实现续期？

> **双 Token 机制**：Access Token 短有效期（如 30 分钟）+ Refresh Token 长有效期（如 7 天）。Access Token 过期后，前端拦截 401 响应，自动用 Refresh Token 调用 `/auth/refresh` 换取新的 Access Token。如果 Refresh Token 也过期了，跳转登录页。也可以用**滑动续期**：每次请求时检查 Access Token 剩余有效期，如果快过期就自动签发新的。

### Q3：JWT 存在哪里？localStorage 还是 Cookie？

> 两种方式各有优劣：**localStorage** 方便前端操作，但有 XSS 攻击风险（JS 可读取）；**HttpOnly Cookie** 防 XSS，但有 CSRF 风险。最佳实践是 **Access Token 存 localStorage + 短有效期 + Refresh Token 存 HttpOnly Cookie**，兼顾安全与体验。

### Q4：Session 和 JWT 怎么选？

> **单体传统 Web** 选 Session（简单，Spring Security 默认支持）；**前后端分离/微服务** 选 JWT（无状态，天然支持水平扩展）。高安全场景（金融/支付）可以用 **短有效期 JWT + Redis Token 黑名单**，兼顾无状态和安全控制能力。

### Q5：讲一下 OAuth2 授权码模式的流程？

> 分四步：① 第三方应用重定向用户到授权服务器，用户确认授权；② 授权服务器回调 redirect_uri，附带授权码 code；③ 第三方应用后端用 code + client_secret 向授权服务器换取 Access Token（code 只能用一次）；④ 用 Access Token 访问资源服务器。**为什么用 code 中转？** 防止 Token 暴露在浏览器中。code 通过前端传递，Token 通过后端获取，更安全。

### Q6：JWT 的优缺点？

> 优点：无状态（服务端不存 Session）、跨域友好、移动端友好、微服务间共享方便。缺点：无法主动失效（需要黑名单机制）、Token 体积可能较大、续期复杂、XSS 窃取风险。实际项目中通常用 **短有效期 + Refresh Token + Redis 黑名单** 来弥补缺陷。

---

## 知识关联

- **Spring Security 核心原理**：JWT 过滤器插入到 SecurityFilterChain 中，替代 Session 认证，详见 [[Spring Security核心原理]]
- **Filter**：`JwtAuthenticationFilter` 继承 `OncePerRequestFilter`，保证每个请求只执行一次
- **Redis**：Token 黑名单、Refresh Token 存储都依赖 Redis
- **HTTPS**：JWT 在网络上传输必须使用 HTTPS，防止 Token 被中间人窃取
- **微服务**：RS256 非对称签名，各微服务只需公钥即可验证 Token，无需回调 Auth Server
