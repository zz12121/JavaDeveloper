# ZooKeeper 核心原理

## 这个问题为什么存在？

在分布式系统里，多个节点需要协调完成一些事情：

1. **服务注册发现**：订单服务启动后，怎么告诉别人"我上线了"？我挂了怎么让别人知道？
2. **配置管理**：数据库密码改了，怎么推送给所有节点？
3. **分布式锁**：多个节点同时写同一行数据，怎么保证互斥？
4. **Leader 选举**：多个节点谁是主，谁挂了谁接替？

这些问题有一个共同点：**需要一个小而可靠的"协调者"**。这个协调者本身也要高可用（不能是单点）。

ZooKeeper 就是来解决这些问题的。它是 **CP 系统**（一致性和分区容错优先，可用性妥协），用 **ZAB 协议** 保证强一致。

> **为什么不用 Redis 做这些？** Redis 是 AP 系统（高可用 + 分区容错），主从切换时可能丢数据。ZooKeeper 保证强一致，但性能比 Redis 差一个数量级。选哪个看场景：高并发选 Redis，强一致选 ZK。

---

## 它是怎么解决问题的？

### 一、核心数据模型：Znode

ZooKeeper 的数据模型类似 **Unix 文件系统**——一棵树的节点（Znode），每个 Znode 可以存少量数据（默认上限 1MB）。

```
ZooKeeper 数据树：
  /
  ├── /services
  │   ├── /order-service
  │   │   ├── node-001  (临时节点，存 "192.168.1.10:8080")
  │   │   └── node-002  (临时节点，存 "192.168.1.11:8080")
  │   └── /user-service
  │       └── node-001
  ├── /config
  │   └── /db-config    (持久节点，存数据库配置 JSON)
  └── /locks
      └── /order-lock-0000000001  (临时顺序节点)
```

#### Znode 四种类型

| 类型 | 创建方式 | 生命周期 | 典型用途 |
|------|----------|----------|----------|
| 持久节点（Persistent） | `PERSISTENT` | 永久存在，除非主动删除 | 配置存储、元数据 |
| 持久顺序节点 | `PERSISTENT_SEQUENTIAL` | 永久存在，名称自动加序号 | 分布式队列、公平锁 |
| 临时节点（Ephemeral） | `EPHEMERAL` | 客户端会话结束自动删除 | **服务注册发现** |
| 临时顺序节点 | `EPHEMERAL_SEQUENTIAL` | 会话结束删除，名称自动加序号 | **分布式锁** |

**临时节点的核心价值**：客户端断开连接（Crash 或网络故障），ZK 自动删除该客户端创建的所有临时节点。这让"服务存活检测"变得极其简单——不需要心跳，靠 TCP 连接本身。

### 二、Session 会话机制

客户端连接 ZK 时建立一个 **Session**，有一个 **sessionTimeout**（默认 2×tickTime = 4秒）。

```
客户端 ↔ ZK 集群

建立连接 → 创建 Session（分配 sessionId + password）
         → 定期发送心跳（PING）维持会话

两种情况会话失效：
1. 客户端主动关闭（sessionTimeout 内没心跳）
2. 网络分区，超过 sessionTimeout 没收到心跳
→ 所有该客户端的临时节点被自动删除
```

**为什么 sessionTimeout 不能太短？** 网络抖动时，短暂的不可达会导致会话失效，临时节点被误删，服务被误判下线。

**为什么 sessionTimeout 不能太长？** 客户端真的 Crash 了，要等很久才能被检测到，故障转移慢。

**建议**：`sessionTimeout = 2 × tickTime = 4000ms`，网络不稳定时可适当调大（如 8000ms）。

### 三、Watch 机制（监听）

Watch 是 ZK 的 **推送机制**——客户端可以对某个 Znode 注册 Watch，当 Znode 发生变化时，ZK 会 **推送一个通知** 给客户端。

