# TCP 连接管理

> **核心认知**：TCP 是面向连接的、可靠的、基于字节流的传输层协议。连接管理是 TCP 可靠性的基石——三次握手建连、四次挥手断连、状态机驱动、队列缓冲，共同保障端到端的可靠通信。

---

## 目录

1. [TCP 连接建立——三次握手](#1-tcp-连接建立三次握手)
2. [TCP 连接终止——四次挥手](#2-tcp-连接终止四次挥手)
3. [TCP 连接状态机](#3-tcp-连接状态机)
4. [半连接队列与全连接队列](#4-半连接队列与全连接队列)
5. [TCP KeepAlive 机制](#5-tcp-keepalive-机制)
6. [连接复用与套接字选项](#6-连接复用与套接字选项)
7. [粘包与拆包问题](#7-粘包与拆包问题)
8. [Java 中的 TCP 编程](#8-java-中的-tcp-编程)
9. [线上问题排查](#9-线上问题排查)
10. [面试高频问题](#10-面试高频问题)

---

## 1. TCP 连接建立——三次握手

### 1.1 三次握手完整流程

```
客户端 (Client)                                服务端 (Server)
    |                                               |
    |============== 第一次握手 =====================|
    |  SYN=1, seq=x  (请求建立连接)                  |
    |---------------------------------------------->|
    |  (客户端进入 SYN_SENT 状态)                     |
    |                                               |
    |============== 第二次握手 =====================|
    |  SYN=1, ACK=1, seq=y, ack=x+1                |
    |<----------------------------------------------|
    |  (服务端进入 SYN_RCVD 状态)                    |
    |                                               |
    |============== 第三次握手 =====================|
    |  ACK=1, seq=x+1, ack=y+1                     |
    |---------------------------------------------->|
    |  (客户端进入 ESTABLISHED 状态)                  |
    |                                               |
    |                   (服务端也进入 ESTABLISHED)     |
    |<==============================================>|
    |              连接建立，开始传输数据               |
```

### 1.2 为什么是三次握手？不是两次？不是四次？

| 握手次数 | 问题 | 结论 |
|---------|------|------|
| 两次 | 服务端无法确认客户端已收到自己的 SYN+ACK，若该包丢失，服务端会一直等待，造成资源浪费 | ❌ 不可行 |
| 三次 | 客户端和服务端都能确认对方的收发能力正常 | ✅ 最优解 |
| 四次 | 第二次握手可以将 SYN 和 ACK 合并发送，无需拆分 | ⚠️ 冗余 |

**核心原因**：
1. **确认双方收发能力正常**：客户端→服务端（第一次），服务端→客户端（第二次），客户端→服务端（第三次）
2. **防止历史重复连接初始化**：若客户端发送多个 SYN，服务端只需响应最后一个有效的
3. **协商初始序列号（ISN）**：双方各自发送初始 seq，确保数据有序、不重叠

### 1.3 三次握手的系统调用

```java
// 服务端
ServerSocket serverSocket = new ServerSocket(8080);
Socket socket = serverSocket.accept();  // 阻塞，直到三次握手完成

// 客户端
Socket socket = new Socket("localhost", 8080);  // 发起三次握手
```

**内核视角**：
- `connect()` 系统调用触发第一次握手（客户端发送 SYN）
- `accept()` 系统调用从全连接队列取出已完成握手的连接
- 三次握手由内核 TCP 协议栈自动完成，应用程序无需干预

### 1.4 SYN Flood 攻击与防御

**攻击原理**：攻击者发送大量 SYN 包，不完成第三次握手，导致服务端半连接队列满，无法服务正常请求。

**防御手段**：
```bash
# 查看 SYN Flood 相关内核参数
sysctl net.ipv4.tcp_syncookies
sysctl net.ipv4.tcp_max_syn_backlog

# 开启 SYN Cookies（防御 SYN Flood）
sysctl -w net.ipv4.tcp_syncookies=1

# 增大半连接队列
sysctl -w net.ipv4.tcp_max_syn_backlog=8192
```

**SYN Cookies 原理**：服务端不分配资源，而是根据时间、源目 IP/端口 等计算出一个 Cookie 值，编码在 SYN+ACK 的序列号中。若客户端回复第三次握手，服务端验证 Cookie 合法性后才分配资源。

---

## 2. TCP 连接终止——四次挥手

### 2.1 四次挥手完整流程

```
客户端 (主动关闭)                              服务端 (被动关闭)
    |                                               |
    |============== 第一次挥手 =====================|
    |  FIN=1, seq=u  (请求关闭连接)                  |
    |---------------------------------------------->|
    |  (客户端进入 FIN_WAIT_1 状态)                   |
    |                                               |
    |============== 第二次挥手 =====================|
    |  ACK=1, seq=v, ack=u+1                       |
    |<----------------------------------------------|
    |  (服务端进入 CLOSE_WAIT 状态)                   |
    |  (客户端进入 FIN_WAIT_2 状态)                   |
    |                                               |
    |  ... 服务端继续发送剩余数据 ...                 |
    |                                               |
    |============== 第三次挥手 =====================|
    |  FIN=1, ACK=1, seq=w, ack=u+1                |
    |<----------------------------------------------|
    |  (服务端进入 LAST_ACK 状态)                     |
    |                                               |
    |============== 第四次挥手 =====================|
    |  ACK=1, seq=u+1, ack=w+1                     |
    |---------------------------------------------->|
    |  (客户端进入 TIME_WAIT 状态，等待 2MSL)          |
    |  (服务端收到 ACK 后进入 CLOSED 状态)             |
    |                                               |
    |  ... 等待 2MSL 后客户端也进入 CLOSED ...        |
```

### 2.2 为什么是四次挥手？

TCP 是**全双工通信**，双方都需要单独关闭自己的发送通道：

1. **第一次挥手**：客户端告知服务端"我没有数据要发送了"（但仍可接收）
2. **第二次挥手**：服务端 ACK 客户端的 FIN（此时服务端可能还有数据要发送）
3. **第三次挥手**：服务端数据发送完毕后，告知客户端"我也没有数据要发送了"
4. **第四次挥手**：客户端 ACK 服务端的 FIN

**为什么不能合并第二次和第三次？**  
因为服务端收到 FIN 后，可能还有未发完的数据（半关闭状态），所以必须先 ACK，等数据发完再发 FIN。

**什么情况可以三次挥手？**  
若服务端收到 FIN 时已经没有数据要发送，可以将第二次和第三次合并（FIN+ACK 一起发）。

### 2.3 TIME_WAIT 状态详解

**TIME_WAIT 是主动关闭方在四次挥手后进入的状态，持续 2MSL（Maximum Segment Lifetime）。**

#### 为什么需要 TIME_WAIT？

1. **确保第四次挥手的 ACK 到达服务端**  
   若 ACK 丢失，服务端会重传 FIN，客户端需要有时间接收并重传 ACK。
   
2. **让网络中残留的旧数据包过期**  
   防止旧连接的延迟数据包被新连接误收（四元组相同的情况下）。

#### TIME_WAIT 的危害

```bash
# 查看 TIME_WAIT 连接数
netstat -an | grep TIME_WAIT | wc -l

# 危害：
# 1. 占用端口：客户端（ ephemeral port 耗尽）
# 2. 占用内存：每个 TCP 连接都要占用一定内存
# 3. 影响新连接建立
```

#### 优化 TIME_WAIT

```bash
# 1. 开启 TIME_WAIT 快速回收（Linux kernel < 4.12）
sysctl -w net.ipv4.tcp_tw_recycle=1   # ⚠️ 不建议（NAT 环境下有问题）

# 2. 开启 TIME_WAIT 复用（推荐）
sysctl -w net.ipv4.tcp_tw_reuse=1

# 3. 增大 ephemeral port 范围
sysctl -w net.ipv4.ip_local_port_range="10000 65535"

# 4. 减小 MSL（不推荐，可能导致旧包干扰）
```

**Java 中避免 TIME_WAIT 堆积**：
```java
// 方案1：让服务端主动关闭（谁主动关闭谁进入 TIME_WAIT）
// 方案2：使用连接池复用连接
// 方案3：设置 SO_LINGER（不推荐，可能导致数据丢失）
socket.setSoLinger(true, 0);  // 发送 RST 关闭，跳过 TIME_WAIT
```

### 2.4 CLOSE_WAIT 状态

**CLOSE_WAIT 是被动关闭方在收到 FIN 后进入的状态，表示"我知道你要关闭了，但我还没关闭"。**

#### CLOSE_WAIT 堆积的原因

```java
// 错误示例：应用程序没有正确关闭连接
Socket socket = serverSocket.accept();
// ... 处理请求 ...
// 忘记调用 socket.close()，导致连接一直停留在 CLOSE_WAIT
```

**排查步骤**：
```bash
# 1. 查看 CLOSE_WAIT 连接数
netstat -an | grep CLOSE_WAIT | wc -l

# 2. 查看具体连接
netstat -an | grep CLOSE_WAIT

# 3. 检查应用程序是否正确关闭连接
#    - 是否在 finally 块中关闭 Socket
#    - 是否使用了 try-with-resources
```

**解决方案**：
```java
// 正确做法：使用 try-with-resources 自动关闭
try (Socket socket = serverSocket.accept();
     BufferedReader in = new BufferedReader(new InputStreamReader(socket.getInputStream()));
     PrintWriter out = new PrintWriter(socket.getOutputStream(), true)) {
    // 处理请求
} // 自动调用 socket.close()，发送 FIN
```

---

## 3. TCP 连接状态机

### 3.1 完整状态转换图

```
                        +---------+
                        | CLOSED  | (初始状态/最终状态)
                        +---------+
                             |
             被动打开/应用程序执行listen    |
                             v
                        +---------+
                        | LISTEN  | (服务端监听状态)
                        +---------+
                             |
              收到 SYN (第一次握手)       |
                             v
                        +---------+
                        | SYN_RCVD| (收到 SYN，已回复 SYN+ACK)
                        +---------+
                             |
           收到 ACK (第三次握手)          |
                             v
                        +---------+
                        | ESTAB-  | (连接已建立，可以传输数据)
                        | LISHED  |
                        +---------+
        
        ============= 客户端视角 =============
        
        CLOSED -> SYN_SENT (发送 SYN) -> ESTABLISHED (收到 SYN+ACK，发送 ACK)
        
        ============= 关闭过程 =============
        
        ESTABLISHED -> FIN_WAIT_1 (发送 FIN) 
                     -> FIN_WAIT_2 (收到对端 ACK)
                     -> TIME_WAIT (收到对端 FIN，发送 ACK，等待 2MSL)
                     -> CLOSED
        
        ESTABLISHED -> CLOSE_WAIT (收到对端 FIN，发送 ACK)
                     -> LAST_ACK (发送 FIN)
                     -> CLOSED (收到对端 ACK)
```

### 3.2 各状态说明

| 状态 | 说明 | 停留时间 |
|------|------|---------|
| CLOSED | 初始/关闭状态 | - |
| LISTEN | 服务端监听端口，等待连接 | 持续直到关闭 |
| SYN_SENT | 客户端已发送 SYN，等待 SYN+ACK | 短暂 |
| SYN_RCVD | 服务端收到 SYN，已回复 SYN+ACK | 短暂 |
| ESTABLISHED | 连接已建立，数据传输中 | 持续直到关闭 |
| FIN_WAIT_1 | 主动关闭方已发送 FIN，等待 ACK | 短暂 |
| FIN_WAIT_2 | 主动关闭方收到 ACK，等待对端 FIN | 可能较长 |
| TIME_WAIT | 主动关闭方收到 FIN，等待 2MSL | 2MSL (通常 60s) |
| CLOSE_WAIT | 被动关闭方收到 FIN，等待应用关闭 | 可能很长（异常） |
| LAST_ACK | 被动关闭方已发送 FIN，等待 ACK | 短暂 |
| CLOSING | 双方同时关闭（罕见） | 短暂 |

---

## 4. 半连接队列与全连接队列

### 4.1 两个队列的作用

```
客户端 SYN → 服务端
                    ┌──────────────┐
                    │  半连接队列   │  (SYN Queue)
                    │  (SYN_RCVD)  │  已完成第一次、第二次握手，
                    │              │  但尚未完成第三次握手的连接
                    └──────┬───────┘
                           │ 三次握手完成
                           v
                    ┌──────────────┐
                    │  全连接队列   │  (Accept Queue)
                    │ (ESTABLISHED)│  已完成三次握手，
                    │              │  等待应用程序调用 accept()
                    └──────┬───────┘
                           │ accept() 调用
                           v
                    应用程序拿到连接
```

### 4.2 队列溢出问题

#### 半连接队列溢出

```bash
# 查看半连接队列溢出次数
netstat -s | grep "SYNs to LISTEN"

# 现象：客户端连接超时（SYN 包被丢弃）
# 原因：
#   1. SYN Flood 攻击
#   2. net.ipv4.tcp_max_syn_backlog 设置过小
#   3. 系统负载过高
```

#### 全连接队列溢出

```bash
# 查看全连接队列溢出
netstat -s | grep "times the listen queue of a socket overflowed"

# 现象：客户端连接被重置（ACK 包被丢弃，服务端发送 RST）
# 原因：
#   1. 应用程序 accept() 不及时
#   2. net.core.somaxconn 设置过小
#   3. backlog 参数设置过小
```

### 4.3 参数调优

```bash
# 半连接队列大小：min(backlog, net.ipv4.tcp_max_syn_backlog)
sysctl -w net.ipv4.tcp_max_syn_backlog=8192

# 全连接队列大小：min(backlog, net.core.somaxconn)
sysctl -w net.core.somaxconn=8192

# Java 中设置 backlog（ServerSocket）
ServerSocket serverSocket = new ServerSocket(8080, 8192);  // backlog=8192
```

### 4.4 查看队列使用情况

```bash
# 查看监听端口的全连接队列当前长度和最大长度
ss -lnt

# 输出示例：
# State      Recv-Q Send-Q Local Address:Port  Peer Address:Port
# LISTEN     0      128    *:8080             *:*
#                     ↑     ↑
#                  当前长度  最大长度（min(backlog, somaxconn)）
```

---

## 5. TCP KeepAlive 机制

### 5.1 为什么需要 KeepAlive？

TCP 连接建立后，若其中一方崩溃、断网、或中间路由器故障，另一方无法感知连接已失效，会一直持有连接资源。

**KeepAlive 的作用**：定期探测对端是否仍然存活。

### 5.2 KeepAlive 参数

```bash
# 查看 KeepAlive 参数
sysctl net.ipv4.tcp_keepalive_time   # 空闲多久后开始探测（默认 7200s = 2小时）
sysctl net.ipv4.tcp_keepalive_intvl  # 探测间隔（默认 75s）
sysctl net.ipv4.tcp_keepalive_probes # 探测次数（默认 9 次）

# 修改参数
sysctl -w net.ipv4.tcp_keepalive_time=600
sysctl -w net.ipv4.tcp_keepalive_intvl=30
sysctl -w net.ipv4.tcp_keepalive_probes=3
```

**判定死亡的时间** = `tcp_keepalive_time + tcp_keepalive_intvl × tcp_keepalive_probes`  
默认：`7200 + 75 × 9 = 7875 秒 ≈ 2.2 小时`

### 5.3 Java 中开启 KeepAlive

```java
Socket socket = new Socket();
socket.setKeepAlive(true);  // 开启 TCP KeepAlive

// ⚠️ 注意：Java 无法设置 KeepAlive 参数，只能使用系统默认值
// 若需要自定义参数，需要使用 NIO 或第三方库（如 Netty）
```

### 5.4 应用层心跳 vs TCP KeepAlive

| 维度 | TCP KeepAlive | 应用层心跳（如 WebSocket ping/pong） |
|------|--------------|-------------------------------------|
| 工作层级 | 内核态 | 用户态 |
| 默认超时 | 2 小时（太长） | 可自定义（通常秒级） |
| 穿透 NAT | 可能被 NAT 设备过滤 | 走应用数据通道，不易被过滤 |
| 灵活性 | 差（全局配置） | 好（每个连接可独立配置） |
| 推荐 | 仅作保底 | **生产环境推荐使用应用层心跳** |

---

## 6. 连接复用与套接字选项

### 6.1 SO_REUSEADDR

**作用**：允许重用处于 TIME_WAIT 状态的本地地址（IP+端口）。

```java
ServerSocket serverSocket = new ServerSocket();
serverSocket.setReuseAddress(true);  // 必须在 bind() 前设置
serverSocket.bind(new InetSocketAddress(8080));
```

**使用场景**：
1. 服务端重启时，端口仍处于 TIME_WAIT，若不设置 SO_REUSEADDR，bind() 会失败
2. 多进程监听同一端口（配合 fork）

### 6.2 SO_REUSEPORT（Linux 3.9+）

**作用**：多个进程可以同时监听同一端口，内核负责负载均衡。

```bash
# 适用场景：多进程/多线程服务端，提高吞吐量
# Nginx、Redis 等都使用了 SO_REUSEPORT
```

**优势**：
1. 内核级负载均衡（无需用户态分发）
2. 避免惊群效应（Linux 4.5+ 已优化）
3. 实现真正的多核并行处理

### 6.3 TCP_DEFER_ACCEPT（Linux）

**作用**：收到数据后才唤醒应用程序（避免空连接唤醒）。

```c
// C 语言示例（Java 不支持直接设置）
int val = 1;
setsockopt(fd, IPPROTO_TCP, TCP_DEFER_ACCEPT, &val, sizeof(val));
```

### 6.4 SO_LINGER

**作用**：控制 close() 的行为。

```java
// 方案1：默认行为（l_onoff=0）
// close() 立即返回，内核负责将发送缓冲区的数据发完

// 方案2：延迟关闭（l_onoff=1, l_linger>0）
// close() 阻塞，直到数据发完或超时
socket.setSoLinger(true, 10);  // 最多等待 10 秒

// 方案3：强制关闭（l_onoff=1, l_linger=0）
// close() 立即返回，发送 RST 重置连接（跳过 TIME_WAIT）
socket.setSoLinger(true, 0);  // ⚠️ 可能导致数据丢失
```

---

## 7. 粘包与拆包问题

### 7.1 什么是粘包/拆包？

**TCP 是面向字节流的协议，没有消息边界**，发送方多次 write() 的数据，接收方可能一次 read() 就全部读到（粘包），也可能一次 write() 的数据被分成多次 read()（拆包）。

```
发送方：write("HELLO")  write("WORLD")

接收方可能收到：
  情况1（粘包）：read() -> "HELLOWORLD"
  情况2（拆包）：read() -> "HELLO"  (下次 read() -> "WORLD")
  情况3（拆包）：read() -> "HE"  (下次 read() -> "LLOWORLD")
```

### 7.2 产生原因

| 原因 | 说明 |
|------|------|
| Nagle 算法 | 发送方将多个小包合并发送 |
| TCP 滑动窗口 | 接收方窗口大小限制，导致数据分多次接收 |
| MSS 限制 | 单次发送的数据超过 MSS，被拆分成多个 TCP 段 |
| 网络拥塞 | 路由器可能将大包拆分成多个小包 |

### 7.3 解决方案

#### 方案1：固定长度（不推荐）

```java
// 每个消息固定 1024 字节，不足补零
// 缺点：浪费带宽
```

#### 方案2：分隔符（推荐简单场景）

```java
// 用特殊字符作为消息边界，如 \n
// 示例：Hello\nWorld\n

BufferedReader reader = new BufferedReader(new InputStreamReader(socket.getInputStream()));
String line = reader.readLine();  // 以 \n 为分隔符
```

#### 方案3：长度字段（推荐生产环境）

```java
// 消息格式：长度字段(4字节) + 消息体
// 示例：| 0x00000005 | "HELLO" |

// 发送方
DataOutputStream dos = new DataOutputStream(socket.getOutputStream());
byte[] data = "HELLO".getBytes(StandardCharsets.UTF_8);
dos.writeInt(data.length);  // 写入长度
dos.write(data);            // 写入数据
dos.flush();

// 接收方
DataInputStream dis = new DataInputStream(socket.getInputStream());
int length = dis.readInt();           // 读取长度
byte[] data = new byte[length];
dis.readFully(data);                 // 读取指定长度的数据
String message = new String(data, StandardCharsets.UTF_8);
```

#### 方案4：使用高层协议（推荐）

```java
// 使用 HTTP、WebSocket、gRPC 等应用层协议
// 这些协议已经处理了粘包/拆包问题
```

---

## 8. Java 中的 TCP 编程

### 8.1 BIO（阻塞式 I/O）

```java
// 服务端
public class BioServer {
    public static void main(String[] args) throws IOException {
        ServerSocket serverSocket = new ServerSocket(8080);
        System.out.println("服务端启动，监听端口 8080");
        
        while (true) {
            Socket socket = serverSocket.accept();  // 阻塞，等待客户端连接
            // 为每个连接创建新线程处理（缺点：线程数爆炸）
            new Thread(() -> handleSocket(socket)).start();
        }
    }
    
    private static void handleSocket(Socket socket) {
        try (socket;
             BufferedReader in = new BufferedReader(new InputStreamReader(socket.getInputStream()));
             PrintWriter out = new PrintWriter(socket.getOutputStream(), true)) {
            String line;
            while ((line = in.readLine()) != null) {
                System.out.println("收到消息：" + line);
                out.println("Echo: " + line);
            }
        } catch (IOException e) {
            e.printStackTrace();
        }
    }
}

// 客户端
public class BioClient {
    public static void main(String[] args) throws IOException {
        Socket socket = new Socket("localhost", 8080);
        
        PrintWriter out = new PrintWriter(socket.getOutputStream(), true);
        BufferedReader in = new BufferedReader(new InputStreamReader(socket.getInputStream()));
        
        out.println("Hello, Server!");
        String response = in.readLine();
        System.out.println("服务端响应：" + response);
        
        socket.close();
    }
}
```

### 8.2 NIO（非阻塞 I/O）

```java
// 服务端（单线程 Reactor 模式）
public class NioServer {
    public static void main(String[] args) throws IOException {
        Selector selector = Selector.open();
        
        ServerSocketChannel serverChannel = ServerSocketChannel.open();
        serverChannel.bind(new InetSocketAddress(8080));
        serverChannel.configureBlocking(false);
        serverChannel.register(selector, SelectionKey.OP_ACCEPT);
        
        while (true) {
            selector.select();  // 阻塞，直到有事件发生
            
            Iterator<SelectionKey> iterator = selector.selectedKeys().iterator();
            while (iterator.hasNext()) {
                SelectionKey key = iterator.next();
                iterator.remove();
                
                if (key.isAcceptable()) {
                    // 处理连接事件
                    ServerSocketChannel server = (ServerSocketChannel) key.channel();
                    SocketChannel client = server.accept();
                    client.configureBlocking(false);
                    client.register(selector, SelectionKey.OP_READ);
                } else if (key.isReadable()) {
                    // 处理读事件
                    SocketChannel client = (SocketChannel) key.channel();
                    ByteBuffer buffer = ByteBuffer.allocate(1024);
                    int bytesRead = client.read(buffer);
                    if (bytesRead == -1) {
                        client.close();
                    } else {
                        buffer.flip();
                        client.write(buffer);
                    }
                }
            }
        }
    }
}
```

### 8.3 Netty（生产级 NIO 框架）

```java
// Netty 服务端（处理粘包/拆包、心跳、连接管理都更方便）
public class NettyServer {
    public static void main(String[] args) {
        EventLoopGroup bossGroup = new NioEventLoopGroup(1);
        EventLoopGroup workerGroup = new NioEventLoopGroup();
        
        try {
            ServerBootstrap b = new ServerBootstrap();
            b.group(bossGroup, workerGroup)
             .channel(NioServerSocketChannel.class)
             .childHandler(new ChannelInitializer<SocketChannel>() {
                 @Override
                 protected void initChannel(SocketChannel ch) {
                     ChannelPipeline p = ch.pipeline();
                     // 处理粘包/拆包
                     p.addLast(new LengthFieldBasedFrameDecoder(1024, 0, 4, 0, 4));
                     p.addLast(new LengthFieldPrepender(4));
                     // 处理字符串编解码
                     p.addLast(new StringDecoder());
                     p.addLast(new StringEncoder());
                     // 业务逻辑
                     p.addLast(new SimpleChannelInboundHandler<String>() {
                         @Override
                         protected void channelRead0(ChannelHandlerContext ctx, String msg) {
                             System.out.println("收到消息：" + msg);
                             ctx.writeAndFlush("Echo: " + msg);
                         }
                     });
                 }
             });
            
            ChannelFuture f = b.bind(8080).sync();
            f.channel().closeFuture().sync();
        } catch (InterruptedException e) {
            e.printStackTrace();
        } finally {
            bossGroup.shutdownGracefully();
            workerGroup.shutdownGracefully();
        }
    }
}
```

---

## 9. 线上问题排查

### 9.1 大量 TIME_WAIT 连接

**现象**：
```bash
netstat -an | grep TIME_WAIT | wc -l
# 输出：50000（异常高）
```

**原因**：
1. 客户端短时间内大量短连接（如 HTTP 1.0 每次请求都新建连接）
2. 服务端主动关闭连接（应让客户端主动关闭）

**解决方案**：
```bash
# 1. 开启 TIME_WAIT 复用
sysctl -w net.ipv4.tcp_tw_reuse=1

# 2. 增大 ephemeral port 范围
sysctl -w net.ipv4.ip_local_port_range="10000 65535"

# 3. 使用连接池（避免频繁建连）
# 4. 使用 HTTP/1.1 或 HTTP/2（长连接）
```

### 9.2 大量 CLOSE_WAIT 连接

**现象**：
```bash
netstat -an | grep CLOSE_WAIT | wc -l
# 输出：1000（持续增长，不减少）
```

**原因**：应用程序没有正确关闭连接（忘记调用 `close()`）

**排查步骤**：
```bash
# 1. 确认 CLOSE_WAIT 连接的来源
netstat -an | grep CLOSE_WAIT | awk '{print $4}' | sort | uniq -c

# 2. 检查应用程序代码，确认是否在 finally 块中关闭连接
# 3. 使用 try-with-resources 自动关闭
# 4. 检查连接池配置（如数据库连接池、HTTP 连接池）
```

### 9.3 连接建立超时

**现象**：客户端连接服务端超时。

**排查步骤**：
```bash
# 1. 检查网络连通性
ping server_ip
telnet server_ip port

# 2. 检查服务端是否监听端口
netstat -an | grep LISTEN | grep 8080

# 3. 检查防火墙规则
iptables -L -n

# 4. 检查半连接队列是否溢出
netstat -s | grep "SYNs to LISTEN"

# 5. 使用 tcpdump 抓包分析
tcpdump -i eth0 port 8080 -w /tmp/tcp.pcap
```

### 9.4 全连接队列溢出

**现象**：客户端偶尔连接失败（reset）。

**排查**：
```bash
# 1. 查看队列溢出次数（持续增加说明有问题）
netstat -s | grep "times the listen queue of a socket overflowed"

# 2. 查看当前队列使用情况
ss -lnt | grep 8080

# 3. 解决方案：
#   - 增大 somaxconn 和 tcp_max_syn_backlog
#   - 增大应用程序的 backlog 参数
#   - 优化应用程序 accept() 速度（使用多线程/线程池）
```

---

## 10. 面试高频问题

### Q1: 三次握手为什么不是两次？

**答**：  
1. **防止历史重复连接**：若客户端发送多个 SYN，两次握手无法确认哪个是有效的；
2. **确认双方收发能力**：两次握手只能确认客户端的发、服务端的收，无法确认服务端的发、客户端的收；
3. **协商初始序列号**：两次握手无法让双方都得到对方的初始序列号。

### Q2: TIME_WAIT 状态为什么需要 2MSL？

**答**：  
1. **确保第四次挥手的 ACK 到达**：若 ACK 丢失，服务端会重传 FIN，客户端需要有时间重传 ACK，MSL 是报文最大生存时间，2MSL 确保有足够时间；
2. **让旧数据包过期**：防止旧连接的延迟数据包被新连接误收。

### Q3: CLOSE_WAIT 状态什么时候会出现？怎么排查？

**答**：  
CLOSE_WAIT 是被动关闭方收到 FIN 后进入的状态。正常情况下会很快转为 LAST_ACK（调用 close()）。  
**若 CLOSE_WAIT 堆积**，说明应用程序没有正确关闭连接（忘记调用 `close()`）。  
**排查**：检查代码是否在 finally 块中关闭连接，或使用 try-with-resources。

### Q4: TCP 如何保证可靠性？

**答**：  
1. **校验和**：检测数据传输中的错误；
2. **序列号**：保证数据有序，去重；
3. **确认应答（ACK）**：保证数据到达；
4. **超时重传**：保证丢失的数据包能重传；
5. **流量控制**（滑动窗口）：防止发送方发送过快，接收方来不及处理；
6. **拥塞控制**（慢启动、拥塞避免、快重传、快恢复）：防止网络拥塞。

### Q5: 半连接队列和全连接队列分别是什么？

**答**：  
- **半连接队列**（SYN Queue）：存储已完成第一次、第二次握手，但未完成第三次握手的连接（状态 SYN_RCVD）；
- **全连接队列**（Accept Queue）：存储已完成三次握手，但应用程序还未调用 accept() 的连接（状态 ESTABLISHED）。  
若队列溢出，会导致连接失败（SYN 丢弃或 RST）。

### Q6: Java 中 BIO、NIO、AIO 的区别？

**答**：

| 模型 | 说明 | 适用场景 |
|------|------|---------|
| BIO | 阻塞式 I/O，一个连接一个线程 | 连接数少且固定 |
| NIO | 非阻塞 I/O，一个线程管理多个连接（Reactor 模式） | 连接数多且连接时间短（如聊天服务器） |
| AIO | 异步 I/O，操作完成后回调（Java AIO 基于 epoll，并非真正的异步） | 连接数多且连接时间长（如文件操作） |

---

## 附录：常用内核参数速查表

```bash
# 半连接队列
net.ipv4.tcp_max_syn_backlog = 8192

# 全连接队列
net.core.somaxconn = 8192

# TIME_WAIT
net.ipv4.tcp_tw_reuse = 1       # 复用 TIME_WAIT 连接
net.ipv4.tcp_tw_recycle = 0     # 不建议开启（NAT 问题）
net.ipv4.tcp_fin_timeout = 30   # FIN_WAIT_2 超时时间

# KeepAlive
net.ipv4.tcp_keepalive_time = 600
net.ipv4.tcp_keepalive_intvl = 30
net.ipv4.tcp_keepalive_probes = 3

# 拥塞控制
net.ipv4.tcp_congestion_control = bbr  # 使用 BBR 算法（Linux 4.9+）

# 窗口缩放
net.ipv4.tcp_window_scaling = 1

# 时间戳（用于 RTT 计算和防序列号回绕）
net.ipv4.tcp_timestamps = 1
```

---

> **面试加分项**：  
> - 能画出三次握手和四次挥手的状态转换图  
> - 能解释 TIME_WAIT 和 CLOSE_WAIT 的区别及排查方法  
> - 能结合实际场景（如服务端重启、连接池配置）解释 TCP 参数调优  
> - 能对比 BIO/NIO/AIO 的适用场景
