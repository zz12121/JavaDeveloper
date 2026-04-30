# JVM调优

## 这个问题为什么存在？

> 从「没有这个东西会怎样」出发，解释问题的根源。

默认JVM参数在生产环境中往往**不是最优配置**：

```bash
# 默认配置
java -Xms2m -Xmx64m MyApp
```

**痛点**：
1. **内存设置不当**：`-Xms`和`-Xmx`不同，导致堆内存动态调整，产生性能开销
2. **GC选择不当**：使用默认收集器（JDK8前的Parallel），无法满足低延迟需求
3. **没有GC日志**：发生OOM或GC频繁时，无法排查问题
4. **元空间溢出**：加载大量类时（如Spring、Hibernate），元空间默认大小不足

**核心问题**：如何根据**应用特性**（吞吐量优先 or 低延迟优先）、**硬件资源**（内存大小、CPU核数），调整JVM参数，使性能最优？

JVM调优的本质是**在吞吐量、延迟、内存占用三者之间找到平衡点**。

## 它是怎么解决问题的？

> 不止讲「是什么」，要讲清楚「为什么这样设计能解决问题」。

### 核心机制

#### 1. JVM调优的3个核心指标

```
┌─────────────────────────────────────────────────────────────┐
│                  JVM 调优的三个核心指标                    │
│                                                             │
│  1. 吞吐量（Throughput）                            │
│     - 定义：运行用户代码时间 / 总时间                   │
│     - 目标：越高越好（适合后台计算、报表生成）          │
│                                                             │
│  2. 延迟（Latency）                                 │
│     - 定义：单次GC停顿时间                              │
│     - 目标：越低越好（适合Web应用、实时系统）          │
│                                                             │
│  3. 内存占用（Footprint）                             │
│     - 定义：JVM占用的内存大小                          │
│     - 目标：在吞吐量和延迟可接受的前提下，越小越好     │
│                                                             │
│  三者不可兼得：吞吐量 ↑ → 延迟 ↑                        │
│               延迟 ↓ → 吞吐量 ↓                        │
└─────────────────────────────────────────────────────────────┘
```

**为什么需要区分这三个指标？**
- 不同应用场景对JVM的要求不同
- **吞吐量优先**：报表系统、离线计算
- **延迟优先**：电商网站、金融交易系统
- **内存占用优先**：云环境、容器化部署

#### 2. JVM参数分类

JVM参数分为三种：

| 参数类型 | 格式 | 示例 | 作用 |
|---------|------|------|------|
| **标准参数** | `-参数名` | `-version`、`-help` | 所有JVM实现都支持 |
| **非标准参数（X）** | `-X参数名` | `-Xms`、`-Xmx`、`-Xss` | 特定JVM实现支持（HotSpot） |
| **非Stable参数（XX）** | `-XX:[+-]<参数名>` 或 `-XX:<参数名>=<值>` | `-XX:+UseG1GC`、`-XX:MetaspaceSize=128m` | 不稳定，可能随时变更 |

**为什么需要三类参数？**
- **标准参数**：保证跨JVM实现兼容
- **X参数**：HotSpot特有的常用配置
- **XX参数**：高级调优参数，最灵活但也最不稳定

#### 3. 关键JVM参数详解

**堆内存设置**：
```bash
# 1. 初始堆大小（Xms）和最大堆大小（Xmx）
-Xms4g  # 初始堆4GB
-Xmx4g  # 最大堆4GB

# 为什么要把Xms和Xmx设为相同？
# → 避免堆内存动态调整，减少性能开销
# → 线上环境必须设置相同！
```

**新生代设置**：
```bash
# 2. 新生代大小
-Xmn2g  # 新生代大小2GB（直接设置，比NewRatio更直观）

# 3. 新生代与老年代比例
-XX:NewRatio=2  # 新生代:老年代 = 1:2（新生代占1/3）

# 4. Eden区与Survivor区比例
-XX:SurvivorRatio=8  # Eden:Survivor = 8:1:1（Eden占新生代的80%）

# 为什么SurvivorRatio=8？
# → 对象朝生夕死，Eden区需要大，Survivor区可以小
```

