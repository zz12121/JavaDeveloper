# Java 核心 - 知识点考法对照

> 本文档是「出题者视角」的知识梳理——每个知识点列出常见考法 + 回答要点。
> 配合对应知识文档一起使用，先学后考。

---

## 泛型擦除

**关联知识文档**：[[01_Java核心/04_泛型/泛型]]

**第一问**：「Java 的泛型擦除是什么？有什么局限？」

| 追问层次 | 追问 | 考点 |
|---------|------|------|
| 第一层 | 擦除之后 `List<String>` 和 `List<Integer>` 是同一种类型吗？ | 编译期类型检查 vs 运行时 |
| 第二层 | 为什么不能 `new T()`、不能 `new T[10]`？ | 类型信息运行时不可用 |
| 第三层 | 什么是桥方法？编译器为什么要生成它？ | 泛型继承的兼容性问题 |

**对比型考法**：「Kotlin 的泛型 `in`/`out` 和 Java 的 `? super`/`? extends` 有什么区别？」

**实战型考法**：「你用过反射绕过泛型吗？具体怎么做的？」

**面试话术总结**：

> 回答思路：先说「是什么」，再说「局限」，最后说「怎么绕过」。

- **擦除本质**：编译期做类型检查，`List<String>` 编译后变成 `List`（raw type），类型参数被替换为上界（无界 → `Object`，有界 → 上界类型）
- **局限**（必须能列举）：
  - 不能 `new T()` —— 运行时不知道 T 的具体类型
  - 不能 `new T[10]` —— 数组有「具体化类型」，泛型没有
  - 不能 `obj instanceof T` —— 运行时类型信息已擦除
  - 静态成员/方法不能使用泛型类型参数
- **桥方法**（高频追问）：
  ```java
  // 源码
  interface Comparable<T> { int compareTo(T other); }
  // 擦除后，编译器自动生成桥方法
  class String implements Comparable {
      int compareTo(Object other) { return compareTo((String) other); }
  }
  ```
  桥方法的意义：保证泛型子类能正确重写父类的擦除后方法
- **绕过方式**：
  - 传 `Class<T>` 参数，用 `clazz.getDeclaredConstructor().newInstance()`
  - 反射直接调用：`Method.setAccessible(true)` 后强转
- **与 Kotlin 对比**（加分回答）：Kotlin 的 `out T` ≈ Java `? extends T`；`in T` ≈ Java `? super T`。但 Kotlin 是**声明处型变**，更安全

---

## 反射机制

**关联知识文档**：[[01_Java核心/07_注解与反射/反射]]

**第一问**：「反射是什么？有什么用？」

| 追问层次 | 追问 | 考点 |
|---------|------|------|
| 第一层 | `Class.forName()` 和 `ClassLoader.loadClass()` 有什么区别？ | 是否触发初始化（`<clinit>`）|
| 第二层 | 反射调用方法比直接调用慢在哪里？ | 访问控制检查 / 参数装箱拆箱 / 方法查找 |
| 第三层 | `setAccessible(true)` 为什么能加速？有什么风险？ | 跳过访问检查 / 破坏封装性 |

**实战型考法**：「你在项目里用过反射吗？用来做什么？」

**面试话术总结**：

> 回答思路：先说「是什么 + 典型场景」，再讲「性能问题 + 优化」，最后说「安全限制」。

- **反射本质**：运行时获取类的结构信息（字段/方法/构造器）并操作它们，绕过编译期类型检查
- **典型场景**：注解处理、`ServiceLoader` SPI、Spring IoC 依赖注入、MyBatis 映射
- **性能开销**：`getMethod()` 每次遍历父类；`Method.invoke()` 有参数装箱和访问检查；JDK 8+ 引入 `LambdaForm` 优化，仍慢约 1.5~2 倍
- **加速技巧**：`setAccessible(true)` 跳过权限检查；缓存 `Method`/`Field` 对象；高频场景用 `MethodHandle` 或 ASM 字节码生成

---

## String 家族

**关联知识文档**：[[01_Java核心/01_String家族/String家族]]

**第一问**：「String、StringBuilder、StringBuffer 有什么区别？」

| 追问层次 | 追问 | 考点 |
|---------|------|------|
| 第一层 | String 为什么是不可变的？ | `final` 类 + `final byte[]` 值数组（JDK 9+）|
| 第二层 | 字符串常量池是什么？`new String("abc")` 创建了几个对象？ | 常量池（堆中）+ 堆对象 |
| 第三层 | `intern()` 方法在 JDK 6 和 JDK 7+ 有什么不同？ | 常量池位置（PermGen vs Heap）|

**面试话术总结**：

