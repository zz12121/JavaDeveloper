# List 与 Set

> List 保证插入顺序和索引访问，Set 保证元素唯一性。两者都继承 Collection，但设计目标和底层实现有本质区别。

---

## 这个问题为什么存在？

数组是最基础的顺序容器，但它有两个硬伤：
1. **定长**：创建时必须指定大小，无法动态扩容
2. **类型单一**：早期只能存相同类型（泛型出现前存 Object，取时强转有风险）

集合框架的 `List` 和 `Set` 解决的是：**用统一的接口抽象「序列」和「不重复集合」两种语义，底层用不同数据结构实现性能最优化**。

---

## 它是怎么解决问题的？

### List 接口

List 的核心契约：**有序、可重复、可索引访问**。

```
List 的核心操作：
- add(E) / add(int, E) — 尾部追加 / 指定位置插入
- get(int) — O(1) 随机访问（对数组实现而言）
- remove(int) / remove(Object) — 按索引 / 按值删除
- indexOf(Object) — 线性查找
```

#### ArrayList：动态数组

```java
// 底层结构
transient Object[] elementData;  // 不序列化空槽位
private int size;                // 实际元素个数（不是数组长度）

// 扩容机制
int oldCapacity = elementData.length;
int newCapacity = oldCapacity + (oldCapacity >> 1);  // 1.5 倍
```

**为什么是 1.5 倍而不是 2 倍？**
```
2 倍扩容：内存浪费严重，长期运行后平均 50% 空间空闲
1.5 倍：内存利用率更高，是「时间 vs 空间」的经典 trade-off
      选择 1.5 是因为它接近黄金比例，多次扩容后内存碎片较少
```

**为什么 elementData 用 transient 修饰？**
ArrayList 序列化时只序列化实际元素（size 个），不序列化空槽位。`writeObject` 方法手动控制序列化过程，节省空间。

#### LinkedList：双向链表

```java
// 底层结构（JDK 源码）
transient Node<E> first;
transient Node<E> last;

static class Node<E> {
    E item;
    Node<E> next;
    Node<E> prev;
}
```

**ArrayList vs LinkedList 性能对比**：

| 操作 | ArrayList | LinkedList | 说明 |
|------|-----------|-------------|------|
| get(int) | O(1) | O(n) | LinkedList 必须遍历 |
| add(E) 尾部 | O(1) 均摊 | O(1) | 两者都是 |
| add(int, E) 插入 | O(n) | O(n) | LinkedList 找位置 O(n)，插入本身 O(1) |
| remove(int) | O(n) | O(n) | 同理 |
| 遍历 | 快（数组连续，CPU 缓存友好）| 慢（节点离散，缓存命中差）| 这是最关键的性能差异 |

**为什么现实中几乎不用 LinkedList？**
- CPU 缓存局部性：数组连续内存，预取效果好；链表节点离散，cache miss 严重
- 大多数「频繁插入删除」场景实际是尾部追加，ArrayList 更快
- 真实适合 LinkedList 的场景：LRU 缓存（需要在中间 O(1) 移动节点）

#### Vector：线程安全的动态数组

```java
// Vector 的方法几乎都加了 synchronized
public synchronized boolean add(E e) { ... }
public synchronized E get(int index) { ... }
```

**为什么不用 Vector？**
- `synchronized` 锁整个方法，并发度极低
- 扩容是 2 倍（比 ArrayList 更浪费空间）
- 替代方案：`CopyOnWriteArrayList`（读完全无锁）或 `Collections.synchronizedList()`

### Set 接口

Set 的核心契约：**不包含重复元素**。

Set 的所有实现都**依赖 Map**：

```java
// HashSet 源码本质
private transient HashMap<E, Object> map;
private static final Object PRESENT = new Object();  // 哑 value

public boolean add(E e) {
    return map.put(e, PRESENT) == null;  // key 唯一 → 天然去重
}

public boolean contains(Object o) {
    return map.containsKey(o);  // 委托给 HashMap
}
```

**为什么用组合而不是继承？** HashSet 持有 HashMap 实例，自己只暴露 Set 接口。这是「组合优于继承」的经典案例——继承会暴露 HashMap 的所有方法，破坏 Set 的语义约束。

#### 三种 Set 实现对比

