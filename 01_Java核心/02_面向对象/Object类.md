# Object 类

> Object 是所有类的根——不继承任何类的类，隐式继承 Object。理解 Object 的三个核心方法（equals / hashCode / toString），是正确使用集合框架的前提。

---

## 这个问题为什么存在？

Java 需要一组**所有对象都具备的基础行为**：

```
没有 Object 根类时：
- 所有类都要自己实现 equals / hashCode / toString → 无统一约定
- 集合框架无法统一处理任意类型（无法要求 T 有 equals()）
- 多线程的 wait / notify 机制没有统一入口
- 垃圾回收无法判断对象是否可以被回收（finalize）
```

Object 的核心价值：**提供所有对象必须拥有的契约方法**，让集合、并发、GC 等基础设施可以有统一的处理方式。

---

## 它是怎么解决问题的？

### equals() 和 hashCode()：成对出现的契约

```
契约（Contract）：
1. equals()  reflexivity：x.equals(x) 必须为 true
2. equals()  symmetry：x.equals(y) == y.equals(x)
3. equals()  transitivity：x.eq(y) && y.eq(z) → x.eq(z)
4. hashCode() consistency：同一次运行中，同对象 hashCode 必须相同
5. 关键：a.equals(b) == true → a.hashCode() == b.hashCode()
   反之不成立：hashCode 相同，equals 不一定 true
```

```java
class Point {
    int x, y;

    @Override
    public boolean equals(Object o) {
        if (this == o) return true;
        if (!(o instanceof Point)) return false;
        Point p = (Point) o;
        return x == p.x && y == p.y;
    }

    @Override
    public int hashCode() {
        return Objects.hash(x, y);  // 必须与 equals 一致
    }
}
```

**只覆写 equals 不覆写 hashCode 的后果**：

```java
Point p1 = new Point(1, 2);
Point p2 = new Point(1, 2);
p1.equals(p2);  // true（我们覆写了 equals）

Set<Point> set = new HashSet<>();
set.add(p1);
set.contains(p2);  // false！因为 hashCode 不同，p2 落在不同桶
// HashMap、HashSet 先比 hashCode，再比 equals
```

详见 [[01_Java核心/05_集合框架/集合框架|集合框架]] 中 HashMap 的桶查找原理。

### toString()：调试与日志

```java
@Override
public String toString() {
    return "Point{x=" + x + ", y=" + y + "}";
}
// 不覆写则默认返回 ClassName@hashCode（如 Point@1b6d3586），毫无意义

// 覆写后的好处：
System.out.println(point);  // 自动调用 toString()
log.info("当前点：{}", point);  // 日志框架也调用 toString()
```

### wait() / notify() / notifyAll()：线程协作

```java
// 经典生产者-消费者模式
class Queue<T> {
    private final List<T> items = new ArrayList<>();

    synchronized void put(T item) throws InterruptedException {
        while (items.size() >= MAX) {
            wait();  // 释放锁，等待消费者消费
        }
        items.add(item);
        notifyAll();  // 唤醒等待的消费者
    }

    synchronized T take() throws InterruptedException {
        while (items.isEmpty()) {
            wait();  // 释放锁，等待生产者生产
        }
        T item = items.remove(0);
        notifyAll();  // 唤醒等待的生产者
        return item;
    }
}
```

**关键规则**：`wait()` / `notify()` / `notifyAll()` **必须在 `synchronized` 块内调用**，否则抛 `IllegalMonitorStateException`。

JDK 5 之后，更推荐用 `[[02_并发编程/线程安全与锁机制|ReentrantLock]]` + `Condition` 替代 `wait/notify`，因为后者不支持多条件队列。

### getClass() vs instanceof

```java
// instanceof：考虑继承，是"is-a"语义
if (o instanceof Point) { }  // 子类也可以

// getClass()：严格相等，不考虑继承
if (o != null && o.getClass() == this.getClass()) { }  // 只有同类才行
```

**覆写 equals 时应该用什么？**

```
《Effective Java》第 10 条建议：用 instanceof，不使用 getClass()。
原因：允许子类继承 equals（只要子类不添加新的字段参与 equals 计算）。

例外：值类（如 Enum、不可变类）可以用 getClass()，
     因为值相等不依赖继承层次。
```

---

## 深入原理

### hashCode() 的桶分布原理

```java
// Object 的默认 hashCode：通常基于对象内存地址
// 但 HotSpot 的默认实现已经不用内存地址了（安全考虑）

// 好的 hashCode 必须满足：
// 1. 快速计算
// 2. 碰撞尽量少
// 3. 均匀分布

// JDK 中 String 的 hashCode 实现：
// h = s[0]*31^(n-1) + s[1]*31^(n-2) + ... + s[n-1]
// 31 的特性：31 * i = (i << 5) - i，JIT 可以优化为移位指令
```

### wait() 的虚假唤醒

```java
// 永远要把 wait() 放在 while 循环里，不能用 if
synchronized void doWork() throws InterruptedException {
    // ❌ 错误：可能虚假唤醒（JVM 规范允许）
    if (!ready) wait();

    // ✅ 正确：用 while
    while (!ready) wait();
    // 即使虚假唤醒，也会重新检查条件
}
```