```java
// 监听 /config/db-config 的数据变化
byte[] data = zk.getData("/config/db-config",
    new Watcher() {
        @Override
        public void process(WatchedEvent event) {
            if (event.getType() == EventType.NodeDataChanged) {
                System.out.println("配置变更了！");
                reloadConfig();
                // ⚠️ Watch 是一次性的，触发后要重新注册！
                reRegisterWatch();
            }
        }
    }, null);
```

#### Watch 的关键特性

| 特性 | 说明 |
|------|------|
| **一次性** | Watch 触发一次后就失效，要持续监听必须重新注册 |
| **轻量级** | ZK 服务端不维持订阅状态，只记录"哪个客户端监听了哪个节点" |
| **顺序保证** | Watch 回调的顺序和 ZK 服务端事件发生的顺序一致 |
| **只通知，不传数据** | Watch 通知只包含事件类型，不包含新数据（需要客户端自己再去读） |

**为什么 Watch 是一次性的？**

这是 ZK 的核心设计取舍：**避免在服务端维持大量订阅状态**。

如果 Watch 是永久的，ZK 服务端要维护"每个客户端监听了哪些节点"的映射表。在分布式系统里，**状态就是成本**——状态越多，复杂度越高，故障恢复越慢。

ZK 的选择是：**服务端只做轻量级通知（无状态），客户端负责重新注册（客户端维护状态）**。这是"最终一致"和"简单设计"的权衡。

> **etcd 的 Watch 是永久的**（基于 gRPC 流），因为 etcd 的设计目标是"更好的 API 体验"。两种设计没有绝对对错，是权衡不同。

### 四、ZAB 协议（ZooKeeper Atomic Broadcast）

ZAB（ZooKeeper Atomic Broadcast）是 ZK 专用的 **原子广播协议**，类似 Paxos，但专门为 ZK 设计。

ZAB 有两种模式：

```
┌─────────────────────────────────────────────────────┐
│              ZAB 协议两种模式                          │
├─────────────────────────────────────────────────────┤
│  1. 崩溃恢复模式（Crash Recovery）                    │
│     → 集群启动时，或 Leader 崩溃时触发                │
│     → 选举新 Leader，同步数据（保证所有节点状态一致）      │
│                                                      │
│  2. 消息广播模式（Message Broadcast）                  │
│     → Leader 接收写请求，广播 Proposal 给所有 Follower  │
│     → 超过半数（Quorum）Follower ACK → 提交（Commit）   │
│     → 保证所有节点看到相同的提交顺序                     │
└─────────────────────────────────────────────────────┘
```

#### 为什么是"超过半数"？

```
3 节点集群（Quorum = 2）：
  Leader + 1 Follower 存活 → 可以写（2 ≥ Quorum）
  Leader 单独存活 → 不能写（1 < Quorum）

5 节点集群（Quorum = 3）：
  Leader + 2 Follower 存活 → 可以写
  只存活 2 个节点 → 不能写

原因：防止脑裂（Split-Brain）
  网络分区时，两个子集群各自选举 Leader →
  如果不需要"超过半数"，两个 Leader 都能写 → 数据不一致
  ZAB 保证：最多只有一个子集群能满足"超过半数"，只有一个 Leader 能写
```

**Quorum 计算**：`Quorum = (节点总数 / 2) + 1`，所以 ZK 集群通常部署 **奇数个节点**（3、5、7）。

| 集群大小 | Quorum | 允许故障节点数 | 说明 |
|----------|---------|----------------|------|
| 1 | 1 | 0 | 单点，不推荐 |
| 3 | 2 | 1 | 允许 1 个节点故障 |
| 5 | 3 | 2 | 推荐生产环境 |
| 7 | 4 | 3 | 大集群 |
| 8 | 5 | 3 | 和 7 一样，但多一个节点成本 |

---

### Leader 选举

当集群启动或 Leader 崩溃时，ZK 会进入 **崩溃恢复模式**，选举一个新的 Leader。

### 选举规则：NP + myid 最大者胜出

