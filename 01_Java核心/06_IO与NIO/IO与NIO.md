# IO 与 NIO

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

## 核心脉络

### 五种 IO 模型概览

Java 的 BIO/NIO/AIO 分别对应操作系统层面的三种 IO 模型。理解它们的前提是理解 OS 层的五种模型：

| 模型 | 阻塞阶段 | CPU 利用 | Java 对应 | 典型应用 |
|------|---------|---------|----------|---------|
| 阻塞 IO | 等数据 + 拷贝 | 浪费 | `java.io.*`（BIO）| 低并发简单服务 |
| 非阻塞 IO | 不阻塞（轮询）| 浪费（CPU 空转）| — | 极少单独使用 |
| IO 多路复用 | 等事件 + 拷贝 | 高效 | `java.nio.*`（NIO）| Netty、Tomcat |
| 信号驱动 | 等信号 + 拷贝 | 较高 | — | Linux 使用不多 |
| 异步 IO | 不阻塞 | 最高 | `java.nio.aio.*`（AIO）| 文件 IO 场景 |

### 各维度文档导航

- [[01_Java核心/06_IO与NIO/BIO|BIO]]：阻塞 IO 模型、ServerSocket/Socket、线程模型。重点：一连接一线程的瓶颈、BIO 适用场景
- [[01_Java核心/06_IO与NIO/NIO|NIO]]：Channel/Buffer/Selector、epoll。重点：Buffer 状态机（flip/clear/compact）、Selector 事件模型、空轮询 Bug
- [[01_Java核心/06_IO与NIO/AIO|AIO]]：AsynchronousChannelGroup、CompletionHandler。重点：回调模型、与 NIO 的适用场景对比
- [[01_Java核心/06_IO与NIO/零拷贝|零拷贝]]：传统 IO → mmap → sendfile 演进。重点：4次拷贝→3次→2次，Kafka/RocketMQ 的零拷贝实践
- [[01_Java核心/06_IO与NIO/序列化|序列化]]：Serializable/Externalizable、transient、JSON 序列化。重点：writeObject/readObject 源码、serialVersionUID 兼容性、安全漏洞

---

## 与其他维度的关系

- **[[01_Java核心/03_异常处理/异常处理#try-with-resources|try-with-resources]]**：所有实现了 `AutoCloseable` 的 IO 流都可以用 try-with-resources 自动关闭
- **[[01_Java核心/04_泛型/泛型|泛型]]**：IO 流不能直接用于泛型，`ObjectInputStream.readObject()` 返回 `Object` 需要强转（[[01_Java核心/06_IO与NIO/序列化|序列化]] 的典型痛点）
- **[[01_Java核心/01_基础语法/字符串#编码问题|字符编码]]**：`InputStreamReader`/`OutputStreamWriter` 涉及字符集转换，UTF-8/GBK 的选择影响 IO 正确性
- **[[01_Java核心/08_Lambda与Stream/Lambda与函数式|Lambda]]**：AIO 的 `CompletionHandler` 可以用 Lambda 简化回调写法
