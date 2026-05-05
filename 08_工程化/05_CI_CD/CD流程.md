# CD流程

> CD（Continuous Deployment，持续部署）不是「自动化脚本跑一下」。它是**从代码到生产的全自动流水线**，保证「提交后 10 分钟内，新版本在生产环境跑起来」。

---

## 这个问题为什么存在？

没有 CD 的团队是什么样的？

```
场景 A：手动发布
  登录跳板机 → 拉代码 → mvn package → 关服务 → 替换 jar → 启动
  → 全程 30 分钟，手抖一下就出错

场景 B：发布全停机
  关服务 → 更新 → 重启
  → 用户看到 502，体验极差

场景 C：发布后没验证
  发布完就下班了
  → 半夜服务挂了，用户投诉才发现

场景 D：回滚慢
  新版本有 bug
  → 重新打包、重新发布，要 30 分钟
  → 用户崩了 30 分钟
```

**CD 要解决的核心问题**：

1. **全自动**：提交后不需要人工干预
2. **零停机**：滚动更新，用户无感知
3. **快速验证**：健康检查 + 自动化冒烟测试
4. **秒级回滚**：出问题立即回退到上一个稳定版本

---

## 它是怎么解决问题的？

### CD 的基本流程（以 Kubernetes 为例）

```
开发者 push → Git 仓库
      ↓
CI 通过（编译、测试、扫描都通过）
      ↓
构建镜像（docker build）
      ↓
推送到镜像仓库（docker push）
      ↓
更新 K8s Deployment 镜像版本（kubectl set image）
      ↓
K8s 滚动更新（Rolling Update）
      ↓
健康检查（Readiness Probe）
      ↓
冒烟测试（Smoke Test）
      ↓
通知（Slack / 钉钉 / 企微）
```

### GitHub Actions 实现 CD（示例）

```yaml
# .github/workflows/cd.yml
name: CD

on:
  push:
    branches: [main]       # 只有 main 分支 push 才触发 CD

jobs:
  deploy:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3

      - name: Login to Docker Hub
        uses: docker/login-action@v2
        with:
          username: ${{ secrets.DOCKER_HUB_USERNAME }}
          password: ${{ secrets.DOCKER_HUB_TOKEN }}

      - name: Build and push image
        run: |
          docker build -t my-app:${{ github.sha }} .
          docker push my-app:${{ github.sha }}

      - name: Deploy to K8s
        uses: azure/k8s-deploy@v4
        with:
          namespace: production
          manifests: |
            k8s/deployment.yml
            k8s/service.yml
          images: my-app:${{ github.sha }}
```

### 滚动更新（零停机发布）

```yaml
# k8s/deployment.yml
apiVersion: apps/v1
kind: Deployment
spec:
  replicas: 6
  strategy:
    type: RollingUpdate
    rollingUpdate:
      maxSurge: 2          # 最多多 2 个 Pod
      maxUnavailable: 1   # 最少保持 5 个 Pod 在线
```

**效果**：更新过程中始终有 Pod 在服务，用户无感知。

### 自动化回滚机制

```yaml
# GitLab CI 示例
deploy_job:
  stage: deploy
  script:
    - kubectl set image deployment/my-app my-app=my-app:$CI_COMMIT_SHA
    - kubectl rollout status deployment/my-app --timeout=60s
    - ./smoke-test.sh          # 冒烟测试
  after_script:
    - |
      if [ "$CI_JOB_STATUS" == "failed" ]; then
        kubectl rollout undo deployment/my-app   # 自动回滚
      fi
```

---

## 它和相似方案的本质区别是什么？

### CD（持续部署） vs 持续交付（Continuous Delivery）

| 维度 | 持续交付 | 持续部署 |
|------|-----------|-----------|
| 触发方式 | 手动触发（一键部署） | 自动触发（push 就部署） |
| 人工审批 | 需要 | 不需要 |
| 发布频率 | 较低（按批次） | 极高（每天多次） |
| 风险 | 低 | 高（需要完善的自动化测试 + 监控） |

**选择建议**：
- 生产环境 → 持续交付（需要人工审批）
- 测试/预发环境 → 持续部署（全自动）

### GitLab CI vs Argo CD（GitOps）