每个节点有两票：**ZXID**（事务 ID）+ **myid**（配置文件里的服务器编号）。

```
选举比较规则（按优先级）：
  1. 先比 ZXID（epoch + counter）
     → ZXID 越大，表示数据越新，优先当 Leader
  2. ZXID 相同，比 myid
     → myid 越大，越可能成为 Leader
```

**ZXID 结构**（64 位）：
```
  ┌──────────────────┬──────────────────┐
  │  epoch (32 bit)  │  counter (32 bit) │
  └──────────────────┴──────────────────┘
    epoch：Leader 任期号，每次选举 +1
    counter：当前 epoch 内的事务计数器
```

### 选举流程（简化）

```
假设 3 节点集群：myid=1(ZXID=100), myid=2(ZXID=120), myid=3(ZXID=110)

第一轮投票（每个节点投自己）：
  Node1 → (120, 1)  ← 自己的 ZXID=100, myid=1
  Node2 → (120, 2)  ← 自己的 ZXID=120, myid=2
  Node3 → (120, 3)  ← 自己的 ZXID=110, myid=3

收到其他节点的选票后，比较：
  Node1 收到 Node2 的票 (120, 2)，比自己的 (100, 1) 大 → 改投 Node2
  Node3 收到 Node2 的票 (120, 2)，比自己的 (110, 3) 大 → 改投 Node2

第二轮投票：
  Node1 → (120, 2)
  Node2 → (120, 2)
  Node3 → (120, 2)

Node2 获得超过半数选票 → Node2 成为 Leader
```

### Observer 角色

除了 Leader 和 Follower，ZK 还有第三种角色：**Observer**。

```
Leader  ：处理写请求，发起投票
Follower：处理读请求，参与投票（选 Leader + 写请求 ACK）
Observer ：处理读请求，不参与投票  ← 关键区别
```

**Observer 的价值**：
- 增加 Observer 可以提高 **读吞吐量**（多一个节点处理读请求）
- 但不增加 **写延迟**（Observer 不参与投票，不影响 Quorum 计算）
- 适合跨机房部署：远程机房部署 Observer，本地机房部署 Leader+Follower

```properties
### zoo.cfg 配置 Observer
server.1=192.168.1.1:2888:3888
server.2=192.168.1.2:2888:3888
server.3=192.168.1.3:2888:3888
server.4=192.168.2.4:2888:3888:observer   # 远程机房，Observer
```

---

### 典型应用场景

### 场景一：服务注册与发现（Dubbo 默认方案）

```
服务注册流程（以 Dubbo 为例）：
  1. 订单服务启动，连接 ZK
  2. 在 /dubbo/com.xxx.OrderService/providers 下
     创建临时节点，值 = "dubbo://192.168.1.10:20880/..."
  3. 订单服务崩溃 → TCP 连接断开 → 临时节点自动删除
     → 消费者收到 Watch 通知，从可用列表移除该节点

服务发现流程：
  1. 消费者启动，从 /dubbo/com.xxx.OrderService/providers
     读取所有子节点（获取所有可用服务提供者地址）
  2. 注册 Watch：当 providers 子节点变化时，重新拉取列表
  3. 根据负载均衡策略，选一个服务提供者发起调用
```

**为什么用临时节点？** 服务崩溃后，ZK 自动删除临时节点，消费者自动感知，不需要心跳机制。

**Dubbo 的 ZK 路径规范**：
```
/dubbo
  └── /com.xxx.OrderService       (服务接口全限定名)
      ├── /providers              (临时节点，存提供者地址)
      ├── /consumers              (临时节点，存消费者地址)
      └── /configurators          (持久节点，存动态配置)
```

### 场景二：配置中心

```
配置中心流程：
  1. 运维在 /config/db-config 写入数据库配置（JSON）
  2. 所有应用启动时读取 /config/db-config 的数据
  3. 所有应用对 /config/db-config 注册 Watch
  4. 配置变更 → ZK 推送 Watch 事件给所有客户端
  5. 客户端收到事件 → 重新读取配置 + 重新注册 Watch
```

