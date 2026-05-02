# MongoDB 实战与 Spring 集成

## 这个问题为什么存在？

在 Java 项目中使用 MongoDB，有两个核心问题要解决：

```
问题 1：怎么操作 MongoDB？
  方案 1：MongoDB 官方 Java Driver（底层 API，功能全但写起来繁琐）
  方案 2：Spring Data MongoDB（推荐，和 Spring 生态无缝集成）
  方案 3：直接使用 MongoTemplate（更灵活，类似 JdbcTemplate）

问题 2：怎么设计文档模型（和关系型建模完全不同）？
  关系型思维：用户表 + 订单表 + 订单明细表（三张表，JOIN 查询）
  MongoDB 思维：用户文档嵌入订单数组（一对少），或订单单独集合（一对多）
  → 建模错了，后续查询性能很差，甚至要重构
```

---

## 它是怎么解决问题的？

### 一、Spring Data MongoDB 快速上手

#### 1.1 依赖配置

```xml
<dependency>
    <groupId>org.springframework.boot</groupId>
    <artifactId>spring-boot-starter-data-mongodb</artifactId>
</dependency>
```

```yaml
# application.yml
spring:
  data:
    mongodb:
      uri: mongodb://localhost:27017/testdb
      # 副本集连接：
      # uri: mongodb://mongo1:27017,mongo2:27017,mongo3:27017/testdb?replicaSet=rs0
      # 分片集群连接（通过 Mongos）：
      # uri: mongodb://mongos1:27017,mongos2:27017/testdb
```

#### 1.2 实体映射（@Document）

```java
@Document(collection = "orders")  // 指定集合名（类似表名）
public class Order {

    @Id                                 // 映射 _id 字段
    private String id;

    private Long userId;                 // 会自动映射为 userId 字段

    @Field("total_amount")              // 自定义字段名（数据库里存 total_amount）
    private BigDecimal total;

    private OrderStatus status;          // 枚举，自动序列化为 String

    @DBRef                                // 引用其他集合（类似外键，慎用！）
    private User user;

    // 嵌入文档（推荐，一次查询拿到所有数据）
    private List<OrderItem> items;

    @CreatedDate                         // 自动填充创建时间
    private Date createdAt;

    @LastModifiedDate                    // 自动填充更新时间
    private Date updatedAt;
}
```

```java
// 嵌入文档（不需要 @Document，就是普通 POJO）
public class OrderItem {
    private Long productId;
    private String productName;
    private Integer quantity;
    private BigDecimal price;
}
```

#### 1.3 MongoRepository（简单场景）

```java
public interface OrderRepository extends MongoRepository<Order, String> {

    // 自动根据方法名生成查询（类似 JPA）
    List<Order> findByUserIdAndStatus(Long userId, OrderStatus status);

    // 支持的关键字：findByXAndY / findByXOrY / findByXOrderByYDesc
    //                  findByXBetween / findByXIn / findByXLike

    // @Query 注解写原生 MongoDB 查询
    @Query("{ 'userId': ?0, 'total': { $gt: ?1 } }")
    List<Order> findLargeOrders(Long userId, BigDecimal minTotal);

    // 分页查询
    Page<Order> findByStatus(OrderStatus status, Pageable pageable);
}
```

#### 1.4 MongoTemplate（复杂场景，推荐）

```java
@Service
public class OrderService {

    @Autowired
    private MongoTemplate mongoTemplate;

    // 复杂查询（类似 JdbcTemplate，更灵活）
    public List<Order> findOrdersByUser(Long userId, OrderStatus status) {
        Query query = new Query()
            .addCriteria(Criteria.where("userId").is(userId))
            .addCriteria(Criteria.where("status").is(status))
            .with(Sort.by(Sort.Direction.DESC, "createdAt"))
            .limit(20);
        return mongoTemplate.find(query, Order.class);
    }

    // 更新（只更新指定字段，不需要更新整个文档）
    public void updateOrderStatus(String orderId, OrderStatus newStatus) {
        Query query = Query.query(Criteria.where("_id").is(orderId));
        Update update = Update.update("status", newStatus)
            .currentDate("updatedAt");
        mongoTemplate.updateFirst(query, update, Order.class);
    }

    // 聚合管道（复杂分析）
    public Map<Long, BigDecimal> sumAmountByUser() {
        Aggregation agg = Aggregation.newAggregation(
            Aggregation.match(Criteria.where("status").is(OrderStatus.PAID)),
            Aggregation.group("userId").sum("total").as("totalAmount"),
            Aggregation.sort(Sort.Direction.DESC, "totalAmount"),
            Aggregation.limit(10)
        );
        AggregationResults<Document> results = mongoTemplate.aggregate(
            agg, "orders", Document.class);
        // 处理结果...
    }
}
```

