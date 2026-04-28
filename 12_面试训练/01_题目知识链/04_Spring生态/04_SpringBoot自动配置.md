# Spring Boot 的自动配置是怎么实现的？

> ⚠️ **先盲答**：为什么只写一个 `@SpringBootApplication` 就能启动整个应用？

---

## 盲答引导

1. `@SpringBootApplication` 是个组合注解，它包含了哪三个注解？
2. `spring.factories`（或 `META-INF/spring/org.springframework.boot.autoconfigure.AutoConfiguration.imports`）是干什么的？
3. 条件注解（`@ConditionalOnClass` 等）是怎么控制自动配置是否生效的？
4. 如何覆盖/禁用某个自动配置？—— `@SpringBootApplication(exclude=...)` / `spring.autoconfigure.exclude`

---

## 知识链提示

```
Spring Boot 自动配置
  → [[自动配置源码]]
    → @SpringBootApplication = @Configuration + @EnableAutoConfiguration + @ComponentScan
      → @EnableAutoConfiguration：触发自动配置
        → @Import(AutoConfigurationImportSelector.class)
          → selectImports() → 读取 META-INF/spring/org.springframework.boot.autoconfigure.AutoConfiguration.imports（Spring Boot 3.x）
            → 旧版（2.x）：META-INF/spring.factories
    → 自动配置类（XxxAutoConfiguration）
      → 每个配置类上都标了大量 @Conditional* 条件注解
        → @ConditionalOnClass：classpath 下有这个类，才生效
        → @ConditionalOnMissingBean：容器里没有这个 Bean，才生效（用户可以覆盖）
        → @ConditionalOnProperty：配置文件里有这个属性，才生效
        → @ConditionalOnBean：容器里有这个 Bean，才生效
    → 配置的优先级
      → 用户定义的 Bean > 自动配置的 Bean（@ConditionalOnMissingBean）
      → 配置文件的属性 > 默认值
```

---

## 核心追问

| 追问 | 考点 |
|------|------|
| Spring Boot 2.x 和 3.x 的自动配置文件路径有什么区别？ | 2.x：spring.factories；3.x：imports 文件 |
| 如何调试自动配置为什么没生效？ | --debug 启动，查看 ConditionEvaluationReport |
| @ConditionalOnMissingBean 为什么能保证用户定义的 Bean 优先？ | 先执行用户的 @Bean，再执行自动配置，发现已有 Bean 就跳过 |
| Spring Boot 的 starter 是什么？ | 一堆依赖 + 一个 AutoConfiguration 类 |

---

## 参考答案要点

**自动配置的核心流程**：
1. `@EnableAutoConfiguration` → 触发 `AutoConfigurationImportSelector`
2. 读取 `imports` 文件 → 拿到所有自动配置类
3. 过滤条件注解（@Conditional*）→ 只有满足条件的配置类才生效
4. 用户定义的 Bean 优先（`@ConditionalOnMissingBean`）

**用户可以覆盖自动配置**：定义自己的 Bean，自动配置发现已存在就跳过。

---

## 下一步

打开 [[自动配置源码]]，补充 `[[双向链接]]`：「自动配置的精髓在 @ConditionalOnMissingBean——它保证用户定义的 Bean 优先，自动配置只做『兜底』」。
