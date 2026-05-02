# gRPC 核心原理

## 这个问题为什么存在？

在微服务架构里，服务之间需要通信。最早的方案是 REST over HTTP/1.1：

```
REST 的问题：
  - HTTP/1.1 同一连接只能处理一个请求（队头阻塞）
  - JSON 序列化效率低（文本格式，体积大，解析慢）
  - 没有强类型的接口契约（Swagger 是额外加的）
  - 不支持服务端推送流式数据
```

**gRPC 是 Google 开源的高性能 RPC 框架**，用 Protocol Buffers 替代 JSON，用 HTTP/2 替代 HTTP/1.1，一次性解决了上面所有问题。

```
有了 gRPC：
  - 定义一个 .proto 文件 → 自动生成客户端和服务端代码
  - 跨语言支持（Java/Go/Python/C++/Rust...）
  - HTTP/2 多路复用 → 一个连接并发多个请求
  - Protobuf 二进制序列化 → 体积小 3-10 倍，速度快 20-100 倍
  - 天然支持四种调用模式（一元/服务端流/客户端流/双向流）
```

> 和 Dubbo 的关系：**Dubbo 是 Java 生态的 RPC 框架，gRPC 是跨语言的 RPC 框架**。Dubbo 3.x 已经把 gRPC 作为默认协议之一。云原生场景（Kubernetes + Istio）几乎标配 gRPC。

---

## 它是怎么解决问题的？

### 一、整体架构

```
┌──────────────────────────────────────────────────────────────┐
│                        gRPC 调用链路                          │
│                                                              │
│  Client Stub  ──→  HTTP/2  ──→  Server Stub  ──→  业务逻辑   │
│  (自动生成)      (多路复用)    (自动生成)                    │
│      ↑                              ↑                        │
│  Protobuf 编解码              Protobuf 编解码                 │
│  (二进制序列化)               (二进制序列化)                   │
└──────────────────────────────────────────────────────────────┘
```

gRPC 的核心设计：**IDL 驱动，代码生成**。

```protobuf
// 1. 写 proto 文件（接口定义语言）
syntax = "proto3";

package com.example.order;

// 订单服务定义
service OrderService {
  // 一元调用（最常用，类似普通函数调用）
  rpc GetOrder (GetOrderRequest) returns (OrderResponse);

  // 服务端流式调用（客户端发一个请求，服务端返回多条数据）
  rpc StreamOrders (StreamOrdersRequest) returns (stream OrderResponse);

  // 客户端流式调用（客户端发多条数据，服务端返回一个结果）
  rpc BatchCreateOrder (stream CreateOrderRequest) returns (BatchResponse);

  // 双向流式调用（双方可以随时发消息）
  rpc Chat (stream ChatRequest) returns (stream ChatResponse);
}

message GetOrderRequest {
  int64 order_id = 1;
}

message OrderResponse {
  int64 order_id = 1;
  repeated OrderItem items = 2;
  int64 total_price = 3;
  string status = 4;
}
```

```bash
# 2. 编译生成代码
protoc --java_out=./src \
       --grpc-java_out=./src \
       order_service.proto

# 自动生成：OrderServiceGrpc（抽象类）、OrderServiceBlockingStub（同步客户端）、
#           OrderServiceFutureStub（异步客户端）、所有消息类的 Builder
```

---

### 二、Protocol Buffers 序列化原理

Protobuf 是 gRPC 的序列化格式，也是 gRPC 高性能的关键。

#### 2.1 为什么比 JSON 快？

```
JSON 表示：
{
  "order_id": 12345,
  "status": "PAID",
  "total_price": 9999
}

Protobuf 二进制表示（简化）：
  [08][39 30]     ← field 1 (order_id), varint 编码, 3 字节
  [18][04][PAID]  ← field 3 (status), 长度前缀 + 字符串, 6 字节
  [20][8F 4E]     ← field 4 (total_price), varint 编码, 3 字节

  总共约 12 字节 vs JSON 约 60 字节 → 体积小 5 倍
```

#### 2.2 编码规则

```
每个字段：Tag（字段编号 + 类型）+ Value

Tag 编码：
  (field_number << 3) | wire_type
  field_number = proto 文件中 = 后面的数字
  wire_type = 数据类型（0=varint, 2=length-delimited, 5=32bit, 1=64bit）

Varint 编码（变长整数）：
  小数字用更少的字节
  1 → [01]（1 字节）
  300 → [AC 02]（2 字节）
  大约每个字节存 7 位有效数据，最高位是 continuation bit
```

