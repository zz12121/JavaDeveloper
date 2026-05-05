# Docker核心

> Docker 的核心价值不是「轻量级虚拟机」，而是**环境一致性**：开发环境跑通了，到任何地方都能跑通。

---

## 这个问题为什么存在？

**「在我机器上能跑」综合征**：

```
开发：在我本地跑得好好的！
测试：我这报错啊。
运维：我这也报错。

原因：
- 开发用 JDK 17，服务器是 JDK 8
- 开发用 MySQL 8.0，服务器是 MySQL 5.7
- 开发用的是 Mac，服务器是 Linux（文件路径分隔符不同）
```

传统解法：写在文档里 ——「部署手册 v3.2.docx」，但文档会过期，会漏步骤。

**Docker 的解法**：把「环境」打包成镜像，镜像到哪，环境到哪。

---

## 它是怎么解决问题的？

### Docker 架构

```
Docker 架构：
┌─────────────────────────────────────────────┐
│            Docker Client（命令行）           │
│         docker pull / docker run ...        │
└──────────────────┬──────────────────────────┘
                   │ REST API
┌──────────────────▼──────────────────────────┐
│          Docker Daemon（dockerd）           │
│  镜像构建 / 容器管理 / 网络管理 / 存储管理  │
└──┬──────────────┬──────────────┬───────────┘
   │              │              │
┌──▼──────┐ ┌────▼─────┐ ┌────▼─────┐
│ 镜像仓库  │ │ 容器运行时 │ │ 存储驱动  │
│ (Registry)│ │(runc/containerd)│ (Overlay2)│
└──────────┘ └──────────┘ └──────────┘
```

**关键组件**：

| 组件 | 作用 |
|------|------|
| Docker Client | 用户操作的命令行界面 |
| Docker Daemon | 后台守护进程，管理 Docker 对象 |
| Image（镜像） | 只读模板，包含运行程序所需的一切 |
| Container（容器） | 镜像的运行实例，在镜像上加了一个可写层 |
| Registry | 镜像仓库（Docker Hub / 私有仓库） |
| containerd | 容器运行时管理（daemon 和 runc 之间的桥梁） |
| runc | 底层容器运行时（按 OCI 规范创建容器） |

### 镜像分层（Layered File System）

```
Docker 镜像的分层结构：
┌─────────────────────┐
│  可写层（容器特有）   │  ← docker commit 会把这一层打包成新镜像
├─────────────────────┤
│  ADD app.jar         │  ← 你的应用（最上层，经常变化）
├─────────────────────┤
│  RUN apt-get install │  ← 依赖安装（中层，偶尔变化）
├─────────────────────┤
│  FROM openjdk:17     │  ← 基础镜像（底层，几乎不变）
└─────────────────────┘
```

**分层的好处**：

1. **共享基础层**：10 个基于 `openjdk:17` 的镜像，只需存储一份 `openjdk:17` 层
2. **构建缓存**：Dockerfile 中某层没变，直接复用缓存，构建飞快
3. **增量传输**：推送到仓库时，只需传输新增的层

**OverlayFS（存储驱动）如何工作**：

```
OverlayFS 合并多层为一个统一的视图：
lowerdir  →  底层（只读，多个层）
upperdir  →  可写层（容器特有）
merged    →  合并后的视图（容器看到的文件系统）

读文件：从 upperdir 开始找，找不到就去 lowerdir
写文件：写在 upperdir（copy-on-write）
删除文件：在 upperdir 创建「白障文件」（wh.文件名），屏蔽 lowerdir 的文件
```

### 容器本质：Namespace + Cgroups

**容器不是虚拟机**！

```
虚拟机：
App → Lib → Guest OS → Hypervisor → Host OS → Hardware
（每层都有开销，启动慢，占用资源多）

容器：
App → Lib → Container Runtime → Host OS → Hardware
（共享 Host 内核，几乎没有额外开销，秒级启动）
```

**Namespace（隔离）**：让容器以为自己有独立的系统资源。

| Namespace | 隔离内容 |
|-----------|---------|
| `PID` | 进程 ID（容器内看到的 PID 从 1 开始） |
| `NET` | 网络栈（容器有独立的 IP、端口空间） |
| `MNT` | 挂载点（容器有独立的文件系统视图） |
| `UTS` | 主机名和域名 |
| `IPC` | 进程间通信（信号量、共享内存） |
| `USER` | 用户和组 ID |

