# Web开发

## 这个问题为什么存在？

> 没有 Spring Boot Web 开发支持，搭一个 Web 项目要手动配置 `DispatcherServlet`、`ViewResolver`、Jackson、`CharacterEncodingFilter`... 每个项目都要重复配置。  
> Spring Boot 的目标是：**引入 `spring-boot-starter-web` 就能直接写 Controller**。

**核心问题**：Spring Boot 是怎么自动配置好 Web 环境的？

---

## 它是怎么解决问题的？

### Spring MVC 的请求处理流程

```
HTTP 请求
    ↓
1. DispatcherServlet（前端控制器，统一入口）
    ↓
2. HandlerMapping（映射器，找哪个 Controller 处理）
    ↓
3. HandlerAdapter（适配器，调用 Controller 方法）
    ↓
4. Controller（业务处理，返回 ModelAndView 或 ResponseEntity）
    ↓
5. ViewResolver（视图解析器，如果是页面渲染）
    ↓
6. View（渲染视图，如 Thymeleaf / JSP）
    ↓
HTTP 响应
```

---

### WebMvcAutoConfiguration（自动配置类）

**问题**：为什么加一个 `spring-boot-starter-web`，就有了 Spring MVC 的所有组件？

```java
// WebMvcAutoConfiguration.java
@Configuration
@ConditionalOnWebApplication(type = Type.SERVLET)
@ConditionalOnClass({ Servlet.class, DispatcherServlet.class })
@AutoConfigureAfter(DispatcherServletAutoConfiguration.class)
public class WebMvcAutoConfiguration {

    // 自动配置 ViewResolver（ContentNegotiatingViewResolver）
    // 自动配置 HandlerMapping（RequestMappingHandlerMapping）
    // 自动配置 HandlerAdapter（RequestMappingHandlerAdapter）
    // 自动配置消息转换器（Jackson => HttpMessageConverter）
}
```

**自动配置的核心组件**：

| 组件 | 作用 | 自动配置的 Bean |
|------|------|-----------------|
| `DispatcherServlet` | 前端控制器 | `DispatcherServletAutoConfiguration` |
| `HandlerMapping` | URL → Controller 映射 | `RequestMappingHandlerMapping` |
| `HandlerAdapter` | 调用 Controller 方法 | `RequestMappingHandlerAdapter` |
| `HandlerExceptionResolver` | 全局异常处理 | `ExceptionHandlerExceptionResolver` |
| `HttpMessageConverter` | HTTP 消息转换（JSON） | `MappingJackson2HttpMessageConverter` |

---

### 源码路径：DispatcherServlet 的初始化

```java
// DispatcherServlet.initStrategies()
protected void initStrategies(ApplicationContext context) {
    // 1. 初始化 MultipartResolver（文件上传）
    initMultipartResolver(context);

    // 2. 初始化 LocaleResolver（国际化）
    initLocaleResolver(context);

    // 3. 初始化 ThemeResolver（主题）
    initThemeResolver(context);

    // 4. ★ 初始化 HandlerMapping（URL 映射）
    initHandlerMappings(context);

    // 5. ★ 初始化 HandlerAdapter（方法适配）
    initHandlerAdapters(context);

    // 6. 初始化 HandlerExceptionResolver（异常处理）
    initHandlerExceptionResolvers(context);

    // 7. 初始化 RequestToViewNameTranslator
    initRequestToViewNameTranslator(context);

    // 8. 初始化 ViewResolver（视图解析）
    initViewResolvers(context);

    // 9. 初始化 FlashMapManager（重定向参数传递）
    initFlashMapManager(context);
}
```

> `initHandlerMappings()` 会从 Spring 容器中找所有 `HandlerMapping` 类型的 Bean。  
> `RequestMappingHandlerMapping` 在启动时扫描所有 `@RequestMapping` 方法，建立 URL → Method 的映射表。

---

### 参数绑定原理（HandlerMethodArgumentResolver）

**问题**：Controller 方法参数那么灵活（`@PathVariable`、`@RequestParam`、`@RequestBody`、自定义对象...），是谁把 HTTP 请求参数转换成方法参数的？

**答案**：`HandlerMethodArgumentResolver`（参数解析器）。

```java
// 请求：
// GET /users/123?name=zhang

@GetMapping("/users/{id}")
public User getUser(@PathVariable Long id,
                    @RequestParam String name,
                    HttpServletRequest request) {
    // ...
}
```

