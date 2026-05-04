# Java 新特性

> Java 新特性不是"炫技清单"，是语言层面解决实际开发痛点的演进记录。每个特性的出现都有明确的背景——理解"为什么要加这个"，比记住"怎么用"重要得多。

---

## 这个问题为什么存在？

Java 从 1995 年诞生至今经历了四个大阶段，每个阶段的核心主题都对应当时的行业痛点：

| 时期 | 版本范围 | 核心主题 | 解决的痛点 |
|------|---------|---------|-----------|
| 强类型化 | Java 5~7 | 泛型、枚举、注解、try-with-resources | 类型安全、配置管理、资源泄漏 |
| 函数式革命 | Java 8 | [[01_Java核心/08_Lambda与Stream/Lambda与函数式\|Lambda]]、[[01_Java核心/08_Lambda与Stream/Stream API\|Stream API]]、Optional | 样板代码、集合处理、null 安全 |
| 现代化基础设施 | Java 9~11 | 模块系统（JPMS）、var、HTTP Client、不可变集合工厂 | 依赖管理、类型冗余、网络库老化 |
| 声明式 + 轻量并发 | Java 14~21 | Records、Sealed Classes、Pattern Matching、Virtual Threads | DTO 样板代码、继承失控、类型匹配繁琐、线程昂贵 |

**一个关键认知**：Java 不是在追潮流，而是在解决真实问题。Records 不是为了"好看"，是为了消除 Lombok 和样板代码；Virtual Threads 不是为了"高性能"，是为了让开发者不用操心线程池大小。

---

## 它是怎么解决问题的？

### Optional：让 null 显式化（Java 8）

`NullPointerException` 是 Java 最常见的异常，根源在于方法的返回值可能是 null，但调用方不知道。`Optional<T>` 是一个容器——要么有值，要么没有：

```java
// 返回 Optional 而不是 null
public Optional<User> findUser(Long id) {
    return Optional.ofNullable(userMap.get(id));
}

// 链式处理，不用逐层判空
String city = findUser(id)
    .map(User::getAddress)
    .map(Address::getCity)
    .orElse("unknown");
```

**正确用法**：方法返回值 → 用 Optional；方法参数 → 不用（增加调用复杂度）；字段 → 不用（Optional 不实现 Serializable，影响序列化）。

**`orElse` vs `orElseGet` 的区别**：
- `orElse(defaultValue)`：无论 Optional 是否有值，`defaultValue` 都会被求值
- `orElseGet(Supplier)`：只在 Optional 为空时才调用 Supplier

当默认值创建成本低（如字符串字面量），两者无区别。当默认值涉及 IO、数据库查询时，**必须用 `orElseGet`**，否则每次调用都会执行昂贵操作。

### var：减少类型噪声（Java 10）

```java
// 泛型嵌套时类型声明极其冗长
Map<String, List<Map<String, Integer>>> map = new HashMap<>();

// var 推断
var map = new HashMap<String, List<Map<String, Integer>>>();
```

`var` 只能用于有初始化器的局部变量——编译器需要从右侧推断类型。不能用于字段、方法参数、返回类型，也不能初始化为 `null`。**适用场景**：泛型嵌套、try-with-resources、长类名（如 `HttpClient`）。**不适用**：简单类型（`var x = 5` 反而降低了可读性）。

### Records：消灭 DTO 样板代码（Java 16 正式）

```java
// Java 15 之前：40+ 行的 POJO
// Java 16：一行
public record Point(int x, int y) {}
```

Record 自动生成：全参构造器、访问器（`x()` 而非 `getX()`）、`equals`、`hashCode`、`toString`。

**关键限制**：
- 字段是 `final` 的——不可变。需要可变字段不要用 Record
- 不能继承其他类（隐式继承 `java.lang.Record`），可以实现接口
- [[01_Java核心/06_IO与NIO/序列化|序列化]]：Record 默认不支持 Java 原生序列化（因为 `java.lang.Record` 没有实现 `Serializable`），但可以实现 `Serializable` 接口

**Record 的 equals 是浅比较**——数组字段用 `==` 比较，不比较内容。如果有数组字段，需要自定义 `equals`/`hashCode`。

```java
record Pair(int[] data) {
    @Override
    public boolean equals(Object o) {
        if (this == o) return true;
        if (!(o instanceof Pair p)) return false;
        return Arrays.equals(data, p.data);  // 深比较
    }
    @Override
    public int hashCode() { return Arrays.hashCode(data); }
}
```

### Sealed Classes：控制继承（Java 17 正式）

传统 Java 中，任何类都可以继承任何非 final 类。在大型项目中这导致继承失控——你想限制一个类只能被特定类继承，但没有机制。

```java
public sealed class Shape permits Circle, Rectangle, Triangle { }

public final class Circle extends Shape { }         // final：不能再被继承
public final class Rectangle extends Shape { }      // final
public non-sealed class Triangle extends Shape { }  // non-sealed：开放继承
```

Sealed Classes 的真正威力在于和 Pattern Matching 配合——编译器能验证你是否穷举了所有子类：

