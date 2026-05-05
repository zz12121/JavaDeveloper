# CI流程

> CI（Continuous Integration，持续集成）不是「提交代码后自动跑测试」。它是**质量内建**的核心机制——每次提交都验证「代码能编译、测试能通过、基本规范不违反」。

---

## 这个问题为什么存在？

没有 CI 的团队是什么样的？

```
场景 A：我本地能跑
  开发者：「在我机器上能跑啊！」
   → 原来他本地改了配置文件，没提交
   → CI 会在干净环境中重新构建，立即发现这个问题

场景 B：分支合并时冲突一堆
   → 大家都在自己分支上开发，几周才合并一次
   → 合并时 50 个文件冲突，解决完发现功能坏了

场景 C：测试是「可选」的
   → 有人懒得写测试，直接提交了
   → 没人知道测试覆盖率在下降

场景 D：代码规范是「口头约定」
   → 有人用 Tab，有人用空格
   → 有人命名变量 a、b、c
   → Code Review 时 Reviewer 要花时间指出这些规范问题
```

**CI 要解决的核心问题**：

1. **快速反馈**：提交后 5 分钟内知道「能不能编译」「测试过没过」
2. **强制规范**：Lint、代码格式化、测试覆盖率，不通过不让合并
3. **防止「我机器上能跑」**：在干净环境中构建，不依赖本地配置
4. **尽早发现冲突**：每次提交都合并到主干，冲突在最小范围内解决

---

## 它是怎么解决问题的？

### CI 的基本流程

```
开发者 push 代码
      ↓
Git 仓库（GitHub/GitLab）触发 Webhook
      ↓
CI 服务器（Jenkins/GitHub Actions/GitLab CI）
      ↓
{1. 拉取代码（干净环境）
 {2. 编译（mvn compile 或 gradle build）
 {3. 跑测试（mvn test）
 {4. 代码扫描（SonarQube / Lint）
 {5. 发布构建产物（可选）
      ↓
     成功 → 标记 Commit 为 ✅（可以合并）
     失败 → 标记 Commit 为 ❌（不能合并）
```

### CI 配置文件示例（GitLab CI）

```yaml
# .gitlab-ci.yml
stages:
  - compile
  - test
  - lint

variables:
  MAVEN_OPTS: "-Dmaven.repo.local=.m2"

cache:
  key: "$CI_COMMIT_REF_SLUG"
  paths:
    - .m2/repository/

compile_job:
  stage: compile
  image: maven:3.8-eclipse-temurin-11
  script:
    - mvn compile -DskipTests
  only:
    - merge_requests

test_job:
  stage: test
  image: maven:3.8-eclipse-temurin-11
  script:
    - mvn test
  coverage: '/Total.*?([0-9]{1,3})%/'
  artifacts:
    reports:
      junit: target/surefire-reports/*.xml
    paths:
      - target/

lint_job:
  stage: lint
  image: sonarsource/sonar-scanner-cli
  script:
    - sonar-scanner -Dsonar.projectKey=my-app
  only:
    - main
```

### CI 流水线的关键设计原则

```
原则 1：速度优先
  → CI 要在 5~10 分钟内完成
  → 开发者还在上下文内时，就能收到反馈

原则 2：失败快速（Fail Fast）
  → 编译失败，就不要跑测试了
  → 用 stages 控制顺序，前面的 stage 失败，后面的不跑

原则 3：环境干净
  → 每次都用全新容器（Docker 镜像）
  → 不依赖上一次构建的状态

原则 4：缓存合理
  → Maven 的 .m2/repository/ 要缓存
  → 但 target/ 每次要清理（或不用缓存）
```

---

## 深入原理

### CI  vs  本地构建

| 维度 | CI（服务器构建） | 本地构建（开发者机器） |
|------|-------------------|----------------------|
| 环境一致性 | 干净、一致 | 可能装有特殊依赖 |
| 触发方式 | 自动（push / PR） | 手动（mvn test） |
| 强制性 | 强制（不通过不能合并） | 不强制（可能忘记跑） |
| 并行度 | 高（服务器并发） | 低（本地只有一核） |

**结论**：本地构建是「自测」，CI 是「质量门禁」，两者不能互相替代。

### Jenkins vs GitHub Actions / GitLab CI

