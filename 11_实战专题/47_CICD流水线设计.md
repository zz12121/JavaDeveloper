# CI/CD流水线设计

> CI/CD核心：流水线编排 + 环境隔离 + 蓝绿/金丝雀发布 + 回滚。

---

## CI/CD流水线架构

```
代码提交
   │
   ▼
┌─────────┐  触发  ┌─────────┐  构建  ┌─────────┐
│  Git    │ ────→  │  CI     │ ────→   │  镜像构建 │
│  仓库    │        │  触发    │         │  Docker  │
└─────────┘        └─────────┘         └────┬────┘
                                            │
                     ┌──────────────────────┼──────────────────────┐
                     │                      │                      │
                     ▼                      ▼                      ▼
              ┌────────────┐         ┌────────────┐         ┌────────────┐
              │  单元测试   │         │  集成测试   │         │  镜像扫描   │
              │  JUnit     │         │  Postman   │         │  Trivy     │
              └────────────┘         └────────────┘         └────┬──────┘
                                                                    │
                     ┌──────────────────────┬──────────────────────┘
                     │                      │
                     ▼                      ▼
              ┌────────────┐         ┌────────────┐
              │  部署 Staging │         │  部署 Production │
              │  K8s Namespace │         │  蓝绿/金丝雀   │
              └────────────┘         └────────────┘
```

---

## 场景 A：流水线编排混乱

### 现象

```
多分支并行开发时，流水线资源冲突
构建、测试、部署阶段混杂，失败难以定位
代码提交后30分钟才反馈结果，开发体验差
```

### 根因

```
未拆分流水线阶段，串行执行所有任务
无并行设计，无依赖管理
缺乏失败快速反馈机制
```

### 解决方案

```yaml
# GitLab CI 流水线定义（.gitlab-ci.yml）
stages:
  - build
  - test
  - package
  - deploy

variables:
  DOCKER_IMAGE: "registry.example.com/myapp:${CI_COMMIT_SHA}"

# 阶段1：构建（并行执行）
build-job:
  stage: build
  script:
    - mvn clean package -DskipTests
  artifacts:
    paths:
      - target/*.jar
    expire_in: 1 hour

# 阶段2：测试（并行执行单元测试和静态检查）
unit-test:
  stage: test
  script:
    - mvn test
  dependencies:
    - build-job

sonar-check:
  stage: test
  script:
    - mvn sonar:sonar -Dsonar.projectKey=myapp
  dependencies:
    - build-job

# 阶段3：打包镜像
package-image:
  stage: package
  script:
    - docker build -t $DOCKER_IMAGE .
    - docker push $DOCKER_IMAGE
  dependencies:
    - unit-test
    - sonar-check

# 阶段4：部署Staging
deploy-staging:
  stage: deploy
  script:
    - kubectl set image deployment/myapp myapp=$DOCKER_IMAGE -n staging
  only:
    - main
```

**编排关键**：
- 无依赖阶段并行执行（如单元测试和静态检查）
- 失败快速终止，不执行后续阶段
- 制品（Artifacts）在阶段间传递，避免重复构建

---

## 场景 B：环境隔离不足

### 现象

```
开发环境能跑，生产环境报错
多项目共用测试环境，资源冲突
配置泄露（生产配置出现在开发环境）
```

### 根因

```
未做环境物理/逻辑隔离
配置硬编码，未做环境差异化
共用Docker镜像，未做环境标签
```

### 解决方案

```yaml
# K8s 环境隔离（Namespace + ConfigMap）
# 1. 创建环境Namespace
apiVersion: v1
kind: Namespace
metadata:
  name: dev
---
apiVersion: v1
kind: Namespace
metadata:
  name: staging
---
apiVersion: v1
kind: Namespace
metadata:
  name: prod

# 2. 环境差异化配置（ConfigMap）
apiVersion: v1
kind: ConfigMap
metadata:
  name: app-config
  namespace: dev
data:
  DB_URL: "jdbc:mysql://dev-db:3306/myapp"
  REDIS_HOST: "dev-redis"
```

```
隔离策略：
1. 逻辑隔离：K8s Namespace区分dev/staging/prod
2. 配置隔离：ConfigMap/Secret按环境拆分，禁止跨环境引用
3. 资源隔离：K8s ResourceQuota限制每个环境的CPU/内存用量
4. 网络隔离：NetworkPolicy限制环境间网络访问
```

