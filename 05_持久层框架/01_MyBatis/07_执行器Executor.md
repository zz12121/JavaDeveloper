# 执行器 Executor

## 这个问题为什么存在？

> `SqlSession` 调了 `selectList()`，最后是谁真正去执行 JDBC 的 `PreparedStatement`？

**Executor** 是 MyBatis 的「执行层」，位于 `SqlSession` 和 JDBC 之间，负责：
1. 缓存管理（一级缓存）
2. 事务管理（提交/回滚）
3. SQL 执行（调用 `StatementHandler`）
4. 批量操作（BatchExecutor）

---

## 它是怎么解决问题的？

### 三种 Executor 类型

```
Executor 接口
  ├── BaseExecutor（抽象基类，实现一级缓存、事务管理）
  │     ├── SimpleExecutor（默认）每次创建新 Statement
  │     ├── ReuseExecutor   复用 Statement（同 SQL 复用）
  │     └── BatchExecutor   批量执行（攒一批再执行）
  └── CachingExecutor（二级缓存代理，包装上面的 Executor）
```

### 创建入口（Configuration）

```java
// Configuration.java
public Executor newExecutor(Transaction transaction, ExecutorType executorType) {
    executorType = executorType == null ? defaultExecutorType : executorType;
    Executor executor;
    if (ExecutorType.BATCH == executorType) {
        executor = new BatchExecutor(this, transaction);
    } else if (ExecutorType.REUSE == executorType) {
        executor = new ReuseExecutor(this, transaction);
    } else {
        executor = new SimpleExecutor(this, transaction);  // ← 默认
    }
    // 如果开启了二级缓存，用 CachingExecutor 包装
    if (cacheEnabled) {
        executor = new CachingExecutor(executor);
    }
    // 插件拦截（后面会讲）
    executor = (Executor) interceptorChain.pluginAll(executor);
    return executor;
}
```

### SimpleExecutor（默认）

```java
// SimpleExecutor.java
@Override
public <E> List<E> doQuery(MappedStatement ms, Object parameter, ...) {
    Statement stmt = null;
    try {
        Configuration configuration = ms.getConfiguration();
        StatementHandler handler = configuration.newStatementHandler(...);
        // 每次都创建新的 Statement
        stmt = prepareStatement(handler, ms.getStatementLog());
        return handler.query(stmt, resultHandler);
    } finally {
        closeStatement(stmt);  // 每次都关闭 Statement
    }
}
```

### ReuseExecutor（复用 Statement）

```java
// ReuseExecutor.java
// 核心：用一个 Map 缓存 SQL → Statement 的映射
private final Map<String, Statement> statementMap = new HashMap<>();

@Override
public <E> List<E> doQuery(MappedStatement ms, Object parameter, ...) {
    Statement stmt = null;
    String sql = getSql(boundSql);  // ← 用 SQL 字符串作为 key
    if (statementMap.containsKey(sql)) {
        stmt = statementMap.get(sql);  // ← 复用已有的 Statement
    } else {
        stmt = prepareStatement(handler, ms.getStatementLog());
        statementMap.put(sql, stmt);  // ← 缓存起来
    }
    return handler.query(stmt, resultHandler);
}
// 注意：ReuseExecutor 不会自动关闭 Statement，需要在事务提交/回滚时批量关闭
```

### BatchExecutor（批量执行）

```java
// BatchExecutor.java
// 核心：把 INSERT/UPDATE/DELETE 攒起来，最后一批执行
private final List<Statement> statementList = new ArrayList<>();
private final List<BatchResult> batchResultList = new ArrayList<>();

@Override
public int doUpdate(MappedStatement ms, Object parameter) {
    // 1. 准备 Statement
    Statement stmt = prepareStatement(handler, ms.getStatementLog());
    // 2. 添加到批处理
    stmt.addBatch();   // ← 关键：只 addBatch，不 executeBatch
    return BATCH_UPDATE_RETURN_VALUE;  // 返回 -1（还不知道影响行数）
}

// 执行批处理（需要手动调用 SqlSession.flushStatements() 或 commit()）
@Override
public List<BatchResult> doFlushStatements(boolean isRollback) {
    for (Statement stmt : statementList) {
        stmt.executeBatch();  // ← 真正执行批处理
    }
    return batchResultList;
}
```

