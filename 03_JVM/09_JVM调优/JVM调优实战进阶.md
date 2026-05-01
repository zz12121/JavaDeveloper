# JVM 调优实战进阶

## 这个问题为什么存在？

> 基础篇讲了「参数怎么配」，这篇讲的是「出了问题怎么排查」。

会配置 JVM 参数只是及格线。生产环境的真实挑战是：

```bash
# 凌晨3点，告警群响了
[OOM] java.lang.OutOfMemoryError: Java heap space
[GC] Full GC 频繁，应用响应时间从 50ms 涨到 5s
[CPU] JVM 进程 CPU 100%，但请求量没变
[DEADLOCK] 检测到死锁，线程全部阻塞
```

**痛点**：
1. **线上不能随便重启**——一个 Full GC 可能就是 SLA 事故
2. **工具不熟**——知道有 jmap、jstack，但关键时刻想不起来怎么用
3. **排查没思路**——拿到 dump 文件一脸懵，不知道从哪看起
4. **经验难复用**——上次解决了，下次换了场景又不会了

**核心问题**：掌握一套**可复用的排查方法论** + **趁手的工具链**，遇到问题能快速定位根因。

---

## 一、排查工具链

### 1.1 JDK 自带工具速查

| 工具 | 用途 | 常用命令 |
|------|------|----------|
| **jps** | 查看Java进程 | `jps -lvm` |
| **jstat** | GC/类加载统计 | `jstat -gcutil <pid> 1000` |
| **jmap** | 堆转储/对象统计 | `jmap -histo <pid>` |
| **jstack** | 线程转储/死锁检测 | `jstack -l <pid>` |
| **jcmd** | 多功能（推荐替代上面三个） | `jcmd <pid> VM.flags` |
| **jinfo** | 查看运行时参数 | `jinfo -flags <pid>` |

**为什么优先用 jcmd？**

```
jcmd 是 JDK 7+ 推荐的统一工具入口，可以替代 jmap/jstack/jstat：
  jcmd <pid> GC.heap_dump      → 等价于 jmap -dump
  jcmd <pid> Thread.print       → 等价于 jstack
  jcmd <pid> GC.class_histogram → 等价于 jmap -histo
  jcmd <pid> GC.run             → 手动触发GC
  jcmd <pid> VM.flags           → 查看所有JVM参数
  jcmd <pid> VM.system_properties → 查看系统属性
  jcmd <pid> VM.command_line    → 查看启动命令行
```

> 生产环境推荐优先用 `jcmd`，一个命令搞定所有诊断。

### 1.2 Arthas——线上诊断神器

**安装**（无需重启应用）：
```bash
# 方式1：直接下载运行（推荐，一行命令搞定）
curl -O https://arthas.aliyun.com/arthas-boot.jar
java -jar arthas-boot.jar

# 方式2：as.sh 脚本（更方便）
curl -L https://arthas.aliyun.com/install.sh | sh
as.sh        # 自动检测Java进程，选择要诊断的
```

**核心命令实战**：

```bash
# ===== 1. dashboard —— 全局概况（第一反应先看这个）=====
dashboard
# 显示：线程数、内存使用、GC统计、运行环境
# 类似「驾驶仪表盘」，一眼看出当前JVM健康状况

# ===== 2. thread —— 线程分析 =====
thread                    # 所有线程状态概览
thread -n 5               # CPU占用最高的5个线程（排查CPU 100%）
thread -b                 # 检测死锁（找出阻塞链）
thread -i 5000            # 每隔5秒采样一次（看趋势）
thread <thread-id>        # 查看指定线程的堆栈

# 实战场景：CPU 100% 排查
# 步骤1：thread -n 5，找到CPU最高的线程
# 步骤2：记下线程 nid（16进制）
# 步骤3：thread <nid>，查看堆栈
# 步骤4：定位到死循环/频繁GC/锁竞争

# ===== 3. jad —— 反编译（看线上跑的实际代码）=====
jad com.example.service.OrderService
jad com.example.service.OrderService --source-only   # 只看源码

# 实战场景：怀疑某个方法有问题，但不确定线上跑的是哪个版本
# jad 直接反编译出字节码对应的Java代码，不用翻发布记录

# ===== 4. trace —— 方法调用链耗时 =====
trace com.example.service.OrderService createOrder
trace com.example.service.OrderService createOrder '#cost > 100'  # 只看耗时>100ms的

# 实战场景：接口响应慢，trace 逐层看哪一步耗时最多
# 输出示例：
# +---[100ms] OrderService.createOrder()
#     +---[80ms]  InventoryService.deductStock()    ← 瓶颈在这里！
#     +---[15ms]  PaymentService.createPayment()
#     +---[5ms]   OrderMapper.insert()

# ===== 5. watch —— 方法入参/返回值/异常观测 =====
watch com.example.service.OrderService createOrder '{params, returnObj, throwExp}' -x 2
# '{params}'      → 入参
# '{returnObj}'   → 返回值
# '{throwExp}'    → 异常信息
# '-x 2'          → 展开深度（对象属性层级）
# '-b'            → 观察方法调用前（入参阶段）
# '-e'            → 观察方法异常时
# '-s'            → 观察方法返回后
# '-f'            → 观察前后都记录（before + after）
# '#cost > 500'   → 只看耗时>500ms的调用

# 实战场景：某个接口偶尔返回空值，watch 加 '#cost>0' 过滤条件
# 每次调用都打印入参和返回值，快速复现问题

# ===== 6. stack —— 查看方法被谁调用 =====
stack com.example.service.OrderService createOrder
# 实战场景：想知道 createOrder 被哪些入口触发
# 输出完整的调用栈，包括 Controller → Service → Mapper 链路

# ===== 7. monitor —— 方法调用统计 =====
monitor -c 10 com.example.service.OrderService createOrder
# 每10秒统计一次：调用次数、成功次数、失败次数、平均RT、最大RT
# 实战场景：压测期间监控方法QPS和RT

# ===== 8. sc/sm —— 查看已加载的类和方法 =====
sc -d com.example.service.OrderService    # 查看类信息（来源jar、类加载器）
sm com.example.service.OrderService *     # 查看类下所有方法

# 实战场景：线上出了ClassCastException，确认加载的是哪个jar里的类
```

