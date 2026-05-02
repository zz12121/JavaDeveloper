# 商品SKU与价格管理设计

> 电商系统中，商品 SKU（Stock Keeping Unit）管理和价格策略是交易的核心。SKU 组合爆炸、多层级价格叠加、库存实时同步、价格计算一致性，每一点踩坑都是资损。

---

## 题目一：商品SKU与价格管理

### 业务背景

```
电商商品管理场景：

商品：iPhone 16 Pro
  ├── 颜色：暗夜紫 / 深空黑 / 白色 / 沙漠色
  ├── 存储：128GB / 256GB / 512GB / 1TB
  └── 版本：国行 / 港版
  → 4 × 4 × 2 = 32 个 SKU

核心问题：
  1. SKU 组合如何存储？笛卡尔积自动生成 vs 手动指定
  2. 价格层级：基础价 → 会员价 → 活动价 → 优惠券 → 最终价，怎么算不乱
  3. 库存与 SKU 绑定，库存扣减如何保证一致性
  4. 商品上下架时 SKU 状态联动
  5. SKU 数量爆炸（规格多时笛卡尔积可能上万）
  6. 价格变动的生效时间和版本控制
  7. 秒杀/拼团/预售等特殊价格场景
```

---

### 数据模型设计

#### 三层模型：SPU → 规格 → SKU

```
SPU（Standard Product Unit）—— 标准产品单元
  一个商品是一个 SPU，是用户认知维度上的"一个商品"
  例：iPhone 16 Pro

规格（Specification）
  SPU 的规格维度和可选值
  例：颜色=[暗夜紫, 深空黑, 白色, 沙漠色]
      存储=[128GB, 256GB, 512GB, 1TB]
      版本=[国行, 港版]

SKU（Stock Keeping Unit）—— 库存量最小单位
  每个 SKU 对应一种具体的规格组合 + 独立的价格 + 独立的库存
  例：iPhone 16 Pro 暗夜紫 256GB 国行
```

#### 表结构设计

