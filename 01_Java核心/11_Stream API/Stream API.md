# Stream API

## 这个问题为什么存在？

> 从「没有这个东西会怎样」出发，解释问题的根源。

在Java 8之前，处理集合需要大量的**循环样板代码**：

```java
// 没有Stream时：筛选、转换、聚合
List<String> result = new ArrayList<>();
for (User user : users) {
    if (user.getAge() > 18) {
        String name = user.getName().toUpperCase();
        result.add(name);
    }
}
Collections.sort(result, String::compareTo);
```

**痛点**：
1. **循环嵌套**：筛选→转换→聚合需要三层嵌套循环
2. **代码冗长**：业务逻辑淹没在for循环的模板代码中
3. **难以并行化**：想用多核CPU需要手动写线程代码
4. **难以组合**：不同的数据处理操作难以复用和组合

**核心问题**：Java的集合API只提供了**存储**能力，没有提供**查询/转换**能力。开发者需要在循环中手写处理逻辑，导致代码重复、难以维护。

Stream API的本质是**将数据处理操作抽象为可组合的管道**，让开发者以声明式方式表达"做什么"而非"怎么做"。

## 它是怎么解决问题的？

> 不止讲「是什么」，要讲清楚「为什么这样设计能解决问题」。

### 核心机制

#### Stream的创建

```java
// 1. 从集合创建
Stream<String> s1 = list.stream();       // 顺序流
Stream<String> s2 = list.parallelStream(); // 并行流

// 2. 从数组创建
String[] arr = {"a", "b", "c"};
Stream<String> s3 = Arrays.stream(arr);

// 3. Stream.of()创建
Stream<String> s4 = Stream.of("a", "b", "c");

// 4. 无限流
Stream<Integer> s5 = Stream.iterate(0, n -> n + 2);  // 偶数序列
Stream<Double> s6 = Stream.generate(Math::random);    // 随机数

// 5. 其他来源
Stream<String> lines = Files.lines(Paths.get("file.txt"));
IntStream range = IntStream.range(1, 100);  // 1-99
```

**为什么需要这么多创建方式？**
- 集合是最常见的数据来源，提供`stream()`
- `Stream.of()`适合少量已知元素
- 无限流适合生成测试数据或数学序列
- 原始类型流（`IntStream`、`LongStream`、`DoubleStream`）避免装箱开销

#### 中间操作与终止操作

```java
list.stream()
    .filter(s -> s.length() > 3)  // 中间操作：返回Stream
    .map(String::toUpperCase)      // 中间操作：返回Stream
    .distinct()                    // 中间操作：返回Stream
    .limit(10)                     // 中间操作：返回Stream
    .forEach(System.out::println); // 终止操作：返回void或结果
```

**关键设计**：Stream的操作分为两类：
- **中间操作（Intermediate）**：返回Stream，**延迟执行**
- **终止操作（Terminal）**：触发计算，返回结果

**为什么这样设计？**
- 延迟执行允许**短路**和**优化**：如`limit(10).filter().takeWhile()`等可以合并执行
- 多个中间操作可以**管道化**，减少中间结果创建

#### ASCII图：Stream执行流程

```
┌─────────────────────────────────────────────────────────────┐
│                    Stream执行流程                           │
│                                                             │
│  数据源 ──▶ 中间操作1 ──▶ 中间操作2 ──▶ ... ──▶ 终止操作    │
│           (lazy)      (lazy)               (trigger)      │
│                                                             │
│  ┌─────────────────────────────────────────────────────┐    │
│  │ 终止操作触发前，所有中间操作都不会执行                │    │
│  │ 只有终止操作被调用时，才会触发整个管道的执行          │    │
│  └─────────────────────────────────────────────────────┘    │
│                                                             │
│  示例：                                                     │
│  Stream.of(1,2,3,4,5)                                      │
│      .filter(x -> x > 2)   // [3,4,5]                       │
│      .map(x -> x * 2)      // [6,8,10]                     │
│      .collect(toList());    // 触发执行 → [6,8,10]          │
└─────────────────────────────────────────────────────────────┘
```

#### 短路操作与优化