- **String 不可变的原因**：常量池共享、hashCode 缓存、线程安全、类加载安全
- **`new String("abc")` 创建对象数**：常量池已有 → 1 个；常量池没有 → 2 个
- **`intern()` 变化**：JDK 6 把字符串复制到 PermGen；JDK 7+ 常量池移到堆，`intern()` 放入的是**引用**而非副本
- **使用场景**：`String` 不频繁修改；`StringBuilder` 单线程拼接；`StringBuffer` 多线程拼接（`synchronized`）

---

## hashCode 与 equals

**关联知识文档**：[[01_Java核心/02_equals与hashCode/equals与hashCode]]

**第一问**：「为什么重写 equals 必须重写 hashCode？」

| 追问层次 | 追问 | 考点 |
|---------|------|------|
| 第一层 | equals 和 hashCode 的约定是什么？ | 相等对象必须有相等哈希码 |
| 第二层 | HashMap 里如果只重写 equals 没重写 hashCode 会怎样？ | 哈希冲突到不同桶，`get()` 找不到 |
| 第三层 | `Objects.hash()` 和手动计算哈希码哪个更好？ | 性能开销 vs 碰撞概率 |

**面试话术总结**：

- **约定**（必须背）：equals 相等 → hashCode 必须相等；hashCode 相等 → equals 不一定相等
- **HashMap 后果**：两个 equals 相等的对象 hashCode 不同 → 放在不同桶里 → `get()` 返回 null
- **好的 hashCode**：让不同对象哈希码尽可能分散；JDK 标准做法 `31 * result + fieldHash`；`Objects.hash()` 方便但慢（有数组创建开销）

---

## final 关键字

**关联知识文档**：[[01_Java核心/03_final关键字/final关键字]]

**第一问**：「final 有哪些用法？分别有什么作用？」

| 追问层次 | 追问 | 考点 |
|---------|------|------|
| 第一层 | final 修饰引用类型时，引用不可变还是对象不可变？ | 引用不可变，对象内容可变 |
| 第二层 | final 字段在构造函数里赋值，有什么线程安全保证？ | JMM final 字段语义（安全发布）|
| 第三层 | `final` vs `immutable`，是一回事吗？ | 引用不变 vs 对象状态完全不可变 |

**面试话术总结**：

- **三种用法**：修饰变量（基本类型值不可变，引用类型引用不可变）；修饰方法（不能被重写）；修饰类（不能被继承）
- **JMM final 语义**：final 字段在构造函数里初始化完成后，任何其他线程都能**正确看到**（无需 volatile），原理是构造函数末尾插入 `StoreStore` 屏障
- **effectively final**（JDK 8+）：变量实际没有被修改，lambda/匿名内部类可访问

---

## 接口 vs 抽象类

**关联知识文档**：[[01_Java核心/05_抽象类与接口/抽象类与接口]]

**第一问**：「接口和抽象类有什么区别？」

| 追问层次 | 追问 | 考点 |
|---------|------|------|
| 第一层 | Java 8 之后接口可以有默认方法，那和抽象类还有区别吗？ | 多继承 / 状态（字段）|
| 第二层 | 接口里的字段为什么默认是 `public static final`？ | 接口不保存状态 |
| 第三层 | 什么情况下用抽象类而不是接口？ | 共享状态 / 模板方法模式 |

**面试话术总结**：

- **语法区别**：接口只有常量 + 抽象方法 + default/static 方法；抽象类可有任意字段和具体方法；接口可多实现，抽象类只能单继承
- **设计意图**：接口定义「能做什么」（契约）；抽象类定义「是什么」（is-a）
- **选择原则**：需要多继承 → 接口；有共享状态 → 抽象类；部分实现 + 模板方法 → 抽象类

---

## 多态实现原理

**关联知识文档**：[[01_Java核心/06_多态与方法分派/多态与方法分派]]

**第一问**：「Java 的多态是怎么实现的？」

| 追问层次 | 追问 | 考点 |
|---------|------|------|
| 第一层 | 方法重载和方法重写是多态吗？ | 编译期静态分派 vs 运行期动态分派 |
| 第二层 | `invokevirtual` 指令是怎么找到目标方法的？ | 虚方法表（vtable）|
| 第三层 | 为什么私有方法 / final 方法不能被重写？ | 静态绑定，不在 vtable 中 |

**面试话术总结**：

- **多态分类**：编译期（重载，静态分派）；运行期（重写，动态分派）
- **JVM 实现**：每个类有 vtable；`invokevirtual` 从对象实际类型查 vtable；vtable 在类加载链接阶段构建
- **重载 vs 重写**：重载看编译期方法签名（名 + 参数类型）；重写看运行期对象实际类型；`@Override` 注解帮助编译期校验

---

## IO / NIO / AIO

**关联知识文档**：[[01_Java核心/08_IO模型/IO模型]]

