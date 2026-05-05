# JVM - 知识点考法对照

> 本文档是「出题者视角」的知识梳理——每个知识点列出常见考法 + 回答要点。
> 配合对应知识文档一起使用，先学后考。

---

## 运行时数据区

**关联知识文档**：[[03_JVM/04_运行时数据区/运行时数据区]]

**第一问**：「JVM 内存分哪几块？」

| 追问层次 | 追问 | 考点 |
|---------|------|------|
| 第一层 | 哪些是线程私有的？哪些是线程共享的？ | 栈/PC/本地方法栈（私有）；堆/方法区（共享）|
| 第二层 | 方法区在 JDK 8 变成了什么？为什么？ | Metaspace（使用本地内存，避免 PermGen OOM）|
| 第三层 | 直接内存是什么？受什么控制？ | NIO `ByteBuffer.allocateDirect()` / `-XX:MaxDirectMemorySize` |

**面试话术总结**：

- **五大部分**：
  - **堆**（Heap）：线程共享，存放对象实例和数组（GC 主要区域）
  - **方法区**（Method Area）：线程共享，存放类信息、常量、静态变量；JDK 7 是 PermGen，JDK 8+ 是 Metaspace（使用本地内存）
  - **虚拟机栈**（VM Stack）：线程私有，每个方法调用创建栈帧（局部变量表、操作数栈、动态链接、返回地址）
  - **本地方法栈**（Native Method Stack）：线程私有，为 Native 方法服务
  - **程序计数器**（PC Register）：线程私有，记录当前执行的字节码行号（唯一不会 OOM 的区域）
- **Metaspace vs PermGen**：PermGen 用 JVM 堆内存，容易 OOM；Metaspace 用本地内存，默认上限是物理内存，可通过 `-XX:MaxMetaspaceSize` 限制

---

## 类加载机制

**关联知识文档**：[[03_JVM/03_类加载机制/类加载机制]]

**第一问**：「什么是双亲委派模型？」

| 追问层次 | 追问 | 考点 |
|---------|------|------|
| 第一层 | 为什么需要双亲委派？不委派会怎样？ | 核心类（如 String）被自定义类覆盖 |
| 第二层 | 什么场景需要破坏双亲委派？ | SPI（JDBC）/ Tomcat / OSGi |
| 第三层 | 自定义 ClassLoader 要重写哪个方法？ | `findClass()`（不要重写 `loadClass()`）|

**面试话术总结**：

- **双亲委派**：类加载器收到请求 → 委派给父加载器 → 父加载器再委派给祖父 → 直到 BootstrapClassLoader → 父加载器加载不到时子加载器才尝试加载
- **三层类加载器**：
  - BootstrapClassLoader（`rt.jar`、`tools.jar`，C++ 实现）
  - ExtensionClassLoader（`ext/*.jar`，JDK 9+ 改为 PlatformClassLoader）
  - ApplicationClassLoader（classpath 下的类）
- **破坏双亲委派的场景**：
  - **SPI**：`DriverManager` 在 `rt.jar` 里，但驱动实现在各厂商 jar 里 → 用 `Thread Context ClassLoader` 打破
  - **Tomcat**：不同 Web App 可能依赖同一类的不同版本 → 每个 Web App 有自己的 WebAppClassLoader
  - **OSGi**：模块化，每个 Bundle 有独立的类加载器，形成网状而非树状

---

## 垃圾回收算法

**关联知识文档**：[[03_JVM/06_垃圾回收算法/垃圾回收]]

**第一问**：「JVM 有哪些垃圾回收算法？」

| 追问层次 | 追问 | 考点 |
|---------|------|------|
| 第一层 | 标记-清除、标记-整理、复制算法各有什么优缺点？ | 空间碎片 / 移动开销 / 空间利用率 |
| 第二层 | 新生代为什么用复制算法而不是标记整理？ | 朝生夕灭，存活率低 |
| 第三层 | 什么是 Stop The World？SafePoint 是什么？ | 所有用户线程暂停 / 安全点位置 |

**面试话术总结**：

- **三大基础算法**：
  - **标记-清除**：效率高但产生碎片（CMS 老年代）
  - **标记-整理**：无碎片但移动对象有开销（Serial Old、Parallel Old）
  - **复制算法**：无碎片但浪费一半空间（新生代 Eden:Survivor = 8:1:1，只用 10% 浪费空间）
- **分代收集原因**：大部分对象朝生夕灭（98%），少部分长期存活 → 新生代用复制算法效率高
- **SafePoint**：GC 暂停线程必须在「安全点」（方法调用、循环跳转、异常跳转等位置），不能在任意指令处暂停；`-XX:+UseCountedLoopSafepoints` 控制长循环中的安全点

---

## 垃圾收集器

**关联知识文档**：[[03_JVM/07_垃圾收集器/垃圾收集器]]

**第一问**：「G1 和 CMS 收集器有什么区别？」