---

### 二、文档建模实战

MongoDB 的数据建模是和关系型**最不同的地方**。

#### 2.1 嵌入（Embed）vs 引用（Reference）

```
决策树：
  关系是 1:1 或 1:少（< 几百）？
    → 是：嵌入（读性能好，一次查询）
    → 否：引用（避免文档超过 16MB）

  嵌入的文档需要独立查询？
    → 是：引用（可以单独查询嵌入文档）
    → 否：嵌入

  有强事务要求（多文档原子性）？
    → 是：嵌入（单文档原子操作）
    → 否：都可以
```

```javascript
// ✅ 一对少：嵌入（订单的订单项，通常 < 50 个）
{
  "_id": "order_1001",
  "userId": 123,
  "items": [              // 嵌入订单项
    { "productId": 456, "name": "鼠标", "price": 99, "qty": 2 },
    { "productId": 789, "name": "键盘", "price": 299, "qty": 1 }
  ],
  "total": 497,
  "status": "PAID"
}
// → 查询订单时，订单项一起返回，不需要额外查询

// ✅ 一对多：引用（用户的订单，可能上千个）
// users 集合
{ "_id": "user_123", "username": "zhangsj" }

// orders 集合
{ "_id": "order_1001", "userId": "user_123", "total": 497 }
{ "_id": "order_1002", "userId": "user_123", "total": 199 }
// → 查询用户订单：db.orders.find({ userId: "user_123" })
// → 不需要嵌入，避免用户文档无限膨胀
```

#### 2.2 常见建模模式

| 模式 | 说明 | 示例 |
|------|------|------|
| **嵌入子文档** | 一对少，读多写少 | 订单 + 订单项 |
| **引用** | 一对多，子文档多 | 用户 + 订单 |
| **分桶模式（Bucket）** | 时间序列数据，按时间分桶 | 日志按天分桶 |
| **列扩展模式（Attribute）** | 字段不固定 | 商品属性（不同商品属性不同） |
| **计算模式（Computed）** | 冗余计算字段 | 订单总金额（冗余，避免每次计算） |
| **子集模式（Subset）** | 文档很大，经常只访问部分字段 | 文章 + 评论（评论多时引用） |

```javascript
// 分桶模式示例（物联网传感器数据）
// ❌ 错误：每条数据一个文档（文档数量爆炸）
{ "sensorId": "temp_01", "timestamp": ISODate("..."), "value": 25.5 }
// → 1 万个传感器 × 每分钟 1 条 = 每天 1440 万条文档

// ✅ 正确：按小时分桶（1 个文档存 60 条数据）
{
  "sensorId": "temp_01",
  "date": ISODate("2024-01-01"),
  "hour": 10,
  "readings": [
    { "minute": 0, "value": 25.5 },
    { "minute": 1, "value": 25.6 },
    ...  // 60 条数据
  ]
}
// → 文档数减少 60 倍，查询某小时的数据只需 1 次读取
```

---

### 三、索引配置（Spring Boot）

```java
@Configuration
public class MongoConfig {

    @Bean
    public MongoCustomConversions customConversions() {
        return MongoCustomConversions.create(List.of(
            // 自定义类型转换器（如 Enum → String）
            new Converter<OrderStatus, String>() {
                @Override
                public String convert(OrderStatus source) {
                    return source.name();
                }
            }
        ));
    }
}
```

```java
// 通过注解建索引（应用启动时自动创建）
@Document(collection = "orders")
@Indexed(direction = IndexDirection.DESCENDING)  // 单字段索引
@CompoundIndex(name = "idx_user_status", def = "{ 'userId': 1, 'status': 1 }")  // 复合索引
public class Order {
    @Id
    private String id;

    @Indexed(unique = true)                   // 唯一索引
    private String orderNo;

    private Long userId;                       // 在类级别 @CompoundIndex 中定义

    @Indexed(expireAfterSeconds = 7 * 24 * 3600)  // TTL 索引（7 天过期）
    private Date createdAt;
}
```