**第一问**：「BIO、NIO、AIO 有什么区别？」

| 追问层次 | 追问 | 考点 |
|---------|------|------|
| 第一层 | NIO 的三大核心组件是什么？ | Channel / Buffer / Selector |
| 第二层 | `select` / `poll` / `epoll` 的区别？ | 数据结构 / 性能 / 触发模式 |
| 第三层 | AIO 为什么在 Linux 上没有真正异步？ | Linux 内核 AIO 只支持直接 IO，不支持 socket |

**面试话术总结**：

- **三种模型**：BIO 全阻塞（一连接一线程）；NIO 非阻塞（Reactor 模式，一个线程管多个连接）；AIO 真正异步（回调驱动）
- **NIO 核心**：Channel 负责传输、Buffer 负责存储、Selector 负责事件多路复用
- **`epoll` 优势**：内核维护事件表（红黑树），只返回就绪 fd，O(1)；支持边缘触发（ET）和水平触发（LT）
- **Linux AIO 的坑**：内核 AIO 只支持 `O_DIRECT`（绕过页缓存），且不支持 socket；Java AIO 在 Linux 底层仍用 `epoll` 模拟，不是真正异步；所以 Netty 只用 NIO

---

## 自动装箱拆箱

**关联知识文档**：[[01_Java核心/09_自动装箱与拆箱/自动装箱与拆箱]]

**第一问**：「Integer a = 127; Integer b = 127; a == b 是 true 还是 false？为什么？」

| 追问层次 | 追问 | 考点 |
|---------|------|------|
| 第一层 | `Integer.valueOf()` 的缓存范围是什么？可以调整吗？ | -128~127 / `XX:AutoBoxCacheMax` |
| 第二层 | 自动装箱拆箱的底层原理是什么？ | 编译器生成 `valueOf()` / `intValue()` |
| 第三层 | `Long` / `Double` 也有缓存吗？ | Long 有（-128~127），Double 没有（浮点数无离散整数那样的规律）|

**对比型考法**：「`int` 和 `Integer` 在内存占用、默认值、比较方式上有什么区别？」

**面试话术总结**：

- **`==` vs `equals`**：`==` 比引用（对象地址）；`equals` 比值；包装类型比较值必须用 `equals`
- **Integer 缓存**：`valueOf()` 对 -128~127 返回缓存对象；`new Integer()` 每次新建，绕过缓存；JVM 参数 `XX:AutoBoxCacheMax` 可调整上限
- **装箱拆箱原理**：编译器在编译期自动插入 `Integer.valueOf()`（装箱）和 `intValue()`（拆箱）；频繁装箱有性能开销（对象创建）
- **陷阱**：`Integer a = null; int b = a;` → 拆箱时 `NullPointerException`

---

## Object 方法

**关联知识文档**：[[01_Java核心/10_Object类/Object类]]

**第一问**：「Object 类有哪些方法？分别做什么用？」

| 追问层次 | 追问 | 考点 |
|---------|------|------|
| 第一层 | `equals()` 和 `hashCode()` 的约定是什么？不遵守会怎样？ | HashMap 放得到取不到 |
| 第二层 | `wait()` / `notify()` 为什么必须在 `synchronized` 块里调用？ | 必须持有对象监视器锁 |
| 第三层 | `finalize()` 为什么不推荐使用？ | 执行时机不确定 / 性能差 / JDK 9+ 已标记废弃 |

**对比型考法**：「`clone()` 是浅拷贝还是深拷贝？怎么实现深拷贝？」

**面试话术总结**：

- **核心方法清单**：`equals()`、`hashCode()`、`toString()`、`clone()`、`wait()`/`notify()`、`finalize()`（废弃）、`getClass()`
- **`wait()` / `notify()` 规则**：必须在 `synchronized(obj)` 块内调用，因为 `wait()` 会释放锁，唤醒后需要重新获取锁
- **`clone()`**：默认浅拷贝（只复制引用，不复制对象内容）；实现深拷贝需要：① 重写 `clone()` 并递归调用成员对象的 `clone()`；② 或用序列化/反序列化；③ 或用三方库（Apache Commons `SerializationUtils.clone()`）
- **`finalize()` 废弃原因**：执行时机完全不确定（GC 不保证什么时候调用）；每个 `finalize` 对象会延迟 GC；JDK 9+ 标记 `@Deprecated(forRemoval=true)`

---

## 异常体系

**关联知识文档**：[[01_Java核心/11_异常体系/异常体系]]

**第一问**：「Java 的异常体系是怎样的？checked 和 unchecked 有什么区别？」

