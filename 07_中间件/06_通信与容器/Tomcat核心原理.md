# Tomcat 核心原理

> Tomcat 是 Java Web 开发中最常用的 Servlet 容器。理解它的架构设计、类加载隔离、请求处理链路，是排查线上性能问题和理解 SpringBoot 内嵌原理的基础。

---

## 这个问题为什么存在？

Java Servlet 规范定义了 Web 应用如何接收 HTTP 请求、处理业务、返回响应。但规范只是接口，需要一个**具体的运行容器**来：

1. **管理 HTTP 连接**——监听端口、解析 HTTP 报文、维持 TCP 连接
2. **管理 Web 应用生命周期**——部署、启动、停止、卸载
3. **隔离不同应用**——应用 A 用 Spring 4，应用 B 用 Spring 5，同名类不能互相干扰
4. **调用 Servlet**——将 HTTP 请求路由到正确的 Servlet，执行业务逻辑

Tomcat 就是这个容器。它的核心设计问题是：**如何把"网络通信"和"业务处理"解耦**，让二者独立扩展。

---

## 它是怎么解决问题的？

### Connector + Container：核心解耦

Tomcat 的顶层结构是 **Server → Service → Engine → Host → Context → Wrapper**：

```
Tomcat Server
├── Service（对外提供完整服务）
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

**核心思想**：Connector 负责"接收请求"（I/O + 协议解析），Container 负责"处理请求"（Servlet 调用）。二者通过 CoyoteAdapter 连接，解耦后一个 Service 可挂多个 Connector。

### Connector：Coyote 连接器

Coyote 是 Tomcat 的连接器框架，负责底层网络通信和协议解析：

```
Socket → Coyote Adapter → Catalina Container
         ↑
    ProtocolHandler
    ├── Endpoint（网络端点）
    │   ├── NioEndpoint（默认，NIO 模型）
    │   ├── Nio2Endpoint（AIO 模式）
    │   └── AprEndpoint（APR 本地库，性能最佳）
    └── Processor（协议处理器）
        ├── Http11Processor（HTTP/1.1）
        └── AjpProcessor（AJP 协议）
```

三种 I/O 模型演进：BIO（Tomcat 6 默认，一请求一线程）→ NIO（Tomcat 8 默认，少量线程处理大量连接）→ NIO2（异步非阻塞）→ APR（操作系统级别，零拷贝 + sendfile）。

### Container：Pipeline-Valve 责任链

每个容器组件内部都有一个 **Pipeline**，串联多个 **Valve**（阀门）：

```
请求 → Engine.Pipeline (AccessLog → ErrorReport → StandardEngineValve)
         → Host.Pipeline (AccessLog → StandardHostValve)
              → Context.Pipeline (StandardContextValve → Filter Chain)
                   → Wrapper.Pipeline (StandardWrapperValve → Servlet.service())
```

设计优势：每个 Valve 独立实现日志、权限、认证等功能，可自定义扩展（如限流、链路追踪）。

### 请求处理全流程

```
Socket → Acceptor(接收) → Poller(轮询I/O事件) → Worker(业务线程池)
  → Coyote Processor(解析HTTP) → CoyoteAdapter
  → Engine Pipeline → Host Pipeline → Context Pipeline → Wrapper Pipeline
  → Filter Chain → Servlet.service()
  → 响应原路返回
```

### SpringBoot 内嵌 Tomcat

```
@SpringBootApplication → @EnableAutoConfiguration
  → SpringApplication.run()
    → 创建 Tomcat ServletWebServerFactory → new Tomcat() → tomcat.start()
```

| 维度 | 内嵌 Tomcat（SpringBoot） | 独立 Tomcat |
|------|--------------------------|-------------|
| **部署方式** | `java -jar app.jar` | WAR 包放入 webapps |
| **多应用** | 一个 jar 一个应用 | 一个 Tomcat 多个 WAR |
| **配置** | `application.yml` | `server.xml` / `web.xml` |
| **适用** | 微服务、容器化 | 传统企业级应用 |

---

## 深入原理

### NIO 线程模型：三阶段架构

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

- **Acceptor**：阻塞在 `ServerSocket.accept()`，接收新连接
- **Poller**：基于 `Selector` 轮询 I/O 事件，将就绪事件封装为 SocketProcessor 提交到 Worker 线程池
- **Worker**：执行 HTTP 报文解析和业务处理

`maxConnections`（默认 8192）控制连接数，`maxThreads`（默认 200）控制线程数。NIO 模式下连接数远大于线程数。

### 类加载机制：为什么破坏双亲委派？

```
BootstrapClassLoader → ExtClassLoader → AppClassLoader → CommonClassLoader
    ├── CatalinaClassLoader（Tomcat 内部类，不向 Web 应用可见）
    └── SharedClassLoader（Web 应用共享类）
            ├── WebAppClassLoader_1（应用1独立）
            ├── WebAppClassLoader_2（应用2独立）
            └── WebAppClassLoader_N（应用N独立）
