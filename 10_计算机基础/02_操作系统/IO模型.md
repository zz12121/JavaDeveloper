# IO 模型

> **核心认知**：IO 模型是理解 Java NIO、Netty、Redis、Kafka 等技术的底层基础。一个"读操作"看起来简单，背后涉及用户态/内核态切换、数据拷贝、阻塞/非阻塞等多种机制。

---

## 1. 基本概念

### 1.1 用户态与内核态

```
┌─────────────────────────────────┐
│         用户空间 (User Space)    │  应用程序运行在这里
├─────────────────────────────────┤  ← 内核态/用户态切换
│         内核空间 (Kernel Space)   │  操作系统内核运行在这里
└─────────────────────────────────┘
```

- **用户态**：应用程序的代码执行环境，权限受限，不能直接访问硬件
- **内核态**：操作系统内核执行的环境，可以访问所有硬件和内存
- **切换代价**：每次用户态→内核态→用户态的切换都需要保存/恢复上下文，有性能开销

**IO 操作必须经过内核**：应用程序（用户态）要读磁盘/网卡数据，必须通过系统调用（如 `read()`）进入内核态，由内核完成实际的 IO 操作。

### 1.2 一次 IO 操作的过程

```
以读取网卡数据为例：

1. 应用程序调用 read(fd, buffer)
2. 切换到内核态，内核等待网卡数据到达（等待数据阶段）
3. 数据到达网卡 → 内核将数据从网卡缓冲区拷贝到内核缓冲区（内核→内核）
4. 内核将数据从内核缓冲区拷贝到用户缓冲区（内核→用户）
5. 切换回用户态，read() 返回

两个阶段：
  ① 等待数据准备好（Waiting for the data to be ready）
  ② 将数据从内核空间拷贝到用户空间（Copying the data from the kernel to the user）
```

### 1.3 同步 vs 异步

| 维度 | 同步 IO | 异步 IO |
|------|---------|---------|
| 等待方式 | 调用者**阻塞等待** IO 完成 | 调用者**不等待**，IO 完成后**回调通知** |
| 返回时机 | 数据准备好并拷贝到用户空间后才返回 | 发起请求后立即返回 |
| 编程模型 | 简单直觉 | 需要回调或 Future |
| 内核实现 | Linux 中 BIO/NIO/IO 多路复用**都是同步** | Linux AIO（glibc 实现，不成熟）；Windows IOCP（成熟） |

**关键理解**：在 Linux 中，**非阻塞 IO 和 IO 多路复用本质上都是同步 IO**——它们只是在"等待数据"阶段不阻塞，但"拷贝数据"阶段仍然阻塞。

---

## 2. 五种 IO 模型

### 2.1 阻塞 IO（Blocking IO, BIO）

```
应用程序                    内核
    │                        │
    │  read()                │
    │───────────────────────>│  等待数据（阻塞）
    │  (阻塞等待...)          │  数据到达网卡
    │                        │  拷贝到内核缓冲区
    │                        │  拷贝到用户缓冲区
    │  <──────────────────────│
    │  read() 返回            │
```

- **等待数据**：阻塞
- **拷贝数据**：阻塞
- **特点**：最简单，一个连接一个线程
- **缺点**：并发高时线程数爆炸，线程切换开销大

### 2.2 非阻塞 IO（Non-blocking IO, NIO）

```
应用程序                    内核
    │                        │
    │  read() (nonblock)     │
    │───────────────────────>│  没有数据
    │  <──────────────────────│  立即返回 EAGAIN
    │  read()                │
    │───────────────────────>│  还没有
    │  <──────────────────────│  立即返回 EAGAIN
    │  read()                │
    │───────────────────────>│  数据到了！拷贝到用户缓冲区
    │  <──────────────────────│  read() 返回数据
```

- **等待数据**：不阻塞（轮询，返回 EAGAIN/EWOULDBLOCK）
- **拷贝数据**：阻塞
- **特点**：需要不断轮询，CPU 空转严重
- **缺点**：频繁系统调用，CPU 浪费

### 2.3 IO 多路复用（IO Multiplexing）

