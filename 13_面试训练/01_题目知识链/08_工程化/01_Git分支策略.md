# 题目：Git 的分支策略是什么？ feature branch 和 GitFlow 的区别是什么？

---

## ⚠️ 先盲答

**不要看任何资料，用自己的话回答，写到纸上或心里默念也行。**

说出至少 3 种分支策略的名字和适用场景。

---

## 盲答引导

1. `master/main` 分支应该保持什么样的状态？能不能直接 commit？
2. `develop` 分支和 `master` 分支的区别是什么？什么时候创建的？
3. `feature/*` 分支从哪个分支拉出来？合并回哪个分支？
4. `release` 分支的生命周期有多长？它和 `master` 的合并有什么特殊操作？
5. `hotfix` 分支为什么必须同时合并回 `master` 和 `develop`？

---

## 知识链提示

这道题应该让你联想到：

- `[[GitFlow流程]]` → 各分支的生命周期管理
- `[[Git rebase]]` → 为什么 feature 分支合并前通常要 rebase？
- `[[Git merge vs squash]]` → feature 合并到 develop 用哪种？为什么？
- `[[Git tag]]` → release 分支和 tag 的关系
- `[[主干开发]]` → Trunk-Based Development vs GitFlow，哪个更适合微服务？

---

## 核心追问

1. `git merge --no-ff` 和 `git merge` 的区别是什么？为什么有些团队强制用 `--no-ff`？
2. rebase 之后本地和远程分叉了怎么处理？`git pull --rebase` 和 `git pull` 的区别？
3. GitFlow 里，`hotfix` 为什么不从 `develop` 分支拉？如果 fix 很简单，会有什么问题？
4. 代码 Review（CR）和分支策略有什么关系？PR/MR 在 GitFlow 里对应哪个环节？
5. 如果团队只有 3 个人，用 GitFlow 会不会过度工程化？什么场景下适合主干开发？

---

## 参考要点（盲答后再看）

<details>
<summary>点击展开</summary>

**GitFlow 全貌**：

```
                              develop
                             /
master ──── hotfix ──────────────────── release ────────→ (合并tag)
                \               /
                 feature/* ────┘
```

**各分支职责**：

| 分支 | 来源 | 合并到 | 生命周期 |
|------|------|--------|---------|
| `master/main` | - | 只能合并进入 | 长期 |
| `develop` | 从 master 拉 | - | 长期 |
| `feature/*` | 从 develop 拉 | develop | 数天~数周 |
| `release/*` | 从 develop 拉 | master + develop | 数天 |
| `hotfix/*` | 从 master 拉 | master + develop | 数小时~数天 |

**--no-ff 的意义**：

```bash
# 普通 merge：fast-forward 时不创建合并提交，丢失分支历史
git checkout develop && git merge feature/x
# 如果 develop 没有新提交 → 自动 fast-forward
# 特征分支历史会「消失」在 git log 里

# --no-ff：强制创建合并提交
git merge --no-ff feature/x
# 始终保留完整的分支历史
```

**hotfix 为什么合并回 develop**：
```
场景：线上紧急 bugfix
- master 有 v1.0 bug
- develop 已经有 v2.0 的很多新 commit

hotfix 打在 master 上 → 必须同时合并回 develop
否则 develop 会「继承」bug，下次 release 又带出来了
```

**何时用主干开发**：
- 团队 ≤ 10 人
- CI/CD 成熟，每个 commit 都能自动测试
- 微服务架构，每个服务独立部署
- 大公司里通常选 GitFlow + PR 流程

</details>

---

## 下一步

1. 盲答后，对比参考要点，找到卡壳的地方
2. 打开 `[[09_工程化/Git分支策略]]` 主题文档，把没懂的地方填进去
3. 在 Obsidian 里建双向链接
4. 在 `[[12_面试训练/每日一题跟踪表]]` 里勾选「今日完成」，打 1~5 分
