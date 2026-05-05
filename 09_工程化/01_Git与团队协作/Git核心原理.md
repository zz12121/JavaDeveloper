# Git核心原理

> Git 不是「存储文件差异」的系统，而是「存储文件快照」的**内容寻址文件系统**。理解这一点，所有 Git 命令的行为都能推导出来。

---

## 这个问题为什么存在？

在 Git 之前，主流版本控制系统（CVS、SVN）都是**增量存储**模式：

```
SVN 存储模式：
版本1: 完整文件
版本2: 相对版本1的差异（diff）
版本3: 相对版本2的差异
...
```

这种模式有三个根本问题：

1. **切换版本慢**：要恢复到版本1，必须从最新版本一路「反向应用」所有 diff
2. **网络依赖**：集中式存储，服务器挂了全团队无法工作
3. **分支成本高**：SVN 创建分支 = 复制整个目录，慢且占空间

**Git 的设计哲学**：本地化 + 快照存储 + 内容寻址。

Linus Torvalds 在 2005 年花 2 周写出来 Git，核心目标就一个：**Linux 内核这种巨型项目，合并要快。**

---

## 它是怎么解决问题的？

### 核心机制：四种对象类型

Git 的本质是一个**键值对数据库**（key-value store），key 是 SHA-1 哈希，value 是对象。

```
Git 对象模型：
┌─────────────────────────────────────────────────────────┐
│                      .git/objects                      │
├─────────────────────────────────────────────────────────┤
│  blob    → 文件内容（只存内容，不存文件名）               │
│  tree    → 目录结构（指向 blob 或其他 tree）              │
│  commit  → 提交（指向一个 tree + 父提交 + 元数据）        │
│  tag     → 注解标签（可选，指向一个 commit）               │
└─────────────────────────────────────────────────────────┘
```

**实际例子**：你执行 `git commit -m "init"` 后，Git 内部发生了什么？

```bash
# 假设工作区有一个文件 README.md，内容是 "# Hello"

# 1. git add README.md
#    → 计算内容哈希：SHA-1("# Hello\n") = a1b2c3...
#    → 存入 .git/objects/a1/b2c3...（blob 对象）

# 2. git commit -m "init"
#    → 创建 tree 对象（记录：README.md → a1b2c3...）
#    → 创建 commit 对象（指向 tree，包含作者/时间/提交信息）
#    → 将 commit 的哈希写入 HEAD 指向的分支文件
```

```
存储结构可视化：
commit a1b2c3...（提交对象）
  │
  │  指向
  ↓
tree 9f8e7d...（目录树对象）
  │
  │  包含
  ↓
README.md → blob a1b2c3...（文件内容对象）
```

**为什么用 SHA-1 做 key？**

不是为了防止「恶意碰撞」（那是后来加的考虑），而是为了**内容寻址**：
- 相同内容 → 相同哈希 → 只存一份（去重）
- 内容变了 → 哈希变了 → 新对象（快照，不是差异）
- 不需要「文件版本号」这种外部标识，内容本身就是地址

### 引用（References）：人类友好的指针

SHA-1 哈希（`a1b2c3d4...`）对人类不友好，所以 Git 引入了**引用**：

```
.git/refs/
├── heads/           # 分支引用
│   ├── main        → a1b2c3...（指向最新提交）
│   └── feature/login → f6e5d4...
├── remotes/        # 远程跟踪分支
│   └── origin/
│       └── main   → a1b2c3...
└── tags/           # 标签引用
    └── v1.0.0     → e3d2c1...
```

**HEAD：当前所在的引用（或提交）**

```
HEAD 的两种状态：
1. 指向分支（正常状态）
   HEAD → refs/heads/main → a1b2c3...
   此时提交会移动 main 的指向

2. 分离头指针（detached HEAD）
   HEAD → a1b2c3...（直接指向提交，不通过分支）
   此时提交不会更新任何分支，切换分支后提交可能丢失
```

### 暂存区（Index / Staging Area）

