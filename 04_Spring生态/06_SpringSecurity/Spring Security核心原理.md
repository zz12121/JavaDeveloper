# Spring Security 核心原理

> Spring Security 是 Java 生态中最强大的安全框架，提供认证（Authentication）和授权（Authorization）的完整解决方案。面试重点在于过滤器链的执行顺序、认证流程、以及与 SpringBoot 的整合方式。

---

## 一、整体架构

### 1.1 核心设计理念

```
请求 → 过滤器链（SecurityFilterChain）
         → Authentication（认证：你是谁？）
         → Authorization（授权：你能做什么？）
         → 请求到达 Controller
```

**两大核心功能**：
- **认证（Authentication）**：验证用户身份（用户名密码、Token、第三方登录等）
- **授权（Authorization）**：控制已认证用户能访问哪些资源（URL 权限、方法权限、数据权限）

### 1.2 模块架构

```
Spring Security
├── Web 层（Servlet Filter 链）
│   ├── DelegatingFilterProxy        ← Servlet 容器 → Spring 的桥梁
│   ├── FilterChainProxy             ← 管理所有 Security Filter
│   └── SecurityFilterChain（N 个 Filter）
│
├── 认证层（Authentication）
│   ├── AuthenticationManager        ← 认证入口
│   ├── ProviderManager              ← 认证管理器（委托给多个 Provider）
│   ├── AuthenticationProvider       ← 具体认证逻辑
│   │   ├── DaoAuthenticationProvider    ← 用户名密码认证
│   │   ├── RememberMeAuthenticationProvider ← 记住我
│   │   └── JwtAuthenticationProvider      ← JWT Token 认证
│   └── UserDetailsService           ← 加载用户信息
│
├── 授权层（Authorization）
│   ├── AccessDecisionManager        ← 访问决策管理器
│   ├── AccessDecisionVoter          ← 投票器（基于角色/表达式）
│   └── SecurityExpressionHandler    ← SpEL 表达式解析
│
└── 上下文（SecurityContext）
    ├── SecurityContextHolder        ← 线程级安全上下文持有者
    ├── SecurityContext              ← 存放 Authentication
    └── Authentication               ← 当前用户身份 + 权限信息
```

---

## 二、认证流程（Authentication）

### 2.1 核心组件关系

```
UsernamePasswordAuthenticationToken（未认证）
    ↓ 提交给
AuthenticationManager
    ↓ 委托给
ProviderManager
    ↓ 匹配对应的
DaoAuthenticationProvider
    ↓ 调用
UserDetailsService.loadUserByUsername()
    ↓ 返回
UserDetails（用户名、密码、权限列表、启用状态）
    ↓ DaoAuthenticationProvider 用 PasswordEncoder 验证密码
    ↓ 验证通过后
UsernamePasswordAuthenticationToken（已认证，携带 authorities）
    ↓ 存入
SecurityContextHolder.getContext().setAuthentication()
```

### 2.2 关键接口

| 接口/类 | 职责 | 常见实现 |
|---------|------|----------|
| **`Authentication`** | 封装认证信息（身份 + 权限） | `UsernamePasswordAuthenticationToken` |
| **`AuthenticationManager`** | 认证入口，`authenticate()` 方法 | `ProviderManager` |
| **`AuthenticationProvider`** | 具体认证逻辑 | `DaoAuthenticationProvider`、`JwtAuthenticationProvider` |
| **`UserDetailsService`** | 根据用户名加载用户信息 | 自定义实现（查数据库） |
| **`UserDetails`** | 用户信息的标准封装 | 自定义实现或 `org.springframework.security.core.userdetails.User` |
| **`PasswordEncoder`** | 密码加密与验证 | `BCryptPasswordEncoder` |

### 2.3 Authentication 的两种状态

```java
// 未认证状态（登录请求提交时）
UsernamePasswordAuthenticationToken authRequest =
    new UsernamePasswordAuthenticationToken(username, password);
// 此时：principal = username, credentials = password, authorities = 空, authenticated = false

// 已认证状态（认证成功后）
UsernamePasswordAuthenticationToken authResult =
    new UsernamePasswordAuthenticationToken(userDetails, password, authorities);
// 此时：principal = UserDetails, credentials = 清空, authorities = 权限列表, authenticated = true
```

### 2.4 ProviderManager 支持多 Provider

