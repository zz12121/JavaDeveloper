# MyBatis-Spring 整合原理

> ⚠️ **先盲答**：MyBatis 的 Mapper 接口没有实现类，是谁帮我们创建了对象？SqlSession 是谁管理的？

---

## 盲答引导

1. Mapper 接口为什么不需要写实现类？
2. SqlSessionFactoryBean 在整合中扮演什么角色？
3. MapperScannerConfigurer 是做什么的？
4. Spring 事务整合 MyBatis 时，SqlSession 是如何管理的？
5. Mapper 代理对象的生命周期？

---

## 知识链提示

```
MyBatis-Spring 整合
  → [[05_持久层框架/01_MyBatis/00_概览]] + [[05_持久层框架/01_MyBatis/08_事务管理]]
    → 1. SqlSessionFactoryBean（工厂 Bean）
      → 实现 FactoryBean<SqlSessionFactory>
        → getObject() 返回 SqlSessionFactory
      → 负责解析 mybatis-config.xml（或注解配置）
      → 构建 Configuration 对象 → 创建 SqlSessionFactory
      → 关键属性：dataSource / mapperLocations / typeAliasesPackage
    → 2. MapperScannerConfigurer（扫描器）
      → 实现 BeanDefinitionRegistryPostProcessor
        → 在容器启动早期，扫描指定包下的 Mapper 接口
        → 为每个 Mapper 接口注册一个 BeanDefinition
        → BeanClass 设置为 MapperFactoryBean（不是接口本身！）
      → 扫描过滤：@Mapper 注解 / markerInterface / basePackage
    → 3. MapperFactoryBean（每个 Mapper 的工厂）
      → 实现 FactoryBean<T>
        → getObject() → sqlSession.getMapper(Mapper.class)
      → 实际返回的是 JDK 动态代理对象（MapperProxy）
    → 4. MapperProxy（JDK 动态代理核心）
      → 实现 InvocationHandler
        → invoke() 方法拦截接口方法调用
        → 根据方法签名（接口名 + 方法名）找到对应的 MappedStatement
        → 通过 SqlSession 执行 SQL（selectOne/selectList/insert/update/delete）
      → MapperProxy.invoke() 核心流程
        → 判断是否是 Object 的方法（toString/hashCode等）→ 直接执行
        → 判断是否是 default 方法（Java 8+）→ 直接调用
        → 否则：获取 MapperMethod → 执行 SQL
    → 5. SqlSession 管理（Spring 事务整合关键）
      → Spring 整合后，不直接使用原生 SqlSession
      → 使用 SqlSessionTemplate（线程安全，代理了 DefaultSqlSession）
        → 每次操作从 TransactionSynchronizationManager 获取当前线程绑定的 SqlSession
        → 如果当前有 Spring 事务，复用同一个 SqlSession
        → 如果没有事务，每次操作新开一个 SqlSession（操作完关闭）
      → 事务整合原理
        → MyBatis-Spring 提供了 SpringManagedTransactionFactory
        → 将 JDBC Connection 交给 Spring 事务管理器管理
        → @Transactional 注解控制事务的提交/回滚
    → 6. 整合配置（Java Config 方式）
      → @MapperScan("com.xxx.mapper") 替代 MapperScannerConfigurer
      → @Bean SqlSessionFactoryBean → 设置 DataSource / MapperLocations
      → @Bean DataSourceTransactionManager → 事务管理器
```

---

## 核心追问

| 追问 | 考点 |
|------|------|
| 为什么 Mapper 接口不能被直接实例化？ | 接口没有构造方法，无法直接 new；必须通过代理生成实现类 |
| SqlSessionTemplate 为什么是线程安全的？ | 内部每次操作都从 ThreadLocal 获取当前 SqlSession（或新建），每个线程独立 |
| Spring 整合后，一级缓存还生效吗？ | 生效，但只在同一个 SqlSession 内；Spring 管理下，无事务时每次 SqlSession 不同，一级缓存失效 |
| MapperScannerConfigurer 和 @MapperScan 的关系？ | @MapperScan 是 Spring Boot 提供的注解，底层就是注册 MapperScannerConfigurer |
| 多个 Mapper 共用一个 SqlSessionFactory 吗？ | 是，通常一个数据源对应一个 SqlSessionFactory |

---

## 参考答案要点

**代理链**：Mapper 接口 → MapperFactoryBean.getObject() → sqlSession.getMapper() → JDK 动态代理（MapperProxy）→ invoke() 执行 SQL。

**SqlSession 生命周期**：Spring 管理下，SqlSessionTemplate 代理了操作，保证事务内复用同一 SqlSession，无事务时每次新建。

**事务整合**：MyBatis 的 JDBC Connection 交给 Spring 的 DataSourceTransactionManager 管理，@Transactional 控制提交/回滚。

**@MapperScan 本质**：底层注册 MapperScannerConfigurer，扫描指定包，为每个 Mapper 接口注册 MapperFactoryBean。

---

## 下一步

打开 [[05_持久层框架/01_MyBatis/00_概览]]，补充 `双向链接`：「MyBatis-Spring 整合的本质是：Mapper 接口 → 动态代理 → Spring 管理 SqlSession 生命周期 → 事务统一由 Spring 控制」。