### 1.3 工具选择决策

```
┌──────────────────────────────────────────────────────────────┐
│                    线上排查工具选择                          │
│                                                              │
│  CPU 100%？                                                   │
│    → Arthas: thread -n 5 → 定位热点线程 → jad 反编译         │
│                                                              │
│  接口响应慢？                                                 │
│    → Arthas: trace → 找到耗时最多的方法                       │
│                                                              │
│  内存泄漏/OOM？                                               │
│    → jcmd/jmap 导出堆转储 → MAT 分析                         │
│                                                              │
│  GC 频繁/停顿长？                                            │
│    → jstat 监控 GC 趋势 → GC 日志分析（GCEasy/GCViewer）     │
│                                                              │
│  死锁？                                                      │
│    → Arthas: thread -b / jstack -l                           │
│                                                              │
│  方法调用异常？                                               │
│    → Arthas: watch '{params, throwExp}' -e                   │
│                                                              │
│  不确定类是哪个jar加载的？                                    │
│    → Arthas: sc -d                                          │
│                                                              │
│  需要 JVM 参数和系统配置？                                    │
│    → jcmd <pid> VM.flags / VM.system_properties               │
└──────────────────────────────────────────────────────────────┘
```

---

## 二、OOM 排查实战

### 2.1 四种 OOM 类型及特征

| OOM 类型 | 报错信息 | 常见原因 | 排查方向 |
|---------|----------|----------|---------|
| **Java heap space** | `OutOfMemoryError: Java heap space` | 堆内存不足、内存泄漏 | 分析堆转储，找大对象 |
| **Metaspace** | `OutOfMemoryError: Metaspace` | 动态类加载过多（CGLIB、Groovy） | 加大 MaxMetaspaceSize、检查代码生成 |
| **Direct buffer memory** | `OutOfMemoryError: Direct buffer memory` | NIO 的 ByteBuffer.allocateDirect() | 检查 Netty/NIO 使用、加大 MaxDirectMemorySize |
| **unable to create new native thread** | `OutOfMemoryError: unable to create new native thread` | 线程数超系统限制 | 检查线程池配置、降低 Xss |

### 2.2 OOM 自动转储（预防措施）

```bash
# 方式1：JVM 参数自动触发（推荐，不依赖人工）
-XX:+HeapDumpOnOutOfMemoryError                    # OOM 时自动 dump
-XX:HeapDumpPath=/var/log/app/dumps/heap.hprof     # dump 文件路径
-XX:OnOutOfMemoryError="kill -9 %p"                # OOM 后执行脚本（可选）

# 方式2：手动触发（在问题发生时趁热打铁）
jcmd <pid> GC.heap_dump filename=/tmp/heap.hprof
# 或
jmap -dump:format=b,file=/tmp/heap.hprof <pid>
```

**注意事项**：
- dump 文件大小 ≈ 堆大小（8GB 堆 ≈ 8GB dump），确保磁盘空间充足
- `jmap -dump` 会触发 Full GC 并 STW（Stop-The-World），**高并发时段慎用**
- 生产环境用 `HeapDumpOnOutOfMemoryError` 自动触发最可靠

### 2.3 实战案例1：堆内存溢出（Java heap space）

**现象**：
```
2026-01-15 14:23:01 [ERROR] c.a.s.OrderService - create order failed
java.lang.OutOfMemoryError: Java heap space
    at java.util.Arrays.copyOf(Arrays.java:3210)
    at java.lang.AbstractStringBuilder.toString(AbstractStringBuilder.java:656)
    ...
```

**排查步骤**：

```
步骤1：拿到 heap.hprof（自动或手动）
         │
步骤2：用 MAT 打开
         │
步骤3：看 Leak Suspects Report（MAT 自动生成的泄漏嫌疑报告）
         │
步骤4：点击 Dominator Tree（支配树）
         │   → 按对象 Retained Size 排序
         │   → Retained Size = 释放该对象后能回收的内存
         │   → Shallow Size = 对象自身大小
         │
步骤5：找到占用最大的对象
         │   比如：ConcurrentHashMap$Node 2.3GB
         │         → 点进去看 key/value 是什么
         │         → key = "user:12345:order_list"
         │         → value = ArrayList(150000)
         │
步骤6：找到引用链（Right-click → Path To GC Roots → exclude weak/soft）
         │   GC Root: static field OrderService.orderCache
         │   → OrderService.orderCache
         │     → HashMap
         │       → Entry["user:12345:order_list"]
         │         → ArrayList (2.3GB，没有清除过期数据)
         │
步骤7：定位到代码
         │   OrderService.orderCache 是一个 static HashMap
         │   只 put 不 remove，数据一直堆积
         │
步骤8：修复 → 改用 Caffeine/Guava Cache，设置 maxSize + expireAfterWrite
```