**Cgroups（限制）**：限制容器能用的资源上限。

| Subsystem | 限制内容 |
|-----------|---------|
| `memory` | 内存使用上限（防止 OOM 拖垮宿主机） |
| `cpu` | CPU 使用上限（按权重或配额） |
| `blkio` | 块设备 IO 速率 |
| `pids` | 进程数上限（防止 fork 炸弹） |

```bash
# 查看某个容器的 Cgroups 限制
cat /sys/fs/cgroup/memory/docker/<container-id>/memory.limit_in_bytes
```

### Docker 网络模型

**默认网络模式**：

```bash
# 查看 Docker 网络
docker network ls

# 输出：
NETWORK ID   NAME       DRIVER    SCOPE
abc123       bridge     bridge    local    ← 默认网络（桥接）
def456       host       host      local    ← 共用宿主机网络（无隔离）
ghi789       none       null      local    ← 无网络（纯隔离）
```

| 模式 | 适用场景 | 性能 | 隔离性 |
|------|---------|------|--------|
| `bridge`（默认） | 单机容器通信 | 中等 | 好 |
| `host` | 高性能场景（如高性能计算） | 最好 | 差（和宿主机共用网络栈） |
| `none` | 安全敏感场景（不需要网络） | N/A | 最好 |
| `overlay` | 跨主机容器通信（Swarm/K8s） | 差 | 好 |
| `macvlan` | 容器需要独立 MAC 地址（如遗留系统） | 好 | 好 |

**Bridge 网络的数据流向**：

```
容器 A (172.17.0.2)                    容器 B (172.17.0.3)
        │                                        │
        ▼                                        ▼
┌──────────────────────────────────────────────────────┐
│           docker0 桥接网卡（172.17.0.1）            │
└──────────────────────────┬───────────────────────────┘
                           │
                           ▼
                    宿主机物理网卡（eth0）
                           │
                           ▼
                      外部网络
```

### 存储卷（Volume）

**问题**：容器是「无状态」的，容器删除 = 所有数据丢失。

**Docker 的三种存储方案**：

```bash
# 1. bind mount（绑定挂载）：把宿主机目录直接挂进容器
docker run -v /host/data:/app/data myapp
# 优点：路径完全可控
# 缺点：依赖宿主机目录结构，可移植性差

# 2. volume（卷）：Docker 管理的存储区域
docker volume create mydata
docker run -v mydata:/app/data myapp
# 优点：Docker 统一管理，不依赖宿主机目录结构，易于备份/迁移
# 缺点：需要额外命令管理

# 3. tmpfs（内存文件系统）：数据不写磁盘
docker run --tmpfs /app/cache myapp
# 优点：最快，无磁盘 IO
# 缺点：重启丢失
```

**对比**：

| 方案 | 数据存储位置 | 可移植性 | 性能 | 适用场景 |
|------|------------|---------|------|---------|
| bind mount | 宿主机指定路径 | 差 | 好 | 开发环境（代码热加载） |
| volume | Docker 管理区域（`/var/lib/docker/volumes/`） | 好 | 好 | 生产环境（数据库文件） |
| tmpfs | 内存 | 差 | 最好 | 缓存、临时文件 |

---

## 它和相似方案的本质区别是什么？

### Docker vs Podman

| 维度 | Docker | Podman |
|------|--------|--------|
| 架构 | Client-Server（需要 daemon） | Daemonless（无需后台进程） |
|  root 需求 | 需要（daemon 以 root 运行） | 不需要（支持 rootless） |
| 安全 | daemon 被突破 = root 权限 | 每个容器以普通用户运行 |
| 兼容性 | 生态最大 | 兼容 Docker CLI，可无缝替换 |
| 编排 | 需要 K8s/Swarm | 支持 K8s，也支持 Pod（类似 K8s Pod） |

**为什么 Podman 更安全？**
Docker 的 daemon 以 root 运行，daemon 被突破 = 攻击者拿到宿主机 root。
Podman 不需要 daemon，每个容器以启动 Podman 的用户身份运行。

### Docker vs 传统虚拟机

已在上文「容器本质」中解释。核心区别：**虚拟机有 Guest OS，容器共享 Host OS 内核**。

| 维度 | Docker 容器 | 虚拟机 |
|------|------------|--------|
| 启动速度 | 秒级 | 分钟级 |
| 资源占用 | 低（MB 级） | 高（GB 级） |
| 隔离性 | 弱（共享内核） | 强（硬件级虚拟化） |
| 性能 | 接近原生 | 有虚拟化开销 |
| 适用场景 | 微服务、CI/CD | 需要强隔离的多租户场景 |