**参数解析器的分工**：

| 参数类型 | 解析器 | 数据来源 |
|----------|---------|----------|
| `@PathVariable` | `PathVariableMethodArgumentResolver` | URI 模板变量 |
| `@RequestParam` | `RequestParamMethodArgumentResolver` | query string / form data |
| `@RequestBody` | `RequestResponseBodyMethodProcessor` | HTTP body（反序列化 JSON） |
| `HttpServletRequest` | `ServletRequestMethodArgumentResolver` | 容器传入 |
| 自定义对象（无注解） | `ServletModelAttributeMethodProcessor` | query string / form data 绑定到对象属性 |

---

### 消息转换器（HttpMessageConverter）

**问题**：`@RequestBody` 接收 JSON，`@ResponseBody` 返回 JSON，是谁做的转换？

**答案**：`HttpMessageConverter`。

```java
// 默认的转换器链（按优先级排序）
1. ByteArrayHttpMessageConverter      （byte[]）
2. StringHttpMessageConverter          （String）
3. MappingJackson2HttpMessageConverter（JSON ← 最常用）
4. ResourceHttpMessageConverter        （文件下载）
```

**自定义消息转换器**：

```java
@Configuration
public class WebConfig implements WebMvcConfigurer {
    @Override
    public void configureMessageConverters(List<HttpMessageConverter<?>> converters) {
        // 自定义 JSON 转换器（设置日期格式、null 处理等）
        MappingJackson2HttpMessageConverter converter =
            new MappingJackson2HttpMessageConverter();
        converter.getObjectMapper().setDateFormat(new SimpleDateFormat("yyyy-MM-dd"));
        converters.add(converter);
    }
}
```

---

## 它和相似方案的本质区别是什么？

### Spring MVC vs Spring WebFlux

| | Spring MVC | Spring WebFlux |
|--|-------------|-----------------|
| 编程模型 | 命令式（阻塞） | 响应式（非阻塞） |
| 服务器 | Servlet 容器（Tomcat） | 支持 Netty、Undertow |
| 适用场景 | 传统 Web 应用 | 高并发、低延迟场景 |
| 返回值 | 直接返回对象 | 返回 Mono / Flux |

---

### @RestController vs @Controller

| | @Controller | @RestController |
|--|--------------|-----------------|
| 返回值处理 | 走 ViewResolver（页面渲染） | 直接写入 HTTP body（JSON） |
| 等价于 | `@Controller` + `@ResponseBody` | `@Controller` + `@ResponseBody` |
| 适用场景 | 返回页面（Thymeleaf） | RESTful API |

```java
// @RestController = @Controller + @ResponseBody
@RestController
public class UserController {
    @GetMapping("/users/{id}")
    public User getUser(@PathVariable Long id) {
        return userService.findById(id);  // 直接返回 JSON
    }
}
```

---

## 正确使用方式

### 1. 全局异常处理（@ControllerAdvice）

```java
@Slf4j
@ControllerAdvice
public class GlobalExceptionHandler {

    // 处理业务异常
    @ExceptionHandler(BusinessException.class)
    @ResponseBody
    public Result<Void> handleBusinessException(BusinessException ex) {
        log.warn("业务异常", ex);
        return Result.fail(ex.getCode(), ex.getMessage());
    }

    // 处理参数校验异常（@Valid 失败）
    @ExceptionHandler(MethodArgumentNotValidException.class)
    @ResponseBody
    public Result<Void> handleValidationException(MethodArgumentNotValidException ex) {
        String msg = ex.getBindingResult()
                      .getFieldError()
                      .getDefaultMessage();
        return Result.fail(400, msg);
    }

    // 兜底：处理所有未捕获的异常
    @ExceptionHandler(Exception.class)
    @ResponseBody
    public Result<Void> handleException(Exception ex) {
        log.error("系统异常", ex);
        return Result.fail(500, "系统繁忙，请稍后再试");
    }
}
```

---

### 2. 拦截器（HandlerInterceptor）

