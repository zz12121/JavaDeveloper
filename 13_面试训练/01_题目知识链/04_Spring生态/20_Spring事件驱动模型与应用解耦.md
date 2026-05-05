# Spring 事件驱动模型与应用解耦

> ⚠️ **先盲答**：Spring 事件机制是怎么工作的？它和消息队列（MQ）有什么区别？

---

## 盲答引导

1. `ApplicationEvent` 和 `ApplicationListener` 是做什么的？
2. Spring 内置了哪些事件？
3. `@EventListener` 和 `@TransactionalEventListener` 的区别？
4. 事件可以是异步的吗？
5. 事件驱动和直接方法调用相比，有什么优劣？

---

## 知识链提示

```
Spring 事件驱动模型
  → [[ApplicationContext]] → 事件发布与监听
    → 1. 核心角色（观察者模式）
      → ApplicationEventPublisher：事件发布者（ApplicationContext 实现了它）
      → ApplicationListener<E extends ApplicationEvent>：事件监听器
      → ApplicationEvent：事件本身（抽象类，需自定义子类）
    → 2. 自定义事件（3步）
      → ① 定义事件类（继承 ApplicationEvent 或任意普通类）
        → Spring 4.2+：事件不再需要继承 ApplicationEvent（任意对象都可作事件）
      → ② 发布事件：applicationEventPublisher.publishEvent(eventObj)
      → ③ 监听事件：@EventListener 注解方法 / 实现 ApplicationListener
    → 3. Spring 内置事件（容器生命周期）
      → ContextRefreshedEvent：容器初始化完成后发布
      → ContextClosedEvent：容器关闭时发布
      → RequestHandledEvent：HTTP 请求处理完成后（Web 环境）
      → SessionCreatedEvent / SessionDestroyedEvent（Web 环境）
    → 4. @EventListener 详解
      → 标注在方法上，方法参数即事件类型（自动匹配）
      → condition 属性：SpEL 条件过滤
        → @EventListener(condition = "#event.amount > 1000")
      → 可以返回对象 → 该对象会被当作新事件继续发布（事件链）
    → 5. 异步事件处理
      → 默认是同步的（发布线程 == 监听执行线程）
      → 加 @Async 在 @EventListener 方法上 → 异步执行
      → 异步时：异常无法抛回发布者（需独立异常处理）
    → 6. @TransactionalEventListener（事务绑定事件）
      → 解决的问题：事务提交前/后/回滚后 触发事件
      → 阶段控制：
        → Phase.AFTER_COMMIT（默认）：事务提交后执行（最常用）
        → Phase.AFTER_ROLLBACK：事务回滚后执行
        → Phase.AFTER_COMPLETION：事务完成后执行（无论提交/回滚）
        → Phase.BEFORE_COMMIT：事务提交前执行
      → fallbackExecution=true：若当前无事务，也执行（否则不执行）
      → 典型场景：
        → 事务提交后发 MQ 消息（防止事务回滚但消息已发出）
        → 事务提交后发邮件/短信通知
    → 7. 事件驱动 vs 直接调用
      → 优点：解耦（发布者不依赖监听者）、可动态增减监听者
      → 缺点：流程变隐式（不好追踪）、调试困难、异步时异常处理复杂
    → 8. 事件驱动 vs MQ
      → 事件驱动：JVM 内，同步/异步可选，轻量级
      → MQ：跨 JVM，持久化，分布式，重量级
      → 选择：单体应用解耦用事件；跨服务通信用 MQ
```

---

## 核心追问

| 追问 | 考点 |
|------|------|
| 事件监听器有多个，执行顺序怎么控制？ | @Order 注解（值越小越先执行） |
| 事件的传播是同步还是异步？ | 默认同步（发布线程阻塞等待所有监听器执行完） |
| @TransactionalEventListener 为什么能感知事务？ | 通过 TransactionSynchronizationManager 注册回调 |
| 事件可以取消吗？ | 可以，监听器抛出异常，发布者的后续监听器不会执行；但无法像 Filter 那样 return 取消 |

---

## 参考答案要点

**三个核心**：`ApplicationEventPublisher`（发布）→ `ApplicationEvent`（事件）→ `ApplicationListener`（监听）。

**@EventListener**：方法级注解，参数即事件类型，支持 SpEL 条件过滤，返回值可作新事件继续传播。

**@TransactionalEventListener**：绑定事务生命周期，`AFTER_COMMIT` 最常用——解决「事务未提交就发 MQ 消息」的经典问题。

**异步事件**：@EventListener + @Async，异步执行；注意异常处理独立。

**与 MQ 区别**：事件在 JVM 内（轻量解耦），MQ 跨 JVM（分布式解耦）。

---

## 下一步

打开 [[ApplicationContext]]，补充 `[[双向链接]]`：「Spring 事件机制是观察者模式的应用——publishEvent() 解耦了业务逻辑的执行时机和执行者」。