```
ProviderManager
    ├── DaoAuthenticationProvider        ← 支持用户名密码
    ├── JwtAuthenticationProvider        ← 支持 JWT
    ├── RememberMeAuthenticationProvider ← 支持记住我
    └── ...自定义 Provider
```

> **ProviderManager** 会依次遍历所有 Provider，找到 `supports(Authentication.class)` 返回 true 的 Provider 执行认证。如果认证成功则返回，失败则尝试下一个。

---

## 三、SecurityContext 上下文传播

### 3.1 SecurityContextHolder 存储策略

```java
// 三种存储策略（通过 SecurityContextHolder.setStrategyName() 设置）
SecurityContextHolder.MODE_THREADLOCAL    // 默认，ThreadLocal 存储（适用于传统 Web）
SecurityContextHolder.MODE_INHERITABLETHREADLOCAL // 可继承 ThreadLocal（适用于异步子线程）
SecurityContextHolder.MODE_GLOBAL         // 全局静态变量（适用于独立应用）
```

### 3.2 线程上下文丢失问题

```
主线程 SecurityContext → @Async 异步线程 → SecurityContext 丢失！
主线程 SecurityContext → 子线程 Thread → SecurityContext 丢失！
```

**解决方案**：
```java
// 方案1：使用可继承策略
SecurityContextHolder.setStrategyName(SecurityContextHolder.MODE_INHERITABLETHREADLOCAL);

// 方案2：手动传递
SecurityContext context = SecurityContextHolder.getContext();
executor.submit(() -> {
    SecurityContextHolder.setContext(context);
    try { /* 业务逻辑 */ } finally { SecurityContextHolder.clearContext(); }
});

// 方案3：DelegatingSecurityContextExecutor（Spring Security 提供）
ExecutorService executor = new DelegatingSecurityContextExecutorService(originalExecutor);
```

---

## 四、过滤器链（SecurityFilterChain）

### 4.1 核心过滤器执行顺序

```
HTTP 请求
    ↓
① DisableEncodeUrlFilter            — 是否编码 URL（默认禁用）
② WebAsyncManagerIntegrationFilter  — 将 SecurityContext 与异步请求绑定
③ SecurityContextHolderFilter        — 从 SecurityContextRepository 加载上下文
④ HeaderWriterFilter                 — 写入安全响应头（CORS/CSP/HSTS）
⑤ CorsFilter                        — CORS 跨域处理
⑥ CsrfFilter                        — CSRF 防护（默认开启）
⑦ LogoutFilter                      — 处理退出登录请求（/logout）
⑧ UsernamePasswordAuthenticationFilter — 处理表单登录（POST /login）
⑨ DefaultLoginPageGeneratingFilter    — 生成默认登录页面
⑩ DefaultLogoutPageGeneratingFilter   — 生成默认退出页面
⑪ ConcurrentSessionFilter            — 并发会话控制
⑫ DigestAuthenticationFilter         — HTTP Digest 认证
⑬ BearerTokenAuthenticationFilter    — JWT Bearer Token 认证
⑭ BasicAuthenticationFilter          — HTTP Basic 认证
⑮ RequestCacheAwareFilter            — 恢复被缓存的原请求（登录后重定向）
⑯ SecurityContextHolderAwareRequestWrapper — 包装请求，支持 request.isUserInRole()
⑰ AnonymousAuthenticationFilter      — 匿名用户认证（兜底）
⑱ SessionManagementFilter            — Session 固定攻击防护、并发 Session 限制
⑲ ExceptionTranslationFilter         — 捕获认证/授权异常，转发给 AuthenticationEntryPoint / AccessDeniedHandler
⑳ AuthorizationFilter                — 授权校验（新版替代 FilterSecurityInterceptor）
```

### 4.2 DelegatingFilterProxy 与 FilterChainProxy

```
Servlet Container（Tomcat）
    ↓ 注册
DelegatingFilterProxy（Spring 框架的 Filter）
    ↓ 委托给 Spring Bean
FilterChainProxy（Spring Security 的核心 Filter）
    ↓ 管理多个
SecurityFilterChain（实际的安全过滤器链）
```

> **为什么需要 DelegatingFilterProxy？** Servlet 容器管理的 Filter 无法直接使用 Spring Bean。DelegatingFilterProxy 作为桥梁，将 Servlet Filter 的生命周期委托给 Spring 容器。

### 4.3 多 SecurityFilterChain

