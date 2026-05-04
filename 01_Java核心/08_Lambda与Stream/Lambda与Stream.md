# Lambda 与 Stream

> Lambda 解决了"如何把一段代码作为参数传递"，Stream 解决了"如何用声明式的方式处理集合数据"。两者合在一起，让 Java 从"命令式循环"进化到了"声明式管道"——你只说"要什么"，不说"怎么遍历"。

---

## 这个问题为什么存在？

Java 8 之前处理集合数据只有一种方式：for 循环。

```java
// 筛选成年人 → 取名字 → 转大写 → 排序
List<String> result = new ArrayList<>();
for (User user : users) {
    if (user.getAge() >= 18) {
        String name = user.getName().toUpperCase();
        result.add(name);
    }
}
Collections.sort(result);
```

这段代码的每一行都在告诉计算机"怎么做"：创建列表、遍历、判断、转换、添加、排序。真正的业务意图（"筛选成年人名字"）淹没在控制流模板代码中。

更根本的问题是：**Java 之前无法将"一段行为"作为参数传递。** 你只能传递数据，不能传递逻辑。匿名内部类是唯一的变通方式，但 5 行模板代码才能表达 1 行逻辑的代价太高。

---

## 核心脉络

### Lambda 与 Stream 的协作关系

```
Lambda（行为参数化）          Stream（数据管道）
      │                           │
      │  提供可传递的行为          │  提供可组合的操作
      │                           │
      └─────────┬─────────────────┘
                ▼
        list.stream()
            .filter(u -> u.getAge() >= 18)   ← Lambda 作为 filter 的参数
            .map(User::getName)               ← 方法引用作为 map 的参数
            .sorted()
            .collect(toList());               ← 终止操作触发执行
```

### 各维度文档导航

- [[01_Java核心/08_Lambda与Stream/Lambda与函数式|Lambda 与函数式]]：函数式接口、invokedynamic 底层、变量捕获、方法引用。重点：Lambda ≠ 匿名内部类、this 指向、effectively final
- [[01_Java核心/08_Lambda与Stream/Stream API|Stream API]]：惰性求值、中间/终止操作、并行流、Collector。重点：Stream 只能消费一次、装箱陷阱、并行流适用条件

---

## 与其他维度的关系

- [[01_Java核心/02_面向对象/内部类|内部类]]：Lambda 可以看作匿名内部类的进化——但底层实现完全不同（invokedynamic vs 生成 $1.class）
- [[01_Java核心/04_泛型/泛型#PECS原则|PECS 原则]]：Stream 的 `map`/`flatMap` 遵循类似的生产者-消费者模式
- [[01_Java核心/05_集合框架/List与Set|List 与 Set]]：Stream 不存储数据，它是对 Collection 的一次性视图——理解集合的内部结构（ArrayList vs LinkedList）能帮助判断并行流的效率
- [[01_Java核心/07_注解与反射/注解|注解]]：`@FunctionalInterface` 是 SOURCE 级注解，编译期检查接口是否符合函数式接口规范
- [[01_Java核心/09_Java新特性/Java新特性|Java 新特性]]：Java 9 的 `Stream.takeWhile/dropWhile`、Java 16 的 `Stream.toList()` 都是 Stream API 的演进
