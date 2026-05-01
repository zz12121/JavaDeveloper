# MyBatis-Plus 核心原理

## 这个问题为什么存在？

> 原生 MyBatis 只解决了「SQL 可控 + 映射自动化」的问题，但没解决「重复 CRUD」的问题。

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
<!-- 每张表都来一遍... 10 张表就是 50 个 SQL -->
```

**痛点**：
1. **单表 CRUD 重复劳动**——90% 的数据库操作都是增删改查，但每个表都要手写 XML
2. **条件构造繁琐**——多条件查询需要大量动态 SQL 标签（`<if>`/`<where>`/`<choose>`）
3. **分页要自己写**——每种数据库的分页语法不同，手写容易出错
4. **多租户/逻辑删除等通用需求**——每个项目都要重复实现

**MyBatis-Plus（简称 MP）的定位**：MyBatis 的增强工具，在 MyBatis 的基础上**只做增强不做改变**。

---

## 一、整体架构

### 1.1 核心组件关系

```
┌─────────────────────────────────────────────────────────────┐
│                  MyBatis-Plus 架构                          │
│                                                             │
│  ┌─────────────┐    继承     ┌──────────────┐              │
│  │  BaseMapper<T> │────────→│  MybatisMapper │              │
│  │  (CRUD 方法)   │          │  (MyBatis原生)  │              │
│  └──────────┬────┘          └──────────────┘              │
│             │ 注入 SQL                                      │
│             ▼                                               │
│  ┌──────────────────────┐   拦截    ┌──────────────┐       │
│  │ MybatisPlusInterceptor│────────→│  Executor     │       │
│  │ (分页/乐观锁/防全表)   │          │  (MyBatis执行器)│       │
│  └──────────────────────┘          └──────────────┘       │
│             │                                               │
│             ▼                                               │
│  ┌──────────────────────┐                                  │
│  │  ISqlInjector         │                                  │
│  │  (SQL 注入器)          │                                  │
│  │  - selectById         │                                  │
│  │  - selectList         │                                  │
│  │  - insert             │                                  │
│  │  - updateById         │                                  │
│  │  - deleteById         │                                  │
│  │  - selectPage         │                                  │
│  └──────────────────────┘                                  │
└─────────────────────────────────────────────────────────────┘
```

**为什么是「增强」而不是「替代」？**
- MP 不覆盖 MyBatis 的任何配置，原有的 XML/注解方式完全可用
- 复杂 SQL 仍然自己写在 XML 里，MP 只管单表 CRUD
- 如果你需要，甚至可以不用 MP 的任何功能，只用它的条件构造器

### 1.2 依赖关系

```xml
<!-- MyBatis-Plus Starter（Spring Boot） -->
<dependency>
    <groupId>com.baomidou</groupId>
    <artifactId>mybatis-plus-spring-boot3-starter</artifactId>
    <version>3.5.7</version>  <!-- Spring Boot 3.x 用这个 -->
</dependency>

<!-- 底层依赖关系 -->
mybatis-plus-spring-boot3-starter
  ├── mybatis-plus-core          ← 核心功能（CRUD、Wrapper、SQL 注入）
  ├── mybatis-plus-extension     ← 扩展功能（分页插件、代码生成器）
  └── mybatis-spring-boot-starter ← MyBatis 原生 Spring Boot 集成
```

**注意**：引入 MP 后**不要**再引入 `mybatis-spring-boot-starter`，否则版本冲突。

---

## 二、BaseMapper CRUD 原理

### 2.1 为什么继承 BaseMapper 就能用？

```java
// 只需继承 BaseMapper<T>，就有了全套 CRUD 方法
public interface UserMapper extends BaseMapper<User> {
    // 这里一个方法都不用写！
}

// 使用
@Autowired
private UserMapper userMapper;

User user = userMapper.selectById(1L);
List<User> users = userMapper.selectList(null);
userMapper.insert(user);
userMapper.updateById(user);
userMapper.deleteById(1L);
```

**原理**：MP 通过 `MybatisMapperRegistry` 和 `MybatisMapperProxyFactory` 动态注册了 BaseMapper 中定义的方法。

```
应用启动时：
1. Spring 扫描到 UserMapper（extends BaseMapper<User>）
2. MP 的 MapperScannerConfigurer（替代 MyBatis 原生的）介入
3. MybatisMapperRegistry.addMapper()
4. 遍历 BaseMapper 中所有方法（selectById/insert/updateById...）
5. 对每个方法，通过 ISqlInjector 生成对应的 MappedStatement
6. 每个 MappedStatement 包含动态生成的 SQL（根据 @TableField 注解自动拼字段名）
7. 最终注册到 MyBatis 的 Configuration 中