```sql
-- SPU 表（标准产品单元）
CREATE TABLE product_spu (
    id              BIGINT PRIMARY KEY AUTO_INCREMENT,
    spu_no          VARCHAR(32) NOT NULL COMMENT 'SPU编号（业务唯一）',
    spu_name        VARCHAR(256) NOT NULL COMMENT '商品名称',
    category_id     BIGINT NOT NULL COMMENT '类目ID（三级类目）',
    brand_id        BIGINT COMMENT '品牌ID',
    main_image      VARCHAR(512) COMMENT '主图URL',
    status          TINYINT NOT NULL DEFAULT 1 COMMENT '1-上架 0-下架 2-删除',
    sales_volume    BIGINT DEFAULT 0 COMMENT '累计销量',
    create_time     DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    update_time     DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    UNIQUE KEY uk_spu_no (spu_no),
    INDEX idx_category (category_id),
    INDEX idx_status (status)
) COMMENT 'SPU表';

-- 规格模板表（定义有哪些规格维度）
CREATE TABLE product_spec_template (
    id          BIGINT PRIMARY KEY AUTO_INCREMENT,
    spu_id      BIGINT NOT NULL COMMENT '关联SPU',
    spec_name   VARCHAR(64) NOT NULL COMMENT '规格名称（如 颜色）',
    sort_order  INT NOT NULL DEFAULT 0 COMMENT '排序（颜色通常排第一）',
    is_required TINYINT DEFAULT 1 COMMENT '是否必选',
    INDEX idx_spu (spu_id)
) COMMENT '规格模板表';

-- 规格值表（每个规格维度的可选值）
CREATE TABLE product_spec_value (
    id              BIGINT PRIMARY KEY AUTO_INCREMENT,
    spec_template_id BIGINT NOT NULL COMMENT '关联规格模板',
    spec_value      VARCHAR(128) NOT NULL COMMENT '规格值（如 暗夜紫）',
    spec_image      VARCHAR(512) COMMENT '规格图片（颜色规格常用）',
    sort_order      INT DEFAULT 0,
    INDEX idx_template (spec_template_id)
) COMMENT '规格值表';

-- SKU 表（库存和价格的最小单元）
CREATE TABLE product_sku (
    id              BIGINT PRIMARY KEY AUTO_INCREMENT,
    sku_no          VARCHAR(64) NOT NULL COMMENT 'SKU编号',
    spu_id          BIGINT NOT NULL COMMENT '关联SPU',
    sku_name        VARCHAR(256) COMMENT 'SKU名称（如 iPhone 16 Pro 暗夜紫 256GB 国行）',
    spec_combo      VARCHAR(512) COMMENT '规格组合JSON {"颜色":"暗夜紫","存储":"256GB","版本":"国行"}',
    barcode         VARCHAR(64) COMMENT '条形码',
    price           DECIMAL(12,2) NOT NULL COMMENT '基础价格（原价）',
    cost_price      DECIMAL(12,2) COMMENT '成本价（不暴露给用户）',
    market_price    DECIMAL(12,2) COMMENT '市场价（划线价）',
    stock           INT NOT NULL DEFAULT 0 COMMENT '可用库存',
    locked_stock    INT NOT NULL DEFAULT 0 COMMENT '锁定库存（已下单未支付）',
    status          TINYINT DEFAULT 1 COMMENT '1-启用 0-禁用',
    weight          DECIMAL(10,2) COMMENT '重量(kg)',
    create_time     DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    update_time     DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    UNIQUE KEY uk_sku_no (sku_no),
    INDEX idx_spu (spu_id),
    INDEX idx_barcode (barcode)
) COMMENT 'SKU表';

-- 价格策略表（多层级价格）
CREATE TABLE product_price_strategy (
    id              BIGINT PRIMARY KEY AUTO_INCREMENT,
    sku_id          BIGINT NOT NULL,
    strategy_type   VARCHAR(32) NOT NULL COMMENT '价格类型：MEMBER/FLASH/SECKILL/GROUP/PRESELL',
    strategy_id     VARCHAR(64) COMMENT '关联策略ID（活动ID/会员等级ID）',
    price           DECIMAL(12,2) NOT NULL COMMENT '策略价格',
    start_time      DATETIME COMMENT '生效开始时间',
    end_time        DATETIME COMMENT '生效结束时间',
    stock_limit     INT COMMENT '活动库存限制',
    sold_count      INT DEFAULT 0 COMMENT '已售数量',
    status          TINYINT DEFAULT 1 COMMENT '1-启用 0-停用',
    create_time     DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_sku (sku_id),
    INDEX idx_type_time (strategy_type, start_time, end_time),
    INDEX idx_status_time (status, start_time, end_time)
) COMMENT '价格策略表';
```

#### SKU 组合生成策略