**为什么 ZK 适合做配置中心？**
- Watch 机制：配置变更实时推送
- Znode 存数据：配置存储在 ZK，不需要额外数据库
- 强一致：所有客户端看到的配置版本一致，不会出现"有的应用用了新配置，有的用了旧配置"

**局限性**：Znode 存储上限 1MB，不适合存大配置（如整个 Spring 的 YAML）。大配置可以存到 Znode 里一个 **路径指针**（如 "配置存在 MinIO 的 xxx 路径"），或者直接用一个专门的配置中心（Nacos、Apollo）。

### 场景三：分布式锁

> 详细实现见 [[08_分布式与架构/02_分布式锁/ZooKeeper分布式锁]]（临时顺序节点 + Watch 前一个节点）

**一句话原理**：在 `/locks/order` 下创建临时顺序节点，序列号最小的获得锁；没获得锁的客户端对前一个节点注册 Watch，前一个节点删除时收到通知，再检查自己是不是最小。

**Curator 封装（生产推荐）**：
```java
InterProcessMutex lock = new InterProcessMutex(client, "/locks/order");
try {
    if (lock.acquire(5, TimeUnit.SECONDS)) {
        processOrder();
    }
} finally {
    lock.release();
}
```

---

### Curator 客户端（生产必用）

原生 ZooKeeper 客户端 API 非常底层，需要自己处理：连接断开重连、重试、Watch 注册、分布式锁实现等。**生产环境用 Curator**（Netflix 开源，Apache 维护）。

### 连接管理

```java
// Curator 连接 ZK（生产标准写法）
RetryPolicy retryPolicy = new ExponentialBackoffRetry(
    1000,   // 初始重试间隔（ms）
    3       // 最大重试次数
);

CuratorFramework client = CuratorFrameworkFactory.builder()
    .connectString("zk1:2181,zk2:2181,zk3:2181")  // 只需要配部分节点，Curator 会自动发现集群
    .retryPolicy(retryPolicy)
    .sessionTimeoutMs(60000)     // Session 超时（ms），默认 60000
    .connectionTimeoutMs(15000)  // 连接超时（ms），默认 15000
    .namespace("myapp")          // 命名空间（所有操作自动加上 /myapp 前缀）
    .build();

client.start();  // 启动客户端
```

**命名空间（namespace）的作用**：多个应用共用一个 ZK 集群时，自动隔离路径。
```
设置 namespace("myapp") 后：
  client.create().forPath("/config")  → 实际创建的是 /myapp/config
```

### 重试策略

| 策略 | 说明 |
|------|------|
| `ExponentialBackoffRetry` | 指数退避重试（推荐） |
| `RetryNTimes` | 固定次数重试 |
| `RetryOneTime` | 只重试一次 |
| `RetryUntilElapsed` | 在指定时间内不断重试 |

### 分布式锁

```java
// 可重入锁（最常用）
InterProcessMutex lock = new InterProcessMutex(client, "/locks/order");
lock.acquire(5, TimeUnit.SECONDS);  // 最多等 5 秒
try {
    processOrder();
} finally {
    lock.release();
}

// 读写锁
InterProcessReadWriteLock rwLock = new InterProcessReadWriteLock(client, "/locks/order");
InterProcessMutex readLock = rwLock.readLock();
InterProcessMutex writeLock = rwLock.writeLock();

// 信号量（分布式信号量，限制并发数）
InterProcessSemaphoreV2 semaphore = new InterProcessSemaphoreV2(client, "/semaphore", 10);
Lease lease = semaphore.acquire(5, TimeUnit.SECONDS);
try {
    // 最多 10 个客户端同时持有信号量
} finally {
    semaphore.returnLease(lease);
}
```

### 分布式计数器