**元空间设置**：
```bash
# 5. 元空间大小
-XX:MetaspaceSize=128m  # 初始元空间大小（触发GC的阈值）
-XX:MaxMetaspaceSize=256m  # 最大元空间大小

# 为什么设置MetaspaceSize？
# → 避免元空间动态调整（默认很小，容易频繁触发GC）
```

**GC日志设置**：
```bash
# JDK 9+ 开启GC日志
-Xlog:gc*:file=gc.log:time,uptime,level,tags

# JDK 8 开启GC日志
-XX:+PrintGC
-XX:+PrintGCDetails
-XX:+PrintGCTimeStamps
-Xloggc:gc.log
```

#### 4. GC日志分析

**Parallel GC的GC日志**：
```
2024-01-01T10:00:00.000+0800: [GC (Allocation Failure)
    [PSYoungGen: 524800K->767K(611840K)]
    524800K->767K(2010112K), 0.0012345 secs]
    [Times: user=0.00 sys=0.00, real=0.00 secs]
```

**含义**：
- `PSYoungGen: 524800K->767K`：新生代GC前524800KB，GC后767KB
- `524800K->767K(2010112K)`：整个堆GC前524800KB，GC后767KB
- `0.0012345 secs`：GC停顿时间

**G1 GC的GC日志**：
```
[GC pause (G1 Evacuation Pause) (young), 0.0023456 secs]
   [Parallel Time: 1.2ms]
   [GC Worker Start (ms): 100.1]
   ...
```

**为什么需要分析GC日志？**
- 判断是否是内存泄漏（老年代使用率只涨不落）
- 判断GC是否过于频繁（Minor GC每秒一次）
- 判断GC停顿时间是否过长（影响响应时间）

### ASCII图：JVM调优流程

```
┌─────────────────────────────────────────────────────────────┐
│                  JVM 调优流程                               │
│                                                             │
│  1. 明确调优目标（吞吐量 or 延迟 or 内存占用）           │
│       │                                             │
│       ▼                                             │
│  2. 选择垃圾收集器                                    │
│     - 吞吐量优先 → Parallel GC                         │
│     - 延迟优先 → CMS（JDK 8）、G1（JDK 9+）      │
│     - 超低延迟 → ZGC（JDK 11+）                    │
│       │                                             │
│       ▼                                             │
│  3. 设置关键JVM参数（Xms、Xmx、NewRatio等）        │
│       │                                             │
│       ▼                                             │
│  4. 开启GC日志（-Xlog:gc*）                         │
│       │                                             │
│       ▼                                             │
│  5. 压测，收集GC日志                                │
│       │                                             │
│       ▼                                             │
│  6. 分析GC日志（使用GC分析工具）                      │
│       │                                             │
│       ├── 吞吐量少 → 调大堆、使用Parallel GC            │
│       │                                             │
│       └── 延迟高 → 调小MaxGCPauseMillis、使用G1/ZGC │
│                                                             │
│  7. 验证调优效果（重复4-6）                        │
└─────────────────────────────────────────────────────────────┘
```

### 源码关键路径

#### JVM参数的解析过程

```cpp
// hotspot/src/share/vm/runtime/arguments.cpp (简化)
void Arguments::parse_each_vm_init_arg(const char* arg) {
    // 1. 解析标准参数
    if (strcmp(arg, "-version") == 0) {
        print_version();
        return;
    }
    
    // 2. 解析X参数
    if (strncmp(arg, "-X", 2) == 0) {
        if (strcmp(arg, "-Xms") == 0) {
            set_initial_heap_size(arg);
        } else if (strcmp(arg, "-Xmx") == 0) {
            set_max_heap_size(arg);
        }
        return;
    }
    
    // 3. 解析XX参数
    if (strncmp(arg, "-XX:", 4) == 0) {
        if (strstr(arg, "UseG1GC") != NULL) {
            select_g1_gc();  // 选择G1收集器
        } else if (strstr(arg, "MaxGCPauseMillis") != NULL) {
            set_max_gc_pause_time(arg);
        }
        return;
    }
}
```

