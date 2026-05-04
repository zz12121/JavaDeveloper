# NIO

> NIO（New IO，Java 1.4）用 Channel + Buffer + Selector 三要素实现了 IO 多路复用，一个线程可以管理成千上万个连接。Netty 基于 NIO 构建，是 Java 高性能网络编程的事实标准。

---

## 这个问题为什么存在？

BIO 的问题是**连接数 = 线程数**，万级连接时线程资源成为瓶颈。NIO 的目标是**一个线程管理多个连接**——用 IO 多路复用（epoll/kqueue）监听多个文件描述符（fd），哪个就绪处理哪个。

---

## 它是怎么解决问题的？

### 核心三要素

```
BIO:  Stream（单向）→ InputStream / OutputStream
NIO:  Channel（双向）+ Buffer（中间缓冲）+ Selector（多路复用）
```

#### Channel（通道）

```java
FileChannel      — 文件 IO
SocketChannel    — TCP 客户端
ServerSocketChannel — TCP 服务端
DatagramChannel  — UDP
```

**Channel vs Stream**：
```
Stream（BIO）：单向流， InputStream 只能读，OutputStream 只能写
Channel（NIO）：双向通道，既能读又能写
Stream：阻塞
Channel：可配置阻塞/非阻塞
```

#### Buffer（缓冲区）

Buffer 是 NIO 的核心——所有读写都经过 Buffer。

```java
ByteBuffer buffer = ByteBuffer.allocate(1024);

// Buffer 的四个属性
// capacity：总容量（创建时固定）
// position：当前读写位置
// limit：可读写的边界
// mark：标记（用于重复读取）
```

**Buffer 状态机**：

```
初始状态（写模式）：
  position = 0, limit = capacity

写入数据后：
  position = 写入的字节数, limit = capacity

flip() — 切换到读模式：
  limit = position（之前写入了多少就能读多少）
  position = 0

读取数据后：
  position = 读取的字节数, limit = 不变

clear() — 重新切换到写模式：
  position = 0, limit = capacity

compact() — 压缩未读数据到开头：
  未读数据移到 buffer 开头
  position = 未读数据长度
  limit = capacity
```

```java
// 典型使用流程
ByteBuffer buf = ByteBuffer.allocate(1024);

// 1. 写入
buf.put("hello".getBytes());

// 2. 切换到读模式
buf.flip();

// 3. 读取
while (buf.hasRemaining()) {
    byte b = buf.get();
}

// 4. 清空，准备下次写入
buf.clear();
```

**直接缓冲区 vs 堆缓冲区**：

```java
// 堆缓冲区：在 JVM 堆内存中，受 GC 管理
ByteBuffer heapBuf = ByteBuffer.allocate(1024);

// 直接缓冲区：在堆外内存中，不受 GC 管理
ByteBuffer directBuf = ByteBuffer.allocateDirect(1024);
```

| 维度 | 堆缓冲区 | 直接缓冲区 |
|------|---------|----------|
| 内存位置 | JVM 堆 | 堆外内存（native） |
| 创建/销毁 | 快 | 慢 |
| IO 性能 | 需要额外拷贝到堆外 | 直接与内核交互 |
| GC 影响 | 受 GC 管理 | 不受 GC 管理（需手动释放）|
| 适用场景 | 短期使用、小数据量 | 长连接、大数据量、网络 IO |

#### Selector（选择器）

Selector 是 Java 对 IO 多路复用的封装，底层是 Linux epoll / macOS kqueue / Windows select。

```java
Selector selector = Selector.open();

ServerSocketChannel server = ServerSocketChannel.open();
server.socket().bind(new InetSocketAddress(8080));
server.configureBlocking(false);  // 非阻塞模式
server.register(selector, SelectionKey.OP_ACCEPT);

while (true) {
    int readyCount = selector.select();  // 阻塞，直到有事件就绪
    if (readyCount == 0) continue;

    Set<SelectionKey> keys = selector.selectedKeys();
    Iterator<SelectionKey> it = keys.iterator();
    while (it.hasNext()) {
        SelectionKey key = it.next();
        if (key.isAcceptable()) {
            // 新连接
            SocketChannel client = server.accept();
            client.configureBlocking(false);
            client.register(selector, SelectionKey.OP_READ);
        } else if (key.isReadable()) {
            // 数据可读
            SocketChannel client = (SocketChannel) key.channel();
            ByteBuffer buf = ByteBuffer.allocate(1024);
            client.read(buf);
            buf.flip();
            // 处理数据...
        }
        it.remove();  // 必须手动移除！
    }
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
   |←─── 就绪事件列表 ──────|  只返回已就绪的 fd（O(1)）
```

**epoll vs select 的核心区别**：
- select：遍历所有 fd（O(n)），有 1024 fd 上限
- epoll：只返回就绪的 fd（O(1)），无上限

---

## 深入原理

### epoll 的两种触发模式

```
水平触发（LT，Level Triggered）：
  → 只要缓冲区有数据，就通知你
  → 如果你没读完，下次 select() 还会通知
  → Java NIO 默认使用 LT（对程序员更友好）

边缘触发（ET，Edge Triggered）：
  → 只有数据"新到达"时才通知一次
  → 如果没读完，不会再通知了
  → 必须一次性读完（用 while 循环读到 EAGAIN）
  → 性能更高（减少系统调用次数）
  → Nginx 使用 ET 模式
```

### NIO 的经典 Bug：空轮询

