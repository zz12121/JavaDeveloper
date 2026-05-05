# Nginx 核心原理

> Nginx 是**高性能 Web 服务器**和**反向代理服务器**，它的核心优势是：事件驱动 + 异步非阻塞 + 极低内存占用，能支撑数万并发连接。

---

## 这个问题为什么存在？

传统 Web 服务器（Apache）采用**多进程/多线程模型**：每个连接分配一个进程/线程，并发高时线程切换开销巨大，内存占用也高。

```
Apache（多进程模型）：
  1 个连接 → 1 个进程
  1 万个并发 → 1 万个进程 → 内存爆炸，性能崩塌

Nginx（事件驱动）：
  1 个 Worker 进程 → 事件循环 → 处理所有连接的请求
  1 万个并发 → 还是那几个 Worker 进程 → 内存几乎不变
```

Nginx 还能同时做：
- **反向代理**：代替后端服务器接收请求，转发给真实后端
- **负载均衡**：把请求分发到多个后端服务器
- **静态资源服务**：直接返回 HTML/CSS/JS/图片，不经过后端
- **SSL 卸载**：在 Nginx 层做 HTTPS 加解密，后端只用 HTTP

---

## 它是怎么解决问题的？

### 一、Nginx 架构原理

```
┌──────────────────────────┐
│     Master 进程            │  ← 管理进程，不处理请求
│  - 读取配置文件           │
│  - 启动/停止 Worker 进程  │
│  - 平滑升级（reload）     │
└──────────┬───────────────┘
           │ fork
           ▼
┌─────────────────────────────────────────────────┐
│          Worker 进程 × N 个                      │
│  - 每个 Worker 都是单线程事件循环              │
│  - 用 epoll（Linux）/ kqueue（Mac）多路复用    │
│  - 一个 Worker 可同时处理数万个连接             │
│  - Worker 数 = CPU 核心数（充分利用多核）       │
│                                                 │
│  事件循环伪代码：                                 │
│  while (true) {                                 │
│      events = epoll_wait(fds, timeout);         │
│      for (event in events) {                    │
│          处理事件（读/写/连接）                  │
│      }                                          │
│  }                                              │
└─────────────────────────────────────────────────┘
```

**为什么一个 Worker 能处理几万个连接？**

> 关键在于**"等"不占资源**。Worker 调用 `epoll_wait()` 等待事件，这期间 Worker 不占 CPU。只有当有事件就绪（有数据可读/可写）时，Worker 才被唤醒处理。这和阻塞 IO（一个连接一个线程，线程一直占着）完全不同。

**Worker 数量怎么设？**

```nginx
# nginx.conf
worker_processes auto;   # 自动设为 CPU 核心数
worker_connections 10240; # 每个 Worker 最大并发连接数
# 总并发能力 = worker_processes × worker_connections
```

### 二、正向代理 vs 反向代理

```
正向代理（VPN、公司内网代理）：
  客户端 → 代理服务器 → 目标服务器
  → 代理"替客户端"访问（客户端知道目标，但目标不知道客户端）
  → 用途：翻墙、内网穿透

反向代理（Nginx 最典型场景）：
  客户端 → Nginx（反向代理） → 后端服务器
  → 代理"替服务器"接收请求（客户端以为 Nginx 就是服务器）
  → 用途：负载均衡、隐藏后端、SSL 卸载、缓存
```

```nginx
# 反向代理基本配置
http {
    upstream backend {
        server 192.168.1.10:8080;
        server 192.168.1.11:8080;
    }

    server {
        listen 80;
        server_name api.example.com;

        location / {
            proxy_pass http://backend;           # 转发到 upstream
            proxy_set_header Host $host;          # 传递原始 Host
            proxy_set_header X-Real-IP $remote_addr;  # 传递真实客户端 IP
        }
    }
}
```

### 三、负载均衡策略

```nginx
upstream backend {
    # 策略1：轮询（默认）
    # server 192.168.1.10:8080;
    # server 192.168.1.11:8080;

    # 策略2：加权轮询
    server 192.168.1.10:8080 weight=5;   # 处理 5/8 的请求
    server 192.168.1.11:8080 weight=3;

    # 策略3：IP 哈希（同一 IP 总打到同一后端，适合有状态 Session）
    # ip_hash;

    # 策略4：最少连接数
    # least_conn;

    # 策略5：一致性哈希（按自定义 key，如 user_id）
    # hash $request_uri consistent;
}
```