| 维度 | Jenkins | GitHub Actions / GitLab CI |
|------|---------|--------------------------|
| 配置方式 | Web UI + Jenkinsfile | YAML 文件（版本控制） |
| 维护成本 | 高（需要维护服务器） | 低（SaaS，或少量自托管） |
| 插件生态 | 极其丰富 | 快速增长中 |
| 学习曲线 | 陡 | 缓 |
| 适合场景 | 老牌大公司、复杂流水线 | 新项目、开源项目 |

**为什么新项目倾向用 GitHub Actions / GitLab CI？**

配置即代码（Configuration as Code）—— `.github/workflows/*.yml` 在 Git 中管理，Reviewer 可以看 CI 配置的变更。

---

## 正确使用方式

### 1. 用 CI 强制代码规范

```yaml
# GitLab CI 示例：代码格式化检查
format_check:
  stage: lint
  image: maven:3.8-eclipse-temurin-11
  script:
    - mvn spotless:check   # 检查代码格式是否符合规范
  only:
    - merge_requests
```

**效果**：代码格式不对 → CI 失败 → PR 不能合并 → 开发者必须本地运行 `mvn spotless:apply` 修复。

### 2. 用 CI 检查测试覆盖率

```yaml
# GitHub Actions 示例
test:
  runs-on: ubuntu-latest
  steps:
    - uses: actions/checkout@v3
    - name: Run tests
      run: mvn test
    - name: Upload coverage to Codecov
      uses: codecov/codecov-action@v3
      with:
        files: target/site/jacoco/jacoco.xml
```

**配合覆盖率门禁**：

```xml
<!-- pom.xml 中配置 JaCoCo -->
<plugin>
    <groupId>org.jacoco</groupId>
    <artifactId>jacoco-maven-plugin</artifactId>
    <version>0.8.8</version>
    <configuration>
        <minimumCoverage>0.80</minimumCoverage>  <!-- 强制 80% 覆盖率 -->
    </configuration>
</plugin>
```

### 3. 用缓存加速 CI

```yaml
# GitLab CI 缓存示例
cache:
  key: "$CI_COMMIT_REF_SLUG"
  paths:
    - .m2/repository/   # Maven 依赖缓存
    - node_modules/    # npm 依赖缓存

# GitHub Actions 缓存示例
- name: Cache Maven dependencies
  uses: actions/cache@v3
  with:
    path: ~/.m2/repository
    key: ${{ runner.os }}-m2-${{ hashFiles('**/pom.xml') }}
    restore-keys: ${{ runner.os }}-m2-
```

---

## 边界情况和坑

### 1. CI 跑过了，但合并后 main 挂了

```
原因：CI 是基于 PR 的源分支运行的
  → 没考虑 main 可能已经更新了
```

**解决**：PR 合并前，强制重新基于 main 做 rebase 或 merge。

```yaml
# GitHub Actions：PR 触发时，拉取最新的 main
steps:
  - uses: actions/checkout@v3
    with:
      ref: ${{ github.event.pull_request.head.ref }}
  - run: git merge origin/main   # 合并最新的 main
```

### 2. CI 缓存导致构建用旧的依赖

```
场景：
  缓存了 .m2/repository/
  → pom.xml 新增了依赖
  → CI 用的还是缓存，找不到新依赖
  → 构建失败
```

**解决**：缓存 key 包含 `pom.xml` 的哈希。

```yaml
cache:
  key: "$CI_COMMIT_REF_SLUG-$CI_COMMIT_SHA"   # 每次 commit 变，缓存也变
  # 更好的方式：基于 pom.xml 的哈希
  key: "$CI_COMMIT_REF_SLUG-{{ checksum 'pom.xml' }}"
```

### 3. CI 跑得太慢，开发者失去耐心

```
原因：
  - 没用缓存（每次都重新下载依赖）
  - 串行跑任务（编译、测试、Lint 按顺序跑）
  - 测试没并行化
```

**解决**：

```yaml
# 并行跑 job
stages:
  - compile
  - test
  - lint

# compile、test、lint 在不同 stage，可以并行（如果依赖允许）
# 或者同一 stage 内的 job 自动并行

# Maven 并行构建
script:
  - mvn test -T 4   # 4 个线程并行
```

### 4. CI 配置文件语法错误，导致流水线不运行

```
排查：
  GitHub Actions：在 "Actions" 标签页看是否有报错
  GitLab CI：在 "CI/CD → Jobs" 页面看是否有 "CI config file not found"
```

**预防**：用 IDE 插件（如 GitLab Workflow for VS Code）在本地校验 YAML 语法。

---