```java
// Spring Security 支持多个 SecurityFilterChain，按 Order 匹配不同路径
httpSecurity
    .securityMatcher("/api/**")  // 只匹配 /api/** 路径
    .authorizeHttpRequests(auth -> auth.anyRequest().authenticated())
    .addFilterBefore(jwtFilter, UsernamePasswordAuthenticationFilter.class)
    .build();

httpSecurity
    .securityMatcher("/open/**")  // 公开接口
    .authorizeHttpRequests(auth -> auth.anyRequest().permitAll())
    .build();
```

---

## 五、授权模型（Authorization）

### 5.1 三种授权方式

```java
// ① URL 级别授权
http.authorizeHttpRequests(auth -> auth
    .requestMatchers("/admin/**").hasRole("ADMIN")
    .requestMatchers("/user/**").hasAnyRole("USER", "ADMIN")
    .requestMatchers("/public/**").permitAll()
    .anyRequest().authenticated()
);

// ② 方法级别授权（注解）
@PreAuthorize("hasRole('ADMIN')")        // 方法执行前
@PostAuthorize("returnObject.owner == authentication.name") // 方法执行后
@Secured("ROLE_ADMIN")                    // 简化版

// ③ 表达式授权（SpEL）
@PreAuthorize("hasAuthority('user:read') and #userId == authentication.principal.id")
```

### 5.2 授权决策流程

```
AuthorizationFilter
    ↓ 获取
AccessDecisionManager（访问决策管理器）
    ↓ 委托给
AccessDecisionVoter（投票器）
    ├── RoleVoter          ← 基于 ROLE_ 前缀的角色投票
    ├── AuthorityAuthorizationContext.Voter ← 基于权限字符串
    └── AuthenticatedVoter  ← 是否已认证
    ↓ 投票结果
AFFIRMATIVE（一票通过） → 默认策略，只要有 Voter 投 ACCESS_GRANTED 就通过
UNANIMOUS（全票通过） → 所有 Voter 都投 ACCESS_GRANTED 才通过
CONSENSUS（多数通过）  → 超过半数 ACCESS_GRANTED 则通过
```

### 5.3 RBAC 权限模型

```
用户（User）→ 角色（Role）→ 权限（Permission/Authority）

用户：张三
  └── 角色：ROLE_ADMIN
        ├── 权限：user:read
        ├── 权限：user:write
        ├── 权限：user:delete
        └── 权限：order:read
```

```java
// UserDetails 实现中返回权限
@Override
public Collection<? extends GrantedAuthority> getAuthorities() {
    return List.of(
        new SimpleGrantedAuthority("ROLE_ADMIN"),
        new SimpleGrantedAuthority("user:read"),
        new SimpleGrantedAuthority("user:write")
    );
}
```

### 5.4 hasRole vs hasAuthority

```java
@PreAuthorize("hasRole('ADMIN')")      // 自动添加 "ROLE_" 前缀 → 实际匹配 "ROLE_ADMIN"
@PreAuthorize("hasAuthority('ADMIN')") // 精确匹配 "ADMIN" 字符串，不添加前缀

// 最佳实践：用 hasRole 做粗粒度（角色），用 hasAuthority 做细粒度（权限）
```

---

## 六、SpringBoot 自动配置

### 6.1 spring-boot-starter-security 默认行为

```java
// 不做任何配置时，Spring Security 默认：
// 1. 所有接口都需要认证
// 2. 生成默认登录页面 /login（GET）
// 3. 处理表单登录 POST /login
// 4. 默认用户名：user，密码在启动日志中打印
// 5. 默认启用 CSRF 防护
// 6. 默认启用 Session 管理
```

### 6.2 常用配置模板