```java
@Component
public class AuthInterceptor implements HandlerInterceptor {

    // 在 Controller 方法执行前
    @Override
    public boolean preHandle(HttpServletRequest request,
                             HttpServletResponse response,
                             Object handler) throws Exception {
        String token = request.getHeader("Authorization");
        if (token == null || !validate(token)) {
            response.setStatus(401);
            return false;  // 返回 false → 中断请求
        }
        return true;  // 返回 true → 继续执行
    }

    // 在 Controller 方法执行后、视图渲染前
    @Override
    public void postHandle(HttpServletRequest request,
                          HttpServletResponse response,
                          Object handler,
                          ModelAndView modelAndView) { }

    // 在视图渲染后（可用于资源清理）
    @Override
    public void afterCompletion(HttpServletRequest request,
                                HttpServletResponse response,
                                Object handler,
                                Exception ex) { }
}

// 注册拦截器
@Configuration
public class WebConfig implements WebMvcConfigurer {
    @Autowired
    private AuthInterceptor authInterceptor;

    @Override
    public void addInterceptors(InterceptorRegistry registry) {
        registry.addInterceptor(authInterceptor)
                .addPathPatterns("/api/**")
                .excludePathPatterns("/api/login");
    }
}
```

---

### 3. 参数校验（@Valid + JSR-303）

```java
@Data
public class UserCreateDTO {
    @NotBlank(message = "用户名不能为空")
    @Size(min = 3, max = 20, message = "用户名长度3-20")
    private String username;

    @Email(message = "邮箱格式不正确")
    private String email;

    @Min(value = 1, message = "年龄最小为1")
    @Max(value = 150, message = "年龄最大为150")
    private Integer age;
}

@PostMapping("/users")
public Result<Void> createUser(@RequestBody @Valid UserCreateDTO dto) {
    userService.create(dto);
    return Result.ok();
}
```

---

## 边界情况和坑

### 1. GET 请求的参数绑定陷阱

```java
// ❌ 错误：GET 请求用 @RequestBody
@GetMapping("/users")
public List<User> getUsers(@RequestBody UserQuery query) {
    // GET 请求没有 body！@RequestBody 会报错
}

// ✅ 正确：GET 请求参数绑定到对象（无 @RequestBody）
@GetMapping("/users")
public List<User> getUsers(UserQuery query) {
    // 自动从 query string 绑定：?name=zhang&age=20
    return userService.query(query);
}
```

---

### 2. @RequestParam 的 required 属性

```java
// ❌ 错误：required 默认为 true，不传参数会抛异常
@GetMapping("/users")
public User getUser(@RequestParam String id) { }

// ✅ 正确：设置 required = false，或用 Optional
@GetMapping("/users")
public User getUser(@RequestParam(required = false) String id) { }

@GetMapping("/users")
public User getUser(@RequestParam Optional<String> id) { }
```

---

### 3. 拦截器的执行顺序

```
preHandle()（按注册顺序执行）
    ↓
Controller 方法执行
    ↓
postHandle()（按注册顺序**逆序**执行）
    ↓
afterCompletion()（按注册顺序**逆序**执行）
```

> `postHandle()` 和 `afterCompletion()` 在 `@ResponseBody` / `@RequestBody` 场景下**可能不执行**（响应已写入）。
> 解决：用 `ResponseBodyAdvice` 或 `HandlerInterceptor` 的 `afterConcurrentHandlingStarted()`。

---

### 4. 静态资源访问

```
classpath:/static/       ← 推荐（js/css/images）
classpath:/public/
classpath:/resources/
classpath:/META-INF/resources/
```

> 访问路径：`http://localhost:8080/css/style.css`  
> 对应文件位置：`classpath:/static/css/style.css`

---

## 我的理解

**Spring Boot Web 开发的本质**：

1. `WebMvcAutoConfiguration` 自动配置了 Spring MVC 的所有组件
2. `DispatcherServlet` 是前端控制器，统一入口
3. `HandlerMethodArgumentResolver` 负责参数绑定
4. `HttpMessageConverter` 负责 HTTP 消息转换（JSON）
5. 全局异常处理用 `@ControllerAdvice`，拦截器用 `HandlerInterceptor`

**面试高频追问**：

1. Spring MVC 的请求处理流程（DispatcherServlet → HandlerMapping → HandlerAdapter → Controller）
2. 参数绑定的原理（HandlerMethodArgumentResolver）
3. 拦截器的执行顺序（preHandle 正序，postHandle/afterCompletion 逆序）
4. `@ResponseBody` 的原理（HttpMessageConverter）
5. 全局异常处理的实现方式（`@ControllerAdvice` + `@ExceptionHandler`）

---
