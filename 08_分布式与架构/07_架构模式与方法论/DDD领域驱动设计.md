# DDD领域驱动设计

## 这个问题为什么存在？

> 微服务拆分没有标准答案。**拆粗了没效果，拆细了分布式事务复杂**。问题是：**怎么科学地划分微服务边界？**

没有DDD，你会遇到：
- 微服务拆分靠"拍脑袋"，拆完了发现两个服务耦合严重
- "订单"和"库存"到底拆不拆？拆了分布式事务复杂，不拆耦合
- 代码写成"面向数据库"——全是getter/setter，没有业务逻辑

---

## 它是怎么解决问题的？

### DDD的核心：限界上下文（Bounded Context）

```
电商系统：
  ┌──────── 订单上下文 ────────┐
  │ Order（聚合根）                     │
  │ OrderLine（实体）                  │
  │ Address（值对象）                 │
  └─────────────────────────────────┘

  ┌──────── 库存上下文 ────────┐
  │ Inventory（聚合根）               │
  │ Warehouse（实体）                 │
  └─────────────────────────────────┘

两个上下文通过「领域事件」通信：
  OrderCreated → 扣减库存
```

**核心思想**：**限界上下文就是微服务的边界**。同一个概念（如Product），在不同上下文中有不同的属性和行为。

### 事件风暴（Event Storming）：划分上下文的方法

```
步骤1：把所有领域事件贴在墙上（橙色便签）
  → 订单已创建、库存已扣减、支付已成功

步骤2：找「命令」（蓝色便签，触发事件的动作）
  → 创建订单、扣减库存、发起支付

步骤3：找「聚合」（黄色便签，一组相关对象作为数据修改单元）
  → 订单（Order）+ 订单行（OrderLine）

步骤4：划分「限界上下文」（用大纸把相关事件、命令、聚合圈起来）
  → 这就是微服务的边界！
```

### 分层架构：让领域层纯净

```
┌───────────┐
│ 用户接口层（Controller）     │  ← 接收请求，不写业务逻辑
├───────────┤
│ 应用层（Application Service）  │  ← 编排领域对象，不包含业务规则
├───────────┤
│ 领域层（Domain）              │  ← 核心！业务规则都在这
│  - Entity（实体，有ID）        │
│  - Value Object（值对象，无ID） │
│  - Aggregate（聚合根）         │
│  - Domain Event（领域事件）    │
├───────────┤
│ 基础设施层（Infrastructure）    │  ← 数据库、MQ、外部服务
└───────────┘
```

```java
// ❌ 贫血模型（Anti-Pattern）
public class OrderService {
    public void confirmOrder(Long orderId) {
        Order order = orderRepository.findById(orderId);
        order.setStatus("CONFIRMED");  // 业务逻辑泄露到应用层
        orderRepository.save(order);
    }
}

// ✅ DDD：业务逻辑在领域对象里
public class Order {
    private OrderStatus status;

    public void confirm() {  // 行为在领域对象里
        if (this.status != OrderStatus.PENDING) {
            throw new IllegalStateException("只有待确认订单能确认");
        }
        this.status = OrderStatus.CONFIRMED;
        // 发布领域事件
        registerEvent(new OrderConfirmedEvent(this.id));
    }
}

// 应用层只做编排
@Service
public class OrderApplicationService {
    public void confirmOrder(Long orderId) {
        Order order = orderRepository.findById(orderId);
        order.confirm();  // 业务逻辑在领域对象
        orderRepository.save(order);
        eventPublisher.publish(order.getEvents());  // 发布领域事件
    }
}
```

---

## 深入原理

| | DDD | 面向数据库设计（CRUD） | 贫血模型 |
|---|---|---|---|
| 关注点 | 业务领域、业务能力 | 表结构、CRUD | 和CRUD差不多 |
| 业务逻辑在哪 | 领域对象（富对象） | Service类 | Service类（领域对象只是数据容器） |
| 适用场景 | 复杂业务领域（电商、金融） | 简单CRUD（后台管理） | ❌ 不推荐 |
| 微服务拆分依据 | 限界上下文 | 拍脑袋、按表拆 | 拍脑袋 |

**本质区别**：
- **CRUD**：关注数据，业务规则散落在Service
- **DDD**：关注行为，业务规则封装在领域对象

---

## 正确使用方式

### 聚合根设计原则

```
原则1：聚合根引用其他聚合根，用ID（不是对象引用）
  → Order引用Product，存productId（不是Product对象）

原则2：聚合根之间，通过领域事件通信
  → OrderConfirmedEvent → InventoryService扣库存

原则3：聚合尽量小
  → 订单（Order）是一个聚合根
  → 订单行（OrderLine）是Order的内部实体，外部看不到
```

```java
public class Order {  // 聚合根
    private Long id;
    private Long customerId;  // 引用其他聚合根，用ID
    private List<OrderLine> lines;  // 内部实体，外界看不到
    private Address shippingAddress;  // 值对象（无ID）

    public void addLine(Long productId, int amount) {  // 业务规则在领域对象
        if (this.status != OrderStatus.DRAFT) {
            throw new IllegalStateException("只有草稿订单能添加商品");
        }
        lines.add(new OrderLine(productId, amount));
    }
}
```

### 领域事件：聚合根之间通信

```java
// 1. 领域事件定义
public class OrderConfirmedEvent {
    private final Long orderId;
    private final Long customerId;
    // ...
}

// 2. 聚合根发布事件
public class Order {
    private List<Object> events = new ArrayList<>();

    public void confirm() {
        this.status = OrderStatus.CONFIRMED;
        events.add(new OrderConfirmedEvent(this.id, this.customerId));
    }

    public List<Object> getEvents() { return events; }
}

// 3. 应用层发布到MQ
@EventListener
public void handleOrderConfirmed(OrderConfirmedEvent event) {
    kafkaTemplate.send("order-confirmed", event.getOrderId().toString(), event);
}
```

---

## 边界情况和坑

### 坑1：过度设计（DDD过度）

```
场景：简单CRUD（如"部门管理"），也搞DDD
结果：一个简单更新，写了聚合根、领域事件、仓储...
```

**解决方案**：
1. **简单CRUD不搞DDD**（用Service + DAO即可）
2. **复杂业务领域才用DDD**（电商、金融、保险）
3. **渐进式演进**：从简单开始，业务复杂了再引入DDD

### 坑2：贫血模型（披着DDD的皮）

```
场景：领域对象只有getter/setter，业务逻辑全在Service
结果：看起来像DDD，实际还是CRUD
```

**解决方案**：
1. **业务逻辑写在领域对象里**（富对象）
2. **Service只做编排**（调用领域对象的方法）
3. **用单元测试验证**（领域对象可以独立单元测试）

### 坑3：聚合根设计太大

```
场景：Order聚合根包含了Customer、Product
结果：每次加载Order，级联加载Customer、Product → 性能炸了
```

**解决方案**：
1. **聚合根引用其他聚合根，只存ID**
2. **需要Customer信息时，通过CustomerService查**
3. **聚合根尽量小**（只包含紧耦合的实体）

---