```
应用程序                    内核
    │                        │
    │  select/poll/epoll     │
    │  (监听多个 fd)         │
    │───────────────────────>│  等待任意 fd 就绪（阻塞）
    │  (阻塞等待...)          │  fd3 有数据了
    │  <──────────────────────│  返回就绪的 fd 列表
    │  read(fd3)             │
    │───────────────────────>│  拷贝数据（阻塞）
    │  <──────────────────────│
```

- **等待数据**：阻塞（但可以同时监听多个 fd）
- **拷贝数据**：阻塞
- **特点**：一个线程管理多个连接，通过"事件通知"机制避免轮询
- **适用**：高并发、连接多但活跃少的场景（如 HTTP 服务、聊天服务器）

**IO 多路复用的三种实现**：

| 维度 | select | poll | epoll (Linux) |
|------|--------|------|---------------|
| 最大连接数 | 1024（FD_SETSIZE） | 无限制 | 无限制 |
| 底层实现 | 数组 | 链表 | 红黑树 + 双向链表 + 事件回调 |
| 时间复杂度 | O(n) | O(n) | O(1)（就绪事件驱动） |
| 内核拷贝 | 每次全量拷贝 fd_set | 每次全量拷贝 | 只拷贝就绪事件 |
| 触发方式 | 水平触发（LT） | 水平触发 | 水平触发 + 边缘触发（ET） |
| 跨平台 | ✅ 所有 Unix | ✅ 所有 Unix | ❌ 仅 Linux |

**epoll 的核心原理**：

```
1. epoll_create()：创建 epoll 实例（红黑树）
2. epoll_ctl(EPOLL_CTL_ADD)：添加 fd 到红黑树，并注册回调
3. epoll_wait()：阻塞等待，有 fd 就绪时回调将其加入双向链表，返回就绪事件

优势：
- 无需遍历所有 fd，只处理就绪的 fd → O(1)
- 内核和用户空间通过 mmap 共享就绪事件，无需全量拷贝
- 支持 ET 模式（只通知一次），更高效
```

**ET vs LT（边缘触发 vs 水平触发）**：

| 维度 | LT（水平触发） | ET（边缘触发） |
|------|--------------|--------------|
| 触发时机 | 只要有数据就触发 | 数据从无到有时才触发一次 |
| 读取要求 | 可以不一次读完 | **必须一次读完**（否则不会再通知） |
| 编程难度 | 简单 | 复杂（需要循环 read 直到 EAGAIN） |
| 性能 | 较低（可能重复通知） | 更高（减少 epoll_wait 调用） |
| 默认模式 | select/poll/epoll 默认 LT | epoll 需手动设置 EPOLLET |

### 2.4 信号驱动 IO（Signal-driven IO）

```
应用程序                    内核
    │                        │
    │  sigaction(SIGIO)      │
    │  (注册信号处理函数)      │
    │───────────────────────>│
    │  read() 立即返回        │
    │  应用程序做其他事        │
    │                        │  数据到达
    │  <────── SIGIO ─────────│  内核发送信号
    │  信号处理函数中          │
    │  read()                │
    │───────────────────────>│  拷贝数据
    │  <──────────────────────│
```

- **等待数据**：不阻塞（通过 SIGIO 信号通知）
- **拷贝数据**：阻塞
- **特点**：信号通知，不需要轮询
- **缺点**：信号处理复杂，TCP 信号驱动不够成熟

### 2.5 异步 IO（Asynchronous IO, AIO）

```
应用程序                    内核
    │                        │
    │  aio_read()            │
    │───────────────────────>│  立即返回
    │  应用程序做其他事        │  内核等待数据 + 拷贝数据
    │                        │  IO 完成后通过回调/信号通知
    │  <────── 完成通知 ───────│
    │  数据已准备好            │
```

- **等待数据**：不阻塞
- **拷贝数据**：不阻塞（内核完成后通知）
- **特点**：真正的异步 IO，全程无阻塞
- **Linux 实现**：glibc 的 AIO 不成熟（基于线程池模拟）；io_uring（Linux 5.1+）是新一代异步 IO

**Java AIO（NIO.2）**：
- Java 的 AIO 底层在 Linux 上使用 epoll 模拟，**不是真正的操作系统级 AIO**
- Windows 上使用 IOCP（真正的异步 IO）
- 实际项目中，Netty 的 IO 多路复用（epoll）是主流方案