**MAT 核心功能速查**：

```
┌─────────────────────────────────────────────────────────────┐
│                  MAT 核心功能                               │
│                                                             │
│  1. Leak Suspects（泄漏嫌疑报告）                           │
│     → 自动分析最可能的泄漏点，附带占用百分比                 │
│     → 入门首选！打开 dump 先看这个                         │
│                                                             │
│  2. Dominator Tree（支配树）                                │
│     → 按Retained Size排序，找出「占内存最多」的对象         │
│     → Retained Size > Shallow Size → 说明它引用了其他对象   │
│                                                             │
│  3. Histogram（直方图）                                    │
│     → 按类名统计对象数量和大小                              │
│     → 快速看出哪种对象异常多                                │
│     → 比如：String 对象 500万个，ArrayList 30万个           │
│                                                             │
│  4. OQL（对象查询语言）                                    │
│     → 类似 SQL，可以精确查询堆中的对象                      │
│     → SELECT * FROM java.lang.String WHERE toString() LIKE '%order%' │
│                                                             │
│  5. GC Roots 引用链                                       │
│     → Path To GC Roots → exclude weak/soft references      │
│     → 找到「谁持有这个对象的引用导致无法回收」               │
│                                                             │
│  6. Top Consumers（顶级消费者）                             │
│     → 按包/类/对象分组统计内存占用                          │
│     → 快速定位是哪个模块占用内存最多                        │
└─────────────────────────────────────────────────────────────┘
```

### 2.4 实战案例2：元空间溢出（Metaspace）

**现象**：
```
java.lang.OutOfMemoryError: Metaspace
    at java.lang.ClassLoader.defineClass1(Native Method)
    at java.lang.ClassLoader.defineClass(ClassLoader.java:760)
```

**常见原因**：

```java
// 原因1：CGLIB 动态代理生成大量类
// Spring AOP、MyBatis Mapper 代理、Hibernate 延迟加载 都用 CGLIB
// 每个代理都生成一个新的 Class 对象，存在 Metaspace

// 原因2：Groovy/Aviator 表达式引擎
// 每次编译表达式都生成新的 Class
Expression exp = AviatorEvaluator.compile(expression); // 每次都新类！

// 原因3：JSP 频繁热部署
// 每次热部署，旧的 Class 没卸载干净，新 Class 又加载进来
```

**排查与解决**：
```bash
# 1. 查看元空间使用情况
jcmd <pid> GC.metaspace
# 输出：
# Metaspace       used  120M, capacity 130M, committed 135M, reserved 1114112K

# 2. 加大元空间（治标）
-XX:MaxMetaspaceSize=512m

# 3. 根治：减少动态类的生成
#    - Aviator：用 compile 缓存，避免重复编译
#    - Groovy：设置 GroovyClassloader 的类缓存
#    - CGLIB：检查是否在不必要的地方使用了动态代理

# 4. 如果是热部署导致，重启前先 undeploy 旧应用
```

### 2.5 实战案例3：直接内存溢出（Direct buffer memory）

**现象**：
```
java.lang.OutOfMemoryError: Direct buffer memory
    at java.nio.Bits.reserveMemory(Bits.java:694)
```

**常见场景**：
```java
// Netty 使用了大量的 DirectByteBuffer（堆外内存）
// 默认大小 = Runtime.getRuntime().maxMemory()（和堆一样大）
// 如果没有限制，可能导致直接内存耗尽

// Kafka 客户端也使用堆外内存
// Elasticsearch 的 Lucene 也用堆外内存做文件缓存
```

**解决**：
```bash
# 显式限制直接内存大小
-XX:MaxDirectMemorySize=1g

# 如果是 Netty，可以调整 allocator
-Dio.netty.allocator.type=pooled       # 使用池化分配器
-Dio.netty.maxDirectMemory=1073741824  # 限制 Netty 的堆外内存
```

### 2.6 实战案例4：线程数超限

**现象**：
```
java.lang.OutOfMemoryError: unable to create new native thread
```

**排查**：
```bash
# 1. 查看线程数
jcmd <pid> Thread.print | grep -c "tid"

# 2. 查看系统线程限制
ulimit -u       # 用户最大进程数（Linux 默认 1024 或 4096）
cat /proc/sys/kernel/pid_max   # 系统最大PID数

# 3. 用 Arthas 看线程分布
thread          # 看线程状态统计
thread | grep RUNNABLE | wc -l   # 运行中的线程数
```

**常见原因与解决**：

```java
// 原因1：线程池没有上限
ExecutorService pool = Executors.newCachedThreadPool();
// CachedThreadPool 的最大线程数是 Integer.MAX_VALUE！
// 高并发时会疯狂创建线程，直到系统崩溃
// ✅ 改用固定大小线程池
ExecutorService pool = new ThreadPoolExecutor(
    10, 50, 60, TimeUnit.SECONDS,
    new LinkedBlockingQueue<>(1000),
    new ThreadFactoryBuilder().setNameFormat("order-pool-%d").build(),
    new ThreadPoolExecutor.CallerRunsPolicy()
);

// 原因2：Xss 设置过大
// 每个线程的栈大小默认 1MB
// 1000 个线程 = 1GB 栈内存
// 如果 Xss=2m，同样的线程数需要 2GB
-XX:ThreadStackSize=512k  # 减小栈大小（不能太小，否则StackOverflowError）
```

---

## 三、线上 GC 问题定位

### 3.1 Full GC 频繁排查

