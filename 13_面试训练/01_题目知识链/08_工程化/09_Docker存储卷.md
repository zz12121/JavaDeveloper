# 题目：Docker 的数据持久化是怎么做的？ volume 和 bind mount 的区别是什么？

---

## ⚠️ 先盲答

**不要看任何资料，用自己的话回答，写到纸上或心里默念也行。**

用一句话说明：容器的文件系统是持久化的吗？为什么？

---

## 盲答引导

1. 容器删除后，容器层（container layer）的数据还存在吗？
2. `docker run -v /data:/app/data` 和 `docker run -v myvolume:/app/data` 的写法有什么区别？
3. Docker 管理的 volume 和 bind mount，哪个存在宿主机哪个目录下？
4. 如果容器里往 `/app/data` 写入文件，用 bind mount 时宿主机看不到，什么原因？
5. 生产环境中，数据库容器（MySQL/PostgreSQL）的数据怎么持久化？用什么类型的 volume？

---

## 知识链提示

这道题应该让你联想到：

- `[[Docker存储驱动]]` → AUFS / OverlayFS / DeviceMapper（容器层）
- `[[Docker volume]]` → Docker 管理的持久化卷
- `[[Docker bind mount]]` → 挂载宿主机目录
- `[[Docker tmpfs]]` → 内存文件系统，适合存敏感数据
- `[[K8s PV/PVC]]` → K8s 里 volume 和 Docker volume 的关系

---

## 核心追问

1. `docker volume ls` 能看到哪些 volume？无名 volume 和有名 volume 的区别是什么？
2. bind mount 挂载后，宿主机目录不存在会发生什么？
3. `VOLUME /data` 在 Dockerfile 里声明和 `-v /data` 运行时挂载，效果一样吗？
4. 用 bind mount 挂载文件（如 `/etc/nginx/nginx.conf`），Docker 和宿主机谁的文件内容为准？
5. 为什么生产 K8s 里通常用 PVC（PersistentVolumeClaim）而不是直接用 hostPath volume？

---

## 参考要点（盲答后再看）

<details>
<summary>点击展开</summary>

**三种 Docker 存储方式**：

| 类型 | 命令写法 | 存储位置 | 生命周期 |
|------|---------|---------|---------|
| 匿名 volume | `-v /app/data` | `/var/lib/docker/volumes/随机ID/_data` | 随容器删除 |
| 有名 volume | `-v myvol:/app/data` | `/var/lib/docker/volumes/myvol/_data` | 独立于容器，可复用 |
| bind mount | `-v /host/path:/app/data` | 宿主机指定路径 | 宿主机管理 |
| tmpfs | `--tmpfs /app/data` | 内存（不落盘） | 随容器停止删除 |

**Docker 管理的 volume**（推荐持久化用）：
```bash
# 创建 volume
docker volume create mydb-data

# 运行容器时使用
docker run -v mydb-data:/var/lib/mysql mysql:8

# 查看 volume
docker volume inspect mydb-data
# [
#     {
#         "Mountpoint": "/var/lib/docker/volumes/mydb-data/_data"
#     }
# ]
```

**bind mount**（适合挂载配置文件 / 源代码）：
```bash
# 源代码热加载（本地改代码，容器实时生效）
docker run -v $(pwd)/src:/app/src myapp

# 配置文件挂载
docker run -v /etc/nginx/nginx.conf:/etc/nginx/nginx.conf nginx
```

**关键区别**：

```
bind mount：
  - 宿主机目录不存在时，Docker 自动创建空目录
  - 容器和宿主机「共享」目录（同一份内容）
  - 宿主机修改，容器立即可见（反之亦然）
  - 性能好（直接读写宿主机文件系统）

Docker volume：
  - Docker daemon 管理，宿主机用户无法直接访问（/var/lib/docker）
  - 容器内是独立文件系统，性能略低于 bind mount
  - 可跨容器共享、可备份
  - 数据库等需要「容器化存储管理」的场景用这个
```

**生产数据库推荐做法**：
```bash
# 生产 K8s：不用 hostPath，用持久卷（PVC）
# 生产 Docker Compose：使用命名 volume
version: "3"
services:
  mysql:
    image: mysql:8
    volumes:
      - mysql-data:/var/lib/mysql  # Docker volume（可备份、可迁移）
volumes:
  mysql-data:
```

</details>

---

## 下一步

1. 盲答后，对比参考要点，找到卡壳的地方
2. 打开 `[[09_工程化/Docker存储卷]]` 主题文档
3. 在 Obsidian 里建双向链接
4. 在 `[[12_面试训练/每日一题跟踪表]]` 里勾选「今日完成」，打 1~5 分