#### 2.3 proto2 vs proto3

| 维度 | proto2 | proto3 |
|------|--------|--------|
| 字段修饰 | `required`/`optional`/`repeated` | 只有 `optional`/`repeated`（默认 optional） |
| 默认值 | 必须显式指定默认值 | 类型默认值（数字=0，字符串=""） |
| 兼容性 | 更严格的向前/向后兼容 | 更宽松，适合跨团队协作 |
| 推荐 | 旧项目 | **新项目用 proto3** |

#### 2.4 向后兼容规则（非常重要）

```
新增字段：不影响旧代码（旧代码忽略不认识的字段）✅
删除字段：field_number 永远不能重复使用 ❌
修改字段类型：不兼容（string → int32 会乱码）❌
修改字段名：只影响 JSON 序列化，不影响二进制 ✅
```

> **面试考点**：Protobuf 的兼容性规则是 gRPC 服务演进的基础。删字段要用 `reserved` 保留编号。

---

### 三、HTTP/2 为什么比 HTTP/1.1 快？

gRPC 基于 HTTP/2，这给了它几个根本性的性能优势：

```
┌─────────────────────────────────────────────────────────────┐
│              HTTP/1.1 vs HTTP/2                             │
│                                                             │
│ HTTP/1.1（一连接一请求）：                                   │
│   Client ──Request1──→ Server                               │
│   Client ←─Response1── Server                               │
│   Client ──Request2──→ Server    ← 必须等 Response1 完成    │
│                                                             │
│ HTTP/2（多路复用）：                                         │
│   Client ══Stream1══╗ Server                                │
│          ══Stream2══╣  ← 多个请求在同一个 TCP 连接上并行    │
│          ══Stream3══╝                                        │
│                                                             │
│ HTTP/2 帧结构：                                              │
│   ┌──────────┬──────────┬──────────────────┐                │
│   │ Length   │ Type     │  Stream ID       │                │
│   │ (9字节)  │ (1字节)  │  (4字节)         │                │
│   ├──────────┴──────────┴──────────────────┤                │
│   │           Payload（0~2^14-1 字节）       │                │
│   └────────────────────────────────────────┘                │
└─────────────────────────────────────────────────────────────┘
```

#### HTTP/2 核心特性

| 特性 | 说明 | gRPC 如何利用 |
|------|------|--------------|
| **多路复用** | 一个 TCP 连接上并发多个请求/响应 | 一个 gRPC Channel 管理所有 RPC 调用 |
| **头部压缩（HPACK）** | 请求头用哈夫曼编码 + 动态表压缩 | gRPC 的元数据（metadata）走 HTTP/2 头部 |
| **二进制帧** | 数据用二进制帧传输，不再是文本 | Protobuf 序列化数据直接放进帧 |
| **流式传输** | 数据可以分帧发送，不需要等全部准备好 | 支持四种流式调用模式 |
| **服务器推送** | 服务器可以主动向客户端推送 | 服务端流式调用天然就是推送 |

#### HPACK 头部压缩原理

```
第一次请求：
  :method: POST          → 编码为静态表索引 3
  :path: /order.OrderService/GetOrder  → 字面量编码
  content-type: application/grpc     → 编码为静态表索引 22
  te: trailers                → 编码为静态表索引 5

后续请求：
  :method、content-type、te → 直接用索引（0 字节！）
  :path → 动态表索引（1 字节）

  → 第 2 次请求的头部从 ~200 字节压缩到 ~30 字节
```

---

### 四、四种调用模式

#### 4.1 一元调用（Unary RPC）

最常见的模式，客户端发一个请求，服务端回一个响应。

```java
// ===== 服务端 =====
@GrpcService
public class OrderServiceImpl extends OrderServiceGrpc.OrderServiceImplBase {

    @Override
    public void getOrder(GetOrderRequest request,
                         StreamObserver<OrderResponse> responseObserver) {
        // 业务逻辑
        Order order = orderService.findById(request.getOrderId());

        OrderResponse response = OrderResponse.newBuilder()
            .setOrderId(order.getId())
            .setStatus(order.getStatus())
            .build();

        responseObserver.onNext(response);   // 返回响应
        responseObserver.onCompleted();      // 标记完成
    }
}

// ===== 客户端（阻塞式）=====
OrderServiceBlockingStub stub = OrderServiceGrpc.newBlockingStub(channel);
OrderResponse response = stub.getOrder(
    GetOrderRequest.newBuilder().setOrderId(12345L).build()
);
System.out.println(response.getStatus());

// ===== 客户端（异步式）=====
OrderServiceFutureStub futureStub = OrderServiceGrpc.newFutureStub(channel);
ListenableFuture<OrderResponse> future = futureStub.getOrder(request);
Futures.addCallback(future, new FutureCallback<>() {
    @Override
    public void onSuccess(OrderResponse result) {
        System.out.println(result.getStatus());
    }
    @Override
    public void onFailure(Throwable t) {
        log.error("调用失败", t);
    }
}, executor);
```

