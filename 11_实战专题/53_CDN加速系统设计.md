# CDN加速系统设计

> CDN核心：DNS智能调度 + 边缘缓存 + 回源优化 + DDoS防护。

---

## CDN系统架构

```
用户请求
   │
   ▼
┌─────────┐  DNS解析 ┌─────────┐  调度 ┌─────────┐
│  用户终端 │ ─────→ │  DNS    │ ────→  │  GSLB   │
│  App/Web │        │  Local  │        │  全局负载 │
└─────────┘        └─────────┘        └────┬────┘
                                           │
                     ┌─────────────────────┼─────────────────────┐
                     │                     │                     │
                     ▼                     ▼                     ▼
              ┌───────────┐         ┌───────────┐         ┌───────────┐
              │  边缘节点A  │         │  边缘节点B  │         │  边缘节点C  │
              │  北京      │         │  上海      │         │  广州      │
              │  缓存+WAF  │         │  缓存+限流  │         │  缓存+WAF  │
              └─────┬─────┘         └─────┬─────┘         └─────┬─────┘
                    │                     │                     │
                    └─────────────────────┼─────────────────────┘
                                          ▼
                                   ┌───────────┐
                                   │  源站      │
                                   │  Origin    │
                                   └───────────┘
```

---

## 场景 A：DNS智能调度（GSLB）

### 现象

```
用户被分配到远距离CDN节点，访问延迟高（>200ms）
某个节点过载，其他节点空闲，负载不均
DNS缓存导致用户长时间无法切换到最优节点
```

### 根因

```
只用简单DNS轮询，未考虑用户地理位置和网络状况
无健康检查机制，故障节点仍接收流量
DNS TTL过长，调度响应慢
```

### 解决方案

```
GSLB（全局服务器负载均衡）调度策略：
1. 基于地理位置：用户IP归属地 → 分配最近边缘节点
2. 基于网络延迟：实时探测各节点延迟 → 选最低延迟节点
3. 基于负载：各节点CPU/带宽/连接数 → 负载低的优先分配
4. 基于运营商：电信用户→电信节点，移动用户→移动节点（跨网加速）
```

```nginx
# Nginx GSLB配置示例（基于GeoIP和健康检查）
upstream cdn_cluster {
    zone cdn_backend 64k;

    # 北京节点
    server bj-cdn.example.com:80 
        weight=5 max_fails=3 fail_timeout=30s;
    
    # 上海节点
    server sh-cdn.example.com:80 
        weight=5 max_fails=3 fail_timeout=30s;
    
    # 广州节点  
    server gz-cdn.example.com:80 
        weight=5 max_fails=3 fail_timeout=30s;
}

# 基于GeoIP的地理路由
geo $cdn_node {
    default                sh;
    110.0.0.0/8            bj;  # 北京地区
    116.0.0.0/8            bj;
    121.0.0.0/8            sh;  # 上海地区
    183.0.0.0/8            gz;  # 广州地区
}

map $cdn_node $cdn_backend {
    bj   "bj-cdn.example.com";
    sh   "sh-cdn.example.com";
    gz   "gz-cdn.example.com";
}
```

**GSLB关键**：
- TTL设为60~300秒，平衡缓存命中率和调度灵活性
- 结合EDNS Client Subnet传递客户端真实IP给权威DNS
- 定期健康检查，自动剔除故障节点

---

## 场景 B：边缘缓存策略

### 现象

```
静态资源命中率低，大量请求回源
动态API被错误缓存，用户看到旧数据
缓存过期后瞬间大量回源，源站被打垮
```

### 根因

```
缓存策略一刀切，未区分资源类型
Cache-Control头设置不合理
无缓存预热机制，冷启动时全量回源
```

### 解决方案

```
分层缓存策略：

1. 静态资源层（TTL长）
   - 图片/JS/CSS/字体：Cache-Control: max-age=31536000（1年）
   - 版本化URL：/static/v2.1.0/app.js （URL变化自动失效）

2. 动态页面层（TTL短）
   - 商品详情页：max-age=60（1分钟）
   - 首页推荐：max-age=10（10秒）

3. API数据层（协商缓存）
   - ETag/Last-Modified做304协商缓存
   - 不适合强制缓存的场景
```

```nginx
# CDN边缘缓存策略配置
server {
    listen 80;
    server_name cdn.example.com;

    # 1. 静态资源：强缓存1年（URL带版本号）
    location ~* \.(js|css|png|jpg|gif|ico|woff|woff2)$ {
        add_header Cache-Control "public, max-age=31536000, immutable";
        add_header X-Cache-Status "HIT-STATIC";
        
        # 缓存到本地磁盘
        proxy_cache_path /var/cache/nginx/static levels=2:2 
                       keys_zone=static_cache:100m max_size=10g inactive=365d;
        proxy_cache static_cache;
        proxy_cache_valid 200 365d;  # 200状态码缓存1年
    }

    # 2. 动态页面：短时间缓存
    location /api/product/ {
        add_header Cache-Control "public, s-maxage=60, stale-while-revalidate=300";
        proxy_pass http://origin;
        
        # 允许用过期内容（stale）同时异步回源更新
        proxy_cache_use_stale error timeout updating http_500 http_502;
    }

    # 3. API接口：不做强制缓存（用协商缓存）
    location /api/order/ {
        add_header Cache-Control "no-store, must-revalidate";
        proxy_set_header Host $host;
        proxy_pass http://origin;
    }
}
```

**缓存策略关键**：
- 静态资源用版本化URL+长期缓存，彻底解决缓存失效问题
- `stale-while-revalidate`允许返回过期内容同时后台刷新，避免回源雪崩
- API接口用`no-store`+ETag协商缓存，保证数据新鲜度

