# Spring Security 实战与面试

> 从安全场景配置到框架对比，覆盖 Java 后端开发者需要掌握的 Spring Security 实战知识。

---

## 一、前后端分离安全配置

### 1.1 完整配置模板

```java
@Configuration
@EnableWebSecurity
@EnableMethodSecurity
public class SecurityConfig {

    @Autowired
    private JwtAuthenticationFilter jwtFilter;

    @Autowired
    private JwtAuthenticationEntryPoint jwtAuthEntryPoint;

    @Autowired
    private CustomAccessDeniedHandler accessDeniedHandler;

    @Bean
    public SecurityFilterChain filterChain(HttpSecurity http) throws Exception {
        http
            // 关闭 CSRF（JWT 无状态认证不需要）
            .csrf(csrf -> csrf.disable())

            // 关闭默认登录/退出页面
            .formLogin(form -> form.disable())
            .httpBasic(basic -> basic.disable())

            // Session 无状态
            .sessionManagement(session ->
                session.sessionCreationPolicy(SessionCreationPolicy.STATELESS))

            // CORS 跨域配置
            .cors(cors -> cors.configurationSource(corsConfigurationSource()))

            // 请求授权
            .authorizeHttpRequests(auth -> auth
                // 公开接口
                .requestMatchers("/auth/login", "/auth/register",
                    "/auth/refresh", "/auth/captcha").permitAll()
                .requestMatchers("/swagger-ui/**", "/v3/api-docs/**").permitAll()
                .requestMatchers("/actuator/health").permitAll()
                // 管理员接口
                .requestMatchers("/admin/**").hasRole("ADMIN")
                // 其他接口需要认证
                .anyRequest().authenticated())

            // 异常处理
            .exceptionHandling(ex -> ex
                .authenticationEntryPoint(jwtAuthEntryPoint)  // 401 未认证
                .accessDeniedHandler(accessDeniedHandler))     // 403 无权限

            // JWT 过滤器
            .addFilterBefore(jwtFilter, UsernamePasswordAuthenticationFilter.class);

        return http.build();
    }

    @Bean
    public CorsConfigurationSource corsConfigurationSource() {
        CorsConfiguration config = new CorsConfiguration();
        config.setAllowedOrigins(List.of("https://example.com"));
        config.setAllowedMethods(List.of("GET", "POST", "PUT", "DELETE", "OPTIONS"));
        config.setAllowedHeaders(List.of("*"));
        config.setAllowCredentials(true);
        config.setMaxAge(3600L);

        UrlBasedCorsConfigurationSource source = new UrlBasedCorsConfigurationSource();
        source.registerCorsConfiguration("/**", config);
        return source;
    }

    @Bean
    public PasswordEncoder passwordEncoder() {
        return new BCryptPasswordEncoder();
    }
}
```

### 1.2 自定义异常处理器

```java
// 未认证 → 401
@Component
public class JwtAuthenticationEntryPoint implements AuthenticationEntryPoint {
    @Override
    public void commence(HttpServletRequest request, HttpServletResponse response,
                         AuthenticationException authException) throws IOException {
        response.setContentType("application/json;charset=UTF-8");
        response.setStatus(HttpServletResponse.SC_UNAUTHORIZED);
        response.getWriter().write(
            "{\"code\":401,\"message\":\"未认证，请先登录\",\"data\":null}");
    }
}

// 无权限 → 403
@Component
public class CustomAccessDeniedHandler implements AccessDeniedHandler {
    @Override
    public void handle(HttpServletRequest request, HttpServletResponse response,
                       AccessDeniedException accessDeniedException) throws IOException {
        response.setContentType("application/json;charset=UTF-8");
        response.setStatus(HttpServletResponse.SC_FORBIDDEN);
        response.getWriter().write(
            "{\"code\":403,\"message\":\"无权限访问该资源\",\"data\":null}");
    }
}
```

### 1.3 UserDetailsService 实现

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
            .password(user.getPassword())
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

---

## 二、常见安全场景

### 2.1 CORS 跨域配置

```
问题：前端（http://localhost:3000）调用后端 API（http://localhost:8080）被浏览器拦截

原因：浏览器的同源策略（Same-Origin Policy）
      同源 = 协议 + 域名 + 端口 完全一致

解决：后端返回 CORS 响应头
      Access-Control-Allow-Origin: https://example.com
      Access-Control-Allow-Methods: GET, POST, PUT, DELETE
      Access-Control-Allow-Headers: Authorization, Content-Type
      Access-Control-Allow-Credentials: true
```

> **注意**：Spring Security 的 CORS 配置必须在 SecurityFilterChain 之前处理，否则 OPTIONS 预检请求会被拦截。