---

### 四、事务管理（Spring @Transactional）

```java
@Service
public class OrderService {

    @Autowired
    private MongoTemplate mongoTemplate;

    // ✅ 声明式事务（推荐）
    @Transactional(rollbackFor = Exception.class)
    public void createOrderWithTransaction(Order order) {
        mongoTemplate.insert(order);

        Update update = new Update().inc("stock", -order.getTotalQuantity());
        mongoTemplate.updateFirst(
            Query.query(Criteria.where("productId").is(order.getProductId())
                .and("stock").gte(order.getTotalQuantity())),
            update,
            Product.class
        );
        // 任何操作失败，Spring 自动回滚整个事务
    }

    // ❌ 不推荐：手动管理事务（复杂且容易漏关闭）
    public void createOrderManual(Order order) {
        MongoClient client = MongoClients.create(uri);
        ClientSession session = client.startSession();
        try {
            session.startTransaction();
            mongoTemplate.insert(order, session);
            // ...
            session.commitTransaction();
        } catch (Exception e) {
            session.abortTransaction();
            throw e;
        } finally {
            session.close();
        }
    }
}
```

```yaml
# 事务配置（application.yml）
spring:
  data:
    mongodb:
      uri: mongodb://mongo1:27017,mongo2:27017,mongo3:27017/testdb?replicaSet=rs0
      # 注意：事务需要副本集（或分片集群），单机模式不支持事务！
```

---

## 它和相似方案的本质区别是什么？

### Spring Data MongoDB vs MyBatis/JPA

| 维度 | Spring Data MongoDB | Spring Data JPA / MyBatis |
|------|---------------------|--------------------------|
| 数据模型 | 文档（灵活 Schema） | 关系表（固定 Schema） |
| 建模思维 | 嵌入 vs 引用 | 实体 + 关系（@OneToMany 等） |
| 事务 | 4.0+ 支持（有性能代价） | 原生支持，成熟 |
| 复杂查询 | Aggregation Pipeline（类 JSON） | JPQL / SQL（声明式） |
| 学习曲线 | 中等（要学 MongoDB 查询语法） | 中等（要学 JPQL / SQL） |
| 适用场景 | 半结构化数据、快速迭代 | 强事务、复杂关系 |

### MongoTemplate vs MongoRepository

| 维度 | MongoRepository | MongoTemplate |
|------|-----------------|---------------|
| 易用性 | 高（方法名自动生成查询） | 中（需要手写 Criteria） |
| 复杂查询 | 弱（复杂查询要用 @Query） | **强**（完全控制查询） |
| 聚合管道 | 不支持 | **支持**（`aggregate()`） |
| 动态查询 | 弱（方法名不能动态生成） | **强**（`Criteria` 动态拼接） |
| 推荐场景 | 简单 CRUD | 复杂查询、聚合分析 |

```java
// ✅ MongoTemplate 动态拼接查询条件（类似 MyBatis 的动态 SQL）
public List<Order> searchOrders(OrderSearchRequest req) {
    Query query = new Query();
    if (req.getUserId() != null) {
        query.addCriteria(Criteria.where("userId").is(req.getUserId()));
    }
    if (req.getStatus() != null) {
        query.addCriteria(Criteria.where("status").is(req.getStatus()));
    }
    if (req.getStartTime() != null) {
        query.addCriteria(Criteria.where("createdAt").gte(req.getStartTime()));
    }
    // ... 更多动态条件
    return mongoTemplate.find(query, Order.class);
}
```

---

## 正确使用方式

### 正确用法

**1. 用 MongoTemplate 而不是 MongoRepository（复杂项目）**

```java
// ✅ 正确：复杂项目用 MongoTemplate（灵活、可控）
@Autowired
private MongoTemplate mongoTemplate;

public Page<Order> search(OrderSearchRequest req, Pageable pageable) {
    Query query = new Query();
    // 动态拼接条件...
    return new PageImpl<>(
        mongoTemplate.find(query.with(pageable), Order.class),
        pageable,
        mongoTemplate.count(query, Order.class)
    );
}
```

