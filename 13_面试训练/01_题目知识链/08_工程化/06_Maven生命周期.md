# 题目：Maven 的构建生命周期是什么？ validate、compile、test、package、install、deploy 分别是做什么的？

---

## ⚠️ 先盲答

**不要看任何资料，用自己的话回答，写到纸上或心里默念也行。**

说出三套生命周期（clean / default / site）各自的用途，并解释它们之间的「相互独立」是什么意思。

---

## 盲答引导

1. `mvn clean install` 的执行顺序是什么？先 clean 还是先 install？
2. `mvn compile` 和 `mvn package` 的区别是什么？不 compile 能 package 吗？
3. `mvn test` 默认用什么测试框架？测试代码在哪个目录？
4. `mvn install` 和 `mvn deploy` 的区别是什么？deploy 是发布到哪里？
5. 在 CI 里，`mvn install` 和 `-DskipTests` 一起用会发生什么？

---

## 知识链提示

这道题应该让你联想到：

- `[[Maven生命周期]]` → clean / default / site 三套独立生命周期
- `[[Maven插件]]` → lifecycle 和 plugin goal 的绑定关系
- `[[Maven多模块]]` → 多模块项目中，install 和 deploy 的顺序
- `[[Maven测试跳过]]` → `mvn package -DskipTests` vs `mvn package -Dmaven.test.skip=true`
- `[[Maven私有仓库]]` → deploy 到 Nexus / Artifactory

---

## 核心追问

1. `mvn install -N`（-N = non-recursive）的作用是什么？在多模块项目里有什么用？
2. Maven 的「相位（phase）」和「插件目标（goal）」是什么关系？`mvn compiler:compile` 为什么能跳 lifecycle 直接执行？
3. `mvn dependency:analyze` 插件能发现什么问题？
4. 为什么 `mvn test` 在 `mvn package` 时也会自动执行？怎么跳过？
5. `mvn install` 和 `mvn deploy` 的本质区别是什么？团队协作时必须用 deploy 吗？

---

## 参考要点（盲答后再看）

<details>
<summary>点击展开</summary>

**Maven 三套生命周期**：

```
clean（清理）：
  pre-clean → clean → post-clean

default（构建，最重要）：
  validate → compile → test → package → verify
            → install → deploy

site（站点生成）：
  pre-site → site → post-site → site-deploy
```

**执行顺序特点**：
```
mvn clean install = 先执行 clean → 再执行 default lifecycle 的 install 及之前所有 phase

mvn test = 执行 compile + test（自动执行，不单独需要 mvn compile）
mvn package = 执行 compile + test + package（不执行 install，不推到本地仓库）
```

**phase 和 goal 的关系**：
```
生命周期 phase：定义了构建的「阶段」（按顺序执行）
插件 goal：绑定到 phase 上的具体任务

mvn compiler:compile  ← 跳过 lifecycle，直接调用插件 goal
```

**install vs deploy**：
```
install  → 推到本地仓库（~/.m2/repository），仅本机可用
deploy   → 推到远程仓库（公司 Nexus / 阿里云 Maven 私服 / Maven Central）
```

</details>

---

## 下一步

1. 盲答后，对比参考要点，找到卡壳的地方
2. 打开 `[[09_工程化/Maven生命周期]]` 主题文档
3. 在 Obsidian 里建双向链接
4. 在 `[[12_面试训练/每日一题跟踪表]]` 里勾选「今日完成」，打 1~5 分