```java
/**
 * SKU 笛卡尔积生成器
 * 根据规格维度的可选值，自动生成所有 SKU 组合
 */
@Component
public class SkuCombinationGenerator {

    /**
     * 输入：[{specName:"颜色", values:["暗夜紫","深空黑"]}, {specName:"存储", values:["256GB","512GB"]}]
     * 输出：[{颜色:"暗夜紫", 存储:"256GB"}, {颜色:"暗夜紫", 存储:"512GB"},
     *        {颜色:"深空黑", 存储:"256GB"}, {颜色:"深空黑", 存储:"512GB"}]
     */
    public List<Map<String, String>> generate(List<SpecDimension> dimensions) {
        if (dimensions == null || dimensions.isEmpty()) {
            return Collections.emptyList();
        }

        List<Map<String, String>> result = new ArrayList<>();
        // 递归做笛卡尔积
        cartesian(dimensions, 0, new LinkedHashMap<>(), result);
        return result;
    }

    private void cartesian(List<SpecDimension> dimensions, int index,
                           Map<String, String> current, List<Map<String, String>> result) {
        if (index == dimensions.size()) {
            result.add(new LinkedHashMap<>(current));
            return;
        }
        SpecDimension dim = dimensions.get(index);
        for (String value : dim.getValues()) {
            current.put(dim.getSpecName(), value);
            cartesian(dimensions, index + 1, current, result);
            current.remove(dim.getSpecName());
        }
    }
}

/**
 * 批量创建 SKU 的业务服务
 */
@Service
public class SkuService {

    @Autowired
    private SkuCombinationGenerator generator;
    @Autowired
    private ProductSkuMapper skuMapper;

    /**
     * 创建商品时，根据规格自动生成 SKU
     * 也可以支持「手动选择SKU」模式（排除某些不需要的组合）
     */
    @Transactional
    public List<ProductSku> createSkus(Long spuId, List<SpecDimension> dimensions,
                                        List<Map<String, String>> excludeCombos,
                                        BigDecimal defaultPrice) {
        List<Map<String, String>> allCombos = generator.generate(dimensions);

        // 排除不需要的组合
        if (excludeCombos != null && !excludeCombos.isEmpty()) {
            allCombos.removeIf(combo -> excludeCombos.stream()
                    .anyMatch(ex -> ex.equals(combo)));
        }

        List<ProductSku> skuList = new ArrayList<>();
        for (Map<String, String> combo : allCombos) {
            ProductSku sku = new ProductSku();
            sku.setSpuId(spuId);
            sku.setSkuNo(generateSkuNo(spuId, combo));
            sku.setSkuName(buildSkuName(spuId, combo));
            sku.setSpecCombo(JSON.toJSONString(combo));
            sku.setPrice(defaultPrice);
            sku.setStock(0);
            sku.setStatus(1);
            skuMapper.insert(sku);
            skuList.add(sku);
        }

        // 防爆：如果笛卡尔积结果超过 1000，警告业务方
        if (allCombos.size() > 1000) {
            log.warn("SKU组合数量过大: spuId={}, count={}", spuId, allCombos.size());
        }

        return skuList;
    }

    private String generateSkuNo(Long spuId, Map<String, String> combo) {
        // 规格值取拼音首字母 + hash，保证唯一性
        String specHash = combo.values().stream()
                .map(s -> s.substring(0, Math.min(2, s.length())))
                .collect(Collectors.joining(""));
        return String.format("SKU%d%s%04d", spuId, specHash,
                (int) (Math.random() * 10000));
    }
}
```

---

### 多层级价格计算引擎

#### 价格叠加优先级

```
用户看到的价格 = 经过多层叠加后的最终价

优先级从高到低：
  1. SKU 级活动价（秒杀/拼团/限时折扣）→ 最高优先级
  2. SKU 级会员价 → 会员等级对应的专属价
  3. SKU 级基础价（商品原价）→ 兜底

叠加顺序：
  SKU基础价 → 减去会员折扣 → 减去活动优惠 → 减去优惠券
  注意：会员价和活动价通常「取最低」，不是叠加减
  优惠券在最后一步减（可以和活动叠加）
```

#### 价格计算服务

```java
@Service
public class PriceCalculator {

    @Autowired
    private ProductSkuMapper skuMapper;
    @Autowired
    private PriceStrategyMapper priceStrategyMapper;
    @Autowired
    private MemberService memberService;
    @Autowired
    private CouponService couponService;

    /**
     * 计算商品的最终展示价格
     * @param skuId        SKU ID
     * @param userId       用户ID（可为空，游客）
     * @param couponId     用户选择的优惠券（可为空）
     */
    public PriceResult calculate(Long skuId, Long userId, Long couponId) {
        ProductSku sku = skuMapper.selectById(skuId);
        BigDecimal originalPrice = sku.getPrice();

        // 第 1 步：获取当前有效的活动价（取最低）
        BigDecimal activityPrice = getActivityPrice(skuId);

        // 第 2 步：获取会员价
        BigDecimal memberPrice = getMemberPrice(skuId, userId);

        // 第 3 步：确定基准价 = min(原价, 活动价, 会员价)
        BigDecimal basePrice = originalPrice;
        if (activityPrice != null && activityPrice.compareTo(basePrice) < 0) {
            basePrice = activityPrice;
        }
        if (memberPrice != null && memberPrice.compareTo(basePrice) < 0) {
            basePrice = memberPrice;
        }

        // 第 4 步：计算优惠券抵扣
        BigDecimal couponDiscount = BigDecimal.ZERO;
        if (couponId != null) {
            couponDiscount = couponService.calculateDiscount(couponId, basePrice);
        }

        // 最终价 = 基准价 - 优惠券（不低于0）
        BigDecimal finalPrice = basePrice.subtract(couponDiscount);
        if (finalPrice.compareTo(BigDecimal.ZERO) < 0) {
            finalPrice = BigDecimal.ZERO;
        }

        return new PriceResult(originalPrice, activityPrice, memberPrice,
                couponDiscount, finalPrice);
    }

    /**
     * 获取 SKU 当前有效的活动价（可能多个活动重叠，取最低）
     */
    private BigDecimal getActivityPrice(Long skuId) {
        List<ProductPriceStrategy> strategies = priceStrategyMapper
                .findActiveBySku(skuId, LocalDateTime.now());

        return strategies.stream()
                .map(ProductPriceStrategy::getPrice)
                .min(BigDecimal::compareTo)
                .orElse(null);
    }

    /**
     * 获取会员价
     */
    private BigDecimal getMemberPrice(Long skuId, Long userId) {
        if (userId == null) return null;
        MemberLevel level = memberService.getMemberLevel(userId);
        if (level == null) return null;

        return priceStrategyMapper.findMemberPrice(skuId, level.getCode(),
                LocalDateTime.now());
    }
}
```