**现象**：应用响应时间波动大，监控显示每隔几分钟出现一次长时间停顿。

**排查流程**：

```
步骤1：确认是否真的是 Full GC
         │
         ▼
    jstat -gcutil <pid> 5000
    # 每5秒打印一次GC统计
    # 关注：O（Old区使用率）是否快满了再被清掉
    # 关注：FGC（Full GC 次数）是否持续增长
    # 关注：FGCT（Full GC 总时间）是否过大
         │
         ├── O 区反复涨到 90%+ 再回落 → 确认是 Full GC 导致
         │
         ▼
步骤2：分析 Full GC 的原因
         │
         ├── 原因A：对象晋升速度过快（Survivor 区太小，对象直接进老年代）
         │   → 现象：Minor GC 后 Old 区就涨了很多
         │   → 解决：加大新生代 -Xmn / 调小 SurvivorRatio
         │
         ├── 原因B：内存泄漏（老年代使用率只涨不降，最终触发 Full GC）
         │   → 现象：Full GC 后 Old 区使用率不降（或降得很少）
         │   → 解决：dump 堆转储，用 MAT 分析泄漏对象
         │
         ├── 原因C：大对象直接进入老年代
         │   → 现象：Young GC 频率正常，但大对象绕过 Eden 直接到 Old
         │   → 解决：-XX:PretenureSizeThreshold=1m（大于1m直接进老年代，减少复制开销）
         │           或者优化代码，避免创建大对象
         │
         ├── 原因D：显式调用 System.gc()
         │   → 现象：GC 日志中有 "System.gc()" 触发记录
         │   → 解决：-XX:+DisableExplicitGC 禁用（除非有堆外内存释放需求）
         │
         └── 原因E：Metaspace 不足触发 Full GC
             → 现象：Metaspace 使用率持续上涨
             → 解决：加大 -XX:MaxMetaspaceSize
         │
         ▼
步骤3：验证修复效果
    重新压测，对比 jstat 输出的 FGC/FGCT 指标
```

### 3.2 G1 GC 常见问题

**问题1：Mixed GC 停顿时间波动大**

```bash
# G1 的调优核心参数
-XX:MaxGCPauseMillis=200    # 目标停顿时间（默认200ms）
-XX:G1HeapRegionSize=8m     # Region 大小（1MB-32MB，必须是2的幂）
-XX:InitiatingHeapOccupancyPercent=45  # 触发并发标记的老年代使用率阈值

# 如果停顿时间波动大：
# 1. 降低 MaxGCPauseMillis → G1会更激进地回收（但可能更频繁）
# 2. 检查是否有大对象导致 Mixed GC 回收 Region 过多
# 3. 调大 G1HeapRegionSize，减少大对象横跨多个 Region 的情况
```

**问题2：G1 出现 Full GC（退化为 Serial Old）**

```
现象：GC 日志中出现 "Full GC (Allocation Failure)"
      停顿时间突然从几十毫秒变成几秒

原因：G1 的并发标记没来得及完成，老年代就满了
      → 被迫退化到 Serial Old（单线程 Full GC）

解决：
1. 降低 IHOP（InitiatingHeapOccupancyPercent）
   → 更早触发并发标记，留更多时间回收
   -XX:InitiatingHeapOccupancyPercent=35  # 默认45，降到35

2. 增加并发标记线程
   -XX:ConcGCThreads=4  # 默认 = ParallelGCThreads / 4

3. 检查是否有内存泄漏
   → 如果 Mixed GC 后 Old 区使用率还是很高，可能是泄漏
```

**问题3：G1 的 Humongous 对象问题**

```java
// 大于 Region 大小一半的对象叫 Humongous Object
// 默认 Region 8MB，超过 4MB 的对象就是 Humongous

// 问题：Humongous 对象直接分配在老年代，不经过 Young GC
// 如果频繁创建大对象，老年代很快满 → 触发 Full GC

// 解决方案1：调大 Region
-XX:G1HeapRegionSize=16m  // 大对象阈值变为 8MB

// 解决方案2：避免大对象
// 不要一次性查询 10 万条数据到内存
// 分页查询，流式处理
```

### 3.3 JDK 8 的 CMS 调优（遗留系统）

> 虽然 CMS 在 JDK 14 被移除，但大量遗留系统仍在使用。

```bash
# CMS 推荐配置
java -Xms8g -Xmx8g \
     -XX:+UseConcMarkSweepGC \
     -XX:+UseParNewGC \
     -XX:CMSInitiatingOccupancyFraction=70 \      # Old 区 70% 触发 CMS
     -XX:+UseCMSInitiatingOccupancyOnly \          # 只用上面的百分比触发
     -XX:+CMSParallelRemarkEnabled \                # 并行重新标记（降低 remark 停顿）
     -XX:+CMSParallelSurvivorRemarkEnabled \        # 并行 Survivor 区重新标记
     -XX:+CMSScavengeBeforeRemark \                 # remark 前先做一次 Minor GC（减少 remark 扫描量）
     -XX:+ExplicitGCInvokesConcurrent \             # System.gc() 触发并发 GC（而非 Full GC）
     -XX:+HeapDumpOnOutOfMemoryError \
     MyApp
```

