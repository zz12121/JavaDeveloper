# 闪卡库：03_JVM

> 使用说明：本闪卡库可导入 Obsidian Spaced Repetition 插件或 Anki。按主题分组，涵盖 JVM 核心知识点。

---

## 1. 类加载机制

**Q: 双亲委派模型是什么？为什么这样设计？**

**A:**
```
类加载请求向上传递：
  AppClassLoader → ExtClassLoader → BootstrapClassLoader

父加载器收到请求后，先尝试加载，找不到才让子类来。

目的：
1. 防止核心类被篡改（String.class 永远由 Bootstrap 加载）
2. 防止类被重复加载（父已加载，子不会再加载）
3. 保证 Java 类型体系的安全性
```

**Tags:** #JVM #类加载 #双亲委派

---

**Q: 类加载的三个阶段？**

**A:**
```
加载(Loading)      → 读取.class 文件，生成 Class 对象
链接(Linking)     → 验证 + 准备 + 解析
  验证：字节码安全检查
  准备：静态变量赋默认值（int = 0, 引用 = null）
  解析：符号引用 → 直接引用
初始化(Initialization) → 静态赋值（static {} 和 static 字段）
  这才是"真正赋值"，比准备阶段晚一步
```

**Tags:** #JVM #类加载 #生命周期

---

**Q: new Object() 的内存分配流程？**

**A:**
```
1. 检查类是否已加载（类加载机制）
2. 在堆中分配内存
   - 指针碰撞：内存规整时用（Serial、ParNew）
   - 空闲列表：内存碎片时用（CMA）
3. TLAB（Thread Local Allocation Buffer）
   - 每个线程预分配一小块 Eden 区
   - 减少并发竞争，无需加锁
4. 初始化为零值（对象头 + 零值字段）
5. 设置对象头（Mark Word）
6. 执行构造函数（<init>）
```

**Tags:** #JVM #对象分配 #内存

---

## 2. 运行时数据区

**Q: JVM 运行时数据区哪些是线程私有的，哪些是共享的？**

**A:**
```
线程私有（线程创建即存在，线程结束即销毁）：
  ├── 程序计数器（PC Register）   — 当前字节码行号
  ├── 虚拟机栈（VM Stack）        — 方法调用栈帧
  └── 本地方法栈（Native Stack）  — JNI 调用

线程共享（随 JVM 启动创建，GC 管理）：
  ├── 堆（Heap）                  — 对象实例
  └── 方法区（Method Area）       — 类信息、常量、静态变量（JDK 7 及之前）
      （JDK 8+ 元空间：Metaspace，用本地内存而非堆）
```

**Tags:** #JVM #运行时数据区 #内存模型

---

**Q: 堆内存分代结构？**

**A:**
```
堆
├── 新生代（Young/Eden）
│   ├── Eden 区        — 对象优先分配
│   └── Survivor ×2    — S0, S1（From, To）
│       （Minor GC 后，存活对象在两个 Survivor 之间复制）
│
└── 老年代（Old/Tenured）
    （对象年龄 ≥ 15 次 Minor GC 后，进入老年代）

Minor GC（新生代 GC）：
  - Eden 满 → 存活对象复制到 Survivor
  - Survivor 满 → 复制到另一个 Survivor（或直接进老年代）

Full GC（全堆 GC）：
  - 老年代空间不足
  - 方法区空间不足
  - System.gc()（仅建议）
```

**Tags:** #JVM #堆 #GC

---

**Q: 对象的内存布局？**

**A:**
```
对象头（Object Header）：
  ├── Mark Word（8 bytes，64位）
  │     存储：哈希码、GC 年龄、锁状态、偏向线程ID
  ├── Klass Pointer（4~8 bytes）
  │     指向方法区的 Class 对象
  └── 数组长度（仅数组对象，4 bytes）

实例数据（Instance Data）：
  - 父类的实例字段 + 子类的实例字段
  - 字段分配顺序：long/double → int/float → short/char → byte/boolean → 引用

对齐填充（Padding）：
  - 对象大小是 8 字节的倍数
  - HotSpot 用对齐填充保证这个规则
```

**Tags:** #JVM #对象布局 #MarkWord

---

## 3. 垃圾回收

**Q: GC Roots 包括哪些？**

**A:**
```
GC Roots（GC 根集合）：
1. 虚拟机栈（栈帧中的局部变量表）引用的对象
2. 方法区中类静态属性引用的对象
3. 方法区中常量引用的对象（final 修饰的字段）
4. 本地方法栈中 JNI（Native 方法）引用的对象
5. JVM 内部引用（Class 对象、异常对象）
6. 同步锁持有的对象（synchronized 锁住的对象）
7. JVM 管理代码持有的对象

⚠️ 局部变量表中的引用是"活"的，GC 时不会被回收
⚠️ 静态变量持有引用 → 类加载器不卸载，静态字段永不回收
```

**Tags:** #JVM #GC #GCRoots

---

**Q: 三大 GC 算法对比？**

