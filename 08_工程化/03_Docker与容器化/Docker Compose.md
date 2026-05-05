# Docker Compose

> 单机多容器编排工具。不需要写复杂的 `docker run` 命令，一个 YAML 文件搞定所有服务的启动、网络、存储。

---

## 这个问题为什么存在？

不用 Compose 时，启动多容器应用的痛点是：

```
场景：启动一个 Web 应用 + Redis + MySQL

传统方式：
  1. 启动 MySQL：
     docker run -d --name mysql \
       -v mysql-data:/var/lib/mysql \
       -e MYSQL_ROOT_PASSWORD=secret \
       -p 3306:3306 \
       mysql:8.0

  2. 启动 Redis：
     docker run -d --name redis \
       -v redis-data:/data \
       -p 6379:6379 \
       redis:7

  3. 启动 Web 应用（需要连接 mysql 和 redis）：
     docker run -d --name web \
       --link mysql:mysql \
       --link redis:redis \
       -p 8080:8080 \
       my-web-app

  问题：
  - 命令太长，记不住
  - 启动顺序要手动控制（先启动 mysql，再启动 web）
  - 网络配置复杂（--link 已废弃）
  - 要停止/删除所有容器，得手动一个个操作
  - 新人入职，不知道要启动哪些容器、什么顺序
```

**Docker Compose 解决的核心问题**：

1. **声明式配置**：一个 YAML 文件定义所有服务
2. **一键启停**：`docker compose up` / `docker compose down`
3. **网络自动打通**：所有服务在同一个网络中，通过服务名互相访问
4. **依赖控制**：用 `depends_on` 控制启动顺序

---

## 它是怎么解决问题的？

### 核心概念：`docker-compose.yml`

```yaml
version: '3.8'

services:
  mysql:
    image: mysql:8.0
    environment:
      MYSQL_ROOT_PASSWORD: secret
      MYSQL_DATABASE: mydb
    volumes:
      - mysql-data:/var/lib/mysql
    ports:
      - "3306:3306"

  redis:
    image: redis:7
    volumes:
      - redis-data:/data
    ports:
      - "6379:6379"

  web:
    build: .          # 用当前目录的 Dockerfile 构建镜像
    ports:
      - "8080:8080"
    depends_on:
      - mysql
      - redis
    environment:
      - SPRING_DATASOURCE_URL=jdbc:mysql://mysql:3306/mydb

volumes:
  mysql-data:
  redis-data:
```

### 启动流程

```bash
# 启动所有服务（前台运行，日志直接输出）
docker compose up

# 后台运行
docker compose up -d

# 查看运行状态
docker compose ps

# 查看某个服务的日志
docker compose logs web

# 停止并删除所有容器
docker compose down

# 停止并删除容器 + 删除 volumes（危险！）
docker compose down -v
```

### 网络自动打通

```
Docker Compose 自动创建一个网络（默认名称：<项目名>_default）
→ 所有 services 都加入这个网络
→ 容器之间可以用「服务名」互相访问：

  web 容器中访问 mysql：
    jdbc:mysql://mysql:3306/mydb   ← 用服务名 mysql，不用 IP

  web 容器中访问 redis：
    redis://redis:6379               ← 用服务名 redis
```

**这和 `--link` 的区别**：

| 方式 | 服务发现 | 网络隔离 |
|------|---------|---------|
| `--link`（已废弃） | 写死在 `/etc/hosts` | 容器间完全打通 |
| Docker Compose 网络 | 内网 DNS 解析 | 同一 Compose 内打通，外部隔离 |

### 依赖控制（`depends_on`）

```yaml
services:
  db:
    image: mysql:8.0

  web:
    build: .
    depends_on:
      - db       # web 会在 db 启动后再启动
```

**注意**：`depends_on` 只控制**启动顺序**，不保证**「db 完全就绪」**。

```
问题：
  web 启动后，db 可能还在初始化（MySQL 第一次启动要 10+ 秒）
  → web 连接 db 失败

解决：在 web 的启动脚本中加「等待逻辑」：
  until mysqladmin ping -h mysql --silent; do
    sleep 1
  done
```

---

## 它和相似方案的本质区别是什么？

### Docker Compose vs `docker run` 脚本

| 维度 | Docker Compose | `docker run` 脚本 |
|------|----------------|-------------|
| 配置方式 | 声明式 YAML | 命令式 Shell 脚本 |
| 可读性 | 高（一眼看懂所有服务） | 低（长命令，容易出错） |
| 可维护性 | 高（版本控制 YAML） | 低（脚本散落各处） |
| 网络配置 | 自动（同一网络） | 手动（--link 或自定义网络） |
| 适用场景 | 开发环境、测试环境 | 简单场景、临时测试 |