| 追问层次 | 追问 | 考点 |
|---------|------|------|
| 第一层 | G1 为什么能控制停顿时间？ | Region + 可预测停顿模型 |
| 第二层 | G1 的 Region 是什么？Eden / Survivor / Old 还存在吗？ | 逻辑分代，物理上统一 Region |
| 第三层 | ZGC 和 G1 的核心区别？ | ZGC 着色指针 + 读屏障，停顿 < 1ms |

**面试话术总结**：

> 回答思路：按「适用年代」分类列举，重点对比 CMS vs G1 vs ZGC。

- **收集器分类**：
  | 收集器 | 新生代 | 老年代 | 算法 | 特点 |
  |--------|--------|--------|------|------|
  | Serial + Serial Old | Serial | Serial Old | 复制 + 标记整理 | 单线程，适合客户端 |
  | Parallel Scavenge + Parallel Old | Parallel | Parallel Old | 复制 + 标记整理 | 多线程，吞吐量优先 |
  | CMS | ParNew | CMS | 复制 + 标记清除 | 低延迟，碎片问题 |
  | G1 | G1 | G1 | Region + 复制/整理 | 可控停顿，JDK 9+ 默认 |
  | ZGC | ZGC | ZGC | 着色指针 + 读屏障 | 超低延迟（<1ms）|
- **CMS 四个阶段**：初始标记（STW 短）→ 并发标记 → 重新标记（STW 短）→ 并发清除；缺点：浮动垃圾 + 内存碎片
- **G1 核心**：堆划分为等大小 Region（1~32MB，共 2048 个），逻辑上分代，物理上混合；`-XX:MaxGCPauseMillis` 设定目标停顿时间，G1 根据历史数据选择回收收益最大的 Region（Garbage First 名称由来）
- **ZGC 核心**（JDK 11+）：染色指针（Colored Pointers）标记对象状态，读屏障（Load Barrier）实现并发整理；停顿时间 < 1ms（JDK 16 支持分代 ZGC）

---

## JIT 编译

**关联知识文档**：[[03_JVM/09_JIT编译与性能优化/JIT编译与性能优化]]

**第一问**：「JVM 的 JIT 编译器是什么？」

| 追问层次 | 追问 | 考点 |
|---------|------|------|
| 第一层 | 什么是热点代码？怎么判断的？ | 方法调用计数器 / 回边计数器 + 阈值 |
| 第二层 | C1 和 C2 编译器有什么区别？ | 编译速度 vs 优化深度 |
| 第三层 | 什么是逃逸分析？有什么优化？ | 标量替换 / 锁消除 / 栈上分配 |

**面试话术总结**：

- **JIT 编译流程**：字节码 → 解释执行（慢）→ 达到热点阈值 → JIT 编译为本地机器码 → 后续直接执行机器码（快）
- **热点判断**：
  - 方法调用计数器：调用次数超过阈值（`-XX:CompileThreshold`，Client 模式 1500，Server 模式 10000）
  - 回边计数器：循环体执行次数超过阈值（OnStackReplacement，OSR）
  - 热度衰减：一段时间没被调用，计数器减半
- **C1 vs C2**：
  - C1（Client Compiler）：编译快，优化少，适合启动速度
  - C2（Server Compiler）：编译慢，深度优化（内联、逃逸分析、循环展开），适合长期运行的服务端
  - 分层编译（Tiered Compilation，JDK 7+ 默认）：C1 先编译 → 热度持续上升 → C2 再编译
- **逃逸分析**（重点）：分析对象是否「逃逸」出方法/线程
  - **标量替换**：对象没逃出方法 → 拆成基本类型变量，不创建对象（省堆内存分配）
  - **锁消除**：对象没逃出方法 → synchronized 无竞争 → 编译器消除锁
  - **栈上分配**：对象没逃出线程 → 分配在栈上（随栈帧释放，无需 GC）— 注意：HotSpot 实际只做了标量替换，没做真正的栈上分配

---

## 内存模型与 OOM

**关联知识文档**：[[03_JVM/08_JVM调优与问题排查/内存溢出与泄漏]]

**第一问**：「你遇到过 OOM 吗？怎么排查的？」

| 追问层次 | 追问 | 考点 |
|---------|------|------|
| 第一层 | JVM 有哪些 OOM 类型？ | Java heap space / Metaspace / GC overhead limit / Direct buffer memory |
| 第二层 | 排查 OOM 的步骤是什么？ | Heap Dump + MAT / jmap / OOM 时自动 dump |
| 第三层 | 内存泄漏和内存溢出的区别？ | 泄漏是对象无法回收，溢出是堆不够用 |

**实战型考法**：「线上系统突然 OOM 了，你第一时间做什么？」

**面试话术总结**：

- **OOM 类型**：
  - `Java heap space`：堆内存不足（大对象 / 内存泄漏）
  - `Metaspace`：类太多或动态代理生成类过多
  - `GC overhead limit exceeded`：GC 占用 98% 以上的时间但只回收不到 2%
  - `Direct buffer memory`：NIO 直接内存泄漏
  - `unable to create new native thread`：创建线程数超过操作系统限制
