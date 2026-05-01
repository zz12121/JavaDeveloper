# Tomcat 核心原理

> Tomcat 是 Apache 基金会下的开源 Java Servlet 容器，实现了 Servlet/JSP 规范，是 Java Web 开发中最常用的 Web 服务器之一。面试重点在于架构设计、类加载隔离、请求处理链路。

---

## 一、整体架构

### 1.1 两大核心组件

```
Tomcat Server
├── Service（对外提供服务）
│   ├── Connector（连接器）—— 接收请求，处理协议
│   │   ├── HTTP/1.1 Connector
│   │   ├── AJP Connector
│   │   └── NIO/APR Connector
│   └── Engine（容器）—— 处理请求
│       ├── Host（虚拟主机，如 localhost）
│       │   ├── Context（Web 应用，如 /myapp）
│       │   │   └── Wrapper（Servlet 包装器）
│       │   └── Context（/other-app）
│       └── Host（www.example.com）
```

**核心思想**：Connector 负责"接收请求"（I/O + 协议解析），Container 负责"处理请求"（Servlet 调用）。二者解耦，一个 Service 可挂多个 Connector。

### 1.2 Server → Service → Engine → Host → Context → Wrapper

| 组件 | 类名 | 职责 | 数量 |
|------|------|------|------|
| **Server** | `StandardServer` | 整个 Tomcat 实例，管理 Service 的生命周期 | 1 |
| **Service** | `StandardService` | 将 Connector 和 Engine 组装，对外提供完整服务 | 1~N |
| **Engine** | `StandardEngine` | 全局 Servlet 引擎，处理所有请求 | 1 |
| **Host** | `StandardHost` | 虚拟主机（域名），如 localhost | 1~N |
| **Context** | `StandardContext` | 单个 Web 应用（WAR 包/目录），对应一个 `/path` | 1~N |
| **Wrapper** | `StandardWrapper` | 封装单个 Servlet 实例 | 1~N |

---

## 二、Connector（连接器）

### 2.1 Coyote 连接器框架

Coyote 是 Tomcat 的连接器框架名称，负责处理底层网络通信和协议解析：

```
Socket → Coyote Adapter → Catalina Container
         ↑
    ProtocolHandler
    ├── Endpoint（网络端点）
    │   ├── NioEndpoint（默认，NIO 模型）
    │   ├── Nio2Endpoint（AIO 模型）
    │   └── AprEndpoint（APR 本地库，性能最佳）
    └── Processor（协议处理器）
        ├── Http11Processor（HTTP/1.1）
        └── AjpProcessor（AJP 协议）
```

### 2.2 三种协议模式

| 模式 | Connector 配置 | 特点 |
|------|----------------|------|
| **NIO** | `protocol="HTTP/1.1"`（默认） | 非阻塞 I/O，基于 Java NIO，Tomcat 8+ 默认 |
| **NIO2** | `protocol="org.apache.coyote.http11.Http11Nio2Protocol"` | 异步 I/O（AIO），Java 7+ |
| **APR** | `protocol="org.apache.coyote.http11.Http11AprProtocol"` | 使用 Apache Portable Runtime（C 库），需安装 native 库，性能最高 |

### 2.3 I/O 模型演进

```
BIO（Tomcat 6 默认）     →  一个请求一个线程，并发能力差
  ↓
NIO（Tomcat 8 默认）     →  少量线程处理大量连接，基于 Poller 事件轮询
  ↓
NIO2                    →  异步非阻塞，回调机制
  ↓
APR                     →  操作系统级别，零拷贝 + sendfile
```

### 2.4 关键参数

```xml
<Connector port="8080" protocol="HTTP/1.1"
    maxThreads="200"        <!-- 最大工作线程数 -->
    minSpareThreads="10"    <!-- 最小空闲线程数 -->
    acceptCount="100"       <!-- 等待队列长度（线程满时排队） -->
    maxConnections="8192"   <!-- 最大连接数（NIO 模式） -->
    connectionTimeout="20000"
    enableLookups="false"   <!-- 关闭 DNS 反查，提升性能 -->
    URIEncoding="UTF-8"
    compression="on"        <!-- 开启 gzip 压缩 -->
    compressionMinSize="2048"
/>
```

---

## 三、Container（容器层级）

### 3.1 Pipeline-Valve 责任链模式

每个容器组件（Engine、Host、Context、Wrapper）内部都有一个 **Pipeline**，Pipeline 中串联多个 **Valve**（阀门）。请求流入时，依次经过每个 Valve 处理，最后到达基础的 Valve（调用下一个容器）：

