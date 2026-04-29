# CopyOnWriteArrayList

> CopyOnWriteArrayList 是"读写分离"思想在集合中的经典实现。它让读操作完全无锁，代价是写操作需要复制整个数组。理解这个 tradeoff，比记住 API 重要得多。

---

## 这个问题为什么存在？

### ArrayList 的并发痛点

```
ArrayList 线程不安全，并发修改会导致：
1. 数组越界：两个线程同时 add，size 只加了 1，但两个元素都写入了
2. 脏读：迭代过程中另一个线程修改了数组
3. ConcurrentModificationException：fail-fast 机制直接抛异常

用 Collections.synchronizedList() 包一层？
→ 整个 List 一把锁，读操作也要加锁
→ 高并发读场景下，99% 的锁竞争是无意义的
→ 两个线程同时读不同位置，完全可以并发，但被锁串行化了
```

```
核心矛盾：
- 读操作天然安全（不修改数据），不需要加锁
- 写操作需要互斥，但频率远低于读
→ 能不能让读操作完全无锁，只对写操作加锁？

答案：CopyOnWriteArrayList（写时复制）
```

---

## 它是怎么解决问题的？

### 核心思想：读写分离

```
CopyOnWriteArrayList 的内部结构：

  volatile Object[] array  —  当前数组引用（volatile 保证可见性）

读操作：直接读 array 引用，不加锁
  读线程永远在读某个"版本"的数组

写操作：复制 + 修改 + 替换
  1. 加锁（synchronized，保证写操作互斥）
  2. 复制当前数组到新数组
  3. 在新数组上做修改
  4. 把 array 引用指向新数组（volatile 写）
  5. 释放锁

  array ──→ [A, B, C]          ← 读线程读这个版本（不受影响）
     │
     └──→  [A, B, C, D]        ← 写线程创建新版本，写完后替换引用
```

### 源码关键分析

```java
// 读操作：不加锁，O(1)
public E get(int index) {
    return getArray()[index];   // getArray() = return array（volatile 读）
}

// 写操作：加锁 + 复制 + 替换，O(n)
public boolean add(E e) {
    final ReentrantLock lock = this.lock;
    lock.lock();                            // 写互斥
    try {
        Object[] elements = getArray();     // 读当前数组
        int len = elements.length;
        Object[] newElements = Arrays.copyOf(elements, len + 1);  // 复制
        newElements[len] = e;               // 在新数组上修改
        setArray(newElements);              // volatile 写，发布新数组
        return true;
    } finally {
        lock.unlock();
    }
}

// set 操作：也是复制
public E set(int index, E element) {
    final ReentrantLock lock = this.lock;
    lock.lock();
    try {
        Object[] elements = getArray();
        E oldValue = get(elements, index);
        if (oldValue != element) {
            int len = elements.length;
            Object[] newElements = Arrays.copyOf(elements, len);
            newElements[index] = element;
            setArray(newElements);
        } else {
            // 要设置的值和当前值相同，不需要复制
            // 但注意：这里不修改 volatile 引用，不触发 happens-before
            // 这是 JDK 的一个优化，但不影响正确性（volatile 读保证可见性）
            setArray(elements);
        }
        return oldValue;
    } finally {
        lock.unlock();
    }
}

// remove 操作：同样是复制
public E remove(int index) {
    final ReentrantLock lock = this.lock;
    lock.lock();
    try {
        Object[] elements = getArray();
        int len = elements.length;
        E oldValue = get(elements, index);
        int numMoved = len - index - 1;
        if (numMoved == 0)
            setArray(Arrays.copyOf(elements, len - 1));  // 删除最后一个
        else {
            Object[] newElements = new Object[len - 1];
            System.arraycopy(elements, 0, newElements, 0, index);
            System.arraycopy(elements, index + 1, newElements, index, numMoved);
            setArray(newElements);
        }
        return oldValue;
    } finally {
        lock.unlock();
    }
}
```

### 迭代器：快照迭代

