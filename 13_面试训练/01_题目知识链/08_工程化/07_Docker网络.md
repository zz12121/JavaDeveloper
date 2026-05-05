# 题目：Docker 有哪几种网络模式？ bridge、host、overlay 分别是干什么的？

---

## ⚠️ 先盲答

**不要看任何资料，用自己的话回答，写到纸上或心里默念也行。**

说出至少三种 Docker 网络模式的名称和适用场景。

---

## 盲答引导

1. bridge 网络是什么？容器和宿主机怎么通信？容器之间怎么通信？
2. host 网络是什么？什么时候用？和 bridge 比有什么缺点？
3. overlay 网络是什么？为什么它是 Docker Swarm / K8s 里用的网络模式？
4. 容器里 `localhost` 指什么？容器内的 `8080` 端口和宿主机的 `8080` 有什么关系？
5. 两个容器在同一个 bridge 网络里，怎么知道对方的 IP？DNS 是怎么工作的？

---

## 知识链提示

这道题应该让你联想到：

- `Docker bridge网络` → docker0 网桥，容器和宿主机通信
- `Docker host网络` → 容器直接用宿主机网络栈
- `Docker overlay网络` → 跨主机容器通信，VXLAN 封装
- `容器间通信` → Docker DNS，自动服务发现
- `[[09_工程化/04_Kubernetes/网络模型]]` → Pod 网络 vs Service 网络 vs ClusterIP

---

## 核心追问

1. 容器内访问外网（`curl baidu.com`）的完整路径是什么？NAT 转换发生在哪一步？
2. `docker network create --driver bridge mynet`，创建的网桥在哪里可以查到？（`ip addr` / `brctl show`）
3. 在 bridge 网络里，容器重启后 IP 会变吗？怎么保证容器间通信的 IP 不变？
4. overlay 网络的 VXLAN 封装是什么？为什么要用 VXLAN 而不是直接路由？
5. `network_mode: "none"` 的容器能联网吗？这种模式有什么用？

---

## 参考要点（盲答后再看）


**Docker 网络模式**：

| 模式 | 网络命名空间 | 宿主机网络 | 适用场景 |
|------|------------|-----------|---------|
| bridge（默认） | 独立 | 隔离，通过 docker0 NAT | 单机容器间通信 |
| host | 共用 | 共用 | 性能敏感（网络零开销） |
| overlay | 跨主机 | - | Docker Swarm 多主机 |
| macvlan | 独立 | 直接接入物理网络 | 需要直接暴露 IP |
| none | 独立 | 无网络 | 安全隔离测试 |

**bridge 网络通信路径**：

```
容器A（172.17.0.2）访问 容器B（172.17.0.3）：
  → 查路由表：在同一子网（172.17.0.0/16）
  → 发到 docker0 网桥（172.17.0.1）
  → docker0 广播/转发 → 到达容器B

容器A（172.17.0.2）访问外网：
  → docker0 做 SNAT（源地址转换）
  → 发到宿主机 eth0 → 访问外网
  → 回来时做 DNAT，返回容器A
```

**Docker DNS（bridge 自定义网络）**：
```bash
docker network create mynet
docker run --network mynet --name db redis
docker run --network mynet --name web nginx
# web 容器里：ping db 能通！
# Docker 内置 DNS，自动解析容器名到 IP
```

**overlay 网络原理**：
```
跨两台宿主机：
宿主机A（容器CA）→ VETH 对 → docker_gwbridge → vxlan0（VXLAN隧道）
                                                          ↓
宿主机B（容器CB）← VETH 对 ← docker_gwbridge ← vxlan0（VXLAN隧道）

数据在宿主机之间用 VXLAN 封装（UDP 4789 端口），
到达目标宿主机后解封装，送入对应容器的 VETH 对。
```

**host 模式的坑**：
```bash
# 容器里跑 nginx，监听 80 端口
docker run --network host nginx
# 容器直接用宿主机的 80 端口
# 如果宿主机已经有服务占 80 → 冲突！
# 如果跑多个容器 → 端口冲突，无法启动第二个
```


---

## 下一步

1. 盲答后，对比参考要点，找到卡壳的地方
2. 打开 `[[13_面试训练/01_题目知识链/08_工程化/07_Docker网络]]` 主题文档
3. 在 Obsidian 里建双向链接
4. 在 `[[13_面试训练/03_每日一题/每日一题跟踪表]]` 里勾选「今日完成」，打 1~5 分