```
请求 → Engine.Pipeline
         → Valve1 (AccessLogValve)
         → Valve2 (ErrorReportValve)
         → StandardEngineValve (基础阀，传递给匹配的 Host)
              → Host.Pipeline
                  → AccessLogValve
                  → StandardHostValve (传递给匹配的 Context)
                       → Context.Pipeline
                           → StandardContextValve (传递给匹配的 Wrapper)
                                → Wrapper.Pipeline
                                    → StandardWrapperValve (调用 Servlet.service())
```

**设计优势**：
- 每个 Valve 可以独立实现日志、权限、认证等功能
- 类似 Filter 但在容器层面，比 Servlet Filter 更早介入
- 可自定义 Valve 扩展功能（如限流、链路追踪）

### 3.2 四个容器的职责

| 容器 | 职责 | 类比 |
|------|------|------|
| **Engine** | 全局请求入口，路由到 Host | 公司总部 |
| **Host** | 根据域名路由到 Context | 公司某个部门 |
| **Context** | 单个 Web 应用，管理 Servlet 生命周期 | 具体项目组 |
| **Wrapper** | 封装单个 Servlet，调用 `service()` | 具体开发人员 |

---

## 四、请求处理全流程

```
1. 客户端发送 HTTP 请求
       ↓
2. Acceptor 线程接收 Socket，注册到 Poller
       ↓
3. Poller 线程检测到可读事件，交给 Worker 线程池
       ↓
4. Worker 线程调用 Coyote Processor 解析 HTTP 报文
   → 生成 CoyoteAdapter 调用 Catalina Container
       ↓
5. Engine Valve 链处理 → 路由到匹配的 Host
       ↓
6. Host Valve 链处理 → 路由到匹配的 Context（根据 URL path）
       ↓
7. Context Valve 链处理 → 加载并匹配 Filter Chain
       ↓
8. Wrapper Valve 链处理 → 调用 Servlet.service()
       ↓
9. Servlet 处理业务逻辑，返回 Response
       ↓
10. Worker 线程将响应写回 Socket
```

**关键路径**：`Socket → Acceptor → Poller → Worker → Processor → Adapter → Pipeline(Engine → Host → Context → Wrapper) → Servlet`

---

## 五、类加载机制

### 5.1 Tomcat 自定义类加载器

```
BootstrapClassLoader（JVM 启动类加载器）
    ↓
ExtClassLoader（扩展类加载器）
    ↓
AppClassLoader（应用类加载器）
    ↓
CommonClassLoader（Tomcat 公共类加载器）
    ├── CatalinaClassLoader（Tomcat 内部类）    ← 只能向下可见
    └── SharedClassLoader（Web 应用共享类）
            ├── WebAppClassLoader_1（应用1）    ← 每个应用独立
            ├── WebAppClassLoader_2（应用2）
            └── WebAppClassLoader_N（应用N）
```

### 5.2 为什么破坏双亲委派？

**Web 应用隔离需求**：
- 应用 A 用 Spring 4，应用 B 用 Spring 5 → 同名类需要隔离
- Tomcat 自身的类不能被应用覆盖 → CatalinaClassLoader 与 WebAppClassLoader 分离

**WebAppClassLoader 加载顺序**（★ 面试高频）：
```
1. 查本地缓存（已加载的类）
2. 委派给 JVM 底层类加载器（Bootstrap → Ext → App）
3. 委派给 CommonClassLoader（共享库）
4. 自己加载 WEB-INF/classes 和 WEB-INF/lib
5. 如果配置了 delegate="true"（server.xml），则 3 和 4 顺序反转
```

> **默认行为**：先查 JVM 底层，再查 Common，最后自己加载。
> 这意味着应用的类可以覆盖 Tomcat Common 中的类（但覆盖不了 JDK 核心类）。

### 5.3 类加载热点问题

| 问题 | 原因 | 解决方案 |
|------|------|----------|
| `ClassNotFoundException` | 依赖 jar 放错位置 | 确认 WEB-INF/lib |
| `NoClassDefFoundError` | 类初始化失败或静态依赖缺失 | 排查静态代码块 |
| `LinkageError` / 类冲突 | 多个 jar 包含同名类 | `mvn dependency:tree` 排查 |
| 热部署内存泄漏 | WebAppClassLoader 引用未释放 | 升级 Tomcat 版本，避免 ThreadLocal 泄漏 |

---

## 六、线程模型

### 6.1 NioEndpoint 线程架构

