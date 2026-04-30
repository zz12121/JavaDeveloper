# Spring设计模式

## 这个问题为什么存在？

>Spring 不是一堆随机拼凑的功能，而是**23 种设计模式的大型实景教学**。理解 Spring 为什么用这些模式，比背设计模式定义更有价值。

**为什么要在框架里用设计模式？**

框架要解决的问题本质：**如何让通用流程稳定、让扩展点灵活**。设计模式就是这个问题的标准答案。

---

## 它是怎么解决问题的？

### 1. 工厂模式 —— BeanFactory

**问题**：框架需要创建对象，但不应该 `new` 具体类（耦合）。

**Spring 的解法**：`BeanFactory` 是**抽象的工厂**，只定义「怎么拿 Bean」，具体创建逻辑推迟到子类。

```java
// 工厂模式的体现
public interface BeanFactory {
    Object getBean(String name) throws BeansException;
    <T> T getBean(Class<T> requiredType) throws BeansException;
}

// 具体工厂：DefaultListableBeanFactory
// 它知道怎么根据 BeanDefinition 创建 Bean
```

**为什么是工厂模式，不是直接 new？**

```
不用工厂：
  OrderService orderService = new OrderService();  // 硬编码，无法扩展

用工厂：
  OrderService orderService = ctx.getBean(OrderService.class);
  // 实际返回的可能是一个代理对象（AOP），调用方完全无感
```

> 工厂模式的核心是**把「创建逻辑」和「使用逻辑」分离**。Spring 把这一点发挥到极致：getBean() 返回的可能不是你要的类，而是一个代理。

---

### 2. 单例模式 —— Bean 的默认作用域

**问题**：某些对象（如 Service、Dao）只需要一个实例，重复创建浪费资源。

**Spring 的单例实现**（不是经典饿汉/懒汉）：

```java
// DefaultSingletonBeanRegistry
private final Map<String, Object> singletonObjects = new ConcurrentHashMap<>();

protected Object getSingleton(String beanName) {
    Object singletonObject = singletonObjects.get(beanName);
    if (singletonObject == null) {
        // 加锁创建（双检锁）
        synchronized (singletonObjects) {
            singletonObject = singletonObjects.get(beanName);
            if (singletonObject == null) {
                singletonObject = createBean(beanName);
                singletonObjects.put(beanName, singletonObject);
            }
        }
    }
    return singletonObject;
}
```

**和经典单例的区别**：

| | 经典单例 | Spring 单例 |
|--|-----------|--------------|
| 控制方 | 类自己控制 | 容器控制 |
| 范围 | JVM 级 | 容器级（一个 Spring 容器一个实例） |
| 实现 | 私有构造器 | 容器缓存 |

> Spring 的单例是**容器级单例**，不是 ClassLoader 级。两个容器各有一个实例。

---

### 3. 代理模式 —— AOP 的核心

**问题**：要在方法前后加逻辑（事务、日志），但不能改源码。

**Spring 的解法**：代理模式，用一个「代理对象」包裹真实对象，调用方无感。

```
调用方 → 代理对象.方法()
                ↓
          前置逻辑（事务开启）
                ↓
          真实对象.方法()
                ↓
          后置逻辑（事务提交）
```

**JDK 动态代理**（基于接口）：

```java
// 代理类实现了目标接口
public class $Proxy0 implements UserService {
    InvocationHandler h;
    public void save(User u) {
        h.invoke(this, saveMethod, new Object[]{u});
    }
}
```

**CGLIB**（基于继承）：

```java
// 代理类继承了目标类
public class UserService$$EnhancerByCGLIB extends UserService {
    MethodInterceptor interceptor;
    public void save(User u) {
        interceptor.intercept(this, saveMethod, new Object[]{u}, methodProxy);
    }
}
```

> 代理模式的本质是「**控制访问**」，不是「增强功能」。Spring AOP 只是借用了代理的「控制访问」能力来插入增强逻辑。

---

### 4. 模板方法模式 —— JdbcTemplate

**问题**：JDBC 操作流程固定（获取连接 → 创建 Statement → 执行 → 关闭资源），但具体 SQL 和结果处理不同。

**Spring 的解法**：模板方法模式，把**固定流程**写在父类，把**可变部分**留给子类（回调）。

```java
// 固定流程在父类（JdbcTemplate）
public <T> T execute(PreparedStatementCreator psc, PreparedStatementCallback<T> action) {
    Connection con = DataSourceUtils.getConnection(dataSource);  // 固定
    PreparedStatement ps = psc.createPreparedStatement(con);      // 可变
    T result = action.doInPreparedStatement(ps);                 // 可变
    ps.close();                                                  // 固定
    return result;
}

// 使用：可变部分用回调传入
jdbcTemplate.update(
    con -> con.prepareStatement("INSERT ..."),  // 创建 Statement（可变）
    ps -> { ps.executeUpdate(); return null; }  // 执行（可变）
);
```

