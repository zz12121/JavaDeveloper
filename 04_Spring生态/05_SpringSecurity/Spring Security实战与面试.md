# Spring Security 实战与面试

> 从前后端分离配置到安全威胁防御，覆盖 Java 后端开发者需要掌握的 Spring Security 实战知识。不只是"能跑通"，而是理解每个配置项背后的安全逻辑。

---

## 这个问题为什么存在？

掌握了 [[04_Spring生态/05_SpringSecurity/Spring Security核心原理]] 的过滤器链和认证流程后，真正的挑战在于**把理论配置到具体项目中**。不同类型的项目（传统 Web、前后端分离、微服务）对安全框架的需求完全不同，配置方式也截然不同。

传统 Web 应用（服务端渲染）使用 Session-Cookie，Spring Security 的默认配置几乎开箱即用。但前后端分离项目（SPA + REST API）需要关闭 CSRF、禁用 Session、手动配置 JWT 过滤器——每一个"关闭"背后都是安全模型的变化，如果理解不到位就容易留下漏洞。

此外，安全不是"配置好就完事"，还需要应对各种攻击向量（SQL 注入、XSS、CSRF、点击劫持）和实际业务场景（数据权限、暴力破解防护、Remember-Me）。这些知识在原理文档中不会详细展开，但在面试和实际项目中是必须掌握的。

---

## 它是怎么解决问题的？

### 前后端分离安全配置：完整模板

前后端分离项目的核心差异是**认证方式从 Session 切换到 JWT**，这带来三个必须调整的配置：

```java
@Configuration
@EnableWebSecurity
@EnableMethodSecurity
public class SecurityConfig {

    @Bean
    public SecurityFilterChain filterChain(HttpSecurity http) throws Exception {
        http
            // ① 关闭 CSRF — JWT 在请求头传递，不受 CSRF 影响
            .csrf(csrf -> csrf.disable())

            // ② 禁用默认登录/退出页面 — 前后端分离不需要服务端渲染的登录页
            .formLogin(form -> form.disable())
            .httpBasic(basic -> basic.disable())

            // ③ Session 无状态 — 不创建 Session，每次请求独立验证 JWT
            .sessionManagement(session ->
                session.sessionCreationPolicy(SessionCreationPolicy.STATELESS))

            // ④ CORS — 前端跨域请求必须配置
            .cors(cors -> cors.configurationSource(corsConfigurationSource()))

            // ⑤ 请求授权规则
            .authorizeHttpRequests(auth -> auth
                .requestMatchers("/auth/login", "/auth/register",
                    "/auth/refresh", "/auth/captcha").permitAll()
                .requestMatchers("/swagger-ui/**", "/v3/api-docs/**").permitAll()
                .requestMatchers("/admin/**").hasRole("ADMIN")
                .anyRequest().authenticated())

            // ⑥ 异常处理 — 返回 JSON 而非重定向
            .exceptionHandling(ex -> ex
                .authenticationEntryPoint(jwtAuthenticationEntryPoint)  // 401
                .accessDeniedHandler(customAccessDeniedHandler))        // 403

            // ⑦ JWT 过滤器 — 插入到 UsernamePasswordAuthenticationFilter 之前
            .addFilterBefore(jwtFilter, UsernamePasswordAuthenticationFilter.class);

        return http.build();
    }
}
```

每个配置项背后的安全逻辑：

**关闭 CSRF**：CSRF 攻击利用浏览器自动发送 Cookie 的特性——用户访问恶意网站时，恶意网站发起的请求会自动带上目标网站的 Cookie。但 JWT 存储在请求头中（不是 Cookie），恶意网站的跨域请求无法自定义 Authorization Header，所以 CSRF 攻击自然失效。

**Session 无状态**：STATELESS 模式下 Spring Security 不创建也不读取 Session，每个请求通过 JWT 过滤器独立验证。这意味着不依赖 Session 共享，天然支持水平扩展。

**CORS 配置**：前后端分离通常前端（localhost:3000）和后端（localhost:8080）端口不同，浏览器的同源策略会拦截跨域请求。CORS 配置告诉浏览器"允许来自特定源的请求"。

**自定义异常处理器**：Spring Security 默认对 401（未认证）重定向到 `/login` 页面，对 403（无权限）返回错误页面。前后端分离项目需要返回 JSON：

```java
// 401 未认证
@Component
public class JwtAuthenticationEntryPoint implements AuthenticationEntryPoint {
    @Override
    public void commence(HttpServletRequest request, HttpServletResponse response,
                         AuthenticationException authException) throws IOException {
        response.setContentType("application/json;charset=UTF-8");
        response.setStatus(HttpServletResponse.SC_UNAUTHORIZED);
        response.getWriter().write(
            "{\"code\":401,\"message\":\"未认证，请先登录\"}");
    }
}

// 403 无权限
@Component
public class CustomAccessDeniedHandler implements AccessDeniedHandler {
    @Override
    public void handle(HttpServletRequest request, HttpServletResponse response,
                       AccessDeniedException accessDeniedException) throws IOException {
        response.setContentType("application/json;charset=UTF-8");
        response.setStatus(HttpServletResponse.SC_FORBIDDEN);
        response.getWriter().write(
            "{\"code\":403,\"message\":\"无权限访问该资源\"}");
    }
}
```

