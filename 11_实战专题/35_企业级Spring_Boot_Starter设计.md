# 企业级Spring Boot Starter设计

> Starter核心是自动配置 + 条件装配 + 健康监测。要做得好需考虑：隔离性、可配置性、可观测性。

---

## 企业级Starter全链路架构

```
企业级Starter架构
┌─────────────────┐
│  Spring Boot应用 │
└────────┬────────┘
         │ 引入Starter
         ▼
┌─────────────────┐
│  Starter模块     │
│  - 自动配置类    │
│  - 条件装配      │
│  - 配置属性      │
└────────┬────────┘
         │ 生效条件
         ▼
┌─────────────────┐
│  Spring上下文    │
│  - Bean注册      │
│  - 健康检查      │
└─────────────────┘
```

---

## 场景 A：自动配置原理

### 现象描述

Starter引入后未生效，定义的Bean未注册到Spring容器；自动配置类未被Spring扫描到，日志中无自动配置相关输出。自定义Starter在其他项目引入后不生效，无法使用。

### 根因分析

Spring Boot自动配置依赖`META-INF/spring/org.springframework.boot.autoconfigure.AutoConfiguration.imports`（Spring Boot 2.7+）或`META-INF/spring.factories`（旧版本）文件，未配置该文件导致自动配置类不被加载。自动配置类未被`@Conditional`注解修饰，无条件注册，可能导致Bean冲突。

### 解决方案

```java
// 1. 自动配置类示例（Redis Starter简化版）
import org.springframework.boot.autoconfigure.condition.ConditionalOnClass;
import org.springframework.boot.autoconfigure.condition.ConditionalOnMissingBean;
import org.springframework.boot.context.properties.EnableConfigurationProperties;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;

@Configuration
@ConditionalOnClass(RedisTemplate.class) // Redis类存在才生效
@EnableConfigurationProperties(RedisProperties.class) // 绑定配置属性
public class RedisAutoConfiguration {
    
    @Bean
    @ConditionalOnMissingBean // 用户未定义时才注册
    public RedisTemplate<String, Object> redisTemplate(RedisProperties properties) {
        RedisTemplate<String, Object> template = new RedisTemplate<>();
        template.setConnectionFactory(new JedisConnectionFactory(properties.getHost(), properties.getPort()));
        return template;
    }
}

// 2. Spring Boot 2.7+ 配置文件：META-INF/spring/org.springframework.boot.autoconfigure.AutoConfiguration.imports
// com.example.redis.RedisAutoConfiguration

// 3. 配置属性类
import org.springframework.boot.context.properties.ConfigurationProperties;

@ConfigurationProperties(prefix = "example.redis")
public class RedisProperties {
    private String host = "localhost";
    private int port = 6379;
    // getter/setter
}
```

---

## 场景 B：条件装配

### 现象描述

Starter在测试环境不应该生效（如连接生产Redis），但还是注册了Bean；`@ConditionalOnProperty`未生效，配置不存在时依然注册Bean。多个条件装配注解组合使用时逻辑混乱，不符合预期。

### 根因分析

条件装配注解使用错误：如`@ConditionalOnProperty`的`havingValue`未匹配配置值；条件注解逻辑组合错误（如同时用`@ConditionalOnClass`和`@ConditionalOnMissingClass`导致矛盾）。未理解条件装配的生效时机（在Bean定义阶段判断，而非运行时）。

### 解决方案

```java
// 1. 条件装配组合示例：只有当Redis类存在且配置example.redis.enabled=true时才生效
@Configuration
@ConditionalOnClass(RedisTemplate.class)
@ConditionalOnProperty(prefix = "example.redis", name = "enabled", havingValue = "true", matchIfMissing = false)
public class ConditionalRedisConfig {
    
    @Bean
    @ConditionalOnMissingBean
    public RedisService redisService(RedisProperties properties) {
        return new RedisService(properties.getHost(), properties.getPort());
    }
}

// 2. 自定义条件注解：仅在生产环境生效
import org.springframework.context.annotation.Condition;
import org.springframework.context.annotation.ConditionContext;
import org.springframework.core.type.AnnotatedTypeMetadata;

public class ProductionOnlyCondition implements Condition {
    @Override
    public boolean matches(ConditionContext context, AnnotatedTypeMetadata metadata) {
        String env = context.getEnvironment().getProperty("spring.profiles.active");
        return "prod".equals(env); // 仅生产环境生效
    }
}

// 3. 使用自定义条件
@Configuration
@Conditional(ProductionOnlyCondition.class)
public class ProdOnlyConfig {
    // 仅生产环境注册的Bean
}
```