```java
// 分布式原子整数（基于 ZK 实现，强一致）
DistributedAtomicInteger counter = new DistributedAtomicInteger(
    client, "/counters/order-id", new RetryNTimes(3, 1000));

// 原子自增
AtomicValue<Integer> result = counter.increment();
if (result.succeeded()) {
    System.out.println("新值：" + result.postValue());
}
```

### Leader 选举（Curator 封装）

```java
// 多个节点竞争 Leader，只有一个能当选，Leader 崩溃后自动重新选举
LeaderSelector leaderSelector = new LeaderSelector(client, "/leader/order-service",
    new LeaderSelectorListenerAdapter() {
        @Override
        public void takeLeadership(CuratorFramework client) throws Exception {
            // 这里是 Leader 逻辑，执行完（或抛异常）表示放弃 Leader
            System.out.println("我是 Leader！");
            Thread.sleep(Long.MAX_VALUE);  // 一直持有 Leader，直到 Crash
        }
    });

leaderSelector.autoRequeue();  // 放弃 Leader 后自动重新参与选举
leaderSelector.start();
```

---

### 部署与运维

### 集群规划

```
推荐配置：
  开发环境：1 节点（单点，不保证高可用）
  测试环境：3 节点（允许 1 个节点故障）
  生产环境：5 节点（允许 2 个节点故障，读写分离用 Observer 扩展读能力）

节点数必须是奇数（3、5、7），原因：
  - Quorum = (n/2) + 1，奇数节点能最大化允许故障数
  - 4 节点和 3 节点一样只允许 1 个故障，但多一个节点成本
```

### 关键配置参数（zoo.cfg）

```properties
### 基本配置
tickTime=2000              # ZK 时间单位（ms），所有时间参数都基于 tickTime
dataDir=/var/lib/zookeeper # 数据目录（存快照 + myid）
clientPort=2181            # 客户端连接端口

### 集群配置（每个节点配置所有节点）
server.1=zk1:2888:3888
server.2=zk2:2888:3888
server.3=zk3:2888:3888
### 格式：server.<myid>=<host>:<peer-port>:<election-port>
###   2888：Follower 和 Leader 通信端口
###   3888：选举端口

### 超时控制
initLimit=10               # Follower 启动后，同步 Leader 数据的超时时间（10×tickTime=20s）
syncLimit=5                # Follower 和 Leader 心跳超时（5×tickTime=10s）
sessionTimeout=4000         # 会话超时（客户端配置，建议 = 2×tickTime）

### 内存快照保留数
autopurge.snapRetainCount=3  # 保留最近 3 个快照
autopurge.purgeInterval=1    # 每天清理一次旧快照（单位：小时）
```

### 常见问题与排查

#### 问题1：羊群效应（Herd Effect）

```
现象：100 个客户端都 Watch 同一个节点（如 /config/db-config）
      配置变更时，ZK 向 100 个客户端推送通知
      100 个客户端同时来读 /config/db-config → ZK 压力激增

原因：Watch 粒度太粗，所有客户端都监听同一个节点

解决：
  1. 用 Curator 的 Cache（如 NodeCache、PathChildrenCache），
     它内部做了优化，合并了重复的 Watch
  2. 配置变更不频繁的场景，羊群效应影响不大，可以忽略
```

#### 问题2：Session 超时导致临时节点被误删

```
现象：服务正常运行，但注册中心里看不到该服务（临时节点被删了）

原因：
  1. GC 停顿（Full GC）超过 sessionTimeout，ZK 认为客户端 Crash
  2. 网络抖动，客户端和 ZK 之间的网络短暂不可达

解决：
  1. 用 G1/ZGC，减少长时间 GC 停顿
  2. sessionTimeout 设长一点（如 30000ms）
  3. 用 Curator，它会自动处理重连和 Watch 重新注册
```

#### 问题3：磁盘空间不足