#### 价格缓存与预热

```java
/**
 * 商品价格缓存
 * 价格是高频读取（商品详情页 QPS 非常高），必须缓存
 */
@Service
public class PriceCacheService {

    @Autowired
    private RedisTemplate<String, Object> redisTemplate;
    @Autowired
    private ProductSkuMapper skuMapper;
    @Autowired
    private PriceStrategyMapper priceStrategyMapper;

    private static final String SKU_PRICE_KEY = "sku:price:";
    private static final int EXPIRE_HOURS = 2;

    /**
     * 获取 SKU 价格（缓存优先）
     */
    public BigDecimal getSkuPrice(Long skuId) {
        String key = SKU_PRICE_KEY + skuId;
        BigDecimal price = (BigDecimal) redisTemplate.opsForValue().get(key);
        if (price != null) {
            return price;
        }

        // 缓存未命中，查 DB
        BigDecimal dbPrice = skuMapper.selectById(skuId).getPrice();
        redisTemplate.opsForValue().set(key, dbPrice, EXPIRE_HOURS, TimeUnit.HOURS);
        return dbPrice;
    }

    /**
     * 商品上架时预热价格缓存
     * 批量查询该 SPU 下所有 SKU 的价格，写入 Redis
     */
    public void warmUpPriceCache(Long spuId) {
        List<ProductSku> skus = skuMapper.selectBySpuId(spuId);
        for (ProductSku sku : skus) {
            redisTemplate.opsForValue().set(
                    SKU_PRICE_KEY + sku.getId(),
                    sku.getPrice(),
                    EXPIRE_HOURS, TimeUnit.HOURS);
        }
        log.info("价格缓存预热完成: spuId={}, skuCount={}", spuId, skus.size());
    }

    /**
     * 价格变更时删除缓存（让下次查询时重建）
     * 不要更新缓存，用失效模式避免缓存和DB不一致的时间窗口
     */
    public void evictPriceCache(Long skuId) {
        redisTemplate.delete(SKU_PRICE_KEY + skuId);
        log.info("价格缓存失效: skuId={}", skuId);
    }

    /**
     * 活动价格到期时，使用 Redis 过期时间自动失效
     */
    public void cacheActivityPrice(Long skuId, Long strategyId, BigDecimal price,
                                    LocalDateTime endTime) {
        String key = "sku:activity:" + skuId + ":" + strategyId;
        long ttlSeconds = ChronoUnit.SECONDS.between(LocalDateTime.now(), endTime);
        if (ttlSeconds > 0) {
            redisTemplate.opsForValue().set(key, price, ttlSeconds, TimeUnit.SECONDS);
        }
    }
}
```

---

### 库存管理与扣减

#### 库存模型

```
SKU 库存字段：
  stock          可用库存（当前可售卖数量）
  locked_stock   锁定库存（已下单未支付的数量）

关系：
  实际库存总量 = stock + locked_stock

库存流转：
  下单 → stock -= 1, locked_stock += 1  （锁定库存）
  支付成功 → locked_stock -= 1          （扣减库存）
  取消/超时 → stock += 1, locked_stock -= 1（释放库存）
```

#### 库存扣减代码

