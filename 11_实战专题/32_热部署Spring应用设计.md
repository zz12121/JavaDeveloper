# 热部署Spring应用设计

> Spring热部署核心：Restart vs Reload。DevTools用Restart（快），JRebel用Reload（真正热替换）。

---

## Spring热部署全链路架构

```
Spring热部署全链路架构
┌─────────────────┐
│  Spring Boot应用 │
│  - DevTools      │
│  - JRebel Agent  │
└────────┬────────┘
         │ 监听
         ▼
┌─────────────────┐
│  文件监听器      │
│  - 监听class文件 │
│  - 监听配置文件  │
└────────┬────────┘
         │ 触发
         ▼
┌─────────────────┐
│  热部署策略      │
│  ├─ Restart     │
│  └─ Reload      │
└─────────────────┘
```

---

## 场景 A：DevTools原理

### 现象描述

Spring DevTools热重启需要5-10秒，比预期慢；静态资源（HTML/CSS/JS）修改不生效；修改@Service类后，依赖该服务的@Controller未更新引用，抛出NullPointerException。

### 根因分析

DevTools使用两级ClassLoader：Base ClassLoader加载第三方依赖（不变），Restart ClassLoader加载应用类（可变）。重启时丢弃Restart ClassLoader并重新创建，但默认Base ClassLoader加载了过多类，导致重启慢。静态资源被浏览器缓存，未禁用缓存导致不生效。依赖持有旧ClassLoader加载的实例引用，重启后未更新。

### 解决方案

```java
// 1. DevTools配置优化（application.yml）
// spring:
//   devtools:
//     restart:
//       enabled: true
//       log-condition-evaluation-delta: false 关闭不必要的日志
//       quiet-period: 200 文件修改后等待200ms再重启（避免频繁重启）
//     livereload:
//       enabled: true 开启静态资源热更新
//   web:
//     resources:
//       cache:
//         period: 0 禁用静态资源缓存

// 2. Java代码：自定义Restart策略，缩小重启范围
import org.springframework.boot.devtools.restart.Restarter;
import org.springframework.context.ApplicationContextInitializer;
import org.springframework.context.ConfigurableApplicationContext;

public class DevToolsInitializer implements ApplicationContextInitializer<ConfigurableApplicationContext> {
    @Override
    public void initialize(ConfigurableApplicationContext applicationContext) {
        Restarter restarter = Restarter.getInstance();
        // 排除不需要重启的包（如第三方依赖、配置类）
        restarter.addExcludePath("com.example.config.**");
        restarter.addExcludePath("com.example.thirdparty.**");
    }
}
```

---

## 场景 B：JRebel方案

### 现象描述

DevTools修改方法签名（如新增参数）、新增类不生效，需要手动重启；JRebel启动时报错"License not found"，或Agent加载失败导致应用无法启动。JRebel热替换后部分类未更新，出现诡异bug。

### 根因分析

DevTools基于ClassLoader重启，无法修改已加载类的结构（方法签名、字段）；JRebel通过Java Instrumentation API修改JVM中的字节码，支持真正热替换，但需要有效的商业License。JRebel未正确配置监听路径，导致部分类未监控到。

### 解决方案

```java
// 1. JRebel启动参数（需要jrebel.jar和license）
// -javaagent:/path/to/jrebel.jar
// -Drebel.log=true 开启JRebel日志
// -Drebel.check_license=true 检查License有效性

// 2. JRebel配置文件（rebel.xml），指定监听路径
// <?xml version="1.0" encoding="UTF-8"?>
// <application xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" 
//             xmlns="http://www.zeroturnaround.com/alderaa/rebel/1.0">
//   <classpath>
//     <dir name="/path/to/classes"> 监听class文件变化
//     </dir>
//   </classpath>
// </application>

// 3. Java代码：检查JRebel是否生效
public class JRebelChecker {
    public static boolean isJRebelEnabled() {
        try {
            Class.forName("org.zeroturnaround.jrebel.agent.Main");
            return true;
        } catch (ClassNotFoundException e) {
            return false;
        }
    }
}
```

