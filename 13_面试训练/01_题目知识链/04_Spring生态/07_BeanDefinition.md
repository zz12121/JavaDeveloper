# BeanDefinition 是什么？Spring 是怎么加载 Bean 定义的？

> ⚠️ **先盲答**：BeanDefinition 是什么？它描述了什么信息？

---

## 盲答引导

1. Spring 为什么需要 BeanDefinition，而不是直接用 Class 对象？
2. BeanDefinition 包含哪些信息？—— class / scope / initMethod / destroyMethod / 依赖注入方式
3. BeanDefinitionReader 的作用是什么？—— 把 XML/@Configuration 里的配置转成 BeanDefinition
4. `@ComponentScan` 的扫描过程是怎样的？—— 扫描包 → 找到 @Component → 注册 BeanDefinition

---

## 知识链提示

```
BeanDefinition
  → [[04_Spring生态/04_Spring原理深入/BeanDefinition]]
    → 作用：描述一个 Bean 的元信息
      → BeanClassName：全限定类名
      → Scope：singleton / prototype
      → ConstructorArgumentValues：构造参数
      → PropertyValues：属性值（DI）
      → InitMethodName：初始化方法名
      → DestroyMethodName：销毁方法名
      → LazyInit：是否懒加载
    → 加载过程
      → XML：XmlBeanDefinitionReader → 解析 <bean> 标签 → BeanDefinition
      → @Configuration + @Bean：ConfigurationClassBeanDefinitionReader
      → @ComponentScan + @Component：ClassPathBeanDefinitionScanner
        → 扫描 classpath → 找 @Component → 生成 BeanDefinition → 注册到 BeanFactory
    → BeanFactoryPostProcessor
      → 在 Bean 实例化之前，可以修改 BeanDefinition（如修改 scope / 属性值）
      → 经典应用：ConfigurationClassPostProcessor（处理 @Configuration）
```

---

## 核心追问

| 追问 | 考点 |
|------|------|
| BeanDefinition 和 Bean 是一回事吗？ | 不是，BeanDefinition 是 Bean 的「配方」，Bean 是根据配方「做出来的菜」|
| BeanFactoryPostProcessor 和 BeanPostProcessor 的区别？ | 前者修改 BeanDefinition（Bean 还没创建），后者修改 Bean 实例（Bean 已创建）|
| BeanDefinition 什么时候被实例化成 Bean？ | AbstractApplicationContext.refresh() 的 finishBeanFactoryInitialization() |
| 为什么需要 BeanDefinition？ | Spring 需要在创建 Bean 之前知道很多元信息（scope / 构造参数 / 生命周期回调）|

---

## 参考答案要点

**BeanDefinition = Bean 的「配方卡」**：BeanFactory 根据这张卡片，决定怎么创建这个 Bean。

**BeanDefinition 不是 Bean**：BeanDefinition 描述「怎么创建」，Bean 是「创建出来的实例」。

---

## 下一步

打开 [[04_Spring生态/04_Spring原理深入/BeanDefinition]]，补充 `双向链接`：「BeanDefinition 是 Spring IoC 容器的基础——没有 BeanDefinition，容器就不知道该怎么创建 Bean」。
