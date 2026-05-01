# Linux 内核原理

> **核心认知**：Linux 内核是连接硬件和应用程序的核心。理解系统调用、中断、内核模块、内核参数调优，是排查线上疑难问题（CPU 飙高、网络异常、OOM）的基础。

---

## 1. Linux 内核架构

### 1.1 宏内核 vs 微内核

| 维度 | 宏内核（Linux） | 微内核（QNX/Minix） |
|------|---------------|-------------------|
| 架构 | 所有核心服务运行在内核态 | 只有最基础的功能在内核态 |
| 性能 | **高**（无用户态↔内核态切换） | 较低（服务间需要 IPC） |
| 稳定性 | 一个模块崩溃可能导致内核崩溃 | 更稳定（模块隔离） |
| 扩展性 | 可加载内核模块（LKM） | 服务独立更新 |
| 代表 | Linux、Windows | QNX、Minix、seL4 |

### 1.2 Linux 内核的组成

```
┌─────────────────────────────────────────────┐
│               系统调用接口 (SCI)               │
│         用户程序通过系统调用进入内核             │
├─────────────────────────────────────────────┤
│  进程管理    │  内存管理    │  文件系统    │  网络    │
│  进程调度    │  虚拟内存    │  ext4/xfs   │  TCP/IP │
│  进程通信    │  页面置换    │  VFS        │  Socket │
│  信号处理    │  内存分配    │  inode      │  Netfilter│
├─────────────────────────────────────────────┤
│               设备驱动                        │
│  块设备（磁盘）│ 字符设备（终端）│ 网络设备（网卡）│
├─────────────────────────────────────────────┤
│               硬件抽象层                       │
│  中断控制器  │  定时器  │  DMA  │  总线       │
├─────────────────────────────────────────────┤
│               硬件                           │
│  CPU │ 内存 │ 磁盘 │ 网卡 │ GPU              │
└─────────────────────────────────────────────┘
```

---

## 2. 系统调用

### 2.1 系统调用机制

```
用户程序调用 read() 的完整流程：

1. 用户程序调用 C 库函数 read()
2. C 库函数将参数放入寄存器，执行 syscall 指令（x86_64）
3. CPU 切换到内核态（Ring 3 → Ring 0）
4. CPU 根据系统调用号（存储在 rax 寄存器）查找系统调用表
5. 执行内核中的 sys_read() 函数
6. 执行完成后，CPU 切换回用户态（Ring 0 → Ring 3）
7. 返回结果给用户程序

整个过程中：
  - 用户态→内核态切换：保存用户态寄存器，加载内核态寄存器
  - 内核态→用户态切换：恢复用户态寄存器
  - 一次系统调用 ≈ 100~1000 纳秒
```

### 2.2 常用系统调用分类

| 分类 | 系统调用 | Java 对应 |
|------|---------|---------|
| 文件 IO | open/read/write/close/lseek/mmap | FileInputStream / FileChannel / MappedByteBuffer |
| 网络 IO | socket/bind/listen/accept/connect/send/recv | Socket / ServerSocket / Netty |
| 进程管理 | fork/exec/wait/exit/clone | ProcessBuilder / Runtime.exec() |
| 内存管理 | brk/mmap/munmap/mprotect | DirectByteBuffer / Unsafe.allocateMemory() |
| 信号 | kill/sigaction/sigprocmask | Signal / ShutdownHook |
| 信息查询 | stat/fstat/getpid/getuid | Files.getAttribute() / ProcessHandle |
| 时间 | gettimeofday/clock_gettime/nanosleep | System.currentTimeMillis() / Thread.sleep() |

### 2.3 strace：追踪系统调用

```bash
# 追踪进程的所有系统调用
strace -p <pid>

# 追踪某个命令的系统调用
strace ls -la

# 统计系统调用次数和耗时
strace -c -p <pid>

# 只追踪特定系统调用
strace -e trace=read,write -p <pid>

# 显示系统调用的时间
strace -T -p <pid>

# 典型应用：
# 排查文件操作缓慢 → strace 看哪个 read/write 耗时长
# 排查 Too many open files → strace 看打开了哪些文件没关闭
# 排查 CPU 高 → strace -c 看哪个系统调用最频繁
```

---

## 3. 中断与软中断

### 3.1 硬中断（Hardware Interrupt）

