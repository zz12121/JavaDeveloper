# Lambda 与函数式

> Lambda 让 Java 可以把"一段代码"当作参数传递给方法。它不是匿名内部类的语法糖——底层用的是 `invokedynamic` 指令在运行时动态生成实现类，这使得 JVM 有机会在后续版本中持续优化 Lambda 性能，而不需要修改你的代码。

---

## 这个问题为什么存在？

在 Lambda 出现之前，Java 想传递一段行为只有一种方式——匿名内部类：

```java
Collections.sort(list, new Comparator<String>() {
    @Override
    public int compare(String o1, String o2) {
        return o1.length() - o2.length();
    }
});
// 6 行模板代码，只有 1 行是业务逻辑
```

这带来三个问题：

1. **代码噪声大**：5 行模板才能包裹 1 行逻辑，在大数据处理的回调链中尤其严重
2. **无法利用多核**：Java 之前没有标准化的方式将集合操作并行化
3. **函数式编程无法落地**：Java 想引入 Stream API（声明式数据处理管道），但管道中的每个操作都需要一种简洁的方式传递"做什么"

Lambda 就是为了解决"如何把行为作为一等公民传递"这个问题而引入的。

---

## 它是怎么解决问题的？

### 语法：从冗长到简洁

```java
// 匿名内部类
new Comparator<String>() {
    @Override
    public int compare(String a, String b) {
        return a.length() - b.length();
    }
}

// Lambda
(a, b) -> a.length() - b.length()

// 方法引用（Lambda体只是调用一个方法时）
Comparator.comparing(String::length)
```

Lambda 语法由三部分组成：`(参数列表) -> { 方法体 }`。编译器根据目标类型（函数式接口）推断参数类型，单表达式可以省略 `return` 和花括号。

### 函数式接口：Lambda 的目标类型

Lambda 本身没有类型。编译器需要知道 Lambda 应该实现哪个接口，这个接口必须是**函数式接口**（只有一个抽象方法）：

```java
@FunctionalInterface  // 编译期检查：确保只有一个抽象方法
public interface Comparator<T> {
    int compare(T o1, T o2);

    default Comparator<T> reversed() { ... }  // default 方法不算
}
```

Java 内置了四组核心函数式接口：

| 接口 | 方法 | 用途 | 示例 |
|------|------|------|------|
| `Predicate<T>` | `boolean test(T)` | 判断 | `s -> s.length() > 3` |
| `Function<T,R>` | `R apply(T)` | 转换 | `String::toUpperCase` |
| `Consumer<T>` | `void accept(T)` | 消费 | `System.out::println` |
| `Supplier<T>` | `T get()` | 生产 | `() -> new User()` |
| `BiFunction<T,U,R>` | `R apply(T,U)` | 二元转换 | `(a, b) -> a + b` |
| `UnaryOperator<T>` | `T apply(T)` | 一元操作 | `x -> x * 2` |

`@FunctionalInterface` 注解不是必须的——只要接口只有一个抽象方法，就可以用 Lambda 实现。但加上注解后，如果有人不小心加了第二个抽象方法，编译器会报错。这是一种**防御性编程**。

### invokedynamic：Lambda 的底层实现

Lambda **不是**匿名内部类的语法糖。它们的字节码完全不同：

```java
// Lambda 编译后的字节码
list.forEach(s -> System.out.println(s));

// → invokedynamic #0  // 引导方法指向 LambdaMetafactory.metafactory
```

编译器不生成任何内部类文件。取而代之的是一条 `invokedynamic` 指令，指向 `LambdaMetafactory.metafactory` 作为引导方法（Bootstrap Method）。**首次调用时**，`LambdaMetafactory` 通过 `Unsafe.defineAnonymousClass` 动态生成一个实现了目标函数式接口的类：

```
首次调用时生成的类（等价伪代码）：
class Lambda$123 implements Consumer<String> {
    private final PrintStream capture$0;

    Lambda$123(PrintStream ps) { this.capture$0 = ps; }

    public void accept(String s) {
        this.capture$0.println(s);  // 直接调用，没有额外间接层
    }
}
```

后续调用直接使用已生成的类，不再经过 invokedynamic。这就是为什么 Lambda 的第一次调用比匿名内部类慢（需要生成类），但后续调用更快。

### 变量捕获：为什么必须是 effectively final

```java
int count = 0;
list.forEach(s -> count++);  // 编译错误！
```

**成因**：Lambda 捕获局部变量时，实际是**值拷贝**。如果允许修改，语义会混乱——你在 Lambda 外部改了 `count`，Lambda 内部看到的还是旧值（因为拷贝的），反之亦然。

`effectively final` 的限制把这个语义问题在编译期就拦截了。实例变量和静态变量不受此限制，因为它们存储在堆上，Lambda 通过引用访问，所有线程共享同一份数据。

---

## 深入原理

### Lambda vs 匿名内部类：五个本质区别

| 维度 | Lambda | 匿名内部类 |
|------|--------|------------|
| **this** | 指向外部类 | 指向匿名内部类自身 |
| **字节码** | `invokedynamic`，运行时生成类 | 编译期生成 `$1.class` 文件 |
| **性能** | 首次调用慢（生成类），后续快 | 首次就快，但类加载有开销 |
| **可实现的类型** | 只能是函数式接口 | 任意接口或抽象类 |
| **状态** | 无自身状态（捕获变量是拷贝） | 可以有自身字段 |

