# 题目：String、StringBuilder、StringBuffer 的区别到底是什么？

---

## ⚠️ 先盲答

**不要看任何资料，用自己的话回答，写到纸上或心里默念也行。**

不仅回答「线不安全/安全/不可变」，把**为什么**说出来。

---

## 盲答引导

1. `String s = "a" + "b"` 编译后变成了什么？
2. `new String("abc")` 创建了几个对象？
3. StringBuilder 的 `append()` 在底层怎么扩容？
4. 为什么 String 要设计成 `final` 的？如果不 `final`，会有什么问题？
5. `intern()` 方法在什么情况下会把字符串放入常量池？

---

## 知识链提示

这道题应该让你联想到：

- `String不可变性` → final char[] 在 JDK 9 之后变成了什么？
- `[[01_Java核心/01_基础语法/字符串]]` → 字符串常量池在哪里？元空间还是堆？
- `JDK版本差异` → JDK 9 对 String 做了什么改动？为什么？
- `+号拼接` → `javac` 编译后到底用了 StringBuilder 还是 StringConcatFactory？
- `equals和hashCode` → String 重写了 hashCode，算法是啥？

---

## 核心追问

1. 下面代码创建几个对象？
   ```java
   String s1 = new String("a");
   String s2 = s1.intern();
   ```
2. `String s = "a" + "b" + "c"` 在编译期和运行期分别发生了什么？
3. `new StringBuilder().append("a").append("b").toString()` 创建了几个对象？
4. 为什么 StringBuffer 是线程安全的但几乎没人用？JVM 有没有对它做优化？
5. `String`、`Long` 的 `intern()` 在 G1 垃圾收集器下有什么坑？

---

## 参考要点（盲答后再看）


**核心区别**：

| | String | StringBuilder | StringBuffer |
|--|--------|----------------|---------------|
| 可变性 | 不可变（final char[] / byte[]） | 可变 | 可变 |
| 线程安全 | 天然安全（不可变） | 不安全 | 安全（synchronized） |
| 性能 | `+` 拼接会生成大量对象 | 最快 | 慢（同步开销） |

**JDK 9 改动**：
```
JDK 8 及之前：char[]（每个字符占2字节）
JDK 9 及之后：byte[] + coder标志（LATIN1占1字节，UTF16占2字节）
省内存，这也是为什么 String 相关的面试题要区分JDK版本
```

**+ 号拼接真相**（分版本）：
```
JDK 8 及之前：javac 编译成 StringBuilder.append()
JDK 9 及之后：使用 StringConcatFactory.makeConcat()（InvokeDynamic）
```

**new String("abc") 几个对象**：
- 编译期：常量池放入 "abc"（如果之前没有）→ 1个
- 运行期：`new String()` 在堆里创建对象 → 1个
- **答**：通常是 1 个或 2 个（取决于常量池是否已有）

**intern() 规则**（JDK 7+）：
- 常量池从方法区移到**堆**
- `intern()`：如果常量池没有，把堆里对象的**引用**放入常量池（而不是拷贝）


---

## 下一步

1. 盲答后，对比参考要点，找到卡壳的地方
2. 打开 `[[01_Java核心/String不可变性]]` 主题文档，把没懂的地方填进去
3. 在 Obsidian 里建双向链接：`[[01_Java核心/String底层结构]]` ←→ 本卡片
4. 在 `[[13_面试训练/03_每日一题/每日一题跟踪表]]` 里勾选「今日完成」，打 1~5 分