```
外部设备通知 CPU：

  网卡收到数据包 → 发送硬件中断 → CPU 暂停当前任务 → 执行网卡中断处理程序
  → 将数据包放入内存缓冲区 → 触发软中断 → 恢复之前任务

中断处理分为两部分：
  上半部（Top Half）：在中断上下文中执行，不能休眠，处理紧急操作
  下半部（Bottom Half）：在软中断/任务队列中执行，可以休眠，处理耗时操作
```

### 3.2 软中断（Softirq）

```
软中断用于处理"不紧急但需要快速响应"的工作：

  网卡收到数据 → 硬件中断（只拷贝到内核缓冲区）
  → 触发 NET_RX_SOFTIRQ 软中断
  → 内核线程 ksoftirqd 处理 TCP/IP 协议栈
  → 将数据放入 Socket 接收缓冲区
  → 唤醒等待的应用程序线程

Linux 中 10 个软中断类型：
  HI_SOFTIRQ, TIMER_SOFTIRQ, NET_TX_SOFTIRQ, NET_RX_SOFTIRQ,
  TASKLET_SOFTIRQ, SCHED_SOFTIRQ, HRTIMER_SOFTIRQ, RCU_SOFTIRQ
```

### 3.3 查看中断统计

```bash
# 查看 CPU 中断统计
cat /proc/interrupts

# 查看软中断统计
cat /proc/softirqs

# 查看 CPU 软中断消耗（si 列）
vmstat 1
# si: soft interrupt（软中断次数）
# 如果 si 持续很高 → 可能是网络流量过大导致软中断风暴
```

---

## 4. 内核模块

### 4.1 可加载内核模块（LKM）

```
LKM（Loadable Kernel Module）允许动态加载/卸载内核代码：

  .ko 文件（Kernel Object）= 内核模块的二进制文件

常见内核模块：
  - 网络驱动（e1000, ixgbe）
  - 文件系统驱动（ext4, xfs）
  - Netfilter（iptables/nftables）
  - eBPF（现代的可编程内核模块）
```

```bash
# 查看已加载的模块
lsmod

# 加载模块
modprobe <module_name>

# 卸载模块
modprobe -r <module_name>

# 查看模块信息
modinfo <module_name>
```

---

## 5. 内核参数调优

### 5.1 查看和修改内核参数

```bash
# 查看所有参数
sysctl -a

# 查看特定参数
sysctl net.ipv4.tcp_tw_reuse
sysctl net.core.somaxconn

# 临时修改（重启后失效）
sysctl -w net.ipv4.tcp_tw_reuse=1

# 永久修改（写入配置文件）
echo "net.ipv4.tcp_tw_reuse = 1" >> /etc/sysctl.conf
sysctl -p  # 重新加载

# 直接修改（立即生效，重启失效）
echo 1 > /proc/sys/net/ipv4/tcp_tw_reuse
```

### 5.2 TCP 相关参数

```bash
# 连接队列
net.core.somaxconn = 8192            # 全连接队列最大长度
net.ipv4.tcp_max_syn_backlog = 8192  # 半连接队列最大长度

# TIME_WAIT
net.ipv4.tcp_tw_reuse = 1            # 复用 TIME_WAIT 连接（推荐）
net.ipv4.tcp_tw_recycle = 0          # 不建议开启（NAT 问题）
net.ipv4.tcp_fin_timeout = 30        # FIN_WAIT_2 超时时间

# KeepAlive
net.ipv4.tcp_keepalive_time = 600    # 空闲多久开始探测
net.ipv4.tcp_keepalive_intvl = 30    # 探测间隔
net.ipv4.tcp_keepalive_probes = 3    # 探测次数

# 缓冲区
net.core.rmem_max = 16777216         # 最大接收缓冲区（16MB）
net.core.wmem_max = 16777216         # 最大发送缓冲区（16MB）
net.ipv4.tcp_rmem = 4096 87380 16777216  # TCP 接收缓冲区（min/default/max）
net.ipv4.tcp_wmem = 4096 65536 16777216  # TCP 发送缓冲区

# 拥塞控制
net.ipv4.tcp_congestion_control = bbr  # 使用 BBR 算法（Linux 4.9+）

# SYN Flood 防御
net.ipv4.tcp_syncookies = 1          # 开启 SYN Cookies
```