---

## 3. 五种 IO 模型对比

| 维度 | BIO | NIO | IO 多路复用 | 信号驱动 | AIO |
|------|-----|-----|-----------|---------|-----|
| 等待数据 | 阻塞 | 轮询 | 事件通知 | 信号通知 | 不等待 |
| 拷贝数据 | 阻塞 | 阻塞 | 阻塞 | 阻塞 | 不阻塞 |
| 并发模型 | 一连接一线程 | 一连接一线程 | **一线程多连接** | 一连接一线程 | 回调 |
| CPU 利用率 | 低 | 浪费 | 高 | 高 | 高 |
| 编程复杂度 | 低 | 中 | 中 | 高 | 高 |
| 典型应用 | 传统 IO | 少用 | **Nginx/Redis/Netty** | 少用 | Node.js/iouring |
| Java 对应 | java.io | java.nio (Channel) | java.nio (Selector) | 不常用 | java.nio (AsynchronousChannel) |

---

## 4. Java IO 演进

```
Java IO 演进路线：

Java 1.0~1.3：BIO（java.io）
  → 一个连接一个线程，简单但不可扩展

Java 1.4+：NIO（java.nio）
  → Channel + Buffer + Selector
  → 底层基于 epoll/kqueue 实现多路复用
  → 编程复杂，需要手动管理 Buffer

Java 7+：NIO.2 / AIO（java.nio.channels.Asynchronous*）
  → 基于 Future 和 CompletionHandler 的异步 IO
  → Linux 底层仍是 epoll 模拟

Java 生态：Netty（封装了 NIO 的复杂性）
  → EventLoop（Reactor 模式）
  → ChannelPipeline（责任链）
  → ByteBuf（自动内存管理）
  → 生产环境的事实标准
```

**BIO vs NIO 的本质区别**：

| 维度 | BIO | NIO |
|------|-----|-----|
| 流模型 | 面向流（Stream） | 面向缓冲区（Buffer） |
| 阻塞 | 阻塞 | 非阻塞（可设置） |
| 选择器 | 无 | Selector（多路复用） |
| 线程 | 一连接一线程 | 一线程管理多连接 |

---

## 5. 零拷贝

### 5.1 传统 IO 的数据拷贝过程

```
读取文件并发送到网络（如静态文件服务）：

  磁盘 → 内核缓冲区（read，DMA 拷贝）→ 用户缓冲区（CPU 拷贝）
  → Socket 缓冲区（write，CPU 拷贝）→ 网卡（DMA 拷贝）

  共 4 次拷贝（2 次 DMA + 2 次 CPU）+ 4 次上下文切换
```

### 5.2 零拷贝技术

| 技术 | 拷贝次数 | 上下文切换 | 说明 |
|------|---------|-----------|------|
| **mmap** | 3 次 | 4 次 | 内核缓冲区和用户缓冲区映射同一块物理内存 |
| **sendfile** | 3 次（2 DMA + 1 CPU） | 2 次 | 数据不经过用户空间，直接从内核到 Socket |
| **sendfile + DMA Scatter/Gather** | **2 次（2 DMA）** | 2 次 | CPU 零参与（Linux 2.4+） |
| **splice** | 2 次 | 2 次 | 在两个 fd 之间移动数据（管道） |

**Java 中的零拷贝**：

```java
// 1. FileChannel.transferTo()（底层调用 sendfile）
FileChannel source = new FileInputStream("file.txt").getChannel();
WritableByteChannel dest = Channels.newChannel(socket.getOutputStream());
source.transferTo(0, source.size(), dest);  // 零拷贝

// 2. MappedByteBuffer（底层调用 mmap）
FileChannel channel = new RandomAccessFile("file.txt", "r").getChannel();
MappedByteBuffer buffer = channel.map(FileChannel.MapMode.READ_ONLY, 0, channel.size());

// 3. Netty 的 FileRegion（底层调用 transferTo）
FileRegion region = new DefaultFileRegion(new File("file.txt"), 0, file.length());
channel.writeAndFlush(region);
```

---