| 维度 | GitLab CI / GitHub Actions | Argo CD |
|------|--------------------------|---------|
| 模式 | Push 模式（CI 推送变更到 K8s） | Pull 模式（Argo CD 监听 Git 变更） |
| GitOps | 不是（以 CI 为中心） | 是（以 Git 为唯一真理源） |
| 回滚 | CI 脚本控制 | git revert + Argo CD 自动同步 |
| 适合场景 | 简单场景 | 复杂场景、多集群管理 |

**GitOps 的核心思想**：Git 仓库的 YAML 就是集群的期望状态，Argo CD 保证「实际状态 = 期望状态」。

---

## 正确使用方式

### 1. 用蓝绿部署实现零停机

```
蓝绿部署：
  蓝色环境（当前生产）：跑 v1.0
  绿色环境（新版本）：部署 v1.1

步骤：
  1. 在绿色环境部署 v1.1
  2. 验证绿色环境（冒烟测试）
  3. 切换负载均衡器到绿色环境
  4. 蓝色环境保留（用于快速回滚）
```

**实现方式**（以 K8s Service 为例）：

```yaml
# 先创建 v1.1 的 Deployment（绿色）
apiVersion: apps/v1
kind: Deployment
metadata:
  name: my-app-green

# 切换 Service 到绿色环境
apiVersion: v1
kind: Service
spec:
  selector:
    app: my-app
    version: green   # 从 blue 改成 green
```

### 2. 用金丝雀发布控制风险

```
金丝雀发布：
  新版本先给 5% 用户用
  → 监控错误率、延迟
  → 没问题再逐步扩大到 100%
```

**Istio 实现金丝雀**：

```yaml
apiVersion: networking.istio.io/v1beta1
kind: VirtualService
metadata:
  name: my-app
spec:
  hosts:
    - my-app.com
  http:
    - route:
        - destination:
            host: my-app
            subset: v1.0
          weight: 95          # 95% 流量到 v1.0
        - destination:
            host: my-app
            subset: v1.1
          weight: 5           # 5% 流量到 v1.1
```

### 3. 用健康检查保证发布质量

```yaml
# readinessProbe（就绪探针）
readinessProbe:
  httpGet:
    path: /actuator/health
    port: 8080
  initialDelaySeconds: 10
  periodSeconds: 5

# livenessProbe（存活探针）
livenessProbe:
  httpGet:
    path: /actuator/health
    port: 8080
  initialDelaySeconds: 30
  periodSeconds: 10
```

**效果**：K8s 只把流量转发到 `readinessProbe` 通过的 Pod。

---

## 边界情况和坑

### 1. 滚动更新时旧 Pod 立即被删

```
现象：
  K8s 滚动更新
  → 新 Pod 还没就绪，旧 Pod 就被删了
  → 服务中断
```

**原因**：`maxUnavailable` 设置过大。

**解决**：

```yaml
strategy:
  rollingUpdate:
    maxSurge: 1
    maxUnavailable: 0   # 保证始终有 Pod 在服务
```

### 2. CD 流水线中敏感信息管理

```
错误做法：
  在 CI 配置文件中硬编码密码
  → 泄露到 Git 仓库
```

**正确做法**：

```yaml
# GitHub Actions：用 Secrets
- name: Deploy
  env:
    DB_PASSWORD: ${{ secrets.DB_PASSWORD }}   # 从 Secrets 读取

# GitLab CI：用 CI/CD Variables
deploy:
  script:
    - echo $DB_PASSWORD   # 从 Variables 读取
```

### 3. 镜像标签用 `latest` 导致不可追溯

```
错误做法：
  docker build -t my-app:latest .
  → 回滚时不知道上一个版本是什么
```

**正确做法**：

```yaml
# 用 Git SHA 或版本号作为标签
- name: Build image
  run: |
    docker build -t my-app:${{ github.sha }} .
    docker push my-app:${{ github.sha }}
```

### 4. CD 失败但没告警

```
场景：
  CD 流水线失败
  → 开发者没收到通知
  → 生产环境一直没更新
```

**解决**：配置流水线失败通知。

```yaml
# GitHub Actions 通知示例
- name: Notify on failure
  if: failure()
  uses: 8398a7/action-slack@v3
  with:
    status: ${{ job.status }}
    webhook_url: ${{ secrets.SLACK_WEBHOOK }}
```

---

