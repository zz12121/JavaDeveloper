# 工具类与 Queue

> Collections 和 Arrays 是集合框架的「瑞士军刀」——排序、查找、包装、同步化都在这里。Queue/Deque 则补充了集合框架在「先进先出」和「优先级」场景下的缺失。

---

## 这个问题为什么存在？

集合框架提供了数据结构（List/Set/Map），但日常开发还需要大量**通用操作**：
- 排序、二分查找、洗牌、填充
- 不可变包装、同步化包装
- 数组与集合的互相转换

这些操作如果让每个开发者自己实现，既重复又容易出错。Java 把它们统一放在 `Collections` 和 `Arrays` 两个工具类里。

同时，`List` 不适合表达「先进先出」的语义（虽然可以用 `add(0)/remove(size-1)` 模拟，但语义不清晰）。`Queue` 接口专门解决队列场景。

---

## 它是怎么解决问题的？

### Collections 工具类

#### 排序

```java
List<String> list = new ArrayList<>(List.of("c", "a", "b"));
Collections.sort(list);  // 自然顺序排序：[a, b, c]

// 自定义排序
Collections.sort(list, Comparator.reverseOrder());  // 降序
```

**Collections.sort() 底层用的什么算法？**

```
JDK 7：归并排序（TimSort 的前身）
JDK 8+：TimSort（混合了归并排序和插入排序）

TimSort 的特点：
- 对部分有序的数据特别快（O(n) 级别）
- 对完全随机数据：O(n log n)
- 稳定排序（相等元素的相对顺序不变）
- 空间复杂度 O(n)

为什么不用快排？
- 快排不稳定（相等元素可能交换顺序）
- 快排最坏情况 O(n²)（虽然可以用随机化避免）
- TimSort 在实际数据中表现更好（真实数据通常有局部有序性）
```

#### 不可变包装

```java
List<String> mutable = new ArrayList<>(List.of("a", "b"));
List<String> immutable = Collections.unmodifiableList(mutable);

immutable.add("c");  // UnsupportedOperationException

// 注意：只是包装，原始 mutable list 修改后 immutable 视图也会变
mutable.add("c");
System.out.println(immutable);  // [a, b, c] — 变了！
```

**更安全的不可变集合（Java 9+）**：
```java
List<String> immutable = List.of("a", "b", "c");  // 真正的不可变
Set<String> set = Set.of("a", "b");
Map<String, Integer> map = Map.of("a", 1, "b", 2);
```

#### 同步化包装

```java
// 用 synchronized 包装，所有方法都加锁
List<String> syncList = Collections.synchronizedList(new ArrayList<>());
Map<String, String> syncMap = Collections.synchronizedMap(new HashMap<>());
```

**注意**：同步化包装的迭代器仍然需要手动同步：
```java
// ❌ 迭代器不是线程安全的
for (String s : syncList) { ... }  // 可能 ConcurrentModificationException

// ✅ 手动同步
synchronized (syncList) {
    for (String s : syncList) { ... }
}
```

这也是 `ConcurrentHashMap` 比同步化包装更好的原因——不需要手动同步迭代器。

#### 其他常用方法

```java
Collections.reverse(list);          // 反转
Collections.shuffle(list);          // 洗牌（随机打乱）
Collections.fill(list, "x");        // 填充
Collections.frequency(list, "a");   // 频率统计
Collections.binarySearch(list, "a"); // 二分查找（必须先排序）
Collections.disjoint(list1, list2);  // 是否无交集
```

### Arrays 工具类

```java
// 数组排序
int[] arr = {3, 1, 2};
Arrays.sort(arr);  // 双轴快速排序（对基本类型）

// 数组转 List
List<String> list = Arrays.asList("a", "b", "c");
// ⚠️ 返回固定大小的 List，不能 add/remove

// 数组转 List（可修改）
List<String> list = new ArrayList<>(Arrays.asList("a", "b", "c"));

// 数组填充
int[] arr2 = new int[5];
Arrays.fill(arr2, 42);  // [42, 42, 42, 42, 42]

// 数组比较
Arrays.equals(arr1, arr2);  // 逐元素比较

// 数组拷贝
int[] copy = Arrays.copyOf(arr, 10);        // 拷贝并扩容
int[] range = Arrays.copyOfRange(arr, 1, 3); // 拷贝子范围
```

