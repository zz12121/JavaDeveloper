# BIO

> BIO（Blocking IO）是 Java 最早的 IO 模型，一个连接对应一个线程，线程在等 IO 时被操作系统挂起。模型简单，但在高并发场景下线程数成为瓶颈。

---

## 这个问题为什么存在？

BIO 是对操作系统阻塞 IO 的直接映射。在 Java 诞生之初（1995年），互联网应用连接数少（几十到几百），一个连接一个线程完全够用。BIO 的优势是**编程模型极其直观**——读就是读，写就是写，不需要事件循环或回调。

但随着互联网发展，连接数从几百增长到上万甚至百万，BIO 的模型撑不住了。

---

## 它是怎么解决问题的？

### 阻塞 IO 的本质

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

**两个阻塞阶段**：
1. **等数据就绪**：数据还没到内核缓冲区（磁盘慢、网络延迟）
2. **拷贝到用户空间**：数据到了内核缓冲区，还要拷贝到 JVM 堆内存

两个阶段线程都被挂起，CPU 完全空闲。

### BIO 的线程模型

```
BIO Server：一个连接 = 一个线程

ServerSocket.accept()  →  阻塞等待连接
  ├── 新连接来了 → 创建新线程
  │     ├── InputStream.read()  →  阻塞等待数据
  │     ├── 处理请求
  │     └── OutputStream.write() → 阻塞发送响应
  └── 继续等待下一个连接
```

```java
// BIO Server 的典型写法
ServerSocket server = new ServerSocket(8080);
while (true) {
    Socket client = server.accept();      // 阻塞：等连接
    new Thread(() -> {
        try (InputStream in = client.getInputStream();
             OutputStream out = client.getOutputStream()) {
            byte[] buf = new byte[1024];
            int len = in.read(buf);       // 阻塞：等数据
            // 处理请求...
            out.write(response);          // 阻塞：等发送
        } catch (IOException e) {
            // 处理异常
        }
    }).start();
}
```

### 线程池优化

```java
// 用线程池限制线程数（伪异步 IO）
ExecutorService pool = Executors.newFixedThreadPool(200);
ServerSocket server = new ServerSocket(8080);
while (true) {
    Socket client = server.accept();
    pool.submit(() -> handleClient(client));  // 复用线程
}
```

**线程池缓解了什么？** 限制了最大线程数，避免无限创建线程导致 OOM。

**线程池没解决什么？**
- 200 个线程在等 IO → 真正在工作的可能只有 5 个，195 个在睡觉
- 如果 200 个连接都不活跃，新的连接会被队列阻塞

---

## 深入原理

### 为什么线程是瓶颈？

```
1 万个连接 = 1 万个线程
1 万个线程的消耗：
  - 栈内存：默认 1MB/线程 → 10GB
  - 操作系统调度：线程切换成本 ≈ 微秒级
  - 文件描述符：默认上限 1024（ulimit -n）

Java 线程映射为操作系统线程（1:1 模型）：
  - JVM 不做 M:N 协程调度
  - Java 21 的虚拟线程（Project Loom）才真正解决这个问题
```

### BIO 在 JDK 源码中的实现

```java
// FileInputStream.read() 的调用链
FileInputStream.read()
  → read0()                    // native 方法
    → JVM_Read()               // JVM 层
      → os::read()             // 操作系统 read(2) 系统调用
        → 阻塞直到数据就绪

// ServerSocket.accept() 的调用链
ServerSocket.accept()
  → implAccept()
    → SocketAcceptable().accept()
      → 操作系统 accept(2) 系统调用
        → 阻塞直到有新连接
```

Java BIO 的每个 read/write/accept 调用最终都是操作系统系统调用，线程在内核态被挂起。

### BIO 的装饰器模式

```
InputStream（抽象基类）
  ├── FileInputStream    — 文件读取
  ├── BufferedInputStream — 缓冲包装（减少系统调用次数）
  ├── DataInputStream    — 基本类型读取
  ├── ObjectInputStream  — 对象反序列化
  └── PushbackInputStream — 回推功能

OutputStream（抽象基类）
  ├── FileOutputStream    — 文件写入
  ├── BufferedOutputStream — 缓冲包装
  ├── DataOutputStream    — 基本类型写入
  ├── ObjectOutputStream  — 对象序列化
  └── PrintStream        — 格式化输出
```