---

## 深入原理

```
SqlSession.selectList()
  → CachingExecutor.query()    （如果有二级缓存，先查缓存）
    → delegate.query()         （BaseExecutor.query()）
      → 查一级缓存（localCache）
      → 未命中 → doQuery()
        → SimpleExecutor.doQuery()
          → StatementHandler.prepare()  准备 Statement
          → StatementHandler.query()    执行 SQL
          → ResultSetHandler.handleResultSets()  处理结果集
```


### 它和相似方案的本质区别是什么？

| 对比维度 | SimpleExecutor | ReuseExecutor | BatchExecutor | Spring JDBC Template |
|---------|----------------|----------------|---------------|-------------------|
| Statement 创建 | 每次新建 | 同 SQL 复用 | 攒批执行 | 每次新建 |
| 性能（重复 SQL） | 低 | 中 | 高（批量） | 低 |
| 内存占用 | 低 | 中（缓存 Statement） | 高（攒批） | 低 |
| 适用场景 | 通用 | 重复查询多 | 批量写入 | 通用 |

**本质区别**：`SimpleExecutor` 是「每次都新建」，`ReuseExecutor` 是「同 SQL 复用 Statement」，`BatchExecutor` 是「攒批执行」。

---

## 正确使用方式

### 指定 Executor 类型

```java
// 方式一：打开 SqlSession 时指定
SqlSession session = sqlSessionFactory.openSession(ExecutorType.BATCH);

// 方式二：Spring 整合后（在 SqlSessionTemplate 中配置）
@Bean
public SqlSessionTemplate sqlSessionTemplate(SqlSessionFactory sqlSessionFactory) {
    return new SqlSessionTemplate(sqlSessionFactory, ExecutorType.BATCH);
}
```

### BatchExecutor 的正确用法

```java
try (SqlSession session = sqlSessionFactory.openSession(ExecutorType.BATCH)) {
    UserMapper mapper = session.getMapper(UserMapper.class);
    for (int i = 0; i < 1000; i++) {
        mapper.insert(user);  // ← 只 addBatch()，不执行
    }
    session.flushStatements();  // ← 真正执行批处理
    session.commit();          // ← 提交事务
}
```


### Executor 选择建议

| 场景 | 推荐 Executor | 原因 |
|------|--------------|------|
| 通用查询/更新 | SimpleExecutor（默认） | 简单可靠 |
| 同一 SQL 重复执行多次 | ReuseExecutor | 减少 Statement 创建开销 |
| 批量插入/更新（>100条） | BatchExecutor | 显著减少网络 IO |
| 有二级缓存需求 | CachingExecutor（自动包装） | 需要配置 <cache/> |

---

## 边界情况和坑

### 坑1：BatchExecutor 必须手动 flush

```
❌ 错误：以为 insert() 后就执行了
  mapper.insert(user);  // 只 addBatch()
  // 如果这里程序崩溃 → 数据库中没有任何记录！

✅ 正确：
  mapper.insert(user);
  session.flushStatements();  // 必须手动 flush
```

### 坑2：ReuseExecutor 的 Statement 泄漏

```
ReuseExecutor 缓存了 Statement，但不会自动关闭
必须在事务提交/回滚时关闭所有缓存的 Statement

解决：SqlSession.close() 时会调用 doFlushStatements(isRollback=true)
       → 关闭所有缓存的 Statement
```

### 坑3：Executor 类型和 Spring 事务的关系

```
Spring 整合后，SqlSessionTemplate 默认用 ExecutorType.SIMPLE
如果想用 BATCH，需要手动指定：

@Autowired
private SqlSessionTemplate batchSqlSessionTemplate;  // 配置为 BATCH 的模板

public void batchInsert() {
    batchSqlSessionTemplate.getMapper(UserMapper.class).insert(...);
    batchSqlSessionTemplate.flushStatements();
}
```

### 坑4：CachingExecutor 的二级缓存不生效

```
原因：CachingExecutor 只在 <cache/> 开启时才生效
如果 Mapper 没有配置 <cache/>，CachingExecutor 直接委托给被包装的 Executor

解决：在 Mapper XML 中添加 <cache/>
```

