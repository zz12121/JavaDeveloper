# Redis 的数据结构有哪些？底层实现是什么？

> ⚠️ **先盲答**：Redis 支持哪些数据结构？它们底层分别用什么实现的？

---

## 盲答引导

1. Redis 有哪些数据结构？—— String/List/Hash/Set/ZSet + 3 种高级结构
2. String 的底层实现是什么？—— int / embstr / raw
3. List 在旧版本（Ziplist）和新版本（Quicklist）的区别是什么？
4. Hash 在什么情况下用 Ziplist，什么情况下用 Hashtable？

---

## 知识链提示

```
Redis 数据结构
  → [[07_中间件/01_Redis/Redis数据结构与底层实现]]
    → 五大基础结构
      → String
        → int（整数，直接存）
        → embstr（≤44字节，连续内存）
        → raw（>44字节，动态字符串 SDS）
      → List
        → Quicklist（Ziplist + LinkedList 的改良）
        → 旧版：Ziplist（小数据）/ LinkedList（大数据）
      → Hash
        → Ziplist（field 少 + value 小）
        → Hashtable（field 多或大）
      → Set
        → intset（全整数 + 元素少）
        → Hashtable
      → ZSet（有序集合）
        → Ziplist（元素少）
        → Skiplist + Hashtable（元素多）
    → 三种高级结构
      → Bitmap（String 的位操作）
      → HyperLogLog（基数估算，用于 UV）
      → Geo（地理位置，基于 ZSet）
    → 编码转换
      → 满足条件 → 编码从紧凑型（Ziplist/intset）升级为通用型（Hashtable/Skiplist）
```

---

## 核心追问

| 追问 | 考点 |
|------|------|
| 为什么 Redis 不都用 Hashtable？ | Ziplist/intset 内存更省，小数据场景更快 |
| SDS（Simple Dynamic String）相比 C 字符串有什么优势？ | O(1) 获取长度 / 二进制安全 / 减少内存重分配 |
| 为什么 ZSet 要用 Skiplist 而不是红黑树？ | 范围查询 Skiplist 更快（链表遍历） |
| Quicklist 是干什么的？ | 解决 ZipList 更新效率低的问题（改一个节点可能触发整个 Ziplist 重分配）|

---

## 参考答案要点

**五大结构 + 底层编码**：

| 数据结构 | 小数据编码 | 大数据编码 |
|---------|------------|------------|
| String | int / embstr | raw（SDS） |
| List | Ziplist（旧） | Quicklist（新）|
| Hash | Ziplist | Hashtable |
| Set | intset | Hashtable |
| ZSet | Ziplist | Skiplist + Hashtable |

**编码升级**：从小数据编码升级为大数据编码，且**不可逆**。

---

## 下一步

打开 [[07_中间件/01_Redis/Redis数据结构与底层实现]]，补充 `双向链接`：「Redis 的底层编码设计核心是『空间换时间』和『紧凑编码』——小数据用 Ziplist/intset，省内存；大数据升级为通用结构，保性能」。