### 5.3 文件相关参数

```bash
# 文件描述符
fs.file-max = 1000000              # 系统最大 fd 数
# 单进程限制通过 ulimit -n 设置

# 内存
vm.swappiness = 10                  # 降低 Swap 使用倾向（0~100）
vm.overcommit_memory = 0            # 内存超分配策略（0: 启发式，1: 允许所有，2: 不允许超物理内存）
vm.dirty_ratio = 20                 # 脏页占物理内存 20% 时触发写回
vm.dirty_background_ratio = 10      # 脏页占物理内存 10% 时后台写回
```

---

## 6. /proc 文件系统

`/proc` 是 Linux 虚拟文件系统，提供了内核和进程信息的接口。

```bash
# CPU 信息
cat /proc/cpuinfo

# 内存信息
cat /proc/meminfo

# 系统版本
cat /proc/version

# 查看进程信息
cat /proc/<pid>/status       # 进程状态、内存使用
cat /proc/<pid>/maps         # 内存映射
cat /proc/<pid>/fd           # 打开的文件描述符
cat /proc/<pid>/limits       # 资源限制
cat /proc/<pid>/cmdline      # 启动命令

# 系统级信息
cat /proc/sys/fs/file-max    # 系统最大 fd 数
cat /proc/sys/net/ipv4/*     # 网络参数
```

---

## 7. 内核与 Java 的关系

| 内核概念 | Java/JVM 对应 |
|---------|-------------|
| 系统调用 | native 方法（JNI），JVM 底层频繁调用 |
| 进程 | JVM 进程 |
| 线程 | Java Thread（1:1 模型） |
| 虚拟内存 | JVM 堆/元空间/直接内存 |
| 页面置换 | GC（思想类似） |
| 文件描述符 | FileDescriptor、FileChannel |
| 信号 | ShutdownHook（SIGTERM） |
| OOM Killer | JVM 被 Kill（物理内存不足时） |
| 内核参数 | 影响 JVM 和应用行为（somaxconn、tcp_tw_reuse 等） |
| 网络软中断 | Netty 的 epoll（依赖内核的网络栈） |

---

## 8. 面试高频问题

### Q1: 什么是系统调用？一次系统调用的开销有多大？

**答**：系统调用是应用程序请求操作系统内核服务的接口。开销主要包括：用户态↔内核态切换（保存/恢复寄存器）、权限检查、内核执行逻辑。一次系统调用约 100~1000 纳秒。Java 中频繁的 IO 应该使用 BufferedInputStream/NIO 减少 system call 次数。

### Q2: 如何用 strace 排查 Java 应用的问题？

**答**：`strace -p <pid>` 可以追踪 JVM 进程的所有系统调用。常见排查场景：1）IO 慢 → 看 read/write 耗时；2）CPU 高 → 看 system call 频率；3）文件泄漏 → 看打开了哪些 fd 没关闭；4）网络问题 → 看 sendto/recvfrom 的行为。配合 `-c` 统计、`-T` 显示时间、`-e trace=xxx` 过滤。

### Q3: Linux 中如何调优 TCP 参数？

**答**：核心参数包括：`net.core.somaxconn`（全连接队列）、`net.ipv4.tcp_max_syn_backlog`（半连接队列）、`net.ipv4.tcp_tw_reuse`（复用 TIME_WAIT）、`net.ipv4.tcp_syncookies`（防御 SYN Flood）、`net.core.rmem_max/wmem_max`（缓冲区大小）。通过 `sysctl -w` 临时修改或写入 `/etc/sysctl.conf` 永久生效。

### Q4: 什么是软中断？为什么 si 持续很高会影响性能？

**答**：软中断是内核处理"不紧急但需要快速响应"的工作机制（如网络数据包的 TCP/IP 处理、定时器）。网卡收到数据后先通过硬件中断拷贝到内核缓冲区，然后触发软中断完成协议栈处理。高网络流量时软中断频繁，si（soft interrupt）持续高，CPU 大量时间在处理软中断，应用程序分配到的 CPU 时间减少，表现为"CPU 高但应用处理慢"。

---

> **面试加分项**：能用 strace 排查实际问题、能说出系统调用与 Java native 方法的关系、能调优 TCP 内核参数解决线上连接问题、能解释软中断风暴的原因和解决思路。