运行时：
userMapper.selectById(1L)
→ MapperProxy.invoke()
→ MappedStatement（MP 启动时注入的）
→ Executor.query()
→ 数据库
```

**ISqlInjector 的核心实现（DefaultSqlInjector）**：

```java
// 简化的源码逻辑
public class DefaultSqlInjector extends AbstractSqlInjector {
    @Override
    public List<AbstractMethod> getMethodList(Class<?> mapperClass, TableInfo tableInfo) {
        return Stream.of(
            new Insert(),                // INSERT INTO ...
            new Delete(),                // DELETE FROM ... WHERE id = ?
            new DeleteById(),            // DELETE FROM ... WHERE id = ?
            new Update(),                // UPDATE ... SET ... WHERE ...
            new UpdateById(),            // UPDATE ... SET ... WHERE id = ?
            new SelectById(),            // SELECT * FROM ... WHERE id = ?
            new SelectBatchByIds(),      // SELECT * FROM ... WHERE id IN (?, ?, ?)
            new SelectList(),            // SELECT * FROM ...
            new SelectPage(),            // SELECT * FROM ... LIMIT ?, ?
            new SelectCount(),           // SELECT COUNT(*) FROM ...
            // ... 更多方法
        ).collect(Collectors.toList());
    }
}
```

### 2.2 @TableName 和 @TableField

```java
@TableName("sys_user")                    // 表名映射（类名和表名不一致时必须指定）
public class User {

    @TableId(type = IdType.ASSIGN_ID)     // 主键策略
    private Long id;

    @TableField("user_name")              // 字段映射（驼峰转下划线默认开启，一致时可不写）
    private String userName;

    @TableField(select = false)           // 查询时不返回此字段（如密码）
    private String password;

    @TableField(exist = false)            // 非数据库字段（不参与 SQL 映射）
    private String confirmPassword;

    @TableField(fill = FieldFill.INSERT)  // 自动填充（插入时填充）
    private LocalDateTime createTime;

    @TableField(fill = FieldFill.INSERT_UPDATE) // 插入和更新时都填充
    private LocalDateTime updateTime;

    @TableLogic                           // 逻辑删除标记
    private Integer deleted;

    @Version                              // 乐观锁版本号
    private Integer version;
}
```

**主键策略（@TableId type）**：

| 策略 | 说明 | 适用场景 |
|------|------|---------|
| `ASSIGN_ID` | MP 自动生成 ID（雪花算法，19 位 Long） | 分布式系统（推荐） |
| `ASSIGN_UUID` | 自动生成 UUID（去掉横线） | 兼容旧系统 |
| `INPUT` | 开发者手动设置 | 自定义 ID 生成规则 |
| `AUTO` | 数据库自增 | 单机 MySQL |
| `NONE` | 无状态（跟随全局配置） | 默认值 |

**为什么默认推荐雪花算法而不是自增？**
- 自增 ID 暴露业务数据量（安全风险）
- 分布式环境下自增 ID 需要额外协调（步长/号段）
- 雪花算法生成有序、趋势递增的 Long，对 B+ 索引友好

### 2.3 驼峰转下划线

```yaml
# application.yml
mybatis-plus:
  configuration:
    map-underscore-to-camel-case: true   # 默认就是 true
```

```
userName  →  user_name     # Java 字段名自动转成数据库列名
userId    →  user_id
createTime → create_time
```

**为什么是下划线？**
- MySQL/PostgreSQL/Oracle 都推荐列名用下划线命名法
- Java 规范用驼峰命名
- MP 的默认行为正好弥合了这一差异

---

## 三、条件构造器（Wrapper 体系）

### 3.1 Wrapper 继承关系

```
AbstractWrapper<T, String, R>        ← 抽象基类（所有条件方法都在这里）
├── QueryWrapper<T>                   ← 查询条件构造器
├── UpdateWrapper<T>                  ← 更新条件构造器
└── LambdaQueryWrapper<T>             ← Lambda 查询（推荐，编译期检查列名）
    └── LambdaUpdateWrapper<T>        ← Lambda 更新
