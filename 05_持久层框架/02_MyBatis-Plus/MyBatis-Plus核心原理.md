# MyBatis-Plus 核心原理

> 原生 MyBatis 只解决了「SQL 可控 + 映射自动化」的问题，但 90% 的数据库操作都是单表增删改查——每个表都要手写重复的 XML。MyBatis-Plus 在 MyBatis 之上加了增强层，用 `BaseMapper<T>` 一行代码替代几十行重复的 SQL。

---

## 这个问题为什么存在？

```java
// 原生 MyBatis：每个表都要写一堆重复的 XML
// UserMapper.xml
<select id="selectById" resultType="User">
    SELECT * FROM user WHERE id = #{id}
</select>
<select id="selectList" resultType="User">
    SELECT * FROM user
</select>
<insert id="insert">
    INSERT INTO user(name, age, email) VALUES(#{name}, #{age}, #{email})
</insert>
<update id="updateById">
    UPDATE user SET name=#{name}, age=#{age} WHERE id = #{id}
</update>
<delete id="deleteById">
    DELETE FROM user WHERE id = #{id}
</delete>
<!-- 每张表都来一遍... 20 张表就是 100 个 SQL -->
```

这不是"能不能用"的问题，而是**重复劳动效率低下**的问题。单表 CRUD 的 SQL 模式高度固定（SELECT * FROM table WHERE id = ?、INSERT INTO table ... VALUES ...），完全可以由框架根据实体类的结构自动生成。

MyBatis-Plus 的定位：**MyBatis 的增强工具，在 MyBatis 的基础上只做增强不做改变**。原有的 XML/注解方式完全可用，复杂 SQL 仍然手写——MP 只接管单表 CRUD 的重复工作。

---

## 它是怎么解决问题的？

### BaseMapper CRUD：继承即用

```java
// 只需继承 BaseMapper<T>，就有了全套 CRUD 方法
public interface UserMapper extends BaseMapper<User> {
    // 这里一个方法都不用写！
}

User user = userMapper.selectById(1L);
List<User> users = userMapper.selectList(null);
userMapper.insert(user);
userMapper.updateById(user);
userMapper.deleteById(1L);
```

**底层原理**：MP 在应用启动时，通过 `MybatisMapperRegistry` 和 `MybatisMapperProxyFactory` 动态注册了 BaseMapper 中定义的所有方法。

```
应用启动时：
1. Spring 扫描到 UserMapper（extends BaseMapper<User>）
2. MP 的 MapperScannerConfigurer（替代 MyBatis 原生的）介入
3. MybatisMapperRegistry.addMapper()
4. 遍历 BaseMapper 中所有方法（selectById/insert/updateById...）
5. 对每个方法，通过 ISqlInjector 生成对应的 MappedStatement
6. 每个 MappedStatement 包含动态生成的 SQL（根据实体类的 @TableName/@TableField 注解自动拼字段名）
7. 最终注册到 MyBatis 的 Configuration 中

运行时：
userMapper.selectById(1L)
→ MapperProxy.invoke()
→ MappedStatement（MP 启动时注入的）
→ Executor.query()
→ 数据库
```

关键组件 `ISqlInjector`（SQL 注入器）负责根据实体类的元信息（表名、字段名、主键策略）生成对应的 SQL 语句。`DefaultSqlInjector` 内置了 Insert、Delete、Update、SelectById、SelectList、SelectPage 等标准方法。

### 实体类注解：Java 对象与数据库表的映射

