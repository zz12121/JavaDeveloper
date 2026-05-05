# IoC 容器与依赖注入

## 这个问题为什么存在？

> 传统编程：对象自己 `new` 依赖 → 高度耦合，改不了、测不了。  
> IoC：把「对象创建」交给外部容器 → 控制权反转。

**没有 IoC 的问题**：

```java
class OrderService {
    private UserService userService = new UserService();  // ❌ 强耦合
    private PaymentService payment = new PaymentService();
}
```

> 如果要换 `UserService` 的实现，需要改代码。  
> 如果要测试 `OrderService`，无法 mock `UserService`。

**IoC 的核心**：把「创建」和「使用」分离，依赖由外部注入。

---

## 它是怎么解决问题的？

### Spring IoC 容器的启动流程

```
ApplicationContext ctx = new ClassPathXmlApplicationContext("spring.xml");
// 或者
ApplicationContext ctx = new AnnotationConfigApplicationContext(AppConfig.class);
```

启动流程（分 4 个阶段）：

```
┌──────────────────────────────────────────────────────┐
│ 1. 容器创建阶段                                        │
│    new AnnotationConfigApplicationContext(AppConfig.class)
│    ├─ 创建 BeanFactory（DefaultListableBeanFactory）
│    ├─ 创建 AnnotatedBeanDefinitionReader
│    └─ 创建 ClassPathBeanDefinitionScanner
├──────────────────────────────────────────────────────┤
│ 2. BeanDefinition 加载阶段                            │
│    reader.register(AppConfig.class)
│    ├─ 扫描 @Configuration 类
│    ├─ 解析 @ComponentScan
│    └─ 扫描 + 注册所有 @Component 类 → BeanDefinitionMap
├──────────────────────────────────────────────────────┤
│ 3. BeanDefinition 合并阶段                            │
│    invokeBeanFactoryPostProcessors()
│    ├─ BeanFactoryPostProcessor（可以修改 BeanDefinition）
│    ├─ BeanDefinitionRegistryPostProcessor
│    └─ ConfigurationClassPostProcessor（@Import 等高级特性）
├──────────────────────────────────────────────────────┤
│ 4. Bean 实例化阶段（核心）                             │
│    preInstantiateSingletons()
│    ├─ createBean(BeanName)
│    │   ├─ 1. resolveBeanClass() 加载类
│    │   ├─ 2. applyMergedBeanDefinitionPostProcessor() 合并
│    │   ├─ 3. populateBean() 依赖注入（属性填充）
│    │   ├─ 4. initializeBean() 初始化
│    │   └─ 5. registerDisposableBean() 注册销毁回调
│    └─ BeanPostProcessor（后置处理，@Autowired 等）
└──────────────────────────────────────────────────────┘
```

---

### 源码关键路径：refresh()（容器刷新）

```java
// AbstractApplicationContext.refresh()
public void refresh() throws BeansException {
    // 1. 创建 BeanFactory
    ConfigurableListableBeanFactory beanFactory = obtainFreshBeanFactory();

    // 2. 准备 BeanFactory（设置类加载器、spel、属性编辑器等）
    prepareBeanFactory(beanFactory);

    // 3. 允许子类修改 BeanFactory（Spring 5.x 新增）
    postProcessBeanFactory(beanFactory);

    // 4. 执行 BeanFactoryPostProcessor（重要：可以修改 BeanDefinition）
    invokeBeanFactoryPostProcessors(beanFactory);

    // 5. 注册 BeanPostProcessor（Bean 初始化前后的拦截器）
    registerBeanPostProcessors(beanFactory);

    // 6. 初始化 MessageSource（国际化）
    initMessageSource(beanFactory);

    // 7. 初始化事件广播器
    initApplicationEventMulticaster();

    // 8. onRefresh（留给子类，比如 Spring Boot）
    onRefresh();

    // 9. 注册监听器
    registerListeners();

    // 10. 重点：实例化所有单例 Bean
    finishBeanFactoryInitialization(beanFactory);

    // 11. 完成刷新（发布 ContextRefreshedEvent）
    finishRefresh();
}
```

---

### 源码关键路径：createBean()

```java
// AbstractAutowireCapableBeanFactory.createBean()
protected Object createBean(String beanName, RootBeanDefinition mbd,
                            @Nullable Object[] args) {
    // 1. 解析类的 Class 对象
    Class<?> resolvedClass = resolveBeanClass(mbd, beanName);

    // 2. 合并 BeanDefinition（父子 BeanDefinition 合并）
    mbd = getMergedLocalBeanDefinition(beanName);

    // 3. 给 BeanFactoryPostProcessor 机会修改 BeanDefinition
    //    （比如用占位符解析 ${jdbc.url}）
    String[] dependsOn = mbd.getDependsOn();
    if (dependsOn != null) {
        for (String dep : dependsOn) registerDependentBean(dep, beanName);
    }

    // 4. 实例化前回调（InstantiationAwareBeanPostProcessor）
    Object bean = resolveBeforeInstantiation(beanName, mbd);
    if (bean != null) return bean;  // 有自定义 Instantiation → 直接返回

    // 5. 真正创建 Bean
    Object beanInstance = doCreateBean(beanName, mbd, args);
    return beanInstance;
}
```

