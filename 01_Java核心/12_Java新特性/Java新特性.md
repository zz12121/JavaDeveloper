# Java新特性

> Java 新特性不是「炫技清单」，是 Java 在语言层面解决实际问题的演进记录。每个特性的出现都有明确的痛点背景——理解"为什么要加这个"，比记住"怎么用"重要得多。

---

## 这个问题为什么存在？

Java 从 1995 年诞生到 2024 年已经发布了 30 多个大版本。**每个版本新增的特性都对应着当时的行业痛点**：

| 时期 | 版本范围 | 核心主题 |
|------|---------|---------|
| 早期 | Java 5~6 | 注解、泛型、枚举——让语言更强类型化 |
| 中期 | Java 7~8 | Lambda、Stream、try-with-resources——函数式革命 |
| 现代 | Java 9~11 | 模块化、var、HTTP Client——现代化基础设施 |
| 近期 | Java 14~21 | Records、Sealed Classes、Pattern Matching、Virtual Threads——声明式 + 轻量并发 |

**理解新特性的关键视角：Java 不是在追潮流，而是在解决真实的开发痛点。** 比如 Records 不是为了"好看"，是为了消除 Lombok 和样板代码；Virtual Threads 不是为了"高性能"，是为了让开发者不用操心线程池大小。

---

## 它是怎么解决问题的？

### Lambda 与函数式接口（Java 8）

**痛点**：在 Java 8 之前，传递一段"行为"需要写匿名内部类——5 行代码只有 1 行是实际逻辑。

```java
// Java 7：匿名内部类
Collections.sort(list, new Comparator<String>() {
    @Override
    public int compare(String a, String b) {
        return a.length() - b.length();
    }
});

// Java 8：Lambda
Collections.sort(list, (a, b) -> a.length() - b.length());

// Java 8：方法引用
Collections.sort(list, Comparator.comparingInt(String::length));
```

**函数式接口** = 只有一个抽象方法的接口（SAM），用 `@FunctionalInterface` 注解标记（非强制，但推荐）：

```
JDK 内置的核心函数式接口：

Consumer<T>       — void accept(T t)         消费一个值
Supplier<T>       — T get()                   提供一个值
Function<T,R>     — R apply(T t)              转换
Predicate<T>      — boolean test(T t)         判断
BiFunction<T,U,R> — R apply(T t, U u)         双参数转换
UnaryOperator<T>  — T apply(T t)              一元运算
BinaryOperator<T> — T apply(T t1, T t2)       二元运算
```

```
Lambda 的实现原理：
Lambda 不是匿名内部类的语法糖——它底层用的是 invokedynamic。
编译时生成一个私有静态方法 + invokedynamic 指令，
运行时由 LambdaMetafactory 动态生成实现类。

好处：
1. 不产生匿名内部类的 .class 文件
2. JVM 可以在运行时优化（内联等）
3. 捕获的变量如果没变化，不会每次都创建新对象
```

### Stream API（Java 8）

**痛点**：集合操作（过滤、映射、聚合）需要写大量 for 循环和临时变量，代码既冗长又不直观。

```java
// 找出名字以"A"开头、年龄大于20的用户，按年龄排序，取前3个名字
List<String> names = users.stream()
    .filter(u -> u.getName().startsWith("A"))
    .filter(u -> u.getAge() > 20)
    .sorted(Comparator.comparingInt(User::getAge))
    .limit(3)
    .map(User::getName)
    .collect(Collectors.toList());
```

```
Stream 的核心设计理念：
1. 声明式——描述"要什么"，而不是"怎么做"
2. 惰性求值——中间操作（filter/map/sorted）不执行，遇到终端操作才执行
3. 单次消费——Stream 只能遍历一次，第二次会报 IllegalStateException
4. 内部迭代——迭代逻辑由 Stream 框架控制，可以利用并行优化

流 vs for 循环的选择：
- 简单遍历、需要索引、需要修改集合 → for 循环
- 链式转换、聚合操作、代码可读性优先 → Stream
- 性能差异通常可以忽略，除非数据量极大
```

**Stream 常见陷阱**：

```java
// 陷阱1：foreach 有副作用
list.stream()
    .filter(x -> x > 0)
    .forEach(x -> externalList.add(x));  // 不推荐，违背声明式理念

// 正确：用 collect
List<Integer> result = list.stream()
    .filter(x -> x > 0)
    .collect(Collectors.toList());

// 陷阱2：装箱开销
List<Integer> result = intList.stream()
    .boxed()
    .collect(Collectors.toList());  // 每个 int 都装箱为 Integer

// 大数据量时用 IntStream/LongStream/DoubleStream 避免装箱
IntSummaryStatistics stats = intList.stream()
    .mapToInt(x -> x)
    .summaryStatistics();
```

