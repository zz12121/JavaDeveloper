# Stream API

> Stream 是 Java 对集合数据的**一次性处理管道**。你不告诉它"怎么遍历"，只告诉它"做什么操作"——筛选、转换、聚合。中间操作是惰性的（延迟执行），终止操作才触发计算。这种设计让 JVM 有机会优化整个管道的执行。

---

## 这个问题为什么存在？

Java 的集合框架（`List`、`Set`、`Map`）提供了强大的数据存储能力，但只有一种遍历方式：外部迭代（for-each 循环）。

```java
// 筛选成年人 → 取名字 → 转大写 → 去重 → 排序
List<String> result = new ArrayList<>();
for (User user : users) {
    if (user.getAge() >= 18) {
        result.add(user.getName().toUpperCase());
    }
}
result.sort(Comparator.naturalOrder());
// result = result.stream().distinct().collect(Collectors.toList());  // 去重也要写循环
```

问题在于：

1. **意图被控制流淹没**：业务是"筛选成年人名字"，但代码在说"创建列表、遍历、判断、添加、排序"
2. **难以组合**：每个数据处理步骤都需要独立的循环和临时变量
3. **无法并行**：想用多核 CPU 需要手动写 `ExecutorService` + `Future`
4. **无法优化**：编译器无法看到"全局意图"，无法短路或重排操作顺序

Stream 的核心设计：**内部迭代 + 惰性求值 + 可组合管道**。

---

## 它是怎么解决问题的？

### 两种操作：中间操作（惰性）和终止操作（触发）

```java
list.stream()
    .filter(s -> s.length() > 3)    // 中间操作：返回 Stream，不执行
    .map(String::toUpperCase)        // 中间操作：返回 Stream，不执行
    .distinct()                      // 中间操作：返回 Stream，不执行
    .collect(Collectors.toList());   // 终止操作：触发整个管道执行
```

**惰性求值的意义**：在终止操作调用之前，中间操作不会执行任何数据处理。JVM 可以分析整个管道，合并操作、短路执行、减少中间集合创建。

```
数据源 → filter → map → distinct → collect
  │        │       │       │         │
  │      (惰性)  (惰性)  (惰性)    (触发)
  │                                    │
  └──────── 触发后，数据逐元素流过 ─────┘
```

### 惰性求值的执行方式

Stream 不是"对整个集合依次执行每个操作"，而是**逐元素流过所有操作**：

```java
Stream.of(1, 2, 3, 4, 5)
    .filter(x -> {
        System.out.println("filter: " + x);
        return x > 2;
    })
    .map(x -> {
        System.out.println("map: " + x);
        return x * 2;
    })
    .collect(toList());

// 执行顺序（注意是交叉的，不是分阶段的）：
// filter: 1  → 1 不满足，跳过
// filter: 2  → 2 不满足，跳过
// filter: 3  → 3 满足 → map: 3 → 输出 6
// filter: 4  → 4 满足 → map: 4 → 输出 8
// filter: 5  → 5 满足 → map: 5 → 输出 10
```

这种**逐元素流过**（而非逐阶段处理）的方式有两个好处：不需要中间集合、可以短路。

### 短路操作

```java
// limit：找到足够数量就停止
Stream.iterate(1, n -> n + 1)
    .filter(x -> x % 2 == 0)
    .limit(5)                    // 只要 5 个
    .forEach(System.out::println); // 输出 2, 4, 6, 8, 10

// findFirst：找到第一个就停止
Optional<Integer> first = list.stream()
    .filter(x -> x > 100)
    .findFirst();  // 找到就停，不会遍历剩余元素

// anyMatch：只要有一个满足就停止
boolean hasLong = list.stream()
    .anyMatch(s -> s.length() > 10);
```

没有短路操作，`Stream.iterate()` 这样的无限流会导致无限循环。

### Collector：终止操作的瑞士军刀

`collect` 是最通用的终止操作，配合 `Collectors` 工厂方法可以实现几乎所有聚合逻辑：

