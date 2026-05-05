# Spring事务管理

## 这个问题为什么存在？

> 没有事务管理时，每个 DAO 自己管连接、自己 commit/rollback → 业务方法跨多个 DAO 时，无法保证原子性。

**没有事务的典型问题**：

```java
// ❌ 没有事务管理
public void transfer(String from, String to, BigDecimal amount) {
    accountDao.deduct(from, amount);   // 扣款成功
    accountDao.add(to, amount);        // 加款失败（异常）
    // 结果：钱扣了，没加上 → 数据不一致
}
```

> 如果每个 DAO 自己拿连接，它们是**不同的数据库连接**，无法用数据库事务保证原子性。  
> 事务管理的本质：**把多个 DAO 的操作绑到同一个数据库连接/事务里**。

---

## 它是怎么解决问题的？

### Spring 事务的抽象层

Spring 不直接操作数据库事务，而是抽象了一层 `PlatformTransactionManager`：

```
Spring 事务抽象层
┌─────────────────────────────────────────────┐
│ 业务代码（@Transactional）                   │
├─────────────────────────────────────────────┤
│ TransactionInterceptor（AOP 拦截）          │
│   ├─ 获取事务（TransactionManager）          │
│   ├─ 调用业务方法                           │
│   ├─ 正常返回 → commit                      │
│   └─ 抛异常 → rollback（按规则判断）         │
├─────────────────────────────────────────────┤
│ PlatformTransactionManager（抽象接口）        │
│   ├─ DataSourceTransactionManager（JDBC）   │
│   ├─ JpaTransactionManager（JPA）          │
│   ├─ HibernateTransactionManager           │
│   └─ ReactiveTransactionManager（响应式）    │
├─────────────────────────────────────────────┤
│ 底层资源                                     │
│   └─ DataSource → Connection → JDBC 事务    │
└─────────────────────────────────────────────┘
```

**关键设计**：Spring 事务不依赖任何具体框架，通过 `TransactionManager` 适配各种持久层。

---

### @Transactional 的工作原理（源码路径）

```java
// 1. 解析 @Transactional 注解
// Spring 在启动时扫描所有 Bean，找到 @Transactional 方法
// → 创建代理对象（JDK 或 CGLIB）

// 2. TransactionInterceptor.intercept()（AOP 拦截）
public Object invoke(MethodInvocation invocation) {
    // 2.1 获取事务属性（从注解解析）
    TransactionAttribute txAttr = getTransactionAttribute(method, targetClass);

    // 2.2 获取事务管理器
    PlatformTransactionManager tm = determineTransactionManager(txAttr);

    // 2.3 开启事务（获取连接，关闭自动提交）
    TransactionInfo txInfo = createTransactionIfNecessary(tm, txAttr);

    try {
        Object retVal = invocation.proceed();  // 调用业务方法
        commitTransactionAfterReturning(txInfo);  // 正常 → 提交
        return retVal;
    } catch (Throwable ex) {
        completeTransactionAfterThrowing(txInfo, ex);  // 异常 → 回滚
        throw ex;
    } finally {
        cleanupTransactionInfo(txInfo);  // 恢复现场
    }
}
```

**事务开启的核心**：`getConnection()` 时，Spring 把连接的 `autoCommit` 设为 `false`，后续所有操作都在同一个连接上执行。

---

### 事务传播行为（7 种）

| 传播行为 | 含义 | 适用场景 |
|----------|------|----------|
| **REQUIRED**（默认） | 有事务就加入，没有就新建 | 大部分业务方法 |
| **REQUIRES_NEW** | 挂起当前事务，新建事务 | 日志、审计（必须独立提交） |
| **SUPPORTS** | 有事务就加入，没有就以非事务执行 | 查询方法（可选事务） |
| **NOT_SUPPORTED** | 以非事务执行，挂起当前事务 | 不需要事务的操作 |
| **MANDATORY** | 必须在事务中执行，否则抛异常 | 强制调用方提供事务 |
| **NEVER** | 不能以事务执行，否则抛异常 | 严格禁止事务 |
| **NESTED** | 嵌套事务（保存点） | 部分回滚 |

**NESTED vs REQUIRES_NEW 的本质区别**：

```
REQUIRES_NEW：
  事务A → 挂起 → 事务B（全新连接）→ 提交B → 恢复A
  → A 和 B 完全独立，B 提交后 A 回滚不影响 B

NESTED（JDBC Savepoint）：
  事务A → 创建保存点 → 执行嵌套操作 → 嵌套失败 → 回滚到保存点
  → 嵌套操作是事务 A 的一部分，外层回滚会连嵌套一起回滚
```

---

### 事务隔离级别

| 隔离级别 | 脏读 | 不可重复读 | 幻读 |
|----------|------|------------|------|
| READ_UNCOMMITTED | ❌ | ❌ | ❌ |
| READ_COMMITTED | ✅ | ❌ | ❌ |
| REPEATABLE_READ（MySQL 默认） | ✅ | ✅ | ❌ |
| SERIALIZABLE | ✅ | ✅ | ✅ |

> Spring 的隔离级别**委托给数据库**，如果数据库不支持（如 Oracle 不支持 REPEATABLE_READ），设置无效。

---

### 核心源码：DataSourceTransactionManager

