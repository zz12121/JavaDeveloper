# Lambda与函数式

## 这个问题为什么存在？

> 从「没有这个东西会怎样」出发，解释问题的根源。

在Java 8之前，想要传递一段行为（代码）给方法，只能通过**匿名内部类**：

```java
// 没有Lambda时，想传递一个"比较大小"的行为
Collections.sort(list, new Comparator<String>() {
    @Override
    public int compare(String o1, String o2) {
        return o1.length() - o2.length();
    }
});
```

**痛点**：
1. **代码冗长**：为了传递一行逻辑，写了6行模板代码
2. **可读性差**：真正的业务逻辑淹没在语法噪声中
3. **无法利用多核**：集合的并行处理需要手动编写线程代码

**核心问题**：Java是面向对象语言，一切都是对象。但有时候我们只需要传递**行为**（一段代码），而不是创建一个完整的对象。Lambda表达式的引入，让Java支持了**行为参数化**——将代码块作为参数传递。

函数式编程的核心思想是**声明式编程**：关注"做什么"而非"怎么做"。Lambda让Java拥有了这一能力。

## 它是怎么解决问题的？

> 不止讲「是什么」，要讲清楚「为什么这样设计能解决问题」。

### 核心机制

#### Lambda表达式语法

```java
// 基础语法
(参数) -> { 表达式 }

// 示例
(a, b) -> a + b              // 两个参数，返回和
() -> System.out.println("") // 无参数
x -> x * 2                   // 单个参数，可省略括号
(x, y) -> {                  // 多行代码，需要花括号
    int sum = x + y;
    return sum;
}
```

**为什么这样设计？**
- 箭头`->`清晰地分隔**参数列表**和**方法体**
- 单表达式可省略`return`和花括号，保持简洁
- 类型推断：编译器能从上下文推断参数类型，无需显式声明

#### 函数式接口（FunctionalInterface）

```java
@FunctionalInterface  // 编译期检查：只能有一个抽象方法
public interface Comparator<T> {
    int compare(T o1, T o2);  // 唯一的抽象方法

    // default方法不计入抽象方法计数
    default Comparator<T> reversed() {
        return (a, b) -> compare(b, a);
    }

    // static方法也不计入
    static <T> Comparator<T> naturalOrder() { ... }
}
```

**为什么需要@FunctionalInterface注解？**
- 编译期保证：确保接口可以用Lambda表达式实现
- 文档作用：明确告诉使用者这是一个函数式接口
- 但如果接口只有一个抽象方法，即使没有该注解，也可以用Lambda

**Java内置的函数式接口**：
| 接口 | 方法 | 用途 |
|------|------|------|
| `Predicate<T>` | `boolean test(T t)` | 判断真假 |
| `Function<T,R>` | `R apply(T t)` | 类型转换 |
| `Consumer<T>` | `void accept(T t)` | 消费对象 |
| `Supplier<T>` | `T get()` | 生产对象 |
| `UnaryOperator<T>` | `T apply(T t)` | 一元操作 |
| `BinaryOperator<T>` | `T apply(T t1, T t2)` | 二元操作 |

#### 方法引用（Method Reference）

```java
// Lambda写法
list.forEach(s -> System.out.println(s));

// 方法引用写法（更简洁）
list.forEach(System.out::println);

// 四种方法引用类型
类名::静态方法       Math::max           // 等价于 (a, b) -> Math.max(a, b)
对象::实例方法        System.out::println  // 等价于 s -> System.out.println(s)
类名::实例方法        String::length      // 等价于 s -> s.length()
类名::new            String::new          // 等价于 () -> new String()
```

**为什么需要方法引用？**
- 当Lambda体只是调用某个方法时，方法引用更简洁
- 编译期类型检查更严格，减少运行时错误

#### Lambda的底层实现：invokedynamic

```java
// 源码
list.forEach(s -> System.out.println(s));

// 编译后的字节码（简化）
invokedynamic #0, 0  // 引导方法：LambdaMetafactory.metafactory
                     // 动态生成函数式接口的实例
```

**关键设计**：Lambda不是**匿名内部类的语法糖**！

| 维度 | Lambda | 匿名内部类 |
|------|--------|------------|
| **字节码** | invokedynamic指令 | 生成内部类文件（xxx$1.class） |
| **绑定时机** | 运行时动态生成 | 编译期生成类 |
| **性能** | 延迟绑定，可优化 | 编译期确定，无法优化 |
| **this指向** | 外部类 | 匿名内部类自身 |

**为什么用invokedynamic而不是匿名内部类？**
1. **延迟绑定**：Lambda的实现类在运行时才生成，JVM可以根据运行时信息优化
2. **减少类文件**：匿名内部类会生成额外的.class文件，Lambda不会
3. **未来优化空间**：invokedynamic让JVM可以在未来版本中优化Lambda性能，而无需修改Java代码

