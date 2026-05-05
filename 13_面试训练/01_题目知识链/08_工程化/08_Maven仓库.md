# 题目：Maven 仓库有哪些类型？ SNAPSHOT 版本和 Release 版本有什么区别？

---

## ⚠️ 先盲答

**不要看任何资料，用自己的话回答，写到纸上或心里默念也行。**

说出三种 Maven 仓库的类型，以及 Maven 查找依赖的顺序。

---

## 盲答引导

1. 本地仓库（`~/.m2/repository`）是怎么来的？第一次 `mvn compile` 时，依赖从哪里下载的？
2. 私服（Nexus/Artifactory）解决了什么问题？和 Maven Central 比有什么优势？
3. `SNAPSHOT` 版本的依赖，每次构建都会重新下载吗？怎么控制？
4. 如果本地仓库有 `A-1.0-SNAPSHOT`，私服有 `A-1.0-SNAPSHOT`，Maven 用哪个？
5. `mvn dependency:purge-local-repository` 是做什么的？什么场景下需要它？

---

## 知识链提示

这道题应该让你联想到：

- `[[Maven本地仓库]]` → `~/.m2/repository`，缓存
- `[[Maven私服]]` → Nexus / 阿里云 / 腾讯云 Maven 镜像加速
- `[[SNAPSHOT版本]]` → 每次构建检查更新，可配置检查频率
- `[[Maven镜像配置]]` → `mirrorOf` 配置，拦截 Central 访问
- `[[Maven依赖查找顺序]]` → 本地 → 私服 → 远程仓库

---

## 核心追问

1. Maven 怎么知道从哪个远程仓库下载依赖？优先级是怎样的？
2. 在公司内网，机器不能访问外网，怎么配置 Maven 使用阿里云镜像？
3. `SNAPSHOT` 版本的 `-U` 参数（`--update-snapshots`）的作用是什么？
4. 如果私服挂了，`mvn compile` 还能成功吗？（取决于本地仓库里有没有缓存）
5. 同一个 `groupId:artifactId:version`，在本地仓库可以有多份吗？用什么区分？

---

## 参考要点（盲答后再看）

<details>
<summary>点击展开</summary>

**Maven 仓库类型**：

```
本地仓库（~/.m2/repository）
    ↓ （依赖不在本地时）
私服（公司 Nexus / Artifactory / 阿里云 Maven 镜像）
    ↓ （私服没有时）
远程仓库（Maven Central Repo / JCenter 等）
```

**Maven 查找依赖的顺序**：
```
1. 本地仓库（~/.m2/repository）
   → 有则使用，结束
   → 没有则继续

2. pom.xml 里配置的 remote repositories（按声明顺序）
   → 通常第一个是公司私服
   → 私服没有 → 私服从 Maven Central 下载（代理配置）

3. settings.xml 里的 <mirrors>
   → 拦截某些仓库的请求，强制定向到镜像
```

**Release vs SNAPSHOT**：

| | Release | SNAPSHOT |
|--|---------|---------|
| 版本号 | `1.0.0`（固定） | `1.0-SNAPSHOT`（动态） |
| 更新 | 不会变 | 每次构建可能拉取新版本 |
| 检查策略 | 无（缓存即最终） | `-U` 或 `alwaysCheckFromRepository=true` |
| 适用 | 正式发布版本 | 开发期间团队内部共享 |
| 典型场景 | 上线后锁定版本 | 开发中联调 |

**SNAPSHOT 拉取策略**：
```bash
# 默认：每天检查一次更新（基于时间戳）
# 强制检查（-U）：
mvn compile -U
# → 强制从远程仓库下载最新的 SNAPSHOT
```

**私服的价值**：
```
1. 加速：统一从国内镜像下载，不受国际网络影响
2. 私有依赖：内部 JAR 包上传，供团队共享
3. 缓存：已经拉过的依赖不用重复下载
4. 安全：扫描依赖中的 CVE 漏洞
```

</details>

---

## 下一步

1. 盲答后，对比参考要点，找到卡壳的地方
2. 打开 `[[09_工程化/Maven仓库]]` 主题文档
3. 在 Obsidian 里建双向链接
4. 在 `[[12_面试训练/每日一题跟踪表]]` 里勾选「今日完成」，打 1~5 分