```
现象：ZK 频繁抛出 Disk FULL 错误，集群不可用

原因：ZK 每次写请求都写事务日志（类似于 WAL），
     快照（Snapshot）也会占磁盘空间

解决：
  1. 配置 autopurge，自动清理旧快照和日志
  2. 事务日志和数据快照存不同磁盘（dataDir 和 dataLogDir 分开）
  3. 监控磁盘使用率，超过 80% 告警
```

#### 问题4：ZK 集群全部重启后，Leader 选举不出来

```
现象：整个集群重启后，所有节点都是 LOOKING 状态，无法选举出 Leader

原因：所有节点的 ZXID 不一致（部分节点数据没同步完就 Crash）
     或者 myid 配置错误

解决：
  1. 先启动 ZXID 最大的节点（数据最完整），让它先成为 Leader
  2. 再依次启动其他节点
  3. 检查 zoo.cfg 里 server.x 的 myid 和 dataDir/myid 文件是否一致
```

---

## 深入原理

### ZooKeeper vs etcd vs Consul vs Nacos

| 维度 | ZooKeeper | etcd | Consul | Nacos |
|------|-----------|------|--------|-------|
| **一致性协议** | ZAB | Raft | Raft | Raft（CP 模式）/ 自研（AP 模式） |
| **CAP 属性** | CP | CP | CP | **CP + AP 可切换** |
| **性能（写）** | 中等 | 高 | 高 | 高 |
| **服务发现** | 需自己实现（临时节点+Watch） | 需自己实现 | **原生支持**（健康检查+服务目录） | **原生支持**（CP/AP 双模式） |
| **配置管理** | 支持（Watch） | 支持（Watch，gRPC 流） | 支持 | 支持（长轮询 + MD5 比对） |
| **分布式锁** | 需自己实现（临时顺序节点） | 需自己实现（租约+事务） | 需自己实现 | 支持（基于 Raft） |
| **健康检查** | 无（依赖 Session） | 无 | **原生支持**（多种检查方式） | 支持 |
| **适用场景** | Hadoop/Dubbo 生态 | Kubernetes 生态 | 微服务全栈 | 微服务全栈（国内主流） |
| **API 友好度** | 低（Watch 一次性） | 高（gRPC 流，Watch 永久） | 高（HTTP API） | 高（HTTP API） |
| **管理界面** | 无（第三方：ZK UI） | 无（第三方） | **原生 Web UI** | **原生管理界面** |

#### 为什么选 A 不选 B？

**选 ZooKeeper**：
- 项目用了 Dubbo（Dubbo 对 ZK 的支持最成熟）
- 维护了 Hadoop/Kafka 生态（它们强依赖 ZK）
- 团队对 ZK 熟悉

**选 etcd**：
- 项目跑在 Kubernetes 上（K8s 用 etcd 做存储，不需要再维护一套 ZK）
- 需要更好的 Watch API（etcd v3 的 Watch 是永久的，基于 gRPC 流）

**选 Consul**：
- 需要开箱即用的服务发现（健康检查 + 服务目录 + Web UI 全套）
- 多数据中心场景（Consul 原生支持多 DC 同步）

**选 Nacos**：
- 国内项目，Spring Cloud Alibaba 生态
- 需要 **CP/AP 可切换**（注册发现用 AP，配置中心用 CP）
- 需要统一的服务发现和配置管理平台

> **趋势**：国内新项目越来越多用 Nacos，老项目（尤其是 Dubbo 体系）继续用 ZK。etcd 主要在 K8s 生态里。

---

## 正确使用方式

### 正确用法

**1. 生产环境用 Curator，不用原生 ZK 客户端**

```java
// ✅ 正确：用 Curator
RetryPolicy retryPolicy = new ExponentialBackoffRetry(1000, 3);
CuratorFramework client = CuratorFrameworkFactory.newClient("zk1:2181,zk2:2181", retryPolicy);
client.start();

// ❌ 错误：用原生 ZK 客户端
ZooKeeper zk = new ZooKeeper("zk1:2181", 3000, event -> {});
// 问题：要自己处理重连、重试、Watch 重新注册
```