```java
// COWArrayList 的迭代器
public Iterator<E> iterator() {
    return new COWIterator<E>(getArray(), 0);
}

// 迭代器内部持有数组的快照引用
static final class COWIterator<E> implements ListIterator<E> {
    private final Object[] snapshot;  // 迭代开始时的数组快照
    private int cursor;

    COWIterator(Object[] elements, int initialCursor) {
        snapshot = elements;  // 保存快照
        cursor = initialCursor;
    }

    public E next() {
        return (E) snapshot[cursor++];
    }

    public void remove() {
        throw new UnsupportedOperationException();  // 快照迭代器不支持修改
    }
}
```

```
快照迭代器的行为：
- 创建迭代器时，拷贝一份当前数组的引用
- 迭代过程中，list 的任何修改对迭代器不可见
- 不会抛 ConcurrentModificationException
- 不支持 remove/add 操作

这和 ArrayList 的 fail-fast 迭代器完全相反：
- ArrayList 迭代时修改 → ConcurrentModificationException
- COWArrayList 迭代时修改 → 迭代器看不到修改，但不报错
```

### 内存可见性保证

```
关键问题：写线程创建的新数组，读线程能立即看到吗？

答案：能，因为 volatile

写线程：
  setArray(newElements);  // volatile 写
  → 所有之前的写操作（newElements 的初始化）对后续读线程可见

读线程：
  getArray()  // volatile 读
  → 看到 volatile 写之后的新数组引用
  → 通过 volatile 的 happens-before 关系，看到数组中的所有元素

这就是为什么 array 必须用 volatile 声明：
  transient volatile Object[] array;
```

---

## 和相似方案的区别

### CopyOnWriteArrayList vs synchronizedList vs Vector

```
              COWArrayList      synchronizedList     Vector
────────────────────────────────────────────────────────────
读性能         极好（无锁）       差（加锁）           差（加锁）
写性能         差（O(n) 复制）    好（O(1) 加锁）      好（O(1) 加锁）
读时写         读旧数据（快照）    等待写完成           等待写完成
迭代器         快照（不报错）     需要手动加锁         fail-fast
迭代时修改     看不到修改         需要重新获取迭代器    ConcurrentModificationException
null 元素      ✅ 允许            ✅ 允许             ✅ 允许
内存开销       大（每次写复制）    正常                正常
```

### CopyOnWriteArrayList vs CopyOnWriteArraySet

```
CopyOnWriteArraySet 内部就是用 CopyOnWriteArrayList 实现的：

public class CopyOnWriteArraySet<E> implements Set<E> {
    private final CopyOnWriteArrayList<E> al;
    // add() → al.addIfAbsent(e)（去重）
}

所以 Set 的性能 = List 的 addIfAbsent 性能
→ addIfAbsent 需要先遍历检查是否存在，O(n)
→ 如果大量元素，Set 的 add 性能很差

结论：CopyOnWriteArraySet 只适合小集合 + 读多写极少
```

---

## 正确使用方式

### 适用场景

```
✅ 读多写极少（写操作占总操作 < 5%）

典型场景：
1. 事件监听器列表
   → 监听器注册一次，每次事件都遍历所有监听器
   → add/remove 极少，forEach 极多

2. 白名单/黑名单
   → 启动时加载，运行时基本只读
   → 偶尔有配置更新

3. 配置信息列表
   → 定期从配置中心拉取，替换整个列表
   → 读请求远远多于配置更新
```

### 典型代码

```java
// 场景 1：事件监听器
public class EventBus {
    // 监听器列表：注册少，通知多
    private final CopyOnWriteArrayList<EventListener> listeners =
        new CopyOnWriteArrayList<>();

    public void register(EventListener listener) {
        listeners.add(listener);
    }

    public void unregister(EventListener listener) {
        listeners.remove(listener);
    }

    public void publishEvent(Event event) {
        // 遍历时不需要加锁，也不会 ConcurrentModificationException
        for (EventListener listener : listeners) {
            listener.onEvent(event);
        }
    }
}

// 场景 2：白名单
public class AccessControl {
    private final CopyOnWriteArrayList<String> whiteList = new CopyOnWriteArrayList<>();

    // 配置更新（低频）
    @Scheduled(fixedRate = 60000)
    public void refreshWhiteList() {
        List<String> newList = configService.getWhiteList();
        whiteList.clear();
        whiteList.addAll(newList);
    }

    // 访问检查（高频）
    public boolean isAllowed(String ip) {
        return whiteList.contains(ip);
    }
}
```

