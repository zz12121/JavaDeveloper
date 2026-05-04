# final 关键字

> `final` 在 Java 中有三个作用：禁止继承、禁止重写、禁止重新赋值。但 `final` 不等于不可变，`final` 也不等于线程安全——理解这三个"不等于"，才是真正理解 final。

---

## 这个问题为什么存在？

`final` 解决的核心问题是：**防止被意外修改**。

```
没有 final 的情况下：
- 任何类都可以被继承 → String 被恶意子类化，安全检查被绕过
- 任何方法都可以被重写 → 模板方法的核心步骤被改写
- 任何变量都可以被重新赋值 → 常量失去意义
- 没有可见性保证 → 多线程可能看到未初始化的值
```

这四个场景对应了 final 的四个设计目的：安全性、设计意图表达、性能优化（编译期内联）、并发可见性保证。

---

## 它是怎么解决问题的？

### final 的三个作用

| 位置 | 作用 | 典型示例 |
|------|------|---------|
| `final class` | 禁止继承 | `String`、`Integer`、`System` |
| `final method` | 禁止重写 | 模板方法中的核心步骤 |
| `final variable` | 禁止重新赋值 | 常量、配置项、[[01_Java核心/01_基础语法/字符串|String]] 的 `private final byte[] value` |

### final 修饰类

```java
// String 必须是 final 的，原因有三：
// 1. 安全性——String 用于文件路径、密码、网络参数，子类化可以绕过安全检查
// 2. 不变性保证——常量池、hash 缓存、substring 优化都依赖值不可变
// 3. JVM 优化——ldc 指令、字符串拼接优化都假设 String 不可变
public final class String { }

// 编译错误：cannot inherit from final String
class MyString extends String { }
```

`[[01_Java核心/02_面向对象/枚举|枚举]]` 也是隐式 final 的——枚举值不能被继承。

### final 修饰方法

```java
class Template {
    // final 方法：子类不能重写
    final void coreAlgorithm() {
        step1();
        step2();  // 核心步骤，不允许子类修改
        step3();
    }

    void step1() { /* 子类可以重写 */ }
    void step2() { /* 子类可以重写 */ }
    void step3() { /* 子类可以重写 */ }
}
```

**`private` 方法天然是 final 的**：private 方法对子类不可见，子类写同名方法只是定义了一个新方法，不构成重写。加上 `final` 只是冗余。

### final 修饰变量

#### 三种变量形态

```java
// 1. 编译期常量（编译器内联）
static final int MAX_SIZE = 1024;
// 编译后所有引用处直接替换为 1024（常量折叠）

// 2. blank final（空白 final）
final int value;              // 声明时不赋值
// 必须在构造器中赋值（每个对象可以有不同的值）
MyClass(int v) { this.value = v; }

// 3. 普通 final
final int count = 0;          // 声明时赋值，之后不可修改
```

blank final 的价值：让每个实例有自己的不可变值。`final` 不意味着"所有实例的值相同"。

```java
class Person {
    final String name;   // 每个人名字不同，但一旦确定就不能改
    Person(String name) { this.name = name; }
}
```

#### final 修饰参数和局部变量

```java
void method(final int size, final List<String> items) {
    // size = 10;       // 编译错误
    // items = newList; // 编译错误
    items.add("x");     // 合法！final 只保护引用，不保护对象内容
}
```

参数加 `final` 主要用于表达设计意图——"这个方法不会修改传入的参数引用"。部分团队在编码规范中要求所有参数加 `final`，但 Java 社区对此有争议，不做强制要求。

### final 不等于不可变

```java
// final 只保护「引用不变」，不保护「对象内容不变」
final List<String> list = new ArrayList<>();
list.add("a");     // 合法——修改的是 list 指向的对象，不是 list 本身
list = new ArrayList<>();  // 编译错误——试图修改 list 的引用

final int[] arr = {1, 2, 3};
arr[0] = 100;     // 合法——修改数组内容
arr = new int[5]; // 编译错误——试图修改 arr 的引用
```

**真正不可变需要四个条件同时满足**：

```
1. 类声明为 final（防止子类化）
2. 所有字段声明为 private final
3. 所有字段引用的对象也是不可变的（防御性拷贝）
4. 不提供 setter 方法
```

```java
// 不可变类示例
public final class ImmutablePoint {
    private final int x;
    private final int y;

    public ImmutablePoint(int x, int y) {
        this.x = x;
        this.y = y;
    }
    public int getX() { return x; }
    public int getY() { return y; }
}

// 或直接用工具类
List<String> immutable = Collections.unmodifiableList(mutableList);
List<String> immutable2 = List.of("a", "b", "c");  // JDK 9+
```

---

## 深入原理

### final 与 JMM（Java 内存模型）

`final` 在多线程中有一个重要的语义保证：

```
JMM 规范（JLS §17.5）：

构造函数中对 final 字段的写入
  happens-before
构造函数返回之后，其他线程读取该 final 字段

前提条件：构造函数没有发生 this 逸出（没在构造完成前把 this 发布出去）
```