**CMS 核心问题——碎片化**：
```
CMS 使用标记-清除算法，不整理内存
→ 长时间运行后产生大量碎片
→ 大对象找不到连续空间 → Concurrent Mode Failure
→ 退化到 Serial Old（单线程 Full GC），停顿时间可能几十秒！

应对：
1. 开启 CMSCompactAtFullCollection（Full GC 时整理碎片，但 Full GC 本身停顿长）
2. 设置 CMSFullGCsBeforeCompaction=5（每5次 Full GC 整理一次）
3. 根本方案：升级到 G1
```

### 3.4 ZGC（JDK 11+，超低延迟场景）

```bash
# ZGC 配置（极简）
java -Xms16g -Xmx16g \
     -XX:+UseZGC \
     -XX:ZCollectionInterval=0 \        # 不定时触发（只靠分配速率触发）
     -XX:+ZGenerational \               # JDK 21+ 分代 ZGC（推荐）
     MyApp

# ZGC 的特点：
# 1. 停顿时间 < 1ms（无论堆多大）
# 2. 支持 8TB 堆（JDK 16+）
# 3. 并发整理（不会像 CMS 一样碎片化）
# 4. JDK 21 引入分代 ZGC，大幅降低分配停顿
```

---

## 四、CPU 100% 排查实战

**现象**：JVM 进程 CPU 占用率持续 100%，但请求量没有增加。

**排查流程**：

```bash
# 步骤1：定位 CPU 高的线程
top -Hp <pid>
# 或用 Arthas（更方便）：
# arthas-boot.jar → 选择进程 → thread -n 5
# 输出示例：
# ID   NAME                STATE     CPU%  DELTA  TIME
# 23   sched-pool-1        RUNNABLE  89.2  89.1   300s  ← 这个线程CPU异常高
# 45   http-nio-8080-exec  WAITING   0.1   0.0    10s

# 步骤2：将线程 ID 转为 16 进制
printf '%x\n' 23
# 输出：17

# 步骤3：查看线程堆栈
jstack <pid> | grep -A 30 "0x17"
# 或用 Arthas：
# thread 23

# 步骤4：分析堆栈，常见原因：

# 原因1：死循环
# "at com.example.service.DataProcessor.process(DataProcessor.java:156)"
# "at com.example.service.DataProcessor.process(DataProcessor.java:145)"  ← 递归调用自己
# 解决：检查循环/递归的退出条件

# 原因2：频繁 Full GC
# "at java.lang.ref.Reference.processPendingReferences(Reference.java:241)"
# CPU 高但堆栈在 GC 相关方法 → GC 线程占满 CPU
# 解决：排查内存泄漏/调大堆

# 原因3：锁竞争（CAS 自旋）
# "at java.util.concurrent.ConcurrentHashMap.putVal(ConcurrentHashMap.java:1019)"
# "at jdk.internal.misc.Unsafe.compareAndSwapInt(Native Method)"  ← CAS 自旋
# 高并发下 ConcurrentHashMap 扩容时可能触发大量 CAS 自旋
# 解决：调大初始容量、避免反复扩容

# 原因4：正则匹配回溯
# "at java.util.regex.Pattern$GroupHead.match(Pattern.java:4668)"
# 恶意正则导致灾难性回溯（ReDoS）
# 解决：避免贪婪匹配、使用预编译正则、设置超时
```

---

## 五、死锁排查实战

### 5.1 快速检测

```bash
# 方式1：jstack 自带死锁检测
jstack -l <pid> | grep -A 20 "Found one Java-level deadlock"

# 方式2：Arthas
thread -b
# 输出示例：
# "http-nio-8080-exec-3" 等待锁 "0x000000076b4b8c50" 持有者 "http-nio-8080-exec-5"
# "http-nio-8080-exec-5" 等待锁 "0x000000076b4b8c78" 持有者 "http-nio-8080-exec-3"
# → 典型的循环等待！
```

### 5.2 常见死锁模式与解决

```java
// 模式1：嵌套锁（最常见）
// 线程A：先锁 accountA，再锁 accountB
// 线程B：先锁 accountB，再锁 accountA
// → 循环等待 → 死锁！

// 解决：统一加锁顺序
synchronized(accountA) {         // 统一先锁 id 小的账户
    synchronized(accountB) {
        transfer();
    }
}

// 模式2：锁未释放
public void process() {
    synchronized(lock) {
        if (error) {
            return;  // ❌ 提前返回，锁没释放！
        }
    }
}
// 解决：try-finally
public void process() {
    synchronized(lock) {
        try {
            if (error) return;
        } finally {
            // 不需要手动释放，synchronized 会自动释放
            // 但如果用 Lock 接口，必须在 finally 中 unlock()
        }
    }
}

// 模式3：数据库事务 + Java 锁的混合死锁
// 线程A：先锁 Java 对象 → 再获取数据库锁
// 线程B：先获取数据库锁 → 再锁 Java 对象
// 解决：统一顺序，或缩短锁的持有时间
```

### 5.3 预防死锁的编码规范

```
1. 减小锁粒度 → 能不加锁就不加，能用局部变量就不用共享变量
2. 统一加锁顺序 → 多把锁时，约定统一的获取顺序（如按ID排序）
3. 使用超时锁 → lock.tryLock(5, TimeUnit.SECONDS)，获取失败则回退
4. 使用并发工具类 → ConcurrentHashMap、AtomicInteger 替代 synchronized
5. 避免嵌套锁 → 如果必须嵌套，确保顺序一致
6. Code Review 死锁 → 并发代码必须经过 Code Review
```

---

## 六、内存泄漏典型案例

### 6.1 ThreadLocal 泄漏（最经典）

