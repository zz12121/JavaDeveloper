# 题目：CI/CD 流程是什么？ Jenkins 和 GitLab CI / GitHub Actions 有什么核心区别？

---

## ⚠️ 先盲答

**不要看任何资料，用自己的话回答，写到纸上或心里默念也行。**

说出 CI（持续集成）和 CD（持续交付 / 持续部署）的区别是什么。

---

## 盲答引导

1. 「持续集成」解决的核心问题是什么？在没有 CI 的团队里，这个问题是怎样的？
2. GitLab CI 的 `.gitlab-ci.yml` 配置文件里，`stages` 和 `jobs` 是什么关系？
3. Jenkins 的 Pipeline 是怎么写的？`script` 块和 `sh` 命令有什么关系？
4. Blue-Green 部署和 Rolling Update 的核心区别是什么？哪种切换更快？
5. 为什么 CD 里的「持续交付」（Delivery）和「持续部署」（Deployment）是两个不同的概念？

---

## 知识链提示

这道题应该让你联想到：

- `[[持续集成]]` → 每次 commit 自动跑构建+测试
- `[[GitLab CI]]` → `.gitlab-ci.yml` / stages / runners
- `[[Jenkins Pipeline]]` → `Jenkinsfile` Groovy DSL
- `[[BlueGreen部署]]` → 两套环境，切换流量
- `[[灰度发布]]` → 金丝雀发布 vs 蓝绿部署

---

## 核心追问

1. GitLab CI 的 Runner 是什么？如果没有配置 Runner，`.gitlab-ci.yml` 会被执行吗？
2. Jenkins Pipeline 里，`environment` 变量、`params` 参数、`credentials` 凭证三者的区别和使用场景？
3. Blue-Green 部署需要几套服务器？如果只有一台服务器，能做蓝绿部署吗？
4. Canary 发布（灰度）和 Blue-Green 的本质区别是什么？适合哪种场景？
5. 为什么说「没有测试覆盖率保障的 CI 是假 CI」？单元测试和集成测试在 CI 里分别起什么作用？

---

## 参考要点（盲答后再看）

<details>
<summary>点击展开</summary>

**CI vs CD**：

```
CI（持续集成）：每次代码提交 → 自动构建 + 自动测试
     ↓
CD（持续交付）：构建+测试通过 → 自动部署到「类生产环境」（手动审批上线）
     ↓
CD（持续部署）：构建+测试通过 → 自动部署到生产环境（无需人工干预）
```

**GitLab CI 结构**：

```yaml
stages:           # 定义阶段顺序
  - build
  - test
  - deploy

build_app:        # Job
  stage: build
  script:
    - mvn package -DskipTests
  artifacts:
    paths:
      - target/*.jar
    expire_in: 1 day

test_unit:
  stage: test
  script:
    - mvn test
  needs: ["build_app"]  # 依赖关系

deploy_prod:
  stage: deploy
  script:
    - kubectl apply -f k8s.yaml
  only:
    - main             # 只有 main 分支才执行
```

**Jenkins Pipeline**：

```groovy
pipeline {
    agent any
    environment {
        REGISTRY = 'registry.mycompany.com'
    }
    stages {
        stage('Build') {
            steps {
                sh 'mvn clean package -DskipTests'
            }
        }
        stage('Test') {
            steps {
                sh 'mvn test'
            }
        }
        stage('Deploy') {
            when { branch 'main' }
            steps {
                sh "docker build -t ${REGISTRY}/myapp:${GIT_COMMIT[0..7]} ."
            }
        }
    }
}
```

**Blue-Green vs Rolling Update**：

```
Blue-Green：准备两套完全相同的集群
            切流：修改负载均衡器权重，瞬间切换
            回滚：切回旧集群，同样瞬间完成

Rolling Update：逐步替换（先杀1个Pod，再起1个新Pod...）
                过程中：新旧版本同时存在，部分用户访问到新版本
                回滚：反向执行
```

</details>

---

## 下一步

1. 盲答后，对比参考要点，找到卡壳的地方
2. 打开 `[[08_工程化/CI_CD流程]]` 主题文档，把没懂的地方填进去
3. 在 Obsidian 里建双向链接
4. 在 `[[12_面试训练/每日一题跟踪表]]` 里勾选「今日完成」，打 1~5 分