```

### 3.2 常用条件方法

```java
// ===== 基础条件 =====
QueryWrapper<User> qw = new QueryWrapper<>();
qw.eq("name", "张三")              // WHERE name = '张三'
  .ne("status", 0)                  // AND status != 0
  .gt("age", 18)                    // AND age > 18
  .ge("age", 18)                    // AND age >= 18
  .lt("age", 60)                    // AND age < 60
  .between("age", 18, 60)          // AND age BETWEEN 18 AND 60
  .like("name", "张")               // AND name LIKE '%张%'
  .likeRight("name", "张")          // AND name LIKE '张%'    ← 左精确匹配，走索引
  .notLike("name", "测试")           // AND name NOT LIKE '%测试%'
  .isNull("deleted_at")             // AND deleted_at IS NULL
  .isNotNull("email")               // AND email IS NOT NULL
  .in("role", "admin", "user")      // AND role IN ('admin', 'user')
  .notIn("status", -1, -2)          // AND status NOT IN (-1, -2)
  .inSql("dept_id", "SELECT id FROM dept WHERE level = 1")  // AND dept_id IN (子查询)
  .orderByAsc("age")                // ORDER BY age ASC
  .orderByDesc("create_time")       // ORDER BY create_time DESC
  .groupBy("dept_id")               // GROUP BY dept_id
  .having("COUNT(*) > 5")           // HAVING COUNT(*) > 5
  .select("id", "name", "age")      // 指定查询列（默认 SELECT *）
  .last("LIMIT 10")                 // 拼接到 SQL 末尾（慎用，有 SQL 注入风险）

// ===== Lambda 版本（推荐！列名写错编译报错）=====
LambdaQueryWrapper<User> lqw = new LambdaQueryWrapper<>();
lqw.eq(User::getName, "张三")           // 编译期检查，写错列名直接报错
   .gt(User::getAge, 18)
   .between(User::getCreateTime, start, end)
   .orderByDesc(User::getCreateTime);

// ===== 链式调用（更简洁）=====
List<User> users = userMapper.selectList(
    new LambdaQueryWrapper<User>()
        .eq(User::getStatus, 1)
        .like(User::getName, "张")
        .orderByDesc(User::getCreateTime)
);

// ===== 条件组装（根据参数动态拼接）=====
QueryWrapper<User> qw = new QueryWrapper<>();
qw.eq(StringUtils.isNotBlank(name), "name", name)          // name 不为空才加条件
  .eq(status != null, "status", status)                     // status 不为 null 才加条件
  .between(startAge != null && endAge != null, "age", startAge, endAge);
// 第一个参数是 boolean condition：true 才会拼接到 SQL
```

### 3.3 QueryWrapper vs LambdaQueryWrapper

```
┌─────────────────────────────────────────────────────────────┐
│           QueryWrapper      vs      LambdaQueryWrapper      │
│                                                             │
│  QueryWrapper:                                              │
│    qw.eq("user_name", "张三")                               │
│    - 字符串列名，写错了运行时才报错（SQLException）         │
│    - 重构时不会自动更新（改了字段名，这里的字符串不会变）    │
│                                                             │
│  LambdaQueryWrapper:                                        │
│    lqw.eq(User::getUserName, "张三")                       │
│    - 方法引用，编译期检查，写错直接报错                      │
│    - 重构时 IDE 自动更新                                    │
│                                                             │
│  结论：生产环境用 LambdaQueryWrapper！                       │
└─────────────────────────────────────────────────────────────┘
```

### 3.4 Wrapper 底层原理

```
QueryWrapper 内部维护了一个 List<SqlSegment>（SQL 片段列表）

每次调用条件方法（eq/like/gt...）：
1. 将条件转换为 SqlSegment 对象
2. SqlSegment 包含：列名、操作符（=、LIKE、>、<...）、值、前后缀
3. 存入 segments 列表

最终生成 SQL 时：
1. 遍历 segments
2. 按顺序拼接：WHERE + segment1 + AND + segment2 + ...
3. 处理 AND/OR 嵌套（通过 nested() 方法）
4. 处理条件为 false 的情况（跳过该 segment）
```

```java
// 嵌套条件（括号分组）
LambdaQueryWrapper<User> lqw = new LambdaQueryWrapper<>();
lqw.eq(User::getStatus, 1)
   .and(w -> w.eq(User::getAge, 18).or().eq(User::getLevel, 5));
// 生成：WHERE status = 1 AND (age = 18 OR level = 5)

// 或者
lqw.eq(User::getStatus, 1)
   .nested(w -> w.like(User::getName, "张").ge(User::getAge, 25));
