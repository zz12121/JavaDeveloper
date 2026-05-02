# MyBatis-Plus 实战与面试

## 这个问题为什么存在？

> 掌握核心原理之后，如何在真实项目中用好 MP？

MP 的功能很丰富，但「能用」和「用得好」是两回事。这篇文章讲实战中最重要的选择判断和避坑经验。

---

## 一、Spring Boot 整合实战

### 1.1 完整配置

```yaml
# application.yml
mybatis-plus:
  # Mapper XML 文件位置
  mapper-locations: classpath*:/mapper/**/*.xml
  # 实体类包扫描
  type-aliases-package: com.example.entity
  configuration:
    # 开启驼峰转下划线（默认 true）
    map-underscore-to-camel-case: true
    # 控制台打印 SQL（开发环境用，生产关掉！）
    log-impl: org.apache.ibatis.logging.stdout.StdOutImpl
  global-config:
    db-config:
      # 逻辑删除配置
      logic-delete-field: deleted
      logic-delete-value: 1
      logic-not-delete-value: 0
      # 表名前缀（自动去掉）
      table-prefix: sys_
      # 主键策略（全局）
      id-type: ASSIGN_ID
```

### 1.2 MapperScan 配置

```java
// 方式1：在启动类上加 @MapperScan
@SpringBootApplication
@MapperScan("com.example.mapper")   // 扫描 Mapper 接口
public class Application {
    public static void main(String[] args) {
        SpringApplication.run(Application.class, args);
    }
}

// 方式2：每个 Mapper 上加 @Mapper（不推荐，太麻烦）
@Mapper
public interface UserMapper extends BaseMapper<User> {}
```

**为什么推荐 @MapperScan？**
- 一个注解搞定所有 Mapper 扫描
- 不需要在每个 Mapper 上加 @Mapper 注解
- 可以控制扫描的包路径（避免扫描到无关的 Mapper）

---

## 二、多表联查方案

### 2.1 方案对比

| 方案 | 适用场景 | 优点 | 缺点 |
|------|----------|------|------|
| **XML 手写 SQL** | 复杂联查、多表 JOIN | 灵活、熟悉、可控 | 需要维护 XML |
| **Wrapper 多表** | 简单联查 | 不用写 SQL | 复杂时很难写 |
| **VO + @Select** | 查询指定字段 | 简洁、无 XML | 复杂 SQL 不好写 |
| **关联查询自动映射** | 一对多/多对一 | 面向对象风格 | N+1 问题 |

### 2.2 XML 手写 SQL（最常用）

```xml
<!-- UserMapper.xml -->
<mapper namespace="com.example.mapper.UserMapper">

    <!-- 联查（有对应 VO） -->
    <select id="selectUserWithRole" resultType="UserRoleVO">
        SELECT u.id, u.name, u.age, r.role_name
        FROM sys_user u
        LEFT JOIN sys_user_role ur ON u.id = ur.user_id
        LEFT JOIN sys_role r ON ur.role_id = r.id
        WHERE u.deleted = 0
          AND u.id = #{userId}
    </select>

    <!-- 分页联查 -->
    <select id="selectUserPage" resultType="UserVO">
        SELECT u.*, d.dept_name
        FROM sys_user u
        LEFT JOIN sys_dept d ON u.dept_id = d.id
        WHERE u.deleted = 0
        <if test="keyword != null and keyword != ''">
            AND (u.name LIKE CONCAT('%', #{keyword}, '%')
                 OR u.email LIKE CONCAT('%', #{keyword}, '%'))
        </if>
        ORDER BY u.create_time DESC
        <!-- 不需要写 LIMIT，分页插件自动加 -->
    </select>
</mapper>
```

```java
// Mapper 接口中声明（BaseMapper 没有的方法）
public interface UserMapper extends BaseMapper<User> {

    // 自定义方法 → 需要在 XML 中写对应 SQL
    UserRoleVO selectUserWithRole(@Param("userId") Long userId);

    // 分页：参数只要传 Page<T>，MP 分页插件自动拦截
    Page<UserVO> selectUserPage(Page<UserVO> page, @Param("keyword") String keyword);
}
```

### 2.3 @Select 注解（轻量联查）

```java
public interface UserMapper extends BaseMapper<User> {

    @Select("""
        SELECT u.id, u.name, r.role_name
        FROM sys_user u
        LEFT JOIN sys_user_role ur ON u.id = ur.user_id
        LEFT JOIN sys_role r ON ur.role_id = r.id
        WHERE u.id = #{userId}
    """)
    UserRoleVO selectUserWithRole(@Param("userId") Long userId);
}
```

**什么时候用 XML，什么时候用注解？**
```
- 简单查询（<5 行 SQL）→ 用 @Select 注解
- 复杂查询（多表 JOIN、动态 SQL）→ 必须用 XML
- 动态 SQL（<if> / <where> / <foreach>）→ 必须用 XML
- 需要代码审查 SQL → 推荐 XML（集中管理）
```

