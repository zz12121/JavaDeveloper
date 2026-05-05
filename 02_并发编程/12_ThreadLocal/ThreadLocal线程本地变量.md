# ThreadLocal 线程本地变量

## 这个问题为什么存在？

> 多个线程要共享一个变量，但又希望**每个线程有自己独立的副本**，互相不干扰。

典型场景：
- **数据库连接**：每个线程需要自己的 `Connection`，不能共享（线程不安全）
- **用户会话信息**：每个请求（线程）有自己的 `userId`，不应该和其他请求混在一起
- **SimpleDateFormat**：线程不安全，每个线程用自己的一份，避免 `synchronized`

没有 `ThreadLocal` 之前，解决办法是：
- 每层方法都把 `userId` 传参（麻烦，破坏接口）
- 用 `Map<Thread, Value>` + `synchronized`（性能差）

`ThreadLocal` 提供了一种**线程隔离的变量存储机制**，每个线程访问自己的副本，完全无锁。

---

## 它是怎么解决问题的？

### 核心机制：Thread → ThreadLocalMap

```
每个 Thread 对象内部：
┌───────────────────┐
│ Thread             │
│  ├── id           │
│  ├── name         │
│  └── threadLocals │──→ ThreadLocalMap（自定义哈希表）
│       ┌────────┐  │
│       │Entry[] │  │  （桶数组，长度必须为 2 的幂）
│       │key=弱引用│ │
│       │value=强  │ │
│       └────────┘  │
└───────────────────┘

ThreadLocal 只是一个「key」：
  threadLocalA.get()
    → 找到当前线程的 ThreadLocalMap
    → 以 threadLocalA 为 key，查到对应的 value
```

**关键点**：`ThreadLocal` **不存数据**，数据存在每个 `Thread` 对象的 `threadLocals` 字段里。  
`ThreadLocal` 只是提供「访问入口」（像钥匙，不是保险箱）。

---

### 源码关键路径：set(T value)

```java
// ThreadLocal.java
public void set(T value) {
    Thread t = Thread.currentThread();
    ThreadLocalMap map = getMap(t);  // return t.threadLocals
    if (map != null)
        map.set(this, value);       // this = 当前 ThreadLocal 对象
    else
        createMap(t, value);        // 第一次，创建 ThreadLocalMap
}
```

**`ThreadLocalMap.set()` 的核心逻辑**（类似 HashMap，但有区别）：

```java
// ThreadLocalMap（ThreadLocal 的内部类）
static class Entry extends WeakReference<ThreadLocal<?>> {
    Object value;
    Entry(ThreadLocal<?> k, Object v) {
        super(k);   // key 是弱引用（关键设计！）
        value = v;
    }
}

private void set(ThreadLocal<?> key, Object value) {
    Entry[] tab = table;
    int len = tab.length;
    int i = key.threadLocalHashCode & (len-1);  // 哈希定位

    // 线性探测（不像 HashMap 用链表）
    for (Entry e = tab[i]; e != null; e = tab[i = nextIndex(i, len)]) {
        ThreadLocal<?> k = e.get();
        if (k == key) {
            e.value = value;  // 找到了，覆盖
            return;
        }
        if (k == null) {
            replaceStaleEntry(key, value, i);  // 清理过期 Entry
            return;
        }
    }

    tab[i] = new Entry(key, value);
    int sz = ++size;
    if (!cleanSomeSlots(i, sz) && sz >= threshold)
        rehash();   // 扩容（2倍）
}
```

**为什么用线性探测，不用链表？**

> `ThreadLocalMap` 的设计目标是**小型哈希表**（每个线程的 `ThreadLocal` 数量通常很少）。  
> 线性探测在**低负载因子**下性能很好（缓存友好，没有指针跳转）。  
> 哈希冲突用 `nextIndex(i, len)` 顺序找下一个桶（开放寻址）。

---

### 源码关键路径：get()

```java
public T get() {
    Thread t = Thread.currentThread();
    ThreadLocalMap map = getMap(t);
    if (map != null) {
        ThreadLocalMap.Entry e = map.getEntry(this);
        if (e != null) {
            @SuppressWarnings("unchecked")
            T result = (T)e.value;
            return result;
        }
    }
    return setInitialValue();  // 第一次 get，调 initialValue()
}
```