这是 Git 最独特的设计——**三个区域**：

```
工作区（Working Directory）     ← 你看到的文件
     ↓ git add
暂存区（Staging Area / Index） ← 下次提交的快照
     ↓ git commit
版本库（Repository）            ← .git/objects 中的对象
```

**为什么需要暂存区？**

其他 VCS（包括 Mercurial）没有暂存区，提交 = 工作区所有变更。暂存区允许你：
- 精确控制每次提交包含哪些变更（部分文件提交）
- 拆分大型修改为多个逻辑独立的提交
- `git add -p` 甚至可以按「代码块（hunk）」选择性暂存

---

## 深入原理

### Git vs SVN（集中式 vs 分布式）

| 维度 | Git | SVN |
|------|-----|-----|
| 存储方式 | 快照（每个版本存完整文件） | 增量（存差异） |
| 仓库模式 | 分布式（每人有完整仓库） | 集中式（只有服务器有完整历史） |
| 分支成本 | 极低成本（只创建一个 41 字节的引用文件） | 高成本（复制目录） |
| 离线工作 | 完全支持（所有操作本地） | 无法提交/查看历史 |
| 合并算法 | 三路合并（共同祖先 + 两个分支） | 两路合并（你的版本 + 对方版本） |

**为什么 SVN 的分支成本高？**

SVN 的分支是目录拷贝：`/trunk` → `/branches/feature`。服务器要复制所有文件记录。Git 的分支只是指针：`refs/heads/main` → `refs/heads/feature`，创建一个 41 字节的文件。

**为什么 Git 的合并更智能？**

Git 会找到「共同祖先提交」，做三路合并：
```
共同祖先：   版本 A
              ↗    ↘
你的分支：  版本 B   版本 C  ← 对方的的分支
              ↘    ↗
           三路合并结果
```

SVN 没有「共同祖先」概念（因为它是增量存储），只能做两路合并，冲突率更高。

### Git vs Mercurial（另一个分布式 VCS）

| 维度 | Git | Mercurial |
|------|-----|-----------|
| 命令设计 | 底层命令暴露（plumbing vs porcelain） | 命令更统一，学习曲线更低 |
| 数据存储 | 内容寻址 + 快照 | 类似，但概念更抽象 |
| 分支模型 | 轻量分支 + HEAD 指针 | 同样轻量，但概念更简洁 |
| 性能 | 对大型仓库（单体巨石）优化更好 | 部分场景更快 |
| 生态 | 绝对主导（GitHub/GitLab） | 日渐式微 |

**为什么 Git 赢了？**

不是技术原因，是生态原因。GitHub 的出现让 Git 成为了「社交工具」，而不只是版本控制系统。

---

## 正确使用方式

### 1. 理解 `git reset` 的三个模式

这是 Git 最容易被误解的命令：

```bash
# --soft：只移动 HEAD，不碰暂存区和工作区
git reset --soft HEAD~1
# 效果：提交撤销了，但变更还在暂存区（像 git add 之后的状态）

# --mixed（默认）：移动 HEAD + 重置暂存区，不碰工作区
git reset HEAD~1              # 等同于 --mixed
# 效果：提交撤销了，变更在工作区（像 git add 之前的状态）

# --hard：移动 HEAD + 重置暂存区 + 重置工作区
git reset --hard HEAD~1
# 效果：提交撤销了，工作区也回到上一个提交的状态（变更全部丢失！）
```

```
三个模式的影响范围：
           HEAD    暂存区    工作区
--soft     ✓ 移动   ✗ 不动   ✗ 不动
--mixed    ✓ 移动   ✓ 重置   ✗ 不动   ← 默认
--hard     ✓ 移动   ✓ 重置   ✓ 重置   ← 危险！
```

**正确用法**：
- 想修改最新提交的消息 → `git commit --amend`（不要 reset）
- 想撤销提交但保留变更 → `git reset --soft HEAD~1`
- 想彻底丢弃最新提交的所有变更 → `git reset --hard HEAD~1`（谨慎！）

