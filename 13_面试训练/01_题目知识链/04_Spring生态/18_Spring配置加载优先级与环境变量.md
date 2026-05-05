# Spring 配置加载优先级与环境变量

> ⚠️ **先盲答**：application.yml、环境变量、命令行参数，同时配置了同一个属性，谁生效？

---

## 盲答引导

1. Spring Boot 支持哪些配置源？
2. 配置文件的加载顺序（优先级）？
3. profile 切换是怎么工作的？
4. `@ConfigurationProperties` 和 `@Value` 的区别？
5. 配置中心（Nacos/Config）在优先级中处于什么位置？

---

## 知识链提示

```
Spring 配置体系
  → [[SpringBoot自动配置]]
    → 1. 配置源类型
      → 配置文件：application.properties / application.yml / application.yaml
      → 配置profile：application-{profile}.yml
      → 环境变量：OS 环境变量（SPRING_DATASOURCE_URL）
      → JVM 参数：-Dspring.datasource.url=xxx
      → 命令行参数：--spring.datasource.url=xxx
      → 配置中心：Nacos / Spring Cloud Config（外部化配置）
    → 2. 优先级完整顺序（从高到低）
      → ① 命令行参数（--key=value）← 最高
      → ② Java 系统属性（-Dkey=value）
      → ③ OS 环境变量
      → ④ 配置中心（远程配置）
      → ⑤ application-{profile}.yml（jar 包外 > jar 包内）
      → ⑥ application-{profile}.yml（jar 包内）
      → ⑦ application.yml（jar 包外 > jar 包内）
      → ⑧ application.yml（jar 包内）
      → ⑨ @ConfigurationProperties 默认值
      → 规则：后加载的覆盖先加载的（实际上是从低到高，最后者胜出）
      → 准确说：序号越小越先生效，但后加载的会覆盖之前的值
      → 重新整理（数字越小优先级越高）：
        1. 命令行参数
        2. Java 系统属性（-D）
        3. OS 环境变量
        4. 配置中心（远程）
        5. jar 包外的 application-{profile}.yml
        6. jar 包内的 application-{profile}.yml
        7. jar 包外的 application.yml
        8. jar 包内的 application.yml
    → 3. profile 机制
      → spring.profiles.active=dev → 激活 dev 环境
      → 会加载 application-dev.yml，并覆盖 application.yml 中的同名配置
      → 多 profile：spring.profiles.active=dev,db,mq（逗号分隔）
      → 默认 profile：spring.profiles.default=default
    → 4. 配置绑定
      → @ConfigurationProperties(prefix="xxx")
        → 批量绑定，支持嵌套对象、集合、Map
        → 支持 Relaxed Binding：xxx.user-name / xxx.userName / xxx.user_name 都能绑定到 userName 属性
        → 支持 JSR-303 校验（@Validated）
      → @Value("${xxx.yyy}")
        → 单个值注入，不支持 Relaxed Binding
        → 支持 SpEL 表达式
    → 5. 配置加载源码入口
      → SpringApplication.prepareEnvironment()
      → 通过 EnvironmentPostProcessor 加载所有配置源
      → ConfigFileApplicationListener（旧）/ ConfigDataEnvironmentPostProcessor（新）
    → 6. 常见坑点
      → yml 缩进用空格，不能用 Tab
      → 冒号后必须有空格（key: value）
      → 配置中心的配置优先级高于本地文件（但低于命令行参数）
```

---

## 核心追问

| 追问 | 考点 |
|------|------|
| `@Value` 能注入静态变量吗？ | 不能，`@Value` 是基于 Bean 实例化的，静态变量在类加载时初始化 |
| yml 和 properties 同时配置，谁生效？ | 同一优先级位置，properties 覆盖 yml（后加载）；但不建议混用 |
| 如何在代码中读取当前激活的 profile？ | `Environment.getActiveProfiles()` |
| 配置中心的配置什么时候加载？ | `EnvironmentPostProcessor` 阶段（非常早，在 Bean 初始化之前） |

---

## 参考答案要点

**优先级口诀**：命令行 > JVM参数 > 环境变量 > 配置中心 > jar外profile > jar内profile > jar外默认 > jar内默认。

**profile 覆盖**：`application-{profile}.yml` 的配置会覆盖 `application.yml` 中的同名配置项，未覆盖的保留。

**@ConfigurationProperties vs @Value**：前者批量绑定 + 宽松绑定 + 校验，后者单值注入 + SpEL 支持。

**配置中心**：通过 `EnvironmentPostProcessor` 在启动早期注入配置，优先级高于本地文件。

---

## 下一步

打开 [[SpringBoot自动配置]]，补充 `[[双向链接]]`：「配置优先级是面试高频坑点——记住：命令行参数最优先，后加载的覆盖先加载的（就近原则）」。
