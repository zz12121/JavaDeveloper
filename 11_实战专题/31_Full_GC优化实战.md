# Full GC优化实战

> Full GC频繁的根因通常是：老年代过小、Metaspace不足、大对象直接进老年代。

---

## Full GC优化全链路架构

```
Full GC优化全链路架构
┌─────────────────┐
│  业务应用        │
│  - 对象生成      │
│  - 大对象分配    │
└────────┬────────┘
         │ 触发GC
         ▼
┌─────────────────┐
│  JVM内存区域    │
│  - Eden         │
│  - Survivor     │
│  - Old Gen      │
│  - Metaspace    │
└────────┬────────┘
         │ 分析
         ▼
┌─────────────────┐
│  诊断工具        │
│  - GC日志       │
│  - MAT/JProfiler│
│  - Arthas       │
└─────────────────┘
```

---

## 场景 A：对象生命周期分析

### 现象描述

Full GC频繁，GC日志显示老年代快速增长；Eden区对象还没到年龄阈值（默认15）就晋升到老年代。短生命周期对象（如临时DTO）占用老年代空间，无法被回收。

### 根因分析

Survivor区过小，无法容纳Minor GC后的存活对象，出发过早晋升（Premature Promotion）；对象年龄阈值设置过高，导致短期对象在Survivor区来回复制多次才晋升，浪费CPU。大对象（超过Eden区一半）直接分配在老年代，触发Full GC。

### 解决方案

```java
// 1. JVM参数调整对象晋升策略
// -XX:NewRatio=2 年轻代:老年代=1:2（年轻代占1/3）
// -XX:SurvivorRatio=8 Eden:Survivor=8:1:1（Survivor区占年轻代1/10）
// -XX:MaxTenuringThreshold=10 降低年龄阈值，减少短期对象在年轻代停留
// -XX:PretenureSizeThreshold=1m 大于1MB的对象直接进老年代（谨慎设置）

// 2. Java代码：分析对象生命周期（通过Arthas统计对象年龄）
// Arthas命令：heapdump --live /tmp/heap.hprof 抓取存活对象
// 用MAT分析：Histogram → 右键对象 → Merge Shortest Paths to GC Roots → 查看引用链

// 3. 代码示例：避免创建大对象
public class LargeObjectOptimizer {
    // 坏实践：创建1MB+的大对象
    public byte[] badPractice() {
        return new byte[2 * 1024 * 1024]; // 2MB数组，直接进老年代
    }
    
    // 好实践：拆分小对象，使用流式处理
    public void goodPractice(InputStream in, OutputStream out) throws IOException {
        byte[] buffer = new byte[8192]; // 8KB缓冲区，在Eden区分配
        int len;
        while ((len = in.read(buffer)) != -1) {
            out.write(buffer, 0, len);
        }
    }
}
```

---

## 场景 B：G1调优避免Full GC

### 现象描述

G1 GC仍然触发Full GC，日志显示Concurrent Mark Failed或Promotion Failed；停顿时间超过1秒，接口P99 RT飙升。Mixed GC回收速度赶不上对象晋升速度，老年代持续增长。

### 根因分析

InitiatingHeapOccupancyPercent设置过高（默认45），老年代占用过高才触发Mixed GC，导致回收不及时；G1ReservePercent过小（默认10），没有足够空间应对突然的对象晋升，触发Promotion Failed；并发标记阶段因为老年代占用过高，无法完成标记，触发Concurrent Mark Failed。

### 解决方案

```java
// 1. G1避免Full GC的核心参数
// -XX:G1ReservePercent=25 预留25%堆空间，应对晋升失败
// -XX:InitiatingHeapOccupancyPercent=35 老年代占用35%就触发Mixed GC（更早回收）
// -XX:G1MixedGCLiveThresholdPercent=85 Region存活对象占比低于85%才回收
// -XX:G1HeapWastePercent=5 堆垃圾占比超过5%就触发Mixed GC

// 2. Java代码：监控Full GC事件并告警
import java.lang.management.GarbageCollectorMXBean;
import java.lang.management.ManagementFactory;

public class FullGCMonitor {
    public static void monitorFullGC() {
        for (GarbageCollectorMXBean bean : ManagementFactory.getGarbageCollectorMXBeans()) {
            if ("G1 Old Generation".equals(bean.getName())) {
                long fullGCCount = bean.getCollectionCount();
                // 每隔1分钟检查一次Full GC次数
                // 如果每小时超过1次，触发告警
                System.out.println("G1 Full GC次数: " + fullGCCount);
            }
        }
    }
}
```

