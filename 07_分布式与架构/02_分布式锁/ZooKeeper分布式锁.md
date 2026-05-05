# ZooKeeper分布式锁

## 这个问题为什么存在？

> Redis分布式锁性能高，但主从切换时可能丢锁（AP系统，一致性妥协）。问题是：**有没有一种分布式锁，保证强一致性，绝对不丢锁？**

ZooKeeper是CP系统，用**临时顺序节点 + Watch机制**实现强一致分布式锁，但性能比Redis差一个数量级。

---

## 它是怎么解决问题的？

### 核心机制：临时顺序节点 + Watch

```
        /locks/order
            │
    ┌──────┼────────┐
  ephemeral_000001  ephemeral_000002  ephemeral_000003
    (客户端A)         (客户端B)         (客户端C)
    │
    └─ 序列号最小 → 获得锁
```

**加锁流程**：
1. 在锁节点下创建**临时顺序节点**（`EPHEMERAL_SEQUENTIAL`）
2. 检查自己是不是**序列号最小**的节点
3. 是 → 获得锁；否 → 对自己前一个节点注册Watch

**释放锁**：
- 客户端主动删除临时节点，或
- 客户端会话断开（崩溃），ZK自动删除临时节点

```java
// ZooKeeper分布式锁核心逻辑（简化版）
public class ZkDistributedLock {
    private final ZooKeeper zk;
    private final String lockPath = "/locks/order";
    private String currentNode;

    public void lock() throws Exception {
        // 1. 创建临时顺序节点
        currentNode = zk.create(
                lockPath + "/ephemeral_",
                new byte[0],
                ZooDefs.Ids.OPEN_ACL_UNSAFE,
                CreateMode.EPHEMERAL_SEQUENTIAL  // 如：/locks/order/ephemeral_0000000001
        );

        // 2. 进入自旋，等待锁
        while (true) {
            List<String> children = zk.getChildren(lockPath, false);
            Collections.sort(children);
            String smallest = children.get(0);

            if (currentNode.endsWith(smallest)) {
                // 我是最小的，获得锁
                return;
            }

            // 3. 不是最小的，对前一个节点注册Watch
            String prevNode = children.get(children.indexOf(currentNode.substring(currentNode.lastIndexOf("/") + 1)) - 1);
            Stat stat = zk.exists(lockPath + "/" + prevNode, true);
            if (stat == null) {
                continue;  // 前一个节点已经释放，重新检查
            }

            synchronized (this) {
                wait();  // 阻塞，等前一个节点释放时Watch回调notify
            }
        }
    }

    public void unlock() throws Exception {
        zk.delete(currentNode, -1);
        currentNode = null;
    }
}
```

**Watch回调**：

```java
// ZooKeeper Watch回调（简化）
public void process(WatchedEvent event) {
    if (event.getType() == Event.EventType.NodeDeleted) {
        // 前一个节点被删除（释放锁），唤醒等待线程
        synchronized (this) {
            notifyAll();
        }
    }
}
```

---

## 它和相似方案的本质区别是什么？

| | ZooKeeper锁 | Redis锁（单节点） | Redis Redlock |
|---|---|---|---|
| 一致性 | 强一致（CP） | 最终一致（AP） | 强一致（多数派） |
| 锁丢失风险 | 无（ZAB协议保证） | 有（主从切换） | 无（多数派确认） |
| 性能 | 低（磁盘+网络） | 极高（内存） | 中（N次RTT） |
| 实现复杂度 | 高（临时顺序节点+Watch） | 中（SET NX EX + Lua） | 高（多节点） |
| 羊群效应 | 有（所有客户端Watch同一个节点） | 无 | 无 |
| 适用场景 | 一致性要求极高 | 高并发，偶尔重复可接受 | 一致性要求极高，且能容忍时钟依赖 |

**本质区别**：
- **ZooKeeper锁**：CP系统，强一致，适合**选主、元数据修改**等对一致性要求极高的场景
- **Redis锁**：AP系统，性能极高，适合**库存扣减、防重**等高并发场景

---

## 正确使用方式

### 推荐：直接用Curator客户端

```java
// Curator封装了所有细节：加锁、Watch、释放锁、可重入
InterProcessMutex lock = new InterProcessMutex(client, "/locks/order");

try {
    // 加锁，最多等待5秒
    if (lock.acquire(5, TimeUnit.SECONDS)) {
        try {
            // 业务处理...
            processOrder();
        } finally {
            lock.release();  // 释放锁
        }
    }
} catch (Exception e) {
    // 处理异常
}
```

**Curator的优点**：
1. **自动Watch**：不用自己写Watch回调
2. **可重入**：同一个线程可以多次获取锁
3. **锁释放安全**：客户端崩溃，ZK自动删除临时节点
4. **避免羊群效应**：只Watch前一个节点，不是所有节点

### 公平锁 vs 非公平锁

```java
// 公平锁（默认）：按序列号顺序获取锁，先到先得
InterProcessMutex fairLock = new InterProcessMutex(client, "/locks/order");

// 非公平锁：所有客户端抢锁，可能饥饿
InterProcessSemaphoreV2 unfairLock = new InterProcessSemaphoreV2(client, "/locks/order", 1);
```

---

## 边界情况和坑

### 坑1：羊群效应（Herd Effect）

```
场景：100个客户端都在等锁
      锁释放时，ZK通知所有客户端
      所有客户端同时醒过来抢锁 → 网络风暴
```

**解决方案**：
1. **只Watch前一个节点**（Curator默认方案），不是所有节点
2. **用Curator**，不要自己实现

### 坑2：ZooKeeper会话超时

```
场景：客户端GC停顿，超过会话超时时间
后果：ZK认为客户端挂了，删除临时节点（锁被释放）
      客户端GC恢复后，还以为自己持有锁
```

**解决方案**：
1. **减少GC停顿**（用G1/ZGC，减少Full GC）
2. **会话超时时间设长一点**（如30秒），但会增加故障检测时间
3. **业务幂等**（最终兜底）

### 坑3：网络抖动导致误删锁

```
场景：客户端和ZK之间的网络抖动
      客户端认为会话断开（锁被释放）
      网络恢复后，客户端还在执行业务，但锁已经丢了
```

**解决方案**：
1. **用Curator**，它会处理网络抖动，自动重连
2. **业务逻辑要幂等**（就算锁丢了，也不能出错）

---

