# 题目：hashCode 和 equals 的关系是什么？不重写会有什么后果？

---

## ⚠️ 先盲答

**不要看任何资料，用自己的话回答，写到纸上或心里默念也行。**

说出三条必须满足的契约，以及一个**破坏契约导致严重后果**的具体例子。

---

## 盲答引导

1. `Object.hashCode()` 的默认实现是什么？和对象的内存地址有什么关系？
2. 把自定义类放进 `HashMap`，如果不重写 equals/hashCode，会发生什么？
3. 重写了 equals 但不重写 hashCode，`HashMap` 还能正确工作吗？什么场景下出问题？
4. 只重写 hashCode 不重写 equals，可以吗？为什么？
5. String、Integer 这些类是如何同时重写 equals 和 hashCode 的？算法是什么？

---

## 知识链提示

这道题应该让你联想到：

- `equals和hashCode契约` → 三条必须满足的契约
- `[[01_Java核心/05_集合框架/HashMap]]` → 底层数组 + 链表 / 红黑树，hashCode 决定落在哪个桶
- `HashSet原理` → `HashSet<E>` = `HashMap<E, Object>`（dummy value）
- `Object.hash` → JDK 7+ 提供的 hash 组合工具方法
- `Objects.equals` → JDK 7+ 的空指针安全的 equals 工具

---

## 核心追问

1. 为什么 hashCode 返回 long/double 字段时，通常取 `Double.hashCode(x)` 而不是 `x.hashCode()`？
2. `HashMap` 用 `hashCode` 找到桶之后，怎么判断「是不是要找的那个对象」？
3. 两个对象 equals 返回 true，hashCode 必须相等。那反过来，hashCode 相等的两个对象，一定 equals 吗？
4. 自己写 equals 时，推荐用 `Objects.equals(a, b)` 还是 `a.equals(b)`？为什么？
5. `IdentityHashMap` 是怎么工作的？它用 equals 还是 == 来比较 key？

---

## 参考要点（盲答后再看）


**equals/hashCode 契约**（Java Language Specification）：

```
1. 自反性：x.equals(x) 必须返回 true
2. 对称性：x.equals(y) == y.equals(x)
3. 传递性：x.equals(y) && y.equals(z) → x.equals(z)
4. 一致性：只要对象没变，多次 equals 结果必须一致
5. 与 hashCode 的关联：
   - x.equals(y) == true  →  x.hashCode() == y.hashCode()
   - 反过来不一定（哈希冲突！）
```

**破坏契约的典型后果**：

```java
class Person {
    String name;
    int age;
    // 只重写了equals，没重写hashCode！

    @Override
    public boolean equals(Object o) {
        return this.name.equals(((Person) o).name) && this.age == ((Person) o).age;
    }
    // hashCode 用的是 Object 默认的（地址）
}

// 使用场景：
HashSet<Person> set = new HashSet<>();
Person p1 = new Person("张三", 30);
Person p2 = new Person("张三", 30);

set.add(p1);
set.contains(p2);  // ❌ 返回false！
                  // p1 和 p2 hashCode 不同（地址不同），在 HashMap 里落在不同桶！
```

**正确的 hashCode 写法**（JDK 8+ Objects.hash）：
```java
@Override
public int hashCode() {
    return Objects.hash(name, age);  // 自动组合各字段的hash
    // 等价于 JDK 7 之前的：
    // int result = 17;
    // result = 31 * result + name.hashCode();
    // result = 31 * result + age;
}
```

**为什么用 31 作为乘数？**
- 质数，奇数（偶数乘以2会溢出）
- 31 * i = (i << 5) - i，现代 JVM 会自动优化为移位操作

**IdentityHashMap**：
- 用 `System.identityHashCode()`（即 Object 默认的 hashCode，基于地址）
- 用 `==` 比较 key（不是 equals）
- 不走常规哈希表逻辑，不维护数组结构


---

## 下一步

1. 盲答后，对比参考要点，找到卡壳的地方
2. 打开 `[[13_面试训练/01_题目知识链/01_Java核心/08_hashCode与equals]]` 主题文档，把没懂的地方填进去
3. 在 Obsidian 里建双向链接
4. 在 `[[13_面试训练/03_每日一题/每日一题跟踪表]]` 里勾选「今日完成」，打 1~5 分
