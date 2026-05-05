# 动态 SQL 解析原理

## 这个问题为什么存在？

> 你写了 `<if test="name != null">AND name = #{name}</if>`，MyBatis 是怎么判断该不该拼接这段 SQL 的？

传统 JDBC：用 StringBuilder 拼 SQL，容易有 SQL 注入风险，且代码丑陋。

MyBatis 动态 SQL：用 **标签 + OGNL 表达式** 描述条件，框架自动拼出最终 SQL。

---

## 它是怎么解决问题的？

### 核心机制：基于标签的 SQL 片段组装

```
XML 中的动态 SQL 标签
  → <if/>       条件判断（最常用）
  → <choose/>   分支（类似 switch）
  → <when/>     choose 的分支
  → <otherwise/> choose 的默认分支
  → <trim/>      去除多余的前缀/后缀（如 WHERE 后的 AND/OR）
  → <where/>     智能 WHERE（自动加 WHERE，自动去掉第一个 AND/OR）
  → <set/>       智能 SET（自动去掉最后一个逗号）
  → <foreach/>   循环（IN 查询、批量插入）
  → <sql/> + <include/>  SQL 片段复用
```

**解析时机**：XML 加载时，MyBatis 把每个 `<select/>` 等标签内的内容解析成 **SqlNode 树**（`MappedStatement.sqlSource.rootSqlNode`）。

**执行时机**：每次调用 Mapper 方法时，根据入参计算 OGNL 表达式，组装出最终 `BoundSql`（包含真实 SQL 字符串）。

### 源码关键路径

```java
// XMLLanguageDriver.createSqlSource() — XML 加载时调用
public SqlSource createSqlSource(Configuration configuration, XNode script, Class<?> parameterType) {
    XMLScriptBuilder builder = new XMLScriptBuilder(configuration, script, parameterType);
    return builder.parseScriptNode();   // ← 解析生成 SqlNode 树
}

// XMLScriptBuilder.parseScriptNode()
public SqlSource parseScriptNode() {
    List<SqlNode> contents = parseDynamicTags(context);  // 递归解析子节点
    MixedSqlNode rootSqlNode = new MixedSqlNode(contents);
    if (isDynamic) {
        return new DynamicSqlSource(configuration, rootSqlNode);
    } else {
        return new RawSqlSource(configuration, rootSqlNode, parameterType);
    }
}
// isDynamic=true 的条件：包含任何动态标签（if/where/foreach...）或 ${}

// DynamicSqlSource.getBoundSql() — 每次执行时调用
public BoundSql getBoundSql(Object parameterObject) {
    DynamicContext context = new DynamicContext(configuration, parameterObject);
    // 遍历 SqlNode 树，根据入参计算每个节点的 SQL 片段
    rootSqlNode.apply(context);   // ← 递归，if 不满足则不 append
    String sql = context.getSql(); // 组装完成的最终 SQL（还包含 #{}/${}）
    // 后续：解析 #{}/${}，生成 PreparedStatement 需要的 SQL
}
```

**关键接口**：`SqlNode`（所有动态标签都实现这个接口）

```java
public interface SqlNode {
    boolean apply(DynamicContext context);  // 返回 false 表示该节点未贡献 SQL
}

// IfSqlNode — <if test="..."> 的实现
public class IfSqlNode implements SqlNode {
    private final ExpressionEvaluator evaluator;
    private final String test;  // OGNL 表达式字符串
    private final SqlNode contents;

    @Override
    public boolean apply(DynamicContext context) {
        // 用 OGNL 解析 test 表达式
        if (evaluator.evaluateBoolean(test, context.getBindings())) {
            contents.apply(context);  // 条件成立，拼接子节点 SQL
            return true;
        }
        return false;
    }
}

// ForEachSqlNode — <foreach> 的实现
public class ForEachSqlNode implements SqlNode {
    @Override
    public boolean apply(DynamicContext context) {
        // 1. 从入参中取出集合/数组
        // 2. 循环，每次循环：
        //    → 把当前元素绑定到 context（供 #{}/${} 引用）
        //    → 调用 contents.apply(context) 拼接 SQL 片段
        // 3. 处理逗号分隔（第一个不加逗号）
    }
}
```


### 动态 SQL 解析流程图

```
XML 加载时
  MappedStatement.sqlSource
    → DynamicSqlSource（isDynamic=true）
        → rootSqlNode: MixedSqlNode
            → [IfSqlNode, TextSqlNode, ForEachSqlNode, ...]

每次方法调用时
  DynamicSqlSource.getBoundSql(parameterObject)
    → DynamicContext 创建（绑定入参）
    → rootSqlNode.apply(context)   ← 递归计算每个 SqlNode
        → IfSqlNode：OGNL 评估 test → true 则拼接子节点
        → ForEachSqlNode：循环绑定每个元素 → 拼接
        → TextSqlNode：直接拼接 SQL 文本
    → context.getSql() → 得到「半成品 SQL」（还有 #{}/${}）
    → SqlSourceParser.parse() → 解析 #{}/${}
        → #{} → ParameterMapping + ? 占位符
        → ${} → 直接字符串替换（有注入风险！）
    → 返回 BoundSql（最终 SQL + ParameterMapping 列表）
```

---

## 它和相似方案的本质区别是什么？