```java
// 问题代码
public class UserContext {
    private static final ThreadLocal<User> CURRENT_USER = new ThreadLocal<>();

    // 在线程池中使用：线程被复用，但 ThreadLocal 的值没清除
    // → 对象一直被 ThreadLocalMap 引用 → 内存泄漏
}

// 正确写法：使用完后必须 remove
try {
    UserContext.CURRENT_USER.set(user);
    // 业务逻辑...
} finally {
    UserContext.CURRENT_USER.remove();  // ✅ 必须在 finally 中清除
}
```

**为什么 ThreadLocal 会泄漏？**

```
Thread → ThreadLocalMap → Entry(ThreadLocal, value)
                                       ↑
                               Entry 的 key 是 WeakReference（会被GC回收）
                               但 value 是强引用（不会被GC回收）

如果 ThreadLocal 对象被回收（key = null），但 value 还在
→ 这个 value 永远无法被访问到（key 已经是 null 了）
→ 但又无法被 GC（被 Entry 的强引用持有）
→ 内存泄漏！

线程池环境下更严重：线程不销毁，ThreadLocalMap 一直存在
→ 大量 value 堆积 → OOM
```

### 6.2 静态集合泄漏

```java
// 问题代码：用 static Map 做缓存，永远不清理
public class CacheManager {
    private static final Map<String, Object> CACHE = new HashMap<>();

    public static void put(String key, Object value) {
        CACHE.put(key, value);  // ❌ 只放不删
    }
}

// 解决：使用带过期策略的缓存
// 方案1：Guava Cache
Cache<String, Object> cache = CacheBuilder.newBuilder()
    .maximumSize(10000)
    .expireAfterWrite(30, TimeUnit.MINUTES)
    .build();

// 方案2：Caffeine（推荐，性能更好）
Cache<String, Object> cache = Caffeine.newBuilder()
    .maximumSize(10000)
    .expireAfterWrite(30, TimeUnit.MINUTES)
    .recordStats()    // 开启统计（命中率、加载时间等）
    .build();
```

### 6.3 资源未关闭泄漏

```java
// 问题代码：连接/流/Statement 没关闭
public List<User> queryUsers() {
    Connection conn = dataSource.getConnection();
    Statement stmt = conn.createStatement();   // ❌ 没有 try-with-resources
    ResultSet rs = stmt.executeQuery("SELECT * FROM users");
    // 如果这里抛异常，conn/stmt/rs 全部泄漏
}

// 正确写法
public List<User> queryUsers() {
    try (Connection conn = dataSource.getConnection();
         Statement stmt = conn.createStatement();
         ResultSet rs = stmt.executeQuery("SELECT * FROM users")) {
        // 自动关闭，即使抛异常
        // 返回结果前先从 ResultSet 中提取数据（因为 rs 关闭后就无效了）
    }
}
```

### 6.4 内部类持有外部类引用

```java
// 问题代码：匿名内部类隐式持有外部类引用
public class BigObject {
    private byte[] data = new byte[100 * 1024 * 1024]; // 100MB

    public void submitTask() {
        executor.submit(new Runnable() {
            @Override
            public void run() {
                // ❌ 这个匿名内部类持有 BigObject 的引用
                // BigObject 无法被 GC（即使主线程不用了）
                System.out.println(data.length);
            }
        });
    }
}

// 解决：使用静态内部类或 Lambda
public void submitTask() {
    byte[] localData = this.data;  // 只提取需要的字段
    executor.submit(() -> System.out.println(localData.length));  // ✅ Lambda 不持有外部类引用
}
```

---

## 七、线上调优实战案例

### 7.1 案例：电商秒杀系统 GC 调优

**背景**：
- Spring Boot 应用，JDK 17，G1 GC
- 秒杀期间 QPS 从 500 暴涨到 50000
- 响应时间从 50ms 涨到 3s

**排查过程**：

```bash
# 1. 看整体指标
jstat -gcutil <pid> 1000
# E（Eden）每次 GC 前 99% → 对象创建极快
# O（Old）从 20% 缓慢涨到 80% → 有对象晋升到老年代
# FGC（Full GC）从 0 变成 5 次/分钟 → 严重！

# 2. 用 Arthas trace 找慢接口
trace com.example.controller.SeckillController seckill '#cost > 100'
# 发现：InventoryService.deductStock() 平均 200ms
#       → 数据库连接池耗尽，大量线程等待

# 3. 分析原因
# - 秒杀请求创建大量临时对象（Order/Event/DTO）
# - Eden 区不够，对象来不及回收就晋升到老年代
# - 数据库连接池（默认 10）完全不够
```

**调优方案**：

```bash
# JVM 调优
java -Xms8g -Xmx8g \
     -XX:+UseG1GC \
     -XX:MaxGCPauseMillis=100 \          # 降低目标停顿时间
     -XX:G1HeapRegionSize=4m \           # Region 调小（秒杀对象小而多）
     -XX:InitiatingHeapOccupancyPercent=35 \  # 更早触发并发标记
     -XX:+AlwaysPreTouch \               # 启动时预分配内存（避免运行时页面分配开销）
     MyApp

# 业务调优（更关键）
# 1. 数据库连接池 10 → 100
spring.datasource.hikari.maximum-pool-size=100
# 2. 秒杀请求用 Redis 预扣库存（不直接打数据库）
# 3. 用消息队列异步处理订单创建
# 4. 限流（令牌桶/滑动窗口）
```

**调优效果**：

