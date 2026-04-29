# IO与NIO

> IO 是程序与外部世界交互的唯一方式。理解 IO 不是背五种 IO 模型的名字，而是搞清楚：**数据从磁盘/网络到你的程序字节数组里，到底经历了什么**。

---

## 这个问题为什么存在？

程序运行在用户态，数据存储在磁盘/网络——两者之间隔着一整个操作系统内核。**IO 问题的本质是：跨越这个边界极其昂贵。**

```
一次磁盘 IO ≈ 10ms（毫秒级）
一次 CPU 操作      ≈ 1ns（纳秒级）

比例：10ms : 1ns ≈ 10,000,000 : 1

换算成人的时间尺度：
- CPU 操作 = 1 秒
- 一次磁盘 IO = 约 115 天
```

所以 IO 优化的核心思想只有一条：**少 IO，或者让 IO 不阻塞你的主线程。**

---

## 五种 IO 模型（操作系统层面）

这是理解 Java BIO/NIO/AIO 的前置知识。不搞清楚这个，谈 Java IO 就是空中楼阁。

### 1. 阻塞 IO（BIO）

```
应用进程                            内核
    |                                |
    |────── 数据请求 ──────────────→  |
    |                                |
    |         (等待数据到达内核缓冲区)
    |         (数据从磁盘拷贝到内核缓冲区)
    |         (数据从内核缓冲区拷贝到用户空间)
    |←────── 数据就绪 ──────────────|
    |                                |
处理数据                             |
```

**特点**：进程在整个 IO 期间被内核挂起，CPU 空闲。简单但浪费资源。

### 2. 非阻塞 IO（NIO，user-level non-blocking）

```
应用进程                            内核
    |                                |
    |────── 数据请求 ──────────────→  |
    |←────── EAGAIN (数据未就绪) ─────|
    |                                |
    |────── 再次请求 ──────────────→  |
    |←────── EAGAIN ─────────────────|
    |  (反复轮询，直到数据就绪)
    |
    |────── 数据请求 ──────────────→  |
    |←────── 数据就绪 ──────────────|
```

**特点**：进程不断轮询内核，CPU 空转。适用于轮询场景，但高并发下极浪费 CPU。

### 3. IO 多路复用（Select/Epoll）

```
应用进程                            内核
    |                                |
    |────── 注册 fd1, fd2, fd3 ────→  |
    |                                |
    |←────── 可读事件通知 ──────────|  (一个系统调用，监控多个 fd)
    |                                |
    |────── 只读取就绪的 fd ───────→  |
    |←────── 数据就绪 ──────────────|
    |                                |
处理数据                             |
```

**特点**：一个线程同时监控多个 IO fd，哪个就绪读哪个。**这是 Linux 高并发服务器的基石。** Java NIO 的 Selector 底层就是 epoll（Linux）/kqueue（macOS）。

### 4. 信号驱动 IO

```
应用进程                            内核
    |                                |
    |────── SIGIO 注册 ───────────→  |
    |                                |
    |  (进程继续做其他事)
    |                                |
    |←────── SIGIO 信号通知 ────────|
    |                                |
    |────── 读取数据 ─────────────→  |
    |←────── 数据就绪 ──────────────|
    |                                |
```

**特点**：内核用信号通知进程，数据还是要主动读。Linux 用得不多。

### 5. 异步 IO（AIO / POSIX async IO）

```
应用进程                            内核
    |                                |
    |────── 异步读请求 ────────────→  |  (告诉内核：帮我读，读完通知我)
    |                                |
    |  (进程继续做其他事)            |  (内核全权负责：等数据、拷贝到用户空间)
    |                                |
    |←────── 读完成通知 ────────────|
    |                                |
处理数据 ← 数据已在用户空间           |
```

**特点**：全程不阻塞进程。Java AIO（AsynchronousChannelGroup）基于此模型，但 Linux AIO（io_uring）在高并发下性能更优。

---

## Java BIO：同步阻塞的代价

Java 最早只有 BIO（java.io.*），这是对操作系统阻塞 IO 的直接映射。

### BIO 的核心问题

```
线程模型：一个连接 = 一个线程
1万个连接 = 1万个线程
1万个线程 = 栈内存消耗几GB + 上下文切换成本极高
```

BIO 的问题是**连接数和线程数绑定**。当连接数增长到一定规模，线程本身的资源消耗就成了瓶颈。

### BIO 的典型写法

```java
// BIO Server：每个连接一个线程
ServerSocket server = new ServerSocket(8080);
while (true) {
    Socket client = server.accept();      // 阻塞：等连接
    new Thread(() -> {
        InputStream in = client.getInputStream();
        // 阻塞：等数据
        // 处理...
        client.close();
    }).start();
}
```

### BIO 适用场景

**不是所有场景都要用 NIO**。BIO 的优点是编程模型极其简单。在以下场景，BIO 完全够用：

- 连接数少（< 1000）
- 每个连接传输数据量大、耗时长
- 团队对 NIO 不熟悉

---

## Java NIO：通道、缓冲区、选择器