---

## 场景 C：限制和坑

### 现象描述

热部署后@Value注入的配置未更新，还是旧值；热部署后新增的@Bean未生效，Spring容器中不存在；热部署导致数据库连接池泄漏，连接数持续增长直到耗尽。

### 根因分析

配置是在上下文刷新时注入的，但部分类持有配置的直接引用（不是${}占位符），未重新注入；新增的@Bean所在的包未被Spring扫描到（扫描路径未包含）；热部署时未关闭旧的连接池，旧连接池中的连接仍然持有旧ClassLoader的引用，无法被GC回收。

### 解决方案

```java
// 1. 配置热更新解决方案：使用@RefreshScope（需要Spring Cloud）
import org.springframework.cloud.context.config.annotation.RefreshScope;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Component;

@RefreshScope // 配置更新时重新创建Bean
@Component
public class ConfigService {
    @Value("${app.timeout:1000}")
    private int timeout; // 配置更新后会重新注入
}

// 2. 新增Bean生效：手动触发Bean扫描
import org.springframework.context.ApplicationContext;
import org.springframework.context.annotation.ClassPathBeanDefinitionScanner;

public class BeanReloader {
    public static void reloadBeans(ApplicationContext context, String basePackage) {
        // 重新扫描指定包下的Bean
        ClassPathBeanDefinitionScanner scanner = new ClassPathBeanDefinitionScanner(
                (org.springframework.beans.factory.support.BeanDefinitionRegistry) context.getAutowireCapableBeanFactory());
        scanner.scan(basePackage);
    }
}

// 3. 连接池关闭：热部署前销毁旧连接池
import javax.sql.DataSource;
import org.springframework.context.ApplicationListener;
import org.springframework.context.event.ContextClosedEvent;

@Component
public class DataSourceCleaner implements ApplicationListener<ContextClosedEvent> {
    @Override
    public void onApplicationEvent(ContextClosedEvent event) {
        DataSource dataSource = event.getApplicationContext().getBean(DataSource.class);
        if (dataSource instanceof AutoCloseable) {
            try {
                ((AutoCloseable) dataSource).close(); // 关闭连接池
            } catch (Exception e) {
                e.printStackTrace();
            }
        }
    }
}
```

---

## 场景 D：生产不建议

### 现象描述

生产环境开启DevTools导致内存泄漏（Restart ClassLoader无法被GC）；JRebel Agent占用额外100MB+内存，增加启动时间；热部署失败后无法回滚，只能重启应用，导致服务不可用。

### 根因分析

生产环境类加载复杂，DevTools的Restart ClassLoader会持有大量类引用，无法被GC回收；JRebel Agent需要修改字节码，增加JVM启动时间和内存开销；热部署无原子性保证，失败后会留下半个上下文，只能重启。

### 解决方案

```java
// 1. 生产环境禁用热部署检查
import org.springframework.boot.SpringApplication;
import org.springframework.boot.env.EnvironmentPostProcessor;
import org.springframework.core.env.ConfigurableEnvironment;

public class ProductionHotDeployDisabler implements EnvironmentPostProcessor {
    @Override
    public void postProcessEnvironment(ConfigurableEnvironment environment, SpringApplication application) {
        String profile = environment.getProperty("spring.profiles.active");
        if ("prod".equals(profile)) {
            // 禁用DevTools
            System.setProperty("spring.devtools.restart.enabled", "false");
            // 移除JRebel Agent（如果存在）
            if (System.getProperty("jrebel.log") != null) {
                System.err.println("生产环境禁止JRebel，正在移除Agent...");
            }
        }
    }
}

// 2. 生产环境用蓝绿部署替代热部署
// 蓝绿部署流程：
// 1. 新版本部署到绿组，流量仍在蓝组
// 2. 健康检查通过后，切10%流量到绿组
// 3. 验证无问题，全量切流量到绿组
// 4. 蓝组保留作为回滚备份
```