| 方案 | SQL 组装方式 | SQL 注入风险 | 复杂度 |
|------|-------------|------------|--------|
| **MyBatis 动态 SQL** | XML 标签 + OGNL | `${}` 有风险，`#{}` 安全 | 中 |
| **字符串拼接（JDBC）** | 手写 if-else 拼接 | 高（直接拼接参数） | 高（代码丑） |
| **JPA Criteria API** | 编程式 API 组装 | 无（自动参数化） | 高（API 冗长） |
| **QueryDSL** | 类型安全的流式 API | 无 | 低（需学习） |

**本质区别**：MyBatis 动态 SQL 是在 **XML 中声明 SQL 模板**，由框架在运行时根据参数「渲染」出最终 SQL（类似模板引擎 Thymeleaf 渲染 HTML）。

---

## 正确使用方式

### 常用标签示例

```xml
<!-- 智能 WHERE：自动加 WHERE 关键字，自动去除第一个 AND/OR -->
<select id="findUsers" resultType="User">
    SELECT * FROM user
    <where>
        <if test="name != null">AND name = #{name}</if>
        <if test="age != null">AND age = #{age}</if>
        <if test="statusList != null">
            AND status IN
            <foreach collection="statusList" item="s" open="(" separator="," close=")">
                #{s}
            </foreach>
        </if>
    </where>
</select>

<!-- 智能 SET：自动去除最后一个逗号 -->
<update id="updateUser">
    UPDATE user
    <set>
        <if test="name != null">name = #{name},</if>
        <if test="age != null">age = #{age},</if>
    </set>
    WHERE id = #{id}
</update>

<!-- choose/when/otherwise：互斥分支（类似 switch） -->
<select id="findUsers2" resultType="User">
    SELECT * FROM user
    <where>
        <choose>
            <when test="name != null">AND name = #{name}</when>
            <when test="age != null">AND age = #{age}</when>
            <otherwise>AND status = 'ACTIVE'</otherwise>
        </choose>
    </where>
</select>

<!-- trim：更灵活的 where/set 替代 -->
<select id="findUsers3" resultType="User">
    SELECT * FROM user
    <trim prefix="WHERE" prefixOverrides="AND | OR" suffixOverrides=",">
        <if test="name != null">AND name = #{name}</if>
    </trim>
</select>
```

### `${}` vs `#{}`（非常重要！）

```xml
<!-- ✅ 安全：预编译，? 占位符 -->
SELECT * FROM user WHERE name = #{name}
→ 实际：PreparedStatement.setString(1, name)

<!-- ❌ 危险：字符串直接替换，有 SQL 注入风险 -->
SELECT * FROM user WHERE name = '${name}'
→ 实际：字符串拼接，如果 name = "xxx' OR '1'='1" 就注入成功

<!-- ✅ ${} 的正确使用场景：动态表名/排序字段 -->
SELECT * FROM ${tableName} ORDER BY ${sortField} ${sortOrder}
→ 这些场景只能 ${}，但要确保 tableName/sortField 是白名单值（不能来自用户输入）
```

---

## 边界情况和坑

### 坑1：`<if test="xxx">` 中数值类型的判断

```xml
<!-- ❌ 错误：Integer 类型用 != '' 判断 -->
<if test="age != ''">   <!-- 永远为 true！Integer 和空字符串永远不相等 -->

<!-- ✅ 正确 -->
<if test="age != null">
<if test="age != null and age > 0">
```

### 坑2：`${}` 的 SQL 注入

```java
// 用户输入：tableName = "user; DROP TABLE user;"
// XML 中：SELECT * FROM ${tableName}
// 拼接后：SELECT * FROM user; DROP TABLE user;  ← 灾难！

// 正确做法：白名单校验
public String getTableName(String input) {
    if (!Arrays.asList("user", "order", "product").contains(input)) {
        throw new IllegalArgumentException("非法表名");
    }
    return input;  // 确认安全后才传入 ${}
}
```

### 坑3：`foreach` 的 `collection` 属性取值

```xml
<!-- Java 接口 -->
List<User> findByIds(@Param("ids") List<Integer> ids);

<!-- XML：collection 必须是 @Param 的值，或者默认名 -->
<foreach collection="ids" item="id" ...>   <!-- ✅ 因为 @Param("ids") -->
<foreach collection="list" item="id" ...>   <!-- ✅ 如果没有 @Param，List 默认名是 list -->
<foreach collection="array" item="id" ...>  <!-- ✅ 数组默认名是 array -->
```

### 坑4：`where` 标签去除 `AND` 的规则

```xml
<where>
    <if test="name != null">name = #{name}</if>  <!-- 没有 AND 开头 -->
    <if test="age != null">AND age = #{age}</if> <!-- 有 AND 开头 -->
</where>
<!-- 最终 SQL：
     如果 name 有值、age 无值 → WHERE name = ?
     如果 name 无值、age 有值 → WHERE age = ?  （自动去掉了前面的 AND）
     如果都有 → WHERE name = ? AND age = ?        -->
```

### 坑5：OGNL 表达式访问字段的方式

```xml
<!-- Java 入参是一个对象 -->
<if test="user.name != null">   <!-- ✅ OGNL：直接写字段名（实际调用 getName()） -->
<if test="user.getName() != null">  <!-- ✅ 也可以写方法调用 -->
<if test="user['name'] != null">   <!-- ✅ Map 取值风格 -->

<!-- 坑：boolean 类型的字段，isDeleted，OGNL 中写 deleted（去掉 is 前缀） -->
<if test="deleted">   <!-- ✅ 不是 isDeleted -->
```

