# 亿级QPS系统GC策略选型与调优

> GC策略选型核心是停顿时间 vs 吞吐量。100万QPS系统必须选G1或ZGC。

---

## GC策略选型全链路架构

```
亿级QPS Java应用系统
   │
   ▼
┌─────────────────┐
│  业务应用实例    │
│  (JVM 堆 32G)   │
│  - 年轻代 16G    │
│  - 老年代 16G    │
└────────┬────────┘
         │ GC触发
         ▼
┌─────────────────┐
│  GC策略选择     │
│  ├─ G1 GC       │
│  ├─ ZGC         │
│  └─ Shenandoah  │
└────────┬────────┘
         │ 监控
         ▼
┌─────────────────┐
│  可观测性平台   │
│  - GC日志采集   │
│  - JMX指标      │
│  - 告警规则     │
└─────────────────┘
```

---

## 场景 A：G1调优参数

### 现象描述

亿级QPS系统使用Parallel GC时，每次Young GC停顿时间达100ms+，Full GC停顿超1秒，导致接口P99 RT飙升到500ms+。业务高峰期GC频率从每秒1次升至5次，CPU因GC占用超过30%，正常业务处理能力下降。

### 根因分析

Parallel GC是吞吐量优先的收集器，年轻代使用标记-复制算法，老年代使用标记-整理，停顿时间与堆大小、存活对象数量正相关。亿级QPS下对象生成速率达GB/s级，年轻代很快填满触发频繁Young GC。G1 GC将堆划分为多个大小相等的Region，优先回收垃圾最多的Region（Garbage First），通过Remember Set避免全堆扫描，停顿时间可预测（MaxGCPauseMillis参数控制）。

### 解决方案

```java
// 1. G1 GC核心调优参数（适用于32G堆、亿级QPS场景）
// -XX:+UseG1GC 启用G1收集器
// -Xmx32g -Xms32g 堆大小固定，避免动态扩容触发GC
// -XX:MaxGCPauseMillis=50 目标最大停顿时间50ms（软目标，尽量满足）
// -XX:G1HeapRegionSize=4m Region大小为4MB（32G堆共8192个Region）
// -XX:G1NewSizePercent=30 年轻代初始占比30%（9.6G）
// -XX:G1MaxNewSizePercent=40 年轻代最大占比40%（12.8G）
// -XX:InitiatingHeapOccupancyPercent=45 老年代占用45%时触发Mixed GC
// -XX:G1ReservePercent=10 预留10%堆空间防止晋升失败
// -Xlog:gc*:file=/logs/gc_%p.log:time,uptime,level,tags:filecount=10,filesize=100M GC日志配置

// 2. Java代码：通过JMX监控G1 GC指标
import java.lang.management.GarbageCollectorMXBean;
import java.lang.management.ManagementFactory;
import java.util.List;

public class G1Monitor {
    public static void printG1Stats() {
        // 获取所有GC收集器MXBean
        List<GarbageCollectorMXBean> gcBeans = ManagementFactory.getGarbageCollectorMXBeans();
        for (GarbageCollectorMXBean bean : gcBeans) {
            // 只关注G1相关的收集器（G1 Young Generation、G1 Old Generation）
            if (bean.getName().contains("G1")) {
                System.out.println("GC名称: " + bean.getName());
                System.out.println("GC次数: " + bean.getCollectionCount());
                System.out.println("GC总耗时: " + bean.getCollectionTime() + "ms");
            }
        }
    }
}
```

---

## 场景 B：ZGC超低延迟

### 现象描述

金融交易类场景要求GC停顿时间低于10ms，G1即使设置MaxGCPauseMillis=10也无法稳定满足，大堆场景下停顿时间波动大。ZGC在JDK 11+引入，设计目标停顿时间不超过10ms，支持TB级堆，但早期版本有稳定性问题，JDK 17+后趋于成熟。

### 根因分析

ZGC采用染色指针、读屏障、内存多重映射技术，几乎所有阶段都是并发执行（标记、转移、引用处理），只有根扫描等极短操作需要停顿，停顿时间与堆大小、存活对象数量无关。G1的停顿时间仍与收集的Region数量相关，大堆场景下Mixed GC可能回收大量Region，导致停顿时间超标。

### 解决方案