```java
// 1. takeWhile() - 遇到不满足条件的元素就停止
Stream.of(1, 3, 5, 6, 7, 8)
    .takeWhile(x -> x % 2 == 1)  // [1, 3, 5] - 遇到6就停止

// 2. dropWhile() - 跳过满足条件的元素直到遇到不满足的
Stream.of(1, 3, 5, 6, 7, 8)
    .dropWhile(x -> x % 2 == 1)  // [6, 7, 8] - 跳过1,3,5

// 3. limit() - 限制元素数量
Stream.iterate(1, n -> n + 1)
    .filter(x -> x % 2 == 0)
    .limit(10)  // 取前10个偶数
    .forEach(System.out::println);

// 4. findFirst() / findAny() - 短路终止
Optional<Integer> first = list.stream()
    .filter(x -> x > 100)
    .findFirst();  // 找到第一个就停止
```

**为什么需要短路？**
- 无限流必须有短路操作，否则会无限执行
- 即使有限流，短路也可以**减少计算量**

#### 常用终止操作

```java
// 聚合操作
long count = list.stream().count();
Optional<String> max = list.stream().max(String::compareTo);
int sum = list.stream().mapToInt(Integer::intValue).sum();

// 收集操作
List<String> list1 = stream.collect(Collectors.toList());
Set<String> set = stream.collect(Collectors.toSet());
Map<String, Integer> map = stream.collect(Collectors.toMap(
    Function.identity(),  // key：元素本身
    String::length       // value：字符串长度
));

// 分组与分区
Map<Boolean, List<String>> partitioned = stream
    .collect(Collectors.partitioningBy(s -> s.length() > 3));

Map<String, List<String>> grouped = stream
    .collect(Collectors.groupingBy(String::toUpperCase));

// 字符串拼接
String joined = stream.collect(Collectors.joining(", "));

// 遍历
stream.forEach(System.out::println);
stream.forEachOrdered(System.out::println);  // 保证顺序
```

### 并行流（Parallel Stream）

```java
// 创建并行流
Stream<String> parallel = list.parallelStream();

// 或将顺序流转为并行流
Stream<String> parallel = list.stream().parallel();

// 判断是否为并行流
parallel.isParallel();  // true

// 终止操作会自动并行执行
long count = list.parallelStream()
    .filter(s -> s.length() > 3)
    .count();  // 多线程并行执行filter和count
```

**并行流的底层实现**：
```
┌─────────────────────────────────────────────────────────┐
│ 并行流执行模型                                           │
│                                                         │
│  数据源: [1, 2, 3, 4, 5, 6, 7, 8]                        │
│                                                         │
│  ForkJoinPool.commonPool()                              │
│  ┌─────────────┬─────────────┬─────────────┐             │
│  │ Thread-1   │ Thread-2   │ Thread-3   │             │
│  │ 处理[1,2]  │ 处理[3,4]  │ 处理[5,6]  │             │
│  └─────┬───────┴─────┬───────┴─────┬───────┘             │
│        └─────────────┴─────────────┘                    │
│                    │ 合并结果                            │
│                    ▼                                    │
│            ForkJoinPool.mainJoiner()                    │
└─────────────────────────────────────────────────────────┘
```

**并行流使用默认的ForkJoinPool.commonPool()**，它的大小默认为**CPU核心数-1**。

### Collector与自定义收集

```java
// 内置收集器
Collectors.toList()
Collectors.toSet()
Collectors.toMap(keyMapper, valueMapper)
Collectors.groupingBy(classifier)
Collectors.partitioningBy(predicate)
Collectors.counting()
Collectors.summingInt(mapper)
Collectors.maxBy(comparator)
Collectors.joining(delimiter)

// 自定义收集器
Collector<T, A, R> collector = Collector.of(
    () -> new StringBuilder(),      // supplier: 创建容器
    (sb, t) -> sb.append(t),       // accumulator: 添加元素
    (sb1, sb2) -> sb1.append(sb2), // combiner: 合并容器
    sb -> sb.toString()             // finisher: 转换结果
);

// 使用自定义收集器
String result = stream.collect(collector);
```

### Stream的惰性求值与优化

