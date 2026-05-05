# Spring Security 核心原理

> Java 企业级安全框架的标准答案——不只是"加个拦截器"，而是认证（你是谁）和授权（你能做什么）的完整体系。理解过滤器链和认证流程是掌握 Spring Security 的核心。

---

## 这个问题为什么存在？

Web 应用的安全问题无处不在：未认证用户访问受保护资源、普通用户越权执行管理员操作、会话被劫持、密码泄露……这些不是"以后再考虑"的事，而是每个接口从设计之初就需要回答的问题。

手动实现安全机制看似简单，实则困难重重：

```java
// 手动写安全过滤器的"伪代码"——看起来能工作，但漏洞百出
public class AuthFilter implements Filter {
    public void doFilter(request, response, chain) {
        String token = request.getHeader("Authorization");
        if (token == null) {
            // 未登录 → 401？还是重定向到登录页？不同接口行为不同
            // 公开接口怎么办？硬编码白名单？维护起来是噩梦
        }
        // 权限检查？每个 Controller 方法都要写 if/else？
        // 并发请求？异步线程？SecurityContext 怎么传递？
        // CSRF？XSS？点击劫持？... 全都要手动处理
    }
}
```

手动方案的问题在于**安全是横切关注点**（和日志、事务一样），每个接口都要处理，但逻辑又高度相似。如果分散在每个 Controller 里，遗漏一个就是安全漏洞。

Spring Security 的定位：提供一套**声明式**的安全框架，通过过滤器链（Servlet Filter Chain）统一处理所有安全逻辑。开发者只需要声明"哪些接口需要认证"、"哪些角色可以访问"，框架处理剩下的所有细节。

---

## 它是怎么解决问题的？

### 过滤器链：安全逻辑的执行载体

Spring Security 的核心机制是一组有序的 Servlet Filter，组成一条**安全过滤器链**（SecurityFilterChain）。每个 HTTP 请求必须依次通过所有过滤器，任何一个过滤器都可以阻止请求继续传递。

```
HTTP 请求
    ↓
SecurityContextHolderFilter        — 从仓库加载 SecurityContext（恢复上下文）
    ↓
CorsFilter                         — CORS 跨域处理
    ↓
CsrfFilter                         — CSRF 防护（默认开启）
    ↓
UsernamePasswordAuthenticationFilter — 表单登录（POST /login）
    ↓
BearerTokenAuthenticationFilter    — JWT Bearer Token 认证（自定义过滤器插入位置）
    ↓
BasicAuthenticationFilter          — HTTP Basic 认证
    ↓
SessionManagementFilter            — Session 固定攻击防护、并发 Session 限制
    ↓
ExceptionTranslationFilter         — 捕获认证/授权异常 → 转为 401/403 响应
    ↓
AuthorizationFilter                — 授权校验（URL 级别权限检查）
    ↓
请求到达 Controller
```

**关键设计**：Servlet Filter 是 Java Web 规范的标准组件，由 Servlet 容器（Tomcat）管理生命周期。Spring Security 的 Filter 在 Servlet 层面拦截请求，比 Spring MVC 的 Interceptor 更早执行——这意味着即使请求不经过 DispatcherServlet（比如静态资源），安全检查也不会被绕过。

**DelegatingFilterProxy 的桥梁作用**：Servlet 容器管理的 Filter 无法直接访问 Spring Bean（因为 Filter 是 Servlet 容器创建的，不在 Spring 容器中）。DelegatingFilterProxy 作为桥梁，将 Filter 的执行委托给 Spring 容器中的 `FilterChainProxy` Bean，从而让安全过滤器可以使用 Spring 的依赖注入。

```
Servlet Container（Tomcat）
    ↓ 创建和管理
DelegatingFilterProxy（Servlet Filter）
    ↓ 委托给 Spring Bean
FilterChainProxy（Spring Security 核心）
    ↓ 管理多条
SecurityFilterChain（按 Order 匹配不同路径）
```

### 认证流程：确认"你是谁"

认证流程的核心是一套**委托链**：AuthenticationManager → ProviderManager → AuthenticationProvider → UserDetailsService。