### 数据权限：行级安全控制

RBAC 解决的是"能不能访问这个接口"的问题，但实际业务中更常见的是"能不能访问这行数据"——比如部门经理只能看到本部门的数据，普通用户只能看到自己的数据。

```java
// 方案：AOP + 自定义注解，动态追加 SQL 条件
@Target(ElementType.METHOD)
@Retention(RetentionPolicy.RUNTIME)
public @interface DataScope {
    String deptColumn() default "dept_id";
}

@Aspect
@Component
public class DataScopeAspect {
    @Before("@annotation(dataScope)")
    public void doBefore(JoinPoint point, DataScope dataScope) {
        UserDetails user = (UserDetails) SecurityContextHolder
            .getContext().getAuthentication().getPrincipal();
        // 获取用户所属部门ID列表
        List<Long> deptIds = getDeptIds(user);
        // 设置到 ThreadLocal，供 MyBatis 拦截器读取
        DataScopeContext.setDeptIds(deptIds, dataScope.deptColumn());
    }
}
```

这个方案的原理是：AOP 在方法执行前拦截，将当前用户的部门信息存入 ThreadLocal，然后 MyBatis 拦截器在 SQL 执行前自动追加 `WHERE dept_id IN (1, 2, 3)` 条件。业务代码完全不需要关心数据权限的逻辑。

### 暴力破解防护：三层防线

```
第一层：登录限速
  用 Redis 记录同一 IP 或用户名的失败次数
  超过阈值（如 5 次/分钟）→ 暂时锁定或要求验证码
  通过自定义 AuthenticationFailureHandler 实现

第二层：验证码
  失败次数达到阈值后要求图形验证码或短信验证码
  防止自动化工具暴力尝试

第三层：账户锁定
  密码错误 N 次后锁定账户一段时间
  可以通过 UserDetailsService 中 UserDetails.isAccountNonLocked() 控制
```

### 安全响应头配置

```java
http.headers(headers -> headers
    .contentTypeOptions(option -> option.disable())   // X-Content-Type-Options: nosniff（防止 MIME 嗅探）
    .frameOptions(frame -> frame.deny())               // X-Frame-Options: DENY（防止点击劫持）
    .contentSecurityPolicy(csp -> csp.policyDirectives(
        "default-src 'self'; script-src 'self'"))     // CSP（限制资源加载来源，防 XSS）
    .httpStrictTransportSecurity(hsts -> hsts
        .includeSubDomains(true)
        .maxAgeInSeconds(31536000)));                  // HSTS（强制 HTTPS，1 年）
```

每个响应头对应一类攻击：
- **nosniff**：防止浏览器将响应内容当作其他类型解析（比如把 JSON 当 HTML 执行）
- **DENY**：防止恶意网站用 iframe 嵌入你的页面（用户以为在操作你的网站，实际在恶意网站上）
- **CSP**：限制页面能加载哪些 JS/CSS/图片资源，即使注入了恶意脚本也无法从外部加载执行
- **HSTS**：告诉浏览器"以后只用 HTTPS 访问我"，防止降级攻击

---

## 深入原理

### @PreAuthorize vs @Secured

```java
// @Secured — 功能简单，只支持角色检查
@Secured("ROLE_ADMIN")
public void deleteUser(Long id) { }

// @PreAuthorize — 基于 SpEL 表达式，支持任意复杂逻辑
@PreAuthorize("hasRole('ADMIN')")                           // 角色检查
@PreAuthorize("hasAuthority('user:write')")                  // 权限检查
@PreAuthorize("#userId == authentication.principal.id")      // 参数校验
@PreAuthorize("hasRole('ADMIN') or #userId == principal.id") // 逻辑组合
@PostAuthorize("returnObject.owner == authentication.name")  // 返回值校验
```

`@EnableMethodSecurity` 的底层实现是 Spring AOP——它创建一个 `AuthorizationManagerBeforeMethodInterceptor`，在标注了权限注解的方法调用前拦截，解析 SpEL 表达式，调用 `AuthorizationManager` 做权限检查。`@PostAuthorize` 在方法执行后拦截，可以访问返回值（通过 `returnObject`）。

### Spring Security vs Apache Shiro

| 维度 | Spring Security | Apache Shiro |
|------|----------------|-------------|
| **Spring 集成** | 原生集成，AOP/Bean 无缝对接 | 需要额外适配 |
| **功能丰富度** | 认证 + 授权 + OAuth2 + LDAP + Method Security | 认证 + 授权 + Session + 加密 |
| **过滤器链** | 自动配置 20+ Filter，高度可定制 | 手动配置 URL Filter，灵活但需更多代码 |
| **学习曲线** | 陡峭（概念多：Filter/Provider/Manager/Voter） | 平缓（Subject/Realm/Session 三个核心概念） |
| **社区生态** | Spring 官方维护，OAuth2.1 标准实现 | 社区维护，更新较慢 |
| **适用场景** | Spring 全家桶项目、企业级（首选） | 轻量项目、非 Spring 项目 |