#### 4.2 服务端流式（Server Streaming）

客户端发一个请求，服务端返回多条数据（适合分页拉取、实时推送）。

```java
// ===== 服务端 =====
@Override
public void streamOrders(StreamOrdersRequest request,
                         StreamObserver<OrderResponse> responseObserver) {
    List<Order> orders = orderService.findByUserId(request.getUserId());

    // 每查到一条就推送一条，不用等全部查完
    for (Order order : orders) {
        OrderResponse response = OrderResponse.newBuilder()
            .setOrderId(order.getId())
            .build();
        responseObserver.onNext(response);  // 推送一条
    }
    responseObserver.onCompleted();  // 推送结束
}

// ===== 客户端 =====
OrderServiceStub stub = OrderServiceGrpc.newStub(channel);
stub.streamOrders(request, new StreamObserver<>() {
    @Override
    public void onNext(OrderResponse response) {
        // 每收到一条数据触发一次
        System.out.println("收到订单: " + response.getOrderId());
    }
    @Override
    public void onError(Throwable t) { /* 错误处理 */ }
    @Override
    public void onCompleted() { /* 流结束 */ }
});
```

#### 4.3 客户端流式（Client Streaming）

客户端发多条数据，服务端返回一个结果（适合批量上传、聚合计算）。

```java
// ===== 服务端 =====
@Override
public StreamObserver<CreateOrderRequest> batchCreateOrder(
        StreamObserver<BatchResponse> responseObserver) {

    return new StreamObserver<>() {
        private int successCount = 0;
        private int failCount = 0;

        @Override
        public void onNext(CreateOrderRequest request) {
            // 每收到一条就处理
            try {
                orderService.create(request);
                successCount++;
            } catch (Exception e) {
                failCount++;
            }
        }

        @Override
        public void onCompleted() {
            // 所有数据接收完毕，返回汇总
            responseObserver.onNext(BatchResponse.newBuilder()
                .setSuccessCount(successCount)
                .setFailCount(failCount)
                .build());
            responseObserver.onCompleted();
        }
    };
}

// ===== 客户端 =====
StreamObserver<CreateOrderRequest> requestObserver =
    stub.batchCreateOrder(new StreamObserver<>() {
        @Override
        public void onNext(BatchResponse response) {
            System.out.println("成功: " + response.getSuccessCount());
        }
        @Override public void onError(Throwable t) { /* ... */ }
        @Override public void onCompleted() { /* ... */ }
    });

// 发送多条数据
for (Order order : orders) {
    requestObserver.onNext(toRequest(order));
}
requestObserver.onCompleted();  // 告诉服务端发送完毕
```

#### 4.4 双向流式（Bidirectional Streaming）

双方都可以随时发消息（适合聊天、实时协作）。

```java
// ===== 服务端 =====
@Override
public StreamObserver<ChatRequest> chat(
        StreamObserver<ChatResponse> responseObserver) {

    return new StreamObserver<>() {
        @Override
        public void onNext(ChatRequest request) {
            // 收到客户端消息，处理后回复
            String reply = processMessage(request.getMessage());
            responseObserver.onNext(ChatResponse.newBuilder()
                .setReply(reply)
                .build());
        }
        @Override
        public void onError(Throwable t) { log.error("流异常", t); }
        @Override
        public void onCompleted() {
            responseObserver.onCompleted();
        }
    };
}
```

#### 四种模式对比

| 模式 | 使用场景 | 类比 |
|------|---------|------|
| 一元调用 | 查询订单、获取用户信息 | 普通函数调用 |
| 服务端流 | 实时推送、分页拉取、日志流 | 订阅 → 持续接收 |
| 客户端流 | 批量上传、聚合计算 | 持续发送 → 一次返回 |
| 双向流 | 聊天、实时协作 | WebSocket |

---

### 五、拦截器（Interceptor）

gRPC 的拦截器类似 Spring MVC 的 Filter / Dubbo 的 Filter，用于在调用前后插入通用逻辑。

#### 5.1 客户端拦截器