// 生成：WHERE status = 1 AND (name LIKE '%张%' AND age >= 25)
```

---

## 四、Service 层 CRUD（IService）

### 4.1 为什么需要 IService？

```java
// 只用 BaseMapper：每个业务都要写这样的代码
public User getUserById(Long id) {
    User user = userMapper.selectById(id);
    if (user == null) {
        throw new RuntimeException("用户不存在");
    }
    return user;
}

public boolean createUser(User user) {
    if (userMapper.selectCount(
        new LambdaQueryWrapper<User>().eq(User::getEmail, user.getEmail())) > 0) {
        throw new RuntimeException("邮箱已存在");
    }
    return userMapper.insert(user) > 0;
}

// 用 IService：一行搞定
User user = userService.getById(1L);
userService.save(user);
userService.removeById(1L);
userService.updateById(user);
```

### 4.2 IService 接口体系

```
IService<T>                       ← 接口（定义所有 CRUD 方法）
└── ServiceImpl<M extends BaseMapper<T>, T>   ← 实现类（M 是 Mapper，T 是实体）

// 使用方式
public interface UserService extends IService<User> {}

@Service
public class UserServiceImpl extends ServiceImpl<UserMapper, User> implements UserService {}
```

### 4.3 IService 常用方法

```java
// ===== 保存 =====
userService.save(user);                    // 插入一条
userService.saveBatch(userList);           // 批量插入
userService.saveOrUpdate(user);            // 有 id 则更新，无 id 则插入
userService.saveOrUpdateBatch(userList);   // 批量保存或更新

// ===== 删除 =====
userService.removeById(1L);                // 按 id 删除
userService.removeByIds(Arrays.asList(1L, 2L, 3L));  // 按 id 批量删除
userService.remove(new LambdaQueryWrapper<User>().eq(User::getStatus, 0));  // 条件删除

// ===== 更新 =====
userService.updateById(user);              // 按 id 更新
userService.update(user, new LambdaUpdateWrapper<User>()
    .eq(User::getEmail, "old@test.com")
    .set(User::getEmail, "new@test.com")); // 条件更新

// ===== 查询 =====
userService.getById(1L);                   // 按 id 查
userService.listByIds(Arrays.asList(1L, 2L));  // 按 id 批量查
userService.list();                        // 查全部
userService.list(new LambdaQueryWrapper<User>().eq(User::getStatus, 1));  // 条件查
userService.getOne(new LambdaQueryWrapper<User>().eq(User::getEmail, "test@test.com"));  // 查一条

// ===== 分页 =====
Page<User> page = userService.page(new Page<>(1, 10));  // 分页查（需配置分页插件）
Page<User> page = userService.page(new Page<>(1, 10),
    new LambdaQueryWrapper<User>().eq(User::getStatus, 1));  // 条件 + 分页

// ===== 统计 =====
long count = userService.count();                          // 总数
long count = userService.count(new LambdaQueryWrapper<User>().gt(User::getAge, 18));  // 条件统计

// ===== 链式调用（lambdaQuery / lambdaUpdate）=====
List<User> users = userService.lambdaQuery()
    .eq(User::getStatus, 1)
    .like(User::getName, "张")
    .orderByDesc(User::getCreateTime)
    .list();   // 直接返回 List

User user = userService.lambdaQuery()
    .eq(User::getEmail, "test@test.com")
    .one();    // 直接返回单个对象

userService.lambdaUpdate()
    .eq(User::getId, 1L)
    .set(User::getName, "新名字")
    .update(); // 直接执行更新
```

### 4.4 saveOrUpdate 的实现原理

```java
// ServiceImpl.saveOrUpdate() 的核心逻辑
public boolean saveOrUpdate(T entity) {
    if (entity.getId() != null) {
        // 有 ID → 先查是否存在
        T existing = baseMapper.selectById(entity.getId());
        if (existing != null) {
            return updateById(entity) > 0;  // 存在 → 更新
        }
    }
    // 无 ID 或不存在 → 插入
    return insert(entity) > 0;
}
```

**注意**：`saveOrUpdate` 会先执行一次 SELECT，在高并发场景下有性能开销。如果明确知道是插入还是更新，直接用 `save`/`updateById`。

---

## 五、分页插件

### 5.1 配置

```java
@Configuration
public class MyBatisPlusConfig {