**虚假唤醒（Spurious Wakeup）**：JVM 规范允许 `wait()` 在没有 `notify()` 的情况下返回。虽然主流 JVM 实现不会主动虚假唤醒，但代码必须防御。

### finalize() 的废弃（JDK 9+）

```java
@Deprecated(since="9")
protected void finalize() throws Throwable { }
```

```text
为什么废弃 finalize？
1. 调用时机不确定（GC 何时发生不确定）
2. 性能差：增加 GC 停顿时间
3. 可能导致对象复活（在 finalize() 中让外部引用重新指向 this）
4. 不保证一定会被调用（JVM 崩溃时不会调用）

替代方案：
- 资源类实现 AutoCloseable，用 try-with-resources
- 或者使用 java.lang.ref.Cleaner（JDK 9+）
```

---

## 正确使用方式

### 1. equals() 的标准写法

```java
@Override
public boolean equals(Object o) {
    if (this == o) return true;                // 第一步：同一引用
    if (!(o instanceof Point p)) return false;  // 第二步：类型检查（Java 16+ 模式匹配）
    return x == p.x && y == p.y;             // 第三步：字段比较
}

// 如果类是可序列化的，还要注意：
// 子类可能覆写 equals，破坏对称性
// 解决方案：用 getClass() 替代 instanceof（但丧失了继承友好性）
```

### 2. hashCode() 与 equals() 必须同步修改

```java
// 如果修改了 equals 的字段，必须同步修改 hashCode
class Point {
    int x, y;
    // 如果加了 int z，必须同步修改 hashCode
    int z;

    @Override
    public int hashCode() {
        return Objects.hash(x, y, z);  // ← 必须同步修改
    }
}
```

### 3. toString() 不要暴露敏感信息

```java
class User {
    private String name;
    private char[] password;  // 密码用 char[] 而不用 String

    @Override
    public String toString() {
        // ❌ 不要把密码放进 toString
        // return "User{name=" + name + ", password=" + new String(password) + "}";
        return "User{name=" + name + "}";  // ✅ 隐藏敏感字段
    }
}
```

---

## 边界情况和坑

### 1. equals() 对称性破坏

```java
class Point {
    int x, y;
    @Override
    public boolean equals(Object o) {
        if (!(o instanceof Point)) return false;
        Point p = (Point) o;
        return x == p.x && y == p.y;
    }
}

class ColorPoint extends Point {
    Color color;
    @Override
    public boolean equals(Object o) {
        if (!(o instanceof ColorPoint)) return false;  // ← 更严格
        return super.equals(o) && color.equals(((ColorPoint)o).color);
    }
}

Point p = new Point(1, 2);
ColorPoint cp = new ColorPoint(1, 2, RED);

p.equals(cp);   // true（Point.equals 只比 x, y）
cp.equals(p);   // false（ColorPoint.equals 要求 instanceof ColorPoint）
// 对称性破坏了！
```

**解决方案**：继承层次中有自定义状态时，放弃 equals 继承，改用组合代替（Effective Java 第 10 条）。

### 2. hashCode() 碰撞不影响正确性，只影响性能

```java
// 即使 hashCode 碰撞，HashMap 仍然正确（桶内用 equals 二次确认）
// 但碰撞过多会导致链表/红黑树退化，性能急剧下降

// 最差的 hashCode：永远返回同一个值
@Override
public int hashCode() { return 42; }  // ← 所有对象落在同一个桶！
```

### 3. wait(long timeout) 的精度问题

```java
synchronized void doSomething() throws InterruptedException {
    wait(1000);  // 等待最多 1000ms，但可能提前返回
    // 虚假唤醒 + 系统时钟精度 → 实际等待时间可能略小于 1000ms
    // 正确做法：用 while + 时间戳
    long deadline = System.currentTimeMillis() + 1000;
    while (!condition) {
        long remaining = deadline - System.currentTimeMillis();
        if (remaining <= 0) break;
        wait(remaining);
    }
}
```

### 4. clone() 是浅拷贝

```java
// Object.clone() 默认是浅拷贝
class MyList implements Cloneable {
    int[] data;

    @Override
    public MyList clone() {
        try {
            MyList copy = (MyList) super.clone();  // 浅拷贝：data 引用相同
            copy.data = this.data.clone();       // ← 必须手动深拷贝引用类型
            return copy;
        } catch (CloneNotSupportedException e) {
            throw new AssertionError();
        }
    }
}
```

详见 [[01_Java核心/02_面向对象/克隆与拷贝|克隆与拷贝]] 中关于浅拷贝与深拷贝的完整分析。

### 5. getClass() 在 JDK 动态代理下的问题

```java
// 动态代理生成的类不是原类型
List<String> proxy = (List<String>) Proxy.newProxyInstance(...);

proxy.getClass() == ArrayList.class;  // false！代理类不是 ArrayList
proxy instanceof List;                  // true！接口检查正常工作

// 所以：覆写 equals 时尽量用 instanceof，不要用 getClass()
```
