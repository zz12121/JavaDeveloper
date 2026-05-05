# 题目：JVM 监控和排查工具有哪些？`jstat`/`jmap`/`jstack` 各怎么用？

---

## ⚠️ 先盲答

**不要看任何资料，用自己的话回答，写到纸上或心里默念也行。**

---

## 盲答引导

1. `jps` 是干什么的？和 `ps -ef | grep java` 有什么区别？
2. `jstat -gc <pid>` 的输出你能看懂吗？S0C/S1C/EDEN/OLD 各是什么？
3. `jmap -histo` 和 `jmap -dump` 各是干什么的？线上用哪个更安全？
4. `jstack` 能看到什么信息？`Blocked` 和 `Waiting` 状态分别表示什么？
5. VisualVM 和 JConsole 有什么本质区别？

---

## 知识链提示

这道题应该让你联想到：

- `[[jstat GC监控]]` → 最常用的 GC 实时统计工具
- `[[jmap内存快照]]` → heap dump，配合 MAT 分析
- `[[jstack线程栈]]` → 排查死锁、线程卡顿
- `[[VisualVM/JConsole]]` → 可视化监控，适合开发环境
- `[[线上排查禁忌]]` → dump 大堆会 STW，需谨慎

---

## 核心追问

1. `jstat -gcutil <pid> 1000` 是什么意思？每列的 `S0/S1/E/O/M` 是什么意思？
2. `jmap -histo:live <pid>` 的 `:live` 会触发 Full GC 吗？有什么风险？
3. `jstack` 转出的线程栈里，`nid`（native ID）是什么？怎么对应到 OS 线程？
4. `jcmd` 是 JDK7+ 的新工具，它能替代哪些旧工具？
5. 生产环境对运行中的 JVM 做 heap dump，有哪些注意事项？

---

## 参考要点（盲答后再看）

<details>
<summary>点击展开</summary>

**常用工具速查表**：

| 工具 | 用途 | 常用命令 |
|------|------|------------|
| `jps` | 列出 Java 进程 | `jps -v` |
| `jstat` | 实时 GC 统计 | `jstat -gc <pid> 1000` |
| `jmap` | 内存快照 | `jmap -histo:live <pid>` |
| `jstack` | 线程栈快照 | `jstack <pid> > stack.txt` |
| `jcmd` | 一站式工具（JDK7+） | `jcmd <pid> VM.info` |
| `VisualVM` | 可视化监控 | 图形界面，适合开发 |

**jstat -gc 输出解读（重点）**：
```
 S0C    S1C    S0U    S1U    EC       EU       OC        OU      MC     MU
 0.0    0.0    0.0    0.0    5248.0  2624.0   131072.0  65536.0  4480.0 4032.0
```
- `C` = Capacity（容量），`U` = Used（已用）
- S0/S1 = Survivor 0/1，EC = Eden Capacity，OC = Old Capacity
- MC/MU = Metaspace Capacity/Used

**jmap 注意事项（高频考点）**：
```bash
# ⚠️ -histo:live 会触发 Full GC（只统计存活对象）
jmap -histo:live <pid>

# heap dump（会 STW，线上谨慎！）
jmap -dump:live,format=b,file=heap.hprof <pid>
```

**jstack 排查死锁**：
```bash
jstack <pid> | grep -A 10 "deadlock"
# 或搜索 "Blocked" 状态的线程
```

**jcmd 替代关系**：
| 旧工具 | jcmd 子命令 |
|--------|-------------|
| `jmap -histo` | `jcmd <pid> GC.class_histogram` |
| `jstack` | `jcmd <pid> Thread.print` |
| `jstat` | `jcmd <pid> VM.gc_info` |

</details>

---

## 下一步

1. 盲答后，对比参考要点，找到卡壳的地方
2. 打开 `[[JVM监控工具]]` 主题文档，把 jstat/jmap/jstack 常用命令做成速查表
3. 在 Obsidian 里建双向链接：`[[09_工程化/线上排查]]` ←→ 本卡片
4. 在 `[[12_面试训练/每日一题跟踪表]]` 里勾选「今日完成」，打 1~5 分