### 2. 用 `git reflog` 找回「丢失」的提交

`git reset --hard` 后，提交并没有立即删除！Git 的垃圾回收（GC）默认 2 周后才会清理「不可达对象」。

```bash
# 查看 HEAD 的移动历史
git reflog
# 输出：
# a1b2c3d HEAD@{0}: reset --hard HEAD~1：回到上一个提交
# f6e5d4c HEAD@{1}: commit：完成了登录功能   ← 这个提交还在！

# 找回「丢失」的提交
git reset --hard f6e5d4c
```

**这是 Git 的「后悔药」机制**——只要对象没有被 GC 清理，你可以通过 reflog 找到它并恢复。

### 3. 用 `git rebase` 保持线性历史

```bash
# 场景：你从 main 拉了分支 feature，main 又有新提交
# 用 merge：会产生一个「合并提交」，历史分叉
git checkout feature
git merge main
# 历史：  A ─ B ─ M （M 是合并提交，有两个父提交）

# 用 rebase：把你的提交「挪到」main 的最新提交之后
git checkout feature
git rebase main
# 历史：  A ─ B ─ C' （C' 是你重新应用的提交，哈希变了）
```

**rebase 的本质**：撤销你的每个提交，把临时文件存起来，更新到 main 最新，再重新应用你的每个提交。

**黄金规则**：**不要 rebase 已经推送到远程的公共分支**。因为 rebase 会改变提交的哈希，其他人基于旧哈希的工作会冲突。

### 4. 用 `.gitignore` 防止垃圾文件入库

```
# .gitignore 规则
*.log          # 忽略所有 .log 文件
/target/       # 忽略根目录下的 target 目录（Maven 构建输出）
node_modules/  # 忽略所有 node_modules 目录
!.gitignore     # 不忽略 .gitignore 自身
```

**已追踪的文件不会被 .gitignore 影响**。如果文件已经被 Git 追踪（`git add` 过），需要先清除缓存：
```bash
git rm --cached filename    # 从暂存区删除，但保留本地文件
```

---

## 边界情况和坑

### 1. 分离头指针（Detached HEAD）导致提交丢失

```bash
git checkout a1b2c3...   # 直接 checkout 一个提交，进入 detached HEAD 状态
# 此时你做的提交不会更新任何分支引用
# 切换回 main 后，这些提交变成「不可达对象」，最终被 GC 清理

# 正确做法：基于提交创建分支
git checkout -b temp-branch a1b2c3...
```

**识别方法**：`git status` 会提示 `HEAD detached at a1b2c3`。

### 2. `git clean` 永久删除未追踪文件

```bash
git clean -fd   # 删除所有未追踪的文件和目录
# 这些文件没有在 Git 的历史中，删除后无法恢复！
```

**防御措施**：先 `git clean -fdn`（dry run，只显示会删除什么，不实际删除）。

### 3. 文件名大小写在 Windows/macOS 上不敏感

```bash
# 在 Windows 上
git mv readme.md README.md   # 报错：大小写不敏感的文件系统
```

**解决方案**：
```bash
git config core.ignorecase false   # 让 Git 区分大小写
# 或者
git mv readme.md temp.md
git mv temp.md README.md
```

### 4. 大文件会永久膨胀仓库

Git 的快照存储方式意味着：**每个版本都存完整文件**。一个 100MB 的文件，改了 10 次 = 1GB 仓库。

**正确做法**：
- 用 `.gitignore` 排除二进制产物
- 用 [Git LFS](https://git-lfs.github.com/) 管理大文件
- 已经提交的大文件要从历史中彻底清除（`git filter-branch` 或 `BFG Repo-Cleaner`）

### 5. `git push --force` 会覆盖远程历史

```bash
git rebase main
git push --force   # 用你的本地历史覆盖远程 → 其他人的工作基于的旧提交消失了
```

**安全替代**：`git push --force-with-lease`（只有当你基于最新的远程分支时才允许 force push）。

---