```java
@TableName("sys_user")                    // 表名映射
public class User {

    @TableId(type = IdType.ASSIGN_ID)     // 主键策略（雪花算法，19 位 Long）
    private Long id;

    @TableField("user_name")              // 字段映射（驼峰转下划线默认开启，一致时可不写）
    private String userName;

    @TableField(select = false)           // 查询时不返回此字段（如密码）
    private String password;

    @TableField(exist = false)            // 非数据库字段（不参与 SQL 映射）
    private String confirmPassword;

    @TableField(fill = FieldFill.INSERT)  // 插入时自动填充
    private LocalDateTime createTime;

    @TableField(fill = FieldFill.INSERT_UPDATE) // 插入和更新时都填充
    private LocalDateTime updateTime;

    @TableLogic                           // 逻辑删除标记
    private Integer deleted;

    @Version                              // 乐观锁版本号
    private Integer version;
}
```

**主键策略为什么推荐雪花算法（ASSIGN_ID）而不是自增（AUTO）？**
- 自增 ID 暴露业务数据量（id=10000 意味着有 1 万条数据，信息泄露）
- 分布式环境下自增 ID 需要额外协调（步长/号段模式）
- 雪花算法生成有序、趋势递增的 Long，对 B+ 索引插入友好

### 条件构造器：替代 XML 动态 SQL

```java
// QueryWrapper（字符串列名，运行时才发现写错）
QueryWrapper<User> qw = new QueryWrapper<>();
qw.eq("name", "张三")              // WHERE name = '张三'
  .gt("age", 18)                    // AND age > 18
  .like("name", "张")               // AND name LIKE '%张%'
  .between("age", 18, 60)          // AND age BETWEEN 18 AND 60
  .orderByDesc("create_time");     // ORDER BY create_time DESC

// LambdaQueryWrapper（推荐！方法引用，编译期检查列名）
LambdaQueryWrapper<User> lqw = new LambdaQueryWrapper<>();
lqw.eq(User::getName, "张三")           // 写错列名直接编译报错
   .gt(User::getAge, 18)
   .orderByDesc(User::getCreateTime);

// 条件组装（动态拼接）
lqw.eq(StringUtils.isNotBlank(name), User::getName, name)  // name 不为空才加条件
   .eq(status != null, User::getStatus, status);            // status 不为 null 才加条件
// 第一个 boolean 参数：true 才拼接到 SQL

// 链式调用（更简洁）
List<User> users = userMapper.selectList(
    new LambdaQueryWrapper<User>()
        .eq(User::getStatus, 1)
        .like(User::getName, "张")
        .orderByDesc(User::getCreateTime)
);
```

**LambdaQueryWrapper vs QueryWrapper** 的本质区别：QueryWrapper 用字符串表示列名（`"name"`），写错了只有运行时抛 SQLException 才能发现，重构时 IDE 也不会自动更新。LambdaQueryWrapper 用方法引用（`User::getName`），编译期就能发现错误，重构时 IDE 自动同步。**生产环境一律用 LambdaQueryWrapper**。

### IService：Service 层的 CRUD 增强接口

```java
public interface UserService extends IService<User> {}

@Service
public class UserServiceImpl extends ServiceImpl<UserMapper, User> implements UserService {}

// 使用
userService.save(user);                  // 插入一条
userService.saveBatch(userList);         // 批量插入
userService.saveOrUpdate(user);          // 有 id 则更新，无 id 则插入
userService.removeById(1L);              // 按 id 删除
userService.updateById(user);            // 按 id 更新
userService.getById(1L);                 // 按 id 查
userService.page(new Page<>(1, 10));     // 分页查

// 链式调用
List<User> users = userService.lambdaQuery()
    .eq(User::getStatus, 1)
    .like(User::getName, "张")
    .orderByDesc(User::getCreateTime)
    .list();
```

IService 在 BaseMapper 之上封装了更丰富的操作（批量、分页、链式调用），并且提供了事务支持（`saveBatch` 内部使用 `SqlSession` 的批处理模式）。

### 分页插件：自动分页

