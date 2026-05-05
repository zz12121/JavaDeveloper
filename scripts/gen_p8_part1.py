import os

base_dir = r"E:\obsidian\JavaDeveloper\11_实战专题"

topics = [
    # ========== 01 Java核心 ==========
    {
        "filename": "20_插件化架构设计.md",
        "title": "插件化架构设计",
        "intro": "插件化架构的核心是：**隔离 + 通信 + 生命周期管理**。通过自定义 ClassLoader 实现插件隔离，通过接口契约实现通信，通过生命周期回调管理插件的加载/激活/卸载。",
        "sections": [
            ("架构设计", """
```
┌─────────────────────────────────────────────┐
│              宿主应用（Host）               │
│  ┌──────────┐  ┌──────────┐  ┌────────┐ │
│  │ 核心业务  │  │ 插件管理  │  │ 通信总线 │ │
│  └──────────┘  └──────────┘  └────────┘ │
└──────────────────────┬──────────────────────┘
                       │ 插件接口（契约）
         ┌─────────────┼─────────────┐
         ▼             ▼             ▼
  ┌──────────┐  ┌──────────┐  ┌──────────┐
  │ 插件 A    │  │ 插件 B    │  │ 插件 C    │
  │ ClassLoader│  │ ClassLoader│  │ ClassLoader│
  └──────────┘  └──────────┘  └──────────┘
```
"""),
            ("场景 A：插件隔离（防止依赖冲突）", """
### 现象
```
插件 A 依赖 fastjson 1.2.8
插件 B 依赖 fastjson 2.0.4
放在同一个 classpath → 冲突 → NoSuchMethodError
```
### 解决方案：自定义 ClassLoader
```java
public class PluginClassLoader extends URLClassLoader {
    private final String pluginName;
    
    public PluginClassLoader(String pluginName, URL[] urls, ClassLoader parent) {
        super(urls, parent);  // parent = 宿主的 ClassLoader
        this.pluginName = pluginName;
    }
    
    @Override
    protected Class<?> loadClass(String name) throws ClassNotFoundException {
        // 1. JDK 核心类委派给父加载器（双亲委派）
        if (name.startsWith("java.")) {
            return super.loadClass(name);
        }
        // 2. 插件自己的类优先加载（破坏双亲委派）
        Class<?> clazz = findClass(name);
        if (clazz != null) {
            return clazz;
        }
        // 3. 找不到再委派父加载器
        return super.loadClass(name);
    }
}
```
**关键点**：parent 设为宿主 ClassLoader，这样插件可以访问宿主导出的接口（契约），但插件之间的类互相隔离。
"""),
            ("场景 B：热卸载插件（防止内存泄漏）", """
### 现象
```
卸载插件后，GC 仍无法回收 PluginClassLoader
原因：静态变量 / 线程 / JNI 全局引用 持有 ClassLoader 引用
```
### 解决方案
```java
public class PluginManager {
    private final Map<String, PluginClassLoader> classLoaders = new ConcurrentHashMap<>();
    
    public void unloadPlugin(String pluginName) {
        PluginClassLoader loader = classLoaders.remove(pluginName);
        if (loader == null) return;
        
        // 1. 停止插件内的线程
        Thread.getAllStackTraces().keySet().forEach(t -> {
            if (t.getClass().getClassLoader() == loader) {
                t.interrupt();
            }
        });
        
        // 2. 清理静态缓存（如果插件用了单例 / 缓存）
        // 约定：插件必须实现 Plugin 接口，提供 destroy() 钩子
        Plugin plugin = activePlugins.remove(pluginName);
        if (plugin != null) {
            plugin.destroy();
        }
        
        // 3. 清空 ClassLoader 引用（让 GC 回收）
        try {
            loader.close();  // JDK 7+，关闭 JAR 文件句柄
        } catch (IOException e) {
            log.warn("关闭插件 ClassLoader 失败", e);
        }
        
        // 4. 建议：卸载后重启应用（最彻底）
        log.info("插件 {} 已卸载，建议重启应用以完全释放资源", pluginName);
    }
}
```
**为什么无法完全热卸载**：Java 规范不保证 ClassLoader 能被 GC（只要有任何引用残留）。生产环境最可靠的方式是：**OSGi 框架** 或 **进程级隔离**（每个插件独立进程，通过 IPC 通信）。
"""),
            ("场景 C：插件通信（契约接口设计）", """
### 设计原则
```
宿主定义接口（契约） → 放在独立的 API jar 里
插件实现接口 → 通过 META-INF/services 或注解发现
宿主通过接口调用插件 → 完全解耦
```
### 代码示例
```java
// ===== 宿主定义契约（单独打包，插件依赖此 jar）=====
public interface PluginService {
    String getName();
    void init(PluginContext context);
    void execute(Map<String, Object> params);
    void destroy();
}

// ===== 插件实现 =====
public class HelloPlugin implements PluginService {
    private PluginContext context;
    
    @Override
    public String getName() { return "hello-plugin"; }
    
    @Override
    public void init(PluginContext context) {
        this.context = context;
        context.log("HelloPlugin initialized");
    }
    
    @Override
    public void execute(Map<String, Object> params) {
        context.log("HelloPlugin execute: " + params);
    }
    
    @Override
    public void destroy() {
        context.log("HelloPlugin destroyed");
    }
}

// META-INF/services/com.example.PluginService
// 内容：com.example.plugin.HelloPlugin
```
```java
// ===== 宿主加载插件（ServiceLoader）=====
public class PluginManager {
    private final Map<String, PluginService> plugins = new HashMap<>();
    
    public void loadPlugins(String pluginDir) {
        File dir = new File(pluginDir);
        File[] jars = dir.listFiles((d, name) -> name.endsWith(".jar"));
        
        for (File jar : jars) {
            try {
                URLClassLoader loader = new URLClassLoader(
                    new URL[]{jar.toURI().toURL()},
                    this.getClass().getClassLoader()
                );
                
                ServiceLoader<PluginService> services = 
                    ServiceLoader.load(PluginService.class, loader);
                
                for (PluginService plugin : services) {
                    plugin.init(new DefaultPluginContext());
                    plugins.put(plugin.getName(), plugin);
                    log.info("加载插件: {}", plugin.getName());
                }
            } catch (Exception e) {
                log.error("加载插件失败: " + jar.getName(), e);
            }
        }
    }
}
```
"""),
        ]
    },
    {
        "filename": "21_RPC框架通信层设计.md",
        "title": "RPC 框架通信层设计",
        "intro": "RPC 框架通信层的核心是：**NIO Reactor 模型 + 自定义协议 + 连接池管理**。Netty 是最主流的实现选择，需要解决粘包拆包、心跳保活、断线重连等问题。",
        "sections": [
            ("架构设计", """
```
┌─────────────────────────────────────────────────┐
│                Client 端                      │
│  │
│  ┌──────────┐    ┌──────────┐    ┌────────┐ │
│  │ Stub 代理 │───→│ 编解码    │───→│ 连接池  │ │
│  └──────────┘    └──────────┘    └───┬────┘ │
│               │
│               ▼
│           ┌────────┐
│           │  IO 线程│（Reactor 线程组）
│           └────────┘
└──────────────────────┬──────────────────────────┘
                       │ TCP 连接
                       ▼
┌─────────────────────────────────────────────────┐
│                Server 端                      │
│               │
│           ┌────────┐
│           │  IO 线程│（Boss 线程组）
│           └───┬────┘
│               │ 接受连接
│           ┌───▼────┐
│           │工作线程  │（Worker 线程组）
│           └───┬────┘
│               │
│           ┌───▼────┐    ┌──────────┐
│           │ 解码器  │───→│ 业务线程池│
│           └────────┘    └──────────┘
└─────────────────────────────────────────────────┘
```
"""),
            ("场景 A：粘包拆包问题", """
### 现象
```
发送端发 2 个包：[Hello][World]
接收端可能收到：[HelloWo] [rld]  （拆包）
              或：[HelloWorld]        （粘包）
```
### 解决方案：自定义协议 + 长度字段
```
协议格式：
+--------+--------+--------+--------+--------+------------+
| 魔数(2B) | 版本(1B) | 类型(1B) |  长度(4B)  |    Body   |
+--------+--------+--------+--------+--------+------------+
```
```java
// Netty 实现：长度字段解码器（解决粘拆包）
public class RpcDecoder extends ByteToMessageDecoder {
    private static final int MAGIC = 0xCAFE;
    private static final int HEADER_SIZE = 8;  // 魔数2 + 版本1 + 类型1 + 长度4
    
    @Override
    protected void decode(ChannelHandlerContext ctx, ByteBuf in, 
                         List<Object> out) throws Exception {
        if (in.readableBytes() < HEADER_SIZE) return;
        
        in.markReaderIndex();
        
        int magic = in.readShort();
        if (magic != MAGIC) {
            throw new IllegalStateException("非法魔数: " + magic);
        }
        
        byte version = in.readByte();
        byte type = in.readByte();
        int length = in.readInt();
        
        if (in.readableBytes() < length) {
            in.resetReaderIndex();  // 数据不够，等待下次
            return;
        }
        
        byte[] body = new byte[length];
        in.readBytes(body);
        out.add(new RpcMessage(version, type, body));
    }
}

// Netty 内置方案（推荐）：LengthFieldBasedFrameDecoder
// 自动处理粘拆包，无需手写 decode
new LengthFieldBasedFrameDecoder(
    8 * 1024,   // 最大帧长度
    4,           // 长度字段偏移量（魔数2+版本1+类型1 = 4）
    4,           // 长度字段长度
    0,           // 长度调整（0 = 长度字段后面的就是 body）
    0            // 需要跳过的初始字节数
);
```
"""),
            ("场景 B：心跳保活与断线重连", """
### 问题
```
NAT 超时（移动网络 5 分钟无数据 → 连接被运营商回收）
需要心跳保活；连接断开后需要自动重连
```
### 解决方案
```java
// 心跳处理器（IdleStateHandler 检测空闲）
public class HeartbeatHandler extends IdleStateHandler {
    // 读空闲 60s / 写空闲 30s / 全空闲 0（不检测）
    public HeartbeatHandler() {
        super(60, 30, 0, TimeUnit.SECONDS);
    }
    
    @Override
    protected void channelIdle(ChannelHandlerContext ctx, 
                              IdleStateEvent evt) {
        if (evt == IdleState.READER_IDLE) {
            // 60秒没收到数据 → 连接可能已死 → 关闭
            ctx.close();
        } else if (evt == IdleState.WRITER_IDLE) {
            // 30秒没写数据 → 发心跳
            ctx.writeAndFlush(new HeartbeatMessage());
        }
    }
}

// 断线重连（ChannelInboundHandlerAdapter）
public class ReconnectHandler extends ChannelInboundHandlerAdapter {
    private final String host;
    private final int port;
    private final Bootstrap bootstrap;
    
    @Override
    public void channelInactive(ChannelHandlerContext ctx) {
        // 连接断开 → 指数退避重连
        scheduleReconnect(ctx.channel().eventLoop());
    }
    
    private void scheduleReconnect(EventLoop eventLoop) {
        eventLoop.schedule(() -> {
            bootstrap.connect(host, port).addListener(future -> {
                if (!future.isSuccess()) {
                    // 连接失败 → 继续重试（指数退避）
                    scheduleReconnect(eventLoop);
                }
            });
        }, 5, TimeUnit.SECONDS);  // 首次 5 秒，后续可指数退避
    }
}
```
"""),
            ("场景 C：连接池设计", """
### 设计要点
```
1. 连接复用（避免每次请求都建 TCP 连接）
2. 连接保活（心跳）
3. 连接数量控制（防止把对端打挂）
4. 故障节点自动摘除（熔断）
```
```java
@Component
public class RpcConnectionPool {
    private final Map<String, ConcurrentLinkedQueue<Channel>> pools 
        = new ConcurrentHashMap<>();
    private final Map<Channel, Long> lastActiveTime 
        = new ConcurrentHashMap<>();
    
    private static final int MAX_CONNECTIONS_PER_NODE = 10;
    private static final long IDLE_TIMEOUT = 60_000;  // 60秒空闲关闭
    
    public Channel getConnection(String host, int port) {
        String key = host + ":" + port;
        ConcurrentLinkedQueue<Channel> queue = pools.computeIfAbsent(
            key, k -> new ConcurrentLinkedQueue<>());
        
        // 1. 尝试复用空闲连接
        while (!queue.isEmpty()) {
            Channel ch = queue.poll();
            if (ch.isActive()) {
                lastActiveTime.put(ch, System.currentTimeMillis());
                return ch;
            }
            // 连接已断开，继续取下一个
        }
        
        // 2. 没有可用连接 → 新建（受限于最大连接数）
        if (queue.size() < MAX_CONNECTIONS_PER_NODE) {
            return createNewConnection(host, port, queue);
        }
        
        // 3. 超过最大连接数 → 等待（或抛异常）
        throw new RpcException("连接池已满: " + key);
    }
    
    public void returnConnection(Channel channel) {
        String key = channel.remoteAddress().toString();
        ConcurrentLinkedQueue<Channel> queue = pools.get(key);
        if (queue != null && channel.isActive()) {
            queue.offer(channel);
        }
    }
    
    // 定期清理空闲连接
    @Scheduled(fixedDelay = 30_000)
    public void cleanIdleConnections() {
        lastActiveTime.forEach((channel, lastTime) -> {
            if (System.currentTimeMillis() - lastTime > IDLE_TIMEOUT) {
                channel.close();
                lastActiveTime.remove(channel);
            }
        });
    }
}
```
"""),
        ]
    },
    {
        "filename": "22_注解权限控制框架设计.md",
        "title": "注解权限控制框架设计",
        "intro": "基于注解的权限控制框架，核心是 **编译期代码生成（APT/Lombok）或运行期 AOP 拦截**。关键点：权限模型设计（RBAC）、注解定义、权限校验逻辑、无侵入集成。",
        "sections": [
            ("架构设计", """
```
┌─────────────────────────────────────────────┐
│              权限控制框架                   │
│                              │
│  ┌──────────────┐    ┌──────────────┐   │
│  │  注解定义     │    │  权限校验     │   │
│  │  @RequireRole │    │  (拦截器/AOP)│   │
│  │  @RequirePerm │    └──────┬───────┘   │
│  └──────────────┘           │             │
│                              │ 查询       │
│               ┌──────────────▼───────┐     │
│               │   权限存储           │     │
│               │  (DB / Redis)      │     │
│               └────────────────────┘     │
└─────────────────────────────────────────────┘
```
"""),
            ("场景 A：注解定义与 AOP 拦截（运行期方案）", """
### 方案选择
```
运行期 AOP（Spring 项目，简单快速）
  - 优点：实现简单，用 Spring AOP 或 Interceptor
  - 缺点：运行时反射有性能开销，权限数据每次都要查

编译期代码生成（APT / Lombok，性能最好）
  - 优点：编译期生成权限校验代码，运行时零反射
  - 缺点：实现复杂，需要写 APT 处理器
```
### 运行期方案（推荐，大部分场景够用）
```java
// 1. 定义注解
@Target(ElementType.METHOD)
@Retention(RetentionPolicy.RUNTIME)
public @interface RequireRole {
    String[] value();  // 允许的角色
}

@Target(ElementType.METHOD)
@Retention(RetentionPolicy.RUNTIME)
public @interface RequirePermission {
    String[] value();  // 允许的权限
}

// 2. AOP 拦截
@Aspect
@Component
public class PermissionAspect {
    @Autowired
    private PermissionService permissionService;
    
    @Around("@annotation(requireRole)")
    public Object checkRole(ProceedingJoinPoint pjp, 
                           RequireRole requireRole) throws Throwable {
        String[] requiredRoles = requireRole.value();
        
        // 获取当前用户（从 ThreadLocal / SecurityContext）
        User user = SecurityContext.getCurrentUser();
        if (user == null) {
            throw new UnauthorizedException("用户未登录");
        }
        
        // 校验角色（用户角色 vs 接口要求的角色）
        boolean hasRole = Arrays.stream(requiredRoles)
            .anyMatch(role -> user.hasRole(role));
        
        if (!hasRole) {
            throw new ForbiddenException("权限不足，需要角色: " 
                + String.join(", ", requiredRoles));
        }
        
        return pjp.proceed();
    }
    
    @Around("@annotation(requirePerm)")
    public Object checkPermission(ProceedingJoinPoint pjp,
                                 RequirePermission requirePerm) {
        // 类似逻辑，校验具体权限点
        // 权限可以细到：user:create, order:delete 等
        return pjp.proceed();
    }
}

// 3. 使用
@RestController
public class AdminController {
    @GetMapping("/admin/users")
    @RequireRole("admin")
    public List<User> listUsers() { ... }
    
    @DeleteMapping("/admin/user/{id}")
    @RequirePermission("user:delete")
    public Result deleteUser(@PathVariable Long id) { ... }
}
```
"""),
            ("场景 B：权限模型设计（RBAC）", """
### RBAC（Role-Based Access Control）核心表设计
```sql
-- 用户表
CREATE TABLE sys_user (
    id BIGINT PRIMARY KEY,
    username VARCHAR(50) NOT NULL,
    ...
);

-- 角色表
CREATE TABLE sys_role (
    id BIGINT PRIMARY KEY,
    role_code VARCHAR(50) NOT NULL UNIQUE,  -- 如 'admin', 'developer'
    role_name VARCHAR(100)
);

-- 权限表（细粒度）
CREATE TABLE sys_permission (
    id BIGINT PRIMARY KEY,
    perm_code VARCHAR(100) NOT NULL UNIQUE,  -- 如 'user:create'
    perm_name VARCHAR(100)
);

-- 用户-角色 关联
CREATE TABLE sys_user_role (
    user_id BIGINT,
    role_id BIGINT,
    PRIMARY KEY (user_id, role_id)
);

-- 角色-权限 关联
CREATE TABLE sys_role_permission (
    role_id BIGINT,
    permission_id BIGINT,
    PRIMARY KEY (role_id, permission_id)
);
```
### 优化：权限缓存
```java
@Service
public class PermissionService {
    // 缓存：userId -> Set<permissionCode>
    private final LoadingCache<Long, Set<String>> permCache =
        CacheBuilder.newBuilder()
            .maximumSize(10_000)
            .expireAfterWrite(5, TimeUnit.MINUTES)
            .build(this::loadPermissions);
    
    public boolean hasPermission(Long userId, String permCode) {
        return permCache.getUnchecked(userId).contains(permCode);
    }
}
```
"""),
            ("场景 C：编译期方案（Lombok 风格，进阶）", """
### 原理
```
1. 定义注解 @RequireRole
2. 写 APT（Annotation Processing Tool）
   - 在编译期扫描带 @RequireRole 的方法
   - 生成权限校验的代码（插入到方法开头）
3. 编译后的 .class 文件里，方法开头已经有校验逻辑
4. 运行时零反射，性能最好
```
### 简化示例（Lombok 原理）
```java
// 编译前
@RequireRole("admin")
public void deleteUser(Long id) { ... }

// 编译后（Lombok 或 APT 自动生成）
public void deleteUser(Long id) {
    // 自动插入的权限校验代码
    if (!SecurityContext.getCurrentUser().hasRole("admin")) {
        throw new ForbiddenException("权限不足");
    }
    ...  // 原方法体
}
```
**实现复杂度高**，一般用运行期 AOP 方案就够了。只有对性能要求极高的框架级项目才需要编译期方案。
"""),
        ]
    },
    {
        "filename": "23_高性能本地缓存设计.md",
        "title": "高性能本地缓存设计",
        "intro": "本地缓存的核心是：**高并发读（无锁化）+ 淘汰策略（LRU/LFU）+ 容量控制 + 失效管理**。Caffeine 是目前 Java 本地缓存的最佳选择，了解其原理有助于面试和实际调优。",
        "sections": [
            ("架构设计", """
```
┌─────────────────────────────────────────────┐
│              本地缓存设计                   │
│                              │
│  读路径（无锁化，极高并发）                │
│  get(key) → 近似 LRU/LFU 判断           │
│           → 返回 value（如果存在）         │
│                              │
│  写路径（异步更新，不阻塞读）              │
│  put(key, value) → 写入 Buffer          │
│                  → 后台线程批量更新        │
│                              │
│  淘汰路径                                 │
│  put 时检测容量 → 触发淘汰算法           │
│  → 淘汰最少使用的条目                    │
└─────────────────────────────────────────────┘
```
"""),
            ("场景 A：手写简化版 LRU 缓存", """
### 面试高频：LinkedHashMap 实现 LRU
```java
public class LruCache<K, V> {
    private final int maxSize;
    private final LinkedHashMap<K, V> map;
    
    public LruCache(int maxSize) {
        this.maxSize = maxSize;
        this.map = new LinkedHashMap<K, V>(16, 0.75f, true) {
            @Override
            protected boolean removeEldestEntry(Map.Entry<K, V> eldest) {
                return size() > maxSize;  // 超过容量，删除最老条目
            }
        };
    }
    
    public V get(K key) {
        return map.get(key);  // accessOrder=true，get 会移动节点到队尾
    }
    
    public void put(K key, V value) {
        map.put(key, value);
    }
}
```
**问题**：`get()` 有 `synchronized` 吗？没有 → 线程不安全。并发场景需要用 `ConcurrentHashMap` + 自己维护 LRU 顺序（复杂）。
"""),
            ("场景 B：Caffeine 深度解析（生产推荐）", """
### 为什么 Caffeine 比 Guava Cache 快？
```
Guava Cache：
  - 用 synchronized 锁住整个 segment（分段锁）
  - 淘汰算法：真 LRU（维护一个队列，开销大）

Caffeine：
  - 用 ConcurrentHashMap（JDK 8+，锁分段更细）
  - 淘汰算法：W-TinyLFU（近似 LFU + 近期访问补偿）
    - 命中率比 LRU 高 10%~50%
    - O(1) 时间复杂度
```
### 使用
```java
// 1. 基础用法
Cache<String, User> cache = Caffeine.newBuilder()
    .maximumSize(10_000)                  // 最大条目数
    .expireAfterWrite(5, TimeUnit.MINUTES) // 写入后 5 分钟过期
    .expireAfterAccess(2, TimeUnit.MINUTES) // 访问后 2 分钟过期
    .refreshAfterWrite(1, TimeUnit.MINUTES)  // 写入后 1 分钟自动刷新
    .recordStats()                          // 开启统计（命中率等）
    .build(key -> loadFromDb(key));         // 加载函数（CacheLoader）

// 2. 手动缓存（更适合包装已有查询）
Cache<String, User> cache = Caffeine.newBuilder()
    .maximumSize(1_000)
    .build();  // 不传 CacheLoader

User user = cache.get("user:1001", k -> loadFromDb(k));
// get 时如果缓存没有，自动调用 loadFromDb

// 3. 统计
CacheStats stats = cache.stats();
log.info("命中率: {}", stats.hitRate());  // 关键指标
```
"""),
            ("场景 C：缓存穿透/击穿/雪崩防护", """
### 三大问题
| 问题 | 原因 | 解决方案 |
|------|------|---------|
| 穿透 | 查询不存在的 key | 布隆过滤器 / 缓存空值（TTL 短）|
| 击穿 | 热点 key 过期，大量请求打到 DB | 互斥锁 / 逻辑过期 |
| 雪崩 | 大量 key 同时过期 | 随机 TTL / 多级缓存 |

### 代码：互斥锁防击穿
```java
public class CacheWithLock<K, V> {
    private final Cache<K, V> cache = Caffeine.newBuilder()
        .maximumSize(10_000).build();
    private final Map<K, ReentrantLock> locks = new ConcurrentHashMap<>();
    
    public V get(K key, Function<K, V> loader) {
        V value = cache.getIfPresent(key);
        if (value != null) return value;
        
        // 缓存未命中 → 加锁加载（防止多个线程同时加载同一个 key）
        ReentrantLock lock = locks.computeIfAbsent(key, k -> new ReentrantLock());
        lock.lock();
        try {
            // 双重检查（可能其他线程已经加载了）
            value = cache.getIfPresent(key);
            if (value != null) return value;
            
            value = loader.apply(key);
            cache.put(key, value);
            return value;
        } finally {
            lock.unlock();
            locks.remove(key);  // 清理锁（防止内存泄漏）
        }
    }
}
```
**Caffeine 内置方案**：`expireAfterWrite` + `refreshAfterWrite` 组合，refresh 是后台异步刷新，不会阻塞读线程。
"""),
        ]
    },
]

# 先写 Java核心 的 4 篇
for topic in topics:
    filepath = os.path.join(base_dir, topic["filename"])
    
    with open(filepath, 'w', encoding='utf-8') as f:
        f.write(f"# {topic['title']}\n\n")
        f.write(f"> {topic['intro']}\n\n---\n\n")
        
        for section_title, content in topic["sections"]:
            f.write(f"## {section_title}\n\n")
            f.write(content.strip() + "\n\n---\n\n")
        
        f.write("## 排查 Checklist\n\n```\n")
        f.write("□ （待补充）\n")
        f.write("```\n\n---\n\n## 涉及知识点\n\n| 概念 | 所属域 | 关键点 |\n")
        f.write("|------|--------|--------|\n| （待补充）| （待补充）| （待补充）|\n\n---\n\n")
        f.write("## 我的实战笔记\n\n-（待补充，项目中的真实经历）\n")
    
    print(f"✅ 已生成: {topic['filename']}")

print("\nJava核心 4 篇完成！")