装饰器模式让 IO 流可以**任意组合**：`new DataInputStream(new BufferedInputStream(new FileInputStream("file")))`。每层装饰器添加一种功能，不修改底层实现。

---

## 正确使用方式

### 资源关闭

```java
// ❌ 旧写法（容易忘关闭）
InputStream in = null;
try {
    in = new FileInputStream("file.txt");
    // 使用 in
} catch (IOException e) {
    // 处理
} finally {
    if (in != null) {
        try { in.close(); } catch (IOException e) { }
    }
}

// ✅ try-with-resources（Java 7+）
try (InputStream in = new FileInputStream("file.txt");
     BufferedInputStream bis = new BufferedInputStream(in)) {
    // 使用 bis
} // 自动关闭 bis 和 in（按逆序）
```

### 缓冲流的选择

```java
// ❌ 每次读取一个字节，每次都调用系统调用
FileInputStream fis = new FileInputStream("big.txt");
int b;
while ((b = fis.read()) != -1) { }  // 每次一个字节！

// ✅ 用缓冲流，减少系统调用次数
BufferedInputStream bis = new BufferedInputStream(
    new FileInputStream("big.txt"), 8192  // 默认 8KB 缓冲区
);
```

**为什么缓冲流更快？** 每次系统调用有固定开销（用户态→内核态切换）。缓冲流一次性读 8KB 到内存，后续 8192 次 `read()` 直接从内存取，不触发系统调用。

### BIO 适用场景

**不是所有场景都要用 NIO**。BIO 在以下场景完全够用：
- 连接数少（< 1000）
- 每个连接传输数据量大、耗时长
- 团队对 NIO 不熟悉，维护成本优先

---

## 边界情况和坑

### 坑 1：`available()` 返回值不可靠

```java
InputStream in = new FileInputStream("file.txt");
int available = in.available();  // 返回"不阻塞就能读到的字节数"
// 这个值不等于文件总大小！
// 对于网络 IO，返回值更不可靠
```

**成因**：`available()` 只是一个**估算值**。对于文件 IO，它可能返回 0（即使文件没读完）。对于网络 IO，数据可能还没到达内核缓冲区。

**正确做法**：一直读直到返回 -1（EOF）：
```java
byte[] buf = new byte[8192];
int len;
while ((len = in.read(buf)) != -1) {
    // 处理 buf[0..len-1]
}
```

### 坑 2：`read(byte[])` 不保证填满数组

```java
byte[] buf = new byte[1024];
int len = in.read(buf);  // len 可能 < 1024！
// 即使文件还有数据，read 也可能只返回一部分
```

**成因**：`read(byte[])` 最多读 `buf.length` 个字节，但不保证一次读完。实际读到多少字节，看内核缓冲区里有多少。

### 坑 3：`OutputStream.write()` 不保证一次写完

```java
OutputStream out = socket.getOutputStream();
out.write(largeData);  // 可能只写了一部分！
```

**成因**：`write()` 可能因为发送缓冲区满而只写了一部分。需要检查返回值或用 `DataOutputStream` / `BufferedOutputStream` 包装。

### 坑 4：`InputStream.close()` 抛异常导致资源泄漏

```java
try (InputStream in1 = new FileInputStream("a.txt");
     InputStream in2 = new FileInputStream("b.txt")) {
    // 如果 in1.close() 抛异常，in2.close() 不会被调用？不会！
    // try-with-resources 会保证所有资源都关闭
}
```

**try-with-resources 的保证**：即使第一个资源的 `close()` 抛异常，后续资源的 `close()` 仍然会被调用。如果多个 `close()` 都抛异常，后抛的异常会被抑制（`addSuppressed`）。

### 坑 5：`Socket` 的半关闭状态

```java
Socket socket = new Socket("host", 8080);
socket.shutdownOutput();  // 关闭输出流，但输入流仍然可用
// 对端能读到 EOF（read 返回 -1），但仍然可以发送数据
socket.shutdownInput();   // 关闭输入流，但输出流仍然可用
```

**成因**：TCP 是全双工连接，`shutdownOutput` 只发送 FIN 包（表示不再发送数据），但仍然可以接收数据。这是实现"请求-响应"模式的标准做法。