```java
public class AuthClientInterceptor implements ClientInterceptor {
    @Override
    public <ReqT, RespT> ClientCall<ReqT, RespT> interceptCall(
            MethodDescriptor<ReqT, RespT> method,
            CallOptions callOptions,
            Channel next) {

        return new ForwardingClientCall.SimpleForwardingClientCall<>(
                next.newCall(method, callOptions)) {
            @Override
            public void start(Listener<RespT> responseListener, Metadata headers) {
                // 在请求头里塞 token
                headers.put(Metadata.Key.of("authorization",
                    Metadata.ASCII_STRING_MARSHALLER),
                    "Bearer " + token);
                super.start(responseListener, headers);
            }
        };
    }
}

// 注册拦截器
channel = NettyChannelBuilder.forTarget("localhost:9090")
    .intercept(new AuthClientInterceptor())
    .build();
```

#### 5.2 服务端拦截器

```java
@GrpcService(interceptors = {AuthServerInterceptor.class})
public class OrderServiceImpl extends OrderServiceGrpc.OrderServiceImplBase {
    // ...
}

public class AuthServerInterceptor implements ServerInterceptor {
    @Override
    public <ReqT, RespT> ServerCall.Listener<ReqT> interceptCall(
            ServerCall<ReqT, RespT> call,
            Metadata headers,
            ServerCallHandler<ReqT, RespT> next) {

        String token = headers.get(Metadata.Key.of("authorization",
            Metadata.ASCII_STRING_MARSHALLER));

        if (token == null || !validateToken(token)) {
            // 未认证，直接关闭连接
            call.close(Status.UNAUTHENTICATED
                .withDescription("缺少或无效的 token"), headers);
            return new ServerCall.Listener<>() {};
        }

        return next.startCall(call, headers);
    }
}
```

#### 常见拦截器场景

| 场景 | 客户端 | 服务端 |
|------|--------|--------|
| 认证鉴权 | 附加 token | 校验 token |
| 链路追踪 | 附加 traceId | 提取 traceId，写入 MDC |
| 日志记录 | 记录请求参数 | 记录响应耗时 |
| 限流 | 发送前检查配额 | 接收后检查配额 |
| 重试 | 捕获异常后重试 | — |

---

### 六、Deadline 与超时控制

gRPC 原生支持 Deadline 机制（不是简单的超时），可以精确控制调用时长。

```java
// 设置 3 秒超时
OrderServiceBlockingStub stub = OrderServiceGrpc.newBlockingStub(channel)
    .withDeadlineAfter(3, TimeUnit.SECONDS);

try {
    OrderResponse response = stub.getOrder(request);
} catch (StatusRuntimeException e) {
    if (e.getStatus().getCode() == Status.Code.DEADLINE_EXCEEDED) {
        log.warn("gRPC 调用超时");
    }
}
```

```
Deadline 传播（重要）：
  客户端设置 3s Deadline
    → 服务端 A 收到后剩余 2.8s（网络耗时 0.2s）
      → 服务端 A 调用服务端 B，Deadline 自动传播，B 只有 2.5s
        → 如果 B 处理超过 2.5s，直接返回 DEADLINE_EXCEEDED

  → 整条链路共享一个 Deadline，不会无限放大超时
```

---

### 七、gRPC 的负载均衡

#### 7.1 客户端负载均衡（gRPC 默认）

gRPC 的负载均衡和 Dubbo 一样，是**客户端侧**的——客户端拿到服务端地址列表后自己决定调用哪个。

```
┌──────────────────────────────────────┐
│           gRPC 负载均衡               │
│                                      │
│  Client                    Server    │
│  ┌───────────┐            ┌─────┐    │
│  │ Name      │ resolver   │ S1  │    │
│  │ Resolver  │─────────→  ├─────┤    │
│  │           │ 地址列表    │ S2  │    │
│  └───────────┘            ├─────┤    │
│       ↓                   │ S3  │    │
│  ┌───────────┐            └─────┘    │
│  │ LB Policy │ picker     选择一个    │
│  │ (均衡策略)│─────────→  Server     │
│  └───────────┘                        │
└──────────────────────────────────────┘
```

#### 7.2 负载均衡策略

| 策略 | 说明 | 适用场景 |
|------|------|---------|
| `pick_first` | 默认，选第一个地址 | 简单场景 |
| `round_robin` | 轮询 | 通用场景 |
| `grpclb` | gRPC 官方 LB 协议 | 需要中心化 LB |
| `xds` | Envoy/Istio 的 xDS 协议 | **K8s + Istio 场景（云原生标配）** |