**为什么需要解析这些参数？**
- JVM启动时需要知道：堆多大、用什么GC、元空间多大
- 解析完后，这些参数会保存在`Arguments`类中，供后续使用

## 它和相似方案的本质区别是什么？

> 对比不是列表，要解释「为什么选 A 不选 B」。

### Parallel GC vs G1 GC

| 维度 | Parallel GC | G1 GC |
|------|--------------|---------|
| **适用场景** | 吞吐量优先 | 延迟优先（可预测停顿） |
| **堆大小** | 适合中小堆（< 4GB） | 适合大堆（> 4GB） |
| **停顿时间** | 长（秒级） | 短（毫秒级，可预测） |
| **碎片处理** | 标记-整理（无碎片） | 复制算法（无碎片） |
| **JDK版本** | 默认（JDK 8及之前） | 默认（JDK 9及之后） |

**为什么选Parallel GC？**
- **吞吐量优先**：如报表生成、离线计算
- **堆较小**：< 4GB，Parallel GC的停顿时间也可接受

**为什么选G1 GC？**
- **延迟优先**：如Web应用，要求停顿时间短
- **大堆**：> 4GB，G1的Region化设计可以避免全堆扫描

### CMS vs G1

| 维度 | CMS | G1 |
|------|-----|-----|
| **算法** | 标记-清除（有碎片） | 标记-整理+复制（无碎片） |
| **碎片处理** | 需要Full GC时整理 | 每次GC都整理 |
| **停顿可预测** | ❌ | ✅（`MaxGCPauseMillis`） |
| **适用场景** | 老年代（与ParNew配合） | 整堆（新生代+老年代） |

**为什么CMS被废弃（JDK 14移除）？**
- **碎片问题严重**：标记-清除算法会产生内存碎片
- **Full GC停顿长**：碎片过多时，会触发Full GC（使用Serial Old，单线程整理）
- **G1全面替代**：G1在JDK 9成为默认，性能更好

## 正确使用方式

> 不是 API 手册，要解释「为什么这样用是对的」。

### 1. 推荐的JVM参数模板

**吞吐量优先（报表系统、离线计算）**：
```bash
java -Xms4g -Xmx4g \
     -Xmn2g \
     -XX:+UseParallelGC \
     -XX:MaxGCPauseMillis=200 \
     -XX:+HeapDumpOnOutOfMemoryError \
     -Xlog:gc*:file=gc.log:time,uptime,level,tags \
     MyApp
```

**为什么这样配置？**
- `Xms4g -Xmx4g`：避免堆动态调整
- `UseParallelGC`：吞吐量优先
- `HeapDumpOnOutOfMemoryError`：OOM时生成堆转储，便于排查

**延迟优先（Web应用、电商系统）**：
```bash
java -Xms8g -Xmx8g \
     -XX:+UseG1GC \
     -XX:MaxGCPauseMillis=200 \
     -XX:MetaspaceSize=128m \
     -XX:MaxMetaspaceSize=256m \
     -XX:+HeapDumpOnOutOfMemoryError \
     -Xlog:gc*:file=gc.log:time,uptime,level,tags \
     MyApp
```

**为什么这样配置？**
- `UseG1GC`：延迟优先，可预测停顿
- `MaxGCPauseMillis=200`：目标停顿时间200ms
- `MetaspaceSize=128m`：避免元空间动态调整

### 2. 使用工具分析GC日志

**GCViewer**（开源工具）：
```bash
# 使用GCViewer分析GC日志
java -jar gcviewer-1.36.jar gc.log
```

**为什么需要工具？**
- 肉眼看GC日志很困难
- GCViewer可以生成图表，直观展示GC频率、停顿时间

**GCEasy**（商业工具，在线）：
- 上传GC日志，自动分析
- 给出调优建议

### 3. 压测验证调优效果

```bash
# 1. 使用JMeter或ab进行压测
ab -n 10000 -c 100 http://localhost:8080/

# 2. 收集GC日志

# 3. 分析GC日志，关注指标：
#    - 吞吐量（应用运行时间 / 总时间）
#    - 平均GC停顿时间
#    - 最大GC停顿时间
#    - GC频率（Minor GC / Full GC）
```