### Docker Compose vs Kubernetes

| 维度 | Docker Compose | Kubernetes |
|------|----------------|-------------|
| 复杂度 | 低（单机） | 高（集群） |
| 高可用 | 不支持 | 支持（多副本、自动重启） |
| 扩缩容 | 手动（改 `replicas` 然后重启） | 自动（`kubectl scale`） |
| 适用场景 | 本地开发、测试环境 | 生产环境 |
| 学习曲线 | 低（半天学会） | 高（几周才能熟练） |

**一般用法**：

- **本地开发**：用 Docker Compose 启动依赖服务（MySQL、Redis、Kafka…）
- **生产部署**：用 Kubernetes（或 Docker Swarm）

---

## 正确使用方式

### 1. 用 `.env` 文件管理环境变量

```yaml
# docker-compose.yml
services:
  web:
    image: my-app
    environment:
      - DB_URL=${DB_URL}
      - DB_PASSWORD=${DB_PASSWORD}
```

```
# .env 文件（和 docker-compose.yml 同目录）
DB_URL=jdbc:mysql://mysql:3306/mydb
DB_PASSWORD=secret

# 启动时会自动加载 .env 文件
docker compose up -d
```

**好处**：敏感信息不进 Git（记得把 `.env` 加入 `.gitignore`）。

### 2. 用 `profiles` 分组服务（Compose v2+）

```yaml
services:
  web:
    image: my-app

  redis:
    image: redis:7
    profiles: ["cache"]      # 只有指定 profile 时才启动

  mysql:
    image: mysql:8.0
    profiles: ["db"]
```

```bash
# 只启动 web（不启动 redis 和 mysql）
docker compose up web -d

# 启动 web + redis（指定 profile）
docker compose --profile cache up -d
```

### 3. 用 `healthcheck` 控制启动顺序

```yaml
services:
  mysql:
    image: mysql:8.0
    healthcheck:
      test: ["CMD", "mysqladmin", "ping", "-h", "localhost"]
      interval: 5s
      timeout: 3s
      retries: 5

  web:
    build: .
    depends_on:
      mysql:
        condition: service_healthy   # 等 mysql 健康检查通过后才启动
```

**效果**：web 不会在 mysql 还没就绪时就启动。

### 4. 本地开发时用 `volume` 挂载代码

```yaml
services:
  web:
    build: .
    volumes:
      - ./src:/app/src       # 挂载源码
      - ./target:/app/target  # 挂载编译产物
    command: mvn spring-boot:run
```

**效果**：本地改代码，容器内立即生效（不用重新构建镜像）。

---

## 边界情况和坑

### 1. `depends_on` 不保证「服务就绪」

见上文「网络自动打通」章节。

**解决**：用 `healthcheck` + `condition: service_healthy`。

### 2. Windows 下路径挂载失败

```
报错：
  Error response from daemon: invalid mount config for type "bind": invalid mount path
```

**原因**：Windows 路径格式问题。

**解决**：

```yaml
# 用 Unix 风格路径（Git Bash）或绝对路径
volumes:
  - /c/Users/zhang/project/src:/app/src   # Git Bash 风格
  # 或者
  - C:\Users\zhang\project\src:/app/src     # Windows 风格（需要 Docker Desktop 配置共享盘符）
```

### 3. 端口冲突

```
报错：
  Error starting userland proxy: listen tcp 0.0.0.0:3306: bind: address already in use
```

**原因**：宿主机已经有程序占用了 3306 端口（可能是本地安装的 MySQL）。

**解决**：

```yaml
# 改宿主机端口（容器内端口不变）
ports:
  - "13306:3306"    # 宿主机用 13306，容器内还是 3306
```

### 4. `docker compose down` 不删除 volume

```bash
# 默认：down 只会停删容器，volume 还在
docker compose down

# 要删除 volume：
docker compose down -v

# 要删除 orbit 的容器和镜像：
docker compose down --rmi all
```

**坑**：`-v` 会删除**所有未使用的 volume**，不只是当前 Compose 项目用的！

### 5. 服务名不能用 `_`（下划线）

```yaml
services:
  my_sql:     # ❌ 不推荐，DNS 解析可能有问题
    image: mysql:8.0

  my-sql:     # ✅ 推荐用连字符
    image: mysql:8.0
```

---