```java
static double area(Shape s) {
    return switch (s) {
        case Circle c    -> Math.PI * c.radius() * c.radius();
        case Rectangle r -> r.width() * r.height();
        case Triangle t  -> 0.5 * t.base() * t.height();
        // 不需要 default——编译器知道所有子类都已处理
    };
}
```

### Pattern Matching：简化类型判断和转换（Java 16~21）

**instanceof 模式匹配（Java 16）** 把类型判断 + 强转合并为一步：

```java
// 旧写法
if (obj instanceof String) {
    String s = (String) obj;
    System.out.println(s.length());
}

// 新写法
if (obj instanceof String s) {
    System.out.println(s.length());
}
```

**switch 模式匹配（Java 21）** 支持类型匹配 + guard 条件 + Record 解构：

```java
return switch (obj) {
    case Integer i when i > 0 -> "正整数: " + i;  // guard 条件
    case String s             -> s.toUpperCase();
    case Point(int x, int y)  -> "点(" + x + "," + y + ")";  // Record 解构
    default                   -> "其他";
};
```

**注意**：模式匹配的 case 顺序敏感——具体类型必须在通用类型之前。`Integer` 必须在 `Number` 之前，否则 `Integer` 永远不会被匹配到（被 `Number` 先拦截了）。

### Virtual Threads：百万级并发（Java 21 正式）

传统平台线程（OS 线程）资源昂贵——每个线程约 1MB 栈空间，一台机器最多几千个并发。Virtual Thread 是由 JVM 管理的轻量级线程，映射到少量载体线程（carrier threads）：

```
┌──────────────────────────────────────────────────┐
│  Virtual Threads（百万级）                        │
│  VT-1  VT-2  VT-3  VT-4  ...  VT-N              │
│    │    │    │    │            │                  │
│    └────┴────┴────┴────────────┘                  │
│         │ (自动 mount/unmount)                    │
│  ┌──────┴──────┐                                  │
│  │ Carrier     │  载体线程 = 平台线程              │
│  │ Threads     │  数量 = CPU 核心数               │
│  │ (ForkJoinPool)                                  │
│  └─────────────┘                                  │
│                                                   │
│  VT 遇到 IO 阻塞 → 自动卸载，释放载体线程           │
│  IO 完成 → 自动挂载回载体线程继续执行                │
└──────────────────────────────────────────────────┘
```

**Virtual Thread 的核心优势：不需要改代码。** 现有同步代码直接在虚拟线程中运行，IO 阻塞时自动让出载体线程。Kotlin Coroutines 和 Go Goroutines 需要用 `suspend`/`async` 重写。

```java
// 一行替换线程池
try (var executor = Executors.newVirtualThreadPerTaskExecutor()) {
    IntStream.range(0, 1_000_000).forEach(i ->
        executor.submit(() -> {
            Thread.sleep(Duration.ofSeconds(1));
            return i;
        })
    );
}
// 百万个任务各 sleep 1 秒，总共约 1 秒完成
```

### Text Blocks：多行字符串（Java 15 正式）

```java
// 旧方式：转义地狱
String json = "{\n" +
    "  \"name\": \"Alice\",\n" +
    "  \"age\": 30\n" +
    "}";

// 新方式
String json = """
    {
      "name": "Alice",
      "age": 30
    }
    """;
```

Text Blocks 的缩进规则：编译器以三引号 `"""` 之后的换行到第一个非空行之间的**最小公共前导空格**作为缩进基准，自动去除。如果需要额外的缩进控制，可以用 `"""` 和内容行手动对齐。

---

## 深入原理

### Virtual Thread 的 pinning 问题

`synchronized` 块会导致载体线程被"钉住"——虚拟线程在 `synchronized` 内遇到阻塞 IO 时无法卸载，载体线程被阻塞：

```java
// ❌ 载体线程被钉住
synchronized (lock) {
    blockingIO();  // 载体线程阻塞，其他虚拟线程无法使用
}

// ✅ 用 ReentrantLock 替代
private final ReentrantLock lock = new ReentrantLock();
lock.lock();
try {
    blockingIO();  // 虚拟线程正常卸载
} finally {
    lock.unlock();
}
```

**成因**：`synchronized` 的 monitor 机制与 JVM 的载体线程绑定，而 `ReentrantLock` 的等待队列是纯 Java 实现，不依赖载体线程状态。JDK 团队计划在后续版本中修复 `synchronized` 的 pinning 问题，但当前（JDK 21）仍需注意。

### Record 的紧凑构造器

Record 允许在构造器中添加验证逻辑，但使用的是"紧凑构造器"——没有参数列表（因为参数已经在 Record 头部声明了）：

```java
public record Age(int value) {
    public Age {  // 紧凑构造器——参数列表省略
        if (value < 0 || value > 150) {
            throw new IllegalArgumentException("Invalid age: " + value);
        }
    }
    // 可以在紧凑构造器中重新赋值参数——编译器会在隐式生成的
    // 构造器中插入这些赋值语句
}
```

### Java 各版本演进一览