| 追问层次 | 追问 | 考点 |
|---------|------|------|
| 第一层 | `RuntimeException` 和 `Exception` 的区别？ | 编译期强制捕获 vs 不强制 |
| 第二层 | `try-with-resources` 是怎么实现的？ | `AutoCloseable` 接口 + 编译器生成 `addSuppressed` |
| 第三层 | `finally` 里的 return 会覆盖 try 里的 return 吗？ | 会，finally 的 return 优先 |

**实战型考法**：「你设计过自定义异常吗？应该怎么设计？」

**面试话术总结**：

- **异常体系**：`Throwable` ← `Error`（严重系统错误，不应捕获）/ `Exception` ← `RuntimeException`（unchecked）/ 其他（checked，必须捕获或声明）
- **checked vs unchecked**：checked（`Exception` 非 `RuntimeException` 子类）编译期强制处理；unchecked（`RuntimeException` + `Error`）编译期不强制
- **`try-with-resources`**：JDK 7+，实现 `AutoCloseable` 接口的对象可自动关闭；编译器自动生成 `try + finally + addSuppressed` 代码
- **`finally` 的坑**：`finally` 里的 `return` 会覆盖 `try`/`catch` 里的 `return`；`finally` 里的异常会覆盖原有异常（用 `addSuppressed` 可保留）

---

## 序列化机制

**关联知识文档**：[[01_Java核心/12_序列化机制/序列化机制]]

**第一问**：「Java 序列化是什么？`Serializable` 接口里有什么方法？」

| 追问层次 | 追问 | 考点 |
|---------|------|------|
| 第一层 | `serialVersionUID` 是做什么的？不写会怎样？ | 版本一致性校验 / 自动生成可能不一致 |
| 第二层 | `transient` 关键字的作用？静态字段会被序列化吗？ | 跳过序列化 / 静态字段属于类，不序列化 |
| 第三层 | 父类没实现 `Serializable`，子类实现了，字段能序列化吗？ | 父类字段不会序列化，需要父类有无参构造函数 |

**对比型考法**：「Java 原生序列化 vs JSON（Jackson）vs Protobuf，你怎么选？」

**面试话术总结**：

- **`Serializable` 接口**：标记接口（无方法）；真正工作的是 `ObjectOutputStream.writeObject()` 的序列化机制
- **`serialVersionUID`**：显式声明可保证版本兼容；不写则由 JVM 根据类结构自动生成，类稍有改动就会 mismatch，反序列化失败
- **`transient`**：标记不序列化的字段；敏感数据（密码）应标记为 `transient`；静态字段不属于对象状态，不会被序列化
- **继承场景**：父类没实现 `Serializable`，子类实现了 → 父类字段不会序列化；反序列化时父类字段通过**无参构造函数**重建（所以父类必须有可访问的无参构造函数）
- **替代方案**：Java 原生序列化性能差、字节数组大、跨语言不支持；生产推荐 Protobuf / Jackson JSON

---

## 注解实现原理

**关联知识文档**：[[01_Java核心/13_注解与反射/注解]]

**第一问**：「注解是什么？怎么自定义一个注解？」

| 追问层次 | 追问 | 考点 |
|---------|------|------|
| 第一层 | `@Retention` 的三种取值是什么？区别？ | SOURCE（编译期丢弃）/ CLASS（字节码保留，运行时不可见）/ RUNTIME（运行时可见，可反射读取）|
| 第二层 | 注解的生效方式有哪些？ | 编译期（APT）/ 类加载期（字节码增强）/ 运行期（反射）|
| 第三层 | Spring 的 `@Autowired` 是怎么生效的？ | `AutowiredAnnotationBeanPostProcessor`（运行时反射）|

**实战型考法**：「你自定义过注解吗？用来做什么？」

**面试话术总结**：

- **注解三要素**：① 注解本身（`@interface`）；② 元注解（`@Target`、`@Retention`、`@Documented`、`@Inherited`）；③ 注解处理器（让它真正起作用）
- **`@Retention` 三种策略**：
  - `SOURCE`：编译后丢弃，`@Override`、`@SuppressWarnings` 属于这类
  - `CLASS`：字节码中保留，运行时不可见（默认策略），供字节码增强工具使用
  - `RUNTIME`：运行时可见，`@Autowired`、`@Transactional` 属于这类，可通过反射读取
- **注解生效方式**：
  - 编译期：APT（`@Processor`，Lombok 用此方式在编译期修改语法树）
  - 类加载期：字节码增强（ASM、Javassist、ByteBuddy）
  - 运行期：反射读取注解，Spring 大部分注解用此方式
- **Lombok 原理**（高频追问）：Lombok 用 APT 在编译期修改 AST（抽象语法树），自动生成 `getter`/`setter`/`equals`/`hashCode` 等方法，编译后的 `.class` 文件里这些方法真实存在