**`initialValue()`**：自定义初始值

```java
// 匿名内部类（JDK 8 之前）
ThreadLocal<Integer> count = new ThreadLocal<Integer>() {
    @Override protected Integer initialValue() { return 0; }
};

// JDK 8：lambda
ThreadLocal<Integer> count = ThreadLocal.withInitial(() -> 0);
```

---

## 它和相似方案的本质区别是什么？

### ThreadLocal vs synchronized

| 维度 | ThreadLocal | synchronized |
|------|--------------|---------------|
| **目的** | 线程隔离（各用各的） | 线程互斥（排队访问） |
| **并发策略** | 「避免共享」 | 「共享 + 加锁」 |
| **性能** | 无锁，极高 | 有锁开销（虽然锁升级后好了很多） |
| **适用场景** | 每个线程要独立副本 | 多个线程操作同一资源 |

**典型误区**：以为 `ThreadLocal` 能解决线程安全问题 → ❌

```java
// ❌ 误解：ThreadLocal 解决线程安全
AtomicInteger count = new AtomicInteger(0);
ThreadLocal<AtomicInteger> local = ThreadLocal.withInitial(() -> count);

// 两个线程 get() 拿到的是「同一个 AtomicInteger」！
// ThreadLocal 只保证「每个线程拿到的是自己副本」，
// 但如果你放的本身就是共享对象，那没有用。
```

---

### ThreadLocal vs InheritableThreadLocal vs TransmittableThreadLocal

| | ThreadLocal | InheritableThreadLocal | TransmittableThreadLocal |
|--|-------------|------------------------|--------------------------|
| **子线程继承父线程的值** | ❌ | ✅ | ✅ |
| **线程池场景** | ❌（线程是复用的） | ❌（线程池线程不是「子线程」） | ✅（每次提交任务时复制） |
| **使用场景** | 普通多线程 | `new Thread()` 创建子线程 | 线程池 + 需要传递上下文 |

**为什么 `InheritableThreadLocal` 在线程池里没用？**

> 线程池的线程是**预先创建的**，不是「子线程」。  
> `InheritableThreadLocal` 只在 `Thread.init()`（创建线程时）复制父线程的 `inheritableThreadLocals`。  
> 线程池提交任务时，不会触发这个复制逻辑。

**`TransmittableThreadLibrary`**（阿里开源）的解决思路：

```java
// 提交任务时，捕获当前线程的 TTL 值
// 执行任务前，把捕获的值恢复到执行线程
// 执行完后，清除（防止线程池复用导致脏数据）

TtlRunnable runnable = TtlRunnable.get(() -> {
    // 这里能读到提交任务线程的 ThreadLocal 值
});
executor.submit(runnable);
```

---

## 正确使用方式

### 1. 用户会话信息（最经典）

```java
class UserContext {
    private static final ThreadLocal<String> USER_ID =
        ThreadLocal.withInitial(() -> null);

    static void setUserId(String id) { USER_ID.set(id); }
    static String getUserId() { return USER_ID.get(); }
    static void clear() { USER_ID.remove(); }
}

// 过滤器（Web 项目）
void doFilter(ServletRequest req, ServletResponse res) {
    String userId = ((HttpServletRequest)req).getHeader("X-User-Id");
    UserContext.setUserId(userId);
    try {
        chain.doFilter(req, res);
    } finally {
        UserContext.clear();  // 必须清除！
    }
}

// Service 层随便用，不用传参
void processOrder() {
    String userId = UserContext.getUserId();  // 直接从 ThreadLocal 拿
    // ...
}
```

---

### 2. 数据库连接管理

```java
class ConnectionManager {
    private static final ThreadLocal<Connection> CONN =
        ThreadLocal.withInitial(() -> {
            try {
                return DriverManager.getConnection(DB_URL);
            } catch (SQLException e) {
                throw new RuntimeException(e);
            }
        });

    static Connection getConnection() { return CONN.get(); }

    static void closeConnection() {
        Connection conn = CONN.get();
        if (conn != null) {
            try { conn.close(); } catch (SQLException ignored) {}
        }
        CONN.remove();  // 归还到连接池前必须 remove
    }
}
```

---

### 3. SimpleDateFormat 线程不安全，用 ThreadLocal 解决