---

## 场景 C：回源优化（Range请求/预取）

### 现象

```
大文件下载慢，用户等很久才能开始播放视频
热点文件首次访问时全部回源，源站压力突增
Range请求处理不当，每次都回源完整文件
```

### 根因

```
未支持Range请求（分片请求），无法断点续传/边下边播
无缓存预热机制，冷启动时流量集中打向源站
回源带宽有限，无法应对突发流量
```

### 解决方案

```nginx
# 回源Range请求支持（视频/大文件场景）
location ~* \.(mp4|flv|m3u8|zip)$ {
    # 支持Range请求（分片获取，实现边下边播）
    proxy_set_header Range $http_range;
    proxy_set_header If-Range $http_if_range;
    
    # 开启Slice模块（Nginx 1.9.8+），将大文件切分为小片独立缓存
    slice 1m;  # 每1MB为一片
    
    # 每片独立缓存，避免重复回源
    proxy_cache_key $uri$is_args$args$slice_range;
    proxy_cache_valid 200 7d;  # 缓存7天
    
    # 回源超时设置
    proxy_connect_timeout 5s;
    proxy_read_timeout 120s;  # 大文件允许更长读取时间
    proxy_send_timeout 120s;
}
```

```bash
#!/bin/bash
# 缓存预取脚本（活动前提前预热热门资源）

# 从日志分析TOP 100热点URL
HOT_URLS=$(tail -100000 /var/log/nginx/access.log | \
    awk '{print $7}' | sort | uniq -c | sort -rn | head -100 | awk '{print $2}')

# 对每个热点URL执行预取（触发CDN回源并缓存）
for url in $HOT_URLS; do
    echo "预热: $url"
    curl -s -o /dev/null -w "%{http_code}" \
        -H "X-Purge-Key: my-secret-key" \
        "$url" &
done
wait
echo "预热完成"
```

**回源优化关键**：
- 大文件必须支持`Range`请求+`Slice`切片缓存，避免重复回源
- 活动前通过日志分析热点URL，提前预取缓存
- 回源带宽预留20%余量，防止突发流量打满

---

## 场景 D：DDoS防护（WAF/限流）

### 现象

```
网站被CC攻击，QPS从1万飙升到50万
正常用户访问缓慢或无法打开页面
CDN节点带宽被打满，费用激增
```

### 根因

```
无接入层防护，所有请求直达后端
无频率限制，恶意脚本可无限刷接口
无Bot识别，爬虫和正常请求无法区分
```

### 解决方案

```
多层DDoS防护体系：

L1：网络层防护（ISP清洗中心）
     → 流量超过阈值时自动牵引至清洗中心
     → 过滤SYN Flood/UDP Flood/ICMP Flood

L2：CDN边缘层防护（WAF + 限流）
     → WAF规则过滤SQL注入/XSS/CSRF攻击
     → 单IP频率限制：100 req/min
     → 单User-Agent限制：500 req/min

L3：应用层防护（验证码/人机验证）
     > 高频请求弹出图形验证码
     > 可疑行为要求滑块验证
```

```nginx
# WAF + 限流配置
# 1. IP频率限制（使用limit_req_zone）
limit_req_zone $binary_remote_addr zone=ip_limit:10m rate=10r/s;
limit_req_zone $binary_remote_addr zone=api_ip_limit:10m rate=5r/s;

# 2. User-Agent频率限制（防简单爬虫）
map $http_user_agent $is_bot {
    default 0;
    ~*bot 1;
    ~*spider 1;
    ~*crawler 1;
}

# 3. WAF安全规则
server {
    # SQL注入检测
    if ($query_string ~* "(union.*select|insert.*into)") {
        return 403;  # 直接拦截
    }
    
    # XSS检测
    if ($args ~* "<script>|<iframe>") {
        return 403;
    }

    # API接口严格限流
    location /api/ {
        limit_req zone=api_ip_limit burst=10 nodelay;
        limit_req_status 429;  # 返回429 Too Many Requests
        
        # Bot直接拦截
        if ($is_bot) {
            return 403;
        }
        
        proxy_pass http://origin;
    }
    
    # 静态资源宽松限流
    location /static/ {
        limit_req zone=ip_limit burst=20 nodelay;
        try_files $uri =404;
    }
}
```

**DDoS防护关键**：
- 多层防御：网络清洗→CDN WAF→应用层验证
- IP+UA双维度限流，兼顾安全和体验
- 关键接口加验证码兜底，机器流量无法绕过

---

## 涉及知识点

| 概念 | 所属域 | 关键点 |
|------|--------|--------|
| GSLB全局负载均衡 | 07_分布式与架构/03_高并发 | GeoIP/健康检查/EDNS |
| CDN缓存策略 | 07_分布式与架构/06_可观测性 | Cache-Control/s-maxage/stale |
| Range/Slice回源 | 06_中间件/04_Docker/Nginx | 分片缓存/断点续传 |
| WAF/DDoS防护 | 07_分布式与架构/03_高并发 | 频率限制/Bot识别/多层防护 |

---

## 排查 Checklist

```
□ 用GSLB调度了吗？ → GeoIP+健康检查+运营商路由
□ 缓存分层合理吗？ → 静态1年/动态60s/API no-store
□ 支持Range请求吗？ → 大文件Slice切片缓存
□ 有缓存预热吗？ → 活动前预取热点URL
□ DDoS防护有几层？ → 网络+CDN WAF+应用层验证
□ 限流粒度够细吗？ → IP+UA双维度限流
□ 缓存命中率监控了吗？ → HIT率≥95%才算合格
□ 回源带宽有冗余吗？ → 预留20%应对突发流量
```

---

## 我的实战笔记

-（待补充，项目中的真实经历）