---

## 场景 C：健康监测

### 现象描述

Starter没有提供健康检查，K8s存活/就绪探针探测失败，导致Pod反复重启；Starter相关指标（如连接数、请求数）未暴露，Prometheus无法采集，监控盲区。

### 根因分析

未实现`HealthIndicator`接口并注册为Bean，Spring Boot Actuator无法检测到Starter健康状态；未使用Micrometer暴露Metrics指标，监控平台无相关数据。健康检查逻辑未覆盖核心依赖（如Redis连接是否可用）。

### 解决方案

```java
// 1. 自定义健康检查指示器
import org.springframework.boot.actuate.health.Health;
import org.springframework.boot.actuate.health.HealthIndicator;
import org.springframework.stereotype.Component;

@Component
public class RedisHealthIndicator implements HealthIndicator {
    private final RedisTemplate<String, Object> redisTemplate;
    
    public RedisHealthIndicator(RedisTemplate<String, Object> redisTemplate) {
        this.redisTemplate = redisTemplate;
    }
    
    @Override
    public Health health() {
        try {
            // 检查Redis连接
            redisTemplate.execute((RedisCallback<String>) connection -> {
                connection.ping();
                return "pong";
            });
            return Health.up().withDetail("host", redisProperties.getHost()).build();
        } catch (Exception e) {
            return Health.down(e).withDetail("error", e.getMessage()).build();
        }
    }
}

// 2. 暴露Metrics指标
import io.micrometer.core.instrument.MeterRegistry;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;

@Configuration
public class MetricsConfig {
    @Bean
    public RedisMetrics redisMetrics(MeterRegistry registry, RedisTemplate<String, Object> redisTemplate) {
        return new RedisMetrics(registry, redisTemplate);
    }
}

// Redis指标收集
public class RedisMetrics {
    public RedisMetrics(MeterRegistry registry, RedisTemplate<String, Object> redisTemplate) {
        // 注册连接数指标
        registry.gauge("redis.connections", redisTemplate, rt -> getConnectionCount());
    }
    
    private double getConnectionCount() {
        // 获取连接数逻辑
        return 10.0;
    }
}
```

---

## 场景 D：配置迁移

### 现象描述

老项目从XML配置迁移到Starter，原配置项（如`redis.host`）无法映射到Starter的`example.redis.host`；配置属性未做校验，设置无效值（如端口为负）导致启动失败，无友好提示。

### 根因分析

未做配置兼容，老配置项未被映射；配置属性未加JSR-303校验注解（如`@Min`、`@NotBlank`），无效值未提前校验报错。迁移时未提供迁移指南，用户不知道如何替换老配置。

### 解决方案

```java
// 1. 配置兼容：映射老配置项
import org.springframework.boot.context.properties.ConfigurationProperties;
import org.springframework.context.annotation.Bean;

@ConfigurationProperties(prefix = "example.redis")
public class CompatibleRedisProperties {
    private String host;
    
    // 兼容老配置redis.host
    @Bean
    public static CompatibleRedisProperties compatibleProperties(Environment environment) {
        CompatibleRedisProperties props = new CompatibleRedisProperties();
        // 先从新配置取，取不到取老配置
        String host = environment.getProperty("example.redis.host", 
                environment.getProperty("redis.host", "localhost"));
        props.setHost(host);
        return props;
    }
}

// 2. 配置校验：JSR-303注解
import javax.validation.constraints.Min;
import javax.validation.constraints.NotBlank;

@ConfigurationProperties(prefix = "example.redis")
public class ValidatedRedisProperties {
    @NotBlank(message = "host不能为空")
    private String host;
    
    @Min(value = 1024, message = "端口必须大于1024")
    private int port = 6379;
    
    // getter/setter
}

// 3. 开启配置校验
@Configuration
@EnableConfigurationProperties
@Validated // 开启校验
public class RedisAutoConfiguration {
    // 配置类
}
```