**为什么不用工厂模式？**

工厂模式解决「创建」问题，模板方法解决「**算法步骤**」问题。JDBC 操作是**有固定步骤的算法**，适合模板方法。

---

### 5. 观察者模式 —— Spring 事件机制

**问题**：一个操作完成后，需要触发多个后续动作（如用户注册后发邮件、发优惠券），但不能硬编码依赖。

**Spring 的解法**：观察者模式，事件发布-订阅。

```java
// 1. 定义事件
public class UserRegisteredEvent extends ApplicationEvent {
    private final User user;
    public UserRegisteredEvent(Object source, User user) {
        super(source);
        this.user = user;
    }
}

// 2. 发布事件
@Autowired ApplicationEventPublisher publisher;
publisher.publishEvent(new UserRegisteredEvent(this, user));

// 3. 监听事件（多个监听器，解耦）
@EventListener
public void sendEmail(UserRegisteredEvent event) { ... }

@EventListener
public void sendCoupon(UserRegisteredEvent event) { ... }
```

**解耦效果**：

```
不用观察者：
  register() {
      userService.save();
      emailService.send();    // 硬编码依赖
      couponService.send();    // 新增需求要改代码
  }

用观察者：
  register() {
      userService.save();
      publisher.publishEvent(event);  // 只管发布，不管谁处理
  }
  // 新增监听者：加一个 @EventListener 方法，不用改 register()
```

---

### 6. 适配器模式 —— HandlerAdapter

**问题**：Spring MVC 的 Handler（处理器）有多种形式（`@RequestMapping` 方法、Controller 接口、`HttpRequestHandler`...），DispatcherServlet 不可能用 `if-else` 判断类型再调用。

**Spring 的解法**：适配器模式，统一调用接口。

```java
// 适配器接口（统一调用）
public interface HandlerAdapter {
    boolean supports(Object handler);  // 是否支持这个 handler
    ModelAndView handle(HttpServletRequest request,
                       HttpServletResponse response,
                       Object handler) throws Exception;
}

// 具体适配器（每种 Handler 一个适配器）
SimpleServletHandlerAdapter   → 适配 Servlet
SimpleControllerHandlerAdapter → 适配 Controller 接口
RequestMappingHandlerAdapter  → 适配 @RequestMapping 方法

// DispatcherServlet 中的调用
HandlerAdapter adapter = getHandlerAdapter(handler);
adapter.handle(request, response, handler);  // 统一调用
```

> 适配器模式的核心是「**接口转换**」。Spring MVC 用它将各种异构的 Handler 统一成相同的调用方式。

---

### 7. 策略模式 —— Resource 接口

**问题**：Spring 需要加载资源（classpath 文件、URL、文件系统文件...），但不同来源的资源加载方式完全不同。

**Spring 的解法**：策略模式，定义统一接口，每种资源一种实现。

```java
// 策略接口
public interface Resource {
    InputStream getInputStream() throws IOException;
    boolean exists();
    boolean isOpen();
}

// 具体策略
ClassPathResource   → 从 classpath 加载
FileSystemResource  → 从文件系统加载
UrlResource         → 从 URL 加载
ByteArrayResource   → 从字节数组加载

// 使用：面向接口编程，不用关心具体来源
Resource res = new ClassPathResource("config.xml");
InputStream is = res.getInputStream();  // 统一接口
```

**和工厂模式的区别**：

| | 工厂模式 | 策略模式 |
|--|-----------|-----------|
| 关注点 | 对象创建 | 算法/行为选择 |
| 调用时机 | 创建时决定 | 运行时可切换 |
| Spring 例子 | BeanFactory | Resource（用策略）+ ResourceLoader（用工厂） |

> 实际上 Spring 经常**组合使用**：ResourceLoader（工厂）根据地址前缀选择 Resource（策略）。

---

### 8. 装饰器模式 —— BeanWrapper

**问题**：需要对一个对象的功能进行**动态扩展**（不是静态继承），且不改变其接口。

**Spring 的解法**：装饰器模式，在 `BeanWrapper` 中对 Bean 进行包装，增加类型转换、属性访问等能力。

```java
// BeanWrapper 装饰了原始的 Bean 对象
Object bean = new User();
BeanWrapper bw = new BeanWrapperImpl(bean);

// 装饰后新增的能力：
bw.setPropertyValue("name", "张三");  // 属性访问
bw.convertIfNecessary(value, targetType);  // 类型转换
```