**Nginx 负载均衡 vs 客户端负载均衡（Ribbon/Dubbo）**，更多负载均衡策略详见 [[08_分布式与架构/04_微服务核心/负载均衡策略|负载均衡策略]]：

| 维度 | Nginx（服务端负载均衡） | Ribbon/Dubbo（客户端负载均衡） |
|------|------------------------|-------------------------------|
| 负载均衡位置 | 服务端（网关层） | 客户端（应用内） |
| 感知后端状态 | 主动健康检查 | 注册中心推送 |
| 灰度发布 | 支持（按权重/Header） | 支持（更灵活） |
| 性能 | 极高（C 实现） | 中（JVM 开销） |
| 跨语言 | 天然支持 | 需要各语言实现 SDK |

### 四、Location 匹配规则（面试题高频）

```nginx
location = /exact   { ... }  # 精确匹配（优先级最高）
location ^~ /static/ { ... } # 前缀匹配，匹配后不再正则
location ~ \.php$   { ... } # 正则匹配（区分大小写）
location ~* \.jpg$  { ... } # 正则匹配（不区分大小写）
location /           { ... }  # 通用前缀匹配（优先级最低）
```

**匹配优先级**（从高到低）：

```
1. =          精确匹配
2. ^~         前缀匹配（一旦匹配，停止正则）
3. ~ / ~*     正则匹配（按配置文件顺序，第一个匹配即停止）
4. 普通前缀匹配（最长前缀，再进行正则匹配）
5. /           通用匹配（兜底）
```

```nginx
# 实际生产配置示例
server {
    listen 80;

    # 精确匹配首页
    location = / {
        proxy_pass http://frontend;
    }

    # 静态资源，直接由 Nginx 返回（不经过后端）
    location ^~ /static/ {
        root /var/www;
        expires 30d;        # 浏览器缓存 30 天
        access_log off;       # 不记录访问日志（提升性能）
    }

    # API 请求，转发到后端
    location /api/ {
        proxy_pass http://backend;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    }

    # 图片等静态资源
    location ~* \.(jpg|jpeg|png|gif|ico|css|js)$ {
        root /var/www/static;
        expires 7d;
    }
}
```

### 五、HTTPS / SSL 配置

详见 [[10_计算机基础/01_计算机网络/HTTP协议详解|HTTP协议详解]] 中 HTTPS/TLS 的完整原理，以下是 Nginx 侧的配置：

```nginx
server {
    listen 443 ssl http2;            # 开启 HTTP/2
    server_name example.com;

    # 证书配置
    ssl_certificate     /etc/nginx/ssl/example.com.crt;
    ssl_certificate_key /etc/nginx/ssl/example.com.key;

    # TLS 配置（推荐 TLS 1.2+）
    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_ciphers HIGH:!aNULL:!MD5;
    ssl_prefer_server_ciphers on;

    # Session 复用（提升握手性能）
    ssl_session_cache shared:SSL:10m;
    ssl_session_timeout 10m;

    location / {
        proxy_pass http://backend;
    }
}

# HTTP 重定向到 HTTPS
server {
    listen 80;
    server_name example.com;
    return 301 https://$host$request_uri;
}
```

**SSL 卸载**：HTTPS 的加解密在 Nginx 层完成，后端服务器只收到 HTTP 请求，大幅降低后端 CPU 开销。

### 六、Gzip 压缩

```nginx
http {
    gzip on;                    # 开启 gzip
    gzip_vary on;               # 响应头加 Vary: Accept-Encoding
    gzip_min_length 1024;       # 小于 1KB 不压缩（压缩收益太小）
    gzip_types text/plain text/css application/json application/javascript;
    gzip_comp_level 6;          # 压缩级别 1-9，6 是性能和压缩率的平衡
}
```

### 七、限流（防止恶意请求/突发流量）

