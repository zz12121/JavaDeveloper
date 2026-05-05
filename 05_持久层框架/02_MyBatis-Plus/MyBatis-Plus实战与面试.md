# MyBatis-Plus 实战与面试

> 掌握了 [[05_持久层框架/02_MyBatis-Plus/MyBatis-Plus核心原理]] 中的 CRUD 机制和 Wrapper 体系后，真实项目中的挑战在于：多表联查怎么做、性能怎么优化、和原生 MyBatis 怎么配合、MP 与 JPA 怎么选型。本文覆盖从整合配置到踩坑排查的完整实战路径。

---

## 这个问题为什么存在？

MP 的核心功能（单表 CRUD、Wrapper、分页、逻辑删除）在核心原理中已经讲清楚，但实际项目远比"继承 BaseMapper 就能用"复杂。多表联查是业务开发中最常见的场景，而 MP 的 Wrapper 只能处理单表条件——一旦涉及 JOIN，就必须回到原生 MyBatis 的方式。此外，批量操作的性能优化、多数据源配置、大数据量分页等实战问题，也需要明确的方案。

更重要的是"能用"和"用得好"的差距：`updateById` 把不相关字段更新为 null、`saveBatch` 在外层事务中退化为单条插入、分页插件的顺序配错导致乐观锁失效——这些问题不会报错，只会在生产环境中制造数据异常。

---

## 它是怎么解决问题的？

### Spring Boot 整合配置

```yaml
# application.yml
mybatis-plus:
  mapper-locations: classpath*:/mapper/**/*.xml    # Mapper XML 位置
  type-aliases-package: com.example.entity          # 实体类包扫描
  configuration:
    map-underscore-to-camel-case: true              # 驼峰转下划线（默认 true）
    log-impl: org.apache.ibatis.logging.stdout.StdOutImpl  # 开发环境打印 SQL
  global-config:
    db-config:
      logic-delete-field: deleted                   # 逻辑删除字段
      logic-delete-value: 1                         # 删除后的值
      logic-not-delete-value: 0                     # 未删除的值
      table-prefix: sys_                            # 表名前缀（自动去掉）
      id-type: ASSIGN_ID                            # 全局主键策略
```

```java
// MapperScan 配置（推荐在启动类上加，一个注解扫描所有 Mapper）
@SpringBootApplication
@MapperScan("com.example.mapper")
public class Application { }
```

### 多表联查：XML 手写 SQL + MP 分页

MP 的 Wrapper 只能处理单表条件。涉及多表 JOIN 时，在 Mapper XML 中手写 SQL，同时仍然可以用 MP 的分页插件：

```xml
<!-- UserMapper.xml -->
<select id="selectUserWithRole" resultType="UserRoleVO">
    SELECT u.id, u.name, u.age, r.role_name
    FROM sys_user u
    LEFT JOIN sys_user_role ur ON u.id = ur.user_id
    LEFT JOIN sys_role r ON ur.role_id = r.id
    WHERE u.deleted = 0 AND u.id = #{userId}
</select>

<!-- 分页联查：参数传 Page<T>，MP 分页插件自动拦截追加 LIMIT -->
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
```

```java
public interface UserMapper extends BaseMapper<User> {
    // 自定义方法 → 在 XML 中写 SQL（BaseMapper 没有的方法）
    UserRoleVO selectUserWithRole(@Param("userId") Long userId);

    // 分页：参数传 Page<T>，分页插件自动拦截
    Page<UserVO> selectUserPage(Page<UserVO> page, @Param("keyword") String keyword);
}
```

**什么时候用 XML，什么时候用注解？**
- 简单查询（< 5 行 SQL）→ 用 `@Select` 注解
- 复杂查询（多表 JOIN、动态 SQL）→ 必须用 XML
- 需要 SQL 代码审查 → 推荐 XML（集中管理）

### 自定义 SQL 中使用 Wrapper

```java
public interface UserMapper extends BaseMapper<User> {
    // ${ew.customSqlSegment} 会被替换成 Wrapper 生成的 WHERE 条件
    @Select("SELECT * FROM sys_user ${ew.customSqlSegment}")
    List<User> selectWithWrapper(@Param("ew") Wrapper<User> wrapper);
}

// 使用
List<User> users = userMapper.selectWithWrapper(
    new LambdaQueryWrapper<User>()
        .eq(User::getStatus, 1)
        .gt(User::getAge, 18)
);
// 生成：SELECT * FROM sys_user WHERE status = 1 AND age > 18
```