| 实现 | 底层 | 顺序 | 查找/插入 | 使用场景 |
|------|------|------|----------|---------|
| HashSet | HashMap | 无序（本质是 hash 槽位顺序）| O(1) 均摊 | 默认选择 |
| LinkedHashSet | LinkedHashMap | 插入顺序 | O(1) | 需要保持插入顺序 |
| TreeSet | TreeMap（红黑树）| 自然顺序或 Comparator 顺序 | O(log n) | 需要有序遍历 |

#### TreeSet 的排序机制

```java
// 方式 1：元素实现 Comparable
class Person implements Comparable<Person> {
    int age;
    public int compareTo(Person o) {
        return Integer.compare(this.age, o.age);
    }
}

// 方式 2：传入 Comparator
TreeSet<Person> set = new TreeSet<>(
    Comparator.comparing(Person::getAge)
);
```

**compareTo 与 equals 的一致性问题**：
```java
// 危险：compareTo 和 equals 不一致
class Person {
    String name;
    int age;
    public int compareTo(Person o) {
        return Integer.compare(this.age, o.age);  // 只比 age
    }
    // equals 比 name + age → 不一致！
}
```
当 `compareTo` 和 `equals` 不一致时，`TreeSet` 认为「age 相同的两个 Person 是相等的」（不会插入重复的 age），但 `equals` 认为它们不相等。这在混合使用 `Set` 实现时会导致诡异 bug。

---

## 深入原理

### ArrayList 的序列化机制

```java
// ArrayList 的自定义序列化
private void writeObject(java.io.ObjectOutputStream s)
    throws java.io.IOException {
    s.defaultWriteObject();  // 写 size
    s.writeInt(size);         // 再写一次 size（用于验证）
    for (int i = 0; i < size; i++) {
        s.writeObject(elementData[i]);  // 只写实际元素
    }
}
```

**为什么不用默认序列化？** 默认序列化会把整个 `elementData` 数组（包括空槽位）全部写出，浪费大量空间。 transient + 自定义 `writeObject/readObject` 只序列化实际元素。

### LinkedList 的「假 O(1) 插入」

很多人说 LinkedList 插入是 O(1)，这是**误导**：

```java
// 在中间插入：需要先找到位置，O(n)
list.add(50000, "x");  // LinkedList O(n)，ArrayList 也是 O(n)

// 在头部插入：才是真正的 O(1)
list.add(0, "x");  // LinkedList O(1)，ArrayList O(n)
```

真正让 LinkedList 头部插入有意义的场景是 **Deque**（双端队列），`LinkedList` 实现了 `Deque` 接口。

### fail-fast 机制

```java
// 常见错误写法
List<String> list = new ArrayList<>();
list.add("A"); list.add("B");
for (String s : list) {       // 底层用 Iterator
    if ("A".equals(s)) {
        list.remove(s);        // ConcurrentModificationException!
    }
}

// 正确写法
Iterator<String> it = list.iterator();
while (it.hasNext()) {
    if ("A".equals(it.next())) {
        it.remove();           // 用迭代器自身的 remove
    }
}
```

**fail-fast 的实现原理**：
```java
// ArrayList 的 Iterator 内部
int expectedModCount = modCount;  // 迭代器创建时记录

public E next() {
    checkForComodification();
    // ...
}

final void checkForComodification() {
    if (modCount != expectedModCount)
        throw new ConcurrentModificationException();
}
```

`modCount` 是 ArrayList 的修改计数器，每次 `add/remove` 都自增。迭代器创建时记录 `expectedModCount`，迭代过程中如果发现不一致，立即抛出异常。

**为什么 fail-fast 是合理的？** 它不是为了「在并发下安全使用」，而是检测程序员的 bug（用集合自己的引用修改了集合，同时在迭代它）。这种 bug 如果静默忽略，会导致极其难追踪的数据不一致。

---

## 正确使用方式

### 选型决策

```
需要 List？
├── 高随机访问（get 多） → ArrayList（默认选这个）
├── 需要在头部频繁插入/删除 → ArrayDeque（比 LinkedList 好）
├── 读多写少的高并发 → CopyOnWriteArrayList
└── 几乎不用 LinkedList（除非实现特定数据结构）

需要 Set？
├── 普通去重 → HashSet（默认选这个）
├── 需要保持插入顺序 → LinkedHashSet
├── 需要有序遍历 → TreeSet（注意 compareTo 与 equals 一致性）
└── 高并发去重 → ConcurrentHashMap.newKeySet()
```

### ArrayList 初始化容量优化

