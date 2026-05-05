# Monorepo工程架构设计

> Monorepo核心：依赖管理 + 增量构建 + 代码生成 + 统一规范。

---

## Monorepo架构拓扑

```
Monorepo根目录
   │
   ├── packages/
   │   ├── auth-service/       # 认证服务
   │   ├── user-service/       # 用户服务
   │   ├── common-utils/       # 公共工具
   │   └── proto-files/       # Protobuf定义
   │
   ├── .bazelrc                # Bazel构建配置
   ├── build.gradle            # Gradle根构建脚本
   └── lerna.json             # Lerna多包管理配置
```

---

## 场景 A：依赖分析与构建拓扑

### 现象

```
构建时重复编译无变更模块，耗时1小时+
依赖混乱，循环依赖导致构建失败
模块A变更，所有依赖模块都被重新构建
```

### 根因

```
未做依赖拓扑分析，全量构建
无依赖图管理，无法识别变更影响范围
循环依赖未检测，构建时栈溢出
```

### 解决方案

```javascript
// Lerna依赖分析示例（识别变更影响范围）
const { execSync } = require('child_process');
const fs = require('fs');
const path = require('path');

// 1. 获取上次构建后的变更文件
const changedFiles = execSync('git diff --name-only HEAD~1 HEAD').toString().split('\n');

// 2. 分析变更影响范围（基于package.json的依赖关系）
const packagesDir = path.join(__dirname, 'packages');
const packages = fs.readdirSync(packagesDir).filter(p => 
  fs.existsSync(path.join(packagesDir, p, 'package.json'))
);

// 3. 构建依赖拓扑图
const depGraph = {};
packages.forEach(pkg => {
  const pkgJson = require(path.join(packagesDir, pkg, 'package.json'));
  depGraph[pkg] = Object.keys(pkgJson.dependencies || {}).filter(d => 
    packages.includes(d)
  );
});
```

**依赖分析关键**：
- 用Lerna/Nx等工具自动分析包依赖拓扑
- 构建前生成依赖图，识别变更影响范围
- 禁止循环依赖，CI中加入依赖校验步骤

---

## 场景 B：增量构建Bazel

### 现象

```
每次构建都全量编译，耗时30分钟+
本地构建和CI构建结果不一致
重复下载依赖，浪费带宽和时间
```

### 根因

```
未用增量构建工具，无缓存机制
构建脚本未做输入/输出声明，无法判断是否需要重构建
依赖未做哈希校验，缓存命中率低
```

### 解决方案

```python
# Bazel BUILD文件定义（增量构建核心）
# packages/auth-service/BUILD
java_library(
    name = "auth-service",
    srcs = glob(["src/main/java/**/*.java"]),
    deps = [
        "//packages/common-utils:common-utils",
        "@maven//:com_google_guava_guava",
    ],
    resources = glob(["src/main/resources/**/*"]),
)
```

```groovy
// Gradle增量构建配置（build.gradle）
tasks.withType(JavaCompile) {
    options.incremental = true  // 启用增量编译
    outputs.cacheIf { true }    // 缓存编译结果
    inputs.files(fileTree("src/main/java"))
    outputs.dir(fileTree("build/classes"))
}
```

**增量构建关键**：
- Bazel基于内容哈希判断是否需要重构建，缓存命中率>90%
- Gradle增量编译只编译变更文件，构建时间缩短70%
- 远程缓存（Bazel Remote Cache）让CI和本地构建共享缓存

---

## 场景 C：代码生成Protobuf

### 现象

```
前后端接口定义不一致，联调时发现字段缺失
手动编写DTO代码，重复劳动且易出错
接口变更后，所有相关代码都要手动修改
```

### 根因

```
未用IDL（接口定义语言）统一管理接口
代码生成流程未自动化，手动执行
生成代码未纳入版本控制，多人协作冲突
```

### 解决方案