### 2.2 接口级权限控制

```java
// 角色控制
@PreAuthorize("hasRole('ADMIN')")           // 需要 ADMIN 角色
@PreAuthorize("hasAnyRole('ADMIN', 'USER')") // ADMIN 或 USER

// 权限控制
@PreAuthorize("hasAuthority('user:read')")   // 需要 user:read 权限
@PreAuthorize("hasAuthority('user:write') && hasAuthority('user:read')")

// 参数校验
@PreAuthorize("#userId == authentication.principal.id")  // 只能操作自己的数据

// 返回值校验
@PostAuthorize("returnObject.owner == authentication.name") // 返回对象的所有者必须是当前用户

// 组合使用
@PreAuthorize("hasRole('ADMIN') or #userId == authentication.principal.id")
```

### 2.3 数据权限（行级安全）

```
场景：用户只能看到自己部门的数据

方案：
1. 注解 + AOP：@DataScope 注解标记方法，AOP 拦截后动态拼接 SQL 条件
2. MyBatis 拦截器：在 SQL 执行前自动追加 WHERE 条件
3. 数据库 Row Level Security（PostgreSQL 原生支持）
```

```java
// 方案1示例：AOP + 注解
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
        // 获取当前用户信息
        UserDetails user = (UserDetails) SecurityContextHolder
            .getContext().getAuthentication().getPrincipal();
        // 获取部门ID列表
        List<Long> deptIds = user.getDeptIds();
        // 设置到 ThreadLocal 或参数中，供 MyBatis 拦截器使用
        DataScopeContext.setDeptIds(deptIds, dataScope.deptColumn());
    }
}
```

### 2.4 密码安全最佳实践

```java
// 注册时
String encodedPassword = passwordEncoder.encode(rawPassword); // 加密后存储
user.setPassword(encodedPassword);

// 登录时（Spring Security 自动调用）
boolean matches = passwordEncoder.matches(rawPassword, storedEncodedPassword);

// 安全要求
// - 密码长度 ≥ 8 位
// - 包含大小写字母 + 数字 + 特殊字符
// - 使用 BCryptPasswordEncoder（强度 10+）
// - 禁止明文存储
// - 禁止 MD5/SHA-1（无盐，易被彩虹表破解）
```

---

## 三、Spring Security vs Apache Shiro

| 维度 | Spring Security | Apache Shiro |
|------|----------------|-------------|
| **学习曲线** | 陡峭，概念多 | 平缓，API 简洁 |
| **Spring 集成** | 原生集成，无缝对接 | 需要额外配置 |
| **社区生态** | Spring 官方维护，生态强大 | 社区维护，更新较慢 |
| **功能丰富度** | 认证+授权+OAuth2+JWT+LDAP+... | 认证+授权+Session+加密 |
| **过滤器链** | 自动配置 20+ Filter，灵活 | 手动配置 URL Filter |
| **RBAC 支持** | 内置 | 需要自行实现 |
| **性能** | 功能多，略重 | 轻量，启动快 |
| **适用场景** | Spring 全家桶项目、企业级 | 轻量项目、非 Spring 项目 |
| **国内使用** | 主流，新项目首选 | 老项目仍有使用 |

**选型建议**：新项目一律选 Spring Security。Shiro 仅在维护老项目时了解即可。

---

## 四、常见安全问题

### 4.1 安全威胁与防御

| 威胁 | 说明 | 防御 |
|------|------|------|
| **SQL 注入** | 恶意 SQL 拼接 | PreparedStatement / MyBatis `#{}` |
| **XSS** | 注入恶意 JS 脚本 | 输入过滤 + 输出转义 + CSP 头 |
| **CSRF** | 跨站请求伪造 | CSRF Token / SameSite Cookie |
| **点击劫持** | 透明 iframe 覆盖 | X-Frame-Options: DENY |
| **暴力破解** | 穷举密码 | 登录限速 / 验证码 / 账户锁定 |
| **Token 泄露** | JWT 被窃取 | HTTPS + HttpOnly Cookie + 短有效期 |

### 4.2 安全响应头配置

```java
http.headers(headers -> headers
    .contentTypeOptions(contentType -> contentType.disable()) // X-Content-Type-Options: nosniff
    .frameOptions(frame -> frame.deny())                       // X-Frame-Options: DENY
    .xssProtection(xss -> xss.disable())                      // X-XSS-Protection: 0（用 CSP 替代）
    .contentSecurityPolicy(csp -> csp.policyDirectives(
        "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'"))
    .httpStrictTransportSecurity(hsts -> hsts
        .includeSubDomains(true)
        .maxAgeInSeconds(31536000))  // HSTS: max-age=1年
);
```

---

## 五、面试高频问题

