# 闪卡库：01_Java核心_面向对象

> 使用说明：本闪卡库可导入 Obsidian Spaced Repetition 插件或 Anki。

---

## 1. 封装与访问控制

**Q: 封装的本质是什么？**

**A:**
封装 ≠ getter/setter
封装 = 把"可以改变的内部实现"藏起来，只暴露"稳定的接口"

检验标准：内部实现改变时，调用方代码要不要改？
- 要改 → 封装做得差
- 不用改 → 封装做得好

**Tags:** #Java核心 #OOP #封装

---

**Q: protected 的访问范围是什么？**

**A:**
- 同包：✅ 可以访问
- 不同包子类：通过子类实例可以访问 ✅
- 不同包非子类：❌ 不能访问
- **常见坑**：`new Parent().protectedMethod()` 编译错误！必须通过子类实例调用

**Tags:** #Java核心 #OOP #访问控制

---

**Q: 什么是防御性拷贝？在什么场景下需要？**

**A:**
返回或接收可变对象的引用时，返回/持有拷贝，防止外部修改内部状态。

```java
class Profile {
    private final int[] scores;

    // 入参防御
    Profile(int[] scores) {
        this.scores = scores.clone();
    }

    // 返回防御
    public int[] getScores() {
        return scores.clone();
    }
}
```

**Tags:** #Java核心 #OOP #封装

---

## 2. 继承与多态

**Q: 子类构造时，构造函数调用顺序是什么？**

**A:**
1. 父类构造函数先执行（默认调用 `super()`，无参构造器）
2. 子类实例变量初始化（`int value = 10`）
3. 子类构造函数体

**⚠️ 陷阱**：构造函数中不能调用可覆写的方法！
```java
class Parent {
    Parent() { doSomething(); }  // ❌ 危险
}
```
子类字段还没初始化，覆写的方法可能读到默认值。

**Tags:** #Java核心 #OOP #继承

---

**Q: 静态分派 vs 动态分派？**

**A:**
- **静态分派（重载 overload）**：编译期决定，看参数的**编译时类型**
- **动态分派（重写 override）**：运行期决定，看对象的**实际类型**

```java
void test(Object o) { print("Object"); }
void test(String s) { print("String"); }

Object o = new String("hi");
test(o);  // 输出 "Object"！因为 o 的编译时类型是 Object
```

**Tags:** #Java核心 #OOP #多态 #JVM

---

**Q: invokevirtual 的动态分派过程？**

**A:**
```
1. 取操作数栈顶的对象引用（实际类型 C）
2. 在 C 的方法表中找匹配的方法（vtable）
3. 找不到就沿着继承链往上找
4. 执行找到的方法
```

这就是为什么普通虚方法有开销（vtable 查找），也是 JIT 做内联缓存优化的原因。

**Tags:** #Java核心 #OOP #JVM #字节码

---

**Q: 字段为什么不参与多态？**

**A:**
字段访问看**编译时类型**，不参与运行时动态分派。

```java
class Animal { String name = "Animal"; }
class Dog extends Animal { String name = "Dog"; }

Animal a = new Dog();
a.name;              // "Animal"！看编译时类型
((Dog) a).name;     // "Dog"
```

这就是为什么字段应该 `private`，通过方法访问才能利用多态。

**Tags:** #Java核心 #OOP #多态

---

## 3. 内部类

**Q: 成员内部类的 this$0 是什么？**

**A:**
编译器自动生成的反向引用，指向外部类实例。

```java
// 源码
class Outer {
    class Inner {
        void print() { System.out.println(x); }
    }
}

// 编译后等价于
class Inner {
    final Outer this$0;  // 编译器生成
    Inner(Outer this$0) { this.this$0 = this$0; }
    void print() {
        System.out.println(this$0.x);
    }
}
```

**⚠️ 内存泄漏风险**：Handler + 匿名内部类持有 Activity 引用 → Activity 无法被 GC

**Tags:** #Java核心 #OOP #内部类

---

**Q: Lambda vs 匿名内部类的本质区别？**