```nginx
http {
    # 定义限流 zone：以客户端 IP 为 key，10MB 内存，每秒 10 个请求
    limit_req_zone $binary_remote_addr zone=api_limit:10m rate=10r/s;

    server {
        location /api/ {
            # 限流：使用 api_limit zone，突发最多 20 个请求（排队）
            limit_req zone=api_limit burst=20 nodelay;
            proxy_pass http://backend;
        }
    }
}
```

**参数说明**：
- `rate=10r/s`：正常限速，每秒最多 10 个请求
- `burst=20`：允许突发 20 个请求排队（相当于"熔断前的缓冲"）
- `nodelay`：排队请求不延迟处理（立即处理，但超过 burst 的直接拒绝）

### 八、静态资源服务（不经过后端）

```nginx
server {
    location /static/ {
        root /var/www;    # 实际路径：/var/www/static/...
        # 或 alias /var/www/static/;  # 实际路径：/var/www/static/...（推荐用 alias）

        autoindex off;     # 不列出目录（安全）
        expires 30d;       # 浏览器缓存 30 天
        access_log off;     # 不记录访问日志
    }
}
```

### 九、Nginx 常用变量

```nginx
$host              # 请求 Host 头
$remote_addr       # 客户端 IP
$proxy_add_x_forwarded_for  # 追加客户端 IP 到 X-Forwarded-For
$request_uri       # 完整请求 URI（含参数）
$request_method    # GET/POST/...
$status            # HTTP 状态码
$body_bytes_sent   # 响应体大小
$upstream_response_time  # 后端响应时间（排查慢请求很有用）
```

---

## 深入原理

### Nginx vs Apache

| 维度 | Nginx | Apache |
|------|-------|---------|
| 架构 | 事件驱动（异步非阻塞） | 多进程/多线程（阻塞） |
| 并发能力 | 极高（数万并发） | 一般（几百并发就吃力） |
| 内存占用 | 极低 | 高 |
| 静态资源 | 极快 | 一般 |
| 动态请求 | 需转发（FastCGI/PHP-FPM） | 内置模块直接处理 |
| 配置 | 声明式，简洁 | .htaccess 灵活但复杂 |
| 适用场景 | 高并发、反向代理、静态资源 | 传统 PHP 托管 |

### Nginx vs Envoy

| 维度 | Nginx | Envoy |
|------|-------|--------|
| 定位 | Web 服务器 + 反向代理 | 云原生边车代理（Service Mesh） |
| 协议支持 | HTTP/1.1、HTTP/2 | HTTP/1.1、HTTP/2、gRPC、WebSocket |
| 动态配置 | 需 reload（重新加载配置） | 动态 API（无需重启） |
| 可观测性 | 基础（access log） | 极丰富（metrics/trace/access log） |
| 适用场景 | 传统反向代理、静态资源 | K8s Service Mesh、微服务 |

### Nginx vs K8s Ingress

```
K8s Ingress 不是一个软件，是一个 API 规范。
实际实现可以是：
  - Ingress-Nginx（基于 Nginx）
  - Envoy（基于 Envoy）
  - HAProxy（基于 HAProxy）

所以 Nginx 和 Ingress 不是对立关系，Ingress-Nginx 就是 Nginx 的 K8s 封装。
```

---

## 正确使用方式

### 正确用法

**1. 反向代理一定要传真实客户端 IP**

```nginx
# 错误：不传 X-Real-IP，后端拿到的 IP 都是 Nginx 的 IP
location /api/ {
    proxy_pass http://backend;
}

# 正确
location /api/ {
    proxy_pass http://backend;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
}
```

**2. upstream 配置健康检查**

```nginx
upstream backend {
    server 192.168.1.10:8080 max_fails=3 fail_timeout=30s;
    # 30 秒内失败 3 次 → 标记该后端为不可用，30 秒后重试
    server 192.168.1.11:8080 max_fails=3 fail_timeout=30s;
}

# 注意：Nginx 开源版只有被动健康检查（请求失败才标记）
# 主动健康检查需要 Nginx Plus 或 OpenResty
```

**3. 大文件上传要调整 client_max_body_size**

```nginx
# 错误：默认 1MB，上传大文件会 413
# 正确：根据实际需求调整
server {
    client_max_body_size 100m;   # 允许最大 100MB 上传
}
```