```
① UsernamePasswordAuthenticationToken（未认证状态）
   → principal = username, credentials = password, authorities = 空, authenticated = false
    ↓ 提交给
② AuthenticationManager（认证入口）
    ↓ 委托给
③ ProviderManager（管理多个 AuthenticationProvider）
    ↓ 找到支持该认证类型的 Provider
④ DaoAuthenticationProvider
    ↓ 调用
⑤ UserDetailsService.loadUserByUsername(username)
    ↓ 查数据库返回
⑥ UserDetails（用户名、加密密码、权限列表、账户状态）
    ↓ Provider 用 PasswordEncoder 验证密码
    ↓ 验证通过
⑦ UsernamePasswordAuthenticationToken（已认证状态）
   → principal = UserDetails, credentials = 清空, authorities = 权限列表, authenticated = true
    ↓ 存入
⑧ SecurityContextHolder.getContext().setAuthentication(authResult)
```

**为什么是委托链而不是直接认证？**

因为应用的认证方式可能不止一种：用户名密码、手机验证码、微信扫码、JWT Token……每种认证方式的验证逻辑完全不同（查数据库？调第三方接口？解析 Token？），不可能写在一个类里。ProviderManager 持有多个 AuthenticationProvider，每个 Provider 只处理自己支持的认证类型（通过 `supports()` 方法判断），调用方完全不需要知道具体是哪个 Provider 在处理。

### SecurityContext：线程级安全上下文

认证成功后，用户的认证信息（Authentication 对象）存入 `SecurityContextHolder`。整个请求处理链中的任何代码都可以通过 `SecurityContextHolder.getContext().getAuthentication()` 获取当前用户信息，而不需要把 User 对象作为参数在方法之间层层传递。

```java
// Controller / Service / 任何地方都能这样获取当前用户
Authentication auth = SecurityContextHolder.getContext().getAuthentication();
String username = auth.getName();                    // 用户名
Collection<GrantedAuthority> authorities = auth.getAuthorities();  // 权限列表
Object principal = auth.getPrincipal();              // UserDetails 对象
```

`SecurityContextHolder` 默认使用 `ThreadLocal` 存储上下文，这意味着**每个线程有独立的安全上下文**。这个设计在同步 Web 请求中工作良好（Tomcat 一个请求一个线程），但在异步场景下会丢失上下文——详见"边界情况和坑"。

### 授权模型：控制"你能做什么"

Spring Security 支持三个层级的授权控制：

```java
// 层级一：URL 级别（在 SecurityFilterChain 中配置）
http.authorizeHttpRequests(auth -> auth
    .requestMatchers("/admin/**").hasRole("ADMIN")
    .requestMatchers("/user/**").hasAnyRole("USER", "ADMIN")
    .requestMatchers("/public/**").permitAll()
    .anyRequest().authenticated()
);

// 层级二：方法级别（在 Service/Controller 方法上注解）
@PreAuthorize("hasRole('ADMIN')")
public void deleteUser(Long id) { }

@PreAuthorize("#userId == authentication.principal.id")
public void updateProfile(Long userId) { }  // 只能操作自己的数据

// 层级三：SpEL 表达式（灵活组合）
@PreAuthorize("hasAuthority('user:read') and #userId == authentication.principal.id")
public User getUserProfile(Long userId) { }
```

**授权决策的底层是投票器**（AccessDecisionVoter）：每个 Voter 对当前请求投 ACCESS_GRANTED、ACCESS_DENIED 或 ACCESS_ABSTAIN。默认策略是 AFFIRMATIVE（一票通过）——只要有任何一个 Voter 投了 GRANTED 就放行。

### RBAC 权限模型

Spring Security 内建支持 RBAC（Role-Based Access Control）模型：

```
用户（User）→ 角色（Role）→ 权限（Permission/Authority）

用户：张三
  └── 角色：ROLE_ADMIN
        ├── 权限：user:read
        ├── 权限：user:write
        └── 权限：user:delete
```

```java
// UserDetails 实现中返回权限列表
@Override
public Collection<? extends GrantedAuthority> getAuthorities() {
    return List.of(
        new SimpleGrantedAuthority("ROLE_ADMIN"),   // 角色（粗粒度）
        new SimpleGrantedAuthority("user:read"),    // 权限（细粒度）
        new SimpleGrantedAuthority("user:write")
    );
}
```

`hasRole('ADMIN')` 和 `hasAuthority('ROLE_ADMIN')` 的区别：`hasRole` 会自动添加 `ROLE_` 前缀，`hasAuthority` 精确匹配字符串。最佳实践是用 `hasRole` 做粗粒度控制（角色），`hasAuthority` 做细粒度控制（权限）。