**2. 服务注册用临时节点，配置用持久节点**

```
/services/order/node-001  → 临时节点（服务挂了自动删除）
/config/db-config        → 持久节点（配置永久保存）
```

**3. Watch 重新注册要放在 finally 块或回调里**

```java
// ✅ 正确：确保 Watch 一定能重新注册
zk.getData("/config/db", new Watcher() {
    @Override
    public void process(WatchedEvent event) {
        try {
            reloadConfig();
        } finally {
            reRegisterWatch();  // 放在 finally 里，确保执行
        }
    }
}, null);
```

**4. 集群节点数用奇数（3、5、7）**

```
3 节点：Quorum=2，允许 1 个故障
4 节点：Quorum=3，允许 1 个故障  ← 和 3 节点一样，但多一台机器成本
5 节点：Quorum=3，允许 2 个故障  ← 推荐生产环境
```

### 错误用法及后果

**错误1：Watch 只注册一次，忘了重新注册**

```java
// ❌ 错误
zk.getData("/config/db", new Watcher() {
    @Override
    public void process(WatchedEvent event) {
        reloadConfig();
        // 没重新注册 Watch！
    }
}, null);
```

**后果**：配置第二次变更时，客户端收不到通知，配置不一致。

**错误2：把 ZK 当数据库用（存大量数据）**

```java
// ❌ 错误：Znode 上限 1MB，且 ZK 不适合存大文件
zk.create("/bigdata", readLargeFile(), ZooDefs.Ids.OPEN_ACL_UNSAFE, CreateMode.PERSISTENT);
```

**后果**：
1. Znode 数据超过 1MB，创建失败（`Packet len1000000 is out of range!`）
2. 就算调大 `jute.maxbuffer`，ZK 性能也会严重下降（ZK 设计用于存小数据）

**正确做法**：大文件存 HDFS/MinIO，ZK 只存文件路径指针。

**错误3：sessionTimeout 设太短，网络抖动就丢锁**

```java
// ❌ 错误
ZooKeeper zk = new ZooKeeper("zk1:2181", 1000, watcher);  // sessionTimeout=1秒
```

**后果**：网络偶尔抖动（1 秒以上），会话断开，临时节点被删，分布式锁丢失。

**修复**：`sessionTimeout` 设为 `2 × tickTime = 4000ms` 以上。

---

## 边界情况和坑

### 坑1：ZXID 溢出（ epoch 用完了）

```
ZXID 结构：32 bit epoch + 32 bit counter

counter 上限：2^32 - 1 ≈ 43 亿
假设每毫秒 1000 次写请求 → 约 5 天用完

但实际上：
  - 每次选举，epoch + 1，counter 重置为 0
  - epoch 上限：2^32 - 1 ≈ 43 亿次选举
  - 正常集群不会这么频繁选举

结论：几乎不可能遇到，但理论上存在。ZK 3.5+ 版本有保护机制。
```

### 坑2：Watcher 丢失事件

```
场景：
  1. 客户端对 /config/db 注册 Watch
  2. /config/db 连续变了 2 次（Watch 还没触发）
  3. Watch 触发时，客户端只能收到"变了"的通知，不知道变了几次

原因：Watch 只保证"最终会通知你"，不保证"每次变更都通知"
```

**解决**：客户端收到 Watch 通知后，**重新读数据，对比版本号**（Stat.version），判断是不是自己想要的版本。

### 坑3：大量的临时节点导致选举慢

```
场景：ZK 里注册了几万个临时节点（每个微服务实例都注册）
      Leader 崩溃，重新选举
      新 Leader 启动后，要检查所有临时节点的 Session 是否还存活

后果：选举和恢复时间变长（几十秒甚至几分钟）
```

**解决**：
1. 不要在 ZK 里注册太多临时节点（考虑用 Nacos/etcd 替代）
2. 用 Observer 扩展读能力，减少选举频率

---