```
                    ┌──────────────┐
                    │  Acceptor    │  （默认1个，接收新连接）
                    └──────┬───────┘
                           │ OP_ACCEPT
                    ┌──────▼───────┐
                    │   Poller     │  （默认2个，轮询I/O事件）
                    └──────┬───────┘
                           │ OP_READ / OP_WRITE
                ┌──────────▼──────────┐
                │   Worker Thread Pool │  （maxThreads，处理业务）
                └─────────────────────┘
```

**三阶段模型**：
1. **Acceptor**：阻塞在 `ServerSocket.accept()`，接收新连接，将 Socket 注册到 Poller
2. **Poller**：基于 `Selector`，轮询已注册 Socket 的事件（可读/可写），将就绪事件封装为 SocketProcessor 提交到 Worker 线程池
3. **Worker**：执行 `SocketProcessor.run()`，完成 HTTP 报文解析和业务处理

### 6.2 线程池参数关系

```
客户端请求
    ↓
maxConnections（最大连接数，默认8192）
    ↓ 超出则排队等待
acceptCount（等待队列，默认100）
    ↓ 队列满则拒绝
Connection Refused
    ↓ 在 maxConnections 以内的连接
Worker 线程池处理
    minSpareThreads ←→ maxThreads（默认 10~200）
    ↓
空闲超过 keepAliveTime 则回收（默认60s）
```

> **注意**：`maxConnections` 控制的是连接数，`maxThreads` 控制的是线程数。NIO 模式下连接数可以远大于线程数（一个线程处理多个连接的 I/O 事件）。

---

## 七、Session 管理

### 7.1 Session 实现机制

```
请求到达 → CoyoteAdapter
    → Manager（StandardManager / PersistentManager）
        → 从 Session 池查找 sessionId
            → 找到 → 恢复 Session，传给 Servlet
            → 未找到 → 创建新 Session
```

**Session ID 生成**：默认使用 `SecureRandom` + SHA-256 生成随机 sessionId。

### 7.2 Session 持久化

| 策略 | 配置 | 说明 |
|------|------|------|
| **内存** | 默认 | 重启丢失 |
| **文件** | `PersistentManager` + `FileStore` | 序列化到磁盘 |
| **JDBC** | `PersistentManager` + `JDBCStore` | 存到数据库 |
| **Redis** | 自定义 `SessionManager` | 分布式 Session（Spring Session） |

### 7.3 Session 过期与清理

- **非活跃过期**：`session.getMaxInactiveInterval()`（默认 30 分钟），后台线程定期清理
- **Last Access Time**：每次请求更新访问时间
- **集群同步**：DeltaManager（全量复制，适合小集群） / BackupManager（增量备份）

---

## 八、SpringBoot 内嵌 Tomcat

### 8.1 启动原理

```
@SpringBootApplication
    → @EnableAutoConfiguration
        → SpringApplication.run()
            → SpringBootServletInitializer.onStartup()
                → 创建 Tomcat ServletWebServerFactory
                    → new Tomcat()
                    → tomcat.start()
```

### 8.2 内嵌 vs 独立部署对比

| 维度 | 内嵌 Tomcat（SpringBoot） | 独立 Tomcat |
|------|--------------------------|-------------|
| **部署方式** | `java -jar app.jar` | WAR 包放入 webapps |
| **多应用** | 一个 jar 一个应用 | 一个 Tomcat 可部署多个 WAR |
| **配置方式** | `application.yml` | `server.xml` / `web.xml` |
| **版本控制** | 由 SpringBoot 管理 | 运维独立管理 |
| **适用场景** | 微服务、容器化部署 | 传统企业级应用 |

### 8.3 切换内嵌容器

```xml
<!-- 排除 Tomcat，切换为 Undertow（性能更好，非阻塞） -->
<dependency>
    <groupId>org.springframework.boot</groupId>
    <artifactId>spring-boot-starter-web</artifactId>
    <exclusions>
        <exclusion>
            <groupId>org.springframework.boot</groupId>
            <artifactId>spring-boot-starter-tomcat</artifactId>
        </exclusion>
    </exclusions>
</dependency>
<dependency>
    <groupId>org.springframework.boot</groupId>
    <artifactId>spring-boot-starter-undertow</artifactId>
</dependency>
```

---

## 九、性能调优

### 9.1 连接器调优