```

**破坏的原因**：Web 应用隔离需求——应用 A 用 Spring 4，应用 B 用 Spring 5，同名类必须隔离。

**WebAppClassLoader 加载顺序**：① 查本地缓存 → ② 委派给 JVM 底层加载器 → ③ 委派给 CommonClassLoader → ④ 自己加载 WEB-INF/classes 和 WEB-INF/lib。应用类可覆盖 Common 中的类，但不能覆盖 JDK 核心类。

### Session 管理

Session 过期机制：`session.getMaxInactiveInterval()`（默认 30 分钟），后台线程定期清理。集群中 DeltaManager 全量复制（小集群）或 BackupManager 增量备份。分布式场景使用 Spring Session + Redis。

---

## 正确使用方式

### 连接器参数调优

```xml
<Connector port="8080" protocol="HTTP/1.1"
    maxThreads="500"        <!-- 200→500 -->
    minSpareThreads="50"
    acceptCount="200"       <!-- 100→200 -->
    maxConnections="10000"
    connectionTimeout="30000"
    enableLookups="false"   <!-- 关闭 DNS 反查 -->
    URIEncoding="UTF-8"
    compression="on"        <!-- gzip 压缩 -->
    compressionMinSize="2048"
    compressibleMimeType="text/html,text/xml,text/plain,application/json"
/>
```

### JVM 调优

```bash
JAVA_OPTS="-server -Xms2g -Xmx2g -Xmn1g \
  -XX:MetaspaceSize=256m -XX:MaxMetaspaceSize=512m \
  -XX:+UseG1GC -XX:MaxGCPauseMillis=200 \
  -XX:+HeapDumpOnOutOfMemoryError \
  -XX:HeapDumpPath=/tmp/tomcat_heapdump.hprof"
```

### 应用层优化

| 优化点 | 措施 |
|--------|------|
| 静态资源 | gzip 压缩、CDN、浏览器缓存（Cache-Control） |
| JSP | 预编译，生产环境避免 JSP |
| 连接池 | HikariCP 配置 maxPoolSize、connectionTimeout |
| 热部署 | 生产环境**关闭** autoDeploy 和 reloadable |
| 日志 | Logback 异步 Appender |

### Tomcat vs Jetty vs Undertow 选型

- **默认选 Tomcat**：生态最成熟，社区最大，SpringBoot 默认
- **选 Jetty**：需要高度定制化、嵌入到各种框架中
- **选 Undertow**：极致性能需求，基于 XNIO 非阻塞 I/O

---

## 边界情况和坑

### 热部署导致内存泄漏

**现象**：频繁热部署后 OOM，或者 `PermGen/Metaspace` 持续增长。

**成因**：Tomcat 后台线程（BackgroundProcessor）检测到文件变化后，卸载旧 `WebAppClassLoader` 并创建新的。但旧 ClassLoader 的引用可能没完全释放——ThreadLocal 未清理、JDBC Driver 未注销、静态集合持有引用。

**解决**：生产环境**关闭热部署**，使用蓝绿部署或滚动更新。

```xml
<Host name="localhost" appBase="webapps"
    autoDeploy="false" unpackWARs="true">
    <Context docBase="/app/myapp" reloadable="false" />
</Host>
```

### 类加载冲突

| 问题 | 成因 | 解决 |
|------|------|------|
| `ClassNotFoundException` | 依赖 jar 放错位置 | 确认 WEB-INF/lib |
| `NoClassDefFoundError` | 类初始化失败或静态依赖缺失 | 排查静态代码块 |
| `LinkageError` | 多个 jar 包含同名类 | `mvn dependency:tree` 排查 |
| 热部署 OOM | WebAppClassLoader 引用未释放 | 升级 Tomcat，避免 ThreadLocal 泄漏 |

### maxThreads vs maxConnections 混淆

`maxConnections` 控制连接数（NIO 模式默认 8192），`maxThreads` 控制线程数（默认 200）。连接数可以远大于线程数。但线程满时新请求排在 `acceptCount` 队列（默认 100），队列也满则 `Connection Refused`。

### 连接数计算参考

```
预期并发量 × 平均响应时间(秒) = 所需线程数
例如：1000 QPS × 0.05s = 50 线程（理论最小值）
生产建议：理论值 × 2~3 = 100~150 线程
maxThreads 设 300~500 足够应对突发流量
```