```java
// 使用 round_robin
ManagedChannel channel = NettyChannelBuilder.forTarget("dns:///order-service:9090")
    .defaultLoadBalancingPolicy("round_robin")
    .build();
```

#### 7.3 和服务发现集成

```java
// gRPC + Nacos 服务发现
// 1. 自定义 NameResolver，从 Nacos 拉取服务地址列表
// 2. 监听 Nacos 的服务变更事件，实时更新地址列表

// 实际项目中常用 grpc-spring-boot-starter + nacos
// 或使用 Spring Cloud gRPC（自动集成服务发现）
```

---

### 八、gRPC 错误处理

gRPC 用 Status 代替 HTTP 状态码，语义更丰富：

```java
// 服务端返回错误
responseObserver.onError(Status.NOT_FOUND
    .withDescription("订单不存在: " + orderId)
    .asRuntimeException());

// 客户端处理错误
try {
    stub.getOrder(request);
} catch (StatusRuntimeException e) {
    switch (e.getStatus().getCode()) {
        case NOT_FOUND:
            // 订单不存在
            break;
        case PERMISSION_DENIED:
            // 无权限
            break;
        case DEADLINE_EXCEEDED:
            // 超时
            break;
        case UNAVAILABLE:
            // 服务不可用
            break;
        default:
            // 其他错误
    }
}
```

#### gRPC 状态码 vs HTTP 状态码

| gRPC Status | 含义 | 对应 HTTP |
|-------------|------|-----------|
| OK | 成功 | 200 |
| INVALID_ARGUMENT | 参数错误 | 400 |
| UNAUTHENTICATED | 未认证 | 401 |
| PERMISSION_DENIED | 无权限 | 403 |
| NOT_FOUND | 资源不存在 | 404 |
| DEADLINE_EXCEEDED | 超时 | 504 |
| RESOURCE_EXHAUSTED | 限流/资源耗尽 | 429 |
| UNAVAILABLE | 服务不可用 | 503 |
| INTERNAL | 内部错误 | 500 |

---

## 它和相似方案的本质区别是什么？

### gRPC vs REST

| 维度 | REST (HTTP/1.1 + JSON) | gRPC (HTTP/2 + Protobuf) |
|------|----------------------|------------------------|
| 协议 | HTTP/1.1（文本协议） | HTTP/2（二进制帧） |
| 序列化 | JSON（文本，可读性好） | Protobuf（二进制，体积小速度快） |
| 流式支持 | 不原生支持（需要 SSE/WebSocket） | 原生支持四种流式模式 |
| 代码生成 | 可选（Swagger/OpenAPI） | **必须**（protoc 生成） |
| 浏览器支持 | 原生支持 | 需要 gRPC-Web 代理 |
| 跨语言 | 有，但类型不安全 | 强类型，多语言 SDK |
| 性能 | 中等 | **高**（体积小 3-10x，速度快 20-100x） |
| 生态 | 最广（几乎所有语言/平台） | 增长快，云原生标配 |
| 适用场景 | 对外 API、前端调用 | **微服务间通信**、高性能场景 |

```
什么时候用 REST？
  - 对外暴露 API（给前端、第三方用）
  - 需要浏览器直接调用
  - 简单的 CRUD 服务

什么时候用 gRPC？
  - 微服务间内部通信
  - 需要流式传输
  - 需要高性能 + 低延迟
  - 多语言技术栈
```

### gRPC vs Dubbo

| 维度 | gRPC | Dubbo |
|------|------|-------|
| 定位 | 跨语言 RPC 框架 | Java 生态 RPC 框架 |
| 序列化 | Protobuf（默认） | Hessian2（默认），支持 Protobuf |
| 协议 | HTTP/2 | dubbo 协议（TCP）、REST、gRPC（Dubbo 3） |
| 服务发现 | 需要自己集成（或用 xDS） | 内置 ZooKeeper/Nacos |
| 负载均衡 | 客户端 LB | 客户端 LB |
| 流量治理 | 依赖 Istio | 内置路由、降级、限流 |
| 多语言 | 原生支持 10+ 语言 | 主要 Java，3.x 支持 Go/Rust |
| 适用场景 | 云原生、多语言、跨团队 | Java 微服务、国内生态 |

> **结论**：Java 单体技术栈用 Dubbo（开箱即用的服务治理），多语言/云原生用 gRPC。Dubbo 3.x 已经支持 gRPC 协议，两者可以互通。

### gRPC vs Thrift vs GraphQL