### 2.4 关联查询自动映射（一对多）

```java
public class User {
    private Long id;
    private String name;

    @TableField(exist = false)
    private List<Order> orders;  // 一对多，非数据库字段
}

// XML 中用 resultMap 映射
<resultMap id="UserWithOrders" type="User">
    <id property="id" column="id"/>
    <result property="name" column="name"/>
    <collection property="orders" ofType="Order">
        <id property="id" column="order_id"/>
        <result property="orderNo" column="order_no"/>
    </collection>
</resultMap>

<select id="selectUserWithOrders" resultMap="UserWithOrders">
    SELECT u.*, o.id as order_id, o.order_no
    FROM sys_user u
    LEFT JOIN sys_order o ON u.id = o.user_id
    WHERE u.id = #{userId}
</select>
```

**注意 N+1 问题**：关联查询如果用嵌套 `SELECT`（而不是 JOIN），会导致 N+1 查询（查 1 个用户 → N 次订单查询）。用 JOIN + resultMap 一次性查出。

---

## 三、自定义 SQL 与 Wrapper 结合

### 3.1 在自定义 SQL 中使用 Wrapper

```java
// Mapper 接口
public interface UserMapper extends BaseMapper<User> {

    // 在自定义 SQL 中使用 Wrapper 条件
    // ${ew.customSqlSegment} 会被替换成 WHERE ... 条件
    @Select("SELECT * FROM sys_user ${ew.customSqlSegment}")
    List<User> selectWithWrapper(@Param("ew") Wrapper<User> wrapper);
}
```

```java
// 使用
List<User> users = userMapper.selectWithWrapper(
    new LambdaQueryWrapper<User>()
        .eq(User::getStatus, 1)
        .gt(User::getAge, 18)
);

// 生成的 SQL：
// SELECT * FROM sys_user WHERE status = 1 AND age > 18
```

**原理**：`${ew.customSqlSegment}` 是 MP 的占位符，运行时会被 Wrapper 生成的 WHERE 条件替换。

---

## 四、性能优化实战

### 4.1 只查需要的字段

```java
// ❌ 不好：SELECT *，浪费带宽和内存
List<User> users = userMapper.selectList(null);

// ✅ 好：只查需要的字段
LambdaQueryWrapper<User> lqw = new LambdaQueryWrapper<>();
lqw.select(User::getId, User::getName, User::getEmail);
List<User> users = userMapper.selectList(lqw);
```

### 4.2 避免 N+1 查询

```java
// ❌ N+1 问题：查询 100 个用户，每个用户再查一次订单（100+1 次查询）
List<User> users = userMapper.selectList(null);
for (User user : users) {
    List<Order> orders = orderMapper.selectList(
        new LambdaQueryWrapper<Order>().eq(Order::getUserId, user.getId())
    );
    user.setOrders(orders);
}

// ✅ 方案1：用 JOIN 一次查出
// ✅ 方案2：用 IN 查询，2 次查询搞定
List<User> users = userMapper.selectList(null);
List<Long> userIds = users.stream().map(User::getId).collect(Collectors.toList());
List<Order> orders = orderMapper.selectList(
    new LambdaQueryWrapper<Order>().in(Order::getUserId, userIds)
);
// 然后在内存中组装（1 次查询用户 + 1 次查询所有订单 = 2 次）
```

### 4.3 分页优化（大数据量）

```java
// ❌ 不好：大分页（LIMIT 100000, 10）会很慢
// 因为 MySQL 要先读 100010 条，再丢弃前 100000 条

// ✅ 方案1：用 ID 游标分页（推荐）
LambdaQueryWrapper<User> lqw = new LambdaQueryWrapper<>();
lqw.gt(User::getId, lastId)   // WHERE id > 上一页最后一条的 id
   .orderByAsc(User::getId)
   .last("LIMIT 10");
List<User> users = userMapper.selectList(lqw);

// ✅ 方案2：延迟关联（覆盖索引）
// SELECT * FROM user a
// JOIN (SELECT id FROM user WHERE status=1 ORDER BY id LIMIT 100000, 10) b
// ON a.id = b.id
```

### 4.4 批量操作优化

```java
// ❌ 不好：循环单条插入（N 次网络往返）
for (User user : userList) {
    userMapper.insert(user);  // 每次都是一次数据库连接
}

// ✅ 好：批量插入
userService.saveBatch(userList);  // 默认 1000 条一批

// ✅ 更好：调整批大小（根据数据大小调整）
userService.saveBatch(userList, 500);  // 500 条一批

// ❌ 不好：循环单条更新
for (User user : userList) {
    userMapper.updateById(user);
}

// ✅ 好：批量更新（用 foreach 拼 SQL）
// 在 XML 里写 <foreach> 批量更新
```