```xml
<Connector port="8080" protocol="org.apache.coyote.http11.Http11NioProtocol"
    maxThreads="500"
    minSpareThreads="50"
    acceptCount="200"
    maxConnections="10000"
    connectionTimeout="30000"
    enableLookups="false"
    URIEncoding="UTF-8"
    compression="on"
    compressionMinSize="2048"
    compressibleMimeType="text/html,text/xml,text/plain,application/json"
    keepAliveTimeout="60000"
    maxKeepAliveRequests="100"
/>
```

### 9.2 JVM 调优

```bash
# 设置 Tomcat 的 JVM 参数（catalina.sh 或 setenv.sh）
JAVA_OPTS="-server \
  -Xms2g -Xmx2g \
  -Xmn1g \
  -XX:MetaspaceSize=256m \
  -XX:MaxMetaspaceSize=512m \
  -XX:+UseG1GC \
  -XX:MaxGCPauseMillis=200 \
  -XX:+HeapDumpOnOutOfMemoryError \
  -XX:HeapDumpPath=/tmp/tomcat_heapdump.hprof"
```

### 9.3 应用层优化

| 优化点 | 措施 |
|--------|------|
| **静态资源** | 开启 gzip、使用 CDN、浏览器缓存（Cache-Control） |
| **JSP 编译** | 预编译 JSP（`jspc`），生产环境避免 JSP |
| **连接池** | HikariCP 配置（maxPoolSize、connectionTimeout） |
| **热部署** | 生产环境**关闭** autoDeploy 和 reloadable |
| **日志** | 使用 Logback 异步 Appender，减少 I/O 阻塞 |

### 9.4 监控指标

```bash
# JMX 监控关键指标
- tomcat.threads.busy           # 忙碌线程数
- tomcat.threads.current        # 当前线程数
- tomcat.threads.config.max     # 最大线程数
- tomcat.requests.count         # 请求总数
- tomcat.requests.errorCount    # 错误请求数
- tomcat.requests.processingTime # 处理耗时
- tomcat.global.sent.bytes      # 发送字节数
```

---

## 十、热部署原理

### 10.1 触发机制

```
1. BackgroundProcessor（后台线程）定期检查
    → Context 的 web.xml、classes、lib 是否变化
2. 检测到变化
    → 调用 Context.stop()
    → 卸载 WebAppClassLoader
    → 重新创建 WebAppClassLoader
    → 调用 Context.start()
    → 重新加载应用
```

### 10.2 热部署的风险

- **内存泄漏**：旧 WebAppClassLoader 的引用未完全释放（ThreadLocal、JDBC Driver、静态集合）
- **类加载异常**：旧的类与新类不兼容
- **生产环境建议**：**关闭热部署**，使用蓝绿部署或滚动更新

```xml
<!-- 关闭自动部署 -->
<Host name="localhost" appBase="webapps"
    autoDeploy="false"
    unpackWARs="true">
    <Context docBase="/app/myapp" reloadable="false" />
</Host>
```

---

## 十一、Tomcat vs Jetty vs Undertow

| 维度 | Tomcat | Jetty | Undertow |
|------|--------|-------|----------|
| **架构** | 四层容器（Engine/Host/Context/Wrapper） | Handler 链式结构 | Handler 链式 + XNIO |
| **性能** | 成熟稳定，高并发优秀 | 轻量，低延迟 | 性能最优（非阻塞 I/O） |
| **标准支持** | Servlet 5.0+（完整） | Servlet 5.0+ | Servlet 5.0+ |
| **WebSocket** | 原生支持 | 原生支持 | 原生支持 |
| **嵌入式** | SpringBoot 默认 | Maven 插件常用 | SpringBoot 可选 |
| **异步** | NIO / NIO2 / APR | Continuations / NIO | XNIO（基于 NIO.2） |
| **适用场景** | 企业级、全功能 | 云原生、轻量 | 高性能、微服务 |
| **社区** | Apache，最大 | Eclipse | JBoss/Red Hat |

**选型建议**：
- **默认选 Tomcat**：生态最成熟，社区最大，SpringBoot 默认集成
- **选 Jetty**：需要高度定制化、嵌入到各种框架/设备中
- **选 Undertow**：极致性能需求，微服务场景，非阻塞 I/O 优势明显

---

## 十二、面试高频问题

### Q1：讲一下 Tomcat 的整体架构

> Tomcat 由 **Server → Service → Engine → Host → Context → Wrapper** 组成。核心是 **Connector + Container** 的解耦设计：Connector（Coyote）负责接收请求、协议解析；Container（Catalina）负责 Servlet 调用。Container 内部使用 **Pipeline-Valve 责任链模式**，请求经过 Engine → Host → Context → Wrapper 逐层处理，最终到达 Servlet。一个 Service 可以挂多个 Connector，实现多协议支持。