**装饰器 vs 代理**：

| | 装饰器 | 代理 |
|--|---------|------|
| 目的 | 增强功能 | 控制访问 |
| 持有对象 | 构造器传入（多个装饰器可叠加） | 内部创建或传入 |
| Spring 例子 | BeanWrapper | AOP 代理 |

---

## 它和相似方案的本质区别是什么？

### 模板方法 vs 策略模式

这两个最容易混淆，Spring 里都有。

| | 模板方法 | 策略模式 |
|--|-----------|-----------|
| 控制结构 | 继承（父类控制流程） | 组合（持有策略对象） |
| 扩展方式 | 子类覆盖步骤方法 | 替换策略对象 |
| 步骤是否固定 | 是（算法骨架固定） | 否（整个算法可替换） |
| Spring 例子 | JdbcTemplate | Resource 加载策略 |

```java
// 模板方法：流程固定在父类，子类实现具体步骤
JdbcTemplate.execute(() -> con.prepareStatement("..."),
                    ps -> { ps.execute(); return null; });

// 策略模式：整个算法可替换
ResourceLoader loader = new DefaultResourceLoader();
Resource res = loader.getResource("classpath:config.xml");  // 策略被替换
```

---

## 正确使用方式

### 1. 自定义 BeanPostProcessor（装饰器模式的应用）

```java
// 对所有 Bean 进行装饰/增强
@Component
public class MyBeanPostProcessor implements BeanPostProcessor {
    @Override
    public Object postProcessAfterInitialization(Object bean, String beanName) {
        if (bean instanceof UserService) {
            return Proxy.newProxyInstance(...);  // 返回装饰后的对象
        }
        return bean;  // 不需要增强，原样返回
    }
}
```

### 2. 自定义事件监听器（观察者模式的应用）

```java
// 异步监听（解耦 + 异步执行）
@EventListener
@Async
public void handleUserRegistered(UserRegisteredEvent event) {
    emailService.send(event.getUser());
}
```

### 3. 自定义 Scope（工厂模式扩展）

```java
// 实现自定义作用域（如「每次调用都新建」）
public class ThreadScope implements Scope {
    private final ThreadLocal<Map<String, Object>> threadLocal = ...;

    @Override
    public Object get(String name, ObjectFactory<?> objectFactory) {
        Map<String, Object> scope = threadLocal.get();
        return scope.computeIfAbsent(name, k -> objectFactory.getObject());
    }
}
```

---

## 边界情况和坑

### 1. 单例 Bean 中的可变状态（线程安全）

```java
@Service
public class UserService {
    private int count = 0;  // ❌ 单例 Bean 的成员变量，多线程共享！

    public void increment() {
        count++;  // 线程不安全
    }
}
```

> Spring 的单例只是「容器只创建一个实例」，**不保证线程安全**。  
> 单例 Bean 应该是**无状态**的（或者只持有线程安全的对象，如 DAO）。

---

### 2. 观察者模式的事件处理异常

```java
@EventListener
public void handleEvent(MyEvent event) {
    throw new RuntimeException("处理失败");
    // 默认：异常会传播到发布者，导致 publisher.publishEvent() 抛异常
}
```

**解决**：用 `@Async` + 异步事件，异常不会传播到发布者。或者捕获异常。

---

### 3. 模板方法中的资源管理

```java
// JdbcTemplate 保证资源关闭，但自定义模板方法时要注意
public <T> T executeWithResource(ResourceCallback<T> callback) {
    Resource res = acquireResource();  // 获取资源
    try {
        return callback.doInResource(res);
    } finally {
        res.close();  // ⚠️ 必须在 finally 中关闭
    }
}
```

---

## 我的理解

Spring 是设计模式的「实战教科书」，每个模式的选择都有其深层原因：

1. **工厂模式** → 解耦创建和使用，支持 AOP 代理
2. **单例模式** → 容器级单例，节省资源
3. **代理模式** → AOP 的基础，控制访问
4. **模板方法** → 固定流程 + 可变步骤（JdbcTemplate）
5. **观察者模式** → 事件驱动，解耦组件
6. **适配器模式** → 统一异构接口（HandlerAdapter）
7. **策略模式** → 算法可替换（Resource）
8. **装饰器模式** → 动态增强功能（BeanWrapper）

**面试追问高发区**：
1. Spring 用到了哪些设计模式？各举一例
2. 工厂模式和单例模式在 Spring 中的体现
3. 模板方法 vs 策略模式的区别
4. 观察者模式在 Spring 事件机制中的应用

---