---

## 场景 C：Off-Heap设计

### 现象描述

堆内存使用率过高（超过90%），频繁Full GC；本地缓存（如Caffeine）占用大量堆空间，生命周期长，无法被GC回收。大文件处理（如上传1GB文件）导致堆内存快速耗尽。

### 根因分析

堆内缓存直接占用老年代空间，缓存过期时间设置过长，或缓存无限增长；大对象在堆内分配，年轻人代放不下直接进老年代；JVM堆内存受GC管理，大内存使用效率低，容易触发Full GC。

### 解决方案

```java
// 1. Off-Heap缓存示例（使用Ehcache堆外缓存）
import org.ehcache.Cache;
import org.ehcache.CacheManager;
import org.ehcache.config.builders.CacheConfigurationBuilder;
import org.ehcache.config.builders.CacheManagerBuilder;
import org.ehcache.config.units.MemoryUnit;

public class OffHeapCacheExample {
    public static Cache<String, byte[]> createOffHeapCache() {
        CacheManager cacheManager = CacheManagerBuilder.newCacheManagerBuilder()
                .withCache("offHeapCache",
                        CacheConfigurationBuilder.newCacheConfigurationBuilder(
                                String.class, byte[].class,
                                org.ehcache.config.builders.ResourcePoolsBuilder.newResourcePoolsBuilder()
                                        .offheap(1, MemoryUnit.GB) // 1GB堆外缓存
                        )
                )
                .build(true);
        
        return cacheManager.getCache("offHeapCache", String.class, byte[].class);
    }
}

// 2. Netty堆外内存示例（处理大文件）
import io.netty.buffer.ByteBuf;
import io.netty.buffer.PooledByteBufAllocator;

public class OffHeapBufferExample {
    public static void handleLargeFile(long fileSize) {
        // 分配堆外内存，不占用堆空间
        ByteBuf buffer = PooledByteBufAllocator.DEFAULT.directBuffer(8192);
        // 使用后必须释放，否则会内存泄漏
        buffer.release();
    }
}
```

---

## 场景 D：JMX监控

### 现象描述

Full GC发生后才知道，没有提前预警；无法实时查看老年代使用率、Metaspace使用率等关键指标。老年代使用率悄悄涨到95%才触发Full GC，没有缓冲时间。

### 根因分析

未开启JMX远程监控，无法实时获取JVM内存指标；未设置告警规则，老年代使用率超过阈值（如80%）不触发告警；监控数据采集间隔过长（如5分钟），无法及时发现增长趋势。

### 解决方案

```java
// 1. Java代码：通过JMX实时监控老年代使用率
import java.lang.management.ManagementFactory;
import java.lang.management.MemoryPoolMXBean;
import java.util.List;

public class OldGenMonitor {
    public static double getOldGenUsage() {
        List<MemoryPoolMXBean> pools = ManagementFactory.getMemoryPoolMXBeans();
        for (MemoryPoolMXBean pool : pools) {
            // G1的老年代名称是G1 Old Gen，Parallel是Tenured Gen
            if (pool.getName().contains("Old Gen") || pool.getName().contains("Tenured Gen")) {
                long used = pool.getUsage().getUsed();
                long max = pool.getUsage().getMax();
                return max > 0 ? (double) used / max * 100 : 0;
            }
        }
        return 0;
    }
    
    public static void checkAndAlarm() {
        double oldGenUsage = getOldGenUsage();
        if (oldGenUsage > 80) {
            System.out.println("告警：老年代使用率超过80%，当前：" + oldGenUsage + "%");
            // 触发告警，通知运维人员
        }
    }
}
```

---

## 核心参数估算

