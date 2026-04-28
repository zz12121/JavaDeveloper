# 题目：TCP 四次挥手的过程是什么？为什么 TIME_WAIT 要等 2MSL？

---

## ⚠️ 先盲答

**不要看任何资料，用自己的话回答，写到纸上或心里默念也行。**

画出四次挥手的时序图，并解释为什么是「四次」而不是「三次」。

---

## 盲答引导

1. 主动关闭方发 FIN，被动关闭方回 ACK，此时主动方还能收数据吗？
2. 被动关闭方发 FIN 之前，为什么可以等一段时间（「半关闭」状态）？
3. TIME_WAIT 状态出现在哪一端？持续多久？
4. 2MSL 是什么意思？MSL 一般设多少秒？
5. 大量 TIME_WAIT 会导致什么问题？怎么解决？

---

## 知识链提示

这道题应该让你联想到：

- `[[TCP四次挥手]]` → FIN / ACK / FIN / ACK
- `[[TIME_WAIT状态]]` → 2MSL 等待，防止 ACK 丢失
- `[[CLOSE_WAIT堆积]]` → 被动关闭方不调 close() 导致的问题
- `[[TCP状态机]]` → `FIN_WAIT_1 → FIN_WAIT_2 → TIME_WAIT`
- `[[Socket参数]]` → `SO_REUSEADDR` / `tcp_tw_reuse`

---

## 核心追问

1. 为什么是四次而不是三次？（和握手为什么是三次的对比）
2. 服务器有大量 CLOSE_WAIT 状态，意味着什么？怎么排查？
3. `tcp_tw_reuse` 和 `tcp_tw_recycle` 的区别是什么？为什么 `tw_recycle` 在高版本内核里被删掉了？
4. 主动关闭方在 TIME_WAIT 期间，端口被占用了，新连接还能用这个端口吗？
5. `SO_LINGER` 参数为 0 时，发 RST 而不是 FIN，这有什么后果？

---

## 参考要点（盲答后再看）

<details>
<summary>点击展开</summary>

**四次挥手过程**：

```
客户端（主动关闭）                    服务器（被动关闭）
ESTABLISHED                           ESTABLISHED
    |                                    |
    |---------- FIN (seq=u) ----------->|
    |   (我没有数据要发了，但还能收)         |
    |<--------- ACK (ack=u+1) ----------|
FIN_WAIT_1                           CLOSE_WAIT
    |                                    |
    |                                    | (服务器继续发剩余数据)
    |<--------- FIN (seq=v) -----------|
    |    (服务器也发完了，可以关闭)          |
FIN_WAIT_2                           LAST_ACK
    |                                    |
    |---------- ACK (ack=v+1) --------->|
    |                                    |
TIME_WAIT                             CLOSED
(等 2MSL)
    |
(2MSL 后)
CLOSED
```

**为什么是四次？**

```
握手时：SYN + ACK 可以合并在一个报文里（SYN-ACK）
挥手时：ACK 和 FIN 不能合并
原因：被动关闭方收到 FIN 后，可能还有数据要发（半关闭）
      → 先回 ACK（我知道你要关了）
      → 等数据发完，再发 FIN（我也要关了）
      → 这是两次独立的决策，不能合并
```

**TIME_WAIT 等待 2MSL 的两个原因**：

```
原因1：确保最后的 ACK 能到达被动关闭方
  - 如果最后的 ACK 丢了，被动方会重传 FIN
  - 主动方在 TIME_WAIT 里，能重传 ACK
  - 如果没等，主动方已经 CLOSED，收到 FIN 会回 RST（错误）

原因2：确保旧连接的报文在网络中消失
  - MSL（Maximum Segment Lifetime）= 报文最大生存时间（通常30s~2min）
  - 等待 2MSL = 一去（1MSL）+ 一回（1MSL）
  - 确保旧连接的报文全部消失，新连接不会收到旧报文
```

**大量 TIME_WAIT 的解决**：

```bash
# 现象：短连接服务，端口耗尽
# 解决1：用长连接（HTTP keep-alive / 连接池）
# 解决2：调整内核参数
net.ipv4.tcp_tw_reuse = 1   # 允许复用 TIME_WAIT 的 socket（仅客户端）
net.ipv4.tcp_tw_recycle = 0 # 已废弃（高版本内核删除），NAT 环境下会出问题
net.ipv4.ip_local_port_range = 10000 65535  # 扩大本地端口范围

# 解决3：服务端尽量不要主动关闭（让客户端主动关闭，TIME_WAIT 在客户端）
```

**CLOSE_WAIT 堆积的原因**：

```
被动关闭方：收到 FIN → 进入 CLOSE_WAIT
                ↓
          应用层没调 close() → 一直卡在 CLOSE_WAIT
现象：服务器 socket 资源耗尽，无法接受新连接
排查：netstat -an | grep CLOSE_WAIT | wc -l
修复：检查代码，确保 finally 块里调 close()
```

</details>

---

## 下一步

1. 盲答后，对比参考要点，找到卡壳的地方
2. 打开 `[[09_计算机基础/TCP四次挥手]]` 主题文档，把没懂的地方填进去
3. 在 Obsidian 里建双向链接
4. 在 `[[12_面试训练/每日一题跟踪表]]` 里勾选「今日完成」，打 1~5 分