```java
// 配置
@Configuration
public class MyBatisPlusConfig {
    @Bean
    public MybatisPlusInterceptor mybatisPlusInterceptor() {
        MybatisPlusInterceptor interceptor = new MybatisPlusInterceptor();
        interceptor.addInnerInterceptor(new PaginationInnerInterceptor(DbType.MYSQL));
        return interceptor;
    }
}

// 使用
Page<User> page = userService.page(new Page<>(1, 10), wrapper);
// page.getRecords() → 数据列表
// page.getTotal()   → 总记录数
// page.getPages()   → 总页数
```

**分页原理**：`PaginationInnerInterceptor` 拦截 MyBatis 的 `Executor.query()`，检测到第一个参数是 `Page` 对象后，自动执行两条 SQL：
1. `SELECT COUNT(*) FROM ...` — 查询总数
2. `SELECT ... LIMIT offset, size` — 分页查询

通过 `DbType` 参数自动适配不同数据库的分页语法（MySQL 的 `LIMIT`、PostgreSQL 的 `LIMIT/OFFSET`、Oracle 的 `ROWNUM`），开发者不需要关心数据库差异。

### 逻辑删除：不真正删除数据

```yaml
# 全局配置
mybatis-plus:
  global-config:
    db-config:
      logic-delete-field: deleted
      logic-delete-value: 1      # 删除后的值
      logic-not-delete-value: 0  # 未删除的值
```

```java
@TableLogic
private Integer deleted;
```

MP 在 SQL 执行层面拦截了所有涉及逻辑删除字段的操作：

```sql
-- userMapper.deleteById(1L)
-- 不是 DELETE FROM user WHERE id = 1
-- 而是 UPDATE user SET deleted = 1 WHERE id = 1 AND deleted = 0

-- userMapper.selectById(1L)
-- 不是 SELECT * FROM user WHERE id = 1
-- 而是 SELECT * FROM user WHERE id = 1 AND deleted = 0

-- userMapper.selectList(null)
-- 不是 SELECT * FROM user
-- 而是 SELECT * FROM user WHERE deleted = 0
```

本质是通过 MyBatis 拦截器，在所有查询和更新条件中**自动追加** `AND deleted = 0`，在删除操作中将 `DELETE` 改为 `UPDATE ... SET deleted = 1`。

### 乐观锁：并发更新的安全保障

```java
// 配置（乐观锁插件必须在分页插件之前）
interceptor.addInnerInterceptor(new OptimisticLockerInnerInterceptor());
interceptor.addInnerInterceptor(new PaginationInnerInterceptor(DbType.MYSQL));

// 实体类加 @Version
@Version
private Integer version;
```

```
// 1. 先查（获取当前版本号）
User user = userMapper.selectById(1L);
// user.version = 3

// 2. 修改业务字段
user.setName("新名字");

// 3. 更新 → 实际执行的 SQL：
UPDATE user SET name = '新名字', version = 4
WHERE id = 1 AND version = 3
                      ↑ 自动追加版本号条件

// 返回影响行数：
// 1 → 更新成功（版本号匹配）
// 0 → 更新失败（版本号已被其他线程修改，并发冲突）
```

乐观锁的原理是在 UPDATE 语句的 WHERE 条件中追加版本号检查——只有当数据库中的版本号和查询时拿到的版本号一致时，更新才生效。另一个线程如果在这期间修改了数据，版本号会自增，第一个线程的 WHERE 条件就不匹配了。

---

## 深入原理

### Wrapper 的底层：SQL 片段列表

```
QueryWrapper 内部维护了一个 List<SqlSegment>（SQL 片段列表）

每次调用条件方法（eq/like/gt...）：
1. 将条件转换为 SqlSegment 对象
2. SqlSegment 包含：列名、操作符（=、LIKE、>、<...）、值、前后缀
3. 存入 segments 列表

最终生成 SQL 时：
1. 遍历 segments
2. 按顺序拼接：WHERE + segment1 AND segment2 AND ...
3. 处理 AND/OR 嵌套（通过 nested() 方法）
4. 处理条件为 false 的情况（跳过该 segment）
```

嵌套条件的实现：

