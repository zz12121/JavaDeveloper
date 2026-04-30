# Spring MVC 执行流程与 DispatcherServlet

> ⚠️ **先盲答**：浏览器发来一个 HTTP 请求，到 Controller 方法被执行，中间经历了什么？

---

## 盲答引导

1. DispatcherServlet 在整个流程中扮演什么角色？
2. HandlerMapping / HandlerAdapter 各自做什么？
3. 拦截器（Interceptor）的执行时机？
4. 视图解析是如何工作的？

---

## 知识链提示

```
HTTP 请求 → DispatcherServlet
  → [[Spring MVC]]
    → 1. DispatcherServlet 初始化（initStrategies）
      → 检测并初始化 8 大组件（HandlerMapping / HandlerAdapter / ViewResolver 等）
      → 启动时完成，运行时不再重复初始化
    → 2. 请求到达 DispatcherServlet.doDispatch()
      → 2.1 getHandler() → HandlerMapping
        → 遍历所有 HandlerMapping，找到能处理当前请求的处理器链（HandlerExecutionChain）
        → 包含：目标 Controller 方法 + 所有匹配的拦截器（Interceptor）
      → 2.2 getHandlerAdapter() → HandlerAdapter
        → 找到支持该 Handler 的适配器（RequestMappingHandlerAdapter 最常用）
        → 适配器模式：统一调用各种类型的 Handler
      → 2.3 执行拦截器 preHandle()
        → 按顺序执行所有 Interceptor.preHandle()
        → 任一返回 false → 中断，触发 afterCompletion()
      → 2.4 HandlerAdapter.handle() → 执行 Controller 方法
        → 参数解析（HandlerMethodArgumentResolver）
        → 方法调用（反射）
        → 返回值处理（HandlerMethodReturnValueHandler）
      → 2.5 执行拦截器 postHandle()
        → 在视图渲染之前调用
      → 2.6 视图解析与渲染
        → ViewResolver.resolveViewName() → 找到 View
        → View.render() → 渲染响应
      → 2.7 执行拦截器 afterCompletion()
        → 无论是否异常都会执行（类似 finally）
    → 3. 异常处理
      → HandlerExceptionResolver 统一处理 Controller 抛出的异常
      → @ExceptionHandler / @ControllerAdvice 在这里生效
    → 核心组件职责
      → DispatcherServlet：中央调度器（前端控制器）
      → HandlerMapping：请求 → Handler 的映射
      → HandlerAdapter：执行 Handler 的适配器
      → ViewResolver：逻辑视图名 → 物理视图
      → HandlerExceptionResolver：统一异常处理
```

---

## 核心追问

| 追问 | 考点 |
|------|------|
| Interceptor 和 Filter 的区别？ | Filter 是 Servlet 规范（请求进入 Servlet 前），Interceptor 是 Spring MVC 规范（Handler 前后）；Filter 依赖 Servlet 容器，Interceptor 可用 Spring 容器资源 |
| @RequestBody 是如何解析参数的？ | RequestResponseBodyMethodProcessor（实现了 HandlerMethodArgumentResolver）|
| 同一个请求被多个 Interceptor 拦截，执行顺序？ | preHandle 正序 → 目标方法 → postHandle 倒序 → afterCompletion 倒序 |
| REST 风格如何匹配 Handler？ | RequestMappingHandlerMapping 基于 @RequestMapping 的 value/method/params/headers 匹配 |

---

## 参考答案要点

**DispatcherServlet 是核心**：所有请求统一经过它，再由它分发到具体的 Controller。

**九大组件**：HandlerMapping、HandlerAdapter、HandlerExceptionResolver、ViewResolver、RequestToViewNameTranslator、LocaleResolver、ThemeResolver、MultipartResolver、FlashMapManager。

**拦截器三方法**：`preHandle`（Handler 前，可中断）、`postHandle`（视图渲染前）、`afterCompletion`（渲染后，必定执行）。

---

## 下一步

打开 [[Spring MVC]]，补充 `[[双向链接]]`：「DispatcherServlet 的本质是一个 Servlet，它把『请求分发』这个横切关注点从业务代码中剥离出来——这就是前端控制器模式」。