| 维度 | gRPC | Thrift | GraphQL |
|------|------|--------|---------|
| 出品方 | Google | Facebook/Apache | Facebook |
| 协议 | HTTP/2 | 自定义 TCP 协议 | HTTP/1.1 |
| 序列化 | Protobuf | Thrift Binary/Compact | JSON |
| 流式支持 | 原生四种 | 不支持 | 支持 Subscription（WebSocket） |
| 代码生成 | 必须生成 | 必须生成 | 可选 |
| 灵活查询 | 否（固定接口） | 否（固定接口） | **是**（客户端决定查什么字段） |
| 适用场景 | 微服务间通信 | 内部高性能通信 | 前端按需查询 |

---

## 正确使用方式

### 正确用法

**1. proto 文件要设计好向后兼容**

```protobuf
// 正确：删除字段用 reserved 保留编号
message OrderResponse {
  int64 order_id = 1;
  string status = 2;
  reserved 3;           // 保留旧字段的编号，永远不重用
  reserved "old_field"; // 保留旧字段名
  int64 total_price = 4; // 新字段用新编号
}

// 正确：新增 optional 字段不影响旧代码
message OrderResponse {
  int64 order_id = 1;
  string status = 2;
  string description = 3;  // 新增，旧代码会忽略
}
```

**为什么正确**：gRPC 的向前/向后兼容依赖 field_number 不变。删了编号又复用，旧客户端发送的数据会被新服务端错误解析。

**2. 异步调用 + Deadline + 重试**

```java
// 正确：设置超时 + 异步回调
OrderServiceFutureStub stub = OrderServiceGrpc.newFutureStub(channel)
    .withDeadlineAfter(3, TimeUnit.SECONDS);

ListenableFuture<OrderResponse> future = stub.getOrder(request);
Futures.addCallback(future, new FutureCallback<>() {
    @Override
    public void onSuccess(OrderResponse result) { /* 处理结果 */ }
    @Override
    public void onFailure(Throwable t) {
        if (t instanceof StatusRuntimeException) {
            StatusRuntimeException sre = (StatusRuntimeException) t;
            if (sre.getStatus().getCode() == Status.Code.DEADLINE_EXCEEDED) {
                // 超时，可以重试或走降级
                fallbackService.getOrder(request.getOrderId());
            }
        }
    }
}, executor);
```

**为什么正确**：同步阻塞调用会占线程，高并发下线程池打满。异步 + Deadline 是生产环境的标准写法。

**3. Channel 复用，不要每次调用都新建**

```java
// 错误：每次调用都创建 Channel（TCP 连接建立开销大）
public OrderResponse getOrder(long orderId) {
    ManagedChannel channel = ManagedChannelBuilder
        .forAddress("localhost", 9090).usePlaintext().build();
    // ...
    channel.shutdown();  // 关了又开，反复建连
}

// 正确：Channel 作为单例，全局复用
public class GrpcClient {
    private static final ManagedChannel channel =
        ManagedChannelBuilder.forAddress("localhost", 9090)
            .usePlaintext()
            .keepAliveTime(30, TimeUnit.SECONDS)  // 保活探测
            .keepAliveTimeout(10, TimeUnit.SECONDS)
            .build();

    public static ManagedChannel getChannel() {
        return channel;
    }
}
```

**为什么正确**：gRPC 基于 HTTP/2，一个 Channel 就是一个 TCP 连接，支持多路复用。每次新建 Channel 要经历 TCP 三次握手 + TLS 握手（如果用 TLS），开销很大。

**4. gRPC-Web 解决浏览器调用问题**

```
浏览器不能直接调用 gRPC（HTTP/2 的帧格式浏览器 API 不完全支持）
→ 需要 gRPC-Web 代理（Envoy / grpcwebproxy）
→ 浏览器 → gRPC-Web 代理 → gRPC 服务端

架构：
  Browser ──(HTTP/1.1 + JSON/Text)──→ Envoy ──(HTTP/2 + Protobuf)──→ gRPC Server
```

### 错误用法及后果

**错误1：没有设置 Deadline，服务端挂了客户端永远等**

```java
// 错误：没有超时设置
OrderServiceBlockingStub stub = OrderServiceGrpc.newBlockingStub(channel);
OrderResponse response = stub.getOrder(request);  // 如果服务端挂了，线程永远阻塞
```

**后果**：线程池耗尽，服务雪崩。

**修复**：始终设置 Deadline：`.withDeadlineAfter(3, TimeUnit.SECONDS)`。

**错误2：在 gRPC 服务端的业务线程中做阻塞 IO**

