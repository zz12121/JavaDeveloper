# JVM 调优实战进阶

> 会配参数只是及格线。这篇讲：出了问题怎么排查、怎么定位根因、怎么避免下次再犯。

---

## 这个问题为什么存在？

配好 JVM 参数不等于高枕无忧。生产环境的真实挑战是：

```
# 凌晨3点，告警群响了
[OOM] java.lang.OutOfMemoryError: Java heap space
[GC]   Full GC 频繁，应用响应时间从 50ms 涨到 5s
[CPU]  JVM 进程 CPU 100%，但请求量没变
[DEADLOCK] 检测到死锁，线程全部阻塞
```

**痛点**：
1. **线上不能随便重启**——一个 Full GC 可能就是 SLA 事故
2. **工具不熟**——知道有 jmap、jstack，但关键时刻想不起来怎么用
3. **排查没思路**——拿到 dump 文件一脸懵，不知道从哪看起
4. **经验难复用**——上次解决了，下次换了场景又不会了

**核心问题**：掌握一套**可复用的排查方法论** + **趁手的工具链**，遇到问题能快速定位根因。

没有这套能力时，只能靠重启解决问题，问题反复出现，最终变成"狼来了"的告警疲劳。

---

## 它是怎么解决问题的？

> 不讲"是什么"，讲清楚"排查问题的方法论是什么、为什么这套工具链能解决问题"。

### 核心机制：分层排查方法论

```
┌──────────────────────────────────────────────────────────────┐
│                  线上问题排查方法论                          │
│                                                              │
│  第1层：快速定位问题类型                                    │
│     OOM？GC频繁？CPU 100%？死锁？接口慢？                │
│       │                                                      │
│       ▼                                                      │
│  第2层：选对工具，拿到现场数据                              │
│     OOM → HeapDump / MAT                                   │
│     GC   → jstat / GC日志                                   │
│     CPU   → top -Hp / Arthas thread                         │
│     死锁  → jstack -l / Arthas thread -b                   │
│       │                                                      │
│       ▼                                                      │
│  第3层：分析数据，找到根因                                  │
│     MAT：Dominator Tree → 找最大对象 → GC Roots 引用链       │
│     jstat：Old 区趋势 → 判断泄漏还是晋升过快                │
│     stack：线程栈 → 定位死循环/CAS自旋/正则回溯             │
│       │                                                      │
│       ▼                                                      │
│  第4层：修复验证，沉淀经验                                  │
│     修复代码 → 压测验证 → 更新 Checklist → 预防同类问题   │
└──────────────────────────────────────────────────────────────┘
```

**为什么需要分层排查？**
- 跳过第1层直接上手工具，容易南辕北辙（比如用 jstack 排查 OOM）
- 第2层的关键是"拿到现场数据"——问题发生后第一反应是保留现场，不是重启
- 第3层需要经验：知道看哪个指标、怎么解读数据

---

### 工具链详解

#### 1. JDK 自带工具（基础必备）

| 工具 | 用途 | 常用命令 | 局限性 |
|------|------|----------|---------|
| **jps** | 查看Java进程 | `jps -lvm` | 只能看进程列表 |
| **jstat** | GC/类加载统计 | `jstat -gcutil <pid> 1000` | 只能看统计，看不到对象 |
| **jmap** | 堆转储/对象统计 | `jmap -histo <pid>` | 触发Full GC，STW |
| **jstack** | 线程转储/死锁检测 | `jstack -l <pid>` | 只能看某一时刻快照 |
| **jinfo** | 查看运行时参数 | `jinfo -flags <pid>` | — |

**为什么优先用 jcmd？**

`jcmd` 是 JDK 7+ 推荐的统一入口，一个命令搞定上面所有功能，且对线上更友好：

```bash
jcmd <pid> GC.heap_dump filename=heap.hprof   # 等价于 jmap -dump（但不会触发Full GC）
jcmd <pid> Thread.print                        # 等价于 jstack
jcmd <pid> GC.class_histogram              # 等价于 jmap -histo
jcmd <pid> GC.run                          # 手动触发GC（谨慎使用）
jcmd <pid> VM.flags                        # 查看所有JVM参数
jcmd <pid> VM.system_properties            # 查看系统属性
jcmd <pid> VM.command_line                 # 查看启动命令行
jcmd <pid> Compiler.codecache              # 查看CodeCache使用情况
```