```java
lqw.eq(User::getStatus, 1)
   .and(w -> w.eq(User::getAge, 18).or().eq(User::getLevel, 5));
// 生成：WHERE status = 1 AND (age = 18 OR level = 5)

lqw.eq(User::getStatus, 1)
   .nested(w -> w.like(User::getName, "张").ge(User::getAge, 25));
// 生成：WHERE status = 1 AND (name LIKE '%张%' AND age >= 25)
```

`and(w -> ...)` 和 `nested(w -> ...)` 的区别：`and` 会在嵌套块前加 AND 连接符，`nested` 直接追加嵌套块（由上一个条件决定连接方式）。

### 自动填充的两种模式

```java
@Component
public class MyMetaObjectHandler implements MetaObjectHandler {

    @Override
    public void insertFill(MetaObject metaObject) {
        // strictInsertFill：字段已有值时不覆盖
        this.strictInsertFill(metaObject, "createTime", LocalDateTime.class, LocalDateTime.now());
        this.strictInsertFill(metaObject, "updateTime", LocalDateTime.class, LocalDateTime.now());
    }

    @Override
    public void updateFill(MetaObject metaObject) {
        // fill：无条件覆盖（推荐用于 updateTime，每次更新都必须是最新时间）
        this.fill(metaObject, "updateTime");
    }
}
```

`strictInsertFill` 和 `fill` 的区别：`strict` 版本检查字段是否已有值，已有值则跳过（尊重手动设置的值）；非 `strict` 版本无条件覆盖。

### 插件机制：MybatisPlusInterceptor

```
MybatisPlusInterceptor（外层，管理多个 InnerInterceptor）
├── OptimisticLockerInnerInterceptor   ← 乐观锁（修改 UPDATE 语句，追加 version 条件）
├── PaginationInnerInterceptor        ← 分页（修改 SELECT 语句，追加 LIMIT/COUNT）
├── BlockAttackInnerInterceptor        ← 防全表更新/删除（检测 WHERE 条件是否为空）
└── IllegalSQLInnerInterceptor         ← 非法 SQL 检查
```

所有 InnerInterceptor 都是 MyBatis 的 `Interceptor` 实现，拦截 `Executor` 的 `query()`/`update()` 方法。拦截顺序很重要：乐观锁需要在 SQL 执行前检查版本号，所以必须排在分页插件之前（分页插件会修改 SQL 结构，乐观锁需要在修改后的 SQL 基础上工作）。

### saveOrUpdate 的实现原理

```java
// ServiceImpl.saveOrUpdate() 的核心逻辑
public boolean saveOrUpdate(T entity) {
    if (entity.getId() != null) {
        T existing = baseMapper.selectById(entity.getId());  // 先查
        if (existing != null) {
            return updateById(entity) > 0;  // 存在 → 更新
        }
    }
    return insert(entity) > 0;  // 不存在 → 插入
}
```

注意：`saveOrUpdate` 会先执行一次 SELECT，在高并发场景下有性能开销。如果明确知道是插入还是更新，直接用 `save`/`updateById`。

---

## 正确使用方式

### 雪花算法主键 vs 自增主键的选型

| 维度 | 雪花算法（ASSIGN_ID） | 自增（AUTO） |
|------|----------------------|-------------|
| **分布式** | 天然支持（算法内含机器标识） | 需要额外协调 |
| **安全性** | 不暴露数据量 | 暴露记录数 |
| **索引性能** | 趋势递增，对 B+ 索引友好 | 严格递增，末尾追加最优 |
| **可读性** | 19 位 Long，不方便调试 | 简单数字 |

**结论**：分布式系统用雪花算法，单机简单项目用自增也可以。

### 条件构造器的选择

```
单表条件查询 → LambdaQueryWrapper（编译期检查）
多表条件查询 → 自定义 SQL（XML + @Select）
动态条件（参数可能为空）→ LambdaQueryWrapper 的条件组装（第一个 boolean 参数）
嵌套条件（括号分组）→ and(w -> ...) / nested(w -> ...)
```