`this` 指向不同是最容易被忽略的区别：

```java
public class Demo {
    private String name = "outer";

    public void test() {
        // 匿名内部类
        new Thread(new Runnable() {
            @Override
            public void run() {
                System.out.println(this.name);     // 编译错误：Runnable 没有 name 字段
            }
        }).start();

        // Lambda
        new Thread(() -> {
            System.out.println(this.name);         // "outer"，指向 Demo 实例
        }).start();
    }
}
```

### 方法引用的四种形式

| 形式 | 语法 | 等价 Lambda |
|------|------|-------------|
| 静态方法引用 | `Math::max` | `(a, b) -> Math.max(a, b)` |
| 实例方法引用（特定对象） | `System.out::println` | `s -> System.out.println(s)` |
| 实例方法引用（任意对象） | `String::length` | `s -> s.length()` |
| 构造方法引用 | `String::new` | `() -> new String()` |

第三种形式容易混淆：`String::length` 看起来像静态方法，但 `length()` 是实例方法。编译器会将第一个参数作为方法调用者，等价于 `s -> s.length()`。判断方法是看目标类型的第一个参数是否是方法所属类。

---

## 正确使用方式

### 何时用 Lambda vs 方法引用

```java
// Lambda：有额外逻辑时
list.map(s -> {
    if (s == null) return "N/A";
    return s.toUpperCase();
})

// 方法引用：只是调用一个方法时
list.map(String::toUpperCase)           // 比上面的 Lambda 更简洁
list.forEach(System.out::println)       // 比更清晰
list.sort(Comparator.comparingInt(String::length))  // 链式调用
```

**原则**：Lambda 体只是一个方法调用时，优先用方法引用。有条件判断、异常处理或多步操作时，用 Lambda。

### 函数式接口设计实践

```java
@FunctionalInterface
public interface ResultHandler<T> {
    void handle(T result) throws Exception;

    // default 方法让接口可以演化
    default ResultHandler<T> andThen(ResultHandler<T> after) {
        return t -> { this.handle(t); after.handle(t); };
    }

    // static 工厂方法提供常用实现
    static <T> ResultHandler<T> logging() {
        return t -> System.out.println("Result: " + t);
    }
}
```

`default` 方法是 Java 8 接口演进的关键——允许在接口中新增方法而不破坏已有实现。`static` 方法提供工厂实现，减少使用处的重复代码。

---

## 边界情况和坑

### 坑 1：Lambda 的 this 指向外部类

在 [[01_Java核心/02_面向对象/内部类|内部类]] 中提到过，匿名内部类有独立的 `this`，Lambda 没有。如果你在 Lambda 中需要一个"内部状态"——比如自己维护一个计数器——Lambda 做不到（因为它不是对象），需要改用匿名内部类或其他方式。

### 坑 2：装箱开销

```java
// 慢：每次操作都装箱
int sum = list.stream()
    .map(x -> x * 2)         // int → Integer 装箱
    .reduce(0, Integer::sum); // Integer → int 拆箱

// 快：使用原始类型流
int sum = list.stream()
    .mapToInt(x -> x * 2)    // IntStream，无装箱
    .sum();
```

Java 提供了 `IntStream`、`LongStream`、`DoubleStream` 三种原始类型流来避免装箱开销。在 [[01_Java核心/08_Lambda与Stream/Stream API|Stream API]] 中还有更详细的讨论。

### 坑 3：Lambda 不能序列化

Lambda 表达式实现的类型不能被序列化（即使函数式接口继承了 `Serializable`）。如果确实需要序列化（如传递到远程服务），应该用匿名内部类或者提取为具名类。

### 坑 4：延迟执行的陷阱

Lambda 是延迟执行的——定义时不运行，被调用时才运行。这在 try-with-resources 等场景可能导致资源提前关闭：

```java
void process() throws IOException {
    try (BufferedReader reader = new BufferedReader(new FileReader("file.txt"))) {
        Stream<String> lines = reader.lines();  // 惰性
        // reader 在这里就关闭了，lines 的终止操作还没执行
    }
    // 解决：在 try 块内调用终止操作
    try (Stream<String> lines = Files.lines(Paths.get("file.txt"))) {
        lines.filter(s -> s.length() > 10).forEach(System.out::println);
    }
}
```

### 坑 5：checked exception 处理

Lambda 的函数式接口方法不允许抛 checked exception，但实际场景中经常需要：

```java
// 编译错误：Consumer.accept() 不声明 throws IOException
list.forEach(s -> Files.readString(Path.of(s)));  // IOException!

// 解法 1：用工具方法包装
list.forEach(throwingConsumer(s -> Files.readString(Path.of(s))));

static <T> Consumer<T> throwingConsumer(ThrowingConsumer<T> c) {
    return t -> { try { c.accept(t); } catch (Exception e) { throw new RuntimeException(e); } };
}

// 解法 2：自定义允许抛异常的函数式接口
@FunctionalInterface
interface ThrowingConsumer<T> {
    void accept(T t) throws Exception;
}
```