```java
// 开启事务
protected void doBegin(Object transaction, TransactionDefinition definition) {
    DataSourceTransactionObject txObject = (DataSourceTransactionObject) transaction;

    // 1. 获取数据库连接（从 DataSource）
    Connection con = obtainConnection();

    // 2. 记录原始 autoCommit 值
    boolean originalAutoCommit = con.getAutoCommit();

    // 3. 关闭自动提交（核心！）
    if (originalAutoCommit) {
        con.setAutoCommit(false);
    }

    // 4. 把连接绑定到当前线程（ThreadLocal）
    TransactionSynchronizationManager.bindResource(dataSource, con);
}

// 提交事务
protected void doCommit(DefaultTransactionStatus status) {
    Connection con = status.getConnection();
    con.commit();  // 直接调用 JDBC 的 commit
}
```

**ThreadLocal 绑定连接**是 Spring 事务的核心机制：同一个线程中的多个 DAO 操作，拿到的是**同一个数据库连接**。

---

## 它和相似方案的本质区别是什么？

### Spring 事务 vs 数据库事务

| | Spring 事务 | 数据库事务（JDBC） |
|---|---|---|
| 抽象层级 | 应用层（AOP 拦截） | 驱动层（Connection.commit） |
| 传播行为 | 支持（7 种） | 不支持 |
| 声明式 | 支持（@Transactional） | 不支持（硬编码） |
| 跨数据源 | 不支持（需要分布式事务） | 单连接内有效 |

**Spring 事务的本质**：对 JDBC 事务的封装 + AOP 拦截，核心是**ThreadLocal 绑定连接**。

### 声明式事务 vs 编程式事务

```java
// ✅ 声明式（推荐）：注解驱动，非侵入
@Transactional
public void transfer() { ... }

// ⚠️ 编程式：需要手动管理，但更灵活
@Autowired TransactionTemplate tt;
tt.execute(status -> {
    // 业务逻辑
    return null;
});
```

**声明式的缺点**：自调用失效（AOP 代理问题），编程式可以绕过。

---

## 正确使用方式

### 1. 正确设置 rollbackFor

```java
// ❌ 错误：默认只回滚 RuntimeException 和 Error
@Transactional
public void create() throws Exception {
    dao.insert();
    throw new Exception();  // 受检异常，不回滚！
}

// ✅ 正确：指定回滚规则
@Transactional(rollbackFor = Exception.class)
public void create() throws Exception {
    dao.insert();
    throw new Exception();  // 现在会回滚
}
```

> Spring 默认：**RuntimeException + Error 才回滚**，受检异常（Exception）不回滚。  
> 这是很多人踩过的坑。

### 2. 正确设置隔离级别和传播行为

```java
// 查询方法：只读，提高性能
@Transactional(readOnly = true, propagation = Propagation.SUPPORTS)
public User findById(Long id) { ... }

// 写方法：需要事务
@Transactional(propagation = Propagation.REQUIRED, rollbackFor = Exception.class)
public void create(User user) { ... }

// 审计日志：无论主事务是否回滚，都要记录
@Transactional(propagation = Propagation.REQUIRES_NEW)
public void audit(String action) { ... }
```

### 3. 正确设置超时

```java
@Transactional(timeout = 30)  // 30 秒超时
public void longRunningTask() { ... }
```

> `timeout` 是**事务超时**（从开启事务算起），不是查询超时。  
> 需要在连接上设置 `queryTimeout` 才对 SQL 生效。

---

## 边界情况和坑

### 1. 自调用导致事务失效（最高频）

```java
@Service
public class UserService {
    public void createUser() {
        this.insert();  // ❌ 自调用，不走代理，@Transactional 失效
    }

    @Transactional
    public void insert() { ... }
}
```

**原因**：`this` 指向原始对象，不是代理对象。Spring 事务通过 AOP 代理实现，自调用绕过代理。

**解决方案**：
```java
// 方案1：注入自身（不推荐，循环依赖风险）
@Autowired UserService self;
self.insert();

// 方案2：拆到另一个 Service（推荐）
userServiceHelper.insert();

// 方案3：AopContext.currentProxy()（需要 exposeProxy = true）
((UserService) AopContext.currentProxy()).insert();
```

---

### 2. 非 public 方法上的 @Transactional 失效

```java
@Service
public class UserService {
    @Transactional  // ❌ 非 public，Spring 不代理
    protected void insert() { ... }
}
```

> Spring AOP 基于代理，只能拦截 **public 方法**。  
> 如果用 CGLIB，`protected` 方法理论上可以被子类覆盖，但 Spring 默认不处理非 public 的 `@Transactional`。

---

### 3. 数据库引擎不支持事务

```java
// MyISAM 引擎不支持事务
@Transactional
public void create() {
    dao.insert();  // MyISAM：插入成功，但事务回滚无效
}
```

> MySQL 的 MyISAM 引擎**不支持事务**，无论怎么设置 `@Transactional` 都不会回滚。  
> 解决：改用 InnoDB。

---

### 4. 多线程下事务不传播

```java
@Transactional
public void create() {
    new Thread(() -> {
        userDao.insert();  // ❌ 新线程，拿不到父线程的连接
    }).start();
}
```

> Spring 事务绑定在 **ThreadLocal** 上，新线程有新的 ThreadLocal → 拿不到连接 → 以非事务方式执行。

---

### 5. 异常被 catch 后不回滚

```java
@Transactional(rollbackFor = Exception.class)
public void create() {
    try {
        dao.insert();
    } catch (Exception e) {
        // ❌ 异常被吞了，Spring 感知不到，不会回滚
        log.error("error", e);
    }
}
```

**解决**：catch 后重新抛出，或者手动设置 rollbackOnly：

```java
catch (Exception e) {
    TransactionAspectSupport.currentTransactionStatus().setRollbackOnly();
    throw e;  // 或者抛出去
}
```

---