---

## 场景 C：发布策略不合理

### 现象

```
新版本上线后全量故障，影响所有用户
回滚需要30分钟，故障持续时间长
用户投诉量激增，资损严重
```

### 根因

```
全量发布，无灰度机制
无流量切分能力，无法小流量验证
监控指标未做发布关联，无法快速判断发布影响
```

### 解决方案

```
1. 蓝绿发布（适合K8s）
   准备两套完全相同的环境（蓝/绿）
   新版本部署到绿环境，验证通过后切流量
   出问题秒级切回蓝环境

2. 金丝雀发布（适合Istio）
   新版本先部署1%实例，观察错误率/延迟
   没问题逐步切10%->50%->100%
```

```yaml
# Istio 金丝雀发布配置（VirtualService）
apiVersion: networking.istio.io/v1beta1
kind: VirtualService
metadata:
  name: myapp-vs
spec:
  hosts:
    - myapp.example.com
  http:
  - match:
    - headers:
        canary:
          exact: "true"
    route:
    - destination:
        host: myapp
        subset: v2
      weight: 100
  - route:
    - destination:
        host: myapp
        subset: v1
      weight: 90
    - destination:
        host: myapp
        subset: v2
      weight: 10
```

---

## 场景 D：回滚机制缺失

### 现象

```
新版本有bug，无法快速回滚
回滚后数据不一致（数据库迁移未回滚）
镜像被覆盖，找不到旧版本镜像
```

### 根因

```
镜像未做版本标签管理，只保留latest
无回滚脚本，手动操作易出错
数据库迁移工具不支持回滚
```

### 解决方案

```bash
# K8s 回滚脚本
#!/bin/bash
# 1. 查看部署历史版本
kubectl rollout history deployment/myapp -n prod

# 2. 回滚到上一个版本
kubectl rollout undo deployment/myapp -n prod

# 3. 回滚到指定版本
kubectl rollout undo deployment/myapp -n prod --to-revision=2
```

```xml
<!-- Flyway 数据库回滚支持 -->
<build>
  <plugins>
    <plugin>
      <groupId>org.flywaydb</groupId>
      <artifactId>flyway-maven-plugin</artifactId>
      <configuration>
        <url>jdbc:mysql://prod-db:3306/myapp</url>
        <locations>
          <location>filesystem:src/main/resources/db/migration</location>
        </locations>
      </configuration>
    </plugin>
  </plugins>
</build>
```

**回滚关键**：
- 镜像必须带版本标签（如v1.0.0、commit-sha），禁止覆盖latest
- 数据库迁移用Flyway/Liquibase，每次迁移对应一个回滚脚本
- 灰度发布期间保留旧版本实例，确保可快速切回

---

## 涉及知识点

| 概念 | 所属域 | 关键点 |
|------|--------|--------|
| GitLab CI流水线 | 11_实战专题/47_CICD流水线设计 | stages/dependencies/artifacts |
| K8s Namespace | 06_中间件/02_K8s | 环境隔离/ResourceQuota |
| Istio金丝雀发布 | 07_分布式与架构/05_服务网格 | VirtualService/DestinationRule |
| Flyway数据库迁移 | 05_数据库/03_数据库运维 | 版本化迁移/回滚支持 |
| Docker镜像管理 | 06_中间件/04_Docker | 标签管理/镜像扫描 |

---

## 排查 Checklist

```
□ 流水线阶段是否拆分清晰？ → 构建/测试/部署分离
□ 无依赖阶段是否并行执行？ → 减少流水线耗时
□ 环境是否物理/逻辑隔离？ → Namespace/ConfigMap按环境拆分
□ 镜像是否带版本标签？ → 禁止只用latest标签
□ 发布是否支持灰度？ → 蓝绿/金丝雀发布配置
□ 回滚是否可以在1分钟内完成？ → K8s rollout undo脚本
□ 数据库迁移是否支持回滚？ → Flyway/Liquibase undo
□ 制品是否安全扫描？ → Trivy/Snyk扫描镜像漏洞
□ 流水线失败是否快速反馈？ → 邮件/钉钉通知到提交人
```

---

## 我的实战笔记

-（待补充，项目中的真实经历）