```java
// JDK NIO 的一个著名 Bug：
// 在某些极端情况下，Selector.select() 无原因返回 0（没有实际事件）
// 导致 while(true) 空转，CPU 100%

// JDK 的修复方案（JDK 7+）：
// 检测 select() 连续返回 0 的次数
// 超过阈值 → 重建 Selector，重新注册所有 Channel

// Netty 的修复方案：
// 自行实现空轮询检测
// 连续 N 次 select() 返回 0 → 重建 Selector
```

**为什么会产生空轮询？** 某些 Linux 内核版本和 JDK 版本的组合下，epoll 的唤醒事件可能被错误触发（没有实际就绪事件但 select 返回），具体原因涉及内核 bug 和 JNI 层的问题。

### SelectionKey 的四个事件

```
OP_ACCEPT  — 有新连接到达（ServerSocketChannel）
OP_CONNECT — 连接建立完成（SocketChannel 客户端）
OP_READ    — 数据可读
OP_WRITE   — 发送缓冲区可写（通常不注册，因为大多数时候都可写）
```

**什么时候需要注册 OP_WRITE？** 只有当发送缓冲区满了时才需要注册。正常情况下发送缓冲区几乎都是空的（可写），注册了会导致 select 不断返回 writable 事件，浪费 CPU。

---

## 正确使用方式

### Buffer 操作的最佳实践

```java
// ❌ 忘记 flip
buffer.put(data);
buffer.get();  // position 在末尾，读不到数据

// ✅ 写完必须 flip
buffer.put(data);
buffer.flip();
buffer.get();

// ❌ 重复使用同一个 Buffer 不 clear
// 第二次 put 时 position 在末尾，写入到错误位置

// ✅ 用完 clear 或 compact
buffer.clear();    // 清空，从头开始
buffer.compact();  // 保留未读数据，移到开头
```

### NIO 事件循环的正确写法

```java
while (true) {
    selector.select(1000);  // 带超时的 select，防止永久阻塞

    Iterator<SelectionKey> it = selector.selectedKeys().iterator();
    while (it.hasNext()) {
        SelectionKey key = it.next();
        it.remove();  // ⚠️ 必须手动移除！
        // 处理事件...
    }
}
```

**为什么必须手动 remove？** `selectedKeys()` 返回的就绪事件集合不会自动清除。如果不 remove，下次 select 返回时，上次处理过的事件还在集合里，会重复处理。

### 直接缓冲区的使用与释放

```java
// Java 9+：直接缓冲区实现了 AutoCloseable
try (ByteBuffer directBuf = ByteBuffer.allocateDirect(1024)) {
    // 使用直接缓冲区
} // 自动释放堆外内存

// Java 8：需要通过反射释放（或依赖 GC）
ByteBuffer directBuf = ByteBuffer.allocateDirect(1024);
// 用完后最好置空引用，让 Cleaner 有机会回收
directBuf = null;
```

---

## 边界情况和坑

### 坑 1：`selectedKeys()` 的重复处理

```java
// ❌ 没有移除已处理的 key
Set<SelectionKey> keys = selector.selectedKeys();
for (SelectionKey key : keys) {
    handle(key);  // 每次循环都重复处理
}
// keys 不会自动清空！

// ✅ 必须手动移除
Iterator<SelectionKey> it = keys.iterator();
while (it.hasNext()) {
    SelectionKey key = it.next();
    handle(key);
    it.remove();  // 关键！
}
```

### 坑 2：`selectedKeys()` 用 for-each 遍历会 ConcurrentModificationException

```java
// ❌ for-each 遍历 + remove = CME
for (SelectionKey key : selector.selectedKeys()) {
    selector.selectedKeys().remove(key);  // CME!
}

// ✅ 用 Iterator.remove()
Iterator<SelectionKey> it = selector.selectedKeys().iterator();
while (it.hasNext()) {
    SelectionKey key = it.next();
    it.remove();
}
```

**成因**：`for-each` 底层用 Iterator，在遍历时调用 `Set.remove()` 修改了集合，触发 fail-fast。

### 坑 3：Channel 关闭后 Selector 中还有残留事件

```java
channel.close();
// 关闭 Channel 后，Selector 中可能还有该 Channel 的就绪事件
// 下次 select() 会返回一个已关闭 Channel 的 SelectionKey
// 处理时会出现 IOException

// 正确做法：关闭前先取消注册
SelectionKey key = channel.keyFor(selector);
if (key != null) key.cancel();
channel.close();
```

### 坑 4：非阻塞 Channel 的 read 返回 0

```java
SocketChannel channel = ...;
ByteBuffer buf = ByteBuffer.allocate(1024);
int bytesRead = channel.read(buf);

if (bytesRead == -1) {
    // 对端关闭连接
} else if (bytesRead == 0) {
    // 没有数据可读（非阻塞模式下）
    // 不是错误！应该跳过，下次 select 再检查
}
```

**成因**：非阻塞模式下，`read()` 可能返回 0（缓冲区暂时没有数据），这和 -1（连接关闭）是完全不同的含义。

### 坑 5：NIO 在 Windows 上的性能问题

```
Linux:  Selector 基于 epoll → 高效，O(1)
Windows: Selector 基于 select → 低效，O(n)，有 1024 fd 上限
macOS: Selector 基于 kqueue → 高效
```

**影响**：Windows 上 Java NIO 性能远不如 Linux。这也是为什么高性能服务器都部署在 Linux 上。Netty 在 Windows 上也有性能下降，但 Netty 做了针对性优化（如串行化 I/O）。