**4. 用 alias 而不是 root（静态资源）**

```nginx
# 容易混淆：
location /static/ {
    root /var/www;    # 实际找 /var/www/static/...  ✓
}

location /static/ {
    alias /var/www/static/;  # 实际找 /var/www/static/...  ✓（推荐）
}
# 区别：root 会把 location 路径拼上去，alias 不会
```

### 错误用法及后果

**错误1：proxy_pass 后面带不带 `/` 差别巨大**

```nginx
location /api/ {
    proxy_pass http://backend;        # 请求 /api/users → 转发到 /api/users  ✓
    # proxy_pass http://backend/;    # 请求 /api/users → 转发到 /users     ✗（路径被替换！）
}
```

**错误2：Nginx reload 不是零成本**

```
nginx -s reload  → 启动新 Worker，旧 Worker 处理完当前请求后退出
→ 如果旧 Worker 有慢请求（比如大文件上传），会等到请求完成后才退出
→ 重启期间会有短暂的双倍内存占用
```

**错误3：access.log 不关导致磁盘满**

```nginx
# 静态资源请求不需要记录访问日志
location ^~ /static/ {
    alias /var/www/static/;
    access_log off;   # 一定要关！否则每个 .jpg 请求都写一条日志
}
```

---

## 边界情况和坑

### 坑1：Nginx 返回 413（Request Entity Too Large）

**原因**：`client_max_body_size` 默认值太小（1MB）。

**修复**：在 `nginx.conf` 或对应 `server` / `location` 块里设置：
```nginx
client_max_body_size 100m;
```

### 坑2：Nginx 做 WebSocket 代理失败

**原因**：WebSocket 握手需要特殊的 Header，Nginx 默认不支持。

**修复**：
```nginx
location /ws/ {
    proxy_pass http://backend;
    proxy_http_version 1.1;
    proxy_set_header Upgrade $http_upgrade;
    proxy_set_header Connection "upgrade";
}
```

### 坑3：跨域问题（CORS）

**现象**：前端调用 API 报 `No 'Access-Control-Allow-Origin' header`。

**修复**：在 Nginx 层统一加 CORS Header：
```nginx
location /api/ {
    proxy_pass http://backend;

    # CORS 配置
    add_header Access-Control-Allow-Origin *;
    add_header Access-Control-Allow-Methods GET,POST,PUT,DELETE,OPTIONS;
    add_header Access-Control-Allow-Headers Content-Type,Authorization;

    # OPTIONS 预检请求直接返回 204
    if ($request_method = OPTIONS) {
        return 204;
    }
}
```

### 坑4：Nginx 重启 vs reload

Nginx 高可用部署（keepalived + VIP）详见 [[08_分布式与架构/05_高可用设计/高可用设计|高可用设计]]，这里说明 reload 的四种信号：

```
nginx -s stop    → 立即停止（杀进程）
nginx -s quit    → 优雅停止（处理完当前请求再退出）
nginx -s reload  → 热加载配置（不中断连接，推荐）
nginx -s reopen  → 重新打开日志文件（日志轮转后使用）
```

---

### OpenResty / Lua 扩展（进阶）

Nginx 本身的功能相对固定，但 **OpenResty**（Nginx + LuaJIT）让你可以用 Lua 脚本扩展 Nginx，实现动态逻辑。**Kong**（[[08_分布式与架构/04_微服务核心/API网关设计|API 网关]]）就是基于 OpenResty 构建的。

```nginx
# OpenResty 示例：在 Nginx 层做限流（不用后端）
lua_shared_dict limit_counter 10m;

location /api/ {
    access_by_lua_block {
        local limit_counter = ngx.shared.limit_counter
        local key = ngx.var.binary_remote_addr
        local current = limit_counter:get(key) or 0

        if current > 100 then
            ngx.exit(429)  -- Too Many Requests
        end

        limit_counter:incr(key, 1, 60)  -- 60 秒过期
    }

    proxy_pass http://backend;
}
```

**Kong**（API 网关）就是基于 OpenResty 构建的，提供丰富的插件（认证、限流、日志、监控）。
