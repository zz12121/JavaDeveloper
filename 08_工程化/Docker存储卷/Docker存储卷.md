# Docker存储卷

## 这个问题为什么存在？

> Docker 容器本身是**无状态**的：容器删除，里面的所有数据（文件、日志、数据库文件）全部丢失。问题是：**怎么让数据脱离容器生命周期，持久化存储，同时又能被多个容器共享？**

Docker 的解决思路是**存储卷（Volume）**：把宿主机的目录或专门管理的存储区域挂载到容器内，数据的读写直接发生在宿主机上。

## 它是怎么解决问题的？

### 三种挂载方式对比

```
┌────────────────────────────────────────────────────┐
│                挂载方式对比                    │
├─────────────┬──────────────┬────────────────┤
│  bind mount  │  volume（卷） │  tmpfs（内存）  │
├─────────────┼──────────────┼────────────────┤
│  宿主机路径  │  Docker 管理  │  内存文件系统  │
│  完全由用户  │  统一管理      │  不写磁盘      │
│  控制路径    │  易于迁移      │  最快          │
└─────────────┴──────────────┴────────────────┘
```

#### 1. bind mount（绑定挂载）

```bash
# 把宿主机 /data 挂载到容器 /app/data
docker run -v /host/data:/app/data:rw myapp

# 只读挂载（容器不能写）
docker run -v /host/config:/app/config:ro myapp
```

特点：路径由用户指定，宿主机上**必须存在该路径**（Docker 不会自动创建）。

#### 2. volume（Docker 管理卷）

```bash
# 创建卷
docker volume create mydata

# 挂载卷（容器里用 /app/data）
docker run -v mydata:/app/data myapp

# 匿名卷（Docker 自动生成卷名）
docker run -v /app/data myapp
```

特点：路径由 Docker 管理（默认 `/var/lib/docker/volumes/`），**不用关心宿主机路径**，易于备份和迁移。

#### 3. tmpfs（内存文件系统）

```bash
# 挂载到内存（不写磁盘，重启丢失）
docker run --tmpfs /app/cache:size=100m myapp
```

适合：**敏感临时数据**（如密钥、token），绝不落盘。

### volume 的生命周期

```
创建 volume → 挂载到容器A → 容器A 删除 → volume 还在！
              ↓
         挂载到容器B → 数据完好 ✅
              ↓
         docker volume rm mydata → 数据彻底删除 ❌
```

**容器删了，volume 不删**——这是 volume 和 bind mount 最大的区别（bind mount 的数据在宿主机路径上，和容器无关）。

### Volume Driver：远程存储

Docker 原生只支持本地卷，但可以通过 **volume driver** 挂载远程存储：

```bash
# 使用 SSHFS volume driver 挂载远程机器
docker volume create --driver vieux/sshfs \
  -o sshcmd=user@remote:/remote/path \
  -o password=$(cat pass.txt) \
  myremotevol

docker run -v myremotevol:/app/data myapp
```

常用 driver：
- **vieux/sshfs**：SSHFS 远程挂载
- **Convoy**：支持 NFS、EBS（AWS）
- **Portworx**：企业级分布式存储

## 它和相似方案的本质区别是什么？

| | bind mount | volume | tmpfs | 数据卷容器（已废弃） |
|---|---|---|---|---|
| 路径管理 | 用户指定 | Docker 管理 | 内存 | 另一个容器 |
| 数据共享 | 多个容器挂同一路径 | 多个容器挂同一卷名 | 仅当前容器 | 通过 `--volumes-from` |
| 持久化 | ✅ | ✅ | ❌ | ✅ |
| 性能 | 中 | 中 | 极高（内存） | 中 |
| 备份迁移 | 手动（路径依赖） | 容易（`docker volume inspect`） | 不适用 | 麻烦 |

### K8s PV/PVC：云原生存储抽象

Docker volume 是单机概念，K8s 把它抽象成 **PV（Persistent Volume）** 和 **PVC（Persistent Volume Claim）**：

```
Pod → PVC（我要 10GB 存储）→ PV（实际存储资源）
                   ↑
            解耦：Pod 不关心存储后端是 NFS / EBS / Ceph
```

PVC 让**应用和存储后端解耦**，迁移到云上时不用改任何代码。

## 正确使用方式

### Docker Compose 配置 volume

```yaml
version: '3'
services:
  mysql:
    image: mysql:8.0
    volumes:
      - mysql-data:/var/lib/mysql       # 命名卷（推荐）
      - ./config:/etc/mysql/conf.d  # bind mount（配置文件）
      - /tmp/cache:/app/cache:ro    # 只读 bind mount

volumes:
  mysql-data:  # 声明命名卷，Docker 管理
```

### 备份 volume 数据

```bash
# 用临时容器备份 volume
docker run --rm \
  -v mydata:/source:ro \
  -v $(pwd):/backup \
  alpine tar czf /backup/mydata.tar.gz -C /source .

# 恢复
docker run --rm \
  -v mydata:/target \
  -v $(pwd):/backup \
  alpine tar xzf /backup/mydata.tar.gz -C /target
```

## 边界情况和坑

### 挂载路径的覆盖问题

```bash
# 镜像里 /app/data 本来有文件
# 挂载 volume 后，/app/data 被 volume 的内容**覆盖**！
docker run -v mydata:/app/data myapp
```

**解决**：用 `volume-nobind`（Docker 17.12+）或在 Dockerfile 里用 `VOLUME` 指令预 populate。

### 文件权限（UID/GID 不匹配）

```bash
# 容器内以 UID=1000 写文件
# 宿主机上文件属主是 1000（可能不存在的用户）
ls -n /host/data
# -rw-r--r-- 1 1000 1000 0 Jan 1 00:00 file.txt
```

解决：
```bash
# 运行容器时指定 UID
docker run --user 1000:1000 -v /data:/app/data myapp

# 或者在 entrypoint 脚本里 chown
```

### Windows 下 bind mount 路径格式

```bash
# ❌ 错误
docker run -v C:\data:/app/data myapp

# ✅ 正确（Git Bash / WSL）
docker run -v //c/data:/app/data myapp
```

Windows 的盘符需要写成 `//c/` 格式（Git Bash）或 `c:/` 格式（PowerShell）。

### 多个容器同时写同一个 volume

```
容器A 写 file.txt
容器B 同时写 file.txt
→ 文件内容损坏！
```

Docker volume **不提供文件锁**，并发写需要应用层自己处理（如用数据库或分布式锁）。

## 我的理解

Docker 存储的核心矛盾是**无状态（容器）vs 有状态（数据）**。

三种挂载方式本质是在**性能、持久化、易用性**之间 trade-off：
- **bind mount**：最直接，但路径依赖宿主机
- **volume**：最推荐，Docker 统一管理，易于迁移
- **tmpfs**：最快，但不持久化

面试追问最高频：**K8s PV/PVC 和 Docker volume 的关系**——Docker volume 是单机存储抽象，K8s PV/PVC 是集群级存储抽象，底层可以对接 Docker volume、云盘、分布式存储等。