**A:**
```
标记-清除（Mark-Sweep）：
  优点：实现简单
  缺点：效率低（两次遍历）；产生内存碎片

复制（Copying）：
  优点：无碎片；只处理存活对象，效率高
  缺点：内存利用率只有 50%
  → 新生代用它（因为 90%+ 对象朝生夕死，复制量很小）

标记-整理（Mark-Compact）：
  优点：内存利用率 100%；无碎片
  缺点：需要移动对象，效率较低
  → 老年代用它（存活率高，复制成本太高）
```

**Tags:** #JVM #GC算法

---

**Q: 引用计数的循环引用问题？**

**A:**
```java
Node a = new Node();
Node b = new Node();
a.next = b;  // a 的计数 +1
b.next = a;  // b 的计数 +1

a = null;
b = null;
// 此时 a.refCount = 1, b.refCount = 1
// 但已经没有任何 GC Root 能到达它们
// 引用计数无法回收 → 内存泄漏

JVM 的可达性分析可以正确回收：
  → GC Roots 无法到达 → 判定为垃圾
```

**Tags:** #JVM #引用计数 #可达性分析

---

**Q: Minor GC 和 Full GC 的区别？**

**A:**
```
Minor GC（年轻代 GC）：
  - 触发条件：Eden 区满
  - STW 时间：短（通常几十毫秒）
  - 存活对象 → Survivor 区 → 多次 Minor GC 后进老年代

Full GC（整堆 GC）：
  - 触发条件：
      老年代空间不足
      方法区空间不足
      System.gc()（JVM 建议，不一定触发）
  - STW 时间：长（取决于收集器和堆大小）
  - 包含：新生代 + 老年代 + 方法区
```

**Tags:** #JVM #GC #MinorGC #FullGC

---

## 4. 垃圾收集器

**Q: Serial / ParNew / Parallel Scavenge 的区别？**

**A:**
```
Serial（Serial GC）：
  - 单线程收集，必须 STW
  - 优点：简单，线程切换开销最小
  - 适合：客户端 / 堆 < 100MB

ParNew（并行 GC）：
  - Serial 的多线程版本
  - JDK 7/8 中与 CMS 配合的新生代收集器
  - JDK 9+ 被 G1 取代

Parallel Scavenge（JDK 8 默认新生代）：
  - 目标：吞吐量最大化（吞吐量 = 用户代码时间 / 总时间）
  - 参数：-XX:GCTimeRatio=19 → GC 时间占 5%
  - 适合：后台计算、批处理（不关心停顿）
```

**Tags:** #JVM #GC收集器 #并行

---

**Q: CMS 的四阶段？它的两大坑？**

**A:**
```
CMS（Concurrent Mark Sweep）：
  目标：低停顿，适合 Web 服务

阶段：
  1. 初始标记（STW）      — 标记 GC Roots 直接关联的对象（快）
  2. 并发标记             — 用户线程运行，沿着引用链标记
  3. 重新标记（STW）      — 修正并发期间产生的引用变化（较快）
  4. 并发清除             — 用户线程运行，清除未标记对象

为什么需要"重新标记"？
  → 并发标记时用户线程在跑，引用可能变化（如 A→B 断开）
  → 不修正会漏标（把存活对象当垃圾回收）

两大坑：
  1. 内存碎片：标记-清除不整理 → Full GC 用 Serial Old（很长）
  2. Concurrent Mode Failure：并发清除时对象创建太快 → 触发 Full GC

预防：-XX:CMSInitiatingOccupancyFraction=75（默认 92% 太晚）
```

**Tags:** #JVM #CMS #GC收集器

---

**Q: G1 的设计思想？它和 CMS 的核心区别？**

**A:**
```
CMS：追踪整个老年代 → 停顿时间不可控
G1：把堆分成多个大小相等的 Region（1~32MB）
    → 每次只回收价值最高的 Region（垃圾多、存活少）
    → 停顿时间可预测（-XX:MaxGCPauseMillis）

G1 的特点：
  - 既有新生代 Eden/Survivor，也有老年代 Region
  - 新增 Humongous 区域（大对象，超过 50% Region 大小）
  - Remembered Set（RS）记录 Region 间的引用关系
  - SATB（Snapshot-At-The-Beginning）解决并发标记时的漏标问题

G1 vs CMS：
  | 维度 | CMS | G1 |
  |------|-----|-----|
  | 内存管理 | 整块连续 | 分 Region |
  | 碎片 | 标记-清除，有碎片 | 整体标记-整理 |
  | 停顿 | 不确定 | 可配置停顿目标 |
  | 大对象 | 容易触发 Full GC | Humongous 区域处理 |
  | JDK 版本 | JDK 14 后移除 | JDK 9+ 默认 |
```

**Tags:** #JVM #G1 #GC收集器

---

**Q: ZGC 的染色指针是什么？**