---

### 源码关键路径：doCreateBean()（实例化的核心）

```java
protected Object doCreateBean(String beanName, RootBeanDefinition mbd,
                              @Nullable Object[] args) {
    // 1. 创建 Bean 实例（通过构造函数或工厂方法）
    if (instanceSupplier != null) {
        bean = instanceSupplier.get();
    } else {
        bean = createBeanInstance(beanName, mbd, args);
        // ⚠️ 构造函数选择逻辑（按 @Autowired 的 required 决定）
    }

    // 2. MergedBeanDefinitionPostProcessor（把 autowired 字段信息提取出来）
    applyMergedBeanDefinitionPostProcessors(mbd, beanType, beanName);

    // 3. 提前暴露 Bean（用于解决循环依赖）
    boolean earlySingletonExposure = (mbd.isSingleton()
        && this.allowCircularReferences);
    if (earlySingletonExposure) {
        addSingletonFactory(beanName, () -> getEarlyBeanReference(beanName, mbd, bean));
    }

    // 4. 属性填充（依赖注入）
    populateBean(beanName, mbd, instanceWrapper);

    // 5. 初始化（init-method、@PostConstruct、InitializingBean）
    bean = initializeBean(beanName, bean, mbd);

    // 6. 注册销毁逻辑
    registerDisposableBeanIfNecessary(beanName, bean, mbd);

    return bean;
}
```

---

### 依赖注入的时机：populateBean()

```java
// AbstractAutowireCapableBeanFactory.populateBean()
protected void populateBean(String beanName, BeanDefinition mbd,
                           @Nullable BeanWrapper bw) {
    // 1. 读取 PropertyValues（XML 或 @Value）
    PropertyValues pvs = mbd.getPropertyValues();

    // 2. InstantiationAwareBeanPostProcessor（@Autowired 注解在这里处理）
    for (InstantiationAwareBeanPostProcessor ibp : getBeanPostProcessors()) {
        PropertyValues pvsToUse = ibp.postProcessProperties(pvs, bw, beanName);
        // ⚠️ AutowiredAnnotationBeanPostProcessor 在这里
        //    遍历所有字段 + setter，找到 @Autowired 注解
        //    → 执行 setter 或字段注入
    }

    // 3. 简单属性注入（XML <property> 或 @Value）
    applyPropertyValues(beanName, mbd, bw, pvs);
}
```

**`@Autowired` 的处理流程**：

```
AutowiredAnnotationBeanPostProcessor.postProcessProperties()
  │
  ├─ findAutowiringMetadata()  ← 读取类的 @Autowired 字段
  │     （第一次读取时用反射解析，缓存到 metadata）
  │
  ├─ bean.resolveCandidate()  ← 根据类型查找 Bean（byType）
  │     → beanFactory.getBean(beanName)
  │
  └─ InjectionMetadata.inject()  ← 把找到的 Bean 注入到字段
        this.field.set(bean, resolvedValue);  // 反射注入
```

---

### Spring 如何解决循环依赖（提前暴露）

```
场景：A 依赖 B，B 依赖 A

1. 创建 A（半成品，未填充属性）
2. 发现 A 需要注入 B → 创建 B（半成品，未填充属性）
3. 发现 B 需要注入 A
4. 从「早期引用缓存」找到 A 的早期引用 → 注入 B
5. B 填充完成 → 返回给 A
6. A 注入 B → A 填充完成

关键：「三级缓存」
  ├─ 一级：singletonObjects      （完全初始化好的 Bean）
  ├─ 二级：earlySingletonObjects （提前暴露的 Bean，未填充属性）
  └─ 三级：singletonFactories    （ObjectFactory，提前暴露工厂）

提前暴露原理：
  doCreateBean() 中：
    addSingletonFactory(beanName, () -> getEarlyBeanReference(beanName, mbd, bean))
  → 往三级缓存放一个 ObjectFactory
  → 依赖注入时，从三级缓存取出，调用 getObject() → 创建代理或返回原对象
  → 移动到二级缓存（避免重复创建）
```

---

## 它和相似方案的本质区别是什么？

### 构造器注入 vs Setter 注入 vs 字段注入

| 注入方式 | 优点 | 缺点 |
|----------|------|------|
| **构造器注入** | 不可变、强制依赖、测试友好 | 参数多时构造函数很长 |
| **Setter 注入** | 可选依赖、可变 | 可选依赖可能未注入（NPE） |
| **字段注入（@Autowired）** | 代码简洁 | 违反单一职责、测试困难、违反 OOP |