### Optional（Java 8）

**痛点**：NullPointerException 是 Java 最常见的异常，根源在于方法的返回值可能是 null，但调用方不知道。

```java
// 不好：返回 null
public User findUser(Long id) {
    return userMap.get(id);  // 可能返回 null
}
// 调用方忘记判空 → NPE

// 好：返回 Optional
public Optional<User> findUser(Long id) {
    return Optional.ofNullable(userMap.get(id));
}
```

```
Optional 的正确用法：
1. 作为方法返回值，明确表示"可能没有"
2. 用 orElse / orElseGet / orElseThrow 处理空值

Optional 的错误用法：
1. 用 Optional 作为方法参数 → 不要这么做，增加了调用复杂度
2. 用 isPresent() + get() 代替 null 检查 → 这是把 null 检查换了个写法
3. 用 Optional 作为字段 → Optional 不实现 Serializable，影响序列化

User user = findUser(id).orElse(new User());        // 默认值
User user = findUser(id).orElseGet(User::new);      // 延迟创建（推荐）
User user = findUser(id).orElseThrow();              // 没有 → 抛异常
findUser(id).ifPresent(u -> System.out.println(u));  // 有才处理
```

### var 局部变量类型推断（Java 10）

**痛点**：泛型嵌套时类型声明极其冗长。

```java
// Java 9：类型声明很长
Map<String, List<Map<String, Integer>>> map = new HashMap<>();

// Java 10：var 推断
var map = new HashMap<String, List<Map<String, Integer>>>();
```

```
var 的限制：
1. 只能用于局部变量，不能用于字段、方法参数、返回类型
2. 必须有初始化器（编译器需要从中推断类型）
3. 不能初始化为 null（无法推断）
4. Lambda 表达式需要显式类型时不能用 var

var 适用场景：泛型嵌套、try-with-resources、长类名
var 不适用场景：简单类型（var x = 5 反而降低了可读性）
```

### Records（Java 16 正式）

**痛点**：Java 中大量 DTO/POJO 类充斥着样板代码（getter/setter/equals/hashCode/toString）。

```java
// Java 15 之前：一个简单的数据类需要 40+ 行
public class Point {
    private final int x;
    private final int y;

    public Point(int x, int y) { this.x = x; this.y = y; }
    public int x() { return x; }
    public int y() { return y; }
    @Override public boolean equals(Object o) { /* ... */ }
    @Override public int hashCode() { /* ... */ }
    @Override public String toString() { /* ... */ }
}

// Java 16：一行搞定
public record Point(int x, int y) {}
```

```
Records 的设计要点：
1. 字段是 final 的——不可变
2. 自动生成：构造器、访问器（x() 不是 getX()）、equals、hashCode、toString
3. 可以自定义紧凑构造器来验证参数：
   public record Age(int value) {
       public Age {  // 紧凑构造器，没有参数列表
           if (value < 0 || value > 150) throw new IllegalArgumentException();
       }
   }
4. 可以实现接口，不能继承类（隐式继承 java.lang.Record）
5. 不能声明可变字段

Records vs Lombok @Data：
- Records 是语言层面的支持，不可变，更安全
- Lombok @Data 是编译期注解处理，可变，但缺少对 null 的防御
- 新项目优先用 Records
```

### Sealed Classes（Java 17 正式）

**痛点**：继承在大型项目中难以控制。你想限制一个类只能被特定类继承，但 Java 没有提供这种机制。

```java
// 定义密封类——明确指定允许哪些子类
public sealed class Shape
    permits Circle, Rectangle, Triangle { }

public final class Circle extends Shape { }        // final：不能再被继承
public final class Rectangle extends Shape { }     // final
public non-sealed class Triangle extends Shape { } // non-sealed：开放继承

// 现在可以穷举所有子类——模式匹配编译器能做穷举检查
static double area(Shape s) {
    return switch (s) {
        case Circle c -> Math.PI * c.radius() * c.radius();
        case Rectangle r -> r.width() * r.height();
        case Triangle t -> 0.5 * t.base() * t.height();
        // 不需要 default——编译器知道所有子类
    };
}
```

```
Sealed Classes 的三个关键字：
- sealed：密封类，声明允许的子类列表
- permits：列出允许的子类
- 子类必须用以下之一修饰：final / sealed / non-sealed

应用场景：
1. 领域模型——限制状态机的状态类型
2. AST（抽象语法树）——每种节点类型有限且明确
3. API 设计——对外暴露接口但控制实现类
```