#### ASCII图：Lambda执行流程

```
┌─────────────────────────────────────────────────────┐
│ 源码：list.forEach(s -> System.out.println(s))       │
└─────────────────────┬───────────────────────────────┘
                      │ 编译
                      ▼
┌─────────────────────────────────────────────────────┐
│ 字节码：invokedynamic #LambdaMetafactory.metafactory│
│          │
│  引导方法（Bootstrap Method）：                      │
│  1. 生成一个实现Consumer接口的类的字节码              │
│  2. 方法体中调用System.out.println()                │
└─────────────────────┬───────────────────────────────┘
                      │ 首次调用时
                      ▼
┌─────────────────────────────────────────────────────┐
│ LambdaMetafactory.metafactory() 动态生成类           │
│          │
│  生成类似这样的类（伪代码）：                         │
│  class Lambda$1 implements Consumer<String> {        │
│      public void accept(String s) {                  │
│          System.out.println(s);                      │
│      }                                              │
│  }                                                  │
└─────────────────────┬───────────────────────────────┘
                      │ 后续调用
                      ▼
┌─────────────────────────────────────────────────────┐
│ 直接调用已生成的类，无需再次invokedynamic            │
└─────────────────────────────────────────────────────┘
```

### 变量捕获（Variable Capture）

```java
int localVar = 10;  // 局部变量
list.forEach(s -> System.out.println(s + localVar));
// 编译错误：localVar必须是final或effectively final

// effectively final：虽然没有显式声明final，但未被修改
int count = 0;
list.forEach(s -> System.out.println(count));  // OK
count = 1;  // 修改后，不再是effectively final
list.forEach(s -> System.out.println(count));  // 编译错误
```

**为什么Lambda只能捕获final或effectively final的变量？**
- **一致性**：Lambda可能在另一个线程执行，如果局部变量可变，无法保证内存可见性
- **实现简化**：Lambda捕获的变量实际上是**值拷贝**，如果允许修改，会导致"修改无效"的混乱语义
- **与匿名内部类一致**：匿名内部类也有同样限制

**实例变量无此限制**：
```java
private int instanceVar = 10;  // 实例变量
list.forEach(s -> System.out.println(s + instanceVar));  // OK
// 因为实例变量存储在堆中，所有线程共享，无可见性问题
```

### 类型推断与上下文

```java
// 编译器根据上下文推断Lambda参数类型
Predicate<String> p = s -> s.isEmpty();  // s被推断为String

// 无法推断时，需要显式声明类型
// Callable<String> c = () -> "hello";  // OK
// 但复杂场景可能需要显式类型
```

**为什么需要上下文？**
- Lambda本身没有类型信息，它的类型由**目标类型**（赋值目标或方法参数类型）决定
- 这也是为什么Lambda只能用于函数式接口——需要唯一抽象方法来确定参数类型和返回类型

## 它和相似方案的本质区别是什么？

> 对比不是列表，要解释「为什么选 A 不选 B」。

### Lambda vs 匿名内部类

**本质区别**：Lambda是**行为参数化**，匿名内部类是**对象创建**。

| 维度 | Lambda | 匿名内部类 |
|------|--------|------------|
| **语法** | 简洁，`(a, b) -> a + b` | 冗长，需要new接口+实现方法 |
| **this指向** | 外部类 | 匿名内部类自身 |
| **字节码** | invokedynamic，运行时生成 | 编译期生成xxx$1.class |
| **性能** | 首次调用稍慢（需生成类），后续快 | 首次就确定，但类加载有开销 |
| **变量捕获** | 只能捕获final/effectively final | 同理，但可修改this的成员 |
| **适用场景** | 函数式接口 | 任意接口或抽象类 |

**为什么选Lambda不选匿名内部类？**
- **可读性**：Lambda更贴近"传递行为"的语义
- **性能**：invokedynamic让JVM有机会优化（虽然首次调用慢）
- **未来兼容**：Java后续版本对Lambda的优化不会影响代码

**匿名内部类的优势**：
- 可以实现**多个方法**的接口，Lambda只能实现一个方法的接口
- 可以**显式继承自某个类**，Lambda不行

### 函数式接口 vs 普通接口

```java
// 函数式接口：只有一个抽象方法
@FunctionalInterface
interface MyFunc {
    void doSomething();
}

// 普通接口：多个抽象方法
interface MyNormal {
    void method1();
    void method2();
}
```

**为什么需要函数式接口？**
- Lambda表达式需要**目标类型**，函数式接口提供了这个类型
- 如果接口有多个抽象方法，Lambda无法知道要实现哪一个