| 版本 | 关键特性 | 解决的痛点 |
|------|---------|-----------|
| Java 7 | try-with-resources、diamond `<>`、switch String | 资源泄漏、类型冗余 |
| Java 8 | Lambda、Stream、Optional、默认方法 | 样板代码、null 安全 |
| Java 9 | 模块系统（JPMS）、`List.of()` 不可变集合、接口私有方法 | 依赖管理、不可变集合 |
| Java 10 | `var` 局部变量推断 | 泛型嵌套的类型冗余 |
| Java 11 | `String.isBlank()`/`lines()`/`strip()`、`Files.readString()` | 字符串/文件操作 API 老化 |
| Java 14 | `switch` 表达式正式、增强 NPE 信息 | switch 赋值繁琐、NPE 无定位信息 |
| Java 16 | Records、instanceof 模式匹配正式 | DTO 样板代码、类型判断+强转 |
| Java 17 | Sealed Classes 正式、强封装 JDK 内部 API | 继承失控、反射安全性 |
| Java 21 | Virtual Threads、switch 模式匹配正式、Record Patterns、Sequenced Collections | 线程昂贵、模式匹配完整性 |
| Java 22~23 | Stream Gatherers、Foreign Function & Memory API、Structured Concurrency | 自定义中间操作、替代 JNI、并发任务管理 |

---

## 正确使用方式

### Optional 链式调用

```java
// 经典链式模式：逐层提取，安全处理 null
return findUser(id)
    .map(User::getName)
    .filter(name -> name.length() > 0)
    .orElse("unknown");

// 避免的写法
if (opt.isPresent()) {       // 这是把 null 检查换了个写法
    return opt.get();         // 如果忘记 isPresent 检查就 NPE
}
```

### Record + Sealed Classes 的黄金组合

```java
// 领域模型 + 穷举匹配 = 编译期保证完备性
public sealed interface Expr permits Num, Add, Mul { }
public record Num(int value) implements Expr { }
public record Add(Expr left, Expr right) implements Expr { }
public record Mul(Expr left, Expr right) implements Expr { }

// 编译器保证所有子类都被处理
static int eval(Expr e) {
    return switch (e) {
        case Num n -> n.value();
        case Add a -> eval(a.left()) + eval(a.right());
        case Mul m -> eval(m.left()) * eval(m.right());
    };
}
```

### Virtual Thread 使用规范

1. **IO 密集型**（HTTP 请求、数据库查询、文件读写）→ 直接替换线程池，业务代码不用改
2. **CPU 密集型**（计算任务）→ 没有优势，用平台线程或 ForkJoinPool
3. `synchronized` → 换成 `ReentrantLock`（避免 pinning）
4. `ThreadLocal` → 谨慎使用（百万虚拟线程各持一份可能导致内存问题），考虑用 Scoped Values 替代
5. **不要缓存虚拟线程**——创建成本极低，用完即弃，不需要线程池

---

## 边界情况和坑

### 坑 1：`orElse` 总是求值

```java
Optional<String> opt = Optional.of("value");

// createDefault() 总是被调用，即使 opt 有值
String a = opt.orElse(createDefault());     // createDefault() 执行了！

// 只在为空时调用
String b = opt.orElseGet(() -> createDefault());  // createDefault() 没执行
```

当 `createDefault()` 涉及数据库查询或网络请求时，用 `orElse` 会导致每次调用都执行昂贵操作。

### 坑 2：Record 的数组字段浅比较

如上所述，Record 自动生成的 `equals` 对数组字段用 `==` 比较。如果有数组、集合等引用类型字段，必须自定义 `equals`/`hashCode`。

### 坑 3：Pattern Matching 的 case 顺序

```java
switch (obj) {
    case Number n -> "数字";     // ❌ 编译错误！Number 在 Integer 前面
    case Integer i -> "整数";     // 永远不会到达
}

// 正确：具体类型在前
switch (obj) {
    case Integer i -> "整数";
    case Number n -> "数字";
    default -> "其他";
}
```

### 坑 4：Text Blocks 的尾随空格

Text Blocks 会保留行尾空格（除了缩进），如果某些行需要尾随空格，用 `\s` 转义：

```java
String text = """
    line1\s
    line2
    """;
// "line1   \nline2\n" — line1 后面有空格
```

### 坑 5：`List.of()` 不可变且不允许 null

Java 9 的 `List.of()`、`Set.of()`、`Map.of()` 返回不可变集合，且**不允许 null 元素**：

```java
List.of("a", null, "b");  // NullPointerException

// 需要可变集合或有 null 元素时，用 new ArrayList<>() 或 Stream 过滤 null
List<String> list = items.stream()
    .filter(Objects::nonNull)
    .collect(Collectors.toList());
```

### 坑 6：Virtual Thread 中 synchronized 导致 pinning

这个问题在前面深入原理中已详细说明。简而言之：在虚拟线程中使用 `synchronized` 包裹阻塞 IO 操作会导致载体线程被钉住，降低整体吞吐量。在 IO 密集型应用中（这是虚拟线程的主要场景），这会严重影响性能。
