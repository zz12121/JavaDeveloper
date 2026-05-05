# 题目：Git 的 stash 和 reflog 是什么？分别用在什么场景？

---

## ⚠️ 先盲答

**不要看任何资料，用自己的话回答，写到纸上或心里默念也行。**

用自己的话描述 stash 和 reflog 分别在解决什么问题。

---

## 盲答引导

1. `git stash` 之后，工作目录变成了什么状态？暂存区呢？
2. `git stash pop` 和 `git stash apply` 的区别是什么？
3. `git stash` 可以嵌套吗？`git stash -u` 和 `git stash` 的区别是什么？
4. `git reflog` 记录的是什么？它能找回被 `git reset --hard` 删掉的 commit 吗？
5. 什么情况下会用到 `git reflog`？能举一个具体的错误操作场景吗？

---

## 知识链提示

这道题应该让你联想到：

- `[[13_面试训练/01_题目知识链/08_工程化/05_Git stash与reflog]]` → 工作现场的临时保存与恢复
- `Git reflog` → 本地操作历史，不参与 push，是「后悔药」
- `Git reset` → 三种模式（soft/mixed/hard）对暂存区和工作目录的影响
- `Git rebase的危险` → 为什么 rebase 后的分支 push 到远程有风险？
- `Git cherry-pick` → 和 stash 的区别，cherry-pick 是捡哪个 commit？

---

## 核心追问

1. `git stash pop` 时有冲突 stash 会消失吗？`git stash apply` 呢？
2. `git stash list` 看到的 stash 对象存放在哪里？它们会被 `gc` 自动清理吗？
3. `git reflog` 的有效期是多久？`git gc` 会清理 reflog 吗？
4. 场景题：在 develop 分支上开发到一半，接到紧急任务切到 feature-b 分支，怎么用 stash 保护现场？
5. `git reflog` 和 `git log` 的根本区别是什么？`git log` 能看到被 reset 掉的 commit 吗？

---

## 参考要点（盲答后再看）


**stash vs reflog**：

```
git stash     → 把工作目录 + 暂存区的修改「压栈」保存，切换分支
git reflog    → 记录本地 HEAD 每次移动的历史，包括被删除的 commit
```

**git stash 详解**：

```bash
git stash              # 保存现场（工作目录 + 暂存区）
git stash -u           # 也包含未跟踪文件（untracked）
git stash -m "message"  # 给 stash 起名字

git stash list         # 查看所有 stash
git stash show          # 查看 stash 内容（不恢复）

git stash pop          # 恢复 + 删除 stash（优先）
git stash apply         # 恢复 + 保留 stash（用这个更安全）
git stash drop          # 手动删除 stash
```

**git reflog 详解**：

```bash
# 记录内容示例：
0a3b7c8 HEAD@{0}: commit: 修复登录bug
f2e4d6a HEAD@{1}: rebase: 应用补丁
c1a2b3d HEAD@{2}: reset: moving to HEAD~1
# ...所有 HEAD 移动记录

# 找回被 reset --hard 删掉的 commit：
git reflog
git checkout HEAD@{n}  # 切到那个 commit 查看
git branch recovered    # 从那个 commit 创建分支保存
```

**stash 是栈结构（可嵌套）**：
```bash
git stash push -m "A"    # 栈顶
git stash push -m "B"    # 新的栈顶
git stash list
# stash@{0}: On develop: B
# stash@{1}: On develop: A
```

**重要特性**：
- stash 默认不包含 untracked 文件（`-u` 包含）
- stash 对象默认 90 天后被 gc 清理（可通过配置修改）
- reflog 默认 90 天后被 gc 清理


---

## 下一步

1. 盲答后，对比参考要点，找到卡壳的地方
2. 打开 `[[13_面试训练/01_题目知识链/08_工程化/05_Git stash与reflog]]` 主题文档，把没懂的地方填进去
3. 在 Obsidian 里建双向链接
4. 在 `[[13_面试训练/03_每日一题/每日一题跟踪表]]` 里勾选「今日完成」，打 1~5 分
