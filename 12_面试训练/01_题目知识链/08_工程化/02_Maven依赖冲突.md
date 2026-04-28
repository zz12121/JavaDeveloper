# 题目：Maven 依赖冲突是怎么产生的？如何排查和解决？

---

## ⚠️ 先盲答

**不要看任何资料，用自己的话回答，写到纸上或心里默念也行。**

说出「依赖传递」和「最近原则」分别是什么，并各举一个会导致问题的例子。

---

## 盲答引导

1. `A → B → C`，`A` 不显式依赖 `C`，那 `A` 能用 `C` 吗？什么情况下会冲突？
2. Maven 用「最近原则」选版本，如果两个版本距离一样长，会选哪个？
3. `mvn dependency:tree` 和 `mvn dependency:tree -Dverbose` 的区别是什么？
4. 怎么强制使用某个版本的依赖，而忽略传递进来的版本？
5. 为什么阿里巴巴规范里要求不同版本的 `spring-boot-starter` 必须显式声明版本号？

---

## 知识链提示

这道题应该让你联想到：

- `[[Maven依赖传递]]` → `compile`/`provided`/`runtime` scope 对传递性的影响
- `[[Maven依赖仲裁]]` → 最近原则 / 显式声明优先
- `[[Maven依赖排除]]` → `<exclusions>` 标签的用法
- `[[Maven依赖管理]]` → `<dependencyManagement>` 统一版本
- `[[Maven enforcer插件]]` → 强制检查依赖冲突的工具

---

## 核心追问

1. `spring-boot-starter-web` 里依赖了 `spring-core`，我的项目里也显式声明了 `spring-core` 不同版本，谁生效？
2. `mvn dependency:tree -Dverbose` 的 verbose 模式会输出什么额外信息？
3. `spring-boot-dependencies` 的 `<dependencyManagement>` 为什么能统一子模块的版本？
4. 如果 A 和 B 都依赖 C，但 A 用的是 C 的某个类，B 用的是 C 的另一个类，能共存吗？
5. `shade` 插件和 `assembly` 插件在解决依赖冲突时，有什么区别？

---

## 参考要点（盲答后再看）

<details>
<summary>点击展开</summary>

**依赖传递（Dependency Transitivity）**：

```
A(pom.xml) 声明依赖 B
B(pom.xml) 声明依赖 C
→ A 自动获得 C（传递依赖）

scope 对传递性的影响：
├── compile  → 传递（默认）
├── provided → 不传递（由容器提供，如 servlet-api）
├── runtime  → 传递，但 compile 时不可见
└── test     → 不传递
```

**最近原则（Nearest Definition）**：
```
A → B(v1.0) → C(v2.0)
A → D(v1.5)

Maven 会选：D(v1.5)（距离A更近）

距离相同时：先声明的优先（pom.xml 里谁写在前面）
```

**解决方式**：

```xml
<!-- 方式1：显式声明（优先于传递依赖） -->
<dependency>
    <groupId>com.google.guava</groupId>
    <artifactId>guava</artifactId>
    <version>30.0-jre</version>
</dependency>

<!-- 方式2：排除传递依赖 -->
<dependency>
    <groupId>org.apache.httpcomponents</groupId>
    <artifactId>httpclient</artifactId>
    <exclusions>
        <exclusion>
            <groupId>commons-logging</groupId>
            <artifactId>commons-logging</artifactId>
        </exclusion>
    </exclusions>
</dependency>

<!-- 方式3：dependencyManagement 统一管理 -->
<dependencyManagement>
    <dependencies>
        <dependency>
            <groupId>com.google.guava</groupId>
            <artifactId>guava</artifactId>
            <version>30.0-jre</version>
        </dependency>
    </dependencies>
</dependencyManagement>
<!-- 子模块不写 version，Maven 从父 pom 的 dependencyManagement 读取 -->
```

**shade vs assembly**：
- `shade`：把依赖的类重打包（重写 package）进 JAR，能解决类冲突
- `assembly`：只打包，不重写，最简单的打包方式

</details>

---

## 下一步

1. 盲答后，对比参考要点，找到卡壳的地方
2. 打开 `[[08_工程化/Maven依赖冲突]]` 主题文档，把没懂的地方填进去
3. 在 Obsidian 里建双向链接
4. 在 `[[12_面试训练/每日一题跟踪表]]` 里勾选「今日完成」，打 1~5 分