### SpringBoot 自动配置的默认行为

引入 `spring-boot-starter-security` 后，Spring Security 默认：
1. 所有接口都需要认证
2. 生成默认登录页面 `/login`（GET）和表单处理（POST）
3. 默认用户名 `user`，密码在启动日志中随机打印
4. 默认启用 CSRF 防护
5. 默认启用 Session 管理

前后端分离项目中，需要关闭 CSRF、禁用 Session（设为 STATELESS）、添加自定义 JWT 过滤器，详见 [[04_Spring生态/05_SpringSecurity/Spring Security实战与面试]]。

---

## 深入原理

### Authentication 接口的两种状态

`UsernamePasswordAuthenticationToken` 在认证前后是同一个类，但内部状态完全不同——这是 Spring Security 用一个类表达两种语义的设计：

```java
// 未认证状态（登录请求提交时构造）
new UsernamePasswordAuthenticationToken(username, password);
// principal = String (用户名), credentials = String (密码)
// authorities = null, authenticated = false
// → 这个对象是"认证请求"，不是"认证结果"

// 已认证状态（认证成功后由 Provider 构造）
new UsernamePasswordAuthenticationToken(userDetails, null, authorities);
// principal = UserDetails (完整用户信息), credentials = null (已清除密码)
// authorities = 权限列表, authenticated = true
// → 这个对象是"认证结果"，包含了用户完整信息
```

为什么认证后要清空 credentials？因为密码已经验证过了，后续使用 Authentication 对象时不需要再持有密码明文。如果 credentials 一直保留在 SecurityContext 中，任何能访问 SecurityContext 的代码都能拿到密码——这是一个安全风险。

### CSRF 防护机制

```
攻击场景：
1. 用户登录了银行网站 A（浏览器持有 A 的 Cookie）
2. 用户访问了恶意网站 B
3. 网站 B 的页面有隐藏表单 <form action="https://bank.com/transfer" method="POST">
4. 浏览器自动带上 A 的 Cookie → 银行认为是用户的合法请求

防御原理：
1. 服务端为每个 Session 生成唯一的 CSRF Token
2. 表单提交时必须携带该 Token（隐藏字段或请求头）
3. 服务端校验 Token 是否匹配
4. 攻击者的恶意页面无法获取 Token（同源策略限制）
```

**什么时候关闭 CSRF？** 关键判断标准是**认证信息存储在哪里**：
- 认证信息放在 **Cookie** 中（传统 Web）→ 必须开启 CSRF（Cookie 会自动随请求发送，攻击者可以利用）
- 认证信息放在 **请求头** 中（如 JWT 的 Authorization Header）→ 可以关闭 CSRF（攻击者的跨域请求无法自定义请求头）

### 密码加密：BCrypt 为什么是首选

```
BCrypt 特点：
- 基于 Blowfish 加密算法
- 自动生成随机盐（Salt），每次加密结果不同
- 可调节强度因子（strength，默认 10，范围 4~31，实际执行 2^strength 轮）

$2a$10$N9qo8uLOickgx2ZMRZoMy.MrqJ2hOaCYd6Xn5JKJ8aTnWkJhCB5K6
│   │  │  │                                              │
│   │  │  Salt（22字符，随机生成）                        Hash（31字符）
│   │  Cost Factor（10 → 2^10 = 1024 轮运算）
│   Algorithm（2a = BCrypt）
$   Prefix
```

BCrypt 的自盐设计意味着开发者不需要自己管理 Salt——加密和验证都是同一个 `BCryptPasswordEncoder` 完成，Salt 编码在密文串中，解密时自动提取。这消除了"Salt 存在数据库哪里"和"每次加密要不要换 Salt"的决策负担。

---

## 正确使用方式

### 标准的 SecurityFilterChain 配置模板