NIO（New IO，Java 1.4引入）的核心三要素：

### Channel（通道）—— 双向的数据流

```
BIO:  Stream（单向：InputStream / OutputStream）
NIO:  Channel（双向：既能读又能写）
```

Channel 不是替代 Stream，而是 Stream 的底层载体。FileChannel、SocketChannel、ServerSocketChannel 都实现了 `SelectableChannel`。

### Buffer（缓冲区）—— 数据暂存区

```
工作流程（读）：
  Channel → Buffer → 程序

工作流程（写）：
  程序 → Buffer → Channel
```

Buffer 本质是一个**有状态的数组**：

```java
// Buffer 的三个指针
ByteBuffer buffer = ByteBuffer.allocate(1024);

buffer.put(data);        // 写入：position 前移
buffer.flip();           // 切换到读模式：limit = position, position = 0
buffer.get();            // 读取：position 前移
buffer.rewind();         // 重读：position = 0
buffer.clear();          // 清空：position = 0, limit = capacity
```

**直接缓冲区和堆缓冲区**：

```java
ByteBuffer heapBuffer = ByteBuffer.allocate(1024);      // 堆内存，速度慢但 JVM GC 管理
ByteBuffer directBuffer = ByteBuffer.allocateDirect(1024); // 直接内存，不受 GC 管理

// 什么时候用直接缓冲区？
// 当需要与 OS 直接交互时（网络 IO、文件 IO）
// 避免堆内存 → 直接内存的额外拷贝
// 但创建和销毁成本高，适合长连接/长期使用的场景
```

### Selector（选择器）—— IO 多路复用的封装

```java
Selector selector = Selector.open();

ServerSocketChannel server = ServerSocketChannel.open();
server.socket().bind(new InetSocketAddress(8080));
server.configureBlocking(false);        // 非阻塞模式
server.register(selector, SelectionKey.OP_ACCEPT);  // 注册监听事件

while (true) {
    selector.select();                  // 阻塞，直到有事件就绪
    Set<SelectionKey> keys = selector.selectedKeys();
    for (SelectionKey key : keys) {
        if (key.isAcceptable()) {
            // 处理新连接
        } else if (key.isReadable()) {
            // 处理读事件
        } else if (key.isWritable()) {
            // 处理写事件
        }
    }
    keys.clear();
}
```

**Selector 的工作原理**（Linux epoll）：

```
用户进程                     内核
   |                         |
   |──── epoll_create ──────→ |  创建 epoll 实例
   |                         |
   |──── epoll_ctl ADD ────→ |  注册 fd1, fd2, fd3...
   |                         |
   |──── epoll_wait ───────→ |  阻塞等待，CPU 不空转
   |                         |
   |←─── 就绪事件列表 ──────|  返回已就绪的 fd 集合（不需要遍历全部）
```

epoll 的优势：**时间复杂度 O(1)**，只返回已就绪的事件，不像 select 那样需要遍历全部 fd 集合。

### NIO 的经典问题：空轮询 Bug

```java
// JDK NIO 的一个经典 Bug：
// 在某些极端情况下，Selector.select() 会无原因返回（没有实际事件）
// 导致 while(true) 空转，CPU 100%

// 解决方案（JDK 7+）：
//     用 Selector.select() 的返回值判断：
//     - 返回 0 且无注册事件 → 重建 Selector
//     - 或者直接用 Netty（自己实现了空轮询检测和修复）
```

---

## AIO：异步 IO

Java 7 引入了 AIO（AsynchronousChannelGroup），基于 POSIX async IO。

```java
AsynchronousServerSocketChannel server =
    AsynchronousServerSocketChannel.open();

server.bind(new InetSocketAddress(8080));
server.accept(null, new CompletionHandler<AsynchronousSocketChannel, Void>() {
    @Override
    public void completed(AsynchronousSocketChannel client, Void attachment) {
        // 这个回调在 IO 完成时由系统调用，进程完全不阻塞
        ByteBuffer buffer = ByteBuffer.allocate(1024);
        client.read(buffer, buffer, new CompletionHandler<Integer, ByteBuffer>() {
            @Override
            public void completed(Integer result, ByteBuffer attachment) {
                // 读完数据后回调
            }
        });
        server.accept(null, this);  // 继续接受下一个连接
    }

    @Override
    public void failed(Throwable exc, Void attachment) { }
});
```

**AIO vs NIO 的选择**：

```
AIO 适用：文件 IO（Java AIO 对文件操作有真优化）、高并发连接数场景
NIO 适用：需要手动控制 IO 行为、低延迟场景、Netty（实际上 NIO 更成熟）
实际生产：Netty 几乎垄断了 Java 高性能网络编程，它基于 NIO
```

---

## 零拷贝：数据是怎么流动的？

理解零拷贝是理解高性能 IO 的关键。

### 传统 IO（4次拷贝，2次上下文切换）

```
磁盘
  ↓ DMA 拷贝
内核缓冲区（Page Cache）
  ↓ CPU 拷贝
用户空间缓冲区
  ↓ CPU 拷贝
Socket 缓冲区
  ↓ DMA 拷贝
网卡
```