### Docker vs LXC/LXD

LXC 是 Docker 的前身，但 Docker 的镜像机制和生态系统远强于 LXC。

| 维度 | Docker | LXC/LXD |
|------|--------|---------|
| 镜像机制 | 分层镜像，易于分发 | 整机模板，分发笨重 |
| 生态 | 极强（Docker Hub、K8s） | 弱 |
| 使用门槛 | 低 | 高 |

---

## 正确使用方式

### 1. 用 `.dockerignore` 防止垃圾文件进入镜像

```
# .dockerignore（类似 .gitignore）
.git
.idea
*.md
target/
*.log
```

**为什么需要？**
`docker build` 会把「构建上下文」（通常是 `.`）全部打包传给 daemon。没有 `.dockerignore`，你的 `.git` 目录（几百 MB）也会被传进去，构建极慢。

### 2. 用多阶段构建减小镜像体积

```dockerfile
# 错误的写法：把构建工具和源码都打进镜像
FROM openjdk:17
COPY . /app
RUN javac /app/Main.java
CMD ["java", "-cp", "/app", "Main"]

# 正确的写法：多阶段构建
FROM openjdk:17 AS builder    # 构建阶段
WORKDIR /app
COPY . .
RUN javac Main.java

FROM openjdk:17-jre-slim      # 运行阶段（更小的 JRE，不含 JDK）
COPY --from=builder /app/Main.class /app/
CMD ["java", "-cp", "/app", "Main"]
```

**效果**：镜像从 480MB（含 JDK）缩小到 220MB（只含 JRE）。

### 3. 用 `docker exec` 进入运行中的容器

```bash
# 进入容器 shell
docker exec -it mycontainer bash

# 在容器内执行一次性命令
docker exec mycontainer java -version
```

**不要用 `attach`**！`attach` 会连接到容器的主进程，退出时可能杀死容器。

### 4. 用 `docker system` 清理空间

```bash
# 查看 Docker 占用的磁盘空间
docker system df

# 清理所有未使用的资源（未使用的镜像、容器、网络、卷）
docker system prune -a --volumes
```

**谨慎使用 `prune`**！它会删除所有停止的容器和未使用的镜像，包括可能有用的旧镜像。

---

## 边界情况和坑

### 1. 容器时间和宿主机不一致

```
问题：容器内时区是 UTC，应用日志时间比实际慢 8 小时（中国时区）
原因：基础镜像默认用 UTC 时区
```

**解决**：

```dockerfile
# 在 Dockerfile 中设置时区
ENV TZ=Asia/Shanghai
RUN ln -snf /usr/share/zoneinfo/$TZ /etc/localtime && echo $TZ > /etc/timezone
```

### 2. 容器内的进程是「PID 1」，需要处理信号

```
问题：docker stop 无法优雅关闭 Java 应用
原因：Java 进程在容器内是 PID 1，默认不处理 SIGTERM 信号
```

**解决**：

```dockerfile
# 用 exec 形式启动（信号处理正确）
CMD ["java", "-jar", "app.jar"]   # exec 形式（正确）
# 不要用 shell 形式：CMD java -jar app.jar  ← shell 形式，PID 1 是 shell，不转发信号
```

### 3. 默认以 root 用户运行，安全风险高

```bash
# 问题：容器内是 root，挂载了宿主机目录 → 容器能修改宿主机文件
docker run -v /:/host myapp   # 危险！容器内 root = 宿主机 root

# 解决：在 Dockerfile 中创建非 root 用户
RUN useradd -m myapp
USER myapp   # 后续命令以 myapp 用户执行
CMD ["java", "-jar", "app.jar"]
```

### 4. 容器内修改了 `resolv.conf`，重启后丢失

```
问题：在容器内修改 /etc/resolv.conf（加 DNS 服务器），重启容器后修改丢失
原因：容器每次启动都会重新生成 /etc/resolv.conf（从 Docker daemon 配置继承）
```

**解决**：在 `docker run` 时指定 DNS：

```bash
docker run --dns 8.8.8.8 --dns 114.114.114.114 myapp
```

或者修改 Docker daemon 配置（`/etc/docker/daemon.json`）：

```json
{
  "dns": ["8.8.8.8", "114.114.114.114"]
}
```

---