    @Bean
    public MybatisPlusInterceptor mybatisPlusInterceptor() {
        MybatisPlusInterceptor interceptor = new MybatisPlusInterceptor();
        // 分页插件（ DbType.MYSQL 指定数据库方言）
        interceptor.addInnerInterceptor(new PaginationInnerInterceptor(DbType.MYSQL));
        return interceptor;
    }
}
```

### 5.2 分页原理

```
执行 userService.page(new Page<>(1, 10), wrapper)

1. MybatisPlusInterceptor 拦截到 Executor.query()
2. 获取 Page 参数：current=1, size=10
3. 自动执行两条 SQL：

   第一条：COUNT（查询总数）
   SELECT COUNT(*) FROM user WHERE status = 1

   第二条：LIMIT（分页查询）
   SELECT * FROM user WHERE status = 1 LIMIT 0, 10

4. 将结果封装到 Page<T> 对象中：
   Page {
       records: [10 条数据],
       total: 150,          // 总记录数
       size: 10,            // 每页大小
       current: 1,          // 当前页
       pages: 15,           // 总页数
   }
```

**不同数据库的分页 SQL**：

| 数据库 | 分页 SQL |
|--------|---------|
| MySQL | `LIMIT offset, size` |
| PostgreSQL | `LIMIT size OFFSET offset` |
| Oracle | `ROWNUM <= end AND ROWNUM > start` |
| SQL Server | `OFFSET offset ROWS FETCH NEXT size ROWS ONLY` |

> MP 通过 `DbType` 参数自动适配不同数据库的分页语法，开发者不需要关心。

### 5.3 分页优化

```java
// 问题：每次分页都要执行 COUNT，大数据量下 COUNT(*) 很慢

// 方案1：不查总数（只要数据，不要分页信息）
Page<User> page = new Page<>(1, 10, false);  // 第三个参数 false = 不查 count
userService.page(page, wrapper);

// 方案2：自定义 count SQL（优化复杂查询的 COUNT）
Page<User> page = userService.page(new Page<>(1, 10), wrapper);
// 复杂场景下，手写 COUNT SQL 比 COUNT(*) 快得多
// MP 也支持自定义 count 查询

// 方案3：游标分页（大数据量推荐，不需要 count）
// 不用 MP 的分页插件，直接用条件：
// 第一页：WHERE id > 0 ORDER BY id LIMIT 10
// 第二页：WHERE id > 上一页最后一条的 id ORDER BY id LIMIT 10
```

---

## 六、代码生成器

### 6.1 为什么需要代码生成？

```
一个典型的后台管理系统：
- 20 张表
- 每张表对应：Entity + Mapper + Service + ServiceImpl + Controller
- 每个文件都有大量样板代码
- 手写 100 个文件，每个 50+ 行 → 5000+ 行样板代码
```

### 6.2 配置与使用

```java
// 代码生成器配置（MP 3.5.x 版本）
public class CodeGenerator {
    public static void main(String[] args) {
        FastAutoGenerator.create("jdbc:mysql://localhost:3306/mydb", "root", "password")
            .globalConfig(builder -> {
                builder.author("zhangsan")          // 作者
                       .outputDir("src/main/java")  // 输出目录
                       .disableOpenDir();           // 不自动打开目录
            })
            .dataSourceConfig(builder -> {
                builder.typeConvertHandler((globalConfig, typeRegistry, metaInfo) -> {
                    // 自定义类型转换
                    return typeRegistry.getColumnType(metaInfo);
                });
            })
            .packageConfig(builder -> {
                builder.parent("com.example")       // 父包名
                       .moduleName("system")        // 模块名
                       .entity("entity")            // Entity 包名
                       .mapper("mapper")            // Mapper 包名
                       .service("service")          // Service 包名
                       .serviceImpl("service.impl") // ServiceImpl 包名
                       .controller("controller")    // Controller 包名
                       .pathInfo(Collections.singletonMap(
                           OutputFile.xml,
                           "src/main/resources/mapper/system"  // Mapper XML 路径
                       ));
            })
            .strategyConfig(builder -> {
                builder.addInclude("sys_user", "sys_role", "sys_menu")  // 表名（可多表）
                       .addTablePrefix("sys_")                          // 过滤表前缀
                       .entityBuilder()
                           .naming(NamingStrategy.underline_to_camel)   // 下划线→驼峰
                           .logicDeleteColumnName("deleted")            // 逻辑删除字段
                           .versionColumnName("version")                // 乐观锁字段
                           .enableLombok()                              // 启用 Lombok
                           .enableChainModel()                          // 启用链式模型
                       .mapperBuilder()
                           .enableMapperAnnotation()                    // Mapper 加 @Mapper
                       .serviceBuilder()
                           .formatServiceFileName("%sService")          // Service 命名
                           .formatServiceImplFileName("%sServiceImpl")  // ServiceImpl 命名
                       .controllerBuilder()
                           .enableRestStyle();                         // Controller 用 @RestController
            })
            .templateEngine(new FreemarkerTemplateEngine())  // 模板引擎（默认 Velocity）
            .execute();
    }
}
```

### 6.3 生成的文件结构

```
com.example.system
├── entity
│   └── User.java                    // @TableName + @TableId + @TableField + Lombok
├── mapper
│   └── UserMapper.java              // extends BaseMapper<User>
└── UserMapper.xml                   // 自定义 SQL 的 XML（初始为空）
├── service
│   └── UserService.java             // extends IService<User>
├── service/impl
│   └── UserServiceImpl.java         // extends ServiceImpl<UserMapper, User>
└── controller
    └── UserController.java          // 自动生成 CRUD 接口