### Q1：Spring Security 的过滤器链是怎么工作的？

> Spring Security 通过 `FilterChainProxy` 管理一组 `SecurityFilter`，按固定顺序执行。核心流程：① `SecurityContextHolderFilter` 加载上下文 → ② `UsernamePasswordAuthenticationFilter` 或自定义 `JwtFilter` 处理认证 → ③ `AuthorizationFilter` 校验权限 → ④ `ExceptionTranslationFilter` 处理异常（401/403）。过滤器链通过 `SecurityFilterChain` Bean 配置，支持按路径匹配不同的链。

### Q2：@PreAuthorize 和 @Secured 有什么区别？

> `@Secured` 功能简单，只支持角色检查（`@Secured("ROLE_ADMIN")`）。`@PreAuthorize` 基于 SpEL 表达式，支持更复杂的逻辑：角色检查、权限检查、参数校验（`#userId == principal.id`）、逻辑运算（`and`/`or`）、甚至调用自定义 Bean 方法。`@PreAuthorize` 是实际项目的主流选择。使用时需在配置类加 `@EnableMethodSecurity`。

### Q3：前后端分离怎么配置 Spring Security？

> 核心三点：① 关闭 CSRF（`csrf.disable()`），因为 JWT 在 Header 传递不受 CSRF 影响；② 设置 Session 无状态（`STATELESS`），不创建 Session；③ 添加自定义 JWT 过滤器，在 `UsernamePasswordAuthenticationFilter` 之前执行，从 Header 提取 Token 验证后设置 SecurityContext。此外还要配置 CORS 和自定义异常处理器（401/402 返回 JSON）。

### Q4：JWT 存 localStorage 还是 Cookie？

> 都有安全风险。localStorage 容易被 XSS 攻击窃取（JS 可读取）；Cookie 设置 HttpOnly 可以防 XSS 但有 CSRF 风险。**推荐方案**：Access Token 存内存或 sessionStorage（页面关闭即清除），Refresh Token 存 HttpOnly Cookie + SameSite=Strict。每次请求用内存中的 Access Token，过期时自动用 Cookie 中的 Refresh Token 续期。兼顾安全与体验。

### Q5：Spring Security 和 Shiro 怎么选？

> 新项目选 Spring Security，与 Spring 生态无缝集成，功能全面（认证/授权/OAuth2/JWT），社区活跃。Shiro API 简单、轻量，但在 Spring 体系下没有优势。面试时可以说：了解 Shiro 的核心概念（Subject/Realm/Session），但实际项目用 Spring Security。

### Q6：如何实现"记住我"功能？

> Spring Security 内置 Remember-Me 功能。原理：用户勾选"记住我"后登录，服务端生成一个 Token（`username + 过期时间 + 密钥`的 MD5），写入数据库（`persistent_logins` 表），同时设置 Cookie。后续请求即使 Session 过期，也可以通过 Cookie 中的 Token 恢复认证状态。在配置中用 `http.rememberMe()` 开启。安全性上，Remember-Me 的 Token 会被持久化，存在被盗风险，所以敏感操作仍需重新登录。

### Q7：如何防止暴力破解登录？

> 三层防护：① **登录限速**：用 Redis 记录同一 IP/用户名的失败次数，超过阈值（如 5 次/分钟）后暂时锁定；② **验证码**：失败次数达到阈值后要求图形验证码或短信验证码；③ **账户锁定**：密码错误 N 次后锁定账户一段时间。Spring Security 可以通过自定义 `AuthenticationFailureHandler` 实现失败计数，配合 Redis 实现分布式限速。

### Q8：说说你对 RBAC 的理解？

> RBAC（Role-Based Access Control）基于角色的访问控制，核心模型：用户 → 角色 → 权限。用户关联多个角色，角色关联多个权限。在 Spring Security 中，用户登录后 `UserDetails.getAuthorities()` 返回权限列表，通过 `@PreAuthorize("hasRole('ADMIN')")` 或 `@PreAuthorize("hasAuthority('user:write')")` 进行权限控制。实际项目中通常用五张表：用户表、角色表、权限表、用户角色关联表、角色权限关联表。

---

## 知识关联

- **Spring Security 核心原理**：本章是实战层面的补充，原理部分见 [[Spring Security核心原理]]
- **JWT 与 OAuth2**：无状态认证方案的理论基础，详见 [[JWT与OAuth2]]
- **MyBatis**：UserDetailsService 实现依赖数据库查询，权限数据通过 MyBatis 加载
- **Redis**：Token 黑名单、登录限速、分布式 Session 共享都依赖 Redis
- **AOP**：`@EnableMethodSecurity` 通过 AOP 拦截方法调用执行权限检查