**为什么需要压测？**
- 不同应用的JVM调优参数不同
- 压测可以模拟真实场景，验证调优效果

## 边界情况和坑

> 不是列举，要解释「坑的成因」。

### 坑1：`-Xms`和`-Xmx`设置不同

```bash
# 错误配置
java -Xms2g -Xmx8g MyApp
```

**成因**：堆内存会根据使用情况动态调整，调整时会触发GC，产生性能开销。

**解决方案**：线上环境必须设置相同！

### 坑2：忽略元空间设置

```bash
# 错误配置：不设置MetaspaceSize
java -Xms8g -Xmx8g -XX:+UseG1GC MyApp
```

**成因**：元空间初始很小，会频繁触发GC来调整大小。

**解决方案**：设置`-XX:MetaspaceSize=128m`（初始元空间大小）。

### 坑3：OOM时没有堆转储

```bash
# 错误配置：不开启HeapDumpOnOutOfMemoryError
java -Xms8g -Xmx8g MyApp
```

**成因**：发生OOM时，无法生成堆转储，导致无法排查问题。

**解决方案**：开启`-XX:+HeapDumpOnOutOfMemoryError`。

### 坑4：GC日志没有开启

```bash
# 错误配置：不开启GC日志
java -Xms8g -Xmx8g MyApp
```

**成因**：发生GC频繁或停顿时间长时，无法排查问题。

**解决方案**：开启GC日志（`-Xlog:gc*`）。

### 坑5：在容器中不识别CGroup限制

```bash
# 在Docker容器中运行Java
docker run -m 4g java -Xms8g -Xmx8g MyApp
```

**成因**：JDK 8u191之前，JVM无法识别Docker的内存限制，会分配8GB堆，导致容器被kill。

**解决方案**：
- 使用JDK 8u191+，开启`-XX:+UseContainerSupport`
- 或者直接使用JDK 11+（默认支持容器）

## 我的理解（可选）

> 用自己的话重新表述一遍，检验是否真正理解。

JVM调优的本质是**在吞吐量、延迟、内存占用三者之间找到平衡点**。

**核心思想**：
- **明确调优目标**：吞吐量优先 or 延迟优先
- **选择合适收集器**：Parallel（吞吐量）、G1（延迟）、ZGC（超低延迟）
- **设置关键参数**：Xms、Xmx、NewRatio、MetaspaceSize等
- **开启GC日志**：便于排查问题
- **压测验证**：模拟真实场景，验证调优效果

**为什么需要JVM调优？**
- 默认参数往往不是最优
- 不同应用场景对JVM的要求不同

**最容易被忽略的点**：
- `Xms`和`Xmx`必须设置相同
- 开启`HeapDumpOnOutOfMemoryError`和GC日志
- 在容器中运行Java，需要使用JDK 8u191+或JDK 11+

## 面试话术总结

1. **JVM调优的基本原则？**
   "JVM调优的基本原则：1）明确调优目标（吞吐量 or 延迟 or 内存占用）；2）选择合适的垃圾收集器；3）设置关键JVM参数；4）开启GC日志；5）压测验证调优效果。"

2. **吞吐量优先和延迟优先分别选择什么收集器？**
   "吞吐量优先：Parallel GC（JDK 8及之前默认）。延迟优先：CMS（JDK 8）、G1（JDK 9+默认）、ZGC（JDK 11+）。"

3. **为什么要把-Xms和-Xmx设为相同？**
   "避免堆内存动态调整，减少性能开销。线上环境必须设置相同！"

4. **如何排查GC频繁的问题？**
   "步骤：1）开启GC日志；2）压测，收集GC日志；3）使用GCViewer或GCEasy分析GC日志；4）关注指标：吞吐量、平均GC停顿时间、最大GC停顿时间、GC频率；5）根据分析结果调整JVM参数。"

5. **在容器中运行Java需要注意什么？**
   "使用JDK 8u191+，开启`-XX:+UseContainerSupport`；或者直接使用JDK 11+（默认支持容器）。否则JVM无法识别Docker的内存限制，会导致容器被kill。"