resources/mapper/system
└── UserMapper.xml
```

### 6.4 自定义模板

```java
// 可以自定义 Velocity/FreeMarker 模板，覆盖默认生成逻辑
// 比如在每个 Controller 加上统一的返回格式包装：
// { "code": 200, "message": "success", "data": ... }

// 模板文件放在 resources/templates/ 目录下
// MP 会优先使用自定义模板，找不到再用默认模板
```

---

## 七、逻辑删除

### 7.1 配置

```yaml
# application.yml
mybatis-plus:
  global-config:
    db-config:
      logic-delete-field: deleted    # 全局逻辑删除字段名
      logic-delete-value: 1          # 删除后的值
      logic-not-delete-value: 0      # 未删除的值
```

```java
public class User {
    @TableLogic
    private Integer deleted;   // 逻辑删除标记（0=正常，1=已删除）
}
```

### 7.2 底层原理

```java
// 执行 userMapper.deleteById(1L)

// 实际执行的 SQL：
// 不是 DELETE FROM user WHERE id = 1
// 而是：
UPDATE user SET deleted = 1 WHERE id = 1 AND deleted = 0

// 执行 userMapper.selectById(1L)
// 实际执行的 SQL：
// 不是 SELECT * FROM user WHERE id = 1
// 而是：
SELECT * FROM user WHERE id = 1 AND deleted = 0

// 执行 userMapper.selectList(null)
// 实际执行的 SQL：
SELECT * FROM user WHERE deleted = 0

// 执行 userMapper.updateById(user)
// 实际执行的 SQL：
UPDATE user SET name=?, ... WHERE id = ? AND deleted = 0
```

**本质**：MP 通过拦截 SQL，在所有查询和更新条件中**自动追加** `AND deleted = 0`，在删除操作中将 `DELETE` 改为 `UPDATE ... SET deleted = 1`。

### 7.3 注意事项

```java
// 坑1：唯一索引问题
// 物理删除后，唯一索引自动释放
// 逻辑删除后，已删除的数据还在表中，唯一索引会冲突
// 解决：唯一索引加上 deleted 字段
// UNIQUE KEY uk_email_deleted (email, deleted)

// 坑2：数据量膨胀
// 逻辑删除的数据永远在表中，需要定期清理
// 解决：定时任务归档或物理删除已标记超过 N 天的数据

// 坑3：关联查询需要手动加条件
// JOIN 查询时，MP 不会自动给关联表加 deleted = 0
// 需要自己写 SQL 时加上条件
```

---

## 八、自动填充

### 8.1 配置

```java
@Component
public class MyMetaObjectHandler implements MetaObjectHandler {

    @Override
    public void insertFill(MetaObject metaObject) {
        // 插入时自动填充
        this.strictInsertFill(metaObject, "createTime", LocalDateTime.class, LocalDateTime.now());
        this.strictInsertFill(metaObject, "updateTime", LocalDateTime.class, LocalDateTime.now());
        this.strictInsertFill(metaObject, "createBy", Long.class, getCurrentUserId());
    }

    @Override
    public void updateFill(MetaObject metaObject) {
        // 更新时自动填充
        this.strictUpdateFill(metaObject, "updateTime", LocalDateTime.class, LocalDateTime.now());
        this.strictUpdateFill(metaObject, "updateBy", Long.class, getCurrentUserId());
    }
}
```

```java
public class BaseEntity {
    @TableField(fill = FieldFill.INSERT)
    private LocalDateTime createTime;