| 指标 | 调优前 | 调优后 |
|------|-------|-------|
| 平均响应时间 | 3000ms | 120ms |
| P99 响应时间 | 5000ms | 350ms |
| Full GC 频率 | 5次/分钟 | 0次 |
| GC 最大停顿 | 800ms | 45ms |
| 吞吐量 | 2000 TPS | 15000 TPS |

> **经验**：JVM 调优只是辅助手段，真正的瓶颈往往在业务层面（数据库/网络/架构设计）。先优化业务，再调 JVM。

### 7.2 案例：报表系统 OOM 排查

**背景**：
- 每日定时任务：查询 100 万条记录，生成 Excel 报表
- 运行一段时间后 OOM：Java heap space

**排查过程**：

```bash
# 1. 拿到 heap.hprof
# 2. MAT 打开 → Leak Suspects
#    Problem Suspect 1: 占用 85% 的堆
#    → ArrayList 有 150 万个元素，每个元素是一个 OrderDTO
#    → Retained Size: 3.2GB
# 3. GC Roots 引用链
#    → ReportGenerator.generateReport()
#      → List<OrderDTO> orders = orderMapper.selectAll()  ← 一次性查出100万条！
```

**修复**：
```java
// 问题代码：一次性加载全部数据到内存
List<OrderDTO> orders = orderMapper.selectAll();  // ❌ 100万条 × 3KB ≈ 3GB

// 修复方案1：分页查询 + 流式写入 Excel
int pageSize = 10000;
int pageNum = 0;
while (true) {
    List<OrderDTO> page = orderMapper.selectPage(pageNum++, pageSize);
    if (page.isEmpty()) break;
    excelWriter.write(page);  // 写完释放
}

// 修复方案2：MyBatis 游标查询（流式读取）
try (Cursor<OrderDTO> cursor = orderMapper.selectByCursor()) {
    for (OrderDTO order : cursor) {
        excelWriter.write(order);  // 逐条处理，内存占用极低
    }
}

// 修复方案3：使用 EasyExcel（流式写入，不将全部数据加载到内存）
EasyExcel.write(outputStream, OrderDTO.class)
    .sheet("订单报表")
    .doWrite(() -> orderMapper.selectByCursor());  // 分批查询写入
```

---

## 八、线上排查 Checklist

```
┌─────────────────────────────────────────────────────────────┐
│                  线上问题排查 Checklist                      │
│                                                             │
│  === 发生 OOM ===                                           │
│  □ 确认 OOM 类型（heap / metaspace / direct / thread）     │
│  □ 检查 HeapDumpOnOutOfMemoryError 是否开启                 │
│  □ 用 MAT 分析 heap dump（Leak Suspects → Dominator Tree）  │
│  □ 查看 GC Roots 引用链                                     │
│  □ 检查是否有内存泄漏（对比多次 dump 的老年代使用率）        │
│                                                             │
│  === GC 频繁 / 停顿长 ===                                   │
│  □ jstat -gcutil 确认 GC 频率和类型                         │
│  □ 下载 GC 日志，用 GCEasy 分析                             │
│  □ 确认是 Minor GC 还是 Full GC 频繁                        │
│  □ 检查 JVM 参数是否合理（Xms/Xmx/新生代大小/GC选择器）     │
│  □ 检查是否有内存泄漏导致 Full GC                           │
│                                                             │
│  === CPU 100% ===                                           │
│  □ top -Hp <pid> 找到 CPU 最高的线程                        │
│  □ jstack/Arthas thread 查看线程堆栈                        │
│  □ 区分：业务死循环 / GC 线程 / CAS 自旋 / 正则回溯         │
│                                                             │
│  === 接口响应慢 ===                                         │
│  □ Arthas trace 方法调用链耗时                              │
│  □ 检查数据库慢查询                                         │
│  □ 检查线程池是否耗尽                                       │
│  □ 检查 GC 停顿是否影响响应时间                             │
│                                                             │
│  === 死锁 ===                                               │
│  □ jstack -l / Arthas thread -b                            │
│  □ 定位循环等待的两把锁和两个线程                           │
│  □ 修复：统一加锁顺序 / 使用超时锁 / 缩小锁范围             │
│                                                             │
│  === 日常监控（预防） ===                                    │
│  □ GC 日志是否开启                                          │
│  □ HeapDumpOnOutOfMemoryError 是否开启                      │
│  □ Xms = Xmx 是否设置相同                                   │
│  □ MetaspaceSize 是否设置                                   │
│  □ 是否配置了 JVM 监控告警（Prometheus + Grafana）          │
└─────────────────────────────────────────────────────────────┘
```

---

## 九、JVM 参数速查表

### 9.1 生产环境推荐模板