```java
// 错误：在 gRPC 的 IO 线程中查数据库（默认情况下 gRPC 用少量线程处理所有请求）
@Override
public void getOrder(GetOrderRequest request,
                     StreamObserver<OrderResponse> responseObserver) {
    // 这个数据库查询可能要 500ms，期间该线程不能处理其他请求
    Order order = orderDao.selectById(request.getOrderId()); // 阻塞 IO！
    // ...
}
```

**后果**：gRPC 默认的线程池线程数很少（Transport 线程），阻塞 IO 会导致所有请求排队。

**修复**：
```java
// 方案1：配置独立的业务线程池
Server server = ServerBuilder.forPort(9090)
    .executor(Executors.newFixedThreadPool(200))  // 业务线程池
    .addService(new OrderServiceImpl())
    .build();

// 方案2：用 CompletableFuture 异步处理
@Override
public void getOrder(GetOrderRequest request,
                     StreamObserver<OrderResponse> responseObserver) {
    CompletableFuture.supplyAsync(() -> orderDao.selectById(request.getOrderId()), bizExecutor)
        .thenAccept(order -> {
            responseObserver.onNext(buildResponse(order));
            responseObserver.onCompleted();
        })
        .exceptionally(t -> {
            responseObserver.onError(Status.INTERNAL
                .withCause(t).asRuntimeException());
            return null;
        });
}
```

**错误3：proto 文件用 reserved 但引用了被 reserved 的字段**

```protobuf
// 错误：reserved 后又使用了该字段
message OrderResponse {
  int64 order_id = 1;
  reserved 2;
  string status = 2;  // 编译报错！field 2 is reserved
}
```

**后果**：编译直接失败，这是 Protobuf 的保护机制。

---

## 边界情况和坑

### 坑1：HTTP/2 的最大帧大小限制

**现象**：发送大对象（如大文件、大批量数据）时报错 `RESOURCE_EXHAUSTED`。

**原因**：HTTP/2 默认帧大小 16KB，gRPC 默认消息大小限制 4MB。

```java
// 服务端调大消息限制
Server server = ServerBuilder.forPort(9090)
    .maxInboundMessageSize(64 * 1024 * 1024)  // 64MB
    .build();

// 客户端调大消息限制
ManagedChannel channel = ManagedChannelBuilder.forAddress("localhost", 9090)
    .maxInboundMessageSize(64 * 1024 * 1024)
    .build();
```

### 坑2：gRPC 元数据（Metadata）中文乱码

**现象**：在 Metadata 里传中文，接收方拿到乱码。

**原因**：gRPC 的 Metadata 的 Key 必须是 ASCII 字符，Value 如果用 `ASCII_STRING_MARSHALLER` 只支持 ASCII。

```java
// 错误：Value 含中文
Metadata headers = new Metadata();
headers.put(Metadata.Key.of("user-name", Metadata.ASCII_STRING_MARSHALLER),
    "张三");  // 乱码！

// 正确：用 BinaryMarshaller 传非 ASCII 内容
Metadata headers = new Metadata();
Metadata.Key<byte[]> key = Metadata.Key.of("user-name-bin",
    Metadata.BINARY_BYTE_MARSHALLER);
headers.put(key, "张三".getBytes(StandardCharsets.UTF_8));

// 接收方：
byte[] bytes = headers.get(key);
String name = new String(bytes, StandardCharsets.UTF_8);  // "张三"
```

### 坑3：gRPC 连接断开后的重连

**现象**：服务端重启后，客户端的旧 Channel 无法自动恢复。

**原因**：gRPC 的 Channel 有内部状态机（IDLE → CONNECTING → READY → TRANSIENT_FAILURE），网络断开后会进入 TRANSIENT_FAILURE，然后自动尝试重连。

```java
// 正确配置重连参数
ManagedChannel channel = ManagedChannelBuilder.forAddress("localhost", 9090)
    .keepAliveTime(30, TimeUnit.SECONDS)         // 30秒发一次保活探测
    .keepAliveTimeout(10, TimeUnit.SECONDS)       // 保活探测 10秒超时
    .keepAliveWithoutCalls(true)                  // 没有调用时也发保活
    .retryBufferSize(10 * 1024 * 1024)            // 重试缓冲区大小
    .build();

// gRPC 重连是指数退避，初始 1s，最大 120s，Jitter 防惊群
```

### 坑4：服务端流式调用忘记 onCompleted

**现象**：客户端的 `onNext` 被调用完后，一直卡着不触发 `onCompleted`。