> 生产环境推荐优先用 `jcmd`，对应用停顿影响更小。

#### 2. Arthas——线上诊断神器（无需重启）

**安装**：
```bash
# 方式1：直接下载运行（推荐）
curl -O https://arthas.aliyun.com/arthas-boot.jar
java -jar arthas-boot.jar

# 方式2：as.sh 脚本
curl -L https://arthas.aliyun.com/install.sh | sh
as.sh
```

**核心命令速查**：

```bash
# === dashboard —— 第一反应先看这个 ===
dashboard              # 全局概况：线程数、内存、GC、运行环境

# === thread —— 线程分析（CPU 100% 必用）===
thread                 # 所有线程状态概览
thread -n 5            # CPU占用最高的5个线程
thread -b              # 检测死锁（找出阻塞链）
thread <thread-id>     # 查看指定线程堆栈

# === jad —— 反编译（确认线上代码版本）===
jad com.example.Service              # 反编译整个类
jad com.example.Service methodName  # 反编译指定方法

# === trace —— 方法调用链耗时（接口慢必用）===
trace com.example.Service methodName
trace com.example.Service methodName '#cost > 100'  # 只看>100ms的

# === watch —— 观测入参/返回值/异常 ===
watch com.example.Service methodName '{params, returnObj, throwExp}' -x 2
# -b 观察方法调用前   -e 观察异常时   -s 观察返回后

# === stack —— 查看调用链 ===
stack com.example.Service methodName   # 谁调用了这个方法

# === monitor —— 方法统计 ===
monitor -c 10 com.example.Service methodName  # 每10秒统计QPS/RT
```

#### 3. 工具选择决策树

```
CPU 100%？
  → Arthas: thread -n 5 → 定位热点线程 → jad 反编译确认代码

接口响应慢？
  → Arthas: trace → 逐层找到耗时最多的方法

内存泄漏/OOM？
  → jcmd 导出堆转储 → MAT 分析（Leak Suspects → Dominator Tree）

GC 频繁/停顿长？
  → jstat -gcutil 看趋势 → GC 日志分析（GCEasy/GCViewer）

死锁？
  → jstack -l / Arthas thread -b

方法调用异常？
  → Arthas: watch '{params, throwExp}' -e

不确定类是哪个jar加载的？
  → Arthas: sc -d 类名
```

---

### 源码关键路径：jstack 如何拿到线程快照？

```cpp
// hotspot/src/share/vm/runtime/javaThread.cpp (简化)
void JavaThread::run() {
    // 线程运行时，每次遇到安全点（Safepoint）会停下来
    // jstack 触发线程快照的原理：
    // 1. 向目标进程发送 SIGQUIT 信号（kill -3 <pid>）或通过 JVM TI 接口
    // 2. JVM 让所有线程到达安全点（Stop-The-World）
    // 3. 遍历所有线程的栈帧，生成堆栈信息
    // 4. 恢复线程运行
}

// 这就是为什么 jstack 会在瞬间让应用停顿（通常几毫秒到几十毫秒）
// 高并发场景下，频繁 jstack 会影响响应时间
```

**为什么 Arthas 的 thread 命令对线上更友好？**
- Arthas 通过 Java Agent 方式 attach 到目标 JVM
- 采样线程堆栈时不需要全局 STW（非精确快照，但足够排查问题）
- `thread -n 5` 的性能开销远小于反复执行 `jstack`

---

## 深入原理

> 本节讲工具背后的工作原理，帮助你理解"为什么工具能工作"以及"工具的局限性"。

### HotSpot 的安全点（Safepoint）机制

jstack、jmap 等工具需要一个**全局安全点**才能拿到一致的快照。

```
┌──────────────────────────────────────────────────────────────┐
│                  Safepoint 机制                              │
│                                                              │
│  应用线程运行中 → 遇到 Safepoint 边界（如方法调用、循环回边）│
│       │                                                      │
│       ▼                                                      │
│  JVM 设置"需要进入 Safepoint"标志位                          │
│       │                                                      │
│       ▼                                                      │
│  所有线程自行到达最近的 Safepoint 并挂起                     │
│       │                                                      │
│       ▼                                                      │
│  JVM 执行需要 STW 的操作（如 jstack、GC）                  │
│       │                                                      │
│       ▼                                                      │
│  恢复所有线程                                               │
└──────────────────────────────────────────────────────────────┘
```

