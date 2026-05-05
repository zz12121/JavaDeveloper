# 题目：Java 的 BIO、NIO、AIO 有什么区别？各自适用什么场景？

---

## ⚠️ 先盲答

**不要看任何资料，用自己的话回答，写到纸上或心里默念也行。**

---

## 盲答引导

1. BIO 的「阻塞」是指什么被阻塞了？读不到数据时会怎样？
2. NIO 的三大核心组件是什么？`Selector` 是干什么用的？
3. AIO 和 NIO 最大的区别在哪？为什么 Netty 不用 AIO？
4. 「同步阻塞」「同步非阻塞」「异步非阻塞」分别对应哪个模型？
5. NIO 的 `Channel` 和 `Stream` 有什么本质区别？

---

## 知识链提示

这道题应该让你联想到：

- `[[Reactor模式]]` → NIO 的核心设计模式，Netty 的基石
- `[[IO多路复用]]` → select/poll/epoll，NIO 的底层实现
- `[[零拷贝]]` → NIO 的 `transferTo()`，高性能 IO 的关键
- `[[Netty线程模型]]` → 为什么 Netty 选 NIO 而不是 AIO
- `[[Linux IO模型]]` → 阻塞/非阻塞、同步/异步的系统调用层面

---

## 核心追问

1. NIO 的 `Selector.select()` 是阻塞的还是非阻塞的？可以设置超时吗？
2. AIO 的回调是在哪个线程执行的？应用线程需要等待吗？
3. 为什么 Linux 对 AIO 的支持不好，导致 Java AIO 在 Linux 上用的是 NIO 模拟的？
4. NIO 的 `Buffer` 为什么要有 `position/limit/capacity` 三个指针？
5. 零拷贝（zero-copy）在 NIO 中是怎么实现的？

---

## 参考要点（盲答后再看）

<details>
<summary>点击展开</summary>

**三大模型对比**：

| 模型 | 核心机制 | 阻塞点 | 适用场景 |
|------|---------|--------|---------|
| BIO | 一个连接一个线程 | read/write 阻塞 | 连接数少、简单应用 |
| NIO | 多路复用，一个线程管多个连接 | select() 阻塞（可超时） | 高并发、短连接（Netty） |
| AIO | 真正异步，操作完成后回调 | 无阻塞 | 连接数多、长连接（Windows） |

**NIO 三大组件**：
```java
// 核心模型
Selector selector = Selector.open();
channel.configureBlocking(false);
channel.register(selector, SelectionKey.OP_READ);

// 事件驱动循环
while (selector.select() > 0) {
    Set<SelectionKey> keys = selector.selectedKeys();
    // 处理就绪的 Channel
}
```

**为什么 Netty 不用 AIO**：
1. Linux 对 AIO 支持不完善（原生 AIO 只支持直接缓冲区+文件）
2. NIO + epoll 已经足够高效
3. AIO 的回调线程模型复杂，难以精细控制

**同步/异步、阻塞/非阻塞（常考概念辨析）**：
- 同步 vs 异步：**谁通知你**——自己轮询结果是同步，系统回调是异步
- 阻塞 vs 非阻塞：**等待时线程能不能干别的**——不能干别的是阻塞，可以干别的是非阻塞

| | 阻塞 | 非阻塞 |
|--|------|---------|
| **同步** | BIO（自己等数据） | NIO（自己轮询） |
| **异步** | — | AIO（系统通知你） |

**零拷贝（NIO 高性能关键）**：
```java
// 传统：4次拷贝，4次上下文切换
// 零拷贝：2次拷贝，2次上下文切换
FileChannel src = ...;
FileChannel dest = ...;
src.transferTo(0, size, dest);  // 底层用 sendfile 系统调用
```

</details>

---

## 下一步

1. 盲答后，对比参考要点，找到卡壳的地方
2. 打开 `[[NIO]]` 和 `[[Reactor模式]]` 主题文档，补充 Reactor 三种模型（单线程/多线程/主从）
3. 在 Obsidian 里建双向链接：`[[09_计算机基础/epoll]]` ←→ 本卡片
4. 在 `[[12_面试训练/每日一题跟踪表]]` 里勾选「今日完成」，打 1~5 分
