# IoC 容器是什么？它是如何工作的？

> ⚠️ **先盲答**：IoC（控制反转）是什么？它和 DI（依赖注入）是一回事吗？

---

## 盲答引导

1. IoC 容器是什么？它管理什么？—— Bean 的创建 / 装配 / 生命周期
2. Bean 的几种注册方式？—— XML / @ComponentScan / @Bean / @Import
3. Bean 的作用域有哪些？—— singleton / prototype / request / session
4. Bean 的生命周期有哪些关键回调？—— init-method / @PostConstruct / DisposableBean

---

## 知识链提示

```
IoC 容器
  → [[04_Spring生态/01_Spring核心/IoC容器]]
    → 核心思想：对象创建权交给容器（Inversion of Control）
      → 传统：A a = new A()（主动创建，强耦合）
      → IoC：容器在合适的时机，把依赖注入到需要的对象（被动接收）
    → Bean 注册
      → @ComponentScan：扫描指定包下的 @Component / @Service / @Repository / @Controller
      → @Bean：方法返回值注册为 Bean
      → @Import：导入配置类 / ImportSelector / ImportBeanDefinitionRegistrar
    → Bean 作用域
      → singleton（默认）：单例，容器内唯一
      → prototype：每次获取都新创建
      → request / session / application（Web 作用域）
    → Bean 生命周期（简化版）
      → 实例化（反射创建对象）
      → 属性赋值（DI 依赖注入）
      → 初始化（@PostConstruct / afterPropertiesSet / init-method）
      → 销毁（@PreDestroy / destroy / destroy-method）
    → BeanDefinition
      → [[04_Spring生态/04_Spring原理深入/BeanDefinition]] → 描述 Bean 的元数据（class / scope / initMethod / destroyMethod 等）
```

---

## 核心追问

| 追问 | 考点 |
|------|------|
| @Autowired 和 @Resource 的区别？ | @Autowired 按类型，@Resource 按名称 |
| 同一类型的 Bean 有多个，怎么指定用哪个？ | @Primary / @Qualifier |
| BeanFactory 和 ApplicationContext 的区别？ | BeanFactory 懒加载，ApplicationContext 启动时预加载 |
| FactoryBean 和 BeanFactory 的区别？ | FactoryBean 是创建复杂 Bean 的工厂，BeanFactory 是容器 |

---

## 参考答案要点

**IoC vs DI**：IoC 是思想（控制反转），DI 是实现手段（依赖注入）。

**Bean 作用域**：默认 singleton（单例），Web 环境有 request / session。

**生命周期回调**：`@PostConstruct` → `afterPropertiesSet()` → `init-method`（三个都会执行，按此顺序）。

---

## 下一步

打开 [[04_Spring生态/01_Spring核心/IoC容器]]，补充 `双向链接`：「IoC 的本质是把『创建对象的权力』从业务代码转交给容器——降低耦合，提升可测试性」。
