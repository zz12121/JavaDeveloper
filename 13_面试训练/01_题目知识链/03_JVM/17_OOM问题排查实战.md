# 题目：OOM（Out Of Memory）有哪些类型？怎么排查和解决？

---

## ⚠️ 先盲答

**不要看任何资料，用自己的话回答，写到纸上或心里默念也行。**

---

## 盲答引导

1. `java.lang.OutOfMemoryError` 有哪些子类（不同场景）？各是什么引起的？
2. 堆 OOM（`Java heap space`）最常见的原因是什么？
3. 元空间 OOM（`Metaspace`）是什么导致的？动态生成类过多？
4. Direct buffer memory OOM 和堆外内存有什么关系？
5. OOM 时自动 dump 堆的参数怎么设？

---

## 知识链提示

这道题应该让你联想到：

- `[[MAT工具]]` → Eclipse MAT，分析 heap dump 的神器
- `[[内存泄漏 vs 内存溢出]]` → 泄漏会导致溢出，但溢出不一定是泄漏
- `[[GC Roots]]` → MAT 里找泄漏对象的 GC Roots 路径
- `[[常见 OOM 场景]]` → 静态集合、未关闭资源、过度使用反射
- `[[JVM参数调优]]` → -Xmx 设大 ≠ 解决根本问题

---

## 核心追问

1. 下面代码运行很久后会 OOM 吗？为什么？
   ```java
   static List<Object> list = new ArrayList<>();
   void addObject() { list.add(new Object()); }
   ```
2. `-XX:+HeapDumpOnOutOfMemoryError` 生成的 dump 文件，用什么打开？
3. 元空间 OOM 常见于什么框架场景中？（提示：Spring/CGLIB 动态代理）
4. `unable to create new native thread` 是什么 OOM？怎么解决？
5. MAT 里的「Shallow Heap」和「Retained Heap」分别是什么意思？

---

## 参考要点（盲答后再看）

<details>
<summary>点击展开</summary>

**OOM 五大类型（必须背熟）**：

| 类型 | 错误信息 | 原因 | 解决方案 |
|------|---------|------|---------|
| 堆 OOM | `Java heap space` | 堆内存不足，对象太多 | -Xmx 调大；MAT 分析泄漏 |
| 元空间 OOM | `Metaspace` | 类加载过多（动态代理/CGLIB） | -XX:MaxMetaspaceSize 调大 |
| 直接内存 OOM | `Direct buffer memory` | 堆外内存用满 | -XX:MaxDirectMemorySize 调大 |
| 线程 OOM | `unable to create new native thread` | 线程数达到 OS 上限 | 降低线程数；调小 -Xss |
| GC  overhead | `GC overhead limit exceeded` | 98% 时间在 GC，回收 <2% 空间 | 同堆 OOM |

**排查流程（重点）**：
```
1. 设参数：-XX:+HeapDumpOnOutOfMemoryError -XX:HeapDumpPath=/path
2. OOM 后拿到 heap dump（.hprof 文件）
3. 用 MAT 打开 → 找「Dominator Tree」
4. 看哪个对象 Retained Heap 最大
5. 看 GC Roots 路径：谁在引用它（通常是静态变量）
```

**MAT 核心功能**：
- Histogram：按类名统计对象数和占用空间
- Dominator Tree：占用内存最大的对象链
- Leak Suspects：自动分析泄漏嫌疑

**常见内存泄漏场景**：
```java
// 1. 静态集合忘记清理
static Map<Long, Object> cache = new ConcurrentHashMap<>();
// 不停 put，从不 remove → 泄漏

// 2. 未关闭资源
FileInputStream fis = new FileInputStream("file");
// 忘记 fis.close() → 文件句柄泄漏

// 3. 监听器/回调未注销
component.addListener(this);
// 组件生命周期比对象长 → 对象无法回收
```

</details>

---

## 下一步

1. 盲答后，对比参考要点，找到卡壳的地方
2. 打开 `[[OOM排查]]` 主题文档，把 5 种 OOM 类型整理成表格
3. 在 Obsidian 里建双向链接：`[[09_工程化/线上排查]]` ←→ 本卡片
4. 在 `[[12_面试训练/每日一题跟踪表]]` 里勾选「今日完成」，打 1~5 分