```bash
# ===== 通用 Spring Boot 应用（4C8G 服务器）=====
java \
  -Xms4g -Xmx4g \
  -XX:+UseG1GC \
  -XX:MaxGCPauseMillis=200 \
  -XX:G1HeapRegionSize=4m \
  -XX:InitiatingHeapOccupancyPercent=45 \
  -XX:+HeapDumpOnOutOfMemoryError \
  -XX:HeapDumpPath=/var/log/app/dumps/ \
  -XX:+AlwaysPreTouch \
  -XX:MetaspaceSize=256m \
  -XX:MaxMetaspaceSize=512m \
  -Xlog:gc*:file=/var/log/app/gc.log:time,uptime,level,tags:filecount=5,filesize=50m \
  -Djava.awt.headless=true \
  -jar app.jar

# ===== 大堆应用（8C16G 服务器，堆 8GB+）=====
java \
  -Xms8g -Xmx8g \
  -XX:+UseG1GC \
  -XX:MaxGCPauseMillis=200 \
  -XX:G1HeapRegionSize=8m \
  -XX:InitiatingHeapOccupancyPercent=40 \
  -XX:G1MixedGCCountTarget=4 \
  -XX:+HeapDumpOnOutOfMemoryError \
  -XX:+AlwaysPreTouch \
  -XX:MetaspaceSize=256m \
  -XX:MaxMetaspaceSize=512m \
  -XX:MaxDirectMemorySize=1g \
  -Xlog:gc*:file=/var/log/app/gc.log:time,uptime,level,tags:filecount=10,filesize=100m \
  -jar app.jar

# ===== 低延迟应用（JDK 21+，考虑 ZGC）=====
java \
  -Xms8g -Xmx8g \
  -XX:+UseZGC \
  -XX:+ZGenerational \
  -XX:+HeapDumpOnOutOfMemoryError \
  -XX:+AlwaysPreTouch \
  -Xlog:gc*:file=/var/log/app/gc.log:time,uptime,level,tags:filecount=5,filesize=50m \
  -jar app.jar

# ===== 容器化部署（Docker/K8s，务必注意内存限制）=====
# 不要硬编码 -Xms/-Xmx，让 JVM 感知容器限制
java \
  -XX:MaxRAMPercentage=75.0 \           # 使用容器内存的 75% 作为堆
  -XX:InitialRAMPercentage=75.0 \       # 初始和最大相同
  -XX:+UseG1GC \
  -XX:MaxGCPauseMillis=200 \
  -XX:+UseContainerSupport \             # JDK 8u191+ 开启容器感知
  -XX:+HeapDumpOnOutOfMemoryError \
  -Xlog:gc*:file=/var/log/app/gc.log:time,uptime,level,tags:filecount=5,filesize=20m \
  -jar app.jar
```

### 9.2 关键参数含义速查

| 参数 | 含义 | 推荐值 |
|------|------|--------|
| `-Xms` | 初始堆大小 | 与 Xmx 相同 |
| `-Xmx` | 最大堆大小 | 物理内存的 50%-75% |
| `-XX:MaxRAMPercentage` | 堆占物理内存百分比（容器推荐） | 75.0 |
| `-XX:+UseG1GC` | 使用 G1 收集器 | JDK 9+ 默认 |
| `-XX:MaxGCPauseMillis` | G1 目标停顿时间 | 100-200ms |
| `-XX:G1HeapRegionSize` | G1 Region 大小 | 堆<8G→4m，8-16G→8m，>16G→16m |
| `-XX:+AlwaysPreTouch` | 启动时预分配堆内存 | 生产推荐 |
| `-XX:MetaspaceSize` | 元空间初始大小 | 256m |
| `-XX:MaxMetaspaceSize` | 元空间最大大小 | 512m |
| `-XX:+HeapDumpOnOutOfMemoryError` | OOM 时自动 dump | 必须开启 |
| `-XX:MaxDirectMemorySize` | 直接内存最大值 | 视 NIO/Netty 使用量 |

---

## 面试话术总结

1. **线上 OOM 怎么排查？**
   "先看 OOM 类型（heap/metaspace/direct/thread），确认是否开启 HeapDumpOnOutOfMemoryError。拿到 heap dump 后用 MAT 分析，看 Leak Suspects 和 Dominator Tree，找到 Retained Size 最大的对象，追踪 GC Roots 引用链定位到具体代码。常见的有 ThreadLocal 未 remove、静态 Map 缓存没清理、资源未关闭。"

2. **线上 CPU 100% 怎么排查？**
   "先用 top -Hp 或 Arthas thread -n 5 找到 CPU 最高的线程，将线程 ID 转 16 进制，用 jstack 查看堆栈。常见原因：死循环、频繁 GC（GC 线程占满 CPU）、CAS 自旋（高并发 HashMap 扩容）、正则灾难性回溯。"

3. **线上 Full GC 频繁怎么定位？**
   "先用 jstat -gcutil 确认 Full GC 频率和 Old 区使用率趋势。如果 Old 区使用率只涨不降，基本是内存泄漏；如果 Minor GC 后 Old 区就涨很多，可能是 Survivor 太小导致对象提前晋升；如果 GC 日志有 System.gc()，加 DisableExplicitGC。根本解决：MAT 分析 dump 找泄漏对象。"

4. **G1 和 ZGC 怎么选？**
   "JDK 9-20 默认 G1，适合 4-32GB 堆，停顿可控制在 100-200ms。JDK 21+ 如果需要亚毫秒停顿，用分代 ZGC（+ZGenerational），可以支撑更大堆（TB 级）。对于大多数 Web 应用，G1 已经够用了，关键参数是 MaxGCPauseMillis 和 IHOP。"

5. **说一下你经历过的 JVM 调优案例。**
   "之前做过秒杀系统的调优：QPS 从 500 暴涨到 50000 时，响应时间从 50ms 涨到 3s。排查发现两个问题：一是 G1 的 Region 大小不合适导致 Mixed GC 停顿长，调小到 4MB；二是数据库连接池不够导致线程等待。JVM 层面调了 G1RegionSize 和 IHOP，但更关键的优化在业务层面——用 Redis 预扣库存、消息队列异步下单、连接池从 10 调到 100。最终 P99 从 5s 降到 350ms。"

---

*基础篇教你配参数，进阶篇教你排问题。真正的高手不只是调 JVM，而是先优化业务架构，JVM 调优只是最后一道防线。*