**Arrays.sort() 对基本类型用快排，对对象用 TimSort**：
```
基本类型（int/double/char...）：双轴快速排序（Dual-Pivot Quicksort）
  - 不需要稳定排序（基本类型没有"相同但不同"的概念）
  - 快排比 TimSort 对基本类型更快

对象类型（Object[]）：TimSort
  - 需要稳定排序
  - 可能调用 Comparator.compare()，快排的比较次数更多
```

### Queue 接口

```
Queue（FIFO 队列）
  ├── LinkedList      — 同时实现 List 和 Deque，不推荐作为 Queue
  ├── PriorityQueue   — 优先级队列（堆实现）
  └── ArrayDeque      — 双端队列，推荐替代 LinkedList

Deque（双端队列，同时支持 FIFO 和 LIFO）
  ├── ArrayDeque      — 数组实现，推荐
  └── LinkedList      — 链表实现
```

#### PriorityQueue：优先级队列

```java
// 默认最小堆
PriorityQueue<Integer> pq = new PriorityQueue<>();
pq.offer(3); pq.offer(1); pq.offer(2);
pq.poll();  // 1（最小的先出）

// 最大堆
PriorityQueue<Integer> maxPq = new PriorityQueue<>(Comparator.reverseOrder());
maxPq.offer(3); maxPq.offer(1); maxPq.offer(2);
maxPq.poll();  // 3（最大的先出）
```

**PriorityQueue 底层是二叉小顶堆**：
```
插入 offer(E)：O(log n)，尾插后上浮
删除 poll()：O(log n)，删除堆顶后用末尾元素替代再下沉
查看 peek()：O(1)，直接返回堆顶

注意：PriorityQueue 不是有序的！
  pq.toArray() 的结果不是排序后的数组
  只有不断 poll() 才能按优先级取出
```

#### ArrayDeque：双端队列

```java
Deque<String> deque = new ArrayDeque<>();

// 队列操作（FIFO）
deque.offerLast("a");  // 入队
deque.pollFirst();     // 出队

// 栈操作（LIFO）
deque.push("a");   // 入栈（等价于 addFirst）
deque.pop();       // 出栈（等价于 removeFirst）
```

**ArrayDeque vs LinkedList**：
- ArrayDeque 基于数组，内存连续，CPU 缓存友好
- LinkedList 基于链表，节点离散，缓存不友好
- **ArrayDeque 作为栈和队列都优于 LinkedList**

---

## 深入原理

### Comparator vs Comparable

```java
// Comparable：类的自然排序（内部比较器）
class Person implements Comparable<Person> {
    int age;
    public int compareTo(Person o) {
        return Integer.compare(this.age, o.age);
    }
}

// Comparator：外部定义排序规则
Comparator<Person> byName = Comparator.comparing(Person::getName);
Comparator<Person> byAgeDesc = Comparator.comparing(Person::getAge).reversed();
```

**区别与使用场景**：

| 维度 | Comparable | Comparator |
|------|-----------|------------|
| 包位置 | `java.lang` | `java.util` |
| 定义位置 | 类内部（修改源码）| 外部独立定义 |
| 方法 | `compareTo(T o)` | `compare(T o1, T o2)` |
| 数量 | 一个类只能有一个自然排序 | 可以有无数个 Comparator |
| 使用方式 | `Collections.sort(list)` | `Collections.sort(list, comp)` |

**优先级**：当两者都存在时，`Comparator` 优先于 `Comparable`。

### Collections.sort() 的两个参数版本

```java
// 单参数：用元素的自然排序（Comparable）
Collections.sort(list);  // list 中的元素必须实现 Comparable

// 双参数：用传入的 Comparator
Collections.sort(list, Comparator.comparing(Person::getAge));
```

### 迭代器的设计模式

```
Iterator 的作用：统一遍历接口，不暴露集合内部结构

List 迭代器：ArrayList 内部用数组，LinkedList 用链表
  → 但迭代器接口一样（hasNext/next/remove）
  → 调用方不需要知道底层结构

ListIterator：双向迭代器（Iterator 的增强版）
  → hasPrevious() / previous()
  → add(E) / set(E)
  → 只有 List 才有 ListIterator
```

---

## 正确使用方式

### 选型决策