```java
// 关键概念：惰性求值（Lazy Evaluation）
Stream<Integer> s = Stream.of(1, 2, 3)
    .filter(x -> {
        System.out.println("filter: " + x);
        return x > 1;
    })
    .map(x -> {
        System.out.println("map: " + x);
        return x * 2;
    });

// 此时什么都没打印！所有操作都是惰性的
System.out.println("--- 分隔线 ---");

List<Integer> result = s.collect(Collectors.toList());
// 现在才打印：
// filter: 1  (处理1，不满足>1，跳过)
// filter: 2  (处理2，满足，传递给map)
// map: 2
// filter: 3  (处理3，满足，传递给map)
// map: 3
```

**为什么这样设计？**
- **惰性求值**允许Stream**优化执行顺序**
- JVM可以分析整个管道，选择最优的执行顺序
- 例如：`filter().limit(10).map()`会先limit后filter，减少计算量

## 它和相似方案的本质区别是什么？

> 对比不是列表，要解释「为什么选 A 不选 B」。

### Stream vs 循环

| 维度 | Stream | 循环 |
|------|--------|------|
| **代码风格** | 声明式：描述做什么 | 命令式：描述怎么做 |
| **可读性** | 业务逻辑清晰 | 模板代码干扰 |
| **可组合性** | 高，可链式调用 | 低，难以复用 |
| **并行化** | 一行`.parallel()` | 需手动线程管理 |
| **调试** | 困难 | IDE支持好 |
| **适用场景** | 转换、筛选、聚合 | 复杂副作用操作 |

**为什么选Stream？**
- 业务逻辑更清晰：`.filter().map().collect()`比嵌套循环更易读
- 一键并行化：`parallelStream()`即可利用多核
- 可组合：自定义Collector可复用

**为什么选循环？**
- 需要**复杂副作用**（如修改外部状态）
- 需要**中途退出**（Stream的break支持有限）
- **调试友好**：IDE断点调试支持好

### 顺序流 vs 并行流

```java
// 顺序流
list.stream()
    .filter(...)
    .map(...);

// 并行流
list.parallelStream()
    .filter(...)   // 多线程并行执行
    .map(...);     // 结果合并
```

**什么时候用并行流？**
- 数据量大（>10000元素）
- 操作是CPU密集型（计算密集）
- 没有或很少I/O等待
- 不关心元素顺序（`findAny`而非`findFirst`）

**什么时候不用并行流？**
- 数据量小：线程创建开销大于并行收益
- I/O密集型：瓶颈在I/O，不在CPU
- 有顺序要求：`forEachOrdered`会抵消并行优势
- 有状态依赖：元素之间有依赖关系无法并行

**并行流的常见错误**：
```java
// 错误1：并行流中的非线程安全操作
List<Integer> result = new ArrayList<>();  // 非线程安全
list.parallelStream().forEach(i -> result.add(i));  // 并发修改！

// 正确1：使用collect
List<Integer> result = list.parallelStream()
    .collect(Collectors.toList());

// 错误2：并行化反而更慢（装箱操作）
list.parallelStream()
    .map(Integer::valueOf)  // 装箱
    .sum();

// 正确2：使用原始类型流
list.parallelStream()
    .mapToInt(Integer::intValue)
    .sum();
```

### 内置Collector对比

```java
// toList() vs toSet()
Collectors.toList()   // 保留重复，允许null
Collectors.toSet()    // 去重，允许null

// joining() vs Collectors.joining()
String.join(",", list)                    // 简单拼接
list.stream().collect(Collectors.joining(", "));  // 可加前缀后缀

// groupingBy() vs partitioningBy()
Collectors.groupingBy(Function)    // 按任意分类函数分组
Collectors.partitioningBy(Predicate) // 按布尔条件分为两组
```

## 正确使用方式

> 不是 API 手册，要解释「为什么这样用是对的」。

### 高效使用Stream