### mmap（内存映射，3次拷贝，2次上下文切换）

```
磁盘
  ↓ DMA 拷贝
内核缓冲区（Page Cache） ← 用户进程直接操作这块内存
  ↓ （无 CPU 拷贝）
Socket 缓冲区
  ↓ DMA 拷贝
网卡
```

`FileChannel.map()` 返回 `MappedByteBuffer`，用户进程可以直接读写内核缓冲区中的数据，避免了一次 CPU 拷贝。

### sendfile（零拷贝，3次拷贝，1次上下文切换）

```java
// Java NIO 的 sendfile
FileChannel.from-transferTo() 底层调用 Linux sendfile(2)

磁盘
  ↓ DMA 拷贝
内核缓冲区（Page Cache）
  ↓ DMA 拷贝（硬件直接传输）
网卡
```

`sendfile` 是真正的零拷贝——数据完全不经过用户空间，由内核直接通过 DMA 从 Page Cache 传到网卡。Kafka 之所以能实现高吞吐，sendfile + 顺序写是核心技术之一。

---

## NIO 和 BIO 的本质区别

```
BIO：同步阻塞 → 连接数 = 线程数 → 线程是瓶颈
NIO：同步非阻塞 → 一个线程管多个连接 → IO 事件是瓶颈
AIO：异步非阻塞 → 真正不阻塞 → 实现复杂，Linux 支持不完善

最根本的区别：谁在等？
BIO：线程在等（CPU 空转）
NIO：CPU 在等 IO（但用 epoll 不空转）
AIO：没有人等（回调通知）
```

---

## 正确使用方式

### 选型决策

```
连接数少（< 1000），简单场景 → BIO（简单就是美）
高并发服务器 → NIO + Netty（工业级成熟方案）
需要极致文件 IO → NIO + mmap
真的需要异步通知，且愿意承担复杂度 → AIO
```

### NIO 写代码的坑

**Buffer 不是线程安全的**：

```java
// 错误：多个线程共享同一个 Buffer
ByteBuffer buffer = ByteBuffer.allocate(1024);
// ❌ 不要在线程间共享可变 Buffer

// 正确：每个线程用自己的 Buffer
```

**忘记 flip() 导致数据读不出来**：

```java
buffer.put("hello".getBytes());
buffer.get();  // ❌ position 已经在末尾，读不到任何东西

// 正确：
buffer.put("hello".getBytes());
buffer.flip();
buffer.get();  // ✅ flip 后才能读
```

**ByteBuffer 分配大小**：

```java
// 网络 IO：一般不超过 64KB（MTU 限制）
ByteBuffer buffer = ByteBuffer.allocate(65536);  // 过大浪费内存

// 文件 IO：可以用更大的 buffer（文件顺序读）
ByteBuffer buffer = ByteBuffer.allocateDirect(1024 * 1024);  // 1MB
```

---

## 边界情况和坑

### 1. NIO 在 Windows 上的差异

```
Linux:  Selector 基于 epoll → 水平触发，高效
Windows: Selector 基于 Select → 有 1024 fd 上限，低效
```

Windows 上 NIO 性能远不如 Linux。这也是为什么高性能服务器都部署在 Linux 上。

### 2. 直接缓冲区的 GC 问题

`allocateDirect()` 的 ByteBuffer 不受 JVM GC 管理，需要手动释放。在 Java 9 之前，如果忘记 close()，会有内存泄漏。Java 9+ 通过 Cleaner 改善，但仍建议显式释放。

### 3. Buffer 的 position/limit 陷阱

```java
// 常见错误：compact() 和 flip() 的区别
buffer.flip();    // 读完后切换：position=0, limit=之前的position
buffer.compact(); // 读完后压缩：未读完的数据移到开头，position=未读完数据长度

// compact() 用于「边读边写」的流式场景
// flip() 用于「一次性读写然后清空」的固定场景
```

### 4. Selector 空轮询导致 CPU 100%

这是 JDK NIO 历史悠久的 bug，触发条件复杂。**生产环境建议直接用 Netty**，它内部实现了对空轮询的检测和修复（通过重建 Selector）。

### 5. Channel 和 Stream 的混淆

```
SocketChannel.read(buffer)  ← NIO，Channel
Socket.getInputStream().read()  ← BIO，Stream

两者不要混用：在同一个 Socket 上混用 BIO 和 NIO 会导致数据错乱。
```

---

## 我的理解

IO 模型的核心不是「哪种更高级」，而是**在等待 IO 的这段时间里，CPU 干什么**。

- BIO：CPU 睡觉（被 OS 挂起）
- NIO：CPU 等待（用 epoll 不空转，进程被内核阻塞）
- AIO：CPU 做别的事（等回调通知）

面试时聊 IO，最高段位不是说「BIO 是同步阻塞，NIO 是非阻塞多路复用」——这是标准答案，初中级都会背。**最高段位是结合 OS 知识说清楚零拷贝的来龙去脉，以及结合 Netty 说说为什么工业界几乎不用 Java 原生 NIO。**
