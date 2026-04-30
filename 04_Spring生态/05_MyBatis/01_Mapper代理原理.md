# Mapper 代理原理

## 这个问题为什么存在？

> 你定义了一个 `UserMapper` 接口，里面只有方法签名，没有实现类。但你可以直接调用 `userMapper.selectById(1)` —— 是谁帮你实现了这个方法？

传统 JDBC：`Statement stmt = conn.createStatement(); ResultSet rs = stmt.executeQuery("select ...")` —— 全要手写。

MyBatis 承诺：你只写接口 + SQL（XML 或注解），剩下的它搞定。这背后的原理就是 **Mapper 代理**。

---

## 它是怎么解决问题的？

### 核心机制

```
你写的代码
  UserMapper mapper = sqlSession.getMapper(UserMapper.class);
  User user = mapper.selectById(1);

背后发生了什么？
  → sqlSession.getMapper() 调用 Configuration.getMapper()
  → MapperRegistry.getMapper() → MapperProxyFactory.newInstance()
  → JDK 动态代理：Proxy.newProxyInstance()
  → 生成代理对象（实现了 UserMapper 接口）
  → 代理对象的 invoke() 方法 → MapperProxy.invoke()
  → 根据方法签名找到对应的 MappedStatement（SQL 定义）
  → 通过 SqlSession 执行对应的 SQL
```

**关键类**：
- `MapperProxyFactory`：为每个 Mapper 接口创建代理工厂
- `MapperProxy`：实现 `InvocationHandler`，代理逻辑的核心
- `MapperMethod`：封装方法调用，决定是执行 `selectOne`/`selectList`/`insert` 等

### 源码关键路径

```java
// MapperProxyFactory.java
public T newInstance(SqlSession sqlSession) {
    MapperProxy<T> mapperProxy = new MapperProxy<>(sqlSession, mapperInterface, methodCache);
    return Proxy.newProxyInstance(
        mapperInterface.getClassLoader(),
        new Class[]{mapperInterface},
        mapperProxy   // ← 所有方法调用都进这里
    );
}

// MapperProxy.java
@Override
public Object invoke(Object proxy, Method method, Object[] args) {
    // 1. 如果是 Object 的方法（toString/hashCode等），直接反射调用
    if (Object.class.equals(method.getDeclaringClass())) {
        return method.invoke(this, args);
    }
    // 2. 获取/缓存 MapperMethod
    MapperMethod mapperMethod = cachedMapperMethod(method);
    // 3. 执行 SQL
    return mapperMethod.execute(sqlSession, args);
}

// MapperMethod.java
public Object execute(SqlSession sqlSession, Object[] args) {
    switch (command.getType()) {   // ← 根据 SQL 类型分发
        case SELECT:
            if (returnsMany) return sqlSession.selectList(...);
            else return sqlSession.selectOne(...);
        case INSERT: return sqlSession.insert(...);
        case UPDATE: return sqlSession.update(...);
        case DELETE: return sqlSession.delete(...);
    }
}
```

**为什么用 JDK 动态代理而不是 CGLIB？**
因为 Mapper 是接口，JDK 动态代理天生适合代理接口；CGLIB 是基于继承的，接口没法继承。

---

## 它和相似方案的本质区别是什么？

| 方案 | 代理方式 | SQL 控制 | 学习曲线 |
|------|---------|---------|---------|
| **MyBatis Mapper** | JDK 动态代理 | 开发者写 SQL（注解/XML） | 低 |
| **Spring Data JPA** | JDK 动态代理 + 方法名解析 | 按方法名自动生成 SQL | 中 |
| **Hibernate（Session）** | CGLIB 代理实体类 | HQL/Criteria API | 高 |
| **直接写 JDBC** | 无代理 | 全手写 | 低（但代码量大） |

**本质区别**：MyBatis 的代理只做「方法 → SQL 语句的路由」，不做「对象关系映射」的全部工作（那是 Hibernate 的事）。这是半自动化 ORM 的精髓。

---

## 正确使用方式

### 定义 Mapper 接口
```java
public interface UserMapper {
    // XML 方式：需要有 UserMapper.xml 中的 <select id="selectById">
    User selectById(Integer id);

    // 注解方式：不需要 XML
    @Select("SELECT * FROM user WHERE id = #{id}")
    User selectByIdAnnotation(Integer id);

    // 返回 List
    List<User> selectByAge(@Param("age") Integer age);

    // 返回 Map（列名 → 值）
    @MapKey("id")
    Map<Integer, User> selectAsMap();
}
```

### 获取 Mapper
```java
// 方式一：传统方式
SqlSession sqlSession = sqlSessionFactory.openSession();
UserMapper mapper = sqlSession.getMapper(UserMapper.class);

// 方式二：Spring 整合后（推荐）
@Autowired
private UserMapper userMapper;   // ← 注入的是 MapperProxy 代理对象
```

### XML 映射文件对应规则
```
接口全限定名：com.example.mapper.UserMapper
XML namespace：com.example.mapper.UserMapper   ← 必须一致
方法名：selectById
XML id：selectById   ← 必须一致
```

---

## 边界情况和坑

### 坑1：方法重载导致绑定失败
```java
// ❌ 错误：MyBatis 不支持方法重载（XML id 唯一，无法区分）
User selectById(Integer id);
User selectById(String id);

// 因为 XML 中 id 是唯一的，JVM 方法签名（名称+参数类型）MyBatis 不区分
```

### 坑2：接口有多个方法名相同（不同参数），XML 只有一个 id
```
原因：MyBatis 通过「接口全限定名 + 方法名」定位 SQL，不考虑参数类型
解决：方法名不能重复，或者改用注解方式
```

### 坑3：Spring 整合后，Mapper 是单例吗？
```
是单例（Spring 容器中只有一个 MapperProxy 实例）
但 MapperProxy 是无状态的，内部通过 SqlSessionTemplate 获取线程绑定的 SqlSession
→ 线程安全 ✅
```

### 坑4：代理对象 toString() 会触发 SQL 吗？
```
不会。Object 的方法（toString/hashCode/equals）直接在 MapperProxy.invoke() 中判断并放行，
不会走 SQL 执行逻辑。
```

---

## Mapper 代理完整调用链（ASCII 图）

```
用户调用：userMapper.selectById(1)
    ↓
MapperProxy.invoke()          ← JDK 动态代理入口
    ↓
MapperMethod.execute()
    ↓ 根据 SqlCommandType 分发
    ↓
SqlSession.selectOne()
    ↓
Executor.query()              ← 执行器（BaseExecutor → SimpleExecutor）
    ↓
PreparedStatementHandler.query()
    ↓
ResultSetHandler.handleResultSets()  ← 结果集映射
    ↓
返回 Java 对象
```

---

## 我的理解

Mapper 代理的本质是 **JDK 动态代理 + 方法名到 SQL 的映射**。

- `Proxy.newProxyInstance()` 生成代理对象
- 所有方法调用进入 `MapperProxy.invoke()`
- 通过「接口全限定名 + 方法名」在 `MappedStatement` 中找到对应的 SQL
- 调用 `SqlSession` 的方法执行 SQL，再映射结果

**为什么 MyBatis 比 JPA 灵活？** 因为 SQL 是开发者控制的，复杂查询、多表关联、数据库特定语法都能写；JPA 自动生成 SQL，复杂场景很难优化。

**为什么用接口而不是抽象类？** 因为 JDK 动态代理要求必须是接口；如果用 CGLIB 就可以用类，但 MyBatis 选择 JDK 代理（更轻量，且无第三方依赖）。
