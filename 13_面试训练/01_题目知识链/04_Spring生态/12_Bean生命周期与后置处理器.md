# Bean 生命周期与后置处理器

> ⚠️ **先盲答**：Spring Bean 从创建到销毁经历了哪些阶段？每个阶段能做什么扩展？

---

## 盲答引导

1. Bean 从实例化到销毁的完整流程是什么？
2. BeanPostProcessor 和 BeanFactoryPostProcessor 有什么区别？
3. @PostConstruct 和 afterPropertiesSet() 的执行顺序？
4. Aware 接口回调在哪个阶段？

---

## 知识链提示

```
Bean 生命周期（完整版）
  → [[IoC容器]] → BeanDefinition → 实例化 → 属性赋值 → 初始化 → 销毁
    → 1. BeanFactoryPostProcessor（容器启动阶段，修改 BeanDefinition）
      → 在所有 Bean 实例化之前执行
      → 可以修改 BeanDefinition 的元信息（propertyValues / scope 等）
      → 典型应用：PropertySourcesPlaceholderConfigurer（占位符替换）
    → 2. 实例化（createBeanInstance）
      → 通过构造函数反射创建对象（相当于 new）
      → 推断构造函数（@Autowired 构造函数 / 默认构造函数）
    → 3. 属性赋值（populateBean）
      → @Autowired / @Value / @Resource 在这里完成注入
      → 依赖的 Bean 如果还没创建，会递归触发创建
    → 4. Aware 接口回调
      → BeanNameAware → setBeanName()
      → BeanFactoryAware → setBeanFactory()
      → ApplicationContextAware → setApplicationContext()
      → 执行顺序：先 BeanNameAware，再 BeanFactoryAware
    → 5. BeanPostProcessor.postProcessBeforeInitialization
      → 所有 BeanPostProcessor 的 before 方法
      → @PostConstruct 就是在这里被触发的（InitDestroyAnnotationBeanPostProcessor）
    → 6. 初始化（afterPropertiesSet + init-method）
      → InitializingBean.afterPropertiesSet()
      → 自定义 init-method / @Bean(initMethod=...)
    → 7. BeanPostProcessor.postProcessAfterInitialization
      → AOP 代理就是在这里生成的（AbstractAutoProxyCreator）
      → 返回代理对象替代原始对象
    → 8. Bean 就绪，放入单例池（singletonObjects）
    → 9. 销毁阶段
      → @PreDestroy → DisposableBean.destroy() → destroy-method
      → 容器关闭时触发（ConfigurableApplicationContext.close()）
    → BeanPostProcessor vs BeanFactoryPostProcessor
      → BeanFactoryPostProcessor：操作 BeanDefinition（元数据层面）
      → BeanPostProcessor：操作 Bean 实例（对象层面）
      → 执行时机不同：前者在实例化前，后者在初始化前后
```

---

## 核心追问

| 追问 | 考点 |
|------|------|
| @PostConstruct 和 afterPropertiesSet() 谁先执行？ | @PostConstruct 先（在 postProcessBeforeInitialization 中触发） |
| BeanPostProcessor 能处理所有 Bean 吗？ | 能，但 BeanPostProcessor 本身是由一个特殊的 BeanPostProcessor 创建的（先有鸡还是先有蛋） |
| 原型（prototype）Bean 的销毁回调会执行吗？ | 不会，Spring 只管理单例 Bean 的销毁 |
| SmartInstantiationAwareBeanPostProcessor 有什么用？ | 可以提前暴露早期 Bean 引用，解决循环依赖的关键接口 |

---

## 参考答案要点

**完整顺序**：实例化 → 属性注入 → Aware回调 → `@PostConstruct` → `afterPropertiesSet()` → `init-method` → AOP代理 → 就绪 → `@PreDestroy` → `destroy()` → `destroy-method`

**两个后置处理器**：`BeanFactoryPostProcessor` 改 BeanDefinition（实例化前），`BeanPostProcessor` 改 Bean 实例（初始化前后）。

**AOP 代理时机**：`postProcessAfterInitialization`——初始化完成后才生成代理对象。

---

## 下一步

打开 [[BeanDefinition]]，补充 `[[双向链接]]`：「Bean 生命周期的每个阶段都暴露了扩展点，理解每个扩展点的时机是掌握 Spring 的关键」。
