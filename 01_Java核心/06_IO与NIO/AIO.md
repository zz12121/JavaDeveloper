# AIO

> AIO（Asynchronous IO，Java 7）让 IO 操作完全异步——发起请求后线程立即返回，IO 完成时由操作系统通过回调通知。但 Linux 的 AIO 实现不如 epoll 成熟，实际生产中 AIO 主要用于文件 IO，网络 IO 几乎全部用 NIO + Netty。

---

## 这个问题为什么存在？

NIO 的本质仍然是**同步**——`selector.select()` 虽然只返回就绪事件，但数据从内核缓冲区拷贝到用户空间这一步仍然由用户线程完成（阻塞在 `channel.read()` 上）。

```
NIO 的局限：
  selector.select() → 返回就绪事件（同步等待事件）
  channel.read()    → 从内核拷贝到用户空间（同步拷贝）

AIO 的目标：
  发起读请求 → 线程立即返回
  → 内核完成数据准备和拷贝
  → 回调通知用户线程（全程不阻塞）
```

---

## 它是怎么解决问题的？

### 异步 IO 的本质

```
应用进程                            内核
    |                                |
    |────── 异步读请求 ────────────→  |  （告诉内核：帮我读，读完通知我）
    |                                |
    |  （进程继续做其他事）            |  （内核全权负责）
    |                                |
    |←────── 读完成通知 ────────────|
    |                                |
处理数据 ← 数据已在用户空间           |
```

**两个阶段都不阻塞**：
1. 等数据就绪 → 内核负责
2. 拷贝到用户空间 → 内核负责

### AIO 的 API

```java
// 异步文件读取
AsynchronousFileChannel fileChannel = AsynchronousFileChannel.open(
    Paths.get("file.txt"), StandardOpenOption.READ);

ByteBuffer buffer = ByteBuffer.allocate(1024);
long position = 0;

// 方式 1：Future 模式
Future<Integer> result = fileChannel.read(buffer, position);
// 可以做其他事...
Integer bytesRead = result.get();  // 阻塞等待结果（可选）

// 方式 2：CompletionHandler 回调模式（推荐）
fileChannel.read(buffer, position, buffer,
    new CompletionHandler<Integer, ByteBuffer>() {
        @Override
        public void completed(Integer result, ByteBuffer attachment) {
            System.out.println("读取了 " + result + " 字节");
            attachment.flip();
            // 处理数据...
        }

        @Override
        public void failed(Throwable exc, ByteBuffer attachment) {
            exc.printStackTrace();
        }
    });
// 线程立即返回，不阻塞！
```

### 异步 Socket

```java
// 异步 TCP Server
AsynchronousServerSocketChannel server =
    AsynchronousServerSocketChannel.open();
server.bind(new InetSocketAddress(8080));

server.accept(null, new CompletionHandler<AsynchronousSocketChannel, Void>() {
    @Override
    public void completed(AsynchronousSocketChannel client, Void attachment) {
        // 处理新连接
        ByteBuffer buf = ByteBuffer.allocate(1024);
        client.read(buf, buf, new CompletionHandler<Integer, ByteBuffer>() {
            @Override
            public void completed(Integer result, ByteBuffer attachment) {
                attachment.flip();
                // 处理数据...
                // 继续接受下一个连接
                server.accept(null, this);
            }

            @Override
            public void failed(Throwable exc, ByteBuffer attachment) { }
        });
    }

    @Override
    public void failed(Throwable exc, Void attachment) { }
});
```

---

## 深入原理

### AIO 底层实现

```
Linux:  AIO 基于 libaio / io_uring
  - io_uring 是 Linux 5.1+ 的新异步 IO 框架
  - 性能远超 libaio，但 Java AIO 尚未直接基于 io_uring

Windows: AIO 基于 IOCP（I/O Completion Ports）
  - Windows 上 AIO 实现成熟，性能优秀
  - Java AIO 在 Windows 上表现比 Linux 好

macOS: AIO 基于内核的 kqueue AIO 支持
```

**为什么 Java AIO 在 Linux 上不流行？**
- Linux 的原生 AIO（libaio）只支持 O_DIRECT（绕过 Page Cache），使用受限
- Linux 上 epoll + 非阻塞 IO 的性能已经足够好
- Netty 在 Linux 上用 NIO（epoll）就足够了

### Future vs CompletionHandler