**@FunctionalInterface的作用**：
- 编译期检查：确保接口可以用Lambda实现
- 但它不是必须的，只要接口只有一个抽象方法，就是函数式接口

### 方法引用 vs Lambda

```java
// Lambda：更灵活，可以有额外逻辑
list.forEach(s -> {
    System.out.println(s);
    // 可以做其他事
});

// 方法引用：更简洁，但只能调用方法
list.forEach(System.out::println);
```

**为什么选方法引用？**
- **简洁性**：当Lambda体只是调用一个方法时，方法引用更清晰
- **编译期检查**：方法引用的参数类型和返回类型在编译期检查，Lambda的类型推断可能在运行时才报错

**为什么选Lambda？**
- **灵活性**：方法引用只能调用已存在的方法，Lambda可以包含任意逻辑
- **可读性**：复杂逻辑用Lambda更清晰，方法引用可能降低可读性（如`String::new`不如`() -> new String()`清晰）

## 正确使用方式

> 不是 API 手册，要解释「为什么这样用是对的」。

### 定义函数式接口的正确方式

```java
/**
 * 正确的函数式接口定义
 */
@FunctionalInterface  // 1. 添加注解，编译期检查
public interface ResultHandler<T> {
    // 2. 只有一个抽象方法
    void handle(T result) throws Exception;

    // 3. 提供default方法，增强接口功能
    default ResultHandler<T> andThen(ResultHandler<T> after) {
        return (t) -> {
            this.handle(t);
            after.handle(t);
        };
    }

    // 4. 提供static工厂方法
    static <T> ResultHandler<T> noop() {
        return t -> {};  // 空操作
    }
}
```

**为什么这样设计？**
- `@FunctionalInterface`确保接口可以用Lambda实现
- default方法让接口可以**演化**，新增方法不破坏现有实现
- static工厂方法提供常用的Lambda实现，减少重复代码

### 使用Lambda的正确场景

```java
// 1. 集合操作：过滤、映射、聚合
List<String> result = list.stream()
    .filter(s -> s.length() > 5)  // 过滤
    .map(String::toUpperCase)       // 映射
    .collect(Collectors.toList());  // 聚合

// 2. 回调函数
CompletableFuture.supplyAsync(() -> queryFromDb())  // 异步任务
    .thenAccept(result -> process(result));         // 回调

// 3. 比较器
list.sort((a, b) -> a.length() - b.length());

// 4. 线程任务
new Thread(() -> {
    System.out.println("Running in thread");
}).start();
```

**为什么这样用是对的？**
- Lambda让**行为参数化**变得自然，代码更简洁
- 配合Stream API，可以用声明式方式处理集合
- 配合CompletableFuture，可以用函数式风格编写异步代码

### 避免Lambda的常见误用

```java
// 错误1：在Lambda中修改外部变量
int count = 0;
list.forEach(s -> count++);  // 编译错误

// 错误2：Lambda体过于复杂
list.forEach(s -> {
    // 20行逻辑！应该用方法引用或提取方法
    ...
});

// 错误3：滥用Lambda，降低可读性
// 不好的写法
Function<String, Integer> f = s -> {
    if (s == null) return 0;
    return s.length();
};

// 好的写法：提取方法
Function<String, Integer> f = this::safeLength;

// 错误4：并行流中的副作用
// 不安全的并行
List<Integer> result = new ArrayList<>();
list.parallelStream().forEach(i -> result.add(i));  // 并发修改异常！

// 安全的并行
List<Integer> result = list.parallelStream()
    .collect(Collectors.toList());  // 使用 collect
```

## 边界情况和坑

> 不是列举，要解释「坑的成因」。

### 坑1：this指向不同

```java
public class Test {
    private String name = "outer";

    public void method() {
        // 匿名内部类：this指向匿名内部类实例
        new Thread(new Runnable() {
            private String name = "inner";
            @Override
            public void run() {
                System.out.println(this.name);  // "inner"
                System.out.println(Test.this.name);  // "outer"（访问外部类）
            }
        }).start();

        // Lambda：this指向外部类
        new Thread(() -> {
            System.out.println(this.name);  // "outer"
            // System.out.println(Lambda.this.name);  // 编译错误，没有Lambda.this
        }).start();
    }
}
```

**成因**：Lambda不是对象，它没有自己的`this`，它只是**代码块**。匿名内部类是对象，有自己的`this`。

### 坑2：变量捕获的值拷贝

```java
int x = 10;
list.forEach(s -> System.out.println(x));  // OK，x是effectively final

// 但x实际上是值拷贝，修改x不会影响Lambda
int x = 10;
Runnable r = () -> System.out.println(x);
x = 20;  // 编译错误：x不再是effectively final
```

**成因**：Lambda捕获局部变量时，实际上是**复制值**。如果允许修改，会导致"修改无效"的语义混乱。