**为什么这很重要？**
- 如果应用中有**大量计算密集型线程**（没有方法调用/循环回边），可能无法及时到达 Safepoint，导致 jstack/jmap 长时间等待
- JDK 10+ 引入了"Thread-Local Handshake"，可以在不进入全局 Safepoint 的情况下操作单个线程

### MAT 的支配树（Dominator Tree）原理

MAT 的 Dominator Tree 不是简单的对象引用树，而是**支配关系**：

```
A 支配 B 的含义：从 GC Root 到 B 的所有路径，都必须经过 A。
→ 如果 A 被回收，B 也一定会被回收。
→ Retained Size of A = A 的 Shallow Size + 所有被 A 支配的对象大小之和。
```

**为什么 Dominator Tree 比引用树更有用？**
- 引用树会显示所有引用关系，包括弱引用、临时引用，信息过载
- Dominator Tree 直接告诉你：释放这个对象能回收多少内存——这正是排查内存泄漏最关心的指标

---

## 正确使用方式

> 不是罗列工具用法，而是讲清楚"每类问题应该怎么正确排查"。

### 1. OOM 排查——四步法

```
步骤1：确认 OOM 类型
         │
         ├── Java heap space    → 堆溢出，重点找大对象
         ├── Metaspace        → 元空间溢出，检查动态类加载
         ├── Direct buffer memory → 堆外内存溢出，检查 Netty/NIO
         └── unable to create new native thread → 线程数超限

步骤2：拿到 heap dump（越早越好）
         │
         ├── OOM 自动触发（推荐，提前配置）：
         │   -XX:+HeapDumpOnOutOfMemoryError
         │   -XX:HeapDumpPath=/var/log/app/dumps/
         │
         └── 手动触发（问题发生时）：
             jcmd <pid> GC.heap_dump filename=/tmp/heap.hprof
             ⚠️ jmap -dump 会触发 Full GC + STW，高并发时段慎用

步骤3：用 MAT 分析
         │
         ├── 先看 Leak Suspects（自动泄漏报告，入门首选）
         ├── 再看 Dominator Tree（按 Retained Size 排序）
         └── 找到最大对象 → Path To GC Roots → exclude weak/soft

步骤4：定位到代码，修复
         │
         ├── ThreadLocal 未 remove → 在 finally 中 remove()
         ├── 静态集合无限增长 → 改用 Guava Cache/Caffeine
         ├── 资源未关闭 → 改用 try-with-resources
         └── 内部类持有外部引用 → 改用 Lambda（不持有外部类引用）
```

**实战案例：堆内存溢出**

```
现象：
  java.lang.OutOfMemoryError: Java heap space
    at java.util.Arrays.copyOf(...)

MAT 分析：
  Leak Suspects → Problem Suspect 1: 占用 85% 堆
    → ArrayList 有 150 万个元素，Retained Size: 3.2GB
    → Path To GC Roots:
        ReportGenerator.generateReport()
          → static Map<String, List> orderCache
            → ArrayList (3.2GB，只 put 不 remove)

修复：
  改用 Caffeine Cache，设置 maxSize + expireAfterWrite
```

---

### 2. GC 频繁/停顿长排查

```bash
# 第1步：确认 GC 类型和频率
jstat -gcutil <pid> 1000
# 关注：O（Old 区使用率）、FGC（Full GC 次数）、FGCT（Full GC 总时间）

# 第2步：分析 GC 日志
# JDK 9+：-Xlog:gc*:file=gc.log:time,uptime,level,tags
# 上传到 GCEasy.io 自动分析，或本地用 GCViewer

# 第3步：判断根因
# ├── Old 区使用率只涨不降 → 内存泄漏，MAT 分析 dump
# ├── Minor GC 后 Old 区就涨很多 → Survivor 太小，对象提前晋升
# ├── GC 日志有 System.gc() → 代码显式调用，加 -XX:+DisableExplicitGC
# └── Humongous 对象过多（G1）→ 调大 G1HeapRegionSize 或避免大对象
```