### Pattern Matching（Java 16~21）

**instanceof 模式匹配（Java 16 正式）**：

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

**switch 模式匹配（Java 21 正式）**：

```java
// 类型模式
static String formatter(Object obj) {
    return switch (obj) {
        case Integer i -> String.format("int %d", i);
        case Long l    -> String.format("long %d", l);
        case Double d  -> String.format("double %f", d);
        case String s  when s.length() > 5 -> "长字符串: " + s;  // guard 条件
        case String s  -> String.format("String %s", s);
        default        -> obj.toString();
    };
}
```

**Record 模式解构（Java 21 正式）**：

```java
// 直接解构 Record 的组件
static void printPoint(Object obj) {
    if (obj instanceof Point(int x, int y)) {
        System.out.println("x=" + x + ", y=" + y);
    }
}

// switch 中解构
return switch (shape) {
    case Point(int x, int y) -> "点(" + x + "," + y + ")";
    case Circle(var r)       -> "圆 r=" + r;
    default                  -> "未知形状";
};
```

### Virtual Threads（虚拟线程，Java 21 正式）

**痛点**：传统平台线程（OS 线程）资源昂贵——每个线程占用约 1MB 栈空间，一台机器最多支撑几千个并发线程。线程池虽然复用线程，但需要开发者手动管理池大小和任务排队。

```java
// 旧方式：平台线程 + 线程池
ExecutorService pool = Executors.newFixedThreadPool(200);

// 新方式：虚拟线程——轻松创建百万级
try (var executor = Executors.newVirtualThreadPerTaskExecutor()) {
    IntStream.range(0, 1_000_000).forEach(i -> {
        executor.submit(() -> {
            Thread.sleep(Duration.ofSeconds(1));
            return i;
        });
    });
}
// 百万个任务，每个 sleep 1秒，总共只需 ~1秒完成
```

```
虚拟线程的核心原理：
1. 虚拟线程是由 JVM 管理的轻量级线程，映射到少量载体线程（carrier threads）
2. 当虚拟线程遇到阻塞操作（IO、sleep）时，自动"卸载"（unmount），
   释放载体线程去执行其他虚拟线程
3. 阻塞结束后自动"挂载"（mount）回载体线程继续执行

虚拟线程 vs 平台线程：
- 创建成本：极低 vs 高（OS 级别）
- 内存占用：几百字节 ~ 几 KB vs ~1MB 栈
- 数量级：百万级 vs 几千级
- 适用场景：IO 密集型（HTTP 请求、数据库查询、文件读写）
- 不适用场景：CPU 密集型（计算任务——虚拟线程不会比平台线程更快）

Virtual Thread 不需要线程池的原因：
既然创建成本极低，就不需要复用——每个任务一个虚拟线程即可。
```

```
注意事项：
1. synchronized 在虚拟线程中可能导致载体线程"钉住"（pinning），
   用 ReentrantLock 替代
2. ThreadLocal 在虚拟线程中要谨慎使用——百万虚拟线程各持一份 ThreadLocal
   可能导致内存问题
3. 虚拟线程不支持设置优先级
4. 不应该缓存虚拟线程（不像平台线程池）
```

### Text Blocks（文本块，Java 15 正式）

```java
// 旧方式：字符串拼接或转义
String json = "{\n" +
    "  \"name\": \"Alice\",\n" +
    "  \"age\": 30\n" +
    "}";

// 新方式：三引号文本块
String json = """
    {
      "name": "Alice",
      "age": 30
    }
    """;
```

### 其他重要特性速览

```
Java 7：
- try-with-resources：自动关闭资源
- diamond operator：Map<String, List<Integer>> map = new HashMap<>();
- switch 支持 String
- multi-catch

Java 9：
- 模块系统（Jigsaw）：强封装，控制依赖
- 接口私有方法
- 集合工厂方法：List.of()、Set.of()、Map.of()
- HTTP Client（孵化）

Java 11（LTS）：
- 字符串新方法：isBlank()、lines()、strip()、repeat()
- 文件操作：Files.readString()、Files.writeString()
- HTTP Client 正式
- 单文件源代码直接运行：java Hello.java（无需先 javac）

Java 12~13：
- switch 表达式（预览）
- 文本块（预览）

Java 14：
- switch 表达式正式
- NullPointerException 增强信息：告诉你是哪行哪个变量为 null
- instanceof 模式匹配（预览）

Java 15：
- 文本块正式
- Records（预览 → 正式）、Sealed Classes（预览）
- Hidden Classes

Java 17（LTS）：
- Sealed Classes 正式
- 模式匹配 instanceof 正式
- 强封装 JDK 内部 API（--illegal-access 默认 deny）
- 新的伪随机数生成器

Java 21（LTS）：
- Virtual Threads 虚拟线程正式
- Pattern Matching for switch 正式
- Record Patterns 正式
- Sequenced Collections（有序集合统一接口）
- String Templates（预览）
- Generational ZGC

Java 22~23：
- Stream Gatherers（自定义中间操作）
- Statements before super()（允许在 super() 之前写语句）
- Flexible Constructor Bodies（构造器体灵活化）
- Implicitly Declared Classes（简化 Hello World）
- Foreign Function & Memory API（替代 JNI）
- Structured Concurrency（结构化并发，预览）
- Scoped Values（作用域值，预览）
```