---

## 核心参数估算

| 参数项 | 估算值 | 说明 |
|--------|--------|------|
| Starter Jar大小 | < 1MB | 轻量级，无多余依赖 |
| 自动配置类数量 | 3-5个 | 按功能拆分 |
| 条件装配注解数 | 2-3个/配置类 | 保证按需生效 |
| 健康检查耗时 | < 100ms | 探测接口响应时间 |
| 配置属性数量 | 10-15个 | 核心配置项 |
| 监控指标数量 | 5-10个 | 连接数、请求数、错误率 |

---

## 涉及知识点

| 知识点 | 所属域 | 关键点 |
|--------|--------|--------|
| 自动配置 | 03_框架/02_Spring Boot | AutoConfiguration.imports、@EnableAutoConfiguration |
| 条件装配 | 03_框架/02_Spring Boot | @Conditional系列注解、自定义Condition |
| 健康监测 | 03_框架/02_Spring Boot | HealthIndicator、Actuator端点 |
| Metrics暴露 | 03_框架/02_Spring Boot | Micrometer、Prometheus集成 |
| 配置迁移 | 03_框架/02_Spring Boot | 配置兼容、JSR-303校验 |

---

## 排查 Checklist

```text
□ 自动配置是否生效？ → 查看日志：Positive matches包含Starter配置类
□ 条件装配是否正确？ → 检查@Conditional注解条件是否满足
□ 健康检查是否通过？ → 访问/actuator/health，检查Starter状态
□ 监控指标是否暴露？ → 访问/actuator/metrics，查看Starter指标
□ 配置是否兼容？ → 老配置项是否映射到新属性
□ 配置是否校验？ → 无效值启动时是否报错
□ Bean是否冲突？ → 用户自定义Bean时Starter是否不注册
□ 依赖是否隔离？ → Starter不传递多余依赖，避免冲突
□ 文档是否完整？ → 提供配置项说明、迁移指南
□ 测试是否覆盖？ → 单元测试、集成测试覆盖核心场景
```

---

## 追问链

### 追问 1：如何保证Starter隔离性？

> "三招：1. 依赖隔离：Starter的pom.xml不传递多余依赖，用`<optional>true</optional>`标记可选依赖；2. 包路径隔离：Starter的包路径与业务代码区分（如`com.example.starter`）；3. Bean隔离：用`@ConditionalOnMissingBean`避免覆盖用户定义的Bean。"

### 追问 2：Starter如何支持多版本共存？

> "两种方式：1. 条件装配：用`@ConditionalOnClass`判断版本（如Redis 2.x/3.x不同类），注册不同Bean；2. 模块化：拆分成starter-redis-2、starter-redis-3，用户按需引入。推荐第一种，更灵活。"

### 追问 3：企业级Starter还需要什么？

> "除了自动配置、条件装配、健康监测，还需要：1. 可观测性：暴露Metrics、日志（带TraceId）；2. 容错：内置重试、降级逻辑；3. 安全：敏感配置（如密码）加密存储；4. 文档：自动生成配置元数据（spring-configuration-metadata.json）。"

### 追问 4：Starter如何避免依赖冲突？

> "三原则：1. 最小化依赖：只依赖Spring Boot核心，不依赖具体实现（如Redis依赖用`redis.clients:jedis`可选）；2. 依赖范围：compile scope的依赖尽量可选；3. 依赖管理：Starter的pom继承自spring-boot-starter-parent，统一版本管理。"

---

## 我的实战笔记

-（待补充，项目中的真实经历）
