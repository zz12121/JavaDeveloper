# SpringBoot Starter 原理与自动配置进阶

> ⚠️ **先盲答**：为什么引入一个 Starter 依赖，相关功能就自动配置好了？自动配置是怎么「猜」到你需要什么 Bean 的？

---

## 盲答引导

1. SpringBoot 自动配置的核心注解是什么？
2. `spring.factories` 和 `AutoConfiguration.imports` 有什么区别？
3. `@Conditional` 条件注解家族有哪些？
4. 如何自定义一个 Starter？

---

## 知识链提示

```
SpringBoot 自动配置
  → [[13_面试训练/01_题目知识链/04_Spring生态/04_SpringBoot自动配置]]
    → 核心注解：@EnableAutoConfiguration
      → 放在 @SpringBootApplication 里（复合注解）
      → 通过 @Import(AutoConfigurationImportSelector.class) 生效
    → 配置文件加载机制（版本差异）
      → SpringBoot 2.x：META-INF/spring.factories → key=org.springframework.boot.autoconfigure.EnableAutoConfiguration
      → SpringBoot 3.x：META-INF/spring/org.springframework.boot.autoconfigure.AutoConfiguration.imports（纯文本，每行一个类）
      → AutoConfigurationImportSelector 读取这些文件，批量导入自动配置类
    → 条件注解家族（@Conditional 派生）
      → @ConditionalOnClass：classpath 存在指定类才生效
      → @ConditionalOnMissingBean：容器中不存在该 Bean 才生效（给用户覆盖的机会）
      → @ConditionalOnBean：容器中存在指定 Bean 才生效
      → @ConditionalOnProperty：配置文件中存在指定属性才生效
      → @ConditionalOnWebApplication / @ConditionalOnNotWebApplication
    → 自动配置类的本质
      → 就是一个普通的 @Configuration 类
      → 通过条件注解控制是否生效
      → 生效的 Bean 定义被注册到容器
    → 自定义 Starter 步骤
      → 1. 创建 autoconfigure 模块（放自动配置类）
      → 2. 创建 starter 模块（空 Jar，只做依赖聚合）
      → 3. 在 autoconfigure 的 META-INF/spring/*.imports 中注册自动配置类
      → 4. 使用 @ConditionalOnClass 检测用户是否引入了相关依赖
      → 5. 使用 @EnableConfigurationProperties 绑定配置属性类
    → 配置属性绑定
      → @ConfigurationProperties(prefix = "xxx")
      → 将 application.yml 中的属性绑定到 Java Bean
      → 支持宽松绑定（kebab-case / camelCase / snake_case 都能识别）
    → 自动配置的执行顺序
      → @AutoConfigureBefore / @AutoConfigureAfter / @AutoConfigureOrder
      → 控制自动配置类之间的相对顺序
```

---

## 核心追问

| 追问 | 考点 |
|------|------|
| 为什么要用 `@ConditionalOnMissingBean`？ | 给用户提供覆盖自动配置的机会——用户自己定义了 Bean，自动配置就不生效 |
| Starter 模块和 Autoconfigure 模块为什么要分开？ | 职责分离：starter 是依赖入口（空 Jar），autoconfigure 是实际配置；用户可以只引入 autoconfigure 做精细控制 |
| `@ConfigurationProperties` 和 `@Value` 的区别？ | 前者批量绑定（支持校验、嵌套对象），后者单个注入；前者支持 Relaxed Binding，后者不支持 |
| 自动配置类会被全部加载吗？ | 不会，通过条件注解过滤，只加载满足条件的 |

---

## 参考答案要点

**核心机制**：`AutoConfigurationImportSelector` 读取配置文件 → 条件过滤 → 注册符合条件的配置类。

**条件注解是关键**：`@ConditionalOnClass` 检测依赖是否存在，`@ConditionalOnMissingBean` 允许用户覆盖。

**Starter 设计精髓**：「检测依赖存在 → 自动配置 Bean → 允许用户覆盖」，三层递进。

**版本差异**：2.x 用 `spring.factories`，3.x 改用 `*.imports` 文件（更高效，按需加载）。

---

## 下一步

打开 [[13_面试训练/01_题目知识链/04_Spring生态/04_SpringBoot自动配置]]，补充 `双向链接`：「自动配置的本质是『条件化注册 Bean』——有这个依赖就配，没有就不配，用户配了就让用户自己决定」。