```
需要队列？
├── 普通队列（FIFO） → ArrayDeque
├── 优先级队列 → PriorityQueue
├── 双端队列 → ArrayDeque
├── 高并发队列 → ConcurrentLinkedQueue（无界）/ LinkedBlockingQueue（有界）
└── 生产者-消费者 → BlockingQueue 实现（ArrayBlockingQueue / LinkedBlockingQueue）

需要排序？
├── 对 List 排序 → Collections.sort() 或 list.sort()
├── 对数组排序 → Arrays.sort()
├── 自定义排序 → Comparator.comparing() 链式调用
└── 不可变排序 → Stream.sorted() 返回新集合

需要转换？
├── 数组 → List → new ArrayList<>(Arrays.asList(arr))
├── List → 数组 → list.toArray(new String[0])
├── 数组 → Stream → Arrays.stream(arr)
└── Collection → 不可变 → List.of() / Set.of() / Map.of()
```

### Comparator 的链式组合

```java
// 先按 age 升序，age 相同再按 name 升序
Comparator<Person> comp = Comparator
    .comparing(Person::getAge)
    .thenComparing(Person::getName);

// 先按 age 降序
Comparator<Person> comp = Comparator
    .comparing(Person::getAge, Comparator.reverseOrder());

// 处理 null 值（null 排在最后）
Comparator<String> comp = Comparator.nullsLast(Comparator.naturalOrder());
```

### 数组与集合转换的正确姿势

```java
// 数组 → List
String[] arr = {"a", "b", "c"};
List<String> list = new ArrayList<>(Arrays.asList(arr));  // ✅ 可修改
List<String> list2 = List.of(arr);  // ✅ 不可变（Java 9+）

// List → 数组
String[] arr2 = list.toArray(new String[0]);  // ✅ 正确
// 不推荐：list.toArray() 返回 Object[]，需要强转
```

---

## 边界情况和坑

### 坑 1：Arrays.asList() 返回固定大小 List

```java
int[] arr = {1, 2, 3};
List<int[]> list = Arrays.asList(arr);  // ⚠️ List<int[]>，不是 List<Integer>
// 基本类型数组不会自动装箱！

Integer[] arr2 = {1, 2, 3};
List<Integer> list2 = Arrays.asList(arr2);  // ✅ List<Integer>

// 另一个陷阱
String[] arr3 = {"a", "b"};
List<String> list3 = Arrays.asList(arr3);
list3.add("c");  // ❌ UnsupportedOperationException
list3.set(0, "x");  // ✅ 可以修改已有元素
```

**成因**：`Arrays.asList()` 返回的是固定大小的内部类 `Arrays.ArrayList`，不支持 `add/remove`，但 `set` 可以（因为它修改的是原数组）。

### 坑 2：Collections.sort() 修改原 List

```java
List<String> list = new ArrayList<>(List.of("c", "a", "b"));
List<String> sorted = Collections.sort(list);  // ❌ 编译错误
// sort 返回 void，直接修改原 List

// 需要保留原 List，先拷贝
List<String> original = new ArrayList<>(list);
Collections.sort(original);
```

### 坑 3：PriorityQueue 不是有序集合

```java
PriorityQueue<Integer> pq = new PriorityQueue<>();
pq.offer(3); pq.offer(1); pq.offer(2);
System.out.println(pq);  // [1, 3, 2] — 不是排序后的！
// 内部是堆结构，只保证 poll() 返回最小元素
```

**成因**：PriorityQueue 底层是堆，不是有序数组。`toArray()` 或 `toString()` 返回的是堆的内部结构，不是排序结果。

**需要有序结果**：
```java
List<Integer> sorted = new ArrayList<>();
while (!pq.isEmpty()) {
    sorted.add(pq.poll());  // 逐个取出才是排序的
}
```

### 坑 4：toArray(T[]) 的类型安全问题

```java
List<String> list = new ArrayList<>(List.of("a", "b"));
String[] arr = list.toArray(new String[0]);  // ✅ 正确

// 危险写法
Object[] arr2 = list.toArray();  // 返回 Object[]
String s = (String) arr2[0];     // 需要强转，不安全
```

**为什么 `new String[0]` 比 `new String[list.size()]` 更好？** 现代 JVM 对空数组有优化，`new String[0]` 比 `new String[list.size()]` 更快（不需要分配和填充数组，JVM 内部会直接分配正确大小的数组）。

### 坑 5：Collections.max() 与空集合

```java
List<String> list = new ArrayList<>();
Collections.max(list);  // ❌ NoSuchElementException
```

**成因**：空集合没有最大值，直接抛异常。需要先判空：
```java
if (!list.isEmpty()) {
    String max = Collections.max(list);
}
```
