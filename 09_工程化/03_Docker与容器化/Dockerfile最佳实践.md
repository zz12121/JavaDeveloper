# Dockerfile最佳实践

> Dockerfile 不是「能跑就行」。不好的 Dockerfile 会导致镜像臃肿、构建慢、安全漏洞多。好的 Dockerfile 能在不改变功能的前提下，把镜像从 1.2GB 压到 120MB。

---

## 这个问题为什么存在？

烂 Dockerfile 的代价：

```
场景 A：镜像臃肿
  FROM ubuntu:20.04
  RUN apt-get update && apt-get install -y build-essential
  COPY . /app
  ...
  → 镜像 1.5GB，传输慢，存储成本高

场景 B：构建慢
  每次改一行代码，重新构建要 10 分钟
  → 因为第 1 条指令是 COPY.，缓存全失效了

场景 C：安全漏洞
  用 root 用户跑容器
  → 容器被突破，攻击者直接拿到宿主机 root 权限

场景 D：运行时报错
  CMD 写的是 sh myscript.sh
  → 脚本第 10 行失败，但容器继续运行（错误被吞掉了）
```

**好的 Dockerfile 要解决的核心问题**：

1. **镜像大小**：能不能压到最小？
2. **构建速度**：能不能利用缓存，避免「改一行重新构建 10 分钟」？
3. **安全性**：能不能不用 root 跑容器？
4. **可调试性**：容器起不来时，能不能快速定位问题？

---

## 它是怎么解决问题的？

### 核心机制：分层缓存

```
Dockerfile 的每条指令生成一个层（layer）
→ 层可以被缓存
→ 只有「变化的层」需要重新构建
```

**缓存生效规则**：

```
假设 Dockerfile 有 5 条指令：

  1. FROM ubuntu:20.04
  2. RUN apt-get update && apt-get install -y curl
  3. COPY pom.xml.
  4. RUN mvn clean package -DskipTests
  5. COPY target/*.jar app.jar

缓存失效的传导：
  如果第 3 条 COPY 变了（pom.xml 改了）
  → 第 3、4、5 条都要重新执行
  → 第 1、2 条用缓存
```

**最佳实践**：把「变化频率最低」的指令放最前面。

### 多阶段构建（Multi-stage Build）

```
问题：
  Dockerfile 中既要编译（需要 JDK、Maven）
  又要运行（只需要 JRE）
  → 如果在一个 Dockerfile 中做，镜像包含编译工具，臃肿且不安全
```

**多阶段构建解决方案**：

```dockerfile
# 阶段 1：编译（起个名字叫 builder）
FROM maven:3.8-eclipse-temurin-11 AS builder
WORKDIR /app
COPY pom.xml.
RUN mvn dependency:go-offline   # 下载依赖（利用缓存）
COPY src/. src/
RUN mvn clean package -DskipTests

# 阶段 2：运行（只复制编译产物）
FROM eclipse-temurin:11-jre
COPY --from=builder /app/target/*.jar app.jar
ENTRYPOINT ["java", "-jar", "app.jar"]
```

**效果**：

| 对比 | 单阶段构建 | 多阶段构建 |
|------|-----------|------------|
| 镜像大小 | ~ 600MB（含 Maven） | ~ 250MB（只含 JRE + jar） |
| 安全 | 包含编译工具，攻击面大 | 只有运行时，攻击面小 |
| 构建速度 | 慢（每次都重新下载依赖） | 快（依赖层缓存） |

---

## 深入原理

### Dockerfile vs docker commit（手工做镜像）

| 维度 | Dockerfile | docker commit |
|------|------------|---------------|
| 可重现性 | 高（文本文件，Git 管理） | 低（手工操作，不可复现） |
| 可维护性 | 高（改 Dockerfile 重新构建） | 低（黑盒镜像，不知道里面改了什么） |
| 镜像大小 | 小（可以控制每层内容） | 大（包含历史变更的中间文件） |
| 团队协作 | 友好（代码审查 Dockerfile） | 不友好（无法审查） |

**结论**：永远用 Dockerfile（或 BuildPack、Kaniko 等自动化工具），不要用 `docker commit`。

### 多阶段构建 vs 单阶段构建 + .dockerignore

| 维度 | 多阶段构建 | 单阶段 +.dockerignore |
|------|---------------|----------------------|
| 镜像大小 | 最优（只含运行时） | 次优（仍包含编译工具） |
| 安全 | 最优（编译工具不在运行时镜像中） | 次优（编译工具仍在镜像中） |
| 构建复杂度 | 稍高（需要写多段 FROM） | 低（一份 Dockerfile） |