### 代码生成器：批量生成样板代码

```
一个典型后台管理系统：
  20 张表 → 每张表对应 Entity + Mapper + Service + ServiceImpl + Controller
  手写 100 个文件 → 代码生成器 10 秒搞定
```

代码生成器通过 `FastAutoGenerator` 读取数据库表结构，自动生成实体类（含 `@TableName`/`@TableId`/`@TableField`）、Mapper 接口（继承 `BaseMapper`）、Service 接口和实现、Controller。

### MP 与原生 MyBatis 的互补关系

```
场景1：单表 CRUD → 用 MP 的 BaseMapper / IService（省 80% 样板代码）
场景2：多表 JOIN → 用原生 MyBatis 的 XML（MP 也可以配合 XML 用）
场景3：存储过程/复杂报表 → 用原生 MyBatis
场景4：动态条件查询 → 用 MP 的 Wrapper（比 XML 的 <if> 标签简洁）

结论：MP 管单表 CRUD，原生 MyBatis 管复杂 SQL。两者无缝混用。
```

---

## 边界情况和坑

### updateById 更新了所有字段

```java
// ❌ 危险：new 出来的对象只有 id 和 name，其他字段都是 null
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

**根因**：`updateById` 会将实体类中**所有字段**都放入 SET 子句。只有非 null 字段才更新的行为在 MP 中不是默认的——你需要先查询出完整对象，或者用 `UpdateWrapper.set()` 显式指定要更新的字段。

### 逻辑删除导致唯一索引冲突

```sql
-- 问题：user 表有 UNIQUE KEY uk_email (email)
-- 用户 A（email=a@test.com）被逻辑删除（deleted=1）
-- 新用户 B 想用同一个 email → 唯一索引冲突！

-- 解决：唯一索引加上 deleted 字段
UNIQUE KEY uk_email_deleted (email, deleted)
-- deleted=0 和 deleted=1 可以共存（email 相同，但 deleted 值不同，组合唯一）
-- 但两个 deleted=0 的相同 email 仍然冲突（正确行为）
```

### Wrapper 的 select 方法返回不完整对象

```java
LambdaQueryWrapper<User> lqw = new LambdaQueryWrapper<>();
lqw.select(User::getId, User::getName);  // 只查这两列
List<User> users = userMapper.selectList(lqw);
// user.getEmail() == null（因为没查 email 列）

// 坑：如果后续用这个不完整对象做 updateById → 会把 email 更新成 null
```

### 分页插件的大分页性能问题

```java
// LIMIT 100000, 10 → MySQL 先读 100010 条，再丢弃前 100000 条 → 慢

// 方案一：不查总数（只需要数据，不需要分页信息）
Page<User> page = new Page<>(1, 10, false);  // 第三个参数 false = 不查 COUNT

// 方案二：游标分页（大数据量推荐）
lqw.gt(User::getId, lastId)   // WHERE id > 上一页最后一条的 id
   .orderByAsc(User::getId)
   .last("LIMIT 10");
```

### 乐观锁插件顺序错误

```java
// ❌ 错误：乐观锁在分页之后
interceptor.addInnerInterceptor(new PaginationInnerInterceptor(DbType.MYSQL));
interceptor.addInnerInterceptor(new OptimisticLockerInnerInterceptor());

// ✅ 正确：乐观锁在分页之前
interceptor.addInnerInterceptor(new OptimisticLockerInnerInterceptor());
interceptor.addInnerInterceptor(new PaginationInnerInterceptor(DbType.MYSQL));
```

### LambdaQueryWrapper 不可序列化

```java
// ❌ LambdaQueryWrapper 包含方法引用（SerializedLambda），在分布式场景下传参会报错
// 解决：Wrapper 应该在使用的地方现场构建，不要作为方法参数跨服务传递
```