**A:**
```
ZGC（Z Garbage Collector）：
  目标：停顿时间 < 1ms，支持 TB 级堆

染色指针（Colored Pointers）：
  64位指针中，用几位做"标记位"：
  - Marked0 / Marked1：对象已标记
  - Remapped：对象位置已更新（用于并发移动）
  - Finalizable：对象只能通过终结器访问

优势：
  1. 标记信息存在指针里，不占对象头 → 对象更小
  2. 并发重定位时，指针自愈 → 不需要 STW 更新引用
  3. 读屏障（Load Barrier）确保访问正确版本的指针

对比 ZGC vs G1：
  G1：停顿时间可预测，但 > 10ms
  ZGC：停顿 < 1ms，但吞吐量略低
  ZGC 适合：大堆（> 8GB）+ 低延迟要求的场景
```

**Tags:** **#JVM #ZGC #GC收集器 #染色指针**

---

## 5. 字节码

**Q: new Object() 的字节码执行流程？**

**A:**
```java
new Object()      →  new（分配内存 + 调用构造器）
  └── bytecode: new #1   // 创建对象，压入栈
dup                 // 复制栈顶引用（构造器需要 this 引用）
invokespecial #1    // 调用构造器 <init>
astore_1            // 存到局部变量表
```

**常见指令**：
```
new              — 创建对象
dup              — 复制栈顶
invokespecial    — 构造器/private 方法
invokevirtual    — 普通实例方法（运行时多态）
invokestatic     — static 方法
invokeinterface  — 接口方法
invokedynamic    — Lambda / 动态语言
getfield / putfield      — 实例字段
getstatic / putstatic    — 静态字段
```

**Tags:** #JVM #字节码 #字节码指令

---

**Q: synchronized 的字节码是怎么实现的？**

**A:**
```java
synchronized (lock) {
    doSomething();
}
```

```
字节码：
  monitorenter   // 进入同步块（获取锁，失败则阻塞）
  aload_1        // 加载 lock 对象
  invokevirtual  // doSomething()
  monitorenter   // 退出同步块（释放锁，唤醒等待线程）

同步方法（方法上加 synchronized）：
  方法的 ACC_SYNCHRONIZED 标志位 → 隐式 monitorenter/exit
```

**Tags:** #JVM #synchronized #字节码

---

## 6. JVM 调优

**Q: OOM 的常见类型和排查思路？**

**A:**
```
OOM 类型：
  1. Java heap space     — 堆溢出（最常见）
  2. GC overhead limit exceeded — GC 回收不了，频繁 Full GC
  3. PermGen space（<= JDK 7） — 方法区溢出
  4. Metaspace（>= JDK 8）   — 元空间溢出（类加载过多）
  5. Unable to create new native thread — 线程数过多（栈内存耗尽）
  6. Direct buffer memory  — NIO DirectByteBuffer 堆外内存

排查工具：
  jmap -heap <pid>        — 堆内存概况
  jmap -histo <pid>      — 对象直方图（哪些对象最多）
  jmap -dump:format=b,file=heap.hprof <pid>  — 导出堆转储
  MAT / JProfiler        — 分析堆转储文件
  Arthas                  — 在线诊断（dashboard / heapdump / ognl）
```

**Tags:** #JVM #OOM #调优 #排查

---

**Q: 常用 JVM 参数？**

**A:**
```bash
# 堆大小
-Xms512m -Xmx512m       # 初始/最大堆（建议设成一样，避免动态扩展）

# 新生代
-Xmn256m                # 新生代大小
-XX:SurvivorRatio=8    # Eden:S0:S1 = 8:1:1

# GC 日志
-XX:+PrintGCDetails    # 详细 GC 日志
-XX:+PrintGCDateStamps # 时间戳
-Xloggc:gc.log         # 输出到文件

# G1
-XX:MaxGCPauseMillis=200    # 最大停顿目标
-XX:G1HeapRegionSize=16m     # Region 大小

# 元空间（JDK 8+）
-XX:MetaspaceSize=256m      # 元空间初始大小
-XX:MaxMetaspaceSize=512m   # 元空间最大（默认无上限！）
```

**Tags:** #JVM #JVM参数 #调优

---

**Q: 对象何时进入老年代？**

**A:**
```
进入老年代的时机：

1. 年龄阈值：
   - 对象每经历一次 Minor GC，age + 1
   - age >= MaxTenuringThreshold（默认 15）→ 进入老年代
   - JVM 可以动态调整阈值（`-XX:+UseAdaptiveSizePolicy`）

2. 提前晋级：
   - Survivor 区相同年龄所有对象大小总和 > Survivor 区的 50%
   → 年龄 >= 该年龄的对象直接进入老年代

3. 大对象直接进入：
   - 超过 PretenureSizeThreshold（默认 0）的对象
   → 直接在老年代分配（避免大对象在 Survivor 区来回复制）

4. 空间分配担保：
   - Minor GC 时，老年代最大可用连续空间 < 新生代所有对象总大小
   → 触发 Full GC（提前晋级担保失败）
```

**Tags:** #JVM #对象晋级 #老年代

---

*生成时间：2026-05-05*