```java
// 1. 链式调用，保持简洁
List<String> result = users.stream()
    .filter(u -> u.getAge() > 18)
    .map(User::getName)
    .map(String::toUpperCase)
    .distinct()
    .sorted()
    .collect(Collectors.toList());

// 2. 使用方法引用减少Lambda参数
list.stream().map(User::getName)  // 优于 user -> user.getName()

// 3. 短路操作减少计算
list.stream()
    .filter(x -> x > 0)
    .limit(100)  // 找到100个就停止
    .forEach(System.out::println);

// 4. 合理使用原始类型流
int sum = list.stream()
    .mapToInt(Integer::intValue)  // 避免Integer装箱
    .sum();

// 5. collect时指定容器大小
List<String> list = list2.stream()
    .filter(...)
    .collect(Collectors.toCollection(
        () -> new ArrayList<>(expectedSize)  // 预分配大小，减少扩容
    ));
```

**为什么这样设计？**
- 链式调用符合Stream的声明式风格
- 方法引用比Lambda更简洁，且编译器检查更严格
- 短路操作可以显著减少计算量
- 原始类型流避免装箱开销
- 预分配容器大小减少扩容开销

### 调试Stream

```java
// 1. 使用peek()调试（不修改元素）
list.stream()
    .filter(x -> x > 0)
    .peek(x -> System.out.println("过滤后: " + x))  // 调试用
    .map(x -> x * 2)
    .forEach(System.out::println);

// 2. 复杂场景用循环
// Stream调试困难，建议复杂逻辑用传统循环

// 3. 在IDE中逐步执行
// IDEA支持在Lambda表达式上设置断点
```

### 并行流最佳实践

```java
// 1. 使用专门的线程池
ForkJoinPool pool = new ForkJoinPool(4);
pool.submit(() ->
    list.parallelStream()
        .filter(...)
        .forEach(...)
);
pool.shutdown();

// 2. 使用collect而非forEach
List<String> result = list.parallelStream()
    .filter(...)
    .collect(Collectors.toList());  // 线程安全

// 3. 避免长管道
// 并行流的线程切换有开销，管道太长反而慢

// 4. 数据源影响并行效率
Arrays.parallelSort(arr);  // 数组：高效
list.parallelStream();     // 链表：效率低（分割成本高）
```

## 边界情况和坑

> 不是列举，要解释「坑的成因」。

### 坑1：Stream只能消费一次

```java
Stream<String> s = list.stream();
s.forEach(System.out::println);  // OK
s.forEach(System.out::println);  // IllegalStateException: 流已被操作或关闭

// 解决方案：需要重新创建流
list.stream().forEach(System.out::println);
list.stream().forEach(System.out::println);
```

**成因**：Stream是**一次性**的，设计上是为了避免重复消费产生意外结果。

### 坑2：并行流的顺序不确定性

```java
// 不保证顺序
list.parallelStream()
    .filter(x -> x > 0)
    .forEach(System.out::println);  // 顺序不确定

// 保证顺序
list.parallelStream()
    .filter(x -> x > 0)
    .forEachOrdered(System.out::println);  // 按原始顺序

// findAny() vs findFirst()
Optional<String> any = list.parallelStream()
    .filter(s -> s.length() > 3)
    .findAny();  // 任意一个，更快

Optional<String> first = list.parallelStream()
    .filter(s -> s.length() > 3)
    .findFirst();  // 第一个，强制顺序

// toList() 不保证顺序
List<String> list1 = list.parallelStream().collect(Collectors.toList());  // 无序
List<String> list2 = list.parallelStream().sorted().collect(Collectors.toList());  // 有序
```

### 坑3：自动装箱的性能陷阱

```java
// 慢：大量Integer装箱操作
int sum = list.stream()
    .map(Integer::valueOf)  // int → Integer装箱
    .reduce(0, Integer::sum);  // Integer → int拆箱

// 快：原始类型流
int sum = list.stream()
    .mapToInt(Integer::intValue)  // 无装箱
    .sum();  // 原始类型求和
```

**成因**：Stream<T>处理int时需要`int→Integer`装箱和`Integer→int`拆箱，开销巨大。

### 坑4：null值处理

```java
// list包含null
List<String> list = Arrays.asList("a", null, "b");

// filter会正常处理null
list.stream()
    .filter(Objects::nonNull)  // 过滤null
    .forEach(System.out::println);

// 但collect可能出问题
Map<String, Integer> map = list.stream()
    .collect(Collectors.toMap(
        Function.identity(),
        String::length
    ));  // NullPointerException：null作为key

// 解决方案：过滤或使用Optional
```