**最佳实践**：结合使用！多阶段构建 + .dockerignore。

---

## 正确使用方式

### 1. 用 `.dockerignore` 排除无用文件

```
# .dockerignore 文件（和 .gitignore 语法一样）
target/
*.md
.git/
.idea/
*.iml
.env
node_modules/
```

**效果**：`COPY.` 时不会把 `target/`、`node_modules/` 等无用文件复制进镜像。

```
没有 .dockerignore：
  COPY. /app   → 把 target/（可能 100MB+）也复制进去了
  → 镜像变大，构建变慢

有 .dockerignore：
  target/ 被排除
  → 镜像小，构建快
```

### 2. 合并 RUN 指令减少层数

```dockerfile
# ❌ 坏例子：3 条 RUN，生成 3 个层
RUN apt-get update
RUN apt-get install -y curl
RUN apt-get clean && rm -rf /var/lib/apt/lists/*

# ✅ 好例子：1 条 RUN，生成 1 个层
RUN apt-get update && \
    apt-get install -y curl && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*
```

**为什么？** 每个层都会占用存储空间。合并 `RUN` 可以减少层数，减小镜像大小。

**注意**：层数是有限的（旧版 Docker 限制 127 层），但不是主要问题。主要是减小镜像大小。

### 3. 用 `ENTRYPOINT` + `CMD` 正确设置启动命令

```dockerfile
# 正确用法：ENTRYPOINT 设主命令，CMD 设默认参数
ENTRYPOINT ["java", "-jar", "app.jar"]
CMD ["--spring.profiles.active=prod"]
```

**效果**：

```bash
# 启动容器（用默认参数）
docker run my-image
# 实际执行：java -jar app.jar --spring.profiles.active=prod

# 启动容器（覆盖默认参数）
docker run my-image --spring.profiles.active=test
# 实际执行：java -jar app.jar --spring.profiles.active=test
```

**坑**：如果只用 `CMD`，容器启动命令可以被 `docker run my-image /bin/bash` 覆盖，导致应用不启动。

### 4. 设置时区和编码

```dockerfile
ENV TZ=Asia/Shanghai \
    LANG=C.UTF-8
```

**问题**：默认镜像的时区是 UTC，日志时间会差 8 小时。

---

## 边界情况和坑

### 1. `COPY --chown` 在 Windows 上构建失败

```
报错：
COPY --chown=1000:1000 app.jar /app/
→  Windows 上不支持 --chown（NTFS 没有 Linux 用户概念）
```

**解决**：在 Linux 上构建，或用 `RUN chown` 在容器启动后改权限。

### 2. 多阶段构建时 `--from` 引用错误

```dockerfile
FROM maven:3.8 AS builder
# ...
RUN mvn package   # 生成的 jar 在 /app/target/app.jar

FROM eclipse-temurin:11-jre
COPY --from=builder /app/app.jar /app/   # ❌ 路径错了！少了 target/
```

**排查**：用 `docker run --rm --entrypoint="" builder ls -R /app` 查看构建阶段的文件结构。

### 3. `CMD` 和 `ENTRYPOINT` 混用导致命令被覆盖

```dockerfile
# 错误写法
ENTRYPOINT ["java"]
CMD ["-jar", "app.jar"]
# 用户运行：docker run my-image -version
# 实际执行：java -version   （CMD 被覆盖，app.jar 丢了！）
```

**解决**：用 `ENTRYPOINT` + `CMD` 的正确姿势：

```dockerfile
ENTRYPOINT ["java", "-jar", "app.jar"]
CMD ["--spring.profiles.active=prod"]   # 这个可以被覆盖，但 jar 不会丢
```

### 4. 镜像中用 `latest` 标签导致不可重现构建

```dockerfile
FROM ubuntu:latest   # ❌ 危险！
```

**问题**：今天构建用 ubuntu:22.04，明天构建用 ubuntu:24.04 → 行为可能不一样。

**解决**：永远用具体版本号。

```dockerfile
FROM ubuntu:22.04   # ✅ 可重现
```

### 5. 忘记清理 APT 缓存导致镜像臃肿

```dockerfile
# ❌ 坏例子
RUN apt-get update && apt-get install -y curl
# APT 缓存（/var/lib/apt/lists/）还在镜像中，占用几十 MB

# ✅ 好例子
RUN apt-get update && \
    apt-get install -y curl && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*
```

---