**2. 更新时用 $set（只更新部分字段）**

```java
// ❌ 错误：更新整个文档（覆盖写，会丢失其他字段）
Order order = mongoTemplate.findById(id, Order.class);
order.setStatus(OrderStatus.PAID);
mongoTemplate.save(order);  // 全量覆盖！如果其他线程改了 items，会被覆盖

// ✅ 正确：用 Update 对象（只更新指定字段）
mongoTemplate.updateFirst(
    Query.query(Criteria.where("_id").is(id)),
    Update.update("status", OrderStatus.PAID)
        .currentDate("updatedAt"),
    Order.class
);
```

**3. 批量操作要用 BulkOperations**

```java
// ❌ 慢：逐条插入（每次都要网络往返）
for (Order order : orders) {
    mongoTemplate.insert(order);  // N 次网络往返
}

// ✅ 快：批量插入（1 次网络往返）
BulkOperations bulkOps = mongoTemplate.bulkOps(BulkOperations.BulkMode.UNORDERED, Order.class);
for (Order order : orders) {
    bulkOps.insert(order);
}
bulkOps.execute();  // 1 次网络往返，性能提升 N 倍
```

### 错误用法及后果

**错误1：用 @DBRef 做"外键"（性能杀手）**

```java
// ❌ 错误：@DBRef 会导致 N+1 查询问题
@Document
public class Order {
    @DBRef
    private User user;  // 查询订单时，每个订单都会单独查一次用户！
}
// → 查询 100 个订单 = 1 + 100 次查询 = 101 次查询！

// ✅ 正确：用嵌入（一对少）或只存 userId（一对多）
@Document
public class Order {
    private Long userId;  // 只存用户 ID，需要用户信息时单独查
}
```

**错误2：不做分页，一次查全量数据**

```java
// ❌ 错误：一次查 100 万条数据
List<Order> orders = mongoTemplate.findAll(Order.class);
// → 内存溢出！网络传输巨量数据！

// ✅ 正确：分页查询
Query query = new Query().with(PageRequest.of(0, 100));
while (true) {
    List<Order> page = mongoTemplate.find(query, Order.class);
    if (page.isEmpty()) break;
    // 处理当前页...
    query.skip(query.getSkip() + 100);  // 注意：大分页用 skip 慢，用范围分页
}
```

**错误3：事务范围过大**

```java
// ❌ 错误：事务里做无关操作
@Transactional
public void createOrder(Order order) {
    mongoTemplate.insert(order);
    sendEmail(order);       // 发送邮件（慢，持锁时间长）
    pushNotification(order); // 推送通知（慢）
}                           // 事务持锁时间太长，并发性能差

// ✅ 正确：事务只做数据库操作
@Transactional
public void createOrder(Order order) {
    mongoTemplate.insert(order);
}
// 事务提交后再做外部操作
sendEmail(order);
pushNotification(order);
```

---

## 边界情况和坑

### 坑1：BigDecimal 精度丢失

**现象**：Java 的 `BigDecimal` 存入 MongoDB 后，精度丢失。

```java
// 问题：BigDecimal 默认序列化为 Double（精度丢失！）
order.setTotal(new BigDecimal("199.99"));
mongoTemplate.insert(order);
// → MongoDB 里存的是 199.98999999999997（Double 精度问题）

// 解决：自定义 BigDecimal 序列化（存为 String 或 Decimal128）
@Field(targetType = FieldType.DECIMAL128)  // MongoDB 4.2+，精确小数
private BigDecimal total;
```

### 坑2：_id 用 String 还是 ObjectId？

```
用 ObjectId（默认）：
  ✅ 体积小（12 字节 vs String 24 字节）
  ✅ 自带创建时间戳（可以推断创建时间）
  ❌ 前端传参时需要转换（String → ObjectId）

用 String（自定义 ID）：
  ✅ 可读性好（可以用业务 ID，如订单号）
  ✅ 前端传参方便
  ❌ 占用空间大
  ❌ 如果自定义 ID 不是单调递增的，会导致 WiredTiger 索引碎片

推荐：
  - 内部实体用 ObjectId（性能好）
  - 需要对外暴露的 ID 用 String（可读性好）
```

