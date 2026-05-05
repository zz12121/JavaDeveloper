# JVM 调优常用的参数有哪些？怎么分析 GC 日志？

> ⚠️ **先盲答**：JVM 调优调什么？常见参数有哪些？

---

## 盲答引导

1. 你遇到过哪些 JVM 性能问题？—— 频繁 Full GC？OOM？
2. 常用 JVM 参数有哪些？—— 至少说出 5 个
3. GC 日志怎么开？怎么分析？—— `-Xlog:gc*`（JDK 9+）/ `-XX:+PrintGCDetails`
4. 什么是「停顿时间」？什么是「吞吐量」？这两个目标常常是矛盾的吗？

---

## 知识链提示

```
JVM 调优
  → [[03_JVM/08_JVM调优与问题排查/JVM调优]]
    → 内存参数
      → -Xms / -Xmx：初始堆 / 最大堆（建议设成一样，避免动态扩容）
      → -Xmn：新生代大小（或 -XX:NewRatio）
      → -XX:SurvivorRatio：Eden : Survivor（默认 8:1:1）
      → -XX:MetaspaceSize / -XX:MaxMetaspaceSize：元空间大小
    → GC 参数
      → -XX:+UseG1GC / -XX:+UseZGC / -XX:+UseSerialGC
      → -XX:MaxGCPauseMillis：G1/ZGC 的目标停顿时间
    → GC 日志
      → JDK 8：-XX:+PrintGCDetails -XX:+PrintGCDateStamps -Xloggc:gc.log
      → JDK 9+：-Xlog:gc*:file=gc.log:time,uptime,level,tags
      → 分析工具：GCViewer / GCEasy（在线分析）
    → 调优目标
      → 低延迟（Low Latency）：GC 停顿短 → G1 / ZGC
      → 高吞吐（High Throughput）：GC 总时间少 → Parallel GC
      → 这两个目标互相矛盾 → 只能侧重一个
    → 常见问题
      → 频繁 Full GC：老年代太小 / 内存泄漏
      → 频繁 Minor GC：新生代太小 / 对象创建太快
```

---

## 核心追问

| 追问 | 考点 |
|------|------|
| `-Xmx` 设得越大越好吗？ | 不是，堆太大导致 Full GC 停顿时间变长 |
| G1 的 `-XX:MaxGCPauseMillis` 是硬保证吗？ | 不是，只是「目标」，JVM 尽力而为 |
| 元空间也会 OOM 吗？怎么调？ | 会，调大 `-XX:MaxMetaspaceSize` |
| 如何判断是不是「内存泄漏」导致的 Full GC？ | 老年代占用率持续上升，即使 Full GC 后也不释放 |

---

## 参考答案要点

**常用参数速查**：

| 参数 | 作用 |
|------|------|
| `-Xms` / `-Xmx` | 初始/最大堆（建议设成一样） |
| `-Xmn` | 新生代大小 |
| `-XX:+UseG1GC` | 使用 G1 收集器 |
| `-Xlog:gc*`（JDK 9+） | 打印 GC 日志 |
| `-XX:+HeapDumpOnOutOfMemoryError` | OOM 时自动 dump |

**调优思路**：先确定目标（低延迟 or 高吞吐）→ 选收集器 → 设置合理内存 → 分析 GC 日志 → 微调参数。

---

## 下一步

打开 [[03_JVM/08_JVM调优与问题排查/JVM调优]]，补充 `双向链接`：「JVM 调优的第一原则是『先确定目标』——低延迟（G1/ZGC）和高吞吐（Parallel）是矛盾的，必须取舍」。