```java
@Configuration
@EnableWebSecurity
@EnableMethodSecurity  // 启用 @PreAuthorize / @PostAuthorize 注解
public class SecurityConfig {

    @Bean
    public SecurityFilterChain filterChain(HttpSecurity http) throws Exception {
        http
            .csrf(csrf -> csrf.disable())  // JWT 无状态认证时关闭 CSRF
            .sessionManagement(session ->
                session.sessionCreationPolicy(SessionCreationPolicy.STATELESS))
            .authorizeHttpRequests(auth -> auth
                .requestMatchers("/auth/login", "/auth/register", "/public/**").permitAll()
                .requestMatchers("/admin/**").hasRole("ADMIN")
                .anyRequest().authenticated())
            .exceptionHandling(ex -> ex
                .authenticationEntryPoint(jwtAuthenticationEntryPoint)  // 401
                .accessDeniedHandler(customAccessDeniedHandler))        // 403
            .addFilterBefore(jwtFilter, UsernamePasswordAuthenticationFilter.class);
        return http.build();
    }

    @Bean
    public PasswordEncoder passwordEncoder() {
        return new BCryptPasswordEncoder();
    }
}
```

### 多 SecurityFilterChain 按路径匹配

```java
// 不同路径使用不同的安全策略
@Bean
public SecurityFilterChain apiFilterChain(HttpSecurity http) throws Exception {
    http.securityMatcher("/api/**")
        .authorizeHttpRequests(auth -> auth.anyRequest().authenticated())
        .addFilterBefore(jwtFilter, UsernamePasswordAuthenticationFilter.class);
    return http.build();
}

@Bean
public SecurityFilterChain openFilterChain(HttpSecurity http) throws Exception {
    http.securityMatcher("/open/**")
        .authorizeHttpRequests(auth -> auth.anyRequest().permitAll());
    return http.build();
}
```

---

## 边界情况和坑

### SecurityContext 在异步线程中丢失

```java
// ❌ 主线程的 SecurityContext 在 @Async 子线程中丢失
@Async
public void sendWelcomeEmail(Long userId) {
    // SecurityContextHolder.getContext() → null！
    // 无法获取当前用户信息
}

// ✅ 方案一：设置可继承的 ThreadLocal 策略
SecurityContextHolder.setStrategyName(SecurityContextHolder.MODE_INHERITABLETHREADLOCAL);

// ✅ 方案二：手动传递
SecurityContext context = SecurityContextHolder.getContext();
executor.submit(() -> {
    SecurityContextHolder.setContext(context);
    try { /* 业务逻辑 */ }
    finally { SecurityContextHolder.clearContext(); }
});

// ✅ 方案三：使用 DelegatingSecurityContextExecutor（Spring Security 内置）
ExecutorService executor = new DelegatingSecurityContextExecutorService(originalExecutor);
```

**根因**：`SecurityContextHolder` 默认用 `ThreadLocal` 存储，而 `ThreadLocal` 的值在子线程中是不可见的。异步线程和主线程是完全独立的 Thread 实例。

### 密码编码器的选择陷阱

| 算法 | 安全性 | 推荐度 | 说明 |
|------|--------|--------|------|
| **BCrypt** | 高 | 首选 | 自带盐、可调强度、广泛使用 |
| **SCrypt** | 更高 | 高安全场景 | 内存消耗型，抗 GPU/ASIC 暴力破解 |
| **Argon2** | 最高 | 最高安全要求 | 密码哈希竞赛冠军，抗侧信道攻击 |
| **MD5/SHA-1** | 极低 | 禁止使用 | 无盐、速度快、易被彩虹表破解 |

**为什么不能用 MD5？** MD5 没有加盐，且计算速度极快（一秒能算上亿次），攻击者可以用彩虹表或 GPU 暴力破解。即使加了固定 Salt，MD5 的计算速度也让暴力破解的成本极低。BCrypt 的 `cost factor` 直接增加了每次计算的工作量，让暴力破解变得不可行。

### 接口权限的 SpEL 表达式失效

```java
// ❌ 忘了加 @EnableMethodSecurity → @PreAuthorize 不生效，所有请求直接通过
@Configuration
public class SecurityConfig {  // 缺少 @EnableMethodSecurity！
    // ...
}

// ✅ 必须加上
@EnableMethodSecurity  // 让 Spring 通过 AOP 拦截方法调用，执行 SpEL 表达式
```

`@PreAuthorize` 的底层是 Spring AOP——它通过 `AutoProxyCreator` 为标注了权限注解的 Bean 创建代理对象，在方法调用前拦截并执行 SpEL 表达式。没有 `@EnableMethodSecurity`，AOP 代理不会创建，注解就是摆设。
