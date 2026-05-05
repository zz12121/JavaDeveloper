# 题目：try-catch-finally 中，如果 try 和 finally 都有 return，返回哪个值？从字节码层面解释为什么。

---

## ⚠️ 先盲答

**不要看任何资料，用自己的话回答，写到纸上或心里默念也行。**

---

## 盲答引导

1. `try { return 1; } finally { return 2; }` —— 最终返回什么？
2. `try { return x; } finally { x++; }` —— 最终返回的是 x 的旧值还是新值？
3. finally 块为什么「一定」会执行？JVM 是怎么保证的？
4. 如果 finally 块抛了异常，try 里的 return 还会执行吗？
5. 从字节码角度看，finally 里的代码被「复制」了几份？为什么？

---

## 知识链提示

这道题应该让你联想到：

- `[[字节码异常表]]` → Exception Table，finally 的字节码会被复制
- `[[return字节码指令]]` → ireturn/areturn 等，操作数栈的变化
- `[[JVM规范异常处理]]` → jsr/ret（旧版）vs 复制语义（新版）
- `[[资源泄漏]]` → 为什么 try-finally 不推荐，应该用 try-with-resources
- `[[面试题陷阱]]` → 经典笔试题：`public int test() { try{ return 1; } finally { return 2; } }`

---

## 核心追问

1. 下面代码输出什么？为什么？
   ```java
   int x = 0;
   try { x = 1; return x; }
   finally { x = 2; }
   // 返回 1 还是 2？
   ```
2. 如果 try 里抛异常，catch 里 return，finally 还会执行吗？
3. 从字节码看，finally 块被「内联复制」到了 try 路径和 catch 路径，这样说对吗？
4. `try-with-resources` 的字节码和 try-finally 有什么本质区别？
5. 下面代码会输出什么顺序？`try / catch / finally / return` 的执行顺序？

---

## 参考要点（盲答后再看）

<details>
<summary>点击展开</summary>

**核心结论（必记）**：
- **finally 里有 return → 覆盖 try/catch 的 return**
- **finally 里修改变量 → 不影响 try 里已经 return 的值**（因为 return 前会把返回值压入操作数栈，finally 修的是局部变量表，不是栈顶的返回值）

**字节码层面的真相**：
```java
// 源码
int test() {
    try { return 1; }
    finally { return 2; }
}
// 字节码逻辑（简化）：
// try 路径：把 1 压栈 → 执行 finally → finally 把 2 压栈 → 返回栈顶（2）！
```

**finally 的字节码实现（重点）**：
- 编译器把 finally 块的字节码**复制三份**：
  1. try 正常执行路径末尾
  2. catch 异常路径末尾
  3. 异常传播路径（如果 finally 也抛异常，原异常被抑制）

**经典陷阱题（必会）**：
```java
public static int test() {
    int x = 0;
    try {
        x = 1;
        return x;   // return 前，x 的值（1）已经被压入操作数栈
    } finally {
        x = 2;     // 改的是局部变量表里的 x，操作数栈里的 1 不受影响
    }
}
// 返回 1（不是 2）
```

**异常情况下的执行顺序**：
```
try 抛异常 → 进入 catch → catch 遇到 return → 先执行 finally → 再真正 return
```

**try-with-resources（Java7+）**：
```java
try (BufferedReader br = new BufferedReader(...)) {
    return br.readLine();
}
// 编译器自动生成 finally：先关资源，再处理异常（异常会被 suppress 掉）
```
比 try-finally 更安全（异常不会掩盖真正的问题）

</details>

---

## 下一步

1. 盲答后，对比参考要点，找到卡壳的地方
2. 打开 `[[异常处理字节码]]` 主题文档，把 finally 的字节码复制机制画出来
3. 在 Obsidian 里建双向链接：`[[01_Java核心/异常处理]]` ←→ 本卡片
4. 在 `[[12_面试训练/每日一题跟踪表]]` 里勾选「今日完成」，打 1~5 分