```java
// 分组（groupBy）
Map<String, List<User>> byCity = users.stream()
    .collect(Collectors.groupingBy(User::getCity));

// 分组 + 下游聚合
Map<String, Long> countByCity = users.stream()
    .collect(Collectors.groupingBy(
        User::getCity,
        Collectors.counting()
    ));

// 分区（partitioningBy 是特殊的 groupingBy，key 只有 true/false）
Map<Boolean, List<User>> adults = users.stream()
    .collect(Collectors.partitioningBy(u -> u.getAge() >= 18));

// 嵌套分组
Map<String, Map<Integer, List<User>>> byCityAndAge = users.stream()
    .collect(Collectors.groupingBy(
        User::getCity,
        Collectors.groupingBy(User::getAge)
    ));

// toMap
Map<String, Integer> nameToAge = users.stream()
    .collect(Collectors.toMap(
        User::getName,
        User::getAge,
        (oldVal, newVal) -> newVal  // key 冲突时取新值
    ));
```

自定义 Collector 的核心是四个函数：`supplier`（创建容器）、`accumulator`（添加元素）、`combiner`（合并容器，并行流用）、`finisher`（转换最终结果）。

---

## 深入原理

### 并行流：ForkJoinPool 下的分治执行

```java
list.parallelStream()
    .filter(...)
    .map(...)
    .collect(toList());
```

并行流使用 `ForkJoinPool.commonPool()`，默认线程数为 `Runtime.getRuntime().availableProcessors() - 1`。执行过程：

```
数据源: [1, 2, 3, 4, 5, 6, 7, 8]
        │
   ┌────┴────┐
   ▼         ▼
[1,2,3,4]  [5,6,7,8]    ← 递归拆分（Spliterator.split）
   │         │
  ┌┴┐      ┌┴┐
  ▼ ▼      ▼ ▼
[1,2] [3,4] [5,6] [7,8] ← 各线程独立处理
  │     │     │     │
  ▼     ▼     ▼     ▼
 结果  结果   结果   结果   ← 合并结果（combiner）
```

**并行流快不快取决于三个因素**：

1. **数据量**：万级以上才有意义，百级以下线程调度开销 > 并行收益
2. **数据源的可分割性**：`ArrayList`（数组底层）分割高效，`LinkedList`（链表）分割代价高
3. **操作是否有状态**：`filter`/`map`（无状态）适合并行，`sorted`/`distinct`（有状态）需要全局协调，并行收益小

### Stream vs 循环：不是谁取代谁

| 场景 | 推荐 | 原因 |
|------|------|------|
| 简单筛选/映射/聚合 | Stream | 代码简洁，意图清晰 |
| 需要修改外部状态 | 循环 | Stream 要求无副作用 |
| 需要中途 break/return | 循环 | Stream 的短路支持有限 |
| 需要调试 | 循环 | IDE 断点调试 Stream 链非常困难 |
| 大数据量并行处理 | Stream | `parallelStream()` 一行搞定 |
| 性能极致敏感 | 循环 | Stream 有管道开销（创建 Spliterator、包装操作） |

**经验法则**：如果 Lambda 体超过 3 行，考虑提取为方法引用；如果整个 Stream 链超过 5 个操作，考虑是否应该用循环。

---

## 正确使用方式

### 常见模式

```java
// 1. 集合转换管道
List<String> result = users.stream()
    .filter(u -> u.getAge() >= 18)
    .map(User::getName)
    .map(String::toUpperCase)
    .distinct()
    .sorted()
    .collect(Collectors.toList());

// 2. toMap 的三种写法
// 简单（key/value 不能为 null）
Map<String, Integer> m1 = users.stream()
    .collect(Collectors.toMap(User::getName, User::getAge));

// key 冲突处理
Map<String, User> m2 = users.stream()
    .collect(Collectors.toMap(
        User::getName,
        Function.identity(),
        (old, new_) -> new_  // 保留新值
    ));

// 指定 Map 实现（保证有序）
LinkedHashMap<String, User> m3 = users.stream()
    .collect(Collectors.toMap(
        User::getName,
        Function.identity(),
        (old, new_) -> new_,
        LinkedHashMap::new
    ));

// 3. 字符串拼接
String names = users.stream()
    .map(User::getName)
    .collect(Collectors.joining(", ", "[", "]"));  // [Alice, Bob, Charlie]
```

