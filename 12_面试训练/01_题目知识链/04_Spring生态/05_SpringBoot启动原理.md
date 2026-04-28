# Spring Boot 的启动流程是怎样的？

> ⚠️ **先盲答**：`SpringApplication.run()` 里面做了什么？

---

## 盲答引导

1. Spring Boot 启动分为哪两个阶段？—— 启动引导（SpringApplication 构造）/ 运行（run() 方法）
2. `ApplicationContext` 有哪几种类型？—— AnnotationConfigServletWebServerApplicationContext（Web） / AnnotationConfigApplicationContext（非 Web）
3. `SpringApplication.run()` 的核心步骤有哪些？—— 10 几步，至少说出 5 个
4. 什么是「启动监听器」？—— SpringApplicationRunListeners

---

## 知识链提示

```
Spring Boot 启动原理
  → [[Spring Boot启动原理]]
    → 阶段一：SpringApplication 构造
      → 推断应用类型（Web / 非 Web / Reactive）
      → 加载 ApplicationContextInitializer（META-INF/spring.factories）
      → 加载 ApplicationListener（META-INF/spring.factories）
    → 阶段二：run() 方法（核心 12 步）
      → 1. 启动计时（StopWatch）
      → 2. 通知所有 SpringApplicationRunListener：starting()
      → 3. 准备 Environment（配置文件：application.yml / profile）
      → 4. 通知：environmentPrepared()
      → 5. 打印 Banner
      → 6. 创建 ApplicationContext（根据应用类型决定用哪个实现）
      → 7. 准备 Context（设置 Environment / 执行 Initializer）
      → 8. 通知：contextPrepared()
      → 9. 加载 BeanDefinition（@ComponentScan / @Import / @Bean）
      → 10. 通知：contextLoaded()
      → 11. refresh Context（调用 AbstractApplicationContext.refresh() → 核心九大步骤）
      → 12. 通知：started() / running()
    → 阶段三：调用 ApplicationRunner / CommandLineRunner
```

---

## 核心追问

| 追问 | 考点 |
|------|------|
| `refresh()` 方法是干什么的？ | [[上下文刷新]] → 核心九大步骤，真正初始化容器 |
| `ApplicationRunner` 和 `CommandLineRunner` 的区别？ | ApplicationRunner 接收 ApplicationArguments，CommandLineRunner 接收 String[] |
| 如何在启动过程中插手？ | 实现 ApplicationContextInitializer / ApplicationListener |
| 为什么 Spring Boot 启动快？ | 自动配置（按需加载）+ 内嵌容器（不用部署 WAR） |

---

## 参考答案要点

**启动流程简化版**：
```
SpringApplication.run()
  → 构造 SpringApplication（推断类型 / 加载初始化器 / 加载监听器）
  → run()
    → 准备 Environment（读配置文件）
    → 创建 ApplicationContext
    → 加载所有 BeanDefinition
    → refresh()（初始化容器，九大步骤）
    → 调用 Runner（ApplicationRunner / CommandLineRunner）
```

**核心在 `refresh()`**：九大步骤（BeanFactory 准备 / BeanFactoryPostProcessor / BeanPostProcessor / 初始化单例 Bean）。

---

## 下一步

打开 [[Spring Boot启动原理]]，关联 [[上下文刷新]]，补充链接：「启动流程的核心在 `refresh()`——它完成了 BeanFactory 准备、后处理器执行、单例 Bean 初始化等所有工作」。
