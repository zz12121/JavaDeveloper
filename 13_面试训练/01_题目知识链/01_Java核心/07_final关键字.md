# 题目：final 关键字在 Java 里到底起了什么作用？ final 修饰的变量就一定线程安全吗？

---

## ⚠️ 先盲答

**不要看任何资料，用自己的话回答，写到纸上或心里默念也行。**

把 `final` 在三个场景（类/方法/变量）的作用分别说清楚，并指出一个反例。

---

## 盲答引导

1. `final class A` 意味着什么？能不能被继承？能不能被 `new A()` 创建？
2. `final method()` 意味着什么？为什么 `private` 方法天然是 final 的？
3. `final variable` 和 `blank final` 有什么区别？空白 final 的初始化时机？
4. `final` 真的能让对象不可变吗？`final Object obj = new HashMap<>()` 这个对象能修改吗？
5. `static final` 和 `final static` 有区别吗？加载时机分别是什么时候？

---

## 知识链提示

这道题应该让你联想到：

- `final与不可变` → `final` 修饰的是**引用**（指针），不是**对象**
- `final域初始化` → 构造函数返回后，final 域必须对所有线程可见
- `逸出问题` → `this.obj = new Something()` 在构造函数里，this 逸出导致其他线程看到未初始化完的对象
- `String不可变性` → String 为什么用 `final` 修饰数组？
- `JMMhappens-before` → `final` 域的写 happens-before 后续读（构造函数结束 → final 域可见）

---

## 核心追问

1. `final Object obj = new Object()`，其他线程一定能读到 obj 的非 null 值吗？（构造器逸出问题）
2. `final int[] arr = {1, 2, 3}; arr[0] = 100;` 合法吗？`final` 在这里保护了什么？
3. `Collections.unmodifiableList()` 和 `final` 修饰 List，哪个真正做到了不可变？
4. 为什么 `String` 是不可变的，不光是因为 `final`，还因为什么？
5. `final` 能保证可见性吗？`volatile` 和 `final` 的区别是什么？

---

## 参考要点（盲答后再看）


**final 的三个作用**：

| 位置 | 作用 |
|------|------|
| `final class` | 禁止继承（String、Integer 等） |
| `final method` | 禁止重写（private 天然 final） |
| `final variable` | 禁止重新赋值 |

**final 不等于不可变**：
```java
final List<String> list = new ArrayList<>();
list.add("a");  // ✅ 合法！final 只保护引用不变化，不保护对象内容
list = new ArrayList<>();  // ❌ 不合法
```
真正不可变：用 `Collections.unmodifiableList()` 或 `ImmutableList` 或 Guava `copyOf`。

**构造函数逸出**：
```java
class Something {
    final int x;
    Something() {
        x = 100;
        // 错误：在构造函数里把this传给其他线程/方法
        // 此时x可能还未初始化完成！
        register(this);  // 逸出！
    }
}
```

**happens-before 与 final（JLS 规则）**：
```
构造函数中final字段的写入
  happens-before
从构造函数返回之后，该对象的任何引用对其他线程可见
（前提：构造函数没有把this逸出）
```

**static final vs blank final**：
```java
static final int A = 100;     // 类加载时初始化，只初始化一次
final int B;                   // blank final，必须在构造函数里初始化
final int C = 100;             // 普通final，初始化一次
```


---

## 下一步

1. 盲答后，对比参考要点，找到卡壳的地方
2. 打开 `[[01_Java核心/01_基础语法/final关键字|01_Java核心/final关键字]]` 主题文档，把没懂的地方填进去
3. 在 Obsidian 里建双向链接
4. 在 `[[13_面试训练/03_每日一题/每日一题跟踪表]]` 里勾选「今日完成」，打 1~5 分