```java
// 1. ZGC调优参数（JDK 17+，适用于32G堆、超低延迟场景）
// -XX:+UseZGC 启用ZGC
// -Xmx32g -Xms32g 固定堆大小
// -XX:ZAllocationSpikeTolerance=5 分配尖峰容忍度，避免过早触发GC
// -XX:ZCollectionInterval=5 最多5秒触发一次GC
// -XX:ZFragmentationLimit=10 碎片率超过10%时触发压缩
// -Xlog:gc*:file=/logs/zgc_%p.log:time,uptime,level,tags:filecount=10,filesize=100M ZGC日志配置

// 2. Java代码：触发ZGC主动回收（生产环境谨慎使用）
public class ZGCForceCollect {
    public static void forceZGC() {
        // 通过JMX调用GC（仅用于测试，生产不建议主动调用）
        System.gc(); // ZGC下System.gc()会触发异步GC，不会停顿应用
        System.out.println("已触发ZGC异步回收");
    }
}
```

---

## 场景 C：GC日志分析

### 现象描述

GC日志文件体积大，每天生成10GB+日志，无法快速定位Full GC根因；日志中存活对象大小、停顿时间等关键指标无法自动化提取。未接入日志分析平台，依赖人工排查，平均定位问题时间超过2小时。

### 根因分析

GC日志未结构化输出，缺少关键指标（如晋升失败次数、并发标记失败次数）；默认日志格式为文本，无法被日志平台自动解析；未配置日志轮转，单个日志文件过大，打开分析耗时。

### 解决方案

```java
// 1. GC日志结构化配置（输出JSON格式，便于日志平台采集）
// -Xlog:gc*:file=/logs/gc_%p.log:json,time,uptime,level,tags:filecount=10,filesize=100M
// 日志示例：{"log":"GC pause (G1 Evacuation Pause)","level":"info","time":"2024-01-01T12:00:00.000+0800","tags":["gc","pause"],"uptime":1000,"gc_time":50}

// 2. Java代码：解析GC日志统计停顿时间
import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Paths;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

public class GCLogAnalyzer {
    private static final Pattern PAUSE_PATTERN = Pattern.compile("\"gc_time\":(\\d+)");

    public static void analyzeGCPause(String logPath) throws IOException {
        // 读取GC日志文件
        String content = Files.readString(Paths.get(logPath));
        Matcher matcher = PAUSE_PATTERN.matcher(content);
        int totalPause = 0;
        int count = 0;
        while (matcher.find()) {
            int pause = Integer.parseInt(matcher.group(1));
            totalPause += pause;
            count++;
        }
        System.out.println("GC总停顿时间: " + totalPause + "ms");
        System.out.println("平均停顿时间: " + (count == 0 ? 0 : totalPause / count) + "ms");
        System.out.println("GC次数: " + count);
    }
}
```

---

## 场景 D：Full GC排查

### 现象描述

系统运行中突然触发Full GC，停顿时间超1秒，接口超时率飙升；GC日志显示晋升失败（Promotion Failed）或并发标记失败（Concurrent Mark Failed）。频繁Full GC会导致系统不可用，影响亿级QPS的正常业务。

### 根因分析

年轻代对象晋升到老年代时，老年代没有足够连续空间（晋升失败）；老年代空间不足，并发收集来不及回收（并发失败）；Metaspace不足触发Full GC。核心原因是对象生命周期过长、内存泄漏，或JVM参数配置不合理（如老年代过小、Metaspace未设上限）。

### 解决方案

```java
// 1. Full GC常见原因与参数调整
// 晋升失败：增大老年代空间（降低-XX:G1MaxNewSizePercent减小年轻代占比），或增大-XX:G1ReservePercent
// 并发失败：降低-XX:InitiatingHeapOccupancyPercent（提前触发Mixed GC），或增大堆大小
// Metaspace不足：-XX:MetaspaceSize=256m -XX:MaxMetaspaceSize=512m 固定Metaspace大小

// 2. Java代码：生成Heap Dump用于内存泄漏排查
import java.lang.management.ManagementFactory;
import com.sun.management.HotSpotDiagnosticMXBean;
import java.io.IOException;

public class HeapDumpGenerator {
    public static void generateHeapDump(String filePath) throws IOException {
        // 获取HotSpot诊断MXBean
        HotSpotDiagnosticMXBean diagnosticBean = ManagementFactory.getPlatformMXBean(HotSpotDiagnosticMXBean.class);
        // 生成Heap Dump（live=true只转储存活对象）
        diagnosticBean.dumpHeap(filePath, true);
        System.out.println("Heap Dump已生成: " + filePath);
    }
}
```

---

## 核心参数估算

