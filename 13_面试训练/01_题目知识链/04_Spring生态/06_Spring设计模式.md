# Spring 用了哪些设计模式？

> ⚠️ **先盲答**：Spring 源码里能看到哪些设计模式？说出三个以上。

---

## 盲答引导

1. IoC 容器是哪种设计模式？—— 工厂模式 + 策略模式
2. `BeanFactory` 的 `getBean()` 体现了什么模式？—— 工厂模式
3. AOP 的实现用了什么模式？—— 代理模式（Decorator/代理）
4. `JdbcTemplate` 用的是什么模式？—— 模板方法模式

---

## 知识链提示

```
Spring 设计模式
  → [[04_Spring生态/01_Spring核心/Spring设计模式]]
    → 工厂模式
      → BeanFactory / FactoryBean
      → BeanFactory 根据 BeanDefinition 创建 Bean
      → FactoryBean 接口：用于创建复杂 Bean（如 MyBatis SqlSessionFactory）
    → 单例模式
      → Spring 默认单例（singleton Bean）
      → 非线程安全，所以 Bean 里不要有可变成员变量
    → 代理模式
      → AOP [[04_Spring生态/01_Spring核心/AOP]]：Spring AOP 基于 JDK 动态代理 / CGLib
      → JPA [[05_持久层框架/01_MyBatis/08_事务管理]]：EntityManager 背后是 Hibernate 代理
    → 模板方法模式
      → JdbcTemplate / RestTemplate / RedisTemplate
      → 固定流程抽象出来，可变步骤由子类实现
      → JdbcTemplate.query()：模板方法，ResultSetExtractor 由调用者提供
    → 策略模式
      → IoC 容器：根据 @Conditional 条件选择不同的实现
      → Spring Boot自动配置：根据 classpath 选择配置
    → 观察者模式
      → ApplicationContext 事件机制：ApplicationEventPublisher → ApplicationListener
      → Spring Boot 启动时的监听器链：SpringApplicationRunListeners
    → 装饰器模式
      → BeanWrapper：包装 Bean，动态增加行为
      → InputStreamReader：包装 InputStream，添加编码转换
```

---

## 核心追问

| 追问 | 考点 |
|------|------|
| 工厂模式和抽象工厂的区别？ | 工厂模式：创建一种产品；抽象工厂：创建一族产品 |
| 为什么 Spring Bean 默认是单例？ | 单例复用，减少对象创建开销（单例对象无状态才是正确的）|
| 为什么单例 Bean 里不要有可变成员变量？ | 多线程并发访问，可能脏数据 |
| Spring 中的 BeanPostProcessor 用了什么模式？ | 装饰器模式（后置处理器包装 Bean）|

---

## 参考答案要点

**Spring 五大设计模式**：

| 设计模式 | 体现 |
|---------|------|
| 工厂模式 | BeanFactory.getBean() |
| 单例模式 | Spring Bean 默认单例 |
| 代理模式 | AOP 动态代理 |
| 模板方法 | JdbcTemplate / RestTemplate |
| 策略模式 | Conditional 自动选择配置 |

**记忆口诀**：工厂生对象（BeanFactory），单例复用（Singleton），代理做事（AOP），模板填空（Template），策略选方案（Conditional）。

---

## 下一步

打开 [[04_Spring生态/01_Spring核心/Spring设计模式]]，补充 `双向链接`：「Spring 设计模式的精髓在『模板方法』——JdbcTemplate 把 JDBC 流程固化了，可变部分（SQL + 结果解析）由你实现」。