| 参数项 | 估算值 | 说明 |
|--------|--------|------|
| 堆大小 | 32G | 避免过大导致GC停顿长 |
| 年轻代占比 | 40% | 12.8G，减少对象过早晋升 |
| Survivor ratio | 8 | Eden:Survivor=8:1:1 |
| Metaspace大小 | 512M | 固定大小，避免动态扩容 |
| Pretenure阈值 | 1MB | 大对象直接进老年代 |
| G1 InitiatingOccupancy | 35% | 提前触发Mixed GC |
| G1 ReservePercent | 25% | 预留空间防止晋升失败 |
| Full GC频率 | < 1次/天 | 优化后目标 |

---

## 涉及知识点

| 知识点 | 所属域 | 关键点 |
|--------|--------|--------|
| Full GC根因 | 01_JVM/02_垃圾收集器 | 晋升失败、并发失败、Metaspace不足 |
| G1调优 | 01_JVM/02_垃圾收集器 | Mixed GC、Region回收、停顿预测 |
| Off-Heap内存 | 01_JVM/03_内存模型 | 堆外缓存、直接内存、Netty ByteBuf |
| 对象生命周期 | 01_JVM/03_内存模型 | 年龄阈值、过早晋升、大对象分配 |
| JMX监控 | 01_JVM/05_监控调优 | 内存池指标、老年代使用率、告警触发 |

---

## 排查 Checklist

```text
□ Survivor区是否足够？ → SurvivorRatio=8，避免过早晋升
□ 老年代增长是否过快？ → 监控老年代使用率，每天增长<5%
□ Full GC触发原因是什么？ → 查看GC日志：Promotion Failed/Concurrent Failed/Metadata
□ 大对象是否进老年代？ → PretenureSizeThreshold合理，避免小对象进老年代
□ Metaspace是否泄漏？ → 使用率<80%，类加载器无泄漏
□ Off-Heap是否使用？ → 缓存、大文件用堆外内存，减少堆压力
□ G1参数是否合理？ → InitiatingOccupancy<40%，ReservePercent>20%
□ 监控是否覆盖？ → 老年代使用率、Full GC次数实时监控告警
□ 代码是否优化？ → 避免创建大对象，短生命周期对象不缓存
□ 压测是否验证？ → 模拟业务高峰，验证无Full GC
```

---

## 追问链

### 追问 1：如何判断是哪种原因导致的Full GC？

> "看GC日志关键词：1. Promotion Failed → 晋升失败，Survivor或老年代空间不足；2. Concurrent Mode Failed → 并发收集失败，老年代增长太快；3. Metadata GC Threshold → Metaspace不足；4. Ergonomics → 自适应调整触发。用Arthas执行`gc`命令可快速查看最近GC原因。"

### 追问 2：Off-Heap内存泄漏如何排查？

> "Off-Heap泄漏排查：1. Netty直接内存：开启`-Dio.netty.leakDetection.level=paranoid`检测泄漏；2. Ehcache堆外：查看缓存命中率、淘汰策略；3. Java NIO：用`jcmd <pid> VM.native_memory detail`查看直接内存使用；4. 堆外内存无法被GC回收，必须手动释放（如ByteBuf.release()）。"

### 追问 3：G1和ZGC哪个更不容易Full GC？

> "ZGC几乎不会Full GC，因为停顿时间与堆大小无关，并发回收效率高。G1在极端场景（如对象分配速率远超回收速率）下仍可能Full GC。但ZGC需要JDK 17+，G1在JDK 8+可用。如果已经用JDK 8，优先调优G1参数避免Full GC。"

### 追问 4：Metaspace满了会触发Full GC吗？

> "会。Metaspace不足时触发Full GC，尝试回收无用的类元数据。如果Full GC后空间仍不足，抛出OOM: Metaspace。解决方案：1. 调大Metaspace（`-XX:MaxMetaspaceSize=512m`）；2. 排查类加载器泄漏（如Web容器热部署未清理ClassLoader）；3. 减少动态代理、反射生成类的使用。"

---

## 我的实战笔记

-（待补充，项目中的真实经历）