| 参数项 | 估算值 | 说明 |
|--------|--------|------|
| 系统QPS | 1亿+ | 亿级QPS场景 |
| 接口P99 RT | < 100ms | GC停顿占比<5% |
| JVM堆大小 | 32G | 固定堆，避免扩容 |
| 年轻代大小 | 12G | 占堆37.5%，G1 MaxNewSizePercent=40 |
| 老年代大小 | 20G | 占堆62.5% |
| G1目标停顿时间 | 50ms | MaxGCPauseMillis=50 |
| ZGC停顿时间 | < 10ms | 超低延迟场景 |
| GC线程数 | 8 | ParallelGCThreads=8，与CPU核数匹配 |
| CPU使用率（GC占比） | < 10% | 优化后GC不占用过多CPU |
| 内存使用率 | 70% | 堆使用率不超过70%触发GC |

---

## 涉及知识点

| 知识点 | 所属域 | 关键点 |
|--------|--------|--------|
| G1 GC | 01_JVM/02_垃圾收集器 | Region划分、Remember Set、Mixed GC、停顿时间预测 |
| ZGC | 01_JVM/02_垃圾收集器 | 染色指针、读屏障、并发转移、TB级堆支持 |
| GC日志分析 | 01_JVM/05_监控调优 | 日志结构化、-Xlog参数、停顿时间统计 |
| Full GC排查 | 01_JVM/05_监控调优 | 晋升失败、并发失败、Metaspace泄漏、Heap Dump分析 |
| JMX监控 | 01_JVM/05_监控调优 | GC指标采集、MXBean使用、远程监控配置 |

---

## 排查 Checklist

```text
□ G1/ZGC收集器是否启用？ → 检查JVM参数-XX:+UseG1GC或-XX:+UseZGC
□ GC停顿时间是否满足要求？ → G1 <50ms，ZGC <10ms，P99 RT无飙升
□ GC日志是否开启并结构化？ → 日志包含时间、停顿时间、GC类型，接入日志平台
□ 堆大小是否固定？ → -Xmx等于-Xms，避免动态扩容触发GC
□ 老年代使用率是否预警？ → 超过70%触发告警，提前排查内存泄漏
□ Metaspace是否泄漏？ → Metaspace使用率超过80%告警，检查类加载器泄漏
□ Full GC是否频繁？ → 每小时Full GC超过1次需排查根因
□ GC线程数是否合理？ → ParallelGCThreads与CPU核数匹配，避免过多占用CPU
□ 监控是否覆盖GC指标？ → 采集GC次数、停顿时间、堆使用率等核心指标
□ 压测是否验证GC表现？ → 模拟亿级QPS压测，验证GC停顿时间符合预期
```

---

## 追问链

### 追问 1：亿级QPS系统如何选择G1和ZGC？

> "核心看停顿时间要求：如果要求P99停顿<50ms，选G1（JDK 8+可用，成熟稳定）；如果要求<10ms，选ZGC（JDK 17+成熟，支持TB级堆）。另外看堆大小：堆小于32G优先G1，大于32G优先ZGC。还要考虑JDK版本：如果用JDK 8，只能用G1；JDK 17+优先ZGC。"

### 追问 2：G1的MaxGCPauseMillis设置为10ms为什么达不到？

> "MaxGCPauseMillis是软目标，G1只尽量满足，不保证。如果年轻代对象太多，转移时需要复制大量对象，停顿时间就会超标。解决方案：增大年轻代大小（提高G1MaxNewSizePercent），减少每次回收的Region数量；或降低对象生成速率（优化代码，减少临时对象）。"

### 追问 3：ZGC在JDK 11版本有什么坑？

> "JDK 11的ZGC是实验性特性，稳定性不足：1. 不支持压缩类空间（Compressed Class Space），容易OOM；2. 并发转移阶段可能触发写屏障风暴，导致CPU飙升；3. 不支持ARM架构。生产环境建议用JDK 17+的ZGC，已标记为生产可用。"

### 追问 4：如何定位Full GC的根因？

> "四步定位法：1. 看GC日志：找到Full GC触发原因（Promotion Failed/Concurrent Mode Failed/Metadata GC Threshold）；2. 生成Heap Dump：用jmap或JMX生成堆转储；3. 分析Heap Dump：用MAT或JProfiler找到占用内存最大的对象；4. 排查代码：定位对象泄漏点（如静态集合未清理、缓存未设置过期时间）。"

---

## 我的实战笔记

-（待补充，项目中的真实经历）