**Spring 官方推荐**：**构造器注入**。

```java
// ✅ 推荐：构造器注入
@Service
class OrderService {
    private final UserService userService;  // final，不可变
    private final PaymentService paymentService;

    @Autowired  // 可省略（构造器注入是 Spring 5.x 默认）
    public OrderService(UserService userService, PaymentService paymentService) {
        this.userService = userService;
        this.paymentService = paymentService;
    }
}

// ❌ 不推荐：字段注入
@Service
class OrderService {
    @Autowired  // 反射注入，违反 OOP
    private UserService userService;  // 难以 mock
}
```

---

### @Component vs @Bean vs @Configuration

| | @Component | @Bean | @Configuration |
|--|------------|-------|----------------|
| **使用位置** | 类上 | 方法上（在 @Configuration 类里） | 类上 |
| **适合场景** | 自定义类（Spring 自动扫描） | 第三方库（不能加 @Component） | 组合多个 @Bean |
| **代理方式** | 默认 CGLIB | 默认 CGLIB（@Configuration） | CGLIB 代理保证单例 |
| **Bean 名称** | 类名首字母小写 | 方法名 | 类名首字母小写 |

**`@Configuration` 为什么用 CGLIB 代理？**

```java
@Configuration
class AppConfig {
    @Bean
    UserService userService() {
        return new UserService();
    }

    @Bean
    OrderService orderService() {
        return new OrderService(userService());  // 如果不是代理，会每次 new！
    }
}
```

> `@Configuration` 类被 CGLIB 代理后，`userService()` 调用会被拦截 →  
> 返回 `beanFactory.getBean("userService")`（从容器拿同一个实例）。  
> → 保证 `userService()` 在同一个 `@Configuration` 类里调用时，总是返回同一个 Bean。

---

## 正确使用方式

### 1. @Primary vs @Qualifier

```java
// 多个同类型 Bean
@Component
@Primary
class AlipayService implements PaymentService {}

@Component
class WechatPayService implements PaymentService {}

// 使用时
@Autowired
PaymentService payment;  // 自动注入 AlipayService（@Primary）

@Autowired
@Qualifier("wechatPayService")
PaymentService payment;  // 显式指定
```

### 2. @Lazy 延迟初始化

```java
// Bean 在第一次使用时才创建（不启动就创建）
@Component
@Lazy
class HeavyService { }

// 或者在 @Bean 上
@Bean
@Lazy
HeavyService heavyService() { return new HeavyService(); }
```

### 3. @Conditional 条件注册

```java
// 只有在 Linux 环境下才注册
@Component
@ConditionalOnOs(OS.LINUX)
class LinuxService { }

// 自定义条件
@Component
@Conditional(MyCondition.class)
class MyService { }
```

---

## 边界情况和坑

### 1. 循环依赖 + 构造函数注入 → 无法解决

```java
// ❌ 构造器循环依赖：Spring 无法解决（启动失败）
@Service
class A {
    private final B b;
    public A(B b) { this.b = b; }  // A 需要 B
}

@Service
class B {
    private final A a;
    public B(A a) { this.a = a; }  // B 需要 A
    // Spring 启动失败：BeanCurrentlyInCreationException
}

// ✅ 解决：至少有一个改成 Setter 注入
@Service
class A {
    private B b;
    @Autowired
    public void setB(B b) { this.b = b; }  // Setter 注入，Spring 可以解决
}
```

> 构造器循环依赖：在实例化 A 时，需要 B（但 B 还没创建完）→ 死锁。  
> Setter 循环依赖：先创建 A 和 B（空对象），再填充属性 → 可以解决。

---

### 2. 多例 Bean 的循环依赖 → 无法解决

```java
// ❌ prototype Bean 不支持循环依赖
@Scope("prototype")
class A { @Autowired B b; }
@Scope("prototype")
class B { @Autowired A a; }

// 每次 getBean("a") 都会创建新实例
// Spring 无法提前暴露 prototype Bean → 循环依赖无法解决
```

---

### 3. @Autowired 的 required=false + 字段注入

```java
// ❌ 危险：required=false 时用字段注入
@Service
class Demo {
    @Autowired(required = false)
    private Optional<LogService> logService;  // 字段注入，Spring 可能不处理
    // 如果 LogService 不存在，logService 为 null，不是 Optional.empty()
}

// ✅ 正确：构造器注入 + @Autowired(required = false)
@Service
class Demo {
    private final Optional<LogService> logService;

    @Autowired(required = false)
    public Demo(Optional<LogService> logService) {
        this.logService = logService != null ? logService : Optional.empty();
    }
}
```

---

