# TCP可靠传输

## 这个问题为什么存在？

> 网络层（IP）是不可靠的：丢包、乱序、重复、损坏都可能发生。问题是：**两个端点之间怎么保证数据按序、完整、不重复地到达？**

TCP 的解决思路是**确认机制（ACK）+ 序号（Sequence Number）+ 重传机制**，在不可靠的 IP 层上构建可靠传输。

## 它是怎么解决问题的？

### 滑动窗口（Sliding Window）

```
发送方                            接收方
  │                                   │
  │──── 32 KB 数据（分 22 个报文）───▶│
  │                                   │
  │◀─── ACK=32768, Win=16KB ────────│
  │       ↑收到 32KB 前 32KB 的确认    │
  │                                   │
  │─── 接着发 32KB~48KB ─────────────▶│
```

发送窗口大小 = **min(接收窗口, 拥塞窗口)**。

### 超时重传（RTO）

```
发送方发报文 N
    ↓
启动重传定时器（RTO）
    ↓
收到 ACK N → 取消定时器 ✅
没收到 ACK → 定时器到期 → 重传报文 N ❌
```

RTO 不是固定值，而是**动态计算**的：

```
RTO = SRTT + max(G, 4×RTTVAR)
SRTT：平滑后的 RTT
RTTVAR：RTT 方差
G：时钟粒度
```

### 快速重传（Fast Retransmit）

```
发送方：1 2 3 4 5
接收方：收到 1, 2 → 发送 ACK=3
        收到 4 → 还是发送 ACK=3（3 没到）
        收到 5 → 还是发送 ACK=3
发送方收到 3 个重复 ACK → 不等超时，立即重传 3
```

**不需要等 RTO 超时，收到 3 个重复 ACK 就重传**。

### 快速恢复（Fast Recovery）

快速重传后进入快速恢复（不是慢启动）：

```
拥塞窗口 cwnd = cwnd / 2   （减半）
慢启动阈值 ssthresh = cwnd / 2
```

### 累积确认 vs 选择确认（SACK）

**累积确认**（默认）：只确认连续收到的最大序号。

```
收到：1, 2, 4, 5
发送 ACK=3（表示 1~2 都收到了，4 和 5 不确认）
```

**SACK**（Selective Acknowledgment）：在 TCP 选项里告诉发送方「我收到了哪些不连续的块」。

```
收到：1, 2, 4, 5
SACK: [4~6]  ← 告诉发送方：4 和 5 我也收到了，只缺 3
```

## 拥塞控制（4 种算法）

### 1. 慢启动（Slow Start）

```
cwnd = 1 MSS（初始拥塞窗口）
每个 RTT：cwnd 翻倍

cwnd: 1 → 2 → 4 → 8 → 16 → ...
          ↑
    cwnd >= ssthresh 时，退出慢启动，进入拥塞避免
```

### 2. 拥塞避免（Congestion Avoidance）

```
每 RTT：cwnd + 1 MSS（线性增长）

cwnd: 16 → 17 → 18 → 19 → ...
```

触发条件：`cwnd >= ssthresh`。

### 3. 快速重传 + 快速恢复（前面已讲）

### 4. BBR（Bottleneck Bandwidth and RTT）

Google 提出的算法，不依赖丢包作为拥塞信号：

```
BBR 状态机：
  STARTUP    → 探测最大带宽，指数增长（类似慢启动）
  DRAIN      → 排空排队的数据
  PROBE_BW   → 稳定探测带宽（核心状态）
  PROBE_RTT  → 周期性探测最小 RTT
```

**和 CUBIC 的核心区别**：CUBIC 依赖丢包（丢包才降窗），高带宽高延迟场景下（如长肥管道）性能差。BBR 直接测量带宽和 RTT，不依赖丢包信号。

## 深入原理

| | TCP | UDP |
|---|---|---|
| 可靠性 | ✅ 确认 + 重传 + 序号 | ❌ 不保证 |
| 有序性 | ✅ 序号 + 去重 | ❌ 不保证 |
| 流量控制 | ✅ 滑动窗口 | ❌ 不提供 |
| 拥塞控制 | ✅ 慢启动 + 拥塞避免 | ❌ 不提供（可能加剧拥塞） |
| 性能 | 中（有开销） | 高（无状态） |

### CUBIC vs BBR

| | CUBIC（Linux 默认） | BBR（Google） |
|---|---|---|
| 拥塞信号 | 丢包 | 带宽 + RTT 测量 |
| 高丢包网络 | 性能差（降窗） | 性能好（不依赖丢包） |
| 缓冲区膨胀（Bufferbloat）| 易受影响 | 主动探测最小 RTT，缓解 |
| 适用场景 | 普通网络 | 高带宽、高延迟、高丢包率 |

## 正确使用方式

### 调整 TCP 参数（Linux）

```bash
# 增加 TCP 接收缓冲区（影响接收窗口大小）
sysctl -w net.ipv4.tcp_rmem="4096 87380 6291456"

# 增加 TCP 发送缓冲区
sysctl -w net.ipv4.tcp_wmem="4096 16384 4194304"

# 开启 BBR（需要 Linux 4.9+）
sysctl -w net.ipv4.tcp_congestion_control=bbr
```

### 应用层超时设置

```java
// TCP 有重传，但应用层仍需超时（防止 TCP 重传耗完 RTO）
Socket socket = new Socket();
socket.setSoTimeout(5000);  // 读取超时 5 秒

// 连接超时（TCP 三次握手超时）
socket.connect(endpoint, 3000);  // 3 秒
```

## 边界情况和坑

### Nagle 算法 + 延迟 ACK 死锁

```
Nagle：小包不发送，等凑满 MSS 或收到 ACK
延迟 ACK：收到数据后不立即 ACK，等凑够 2 个包或超时（40ms）

场景：一方发小包 + Nagle，另一方延迟 ACK
→ 互相等待 → 40ms 延迟
```

解决：
```java
socket.setTcpNoDelay(true);  // 关闭 Nagle，小包立即发送
```

### TIME_WAIT 堆积

```
主动关闭方 → 收到 FIN → 发送 ACK → 进入 TIME_WAIT（2MSL，默认 60s）
```

高并发短连接（如 HTTP 短连接）会在主动关闭方留下大量 `TIME_WAIT` 套接字，占用端口。

解决：
```bash
# 开启 TIME_WAIT 快速回收（Linux）
sysctl -w net.ipv4.tcp_tw_reuse=1

# 允许 TIME_WAIT 套接字重用（谨慎）
sysctl -w net.ipv4.tcp_tw_recycle=1  # Linux 4.12 后已移除
```

### 初始 cwnd 大小

Linux 2.6.39+ 起 `cwnd` 初始值改为 **10 MSS**（RFC 6928），不再是 1 MSS。对于一个 1500 字节 MTU、MSS=1460 的场景，第一次 RTT 就能传 ~14KB。

