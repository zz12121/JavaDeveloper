# BeanDefinition

## 这个问题为什么存在？

> Spring 要创建 Bean，但 Bean 的「类是谁」、「作用域是单例还是原型」、「构造器参数是什么」... 这些信息需要一种**统一的数据结构**来描述。  
> 如果没有 `BeanDefinition`，Spring 只能边创建边解析，无法做**提前校验**、**Bean 定义合并**、**动态修改 Bean 定义**。

**BeanDefinition 的本质**：Spring 容器的**元数据模型**（Bean 的「配方」）。

---

## 它是怎么解决问题的？

### BeanDefinition 的继承体系

```
BeanDefinition（顶层接口）
    │
    ├── RootBeanDefinition          （Spring 内部使用，不可有父 Bean）
    ├── ChildBeanDefinition         （已废弃，需要有父 Bean）
    ├── GenericBeanDefinition      （替代品，可有父 Bean）
    │
    └── AnnotatedBeanDefinition（注解驱动的 BeanDefinition）
        ├── ScannedGenericBeanDefinition   （@Component 扫描）
        ├── ConfigurationClassBeanDefinition（@Bean 方法）
        └── InnerBeanDefinition             （内部类 Bean）
```

**核心属性**（每个 BeanDefinition 都有）：

```java
public interface BeanDefinition {
    // 类名（Bean 的 Class）
    String getBeanClassName();

    // 作用域（singleton / prototype / request / session）
    String getScope();

    // 是否懒加载
    boolean isLazyInit();

    // 依赖的 Bean（depends-on）
    String[] getDependsOn();

    // 工厂方法名（@Bean 对应的方法名）
    String getFactoryMethodName();

    // 构造器参数
    ConstructorArgumentValues getConstructorArgumentValues();

    // 属性值（<property> 或 @Value）
    MutablePropertyValues getPropertyValues();
}
```

---

### BeanDefinition 的加载路径

**路径一：XML 配置 → `XmlBeanDefinitionReader`**

```java
// 1. 创建 Reader
XmlBeanDefinitionReader reader = new XmlBeanDefinitionReader(registry);

// 2. 加载 XML 文件 → 解析 → 注册 BeanDefinition
reader.loadBeanDefinitions("classpath:spring.xml");

// 3. 解析过程（简化）
//     → 读取 <bean> 标签
//     → 提取 class、scope、lazy-init 等属性
//     → 创建 GenericBeanDefinition
//     → 注册到 registry
```

**路径二：注解配置 → `AnnotatedBeanDefinitionReader`**

```java
// 处理 @Configuration 类中的 @Bean 方法
AnnotatedBeanDefinitionReader reader = new AnnotatedBeanDefinitionReader(registry);

// 注册配置类
reader.register(AppConfig.class);
// → 读取 @Bean 注解
// → 创建 ConfigurationClassBeanDefinition
// → 注册到 registry
```

**路径三：组件扫描 → `ClassPathBeanDefinitionScanner`**

```java
// 扫描 @Component（包括 @Service、@Repository、@Controller）
ClassPathBeanDefinitionScanner scanner =
    new ClassPathBeanDefinitionScanner(registry);

// 扫描指定包
scanner.scan("com.example.service");
// → 找到所有 @Component 类
// → 创建 ScannedGenericBeanDefinition
// → 注册到 registry
```

---

### BeanDefinition 注册（BeanDefinitionRegistry）

**问题**：解析出来的 BeanDefinition 放在哪里？

**答案**：`BeanDefinitionRegistry`（BeanDefinition 注册表）。

```java
// DefaultListableBeanFactory 实现了 BeanDefinitionRegistry
public class DefaultListableBeanFactory
    extends DefaultSingletonBeanRegistry
    implements BeanDefinitionRegistry, ConfigurableListableBeanFactory {

    // BeanDefinition 注册表（核心数据结构）
    private final Map<String, BeanDefinition> beanDefinitionMap = new ConcurrentHashMap<>(256);

    @Override
    public void registerBeanDefinition(String beanName, BeanDefinition bd) {
        // 1. 校验 BeanDefinition（是否有类、是否单例等）
        validateBeanDefinition(bd);

        // 2. 放入注册表
        beanDefinitionMap.put(beanName, bd);

        // 3. 清空合并 BeanDefinition 缓存（如果有）
        clearMergedBeanDefinition(beanName);
    }
}
```

> **所有 BeanDefinition 都注册到 `DefaultListableBeanFactory.beanDefinitionMap`**，  
> `getBean()` 时从这里取定义，然后创建 Bean。

---

### BeanDefinition 合并（父子合并）

**问题**：`<bean id="parent" abstract="true">` 定义了公共属性，`<bean id="child" parent="parent">` 继承它。怎么合并？

```xml
<bean id="parent" abstract="true" scope="prototype">
    <property name="name" value="default"/>
</bean>

<bean id="child" parent="parent">
    <property name="age" value="20"/>
</bean>
```

**合并流程**：