---

## 边界情况和坑

### 坑 1：写操作内存开销

```
每次 add/remove 都要复制整个数组：

数组大小 10 万，add 一个元素：
→ 复制 10 万个引用（约 800KB）
→ 如果每秒 100 次 add → 每秒 80MB 新数组
→ 老数组等 GC 回收 → GC 压力巨大

结论：大数组 + 频繁写 = 灾难
监控指标：留意 Young GC 频率和老年代增长速度
```

### 坑 2：迭代器看不到最新数据

```java
CopyOnWriteArrayList<String> list = new CopyOnWriteArrayList<>();
list.add("A");

// 线程 1：迭代
for (String s : list) {
    System.out.println(s);  // 只能看到 "A"
    // 如果线程 2 此时 add("B")，这个迭代器看不到 "B"
}

// 如果业务需要"读到最新"：
// 不要用迭代器遍历，用 list.get(i) 每次都从最新数组读
for (int i = 0; i < list.size(); i++) {
    System.out.println(list.get(i));  // 每次都 volatile 读，能看到最新
}
```

### 坑 3：addIfAbsent 的 O(n²) 问题

```java
// addIfAbsent 内部：先遍历检查是否存在，再 add
list.addIfAbsent("x");  // 遍历 O(n) + 复制 O(n) = O(n)

// 批量去重添加更危险
list.addAllAbsent(otherList);  // O(n × m)！
// 对 otherList 中每个元素，都遍历当前 list

// 如果需要去重的并发集合，考虑 ConcurrentHashMap.newKeySet()
```

### 坑 4：和 for-each 的配合

```java
// ✅ 安全：for-each 用迭代器，快照读，不会 CME
for (String s : cowList) {
    process(s);
}

// ✅ 安全：forEach 方法
cowList.forEach(this::process);

// ✅ 安全：stream
cowList.stream().forEach(this::process);

// ❌ 危险：普通 for 循环 + size()
for (int i = 0; i < cowList.size(); i++) {
    // size() 返回当前最新数组的长度
    // 如果其他线程在 add/remove，size 可能变化
    // 可能 IndexOutOfBoundsException 或漏读/重复读
    System.out.println(cowList.get(i));
}
```

---

## 我的理解（面试考点）

### 高频面试题

```
Q1: CopyOnWriteArrayList 的原理？
→ 写时复制：读不加锁直接读，写时加锁复制新数组再替换引用
→ volatile 数组引用保证写操作对读线程的可见性
→ 读性能极好，写性能差（O(n) 复制）

Q2: 什么场景下用 CopyOnWriteArrayList？
→ 读多写极少（写 < 5%）
→ 事件监听器、白名单、配置列表
→ 不适合高频写入场景（GC 压力大）

Q3: 迭代器的特点？
→ 快照迭代器，创建时固定，看不到后续修改
→ 不抛 ConcurrentModificationException
→ 不支持 remove 操作

Q4: 和 synchronizedList 的区别？
→ 读性能：COW 远好于 synchronized（无锁 vs 加锁）
→ 写性能：synchronized 远好于 COW（O(1) vs O(n)）
→ 内存：COW 每次写都复制，synchronized 无额外开销

Q5: CopyOnWriteArraySet 的实现原理？
→ 内部用 CopyOnWriteArrayList 实现
→ add 调用 addIfAbsent 去重
→ 只适合小集合
```

### 一句话总结

```
CopyOnWriteArrayList 是"用空间换时间"的典型案例：
牺牲写操作的性能和内存，换取读操作的完全无锁。
核心判断标准：如果读远多于写，它是最佳选择；
如果写操作频繁，它会成为系统的性能瓶颈。
```