`${ew.customSqlSegment}` 是 MP 的占位符，运行时会被 Wrapper 生成的 WHERE 条件替换。这样自定义 SQL 可以复用 Wrapper 的条件构造能力。

### 一对多关联映射

```xml
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

注意 N+1 问题：关联查询如果用嵌套 `<select>`（而不是 JOIN），会导致 N+1 查询（查 1 个用户 → N 次订单查询）。用 JOIN + `<collection>` 的 `<resultMap>` 一次性查出。

---

## 深入原理

### saveBatch 在外层事务中退化的原因

```
saveBatch 的批处理原理：
1. 获取一个新的 SqlSession（批处理模式）
2. 循环调用 sqlSession.insert()
3. 每 batchSize 条执行一次 flushStatements()
4. 提交并关闭 SqlSession

问题：如果外层有 @Transactional（传播行为 = REQUIRED）
→ 外层事务已经打开了一个 SqlSession
→ saveBatch 内部尝试获取新的 SqlSession 时
→ Spring 的事务管理器返回的是同一个 SqlSession（REQUIRED 传播行为的定义）
→ 批处理模式没有生效 → 退化为逐条插入

解决：不要在外层用 REQUIRED 事务包裹 saveBatch
或者使用 REQUIRES_NEW 传播行为让 saveBatch 在新事务中执行
```

### MP 与 JPA 的架构差异

| 维度 | MyBatis-Plus | JPA / Hibernate |
|------|---------------|-----------------|
| **SQL 控制** | 半自动（单表自动，复杂 SQL 手写） | 全自动（HQL/JPQL，也可用原生 SQL） |
| **学习曲线** | 低（懂 SQL 就能用） | 高（需要理解脏检查、持久化上下文、延迟加载） |
| **性能可预测性** | 高（SQL 可控，可针对性优化） | 中（N+1 问题、脏检查开销难以预测） |
| **数据库移植** | 差（手写 SQL 有数据库方言） | 好（HQL 是数据库无关的） |
| **复杂查询** | XML 手写 SQL，灵活 | Criteria API / QueryDSL |
| **适合场景** | 复杂业务 SQL、需要针对性优化 | 简单 CRUD、快速开发 |

JPA 的全自动（脏检查自动更新、关联关系自动管理）在简单场景下很方便，但在复杂业务 SQL 场景下容易遇到 N+1 问题、脏检查导致的意外更新、延迟加载的 LazyInitializationException。MP 的"半自动"策略更可控——简单 CRUD 自动，复杂 SQL 手写，开发者始终知道执行的每一条 SQL 是什么。

---

## 正确使用方式

### 只查需要的字段

```java
// ❌ 不好：SELECT *，浪费带宽和内存
List<User> users = userMapper.selectList(null);

// ✅ 好：只查需要的字段
LambdaQueryWrapper<User> lqw = new LambdaQueryWrapper<>();
lqw.select(User::getId, User::getName, User::getEmail);
List<User> users = userMapper.selectList(lqw);
```

### 避免 N+1 查询

```java
// ❌ N+1 问题：100 个用户 → 101 次查询
List<User> users = userMapper.selectList(null);
for (User user : users) {
    List<Order> orders = orderMapper.selectList(
        new LambdaQueryWrapper<Order>().eq(Order::getUserId, user.getId()));
}

// ✅ 方案一：用 JOIN 一次查出
// ✅ 方案二：IN 查询 + 内存组装（2 次查询）
List<User> users = userMapper.selectList(null);
List<Long> userIds = users.stream().map(User::getId).toList();
List<Order> orders = orderMapper.selectList(
    new LambdaQueryWrapper<Order>().in(Order::getUserId, userIds));
// 内存中按 userId 分组组装
```

### 批量插入的性能优化

```java
// ❌ 不好：循环单条插入（N 次网络往返）
for (User user : userList) {
    userMapper.insert(user);
}

// ✅ 好：批量插入（默认 1000 条一批）
userService.saveBatch(userList);

// ✅ 更好：JDBC URL 加 rewriteBatchedStatements=true（MySQL 专属优化）
// jdbc:mysql://localhost:3306/mydb?rewriteBatchedStatements=true
// MySQL 驱动会将多条 INSERT 重写为一条多行 INSERT
// 网络往返从 N 次降为 1 次，性能提升 5~10 倍