选型建议：新项目一律选 Spring Security。Shiro 在 Spring 生态下没有优势——Spring Security 的 OAuth2 支持和 Method Security 是 Shiro 不具备的。

---

## 正确使用方式

### UserDetailsService 实现要点

```java
@Service
public class CustomUserDetailsService implements UserDetailsService {

    @Autowired
    private UserRepository userRepository;

    @Override
    public UserDetails loadUserByUsername(String username)
            throws UsernameNotFoundException {
        User user = userRepository.findByUsername(username)
            .orElseThrow(() -> new UsernameNotFoundException("用户不存在: " + username));

        return org.springframework.security.core.userdetails.User.builder()
            .username(user.getUsername())
            .password(user.getPassword())  // 必须是加密后的密码
            .authorities(user.getRoles().stream()
                .map(role -> new SimpleGrantedAuthority(role.getName()))
                .collect(Collectors.toList()))
            .accountExpired(!user.isAccountNonExpired())
            .accountLocked(!user.isAccountNonLocked())
            .credentialsExpired(!user.isCredentialsNonExpired())
            .disabled(!user.isEnabled())
            .build();
    }
}
```

四个账户状态标志（`accountNonExpired`、`accountNonLocked`、`credentialsNonExpired`、`enabled`）在 `DaoAuthenticationProvider` 中会被检查——任何一个为 false 都会抛出对应的异常（`AccountExpiredException`、`LockedException`、`CredentialsExpiredException`、`DisabledException`），被 `ExceptionTranslationFilter` 捕获后转为对应的 HTTP 状态码。

### 接口级权限控制的最佳实践

```java
// 粗粒度（URL 级别）→ 在 SecurityFilterChain 中配置
.requestMatchers("/admin/**").hasRole("ADMIN")
.requestMatchers("/user/**").hasAnyRole("USER", "ADMIN")

// 细粒度（方法级别）→ 在 Service/Controller 上用注解
@PreAuthorize("hasRole('ADMIN')")
public void deleteUser(Long id) { }

@PreAuthorize("#userId == authentication.principal.id")
public User getProfile(Long userId) { }  // 只能查看自己的信息

// 组合逻辑：ADMIN 可以操作所有，普通用户只能操作自己的
@PreAuthorize("hasRole('ADMIN') or #userId == authentication.principal.id")
public void updateUser(Long userId, UserDTO dto) { }
```

分层授权的好处：URL 级别做第一道防线（快速拦截明显不合法的请求），方法级别做精确控制。即使有人绕过了 URL 配置（比如新增了接口忘了配置），方法级别的注解仍然能拦截。

---

## 边界情况和坑

### CORS 配置必须在 SecurityFilterChain 之前生效

```
浏览器跨域请求的流程：
1. 浏览器先发 OPTIONS 预检请求
2. 如果预检通过，再发实际请求

问题：如果 SecurityFilterChain 先拦截了 OPTIONS 请求
→ OPTIONS 被当作普通请求 → 要求认证 → 返回 401
→ 浏览器收到 401 → 实际请求不会发出 → CORS 失败

解决：在 SecurityFilterChain 中配置 CORS
→ Spring Security 确保预检请求不被认证过滤器拦截
```

### "记住我"功能的 Token 安全风险

```
Remember-Me 原理：
  用户勾选"记住我"后登录
  → 服务端生成 Token = MD5(username + 过期时间 + 密钥 + 密码)
  → Token 存入数据库（persistent_logins 表）
  → Token 写入 Cookie（默认 2 周有效）
  → 后续请求即使 Session 过期，Cookie 中的 Token 也能恢复认证状态

风险：Remember-Me Token 是长期凭证，Cookie 中可被窃取（XSS/网络窃听）
→ 敏感操作（修改密码、支付）不应依赖 Remember-Me
→ 敏感操作应要求重新输入密码
```

### 密码安全实践中的常见错误

```java
// ❌ 明文存储密码
user.setPassword(rawPassword);  // 直接存明文

// ❌ 用 MD5 加密
user.setPassword(DigestUtils.md5Hex(rawPassword));  // MD5 无盐，彩虹表秒破

// ✅ 用 BCryptPasswordEncoder
String encoded = passwordEncoder.encode(rawPassword);  // 每次加密结果不同（自动加盐）
user.setPassword(encoded);
boolean match = passwordEncoder.matches(rawPassword, encoded);  // 验证
```

`BCryptPasswordEncoder.encode()` 每次对同一个密码生成的密文都不同（因为 Salt 是随机生成的），但 `matches()` 仍然能正确验证——因为密文串中编码了 Salt，`matches` 会先提取 Salt 再用相同算法计算，比较结果。