```java
// 正确用法：构造函数完成后，任何线程都能读到正确的 final 值
class Config {
    final int timeout;
    Config(int timeout) {
        this.timeout = timeout;
    }
}

// 错误用法：this 逸出，final 保证失效
class BadConfig {
    final int timeout;
    BadConfig(int timeout) {
        new Thread(() -> {
            System.out.println(this.timeout);  // 可能读到 0（默认值）！
        }).start();
        this.timeout = timeout;
    }
}
```

**final vs volatile**：

| 维度 | final | volatile |
|------|-------|----------|
| 保护方向 | 写一次，之后只读 | 每次读写都保证可见性 |
| 可变性 | 初始化后不可变 | 可以被修改 |
| 语义 | happens-before（构造→读） | happens-before（写→后续读） |
| 典型用途 | 不可变对象、配置常量 | 状态标志（`volatile boolean running`） |
| 数组/对象 | 只保护引用，不保护内容 | 保护引用的可见性，不保护内容 |

### final 的编译期优化与类加载

```java
class Constants {
    // 编译期常量：编译器直接内联，不触发类加载
    public static final int A = 100;
    // 其他类引用 Constants.A 时，编译后等价于直接写 100

    // 运行时常量：会触发 Constants 类的初始化
    public static final long NOW = System.currentTimeMillis();
}
```

编译期常量的判断标准：基本类型 + String 字面量 + 编译期可确定的常量表达式。如果常量的值被修改并重新编译，但引用它的类没有重新编译 → 旧的 class 文件中仍然是旧值。**这就是为什么常量类更新后需要全量编译。**

### Lambda 中的 effectively final

```java
int factor = 2;          // effectively final——虽然没加 final 关键字，
                         // 但后续没被重新赋值，编译器视为 final

list.forEach(x -> System.out.println(x * factor));  // 合法

// factor = 3;  // 如果取消注释，编译器报错：lambda 中引用的局部变量必须是 final 或 effectively final
```

Lambda 捕获的变量必须是 final 或 effectively final。详见 [[01_Java核心/08_Lambda与Stream/Lambda与函数式|Lambda与函数式]] 中 invokedynamic 的实现原理。

---

## 正确使用方式

### 1. 类设计中的 final

```
应该用 final class 的场景：
- 安全敏感的类（String、包装类型）
- 设计上就不应该被继承的类（工具类、策略枚举）

不需要 final class 的场景：
- 框架/库中的基类（需要被子类扩展）
- 面向接口编程时，实现类一般不加 final（让扩展更灵活）
```

### 2. 方法中的 final

```
应该用 final method 的场景：
- 模板方法模式中不允许子类覆盖的核心步骤
- 父类的构造方法调用的方法（避免多态导致子类在未初始化时被调用）

不需要 final method 的场景：
- 普通业务方法——过度使用 final 会降低类的可扩展性
```

### 3. 字段中的 final

```java
public class GoodExample {
    // 1. 静态常量：编译期确定，所有实例共享
    private static final int MAX_RETRIES = 3;

    // 2. 实例常量：每个实例不同，但创建后不可变
    private final String id;

    public GoodExample(String id) {
        this.id = Objects.requireNonNull(id, "id不能为null");
    }
}
```

不可变字段用 `final` 是最佳实践。JVM 对 final 字段有额外的优化（不需要在每次读取时检查是否被修改），也能在多线程场景下省去 volatile 或同步的开销。

---

## 边界情况和坑

### 1. final 字段引用可变对象

```java
final List<String> list = new ArrayList<>();
list.add("a");     // 合法，但"不可变"的语义被破坏了
list.add("b");     // 任何人拿到 list 的引用都能修改内容
```

`final` 只保证引用不变，不保证对象内容不变。如果你需要真正不可变的集合，用 `List.of()` 或 `Collections.unmodifiableList()`。

### 2. blank final 未初始化

```java
class Bad {
    final int value;  // 必须在构造器中赋值

    Bad() {
        // 忘记赋值 → 编译错误：variable value might not have been initialized
    }

    Bad(int v) {
        value = v;    // 正确
    }
}
```

blank final 必须在构造器退出前被赋值，且只能赋值一次。如果在两个分支中分别赋值，编译器也能追踪到：

```java
Bad(boolean flag) {
    if (flag) {
        value = 1;
    } else {
        value = 2;
    }
    // 编译器知道两个分支都赋了值 → 合法
}
```

### 3. 编译期常量内联导致的"不一致"

```java
// A.java
public class A {
    public static final int VERSION = 1;
}

// B.java
public class B {
    public static void main(String[] args) {
        System.out.println(A.VERSION);  // 编译后：System.out.println(1);
    }
}
```

如果修改 A.VERSION 为 2，只重新编译 A.java，不重新编译 B.java → B 中打印的仍然是 1。因为编译器把 `A.VERSION` 直接内联为字面量 `1`。

**解决**：修改常量类后全量编译，或者把常量改为运行时确定的值（如通过方法获取）。

### 4. final 与 abstract 的互斥

```java
// 编译错误：illegal combination of modifiers
public final abstract class MyClass { }

// 编译错误：illegal combination of modifiers
public final abstract void method();
```

`final` 表示"不能被重写/继承"，`abstract` 表示"必须被重写/继承"——两者语义矛盾，不能同时使用。