```java
@Service
public class StockService {

    @Autowired
    private ProductSkuMapper skuMapper;
    @Autowired
    private RedisTemplate<String, String> redisTemplate;
    @Autowired
    private StringRedisTemplate stringRedisTemplate;

    /**
     * 库存扣减 —— Redis 原子操作 + DB 异步落盘
     * 适用于高并发场景（秒杀、抢购）
     */
    public boolean deductStock(Long skuId, int quantity) {
        String stockKey = "sku:stock:" + skuId;
        String lockedKey = "sku:locked:" + skuId;

        // 第一步：Redis 原子扣减
        Long remainStock = redisTemplate.opsForValue().increment(stockKey, -quantity);
        if (remainStock == null || remainStock < 0) {
            // 库存不足，回补
            redisTemplate.opsForValue().increment(stockKey, quantity);
            return false;
        }

        // Redis 锁定库存 +1
        redisTemplate.opsForValue().increment(lockedKey, quantity);

        // 第二步：发送消息异步扣减 DB
        mqTemplate.send("stock:deduct", new StockDeductMsg(skuId, quantity));

        return true;
    }

    /**
     * DB 层库存扣减（消息消费者调用）
     * 用乐观锁防止超扣
     */
    @Transactional
    public void deductStockInDb(Long skuId, int quantity) {
        int rows = skuMapper.deductStock(skuId, quantity);
        if (rows == 0) {
            log.error("库存扣减失败(DB), skuId={}, quantity={}", skuId, quantity);
            // 触发告警 + 人工对账
        }
    }

    /**
     * 释放库存（订单取消/超时）
     */
    public void releaseStock(Long skuId, int quantity) {
        // Redis 回补
        redisTemplate.opsForValue().increment("sku:stock:" + skuId, quantity);
        redisTemplate.opsForValue().increment("sku:locked:" + skuId, -quantity);

        // DB 异步释放
        mqTemplate.send("stock:release", new StockReleaseMsg(skuId, quantity));
    }
}

// Mapper 中的乐观锁扣减 SQL
@Mapper
public interface ProductSkuMapper {

    @Update("UPDATE product_sku SET stock = stock - #{quantity}, " +
            "locked_stock = locked_stock + #{quantity} " +
            "WHERE id = #{skuId} AND stock >= #{quantity}")
    int deductStock(@Param("skuId") Long skuId, @Param("quantity") int quantity);

    @Update("UPDATE product_sku SET stock = stock + #{quantity}, " +
            "locked_stock = locked_stock - #{quantity} " +
            "WHERE id = #{skuId} AND locked_stock >= #{quantity}")
    int releaseStock(@Param("skuId") Long skuId, @Param("quantity") int quantity);
}
```

#### 库存同步（Redis ↔ DB）

```
库存同步问题：
  Redis 中的库存和 DB 可能不一致（Redis 扣了但 DB 消息丢失/消费失败）

解决方案：
  1. 本地消息表：DB 扣库存操作写入本地消息表，MQ 消费成功后标记
     如果消息消费失败，定时任务重新投递

  2. 定时对账：每 5 分钟对比 Redis 和 DB 的库存差异
     SELECT sku_id, (stock + locked_stock) as total FROM product_sku
     对比 Redis 中 sku:stock:{skuId} + sku:locked:{skuId}
     差异超过阈值 → 告警 + 自动修复

  3. 活动库存独立管理
     秒杀等活动的库存不在 SKU 主库存中扣，走活动库存表
     避免活动库存和正常库存混淆
```

---

### 商品状态联动

```java
/**
 * SPU 状态与 SKU 状态联动管理
 */
@Service
public class ProductStatusService {

    @Autowired
    private ProductSpuMapper spuMapper;
    @Autowired
    private ProductSkuMapper skuMapper;
    @Autowired
    private RedisTemplate<String, Object> redisTemplate;

    /**
     * SPU 下架 → 所有 SKU 禁用
     */
    @Transactional
    public void offlineSpu(Long spuId) {
        spuMapper.updateStatus(spuId, 0);
        skuMapper.batchUpdateStatusBySpu(spuId, 0);

        // 清除所有 SKU 的价格缓存
        List<ProductSku> skus = skuMapper.selectBySpuId(spuId);
        for (ProductSku sku : skus) {
            redisTemplate.delete("sku:price:" + sku.getId());
        }
    }

    /**
     * 单个 SKU 禁用 → 检查是否所有 SKU 都禁用了 → SPU 也下架
     */
    @Transactional
    public void offlineSku(Long skuId) {
        ProductSku sku = skuMapper.selectById(skuId);
        skuMapper.updateStatus(skuId, 0);

        // 检查该 SPU 下是否还有可用的 SKU
        int activeCount = skuMapper.countActiveBySpu(sku.getSpuId());
        if (activeCount == 0) {
            spuMapper.updateStatus(sku.getSpuId(), 0);
            log.info("SPU自动下架（无可用SKU）: spuId={}", sku.getSpuId());
        }
    }
}
```