---

## 核心参数估算

| 参数项 | 估算值 | 说明 |
|--------|--------|------|
| DevTools重启耗时 | 2-5秒 | 优化后，仅重启应用上下文 |
| JRebel热替换耗时 | < 500ms | 仅替换修改的类 |
| JRebel内存开销 | 100MB+ | Agent自身占用 |
| DevTools内存开销 | 50MB/重启 | Restart ClassLoader开销 |
| 支持热替换范围 | 方法体修改 | JRebel支持，DevTools不支持签名修改 |
| License成本 | $550/开发者/年 | JRebel商业授权 |

---

## 涉及知识点

| 知识点 | 所属域 | 关键点 |
|--------|--------|--------|
| Spring DevTools | 03_框架/02_Spring Boot | 两级ClassLoader、Restart机制、LiveReload |
| JRebel | 03_框架/02_Spring Boot | Instrumentation API、字节码替换、License管理 |
| 配置热更新 | 03_框架/03_Spring Cloud | @RefreshScope、配置中心推送、上下文刷新 |
| 连接池生命周期 | 05_数据库/02_连接池 | 关闭时机、旧连接回收、ClassLoader泄漏 |
| 蓝绿部署 | 07_架构设计/04_高可用 | 流量切换、回滚机制、健康检查 |

---

## 排查 Checklist

```text
□ DevTools是否优化？ → 排除不变包，缩小重启范围，静态资源禁用缓存
□ JRebel是否生效？ → 检查Agent加载日志，确认license有效
□ 配置是否更新？ → 使用@RefreshScope，或手动触发上下文刷新
□ 新增Bean是否生效？ → 确认包被扫描，或手动触发扫描
□ 连接池是否泄漏？ → 热部署前关闭旧连接池，监控连接数
□ 生产是否禁用？ → 生产profile下关闭DevTools和JRebel
□ 内存是否泄漏？ → 监控ClassLoader数量，Restart ClassLoader是否回收
□ 耗时是否合理？ → DevTools<5秒，JRebel<500ms
□ 回滚是否可行？ → 热部署失败可快速回滚，或预留旧版本
□ 静态资源是否更新？ → 开启LiveReload，禁用浏览器缓存
```

---

## 追问链

### 追问 1：DevTools和JRebel的核心区别是什么？

> "DevTools是Restart（重启应用上下文），JRebel是Reload（热替换字节码）。DevTools速度快但支持范围小（不支持方法签名修改），JRebel支持所有类型的修改但需要付费。开发环境用DevTools（免费），需要更强调剂用JRebel。"

### 追问 2：为什么JRebel能修改已加载的类？

> "JRebel使用Java Instrumentation API，在类加载时修改字节码，插入监控逻辑；当类文件变化时，通过Agent重新定义类（redefineClasses），替换方法体。但JRebel也不是万能的：修改类继承关系、字段增减仍然不支持，需要重启。"

### 追问 3：热部署后事务会失效吗？

> "可能。如果热部署替换了Service类的字节码，Spring的事务代理可能未更新，导致事务失效。解决方案：1. 热部署后手动触发事务代理重建；2. 使用JRebel时，确保事务相关的Bean也被重新加载；3. 重要业务场景避免热部署，走标准发布流程。"

### 追问 4：生产环境真的完全不能用热部署吗？

> "完全不能。生产环境要求高可用、可审计、可回滚，热部署都不满足：1. 无原子性，失败会搞坏上下文；2. 无审计日志，不知道改了什么；3. 无回滚机制，失败了只能重启。生产环境用蓝绿部署、金丝雀发布替代，热部署只用于开发/测试环境。"

---

## 我的实战笔记

-（待补充，项目中的真实经历）