```java
// ❌ 坏写法：默认容量 10，频繁扩容
List<String> list = new ArrayList<>();
for (int i = 0; i < 100000; i++) {
    list.add("item" + i);  // 触发多次扩容
}

// ✅ 好写法：一次性分配足够容量
List<String> list = new ArrayList<>(100000);  // 指定初始容量
for (int i = 0; i < 100000; i++) {
    list.add("item" + i);  // 无扩容开销
}
```

### 遍历方式的选择

```java
List<String> list = new ArrayList<>();

// 1. for-each（底层用 Iterator，最简洁）
for (String s : list) {
    System.out.println(s);
}

// 2. 普通 for（ArrayList 最快，random access）
for (int i = 0; i < list.size(); i++) {
    System.out.println(list.get(i));
}

// 3. Iterator（需要迭代中删除元素时用）
Iterator<String> it = list.iterator();
while (it.hasNext()) {
    String s = it.next();
    if (s.isEmpty()) it.remove();
}

// 4. Stream（函数式处理）
list.stream().filter(s -> !s.isEmpty()).forEach(System.out::println);
```

**选择原则**：
- ArrayList：普通 for 循环最快（CPU 缓存友好）
- LinkedList：必须用迭代器，不要用 `get(i)` 遍历（O(n²)！）
- 需要过滤/映射：用 Stream，可读性更好

---

## 边界情况和坑

### 坑 1：LinkedList 用 get(i) 遍历 → O(n²)

```java
// ❌ 灾难写法
LinkedList<String> list = new LinkedList<>();
for (int i = 0; i < list.size(); i++) {
    System.out.println(list.get(i));  // 每次 get 都是 O(n)，总共 O(n²)
}

// ✅ 正确写法
for (String s : list) {  // 用迭代器
    System.out.println(s);
}
```

**成因**：LinkedList 的 `get(i)` 需要从头（或尾）遍历到位置 i，单次 O(n)。用 for-i 循环调用 `get(i)`，总时间复杂度 O(n²)。

### 坑 2：Arrays.asList() 返回的 List 不能 add/remove

```java
List<String> list = Arrays.asList("a", "b", "c");
list.add("d");  // ❌ UnsupportedOperationException
```

**成因**：`Arrays.asList()` 返回的是 `Arrays.ArrayList`（内部类），不是 `java.util.ArrayList`。这个内部类**没有实现 add/remove**，大小固定。

**解决方案**：包一层真正的 ArrayList：
```java
List<String> list = new ArrayList<>(Arrays.asList("a", "b", "c"));
```

### 坑 3：subList 是原 List 的「视图」，不是副本

```java
List<Integer> original = new ArrayList<>(List.of(1, 2, 3, 4, 5));
List<Integer> sub = original.subList(0, 3);  // [1, 2, 3]
sub.clear();  // 清空子列表
System.out.println(original);  // [4, 5] — 原 List 也被修改了！
```

**成因**：`subList` 返回的是原 List 的视图（通过偏移量访问原 List 的元素），不是独立的副本。对子列表的修改会反映到原 List 上。

**解决方案**：需要独立副本时用构造函数：
```java
List<Integer> copy = new ArrayList<>(original.subList(0, 3));
```

### 坑 4：hashCode/equals 与 HashSet 的幽灵 bug

```java
class Person {
    String name;
    @Override public boolean equals(Object o) { ... }
    // 忘了重写 hashCode！
}

Person p = new Person("Alice");
Set<Person> set = new HashSet<>();
set.add(p);
System.out.println(set.contains(p));  // false！明明加进去了
```

**成因**：HashSet 先根据 `hashCode()` 找桶，再在桶里用 `equals()` 比较。`equals` 相等但 `hashCode` 不同 → 对象被放到不同的桶里，`contains` 找不到。

**规则**：**重写 equals 必须重写 hashCode**，且相等的对象必须有相等的 hashCode。

### 坑 5：TreeSet 中可变对象修改后顺序失效

```java
class Person implements Comparable<Person> {
    String name;
    int age;
    public int compareTo(Person o) {
        return Integer.compare(this.age, o.age);
    }
}

TreeSet<Person> set = new TreeSet<>();
Person p = new Person("Alice", 20);
set.add(p);
p.age = 25;  // 修改了参与排序的字段！
set.contains(p);  // false！内部结构已经不对了
```

**成因**：TreeSet 底层是红黑树，插入时根据 `compareTo` 决定位置。插入后修改排序字段，树的结构不会自动调整，导致查找失败。

**解决方案**：存入 TreeSet 的对象应该是**不可变对象**，或者至少保证参与排序的字段不会被修改。