```java
// AbstractBeanFactory.getMergedLocalBeanDefinition()
protected RootBeanDefinition getMergedLocalBeanDefinition(String beanName) {
    // 1. 先查缓存（merged BeanDefinition 缓存）
    RootBeanDefinition mbd = mergedBeanDefinitions.get(beanName);
    if (mbd != null) return mbd;

    // 2. 从注册表取原始 BeanDefinition
    BeanDefinition bd = getBeanDefinition(beanName);

    // 3. 如果有父 Bean，递归合并
    if (bd instanceof GenericBeanDefinition && bd.getParentName() != null) {
        String parentName = bd.getParentName();
        BeanDefinition pbd = getMergedBeanDefinition(parentName);  // 递归
        mbd = new RootBeanDefinition(pbd);  // 以父为模板
        mbd.overrideFrom(bd);              // 子覆盖父
    } else {
        mbd = new RootBeanDefinition(bd);   // 没有父，直接复制
    }

    // 4. 放入缓存
    mergedBeanDefinitions.put(beanName, mbd);
    return mbd;
}
```

> **合并后的 BeanDefinition 是 `RootBeanDefinition`**（不可再有父 Bean）。  
> 合并是**递归的**：如果父 Bean 还有父 Bean，继续往上合并。

---

## 它和相似方案的本质区别是什么？

### BeanDefinition vs 直接反射创建

| | 有 BeanDefinition | 直接反射 |
|---|------------------|-----------|
| 提前校验 | ✅（注册时就校验） | ❌（创建时才报错） |
| 动态修改 | ✅（BeanFactoryPostProcessor 可以改） | ❌ |
| 延迟创建 | ✅（lazy-init） | ❌ |
| 作用域控制 | ✅（scope） | ❌ |

**BeanDefinition 的核心价值**：**把「Bean 的元数据」和「Bean 的实例」分离**，让 Spring 有机会在创建之前做各种处理。

---

## 正确使用方式

### 1. 用 BeanFactoryPostProcessor 修改 BeanDefinition

```java
@Component
public class MyBeanFactoryPostProcessor implements BeanFactoryPostProcessor {

    @Override
    public void postProcessBeanFactory(ConfigurableListableBeanFactory beanFactory) {
        // 1. 获取 BeanDefinition
        BeanDefinition bd = beanFactory.getBeanDefinition("userService");

        // 2. 修改属性（把 userService 的 scope 改成 prototype）
        bd.setScope(ConfigurableBeanFactory.SCOPE_PROTOTYPE);

        // 3. 添加属性
        bd.getPropertyValues().add("name", "newName");
    }
}
```

> **这是 Spring Boot 自动配置的核心机制**！  
> `ConfigurationClassPostProcessor`（一个 `BeanFactoryPostProcessor`）扫描所有 `@Configuration` 类，把 `@Bean` 方法注册成 `BeanDefinition`。

---

### 2. 用 GenericBeanDefinition 动态注册 Bean

```java
@Autowired
private BeanDefinitionRegistry registry;

public void registerBean() {
    GenericBeanDefinition bd = new GenericBeanDefinition();
    bd.setBeanClass(UserService.class);
    bd.setScope(ConfigurableBeanFactory.SCOPE_SINGLETON);
    bd.setLazyInit(false);

    // 注册到容器
    registry.registerBeanDefinition("userService", bd);
}
```

---

## 边界情况和坑

### 1. BeanDefinition 覆盖（同名 Bean）

```java
// ❌ 默认不允许覆盖（Spring Boot 2.1+ 默认禁止）
@Bean
public UserService userService() {
    return new UserService();
}

@Bean
public UserService userService() {  // 同名 Bean → 启动报错
    return new UserServiceV2();
}
```

**解决**：允许覆盖（不推荐）

```yaml
spring:
  main:
    allow-bean-definition-overriding: true  # 允许同名 Bean 覆盖
```

> **同名 Bean 覆盖是危险的**：不知道哪个 Bean 会生效，容易产生诡异 bug。  
> 推荐：用 `@Primary` 或 `@Qualifier` 解决冲突。

---

### 2. BeanDefinition 中的类找不到

```java
// 配置文件写了不存在的类
<bean class="com.example.NonExistClass"/>  // ❌ 启动时（或首次 getBean 时）报错
```

> **Spring 的行为**：  
> - 如果 `default-lazy-init="true"`（懒加载），启动时**不报错**，首次 `getBean()` 才抛 `ClassNotFoundException`。  
> - 默认（非懒加载），启动时就会校验，**报错更早**。

---

### 3. FactoryBean 的 BeanDefinition 特殊行为

```java
// FactoryBean 的 BeanDefinition：
//   - getBean("myFactoryBean")  → 返回 FactoryBean.getObject() 的结果
//   - getBean("&myFactoryBean") → 返回 FactoryBean 本身

@Component
public class MyFactoryBean implements FactoryBean<User> {
    @Override
    public User getObject() {
        return new User("from-factory");  // 实际返回的 Bean
    }
}
```

> `FactoryBean` 是一种**特殊 Bean**：它的 `BeanDefinition` 描述的是 FactoryBean 本身，  
> 但 `getBean()` 返回的是 `getObject()` 的返回值。

---