    @TableField(fill = FieldFill.INSERT_UPDATE)
    private LocalDateTime updateTime;

    @TableField(fill = FieldFill.INSERT)
    private Long createBy;

    @TableField(fill = FieldFill.INSERT_UPDATE)
    private Long updateBy;
}
```

### 8.2 strictInsertFill vs fill

```java
// strictInsertFill：如果字段已有值（不为 null），则不覆盖
// fill：无条件覆盖（即使字段已有值）

this.strictInsertFill(metaObject, "createTime", LocalDateTime.class, LocalDateTime.now());
// 用户手动设置了 createTime → 不覆盖
// 用户没设置 createTime → 自动填充

this.fill(metaObject, "updateTime");
// 无条件填充（推荐用于 updateTime，每次更新都必须是最新时间）
```

---

## 九、乐观锁

### 9.1 配置

```java
@Configuration
public class MyBatisPlusConfig {
    @Bean
    public MybatisPlusInterceptor mybatisPlusInterceptor() {
        MybatisPlusInterceptor interceptor = new MybatisPlusInterceptor();
        // 乐观锁插件（必须在分页插件之前！）
        interceptor.addInnerInterceptor(new OptimisticLockerInnerInterceptor());
        // 分页插件
        interceptor.addInnerInterceptor(new PaginationInnerInterceptor(DbType.MYSQL));
        return interceptor;
    }
}
```

```java
public class User {
    @Version
    private Integer version;  // 乐观锁版本号
}
```

### 9.2 底层原理

```
// 1. 先查（获取当前版本号）
User user = userMapper.selectById(1L);
// user.version = 3

// 2. 修改业务字段
user.setName("新名字");

// 3. 更新
userMapper.updateById(user);

// 实际执行的 SQL：
UPDATE user SET name = '新名字', version = 4
WHERE id = 1 AND version = 3
                                      ↑ 加上版本号条件！

// 返回影响行数：
// 1 → 更新成功（版本号匹配）
// 0 → 更新失败（版本号已被其他线程修改，并发冲突）
```

**为什么不用悲观锁（SELECT ... FOR UPDATE）？**
- 悲观锁在查询时就加锁，其他事务等待 → 吞吐量低
- 乐观锁在更新时检查版本号，不加读锁 → 适合读多写少的场景
- 大多数业务场景都是读多写少，乐观锁性能更好

```
┌─────────────────────────────────────────────────────────────┐
│                  乐观锁 vs 悲观锁                            │
│                                                             │
│  乐观锁（@Version）：                                       │
│    - 不加读锁，并发度高                                     │
│    - 更新时检查版本号，冲突时返回 0 行                       │
│    - 适合：读多写少、冲突概率低                              │
│                                                             │
│  悲观锁（SELECT ... FOR UPDATE）：                          │
│    - 查询时就加行锁，其他事务阻塞                            │
│    - 不会冲突，但吞吐量低                                   │
│    - 适合：写多、冲突概率高（如库存扣减）                    │
│                                                             │
│  库存扣减场景 → 用悲观锁或 Redis 原子操作                   │
│  用户信息更新 → 用乐观锁                                    │
└─────────────────────────────────────────────────────────────┘
```

---

## 十、插件机制（MybatisPlusInterceptor）

### 10.1 InnerInterceptor 体系

```
MybatisPlusInterceptor（外层，管理多个 InnerInterceptor）
├── PaginationInnerInterceptor        ← 分页插件
├── OptimisticLockerInnerInterceptor   ← 乐观锁插件
├── BlockAttackInnerInterceptor        ← 防全表更新/删除插件
└── IllegalSQLInnerInterceptor         ← 非法 SQL 检查插件
```

### 10.2 防全表更新/删除

```java
// 开启防全表操作插件
interceptor.addInnerInterceptor(new BlockAttackInnerInterceptor());

// 效果：
userService.update(new User(), null);     // ❌ 抛异常！全表更新被阻止
userService.remove(new QueryWrapper<>()); // ❌ 抛异常！全表删除被阻止