### 坑3：Lambda的延迟执行

```java
list.forEach(s -> {
    System.out.println("Processing: " + s);
    // 这行代码在forEach执行时才会运行
});

// 对比：直接调用
System.out.println("Processing: " + s);  // 立即执行
```

**成因**：Lambda是**延迟执行**的，它只在被调用时才执行。这也是为什么Lambda适合作为回调函数——它定义了"将来要做的事"。

### 坑4：并行流中的线程安全问题

```java
// 不安全的并行流操作
List<String> result = new ArrayList<>();
list.parallelStream().forEach(s -> result.add(s));  // 并发修改异常！

// 解决方案1：使用线程安全的集合
List<String> result = Collections.synchronizedList(new ArrayList<>());
list.parallelStream().forEach(s -> result.add(s));

// 解决方案2：使用collect（推荐）
List<String> result = list.parallelStream()
    .collect(Collectors.toList());
```

**成因**：`forEach`中的Lambda可能在多个线程同时执行，`ArrayList`不是线程安全的。

### 坑5：Lambda的序列化问题

```java
// Lambda表达式不能被序列化！
SerializableRunnable r = () -> System.out.println("hello");
// 编译错误：Lambda表达式不能强制转换为Serializable

// 解决方案：使用闭包序列化工具（如Apache Commons Lang）
```

**成因**：Lambda没有名字，序列化时需要存储"如何重建这个Lambda"的信息，但Java的序列化机制不支持。

### 坑6：性能陷阱——boxed操作

```java
// 慢：int自动装箱为Integer
int sum = list.stream()
    .map(Integer::valueOf)  // 装箱
    .reduce(0, Integer::sum);

// 快：使用原始类型流
int sum = list.stream()
    .mapToInt(Integer::intValue)  // 转为IntStream
    .sum();  // 原始类型操作，无装箱开销
```

**成因**：`map`返回`Stream<Integer>`，涉及大量的`int`→`Integer`装箱操作，有性能开销。

## 我的理解（可选）

> 用自己的话重新表述一遍，检验是否真正理解。

Lambda表达式的本质是**行为参数化**：把"一段代码"当作参数传递给方法。

**核心机制**：
- Lambda不是匿名内部类的语法糖，而是基于`invokedynamic`指令在运行时动态生成函数式接口的实例
- 函数式接口是Lambda的**目标类型**，它限制了Lambda的签名（参数类型和返回类型）
- 方法引用是Lambda的简化写法，当Lambda体只是调用一个方法时可以用

**为什么Java需要Lambda？**
- 简化代码：匿名内部类太冗长
- 支持函数式编程：可以用声明式方式处理集合（Stream API）
- 支持行为参数化：回调、事件处理、异步任务等场景更自然

**最容易被忽略的点**：
- Lambda的`this`指向外部类，而非Lambda自身
- 局部变量捕获限制：必须是final或effectively final
- 并行流中的线程安全问题

## 面试话术总结

1. **Lambda表达式是什么？**
   "Lambda表达式是Java 8引入的函数式编程特性，它允许将行为（代码块）作为参数传递。Lambda不是匿名内部类的语法糖，而是基于invokedynamic指令在运行时动态生成函数式接口的实例。它的语法是`(参数) -> { 方法体 }`，编译器会根据上下文推断参数类型和返回类型。"

2. **函数式接口是什么？为什么需要@FunctionalInterface注解？**
   "函数式接口是只有一个抽象方法的接口，可以用Lambda表达式实现。@FunctionalInterface注解是编译期检查工具，确保接口确实只有一个抽象方法，防止开发者误添加抽象方法。但它不是必须的，只要接口只有一个抽象方法，就是函数式接口。"

3. **Lambda和匿名内部类的区别？**
   "主要区别有四点：1）语法：Lambda更简洁；2）this指向：Lambda指向外部类，匿名内部类指向自身；3）字节码：Lambda用invokedynamic运行时生成，匿名内部类编译期生成.class文件；4）性能：Lambda首次调用慢（需生成类），但后续快，且JVM可以优化。"

4. **Lambda可以捕获哪些变量？有什么限制？**
   "Lambda可以捕获实例变量、静态变量，以及局部变量。但局部变量必须是final或effectively final（未被修改）。这是因为Lambda可能在另一个线程执行，如果局部变量可变，无法保证内存可见性。而实例变量存储在堆中，所有线程共享，无此问题。"

5. **方法引用有哪几种类型？**
   "四种：1）类名::静态方法（如Math::max）；2）对象::实例方法（如System.out::println）；3）类名::实例方法（如String::length，等价于s -> s.length()）；4）类名::new（如String::new，等价于() -> new String()）。方法引用是Lambda的简化写法，当Lambda体只是调用一个方法时可以用。"