```java
// ❌ 错误：共享 SimpleDateFormat（线程不安全）
SimpleDateFormat sdf = new SimpleDateFormat("yyyy-MM-dd");
// 多个线程同时调用 sdf.parse() → 数据错乱

// ✅ 正确：每个线程一份
private static final ThreadLocal<SimpleDateFormat> SDF =
    ThreadLocal.withInitial(() -> new SimpleDateFormat("yyyy-MM-dd"));

String format(Date date) {
    return SDF.get().format(date);  // 每个线程用自己的，无锁
}
```

> **更好的方案**（JDK 8+）：用 `DateTimeFormatter`，它是**不可变且线程安全**的，不需要 `ThreadLocal`。

---

## 边界情况和坑

### 1. 内存泄漏（最大的坑）

```
ThreadLocal 内存泄漏的成因：

Thread
  └── threadLocals（ThreadLocalMap）
        └── Entry[]（桶数组）
              ├── Entry(key=WeakReference, value=强引用)
              ├── Entry(key=WeakReference, value=强引用)
              └── ...

如果线程一直不结束（比如线程池的核心线程）：
  1. ThreadLocal 对象被 GC 回收（key 是弱引用 → 变成 null）
  2. 但 Entry 的 value 是强引用，还在！
  3. 这个 value 无法被访问（key=null，get() 找不到）
  4. 如果线程一直活着（线程池），这个 value 永远无法被 GC → 泄漏
```

**为什么 key 要用弱引用？**

> 如果 key 是强引用：`ThreadLocal` 对象被置为 `null`（业务代码里不再使用），  
> 但 `ThreadLocalMap` 里还持有对 `ThreadLocal` 对象的强引用 → **无法回收** → 泄漏。  
> 用弱引用：业务代码释放 `ThreadLocal` 引用后，下次 GC 就把 key 回收了（变成 `null`）。

**但弱引用只解决「key 的泄漏」，不解决「value 的泄漏」！**

**正确的使用方式**：

```java
// ✅ 必须：用完就 remove
ThreadLocal<String> local = new ThreadLocal<>();
try {
    local.set("value");
    // ... 使用 ...
} finally {
    local.remove();  // 删除 Entry，断开 value 的强引用
}
```

**线程池场景尤其要注意**：

```java
// 线程池：线程是复用的，不会销毁
executor.submit(() -> {
    ThreadLocal<String> local = new ThreadLocal<>();
    local.set("task-" + taskId);
    // ... 执行任务 ...
    // 如果这里不 remove，下一个任务复用这个线程时，
    // 还能读到上一个任务的 value（脏数据）！
    local.remove();  // 必须！
});
```

---

### 2. 线程池里 ThreadLocal 不会自动清理

> 普通线程（`new Thread()`）执行完 `run()` 就结束了，`threadLocals` 随线程一起被 GC。  
> **线程池的核心线程永远不会结束**，所以 `threadLocals` 一直存在 → 必须手动 `remove()`。

**最佳实践**：在 `finally` 块里 `remove()`，保证任何情况下都会清理。

---

### 3. ThreadLocal 不能跨线程传递

```java
ThreadLocal<String> local = ThreadLocal.withInitial(() -> "parent");

new Thread(() -> {
    System.out.println(local.get());  // null！子线程拿不到父线程的值
}).start();
```

**解决**：用 `InheritableThreadLocal`（仅限 `new Thread()` 创建的线程）

```java
InheritableThreadLocal<String> local = new InheritableThreadLocal<>();
local.set("parent");

new Thread(() -> {
    System.out.println(local.get());  // "parent"（子线程继承到了）
}).start();
```

**线程池场景**：用阿里 `TransmittableThreadLocal`（`TTL`）。

---

### 4. 哈希冲突的处理

`ThreadLocalMap` 用**线性探测**解决冲突（不是链表）。

```java
// 假设 ThreadLocalMap 的 table 长度是 16
// ThreadLocal1 的 hash → 索引 3
// ThreadLocal2 的 hash → 索引 3（冲突！）

// 线性探测：往后找下一个空位
// 索引 3 被占了 → 试 4 → 试 5 → ... 直到找到空位
```

**后果**：如果 `ThreadLocal` 数量多，哈希冲突严重，查找性能会退化到 O(n)。  
**建议**：每个线程的 `ThreadLocal` 数量不要太多（通常 < 10 个没问题）。

---