```java
@Configuration
@EnableWebSecurity
@EnableMethodSecurity  // 启用 @PreAuthorize 注解
public class SecurityConfig {

    @Bean
    public SecurityFilterChain filterChain(HttpSecurity http) throws Exception {
        http
            // 1. 关闭 CSRF（前后端分离/REST API 场景）
            .csrf(csrf -> csrf.disable())

            // 2. Session 管理（无状态）
            .sessionManagement(session ->
                session.sessionCreationPolicy(SessionCreationPolicy.STATELESS))

            // 3. 请求授权规则
            .authorizeHttpRequests(auth -> auth
                .requestMatchers("/auth/login", "/auth/register", "/public/**").permitAll()
                .requestMatchers("/admin/**").hasRole("ADMIN")
                .requestMatchers("/user/**").hasAnyRole("USER", "ADMIN")
                .anyRequest().authenticated())

            // 4. 异常处理
            .exceptionHandling(ex -> ex
                .authenticationEntryPoint(jwtAuthenticationEntryPoint)  // 未认证
                .accessDeniedHandler(customAccessDeniedHandler))        // 无权限

            // 5. 添加自定义过滤器
            .addFilterBefore(jwtAuthenticationFilter,
                UsernamePasswordAuthenticationFilter.class);

        return http.build();
    }

    @Bean
    public PasswordEncoder passwordEncoder() {
        return new BCryptPasswordEncoder();
    }

    @Bean
    public AuthenticationManager authenticationManager(
            AuthenticationConfiguration config) throws Exception {
        return config.getAuthenticationManager();
    }
}
```

---

## 七、密码加密

### 7.1 BCrypt 算法原理

```
BCrypt 特点：
- 基于 Blowfish 加密算法
- 自动生成随机盐（Salt），每次加密结果不同
- 可调节强度因子（strength，默认 10，范围 4~31）
- 自验证：加密后的字符串包含算法标识、强度、盐、哈希值

$2a$10$N9qo8uLOickgx2ZMRZoMy.MrqJ2hOaCYd6Xn5JKJ8aTnWkJhCB5K6
│   │  │  │                                              │
│   │  │  Salt（22字符）                               Hash（31字符）
│   │  Cost Factor（10 → 2^10 轮）
│   Algorithm（2a = BCrypt）
$   Prefix
```

```java
// 使用
PasswordEncoder encoder = new BCryptPasswordEncoder();
String encoded = encoder.encode("123456");  // 加密，每次结果不同
boolean match = encoder.matches("123456", encoded);  // 验证，返回 true
```

### 7.2 PasswordEncoder 对比

| 算法 | 特点 | 安全性 | 推荐度 |
|------|------|--------|--------|
| **BCrypt** | 自带盐，可调强度，广泛使用 | 高 | 首选 |
| **SCrypt** | 内存消耗型，抗 GPU/ASIC 暴力破解 | 更高 | 高安全场景 |
| **Argon2** | 密码哈希竞赛冠军，抗 GPU/侧信道攻击 | 最高 | 最高安全要求 |
| **PBKDF2** | 标准算法，迭代次数可调 | 中高 | 兼容性要求 |
| **NoOp** | 不加密（明文存储） | 无 | 仅测试用 |
| **MD5/SHA** | 无盐、快速，易被彩虹表破解 | 低 | 禁止使用 |

---

## 八、CSRF 防护

### 8.1 原理

```
攻击场景：
1. 用户登录了银行网站 A（浏览器存了 A 的 Cookie）
2. 用户访问了恶意网站 B
3. 网站 B 的页面有一个 <form action="https://bank.com/transfer"> （自动提交）
4. 浏览器会自动带上 A 的 Cookie → 银行认为是用户的合法请求

防御：CSRF Token
1. 服务端为每个 Session 生成唯一的 CSRF Token
2. 表单中携带该 Token（隐藏字段）
3. 提交时校验 Token 是否匹配
4. 攻击者无法获取 Token（同源策略限制），所以伪造的请求无法通过校验
```

### 8.2 何时关闭 CSRF

```java
// 前后端分离 + JWT 无状态认证 → 关闭 CSRF
http.csrf(csrf -> csrf.disable());

// 原因：JWT 不依赖 Cookie，请求头携带 Token，不受 CSRF 攻击影响
```

> **关键判断**：如果认证信息放在 **Cookie** 中 → 必须开启 CSRF。如果认证信息放在 **请求头**（如 Authorization Header） → 可以关闭。

---

## 知识关联

- **AOP**：`@EnableMethodSecurity` 通过 AOP 拦截方法调用，执行 `@PreAuthorize` / `@PostAuthorize`
- **Filter**：Spring Security 本质是一组 Servlet Filter，与 Tomcat 的 Pipeline-Valve 模式有相似之处
- **JWT**：无状态认证方案，替代 Session-Cookie 机制，详见 [[JWT与OAuth2]]
- **OAuth2**：第三方授权框架，支持授权码模式、客户端模式等，详见 [[JWT与OAuth2]]
- **ThreadLocal**：`SecurityContextHolder` 默认使用 ThreadLocal 存储 SecurityContext，存在跨线程传递问题