---

## 五、MP 与原生 MyBatis 的取舍

```
┌─────────────────────────────────────────────────────────────┐
│          什么时候用 MP，什么时候用原生 MyBatis？          │
│                                                             │
│  场景1：单表 CRUD（增删改查）                             │
│    → 用 MP 的 BaseMapper / IService                        │
│    → 省 80% 的样板代码                                    │
│                                                             │
│  场景2：多表 JOIN、复杂 SQL                                │
│    → 用原生 MyBatis 的 XML                                │
│    → MP 也可以配合 XML 用（推荐）                          │
│                                                             │
│  场景3：存储过程、复杂报表                                │
│    → 用原生 MyBatis                                       │
│    → MP 的 Wrapper 不适合这种场景                         │
│                                                             │
│  场景4：函数式条件查询（动态条件多）                      │
│    → 用 MP 的 Wrapper                                    │
│    → 比 XML 的 <if> 标签灵活                              │
│                                                             │
│  结论：MP 和原生 MyBatis 不是二选一，而是互补！          │
│  MP 管单表 CRUD，原生 MyBatis 管复杂 SQL。              │
└─────────────────────────────────────────────────────────────┘
```

---

## 六、常见坑与排查

### 坑1：逻辑删除后唯一索引冲突

```java
// 问题：user 表有 UNIQUE KEY uk_email (email)
// 用户 A（email=a@test.com）被逻辑删除（deleted=1）
// 新用户 B 想用同一个 email 注册 → 唯一索引冲突！

// 解决：唯一索引加上 deleted 字段
UNIQUE KEY uk_email_deleted (email, deleted)
// 这样 deleted=0 和 deleted=1 可以共存（email 相同）
// 但两个 deleted=0 的相同 email 仍然冲突（正确行为）
```

### 坑2：updateById 更新了所有字段

```java
// 问题代码
User user = new User();
user.setId(1L);
user.setName("新名字");
userMapper.updateById(user);
// 生成的 SQL：
// UPDATE sys_user SET name='新名字', age=null, email=null WHERE id=1
//                                     ↑↑↑ 其他字段被设为 null 了！

// ✅ 解决：先查询再更新
User user = userMapper.selectById(1L);
user.setName("新名字");
userMapper.updateById(user);
// 或者用 UpdateWrapper，只更新指定字段
LambdaUpdateWrapper<User> luw = new LambdaUpdateWrapper<>();
luw.eq(User::getId, 1L)
   .set(User::getName, "新名字");
userMapper.update(null, luw);
```

### 坑3：Wrapper 的 select 方法把其他字段置 null

```java
// select() 指定查询列 → 返回的实体其他字段是 null
LambdaQueryWrapper<User> lqw = new LambdaQueryWrapper<>();
lqw.select(User::getId, User::getName);  // 只查这两列
List<User> users = userMapper.selectList(lqw);
// user.getEmail() == null（因为没查 email 列）

// 如果后续要把这个 User 更新回数据库 → 会把 email 更新成 null
// ✅ 解决：更新时不要用这个不完整对象
// 或者更新前先查一次完整对象
```

### 坑4：分页插件顺序问题

```java
// ❌ 错误：乐观锁插件在分页插件之后
MybatisPlusInterceptor interceptor = new MybatisPlusInterceptor();
interceptor.addInnerInterceptor(new PaginationInnerInterceptor(DbType.MYSQL));
interceptor.addInnerInterceptor(new OptimisticLockerInnerInterceptor());  // 顺序不对！

// ✅ 正确：乐观锁插件要在分页插件之前
interceptor.addInnerInterceptor(new OptimisticLockerInnerInterceptor());
interceptor.addInnerInterceptor(new PaginationInnerInterceptor(DbType.MYSQL));
// 原因：乐观锁需要在 SQL 执行前检查版本号
```

### 坑5：saveBatch 不生效（事务问题）

```java
// 问题：saveBatch 内部已经加了事务
// 如果你在外层也加了 @Transactional，可能导致批量插入退化为单条插入

// saveBatch 源码（简化）：
public boolean saveBatch(Collection<T> entityList, int batchSize) {
    // 这里内部开启了新事务
    return executeBatch(entityList, batchSize, (sqlSession, entity) -> {
        sqlSession.insert(sqlStatement, entity);
    });
}

// ✅ 解决：外层不要用 REQUIRED 事务（会用同一个 SqlSession）
// 或者直接用 saveBatch，不要在外层加 @Transactional
```

### 坑6：LambdaQueryWrapper 序列化问题

```java
// 问题：LambdaQueryWrapper 不能被序列化（分布式场景下传参会报错）
// 解决：用普通 QueryWrapper，或者不要把 Wrapper 当作参数传递
// Wrapper 应该是在使用的地方现场构建的
```