**G1 常见问题与处理**：

| 现象 | 原因 | 解决方案 |
|------|------|----------|
| Mixed GC 停顿波动大 | Region 大小不合适 | 调小 G1HeapRegionSize（4MB），降低 MaxGCPauseMillis |
| 出现 Full GC（单线程） | 并发标记来不及，退化到 Serial Old | 降低 InitiatingHeapOccupancyPercent（35%），增加 ConcGCThreads |
| Humongous 对象导致 Full GC | 大对象直接进老年代 | 调大 RegionSize，避免一次性查大量数据 |

---

### 3. CPU 100% 排查

```bash
# 第1步：定位 CPU 最高的线程
top -Hp <pid>          # 找到 CPU 最高的线程 ID（十进制）
# 或用 Arthas（更方便）：
# arthas-boot.jar → 选择进程 → thread -n 5

# 第2步：线程 ID 转 16 进制
printf '%x\n' <线程ID>    # 输出如 17

# 第3步：查看线程堆栈
jstack <pid> | grep -A 30 "0x17"
# 或用 Arthas：thread <线程ID>

# 第4步：根据堆栈判断根因
# ├── 死循环：at com.example.Service.process(Service.java:156) 递归调用自己
# ├── 频繁 Full GC：at java.lang.ref.Reference.processPendingReferences → GC 线程占满 CPU
# ├── CAS 自旋：at sun.misc.Unsafe.compareAndSwapInt → ConcurrentHashMap 扩容
# └── 正则回溯：at java.util.regex.Pattern$GroupHead.match → ReDoS 攻击
```

---

### 4. 死锁排查与预防

```bash
# 快速检测
jstack -l <pid> | grep -A 20 "Found one Java-level deadlock"
# 或 Arthas：thread -b

# 常见死锁模式
# 模式1：嵌套锁（最经典）
#   线程A：先锁 accountA，再锁 accountB
#   线程B：先锁 accountB，再锁 accountA → 循环等待！
#   解决：统一加锁顺序（按 ID 排序）

# 模式2：锁未释放（synchronized 块中提前 return）
#   解决：用 try-finally 确保释放（synchronized 会自动释放，但 Lock 接口必须手动 unlock()）

# 模式3：数据库事务 + Java 锁混合
#   解决：统一顺序，或缩短锁持有时间
```

**预防规范**：
1. 减小锁粒度——能不加锁就不加
2. 统一加锁顺序——多把锁时约定统一顺序
3. 使用超时锁——`lock.tryLock(5, TimeUnit.SECONDS)`，获取失败则回退
4. 并发代码必须经过 Code Review

---

### 5. 线上 JVM 参数推荐模板

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
  -jar app.jar

# ===== 容器化部署（Docker/K8s）=====
# 不要硬编码 -Xms/-Xmx，让 JVM 感知容器限制
java \
  -XX:MaxRAMPercentage=75.0 \
  -XX:InitialRAMPercentage=75.0 \
  -XX:+UseContainerSupport \
  -XX:+UseG1GC \
  -XX:+HeapDumpOnOutOfMemoryError \
  -jar app.jar
```

---

### 6. 线上排查 Checklist

```
=== 发生 OOM ===
  □ 确认 OOM 类型（heap / metaspace / direct / thread）
  □ 检查 HeapDumpOnOutOfMemoryError 是否开启
  □ MAT 分析 heap dump（Leak Suspects → Dominator Tree）
  □ 查看 GC Roots 引用链

=== GC 频繁 / 停顿长 ===
  □ jstat -gcutil 确认 GC 频率和类型
  □ 下载 GC 日志，用 GCEasy 分析
  □ 检查是否有内存泄漏（Old 区使用率只涨不降）

=== CPU 100% ===
  □ top -Hp 找到 CPU 最高的线程
  □ jstack / Arthas thread 查看堆栈
  □ 区分：死循环 / GC 线程 / CAS 自旋 / 正则回溯

=== 接口响应慢 ===
  □ Arthas trace 方法调用链耗时
  □ 检查数据库慢查询
  □ 检查线程池是否耗尽

=== 死锁 ===
  □ jstack -l / Arthas thread -b
  □ 定位循环等待的两把锁和两个线程