**原因**：服务端忘了调 `responseObserver.onCompleted()`。

```java
// 错误：只调了 onNext，没调 onCompleted
@Override
public void streamOrders(StreamOrdersRequest request,
                         StreamObserver<OrderResponse> responseObserver) {
    for (Order order : orders) {
        responseObserver.onNext(buildResponse(order));
    }
    // 忘了 responseObserver.onCompleted()！
    // 客户端会一直等，不知道流已经结束
}
```

**修复**：循环结束后必须调 `onCompleted()`，这是告诉客户端"流结束"的信号。

---

## 面试话术

**Q：gRPC 和 REST 怎么选？**
"gRPC 适合微服务间内部通信——性能高（Protobuf 二进制序列化，体积比 JSON 小 3-10 倍）、支持流式传输、有强类型接口。REST 适合对外暴露 API——浏览器原生支持、生态最广、调试方便（curl 就能测）。实际项目中通常是内外兼用：对外 REST，内部 gRPC。"

**Q：gRPC 为什么快？**
"两个关键：一是 HTTP/2 的多路复用（一个 TCP 连接并发多个请求，没有队头阻塞）+ 头部压缩（HPACK）；二是 Protobuf 二进制序列化（比 JSON 体积小 3-10 倍，解析快 20-100 倍，用 varint 编码整数，小数字只需要 1-2 字节）。"

**Q：gRPC 的四种调用模式？**
"一元调用（一次请求一次响应，最常用）、服务端流（客户端一个请求，服务端推多条数据）、客户端流（客户端推多条数据，服务端一个响应）、双向流（双方随时发消息，类似 WebSocket）。分别适用于普通查询、实时推送、批量上传、聊天场景。"

**Q：gRPC 的 Deadline 机制？**
"gRPC 用 Deadline 控制超时，不是简单的 timeout。Deadline 可以在整条调用链上传播——客户端设 3 秒，调 A 耗时 0.5 秒，A 调 B 时 B 的 Deadline 自动剩 2.5 秒。任何一个节点超时都直接返回 DEADLINE_EXCEEDED，不会无限放大等待时间。"

**Q：gRPC 和 Dubbo 的区别？**
"gRPC 是跨语言 RPC 框架，基于 HTTP/2 + Protobuf，云原生生态（K8s/Istio）标配。Dubbo 是 Java 生态 RPC 框架，自带服务发现和流量治理，开箱即用。Dubbo 3.x 已经支持 gRPC 协议，两者可以互通。Java 单体技术栈用 Dubbo方便，多语言或云原生场景用 gRPC。"

**Q：Protobuf 怎么保证向前/向后兼容？**
"靠 field_number 不变。新增字段用新编号，旧代码会忽略不认识的字段。删除字段要用 reserved 保留编号，永远不重用。改字段类型不兼容。这个规则和数据库的 Schema 迁移类似——只能加列，不能删列，不能改类型。"

---

## 本文总结

**gRPC** 是 Google 开源的跨语言高性能 RPC 框架，核心要点：

- **序列化**：Protocol Buffers（二进制，varint 编码，比 JSON 小 3-10 倍、快 20-100 倍）
- **协议**：HTTP/2（多路复用、头部压缩、二进制帧、流式传输）
- **调用模式**：一元/服务端流/客户端流/双向流，覆盖所有场景
- **拦截器**：客户端/服务端拦截器，实现认证、链路追踪、日志、限流
- **超时控制**：Deadline 机制，链路传播，不会无限放大
- **负载均衡**：客户端侧 LB，支持 round_robin / pick_first / xDS（Istio）
- **对比**：vs REST → 性能优势大但浏览器不原生支持；vs Dubbo → 跨语言优势但治理能力弱
- **常见坑**：没有 Deadline、阻塞 IO 线程、Channel 不复用、Metadata 中文乱码、流式忘了 onCompleted

**高频面试考点**：gRPC 为什么快（HTTP/2 + Protobuf）、四种调用模式、Deadline 传播机制、与 REST/Dubbo 对比、Protobuf 兼容性规则。

---

**关联文档**：
- [[Dubbo核心原理]]（Java 生态 RPC 框架，可与 gRPC 互通）
- [[Netty核心原理]]（gRPC Java 版底层基于 Netty）
- [[常见中间件综合]]（ZooKeeper/Netty 基础设施）
- [[服务注册与发现]]（微服务层面的注册发现）
- [[API网关设计]]（网关层 gRPC-Web 代理）
- [[服务容错设计]]（熔断/降级/限流）