---

### 高频追问

#### Q1：SKU 数量爆炸怎么办？规格太多笛卡尔积上万

```
真实案例：服装类目
  颜色 20 种 × 尺码 10 种 = 200 SKU（可接受）
  但有些商品颜色 50 种 × 尺码 15 种 × 版型 3 种 = 22,500 SKU

解决方案：
1. 限制规格维度：最多 3 个维度，每个维度最多 30 个值
2. 不用笛卡尔积，改为「手动选择组合」模式
   运营在后台勾选实际存在的组合，而不是自动生成全部
3. 虚拟 SKU：不实际创建所有 SKU，用规格组合编码动态生成
   代价是库存管理复杂度上升
4. 分层管理：SPU 不变，但按「系列」分组 SKU
   同一系列共用大部分属性，只维护差异
```

#### Q2：如何保证价格计算在订单创建和支付回调时一致？

```
问题：
  下单时计算的价格是 100 元
  支付回调时活动结束，价格变成 120 元
  用户付了 100 元，但此时价格已变

解决方案：
1. 订单快照：下单时把最终价格写入订单表，后续不再重新计算
   order.product_price = 下单时的价格
   order.activity_price = 下单时的活动价
   订单金额 = 下单时计算好的金额，不随活动变化

2. 支付金额校验：
   支付回调时，只校验 order.total_amount == 支付金额
   不重新计算价格

3. 活动结束保护：
   活动到期前 N 分钟（如 5 分钟）自动标记「即将结束」
   前端不再展示活动价，新下单走原价
   但已经下单未支付的订单仍然享受活动价（通过订单快照保证）
```

#### Q3：商品改价如何防止并发问题？

```
问题：
  运营 A 改价格为 99 元
  运营 B 同时改为 89 元
  最终应该是什么？

解决方案：
1. 乐观锁：UPDATE product_sku SET price=#{price}, version=version+1
   WHERE id=#{skuId} AND version=#{version}
   失败则提示「数据已被他人修改，请刷新」

2. 价格变更审批：
   改价操作不是直接生效，走一个审批流程
   审批通过后才真正更新价格

3. 价格变更记录：
   product_price_history 表记录每次变更
   变更人、变更前、变更后、变更时间、变更原因
```

#### Q4：如何支持预售场景的库存管理？

```
预售场景：
  商品还没到货，但可以提前卖
  预售库存和实际库存是分开的

模型：
  stock           实物库存（到货后才有）
  presale_stock   预售库存（运营设置的预售数量）
  presale_sold    预售已售

  用户下单预售商品：
  presale_sold += 1
  到货后：
  stock += presale_stock
  预售订单转正常订单

实现：
  预售商品标记 presale = true，截止时间 presale_end_time
  到货后运营操作「预售转正式」，系统自动将预售库存转为正式库存
```

---

### 生产 Checklist

```
□ SKU 笛卡尔积生成是否有数量上限保护
□ 价格缓存失效策略是否用 delete 而非 update
□ 库存扣减是否有乐观锁防超卖
□ Redis 库存和 DB 库存是否有定时对账
□ 订单是否保存了价格快照（不依赖实时价格）
□ 多个活动价格重叠时是否取最低而非叠加
□ SKU 禁用后是否已下架所有关联的购物车/收藏
□ SPU 下架是否联动所有 SKU 下架 + 清缓存
□ 价格变更是否有操作日志和审批记录
□ 预售场景的库存模型是否和正常库存隔离
□ 商品规格值变更（如颜色名修改）是否更新了 SKU 名称
□ SKU 查询是否有组合索引 (spu_id, status) 支撑
```