// 原因：没有 WHERE 条件的 UPDATE/DELETE 太危险，误操作可能导致数据全丢
// 开发阶段建议开启，上线后可以关闭（或仅在测试环境开启）
```

---

## 十一、MP 与原生 MyBatis 的关系

```
┌─────────────────────────────────────────────────────────────┐
│               MyBatis-Plus vs 原生 MyBatis                  │
│                                                             │
│  MP 不替代 MyBatis，而是在 MyBatis 之上加了增强层：          │
│                                                             │
│  ┌──────────────────────────┐                               │
│  │   MyBatis-Plus 增强层     │                               │
│  │   - BaseMapper CRUD       │                               │
│  │   - 条件构造器 Wrapper     │                               │
│  │   - 分页插件              │                               │
│  │   - 代码生成器            │                               │
│  │   - 逻辑删除/自动填充     │                               │
│  └──────────┬───────────────┘                               │
│             │ 基于                                          │
│  ┌──────────▼───────────────┐                               │
│  │   MyBatis 核心            │                               │
│  │   - SqlSession            │                               │
│  │   - Executor              │                               │
│  │   - MappedStatement       │                               │
│  │   - 动态 SQL              │                               │
│  │   - 一级/二级缓存         │                               │
│  └──────────────────────────┘                               │
│                                                             │
│  复杂 SQL → 写在 XML 里（MyBatis 原生方式完全可用）         │
│  单表 CRUD → 直接用 BaseMapper（MP 增强）                   │
│  多条件查询 → 用 Wrapper（比 XML 动态 SQL 简洁）            │
│                                                             │
│  两者可以无缝混用！                                          │
└─────────────────────────────────────────────────────────────┘
```

---

## 面试话术总结

1. **MyBatis-Plus 的核心功能有哪些？**
   "MP 是 MyBatis 的增强工具，核心功能：BaseMapper 提供单表 CRUD（不需要写 XML）、条件构造器（Wrapper，支持 Lambda 版本的编译期检查）、分页插件（自动适配不同数据库方言）、代码生成器（Entity/Mapper/Service/Controller 全套生成）、逻辑删除（DELETE 自动改为 UPDATE）、自动填充（create_time/update_time）、乐观锁（@Version）。"

2. **BaseMapper 的 CRUD 是怎么实现的？**
   "应用启动时，MP 的 MybatisMapperRegistry 会遍历 BaseMapper 中定义的方法，通过 ISqlInjector（默认 DefaultSqlInjector）为每个方法生成对应的 MappedStatement（包含动态 SQL）。这些 MappedStatement 注册到 MyBatis 的 Configuration 中。运行时调用 Mapper 方法，和普通 MyBatis 调用完全一致，只是 SQL 是 MP 自动生成的。"

3. **条件构造器 QueryWrapper 和 LambdaQueryWrapper 有什么区别？**
   "QueryWrapper 用字符串列名（`eq("name", "张三")`），写错列名运行时才报错，重构时不自动更新。LambdaQueryWrapper 用方法引用（`eq(User::getName, "张三")`），编译期检查列名，重构时 IDE 自动更新。生产环境推荐 LambdaQueryWrapper。"

4. **逻辑删除是怎么实现的？**
   "在实体类的逻辑删除字段上加 @TableLogic 注解，配置逻辑删除值和未删除值（比如 1 和 0）。MP 通过拦截 SQL 实现：查询时自动追加 WHERE deleted = 0，删除时将 DELETE 改为 UPDATE SET deleted = 1。开发者代码不需要任何改动。注意事项：唯一索引要加上 deleted 字段，定时清理已删除数据防止表膨胀。"

5. **乐观锁的原理？**
   "实体类字段加 @Version 注解。查询时获取版本号，更新时自动在 WHERE 条件中加上版本号检查（`WHERE id = ? AND version = ?`），同时 SET version = version + 1。返回 0 行表示版本号冲突（其他线程已修改），需要重试或提示用户。乐观锁插件必须在分页插件之前注册。适合读多写少场景，库存扣减场景不适合（应该用悲观锁或 Redis）。"

6. **分页插件的原理？**
   "通过 MybatisPlusInterceptor 拦截 Executor.query()，将 Page 参数解析后自动拼接分页 SQL 和 COUNT SQL。先执行 COUNT 查总数，再执行 LIMIT 分页查询，结果封装到 Page 对象中。通过 DbType 参数适配不同数据库的分页语法。如果不需要总数，Page 构造函数第三个参数传 false 可以跳过 COUNT 查询。"

---

*MyBatis-Plus 解决的是「90% 的重复劳动」问题。理解 BaseMapper 的 SQL 注入原理，就知道它和原生 MyBatis 不是替代关系，而是增强关系——复杂 SQL 仍然用 XML，单表 CRUD 用 MP。*