### 坑5：无限流必须短路

```java
// 错误：无限流+非短路操作 = 死循环
Stream.iterate(0, n -> n + 1)
    .map(x -> x * 2)
    .filter(x -> x > 0)
    .collect(Collectors.toList());  // 永不停止！

// 正确：添加limit或其他短路操作
Stream.iterate(0, n -> n + 1)
    .map(x -> x * 2)
    .filter(x -> x > 0)
    .limit(100)  // 限制数量
    .collect(Collectors.toList());  // OK
```

### 坑6：flatMap的误解

```java
// 错误理解：flatMap会把元素"展平"
List<List<String>> nested = Arrays.asList(
    Arrays.asList("a", "b"),
    Arrays.asList("c", "d")
);

nested.stream()
    .map(list -> list)  // [[a,b], [c,d]]
    .collect(Collectors.toList());  // [[a,b], [c,d]]

// 正确理解：flatMap先map再扁平化
nested.stream()
    .flatMap(list -> list.stream())  // [a, b, c, d]
    .collect(Collectors.toList());  // [a, b, c, d]

// 用途：把String[]数组转为单个String
String[] words = {"hello", "world"};
Arrays.stream(words)
    .flatMap(word -> Arrays.stream(word.split("")))  // [h, e, l, l, o, w, o, r, l, d]
    .distinct()
    .collect(Collectors.toList());  // 去重
```

## 我的理解（可选）

> 用自己的话重新表述一遍，检验是否真正理解。

Stream API的核心思想是**把数据处理管道化**：从数据源出发，经过一系列中间操作（filter、map、distinct等），最后用终止操作触发计算。

**核心机制**：
- 中间操作是**惰性**的，只有终止操作才会触发执行
- 这种设计允许JVM**优化执行顺序**（如先limit后filter）
- 并行流通过ForkJoinPool实现多线程并行处理

**Stream vs 循环的选择**：
- 业务逻辑清晰用Stream，复杂副作用用循环
- 大数据量并行处理用Stream，小数据量用循环
- 需要调试用循环，声明式表达用Stream

**最容易被忽略的坑**：
- Stream只能消费一次
- 并行流不保证顺序
- 自动装箱的性能开销
- 无限流必须配合短路操作

## 面试话术总结

1. **Stream和Collection的区别？**
   "Collection是存储数据的容器，关注的是如何存储数据；Stream是数据处理的管道，关注的是如何处理数据。Collection需要主动遍历元素，Stream是惰性求值，只有终止操作才会触发计算。另一个关键区别是Stream只能消费一次，不能重复使用。"

2. **中间操作和终止操作的区别？**
   "中间操作返回Stream本身，是惰性的，不会触发实际计算；终止操作返回结果或void，会触发整个管道的执行。Stream的设计允许JVM分析整个管道并进行优化，比如将limit操作提前到filter前面执行，减少计算量。"

3. **parallelStream和普通stream的区别？如何正确使用并行流？**
   "parallelStream使用ForkJoinPool.commonPool()实现多线程并行处理，适合大数据量、CPU密集型、无顺序要求的场景。使用时需要注意：1）不要在并行流中对非线程安全的集合进行add等操作；2）尽量使用原始类型流避免装箱开销；3）管道不要太长；4）数据量小时并行开销可能大于收益。"

4. **flatMap和map的区别？**
   "map是一对一转换，如`Stream<List> → Stream<List>`；flatMap是一对多转换加扁平化，如`Stream<List> → Stream<String>`。flatMap的原理是先将每个元素映射为一个Stream，再将这些Stream合并为一个Stream。常见用途包括将字符串数组拆分为单个字符。"

5. **Stream的性能如何？有哪些优化建议？**
   "Stream本身性能不错，但使用不当会慢。主要优化点：1）大数据量才考虑parallelStream；2）使用原始类型流（IntStream等）避免装箱；3）合理使用limit、findFirst等短路操作；4）避免无限流没有short-circuit；5）collect时预分配容器大小。对于小数据量，循环往往比Stream更快更简洁。"