### 性能优化技巧

```java
// 1. 用原始类型流避免装箱
int sum = list.stream()
    .mapToInt(Integer::intValue)
    .sum();

// 2. 预分配 Collector 容器大小
List<String> result = list.stream()
    .filter(s -> s.length() > 3)
    .collect(Collectors.toCollection(() -> new ArrayList<>(expectedSize)));

// 3. 先过滤再映射，减少处理量
// 好
list.stream().filter(x -> x != null).map(x -> x.toUpperCase())
// 差
list.stream().map(x -> x.toUpperCase()).filter(x -> x != null)
// （差的方式对 null 调用 toUpperCase 会 NPE）

// 4. 并行流用专用线程池，避免占用 commonPool
ForkJoinPool pool = new ForkJoinPool(4);
pool.submit(() ->
    list.parallelStream().filter(...).collect(toList())
).get();
pool.shutdown();
```

---

## 边界情况和坑

### 坑 1：Stream 只能消费一次

```java
Stream<String> s = list.stream();
s.forEach(System.out::println);  // OK
s.collect(toList());             // IllegalStateException: stream has already been operated upon
```

**成因**：Stream 设计为一次性管道。它的内部状态（Spliterator 的游标位置）在终止操作后就不可重置了。

**解法**：需要多次处理时，每次重新创建 `list.stream()`。如果数据源构建成本高，可以先 `collect` 到 List 中。

### 坑 2：toMap 的 null key/value 会 NPE

```java
// NullPointerException
list.stream().collect(Collectors.toMap(
    Function.identity(),   // key 不能为 null
    String::length         // value 不能为 null
));
```

`Collectors.toMap()` 内部使用 `HashMap.merge()`，`merge` 遇到 null key 或 null value 会 NPE。如果数据可能包含 null，先 `filter(Objects::nonNull)` 过滤，或者用 `Collectors.toMap()` 的三参数版本加上合并函数，或者使用第三方库的 `ImmutableMap.toImmutableMap()`（会给出更明确的错误信息）。

### 坑 3：并行流中 forEach 修改外部 ArrayList

```java
List<Integer> result = new ArrayList<>();
list.parallelStream().forEach(i -> result.add(i));  // 可能丢数据或抛异常
```

**成因**：`ArrayList.add()` 不是线程安全的，并行流的多个线程同时调用它会产生竞态条件。

**解法**：用 `collect(toList())` 替代 `forEach` + 手动添加。`collect` 的 `combiner` 函数保证并行结果的正确合并。

### 坑 4：parallelStream 共享 ForkJoinPool.commonPool()

```java
// 请求1：并行流
list.parallelStream().map(...).collect(toList());

// 请求2：同时使用并行流
otherList.parallelStream().map(...).collect(toList());
// → 两者竞争同一个 commonPool 的线程，互相拖慢
```

在 Web 服务器中（如 Tomcat），多个请求如果都用 `parallelStream()`，会共享一个默认大小为 `CPU核数-1` 的线程池，导致请求间互相阻塞。**生产环境中应该使用专用 `ForkJoinPool`。**

### 坑 5：flatMap 的错误使用

```java
// 常见错误：以为 flatMap 会自动展平
List<List<String>> nested = ...;
nested.stream()
    .map(list -> list)  // 返回 Stream<List<String>>，没有展平
    .collect(toList());

// 正确：flatMap 需要把每个元素映射为 Stream
nested.stream()
    .flatMap(List::stream)  // 返回 Stream<String>，展平了
    .collect(toList());
```

`flatMap` = `map` + 展平。它要求你把每个元素映射为一个 `Stream`，然后自动把所有 `Stream` 合并为一个。如果你映射的不是 `Stream`（如映射为 `List`），编译不会报错，但运行时会得到嵌套结构而非展平结果。

### 坑 6：Stream.of(null) 会 NPE

```java
Stream.of(null);           // NullPointerException
Stream.of("a", null, "b"); // NullPointerException

// 安全的写法
Stream.ofNullable(null);     // Java 9+，返回空 Stream
Stream.concat(
    Stream.ofNullable(a),
    Stream.ofNullable(b)
);
```
