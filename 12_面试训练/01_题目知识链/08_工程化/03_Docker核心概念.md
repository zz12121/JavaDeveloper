# 题目：Docker 的核心概念是什么？ Dockerfile 的最佳实践是什么？

---

## ⚠️ 先盲答

**不要看任何资料，用自己的话回答，写到纸上或心里默念也行。**

说出镜像、容器、仓库三者的关系，并用类比说明。

---

## 盲答引导

1. Docker 镜像和容器的关系，像什么？和面向对象的什么概念最像？
2. `docker build -t myapp:1.0 .` 这条命令的执行过程是什么？
3. 为什么 Java 应用进容器时，推荐用多阶段构建而不是一条 Dockerfile 写到底？
4. `COPY` 和 `ADD` 命令的区别是什么？什么时候用 ADD 更好？
5. Docker 容器里的 JVM 内存怎么配置？为什么默认配置在容器里可能不准？

---

## 知识链提示

这道题应该让你联想到：

- `[[Docker镜像层]]` → 写时复制（COW），每一层只读
- `[[Docker多阶段构建]]` → 构建时用 maven 镜像，运行只用 JRE 镜像
- `[[Docker网络模式]]` → bridge / host / overlay / none
- `[[容器与JVM]]` → JDK 10+ 自动感知容器 cgroup 内存限制
- `[[Docker存储卷]]` → `VOLUME` 声明的数据卷，绕过 UnionFS

---

## 核心追问

1. 为什么 Docker 镜像通常比虚拟机镜像小得多？Docker 和 VM 的本质区别是什么？
2. 多阶段构建里，`FROM maven:3.8 AS builder` 里的 `AS` 是做什么的？后面的 `FROM openjdk:11` 为什么可以复用 builder 的产物？
3. `ENTRYPOINT` 和 `CMD` 的区别是什么？为什么 `ENTRYPOINT ["java", "-jar", "app.jar"]` 是推荐写法？
4. Docker 容器里 PID 1 进程是什么？如果它变成了僵尸进程，Docker 会怎么处理？
5. 容器内的 Java 应用如何知道容器的内存限制？`-XX:+UseContainerSupport` 是哪个 JDK 版本加入的？

---

## 参考要点（盲答后再看）

<details>
<summary>点击展开</summary>

**镜像 vs 容器 vs 仓库**：

```
仓库（Registry）: Docker Hub / 私有仓库
    ↓ docker pull
镜像（Image）   : 只读模板，叠加层（UnionFS）
    ↓ docker run
容器（Container）: 镜像的运行实例，可写层（COW）
```

**多阶段构建示例**：

```dockerfile
# 阶段1：构建
FROM maven:3.8 AS builder
WORKDIR /app
COPY pom.xml .
RUN mvn dependency:go-offline  # 先下载依赖层
COPY src ./src
RUN mvn package -DskipTests

# 阶段2：运行（只带运行时）
FROM openjdk:11-jre-slim
WORKDIR /app
COPY --from=builder /app/target/myapp.jar ./app.jar
EXPOSE 8080
ENTRYPOINT ["java", "-jar", "app.jar"]
```

**COPY vs ADD**：
- `COPY`：纯复制，本地文件 → 镜像（优先使用）
- `ADD`：可以复制远程 URL，也可以自动解压 tar 文件（不推荐，除非需要解压）

**JVM 在容器里的内存**：
```
JDK 8 u131 之前：JVM 不知道容器内存限制，用物理机内存配置
JDK 8 u131+     ：加 -XX:+UnlockExperimentalVMOptions -XX:+UseCGroupMemoryLimitForHeap
JDK 10+         ：默认启用 UseContainerSupport，自动感知 cgroup
JDK 11+         ：默认开启 UseContainerSupport
```

**最佳实践要点**：
1. `.dockerignore` 排除构建无关文件（target/、.git/、*.md）
2. 优先用较小的基础镜像（alpine、slim）
3. 最小化层数：`RUN` 命令合并
4. 把变化少的层放上面（依赖层先 COPY pom.xml 再 COPY 代码）
5. 不使用 root 用户运行容器

</details>

---

## 下一步

1. 盲答后，对比参考要点，找到卡壳的地方
2. 打开 `[[08_工程化/Docker最佳实践]]` 主题文档，把没懂的地方填进去
3. 在 Obsidian 里建双向链接
4. 在 `[[12_面试训练/每日一题跟踪表]]` 里勾选「今日完成」，打 1~5 分