// ✅ 调整批大小（根据数据大小调整）
userService.saveBatch(userList, 500);  // 500 条一批
```

### 生产环境配置

```yaml
mybatis-plus:
  configuration:
    # 生产环境：关闭 SQL 日志（影响性能）
    log-impl: org.apache.ibatis.logging.nologging.NoLoggingImpl
    # SQL 超时设置（防止慢 SQL 一直占连接）
    default-statement-timeout: 30
  global-config:
    # 生产环境：关闭 banner
    banner: false
```

### 多数据源配置

```java
// 使用 mybatis-plus-dynamic-datasource 插件
@DS("master")   // 主库（写）
@Service
public class UserService {
    @DS("slave")   // 从库（读）
    public User getById(Long id) {
        return userMapper.selectById(id);
    }
}
```

`@DS` 注解通过 AOP 拦截方法调用，在执行前切换数据源。粒度可以到方法级别——同一个 Service 中写操作走主库、读操作走从库，实现简单的读写分离。

---

## 边界情况和坑

### updateById 更新了所有字段

```java
// ❌ new 出来的对象只有 id 和 name，其他字段都是 null
User user = new User();
user.setId(1L);
user.setName("新名字");
userMapper.updateById(user);
// 生成：UPDATE sys_user SET name='新名字', age=null, email=null WHERE id=1
// 其他字段被设为 null！

// ✅ 方案一：先查再改
User user = userMapper.selectById(1L);
user.setName("新名字");
userMapper.updateById(user);

// ✅ 方案二：用 UpdateWrapper 只更新指定字段
new LambdaUpdateWrapper<User>()
    .eq(User::getId, 1L)
    .set(User::getName, "新名字");
```

### Wrapper 的 select 方法返回不完整对象

```java
// select() 指定查询列 → 返回的实体其他字段是 null
LambdaQueryWrapper<User> lqw = new LambdaQueryWrapper<>();
lqw.select(User::getId, User::getName);
List<User> users = userMapper.selectList(lqw);
// user.getEmail() == null

// 坑：用这个不完整对象做 updateById → 会把 email 更新成 null
// ✅ 解决：查询和更新用不同的对象
```

### 分页插件顺序错误

```java
// ❌ 错误：乐观锁在分页之后
interceptor.addInnerInterceptor(new PaginationInnerInterceptor(DbType.MYSQL));
interceptor.addInnerInterceptor(new OptimisticLockerInnerInterceptor());

// ✅ 正确：乐观锁在分页之前
interceptor.addInnerInterceptor(new OptimisticLockerInnerInterceptor());
interceptor.addInnerInterceptor(new PaginationInnerInterceptor(DbType.MYSQL));
// 原因：分页插件会修改 SQL 结构（追加 LIMIT），乐观锁需要在最终 SQL 基础上追加 version 条件
```

### 防全表更新/删除

```java
// 开启防全表操作插件（开发阶段建议开启）
interceptor.addInnerInterceptor(new BlockAttackInnerInterceptor());

// 效果：
userService.update(new User(), null);     // ❌ 抛异常！全表更新被阻止
userService.remove(new QueryWrapper<>()); // ❌ 抛异常！全表删除被阻止

// 原因：没有 WHERE 条件的 UPDATE/DELETE 太危险，误操作可能导致数据全丢
```

### 逻辑删除的数据膨胀

```
问题：逻辑删除的数据永远在表中，不参与查询但占据存储空间
→ 数据量持续增长 → 查询性能下降 → 存储成本增加

解决：
1. 定时任务归档：将已删除超过 N 天的数据迁移到归档表
2. 定时物理删除：定期执行 DELETE FROM table WHERE deleted = 1 AND update_time < 30天前
3. 业务评估：不是所有表都需要逻辑删除——操作日志、临时数据可以直接物理删除
```

### LambdaQueryWrapper 不可序列化

```
问题：LambdaQueryWrapper 使用了 SerializedLambda（通过方法引用获取列名）
→ 在分布式场景下作为 RPC 参数传递时会报序列化异常

解决：Wrapper 应该在使用的地方现场构建，不要跨服务传递
如果需要传递查询条件，用 DTO 或 Map 描述条件，在目标服务端重建 Wrapper
```