**A:**
| 维度 | 匿名内部类 | Lambda |
|------|-----------|--------|
| 编译产物 | 生成 `.class` 文件 | 无额外 `.class` |
| 字节码指令 | `invokevirtual` | `invokedynamic` |
| 外部类引用 | 总是持有 `this$0` | 只捕获实际使用的变量 |
| this 指向 | 指向匿名类实例 | 指向 enclosing 类实例 |
| 可序列化 | ✅（如接口可序列化） | ❌ |

**Tags:** #Java核心 #Lambda #内部类

---

## 4. 抽象类与接口

**Q: 抽象类 vs 接口的本质区别？**

**A:**
- **抽象类**："是不是"的关系（is-a），共享代码 + 控制子类构造
- **接口**："能不能"的关系（can-do），能力契约

| 维度 | 抽象类 | 接口 |
|------|--------|------|
| 构造器 | ✅ 有 | ❌ 无 |
| 多继承 | ❌ | ✅ 支持多实现 |
| 状态 | 可以有实例字段 | Java 8+ 只有 static final |
| 演进能力 | 加具体方法 → 自动继承 | 需要 default 方法 |

**Tags:** #Java核心 #OOP #接口

---

**Q: 接口 default 方法冲突怎么解决？**

**A:**
```java
interface A { default void hello() { print("A"); } }
interface B { default void hello() { print("B"); } }
class C implements A, B {
    @Override
    public void hello() {
        A.super.hello();  // 显式选择
        // 或完全自己实现
    }
}
```

规则：
1. 类方法 > 接口 default
2. 两个接口的 default 冲突 → 必须显式覆写

**Tags:** #Java核心 #OOP #接口 #Java8

---

## 5. 枚举

**Q: 为什么枚举是实现单例的最佳方式？**

**A:**

| 维度 | 双重检查锁 | 静态内部类 | 枚举 |
|------|-----------|-----------|------|
| 线程安全 | 需要 volatile | JVM 保证 | JVM 保证 |
| 序列化安全 | 需要 readResolve() | 需要 readResolve() | ✅ 天然安全 |
| 反射攻击 | ❌ 可破坏 | ❌ 可破坏 | ✅ 天然防 |
| 代码量 | ~15行 | ~8行 | ~3行 |

**防反射**：JDK 在 `Constructor.newInstance()` 中拦截枚举类
**防序列化**：只写 name 字符串，反序列化用 `Enum.valueOf()` 返回已有实例

**Tags:** #Java核心 #OOP #枚举 #单例

---

**Q: ordinal() 的坑是什么？**

**A:**
```java
enum Priority { LOW, MEDIUM, HIGH }
// ordinal: LOW=0, MEDIUM=1, HIGH=2

// ❌ 如果中间插入新值，所有 ordinal 都错乱
enum Priority { LOW, NORMAL, MEDIUM, HIGH }
// 现在 MEDIUM=2, HIGH=3
```

**正确做法**：用自定义字段
```java
enum Priority { LOW(1), MEDIUM(2), HIGH(3);
    private final int level;
    Priority(int level) { this.level = level; }
}
```

**Tags:** #Java核心 #OOP #枚举

---

## 6. 克隆与拷贝

**Q: 浅拷贝 vs 深拷贝 vs 引用拷贝？**

**A:**
```
引用拷贝:     a ──→ [obj]      a和b指向同一对象
             b ──↗

浅拷贝:      a ──→ [obj₁]    新对象，但引用类型字段共享
             b ──→ [obj₁]

深拷贝:      a ──→ [obj₁]    完全独立的副本
             b ──→ [obj₂]
```

`Object.clone()` 默认是**浅拷贝**——数组、List 等引用类型字段会共享。

**Tags:** #Java核心 #OOP #克隆

---

**Q: 为什么推荐拷贝构造器而不是 Cloneable？**

**A:**
Cloneable 的设计缺陷：
1. 没有 `clone()` 方法签名（Object 的 clone 是 protected）
2. 返回 `Object`，需要强制类型转换
3. 不抛异常的约定靠文档，编译器不检查

```java
// ✅ 推荐：拷贝构造器
class Profile {
    Profile(Profile source) {
        this.name = source.name;
        this.scores = source.scores.clone();  // 深拷贝
    }
}
```

**Tags:** #Java核心 #OOP #克隆 #EffectiveJava

---

*生成时间：2026-05-05*