---

## 和相似方案的区别

### Java Lambda vs 匿名内部类

| 维度 | Lambda | 匿名内部类 |
|------|--------|-----------|
| 代码量 | 简洁 | 冗长 |
| this 指向 | 外部类的 this | 内部类自己的 this |
| 可以捕获的变量 | effectively final | effectively final |
| 生成的类文件 | 无（invokedynamic） | 有 Outer$1.class |
| 可用范围 | 仅函数式接口 | 任意接口/抽象类 |

### Java Records vs Kotlin Data Class

| 维度 | Java Records | Kotlin data class |
|------|-------------|-------------------|
| 语法 | `record Point(int x, int y)` | `data class Point(val x: Int, val y: Int)` |
| 可变性 | 强制不可变 | 默认可变（加 val 不可变） |
| 解构 | switch 模式匹配 | `val (x, y) = point` |
| 继承 | 不能继承类，可实现接口 | 可继承（open class） |
| 空安全 | 无语言级支持 | 内置 null safety |

### Java Virtual Threads vs Kotlin Coroutines vs Go Goroutines

| 维度 | Java VT | Kotlin Coroutines | Go Goroutines |
|------|---------|-------------------|---------------|
| 实现层 | JVM 层 | 编译器 + 库 | 运行时 |
| 模型 | M:N | M:N | M:N |
| 阻塞处理 | 自动卸载 | suspend 函数 | 自动调度 |
| 语法 | 几乎无需改代码 | suspend/launch/async | go 关键字 |
| 学习成本 | 极低（写法不变） | 中等（新概念多） | 低 |
| 生态兼容 | 完全兼容现有同步代码 | 需要异步库配合 | 需要异步库配合 |

```
Virtual Thread 的核心优势：不需要改代码。
现有同步代码直接在虚拟线程中运行，IO 阻塞时自动让出载体线程。
Kotlin Coroutines 和 Go 需要用 async/await 或 channel 重写。
```

---

## 正确使用方式

### 1. Lambda / Stream 的使用原则

```
1. Stream 操作链不宜过长（3~5 个操作最佳），太长拆成方法
2. 避免在 Stream 中有副作用（修改外部变量）
3. 并行流 parallelStream() 只在 CPU 密集 + 大数据量时考虑
   IO 场景不要用并行流（可能阻塞公共 ForkJoinPool）
4. 纯数据转换用 Stream，需要控制流/异常处理用 for 循环
```

### 2. Optional 使用规范

```
1. 作为方法返回值 ✓，方法参数 ✗，字段 ✗
2. 优先用 orElseGet() 而非 orElse()——避免不必要的对象创建
3. 不要用 isPresent() + get()，用 ifPresent()、orElse()、map()
4. 链式调用：
   return findUser(id)
       .map(User::getName)
       .filter(name -> name.length() > 0)
       .orElse("unknown");
```

### 3. Record 使用规范

```
1. 只用于纯数据载体——没有行为逻辑的类
2. 需要可变字段 → 不要用 Record，用普通类
3. 需要继承其他类 → Record 不能继承（只能实现接口）
4. Record + Sealed Classes 是黄金组合——类型安全 + 穷举匹配
```

### 4. Virtual Thread 使用规范

```
1. IO 密集型场景 → 直接替换线程池，不用改业务代码
2. CPU 密集型场景 → 没有优势，用平台线程或 ForkJoinPool
3. synchronized → 换成 ReentrantLock（避免 pinning）
4. ThreadLocal → 谨慎使用，考虑用 Scoped Values 替代
5. 不要缓存虚拟线程——创建成本极低，用完即弃
6. 用 StructuredTaskScope 管理并发子任务的生命周期（预览 API）
```

---

## 边界情况和坑

### 1. Stream 的惰性求值陷阱

