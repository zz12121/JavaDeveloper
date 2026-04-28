# Maven依赖机制

## 这个问题为什么存在？

> 项目依赖 spring-core、spring-context、mybatis……每个库又依赖各自的库，一层套一层。问题是：**当同一个库出现多个版本时，用哪个？怎么解决版本冲突？**

Maven 通过依赖仲裁机制（传递依赖 + 版本冲突解决）自动处理这个问题。

## 它是怎么解决问题的？

### 依赖传递（Transitive Dependency）

```
A 依赖 B（B-1.0）
C 依赖 D（D-2.0）

B 也依赖 D（D-1.0）
```

Maven 自动把 B 和 D 下载到 A 的 classpath，叫**传递依赖**。如果 B 和 D 依赖的 D 版本不同，就产生**依赖冲突**。

### 依赖仲裁三原则

```
┌─────────────────────────────────────┐
│  原则1：最短路径优先（就近原则）      │
│  原则2：第一声明优先（同级）           │
│  原则3：显式声明优先（直接指定）       │
└─────────────────────────────────────┘
```

**原则1：最短路径优先**

```
A → B → C → D-1.0  (路径长度 3)
A → E → D-2.0     (路径长度 2)
→ 最终选用 D-2.0
```

**原则2：第一声明优先（同路径长度时）**

```xml
<dependency>
    <dependency>B</dependency>   <!-- 第一个声明，优先 -->
    <dependency>C</dependency>
</dependency>

B → D-1.0
C → D-2.0
→ 路径长度相同，用 B 的 D-1.0（因为 B 先声明）
```

**原则3：显式声明优先**

```xml
<dependency>
    <A/>
    <B/>
    <C/>
    <dependencyManagement>
        <dependency>D-3.0</dependency>  <!-- 显式指定，优先级最高 -->
    </dependencyManagement>
</dependency>
```

### `maven-dependency-plugin` 分析依赖树

```bash
# 查看依赖树
mvn dependency:tree

# 查看特定依赖
mvn dependency:tree -Dincludes=com.alibaba:fastjson

# 分析依赖冲突
mvn dependency:analyze
[WARNING] Used undeclared dependencies: XXX
[WARNING] Unused declared dependencies: YYY
```

### `dependencyManagement` 的作用

```xml
<dependencyManagement>
    <dependencies>
        <dependency>
            <groupId>com.alibaba</groupId>
            <artifactId>fastjson</artifactId>
            <version>1.2.83</version>  <!-- 统一版本管理 -->
        </dependency>
    </dependencies>
</dependencyManagement>

<!-- 子模块引用时，只需写 groupId + artifactId，不用写 version -->
<dependency>
    <groupId>com.alibaba</groupId>
    <artifactId>fastjson</artifactId>
    <!-- 不写 version，自动用 dependencyManagement 里的版本 -->
</dependency>
```

**作用**：在多模块项目中**统一版本**，防止子模块用了不同版本。

### Scope：依赖作用域

| Scope | 编译时可见 | 运行时可见 | 传递性 |
|---|---|---|---|
| `compile`（默认）| ✅ | ✅ | ✅ |
| `provided` | ✅ | ❌ | ❌（如 servlet-api，容器已提供）|
| `runtime` | ❌ | ✅ | ✅（如 JDBC 驱动）|
| `test` | ❌ | ❌ | ❌（仅测试代码可见）|
| `system` | ✅ | ❌ | ❌（系统路径，不推荐）|
| `import` | 仅在 dependencyManagement 中，用于导入 BOM | | |

### Maven Shade 插件：重打包解决冲突

当两个依赖**都有同一个库的不同版本**，且没有统一 BOM 可以控制版本时，用 shade 插件重打包：

```xml
<plugin>
    <groupId>org.apache.maven.plugins</groupId>
    <artifactId>maven-shade-plugin</artifactId>
    <configuration>
        <createDependencyReducedPom>false</createDependencyReducedPom>
        <relocations>
            <relocation>
                <pattern>com.google.guava</pattern>
                <shadedPattern>com.mycompany shaded.guava</shadedPattern>
            </relocation>
        </relocations>
    </configuration>
</plugin>
```

把 `com.google.guava` 重打包为 `com.mycompany.shaded.guava`，在类路径上消除冲突。

## 它和相似方案的本质区别是什么？

### Maven vs Gradle 依赖管理

| | Maven | Gradle |
|---|---|---|
| 配置格式 | XML | Groovy/Kotlin DSL |
| 依赖冲突解决 | 就近优先 + 声明顺序 | 默认最新版本，可配置策略 |
| BOM 支持 | dependencyManagement | dependencyManagement 同理 |
| 传递依赖 | 默认开启，可 exclusion | 默认开启，可 implementation |

Gradle 默认选**最新版本**，Maven 选**最短路径**。这是两者行为差异最大的地方。

## 正确使用方式

### `exclusion` 排除冲突依赖

```xml
<dependency>
    <groupId>com.alibaba</groupId>
    <artifactId>druid</artifactId>
    <version>1.2.8</version>
    <exclusions>
        <!-- 排除 druid 传递进来的 slf4j，用项目自己的版本 -->
        <exclusion>
            <groupId>org.slf4j</groupId>
            <artifactId>slf4j-api</artifactId>
        </exclusion>
    </exclusions>
</dependency>
```

### BOM（Bill of Materials）：统一版本管理

Spring Boot 的 `spring-boot-starter-parent` 就是 BOM：

```xml
<parent>
    <groupId>org.springframework.boot</groupId>
    <artifactId>spring-boot-starter-parent</artifactId>
    <version>2.7.0</version>
</parent>

<!-- 不用写版本号，自动用 parent 里定义的版本 -->
<dependency>
    <groupId>com.alibaba</groupId>
    <artifactId>fastjson</artifactId>
    <!-- 自动用 1.2.76，由 parent 管理 -->
</dependency>
```

## 边界情况和坑

### 类加载器隔离（Tomcat / OSGi）

Tomcat 的 `WEB-INF/lib` 有自己的类加载器，和 Maven 依赖完全隔离。**同一个 JVM 进程里，不同 Web 应用可以加载不同版本的同一个类**，不会冲突。

但如果两个 jar 包在**同一个 Web 应用的 classpath**，Maven 仲裁规则生效，只有一个版本能进 classpath。

### `optional` vs `exclusion`

```xml
<dependency>
    <groupId>org.projectlombok</groupId>
    <artifactId>lombok</artifactId>
    <version>1.18.24</version>
    <optional>true</optional>  <!-- 可选依赖：引用本项目的人不会自动传递这个依赖 -->
</dependency>
```

`optional`：本项目能用，但不会传递给下游。`exclusion`：传递了但主动排除。

### 依赖未声明却能编译通过

```bash
mvn dependency:analyze

[WARNING] Used undeclared dependencies found:
  --- org.apache.commons.lang3:commons-lang3:jar:3.12.0:compile
```

说明代码里用了这个类，但**没有在 pom.xml 里显式声明**，是其他依赖传递进来的。需要**显式声明**，否则哪天传递依赖没了，代码就编译不过。

## 我的理解

Maven 依赖冲突的解决是**机械规则**（路径最短 > 第一声明 > 显式声明），不难理解。真正麻烦的是**大型项目的依赖失控**——传递依赖层级太深，不知道哪个版本被谁带进来的。

面试高频追问：**shade 插件重打包原理**——把冲突的包重命名为新的包名，在 classpath 上"去重"。这相当于让 JVM 认为这是两个不同的包，从而绕过仲裁规则。