```java
// Future 模式：适合简单的异步调用
Future<Integer> future = channel.read(buffer, 0);
// 做其他事...
Integer result = future.get(10, TimeUnit.SECONDS);  // 可设超时

// CompletionHandler 模式：适合复杂的事件驱动
channel.read(buffer, 0, buffer, new CompletionHandler<>() {
    public void completed(Integer result, ByteBuffer att) { ... }
    public void failed(Throwable exc, ByteBuffer att) { ... }
});
```

**选择原则**：
- 简单场景（单个异步操作）→ Future
- 复杂场景（链式异步操作）→ CompletionHandler
- 现代替代：`CompletableFuture`（Java 8+），更灵活的组合能力

### AsynchronousChannelGroup

```java
// 自定义线程池
ExecutorService executor = Executors.newFixedThreadPool(4);
AsynchronousChannelGroup group = AsynchronousChannelGroup.withThreadPool(executor);

// 用自定义线程池创建 Channel
AsynchronousServerSocketChannel server = AsynchronousServerSocketChannel.open(group);

// group 负责执行所有回调
// 默认使用系统线程池
// 关闭 group 时所有关联的 Channel 也关闭
```

---

## 正确使用方式

### AIO vs NIO 的选择

```
文件 IO：
  - 大文件读写 → AIO（Java AIO 对文件 IO 有真正的优化）
  - 普通文件操作 → NIO FileChannel（更成熟、更常用）

网络 IO：
  - 高并发 → NIO + Netty（事实标准）
  - 简单异步 → AIO（但生产中很少用）
  - Windows 环境 → AIO 表现比 Linux 好

文件传输（服务器→客户端）：
  - 零拷贝（sendfile/mmap）> AIO > NIO > BIO
```

### CompletionHandler 的异常处理

```java
// ❌ 忽略 failed 回调
channel.read(buffer, 0, buffer, new CompletionHandler<>() {
    public void completed(Integer result, ByteBuffer att) { ... }
    public void failed(Throwable exc, ByteBuffer att) {
        // 空的！异常被吞掉
    }
});

// ✅ 正确处理异常
channel.read(buffer, 0, buffer, new CompletionHandler<>() {
    public void completed(Integer result, ByteBuffer att) { ... }
    public void failed(Throwable exc, ByteBuffer att) {
        if (exc instanceof ClosedChannelException) {
            // 连接已关闭，正常情况
        } else {
            logger.error("异步读取失败", exc);
        }
    }
});
```

---

## 边界情况和坑

### 坑 1：`Future.get()` 无限阻塞

```java
Future<Integer> future = channel.read(buffer, 0);
Integer result = future.get();  // ❌ 如果 IO 永远不完成，线程永远阻塞

// ✅ 设置超时
Integer result = future.get(10, TimeUnit.SECONDS);
```

### 坑 2：回调在 IO 线程中执行

```java
channel.read(buffer, 0, buffer, new CompletionHandler<>() {
    public void completed(Integer result, ByteBuffer att) {
        // ⚠️ 这个回调在 AsynchronousChannelGroup 的线程池中执行
        // 不要在这里做耗时操作！会阻塞其他 IO 回调
        heavyComputation();  // ❌ 阻塞 IO 线程池
    }
});

// ✅ 耗时操作提交到业务线程池
public void completed(Integer result, ByteBuffer att) {
    executor.submit(() -> {
        heavyComputation();  // 在业务线程池中执行
    });
}
```

### 坑 3：Buffer 在回调时已被修改

```java
ByteBuffer buf = ByteBuffer.allocate(1024);
channel.read(buf, 0, buf, new CompletionHandler<>() {
    public void completed(Integer result, ByteBuffer att) {
        att.flip();
        processData(att);  // ✅ att 就是传入的 buf，已填充数据
    }
});
// 如果在 read 完成前又调用了 channel.read(buf, ...)，buf 会被两个操作同时使用！
```

**成因**：AIO 是异步的，回调可能在 `read()` 返回后的任意时刻触发。如果用同一个 Buffer 发起多个异步操作，会导致数据错乱。

**解决方案**：每个异步操作使用独立的 Buffer，或者用队列串行化操作。

### 坑 4：AsynchronousFileChannel 不支持文件锁

```java
// AsynchronousFileChannel.open() 不能同时使用文件锁
// 如果需要文件锁，用 FileChannel + lock()
FileChannel fc = FileChannel.open(Paths.get("file.txt"),
    StandardOpenOption.READ, StandardOpenOption.WRITE);
FileLock lock = fc.lock();  // 同步操作
```