### Q2：Tomcat 的类加载机制为什么破坏双亲委派？

> Web 应用场景下需要**类隔离**：不同应用可能依赖同名类的不同版本（如 Spring 4 和 5），必须保证互不影响。Tomcat 的 **WebAppClassLoader** 加载顺序是：先查 JVM 底层加载器 → 再查 CommonClassLoader → 最后自己从 WEB-INF 加载。这样应用自己的类可以覆盖 Common 中的类，但无法覆盖 JDK 核心类。每个 Web 应用有独立的 WebAppClassLoader，实现了应用间类隔离。

### Q3：NIO 模式下 Tomcat 的线程模型是怎样的？

> NioEndpoint 采用 **三阶段线程模型**：① **Acceptor**（1个线程）负责接收新连接，将 Socket 注册到 Poller；② **Poller**（默认2个）基于 Selector 轮询 I/O 事件，将就绪的 Socket 封装为 SocketProcessor 提交到 Worker 线程池；③ **Worker 线程池**处理实际的 HTTP 解析和业务逻辑。`maxConnections` 控制连接数（8192），`maxThreads` 控制线程数（200），NIO 模式下连接数远大于线程数。

### Q4：一个 HTTP 请求在 Tomcat 中是怎么流转的？

> Socket 被 Acceptor 接收 → Poller 检测到可读事件 → Worker 线程调用 Coyote Processor 解析 HTTP 报文 → 生成 `CoyoteAdapter` 调用 Catalina Engine → Engine Pipeline 依次经过各 Valve → StandardEngineValve 路由到 Host → Host Pipeline → StandardHostValve 路由到 Context → Context Pipeline 经过 Filter Chain → StandardWrapperValve 调用 `Servlet.service()` → 响应原路返回。

### Q5：Tomcat 怎么实现热部署？

> Tomcat 后台线程（BackgroundProcessor）定期检查 Web 应用的 WEB-INF/classes、WEB-INF/lib、web.xml 是否有变化。检测到变化后调用 `Context.stop()` 卸载应用（包括 WebAppClassLoader），然后重新创建 WebAppClassLoader 并调用 `Context.start()` 重新加载。**生产环境建议关闭热部署**，因为频繁加载卸载容易导致内存泄漏（ThreadLocal 未清理、JDBC Driver 未注销等）。

### Q6：Tomcat、Jetty、Undertow 怎么选？

> **默认选 Tomcat**——生态最成熟、社区最大、SpringBoot 默认、文档丰富。**Jetty 适合需要高度定制和嵌入场景**，架构更灵活（Handler 链）。**Undertow 性能最优**，基于 XNIO 非阻塞模型，适合微服务和高并发场景。实际项目 95% 以上用 Tomcat 就够了，除非有明确的性能瓶颈或架构需求。

### Q7：SpringBoot 内嵌 Tomcat 和独立部署有什么区别？

> 内嵌 Tomcat 由 Spring 容器管理生命周期，`java -jar` 一键启动，适合微服务和容器化部署，一个 jar 一个应用。独立部署是运行独立的 Tomcat 进程，将 WAR 包放入 webapps 目录，支持多应用部署，通过 server.xml 统一管理配置。微服务时代内嵌已成为主流。

### Q8：如何调优 Tomcat？

> 四个层面：① **连接器**：增大 maxThreads（200→500）、acceptCount（100→200）、开启 gzip 压缩、关闭 DNS 反查；② **JVM**：堆大小固定（-Xms = -Xmx）、选用 G1 收集器、设置 Metaspace 大小；③ **应用层**：数据库连接池调优、关闭热部署、异步日志；④ **运维**：JMX 监控线程数/请求量/错误率，设置 HeapDump 预留排查手段。

---

## 知识关联

- **Servlet 规范**：Tomcat 实现了 Servlet 容器规范，Filter、Listener、ServletContext 是 Servlet 核心概念
- **NIO 与 Netty**：Tomcat 9 的 NIO 模型与 Netty 的 Reactor 线程模型有相似之处（都是 Acceptor + Poller + Worker），但 Tomcat 偏重 HTTP 协议处理，Netty 更通用
- **SpringBoot 自动配置**：`ServletWebServerFactoryAutoConfiguration` 自动创建内嵌 Tomcat 实例
- **JVM 类加载**：Tomcat 的自定义类加载器是面试中"双亲委派模型"最经典的"破坏案例"