```java
Stream<Integer> stream = list.stream().filter(x -> {
    System.out.println("filter: " + x);
    return x > 0;
});
// 此时什么都不会打印——filter 是惰性的，没有终端操作

stream.count();  // 这时才会触发整个流水线执行
```

### 2. Lambda 中的异常处理

```java
// Lambda 中不能直接抛 checked exception
list.forEach(s -> Files.readString(Path.of(s)));  // 编译错误

// 解决方案1：try-catch 包装
list.forEach(s -> {
    try { Files.readString(Path.of(s)); }
    catch (IOException e) { throw new RuntimeException(e); }
});

// 解决方案2：提取为辅助方法
list.forEach(this::readFileUnsafe);

// 解决方案3：自定义函数式接口
@FunctionalInterface
interface ThrowingConsumer<T> {
    void accept(T t) throws Exception;
    static <T> Consumer<T> unchecked(ThrowingConsumer<T> c) {
        return t -> { try { c.accept(t); } catch (Exception e) { throw new RuntimeException(e); } };
    }
}
list.forEach(ThrowingConsumer.unchecked(s -> Files.readString(Path.of(s))));
```

### 3. Optional 的 orElse vs orElseGet

```java
Optional<String> opt = Optional.of("value");

// orElse：无论 Optional 是否为空，都会执行参数表达式
String a = opt.orElse(createDefault());  // createDefault() 会被调用！

// orElseGet：只在 Optional 为空时才执行
String b = opt.orElseGet(() -> createDefault());  // createDefault() 不会被调用
```

当默认值创建成本低（如 `orElse("default")`），两者无区别。当默认值创建涉及 IO、数据库查询等昂贵操作时，**必须用 orElseGet**。

### 4. Record 的 equals 是浅比较

```java
record Pair(int[] data) {}

var a = new Pair(new int[]{1, 2, 3});
var b = new Pair(new int[]{1, 2, 3});
a.equals(b);  // false！数组用 == 比较，不比较内容

// 需要深比较的字段，自定义 equals
record Pair(int[] data) {
    @Override
    public boolean equals(Object o) {
        if (this == o) return true;
        if (!(o instanceof Pair p)) return false;
        return Arrays.equals(data, p.data);
    }
    @Override
    public int hashCode() { return Arrays.hashCode(data); }
}
```

### 5. Virtual Thread 的 pinning 问题

```java
// synchronized 块会导致载体线程被"钉住"——虚拟线程无法卸载
synchronized (lock) {
    blockingIO();  // 载体线程被阻塞，其他虚拟线程也受影响
}

// 正确：用 ReentrantLock 替代
private final ReentrantLock lock = new ReentrantLock();
lock.lock();
try {
    blockingIO();  // 虚拟线程正常卸载，载体线程去执行其他任务
} finally {
    lock.unlock();
}
```

### 6. Text Blocks 的缩进陷阱

```java
String html = """
        <html>
            <body>Hello</body>
        </html>
        """;
// 开头的空格会被计入——需要右对齐到最左边的非空行

// 编译器将 """ 后面换行到第一个非空行的公共前导空格作为缩进基准
// 实际结果：<html>\n    <body>Hello</body>\n</html>
```

### 7. Pattern Matching 的顺序敏感

```java
// 子类型必须在父类型之前
switch (obj) {
    case Number n -> "数字";     // 编译错误！Number 是 Integer 的父类型
    case Integer i -> "整数";
}
// 正确：具体类型在前，通用类型在后
switch (obj) {
    case Integer i -> "整数";
    case Number n -> "数字";
    default -> "其他";
}
```

---

## 我的理解

Java 新特性反映了一个趋势：**Java 从"啰嗦但安全"向"简洁但不妥协安全"演进**。

- Java 8 的 Lambda/Stream 解决了样板代码问题
- Java 10 的 var 减少了冗余的类型声明
- Java 16 的 Records 消灭了 DTO 的样板代码
- Java 17 的 Sealed Classes + Pattern Matching 实现了类型安全的穷举匹配
- Java 21 的 Virtual Threads 彻底改变了 Java 并发编程的范式

**面试中关于 Java 新特性的考察重点**：

1. **Lambda 原理**：invokedynamic vs 匿名内部类（高频）
2. **Stream 惰性求值**：中间操作 vs 终端操作（高频）
3. **Optional 正确用法**：什么时候该用、什么时候不该用（中频）
4. **Virtual Threads**：原理、pining 问题、适用场景（高频，新热点）
5. **Records**：限制（不可变、不能继承）、与 Lombok 对比（中频）
6. **Sealed Classes + Pattern Matching**：设计理念、与 when 子句组合（中高频）
7. **整体演进脉络**：每个版本解决什么问题（考察广度和深度）