```protobuf
// proto-files/user.proto（接口定义）
syntax = "proto3";

package com.example.user;

option java_multiple_files = true;
option java_package = "com.example.user.proto";

message User {
  int64 id = 1;
  string username = 2;
  string email = 3;
  int32 age = 4;
}

service UserService {
  rpc GetUser(GetUserRequest) returns (GetUserResponse);
}
```

```xml
<!-- Maven Protobuf代码生成配置 -->
<plugin>
  <groupId>com.github.os72</groupId>
  <artifactId>protoc-jar-maven-plugin</artifactId>
  <executions>
    <execution>
      <phase>generate-sources</phase>
      <configuration>
        <protocVersion>3.11.4</protocVersion>
        <inputDirectories>
          <include>src/main/proto</include>
        </inputDirectories>
        <outputTargets>
          <outputTarget>
            <type>java</type>
            <outputDirectory>src/main/java</outputDirectory>
          </outputTarget>
        </outputTargets>
      </configuration>
    </execution>
  </executions>
</plugin>
```

**代码生成关键**：
- 用Protobuf/OpenAPI统一定义接口，前后端自动生成代码
- 代码生成纳入构建流程，接口变更自动重新生成
- 生成代码提交到版本库，避免多人协作差异

---

## 场景 D：统一规范ESLint/Checkstyle

### 现象

```
团队代码风格不一致，PR中大量格式问题
低级错误（未关闭资源、空指针）频繁出现
不同项目用不同规范，跨项目协作成本高
```

### 根因

```
未统一代码规范，各项目自定规则
CI无规范检查，不规范代码合入主干
无自动格式化工具，手动调整费时费力
```

### 解决方案

```xml
<!-- Checkstyle统一规范配置（checkstyle.xml） -->
<module name="Checker">
  <module name="TreeWalker">
    <module name="AvoidStarImport"/>
    <module name="UnusedImports"/>
    <module name="MemberName"/>  <!-- 成员变量命名：lowerCamelCase -->
    <module name="MethodName"/>   <!-- 方法命名：lowerCamelCase -->
    <module name="ConstantName"/> <!-- 常量命名：UPPER_CASE -->
  </module>
</module>
```

```javascript
// ESLint统一规范配置（.eslintrc.js）
module.exports = {
  root: true,
  env: { browser: true, node: true },
  extends: ['eslint:recommended'],
  rules: {
    'no-console': process.env.NODE_ENV === 'production' ? 'error' : 'warn',
    'no-unused-vars': ['error', { vars: 'all', args: 'none' }],
  },
};
```

**统一规范关键**：
- 根目录放置统一规范配置文件，所有子项目继承
- CI中加入规范检查门禁，不通过不允许合入
- 配合IDE插件（Checkstyle-IDEA、ESLint插件）实时提示

---

## 涉及知识点

| 概念 | 所属域 | 关键点 |
|------|--------|--------|
| Lerna/Nx依赖管理 | 11_实战专题/48_Monorepo工程架构设计 | 依赖拓扑/变更影响分析 |
| Bazel增量构建 | 11_实战专题/48_Monorepo工程架构设计 | 内容哈希/远程缓存 |
| Protobuf代码生成 | 03_编程语言/02_Java/05_常用框架 | IDL定义/多语言生成 |
| Checkstyle/ESLint | 11_实战专题/49_代码质量平台设计 | 统一规范/CI门禁 |

---

## 排查 Checklist

```
□ 有依赖拓扑分析工具吗？ → Lerna/Nx识别变更影响
□ 支持增量构建吗？ → Bazel/Gradle增量编译+缓存
□ 接口定义用IDL吗？ → Protobuf/OpenAPI统一管理
□ 规范检查在CI中吗？ → Checkstyle/ESLint门禁
□ 禁止循环依赖吗？ → 依赖校验CI步骤
□ 生成代码纳入版本控制吗？ → 避免协作冲突
□ 有统一根配置吗？ → 规范配置放在Monorepo根目录
□ 构建缓存共享吗？ → Bazel Remote Cache/Gradle Build Cache
```

---

## 我的实战笔记

-（待补充，项目中的真实经历）