### 坑3：Spring Boot 自动创建的索引在produation 环境很危险

**现象**：应用启动时自动创建索引，在大集合上会导致阻塞（MongoDB 4.2 之前）。

```java
// 禁用 Spring Boot 自动创建索引（生产环境推荐）
@Configuration
public class MongoConfig extends AbstractMongoClientConfiguration {

    @Override
    protected boolean autoIndexCreation() {
        return false;  // 禁用自动创建索引
    }
}
// → 索引用脚本（MongoDB Migrations）统一管理，避免应用启动时建索引
```

### 坑4：连接池配置不合理

**现象**：高并发下报错 `Timeout waiting for connection`。

```yaml
# ✅ 正确：合理配置连接池
spring:
  data:
    mongodb:
      auto-index-creation: false
      # 连接池配置（通过 URI 参数）
      uri: mongodb://localhost:27017/testdb?maxPoolSize=100&minPoolSize=10&maxIdleTimeMS=60000
      # maxPoolSize：最大连接数（默认 100，高并发要调大）
      # minPoolSize：最小维持连接数
      # maxIdleTimeMS：空闲连接回收时间
```

---

## 面试话术

**Q：MongoDB 和 Spring 怎么集成？**
"用 Spring Data MongoDB，核心是两个类：`MongoRepository`（简单 CRUD，方法名自动生成查询）和 `MongoTemplate`（复杂查询、聚合管道、批量操作，推荐在复杂项目中使用）。配置很简单，在 `application.yml` 里配 MongoDB URI 即可。事务需要副本集环境，用 `@Transactional` 注解和 JPA 一样用。"

**Q：MongoDB 的数据建模有什么要注意的？**
"最核心的是嵌入 vs 引用的决策：一对少（如订单项）直接嵌入，读性能好；一对多（如用户订单）用引用，避免文档超过 16MB。还有分桶模式（时间序列数据按时间分桶，减少文档数量）、计算模式（冗余计算字段，避免每次计算）。建模错了后续要重构，比关系型数据库更痛苦，因为 MongoDB 没有 ALTER TABLE，要写迁移脚本。"

**Q：MongoTemplate 和 MongoRepository 怎么选？**
"简单项目、快速原型用 MongoRepository（开发快）。复杂项目、需要动态查询条件、聚合分析用 MongoTemplate（灵活可控）。实际项目中大多是 MongoTemplate，因为查询条件经常是动态的（前端传了哪个字段就加哪个查询条件）。"

**Q：MongoDB 事务在 Spring 中怎么用？有什么坑？**
"用 `@Transactional` 注解，和 JPA 一样，但有几个坑：第一，事务需要副本集环境（单机模式不支持）；第二，事务范围要尽量小（不要在事务里做外部调用，持锁时间长影响并发）；第三，多文档事务有性能代价，能用嵌入模型避免就不用事务。Spring 的 `@Transactional` 会自动处理 MongoDB 的会话管理，比手动管理简单很多。"

---

## 本文总结

**MongoDB 实战与 Spring 集成**核心要点：

- **Spring Data MongoDB**：MongoRepository（简单 CRUD）+ MongoTemplate（复杂查询、聚合，推荐）
- **文档建模**：嵌入（一对少）vs 引用（一对多），分桶模式、计算模式
- **索引配置**：注解建索引（开发环境）+ 脚本建索引（生产环境，避免启动时建索引）
- **事务管理**：`@Transactional`（和 JPA 一样用），但需要副本集环境
- **批量操作**：用 `BulkOperations`（1 次网络往返，性能提升 N 倍）
- **常见坑**：`@DBRef` 导致 N+1 查询、BigDecimal 精度丢失、`_id` 类型选择、连接池配置

**高频面试考点**：嵌入 vs 引用决策、MongoTemplate vs MongoRepository、Spring 事务管理、MongoDB 数据建模模式。

---

**关联文档**：
- [[MongoDB核心概念与架构]]（文档模型、WiredTiger、副本集）
- [[MongoDB索引与查询优化]]（索引配置、聚合管道优化）
- [[MongoDB事务与一致性]]（Spring @Transactional 底层原理）
- [[MongoDBvsMySQL面试对比]]（建模思维差异、事务差异）
