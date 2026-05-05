# 题目：TCP 的拥塞控制是怎么做的？ 慢启动、拥塞避免、快重传、快恢复分别是什么？

---

## ⚠️ 先盲答

**不要看任何资料，用自己的话回答，写到纸上或心里默念也行。**

说出拥塞控制的四个算法名字，以及它们分别在「拥塞发生前」「拥塞发生后」起什么作用。

---

## 盲答引导

1. 「拥塞窗口（cwnd）」和「接收窗口（rwnd）」分别由谁控制？发送窗口取哪个？
2. 慢启动（Slow Start）为什么叫「慢」？它的增长是指数还是线性？
3. 拥塞避免（Congestion Avoidance）阶段，cwnd 的增长速度是多少？
4. 收到 3 个重复 ACK（Dup ACK）时，TCP 走「快重传 / 快恢复」，还是重新慢启动？
5. 超时（RTO）和 3 个重复 ACK，触发的行为一样吗？哪个更「温和」？

---

## 知识链提示

这道题应该让你联想到：

- `TCP拥塞控制四算法` → 慢启动 / 拥塞避免 / 快重传 / 快恢复
- `ssthresh` → 慢启动阈值，决定何时进入拥塞避免
- `[[TCP BIC/CUBIC]]` → Linux 默认拥塞控制算法
- `BBR` → Google 的拥塞控制算法，基于带宽和延迟
- `拥塞窗口vs接收窗口` → 发送窗口 = min(cwnd, rwnd)

---

## 核心追问

1. 为什么现代 Linux 内核默认用 CUBIC 而不是老的 Reno 算法？
2. BBR 算法和 CUBIC 的核心区别是什么？为什么 BBR 在高延迟网络里表现更好？
3. `net.ipv4.tcp_congestion_control` 怎么查看和修改拥塞控制算法？
4. 为什么 TCP 要区分「超时重传」和「快重传」两种场景？网络环境有什么不同？
5. `tcpdump` 抓包时，看到大量「TCP Retransmission」，通常是 cwnd 太小还是网络真的丢包了？

---

## 参考要点（盲答后再看）


**拥塞控制四算法**：

```
① 慢启动（Slow Start）
  - cwnd 初始 = 1 MSS
  - 每收到 1 个 ACK → cwnd 翻倍（指数增长）
  - 直到 cwnd >= ssthresh → 进入拥塞避免

② 拥塞避免（Congestion Avoidance）
  - cwnd 线性增长（每个 RTT + 1 MSS）
  - 直到发生拥塞

③ 快重传（Fast Retransmit）
  - 收到 3 个重复 ACK → 立即重传丢失的包（不等 RTO 超时）
  - 不回到慢启动！

④ 快恢复（Fast Recovery）
  - 收到 3 个重复 ACK 后，ssthresh = cwnd / 2
  - cwnd = ssthresh + 3（Reno 算法）
  - 直接进入拥塞避免（跳过了慢启动）
```

**窗口变化状态机**：

```
慢启动：cwnd = 1 → 2 → 4 → 8 → 16...（指数）
         ↓（cwnd >= ssthresh）
拥塞避免：cwnd = ssthresh → ssthresh+1 → ssthresh+2...（线性）
         ↓（收到 3 个重复 ACK）
快恢复：cwnd = ssthresh（不回到 1！）
         ↓（超时 RTO）
慢启动：cwnd = 1（重新来过，最惨的情况）
```

**超时 vs 3 个重复 ACK（不同处理）**：

```
超时（RTO）：
  - 认为网络严重拥塞
  - ssthresh = cwnd / 2
  - cwnd = 1（重新慢启动！最保守）

3 个重复 ACK（快重传）：
  - 认为网络轻度拥塞（只是丢了一个包）
  - ssthresh = cwnd / 2
  - cwnd = ssthresh（快恢复，不回到 1）
```

**Linux 拥塞控制算法**：

```bash
# 查看当前算法
sysctl net.ipv4.tcp_congestion_control
# 通常输出：net.ipv4.tcp_available_congestion_control = cubic reno bbr

# 修改为 BBR（需要内核 4.9+）
echo "tcp_bbr" > /proc/sys/net/ipv4/tcp_congestion_control
```

**CUBIC vs BBR**：

```
CUBIC（默认）：
  - 基于「丢包」判断拥塞
  - 问题：高带宽高延迟网络里，丢包 ≠ 拥塞（可能是随机错误）
  - 导致：带宽没用完就降速

BBR（Google）：
  - 基于「实时带宽」和「延迟」判断
  - 先探测最大带宽 → 再探测最小延迟 → 平衡两者
  - 适合：高延迟、高带宽网络（跨国传输）
```


---

## 下一步

1. 盲答后，对比参考要点，找到卡壳的地方
2. 打开 `[[13_面试训练/01_题目知识链/09_计算机基础/07_TCP拥塞控制]]` 主题文档
3. 在 Obsidian 里建双向链接
4. 在 `[[13_面试训练/03_每日一题/每日一题跟踪表]]` 里勾选「今日完成」，打 1~5 分