---

## 七、MP 配置最佳实践

### 7.1 生产环境配置

```yaml
mybatis-plus:
  configuration:
    # 生产环境：关闭 SQL 日志（影响性能）
    log-impl: org.apache.ibatis.logging.nologging.NoLoggingImpl
    # 开启二级缓存（如果用的话）
    cache-enabled: true
    # 超时设置
    default-statement-timeout: 30   # 30 秒超时
  global-config:
    # 生产环境：关闭 banner
    banner: false
```

### 7.2 多数据源

```java
// 多数据源场景（主从分离、多库查询）
// 用 MyBatis-Plus 的多数据源插件：mybatis-plus-dynamic-datasource

@DS("master")   // 主库（写）
@Service
public class UserService {
    @DS("slave")   // 从库（读）
    public User getById(Long id) {
        return userMapper.selectById(id);
    }
}
```

---

## 八、MyBatis-Plus vs JPA 对比

| 维度 | MyBatis-Plus | JPA / Hibernate |
|------|---------------|-----------------|
| **SQL 控制** | 半自动（单表自动，复杂 SQL 手写） | 全自动（HQL/JPQL） |
| **学习曲线** | 低（懂 SQL 就能用） | 高（需要理解脏检查、持久化上下文） |
| **复杂查询** | XML 手写 SQL，灵活 | 用 Criteria API 或 QueryDSL |
| **性能** | 高（SQL 可控，可针对性优化） | 中（N+1 问题、脏检查开销） |
| **数据库移植** | 差（手写 SQL 可能有数据库方言） | 好（HQL 是数据库无关的） |
| **适合场景** | 复杂业务 SQL、需要针对性优化 | 简单 CRUD、快速开发、数据库无关 |

**结论**：国内项目推荐 MP（SQL 可控、学习成本低）； JPA 适合对 SQL 优化要求不高、追求开发速度的项目。

---

## 面试话术总结

1. **MyBatis-Plus 解决了什么问题？**
   "原生 MyBatis 只解决了 SQL 可控 + 映射自动化，但单表 CRUD 仍然要手写大量重复 XML。MP 通过 BaseMapper 自动注入单表 CRUD SQL、Wrapper 条件构造器替代动态 SQL 标签、分页插件自动处理分页、代码生成器一键生成 Entity/Mapper/Service/Controller。复杂 SQL 仍然用 XML 手写，MP 只是增强不替代。"

2. **BaseMapper 的 CRUD 方法是怎么注入的？**
   "应用启动时，MP 的 MybatisMapperRegistry 扫描所有继承 BaseMapper 的 Mapper 接口，遍历 BaseMapper 中定义的方法（selectById/insert/updateById 等），通过 DefaultSqlInjector 为每个方法生成对应的 MappedStatement（包含动态生成的 SQL），注册到 MyBatis 的 Configuration 中。运行时调用 Mapper 方法，走的还是 MyBatis 原生的执行流程。"

3. **逻辑删除有什么坑？**
   "逻辑删除通过 @TableLogic 实现，删除时改为 UPDATE SET deleted=1。主要坑：1) 唯一索引要加上 deleted 字段（否则逻辑删除的记录会和正常记录冲突）；2) 已删除数据还在表中，需要定时归档清理；3) 关联查询需要手动加 deleted=0 条件（MP 不会自动加到 JOIN 的关联表上）。"

4. **MP 分页插件的原理？有什么注意事项？**
   "分页插件通过 MybatisPlusInterceptor 拦截 Executor.query()，在执行查询前自动拼接 COUNT SQL（查总数）和 LIMIT SQL（分页）。分页时传 Page 对象，结果自动封装回 Page。注意事项：1) 大数据量分页用 LIMIT 100000,10 会很慢，推荐用 ID 游标分页；2) 不需要总数时传 false 跳过 COUNT 查询。"

5. **saveBatch 的原理和注意事项？**
   "saveBatch 通过 SqlSession 的批处理模式，将多条 INSERT 语句攒批执行，减少网络往返。默认 1000 条一批。注意事项：1) 外层不要加 @Transactional（可能导致退化为单条）；2) 批大小要根据单条数据大小调整（太大内存溢出，太小效果不佳）；3) MySQL 需要开启 rewriteBatchedStatements=true 才能真正批处理。"

6. **MP 和原生 MyBatis 怎么取舍？**
   "不是二选一，是互补。单表 CRUD 用 MP 的 BaseMapper（省 80% 样板代码），复杂联查用原生 MyBatis 的 XML（灵活可控），动态条件多用 Wrapper（比 XML 的 <if> 标签灵活）。MP 完全兼容原生 MyBatis，XML 和注解方式都可以混用。"

---

*MP 的核心价值是「减少重复劳动」，不是「替代 SQL」。理解这个边界，才能用好它。*