- **排查步骤**：
  1. `-XX:+HeapDumpOnOutOfMemoryError -XX:HeapDumpPath=/tmp/dump.hprof`（线上必须配）
  2. 下载 dump 文件，用 MAT（Memory Analyzer Tool）或 VisualVM 分析
  3. 看 Dominator Tree / Leak Suspects，找到占用最大的对象
  4. 分析 GC Roots 引用链，找到为什么无法回收
- **预防措施**：合理设置堆大小（`-Xms` = `-Xmx`）；监控堆使用率；定期压测

---

## 类文件结构与字节码

**关联知识文档**：[[03_JVM/02_字节码与类文件/字节码]]

**第一问**：「一个 .class 文件里有什么？」

| 追问层次 | 追问 | 考点 |
|---------|------|------|
| 第一层 | 类文件的基本结构是什么？ | 魔数 + 版本号 + 常量池 + 访问标志 + 类索引 + 字段表 + 方法表 + 属性表 |
| 第二层 | 常量池存了什么？为什么要有常量池？ | 字面量 + 符号引用，节省空间 |
| 第三层 | 怎么用 `javap` 看字节码？ | `javap -c -p -v` 各参数含义 |

**面试话术总结**：

- **类文件结构**（必须能说出主要部分）：`魔数(0xCAFEBABE)` → 版本号 → 常量池 → 访问标志(`ACC_PUBLIC`等) → 类索引/父类索引 → 接口表 → 字段表 → 方法表 → 属性表
- **常量池**：字面量（字符串、数字）+ 符号引用（类/方法/字段的全限定名和描述符）；JVM 运行时将符号引用解析为直接引用（内存地址）
- **`javap` 常用参数**：`-c` 反汇编方法体；`-p` 显示所有类/方法（含 private）；`-v` 显示详细信息（含常量池和栈帧）
- **常考字节码指令**：`aload_0`（加载 this）、`invokespecial`（构造器/私有方法）、`invokevirtual`（虚方法调用）、`invokeinterface`（接口方法）、`invokestatic`（静态方法）

---

## JVM 监控与调优

**关联知识文档**：[[03_JVM/08_JVM调优与问题排查/JVM调优]]

**第一问**：「你做过 JVM 调优吗？怎么做的？」

| 追问层次 | 追问 | 考点 |
|---------|------|------|
| 第一层 | 常用的 JVM 调优参数有哪些？ | 堆大小 / GC 选择 / GC 日志 |
| 第二层 | 怎么监控 JVM 运行状态？ | jstat / jmap / jstack / Arthas |
| 第三层 | Full GC 频繁怎么排查？ | 老年代空间不足 / Metaspace 不足 / 内存泄漏 |

**实战型考法**：「你的项目 GC 参数是怎么配的？为什么这么配？」

**面试话术总结**：

- **常用 JVM 参数**：
  - 堆：`-Xms4g -Xmx4g`（初始=最大，避免扩容抖动）
  - GC 选择：JDK 8+ 推荐 G1（`-XX:+UseG1GC`）；JDK 9+ G1 是默认
  - GC 日志：`-Xlog:gc*:file=gc.log`（JDK 9+）/ `-XX:+PrintGCDetails`（JDK 8）
  - OOM dump：`-XX:+HeapDumpOnOutOfMemoryError`
- **监控工具**：
  - `jstat -gcutil <pid> 1000`：每秒打印 GC 统计
  - `jmap -histo <pid>`：按占用排序的对象统计
  - `jstack <pid>`：线程堆栈（排查死锁/阻塞）
  - Arthas：`dashboard`（总览）、`thread`（线程）、`heapdump`（导出堆）
- **Full GC 排查思路**：
  1. 先看 GC 日志，确认 Full GC 频率和触发原因
  2. `jmap -histo` 看哪些对象占用多
  3. 导出 Heap Dump 分析引用链
  4. 常见原因：大对象直接进老年代、内存泄漏、Metaspace 不足

---

## P8 架构型考法汇总

> P8 级别开放设计题，考察技术整合与架构决策能力。

1. **如何为 100 万 QPS 的系统选择合适的 GC 策略并调优？**
   - 考点：停顿时间要求、吞吐量要求、G1 vs ZGC 选型、GC 日志分析
2. **如何设计一个线上 JVM 监控和自动诊断系统？**
   - 考点：JMX / jstat / Arthas、阈值告警、自动化 Heap Dump、根因分析
3. **如何设计一个支持热部署的 Java 应用架构？**
   - 考点：OSGi / 自定义 ClassLoader、模块隔离、状态迁移
4. **如何优化一个 Full GC 每秒一次的大型系统？**
   - 考点：对象生命周期分析、分代调优、Heap 分区、Off-Heap 设计