```

---

## 边界情况和坑

> 不是列举，要解释"坑的成因"。

### 坑1：jmap -dump 触发 Full GC，高并发时段慎用

**成因**：`jmap -dump` 实现原理是触发一次 Full GC 来确保堆状态一致，再导出内存镜像。在 QPS 几万的系统上执行，可能导致几秒的全局停顿。

**解决方案**：
- 提前开启 `-XX:+HeapDumpOnOutOfMemoryError`，让 JVM 在 OOM 时自动 dump
- 使用 `jcmd <pid> GC.heap_dump`——它不需要触发 Full GC，对线上更友好
- 实在需要手动 dump，选在低峰期执行

---

### 坑2：MAT 分析大堆时内存不足

**成因**：MAT 本身也是 Java 程序，分析 8GB 的 heap dump 需要 MAT 有至少 8GB 以上堆内存。

**解决方案**：
```bash
# 修改 MAT 的启动参数（MemoryAnalyzer.ini）
-vmargs
-Xmx10g       # 至少比 heap dump 大 20%
-XX:+UseG1GC  # MAT 本身也用 G1，避免分析时卡顿
```

---

### 坑3：Arthas Attach 失败（JVM 启动参数限制）

**成因**：如果 JVM 启动时加了 `-XX:+DisableAttachMechanism`，无法通过 `jcmd` 或 Arthas attach 到进程。

**解决方案**：
- 检查 JVM 启动参数，去掉 `-XX:+DisableAttachMechanism`
- 如果无法修改启动参数，只能靠提前开启的 GC 日志和 `jstat` 排查

---

### 坑4：容器中的 JVM 无法识别内存限制（JDK 8u191 之前）

**成因**：早期 JDK 8 无法读取 Docker 的 cgroup 内存限制，`Runtime.getRuntime().maxMemory()` 返回的是宿主机物理内存，导致 `-Xmx` 设置超出容器限制，被 OOM Killer 杀掉。

**解决方案**：
- JDK 8u191+：开启 `-XX:+UseContainerSupport`（默认已开启）
- JDK 11+：默认支持容器，无需额外配置
- 推荐：容器化部署时用 `-XX:MaxRAMPercentage=75.0` 替代硬编码 `-Xmx`

---

### 坑5：正则匹配导致 CPU 100%（ReDoS）

**成因**：贪婪匹配 `.**` 遇到长字符串时可能产生指数级回溯。攻击者可以构造恶意输入，让服务 CPU 占满。

```java
// 危险代码：贪婪匹配
Pattern p = Pattern.compile("(a+)+");
p.matcher("aaaaaaaaaaaaaaaaaaaaaaaaaaaa!");  // ← 灾难性回溯！

// 解决方案1：使用非贪婪匹配或重写正则
Pattern p = Pattern.compile("a+");  // 不用分组和 + 嵌套

// 解决方案2：设置正则匹配超时（JDK 9+）
Pattern p = Pattern.compile(regex, Pattern.MATCHES);
// 通过 Thread.interrupt() 打断长时间匹配（需要自行实现）
```

---

### 坑6：ThreadLocal 在线程池中导致内存泄漏

**成因**（详见 `02_并发编程/02_JMM内存模型` 相关文档）：
- ThreadLocalMap 的 Entry 是弱引用（key 是 ThreadLocal，value 是强引用）
- 如果 ThreadLocal 被回收（key = null），value 仍然是强引用，无法被 GC
- 线程池中的线程会复用，value 永远无法被回收 → 内存泄漏

**解决方案**：
```java
// ❌ 错误：使用完 ThreadLocal 不清理
public void process() {
    CURRENT_USER.set(user);
    // 如果这里抛异常，set 的值永远留在 ThreadLocalMap 里
}

// ✅ 正确：必须在 finally 中 remove
public void process() {
    try {
        CURRENT_USER.set(user);
        // 业务逻辑
    } finally {
        CURRENT_USER.remove();  // 必须清理！
    }
}
```

---

> **经验**：JVM 调优只是辅助手段，真正的瓶颈往往在业务层面（数据库/网络/架构设计）。先优化业务，再调 JVM。真正的高手不只是调 JVM，而是先优化业务架构，JVM 调优只是最后一道防线。
