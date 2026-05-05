# 题目：Object 类的核心方法有哪些？各自的设计目的是什么？

---

## ⚠️ 先盲答

**不要看任何资料，用自己的话回答，写到纸上或心里默念也行。**

不仅能列出来，还要说清楚：为什么 ` wait()`/`notify()` 必须在 `synchronized` 里面调用？

---

## 盲答引导

1. `equals()` 和 `hashCode()` 的契约是什么？破坏了会怎样？
2. 为什么 ` wait()`/`notify()` 要放在 `synchronized` 块里？Java 能不能设计成不用？
3. `clone()` 为什么是 `protected` 的？浅拷贝和深拷贝怎么实现？
4. `finalize()` 为什么被废弃了？替代方案是什么？
5. `getClass()` 为什么是 `final` 的，不允许子类重写？

---

## 知识链提示

这道题应该让你联想到：

- `equals与hashCode契约` → HashMap 为什么依赖这个契约？
- `浅拷贝vs深拷贝` → clone() 的默认行为 + 序列化实现深拷贝
- `finalize废弃` → `Cleaner` / `PhantomReference` 替代方案
- `[[wait/notify机制]]` → 为什么必须在 synchronized 里（竞态条件）
- `native方法` → Object 里哪些方法是 native 的？

---

## 核心追问

1. 只重写了 `equals()` 没重写 `hashCode()`，把这个对象放进 `HashMap` 会怎样？
2. ` wait()` 为什么要放在 `while` 循环里而不是 `if` 里？（醒早了问题）
3. `System.identityHashCode()` 和 `hashCode()` 的区别是什么？
4. `clone()` 是深拷贝还是浅拷贝？怎么实现深拷贝？
5. 如果 `finalize()` 里重新把对象赋值给一个 GC Root 可达的引用，对象会复活吗？

---

## 参考要点（盲答后再看）


**Object 核心方法**：

| 方法 | 作用 | 注意点 |
|------|------|--------|
| `equals()` | 判断逻辑相等 | 必须和 `hashCode()` 一起重写 |
| `hashCode()` | 哈希码 | 相等对象必须有相等 hashCode |
| `toString()` | 字符串表示 | 默认 `类名@hashCode十六进制` |
| `clone()` | 对象拷贝 | 浅拷贝，需实现 `Cloneable` |
| `getClass()` | 获取运行时类 | `final`，不可重写 |
| `wait()`/`notify()`/`notifyAll()` | 线程通信 | 必须在 `synchronized` 块内 |
| `finalize()` | GC 前回调 | **已废弃（JDK 9+）**，不要用 |

**equals/hashCode 契约**：
```
1. equals 返回 true → hashCode 必须相等
2. hashCode 相等 → equals 不一定返回 true（哈希冲突）
3. 只重写 equals 不重写 hashCode → HashMap 找不到对象（放到不同桶）
```

**wait/notify 为什么必须 synchronized**：
```
// 竞态条件：
if (condition) {   // 线程A判断条件
    // 线程B此时修改了condition，并notify
    // 但A还没进入wait，notify信号丢失！
}
wait();

// 正确做法：
synchronized(lock) {
    while (condition) {  // 用while，防止虚假唤醒
        lock.wait();
    }
}
```

**finalize 废弃原因**：
- 执行时机不确定（GC 时间不确定）
- 可能拖慢 GC
- 可能对象「复活」，破坏 GC 算法假设
- **替代方案**：`Cleaner`（JDK 9+）或 `PhantomReference`


---

## 下一步

1. 盲答后，对比参考要点，找到卡壳的地方
2. 打开 `[[01_Java核心/Object核心方法]]` 主题文档，把没懂的地方填进去
3. 在 Obsidian 里建双向链接
4. 在 `[[13_面试训练/03_每日一题/每日一题跟踪表]]` 里勾选「今日完成」，打 1~5 分
