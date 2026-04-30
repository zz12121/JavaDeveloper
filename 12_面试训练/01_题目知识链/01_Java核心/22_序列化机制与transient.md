# 题目：Java 序列化是什么？transient 关键字有什么用？Serializable 接口里为什么没有任何方法？

---

## ⚠️ 先盲答

**不要看任何资料，用自己的话回答，写到纸上或心里默念也行。**

---

## 盲答引导

1. `Serializable` 接口为什么是空接口（没有方法）？它叫什么接口？
2. `transient` 修饰的字段，序列化和反序列化时会发生什么？
3. `serialVersionUID` 是干什么的？不写会有什么问题？
4. 静态变量（static）会被序列化吗？为什么？
5. 如果一个类里有个 `Object` 类型的字段，它指向的对象没实现 Serializable，序列化会怎样？

---

## 知识链提示

这道题应该让你联想到：

- `[[transient关键字]]` → 控制哪些字段不参与序列化
- `[[Externalizable]]` → 比 Serializable 更精细的控制
- `[[JSON序列化]]` → Jackson/Gson 和 Java 原生序列化的区别
- `[[分布式存储]]` → 对象需要序列化才能网络传输（Redis、RMI）
- `[[protobuf]]` → 跨语言、高性能的序列化方案

---

## 核心追问

1. 写出 `serialVersionUID` 的正确声明格式。不写时 JVM 自动生成，会有什么问题？
2. 如果一个类 A 的父类没有实现 Serializable，反序列化时父类的字段怎么初始化？
3. `writeObject` / `readObject` 方法（私有方法）为什么能被 `ObjectOutputStream` 调用？用了什么机制？
4. Java 原生序列化的效率问题在哪？为什么分布式系统常用 protobuf/thrift？
5. `ArrayList` 的 `elementData` 数组为什么用 `transient` 修饰？

---

## 参考要点（盲答后再看）

<details>
<summary>点击展开</summary>

**标记接口（Marker Interface）**：
- `Serializable`、`Cloneable`、`RandomAccess` 都是空接口
- 作用：给 JVM 一个"信号"，触发特定处理逻辑（反射检查 `instanceof Serializable`）

**序列化流程**：
```java
// 序列化
ObjectOutputStream oos = new ObjectOutputStream(new FileOutputStream("obj.bin"));
oos.writeObject(obj);  // obj 必须实现 Serializable

// 反序列化
ObjectInputStream ois = new ObjectInputStream(new FileInputStream("obj.bin"));
Object obj = ois.readObject();
```

**transient 的作用**：
- 修饰的字段**不参与**序列化
- 反序列化时，transient 字段取默认值（0 / null / false）
- 典型用法：`ArrayList.elementData`（数组容量可能比实际元素多，不需要全序列化）

**serialVersionUID（重要）**：
```java
private static final long serialVersionUID = 1L;  // 显式声明
```
- 不写：JVM 根据类结构自动生成，类稍有改动就变化 → 反序列化失败（InvalidClassException）
- 写了：类字段增加/减少，只要 UID 不变，兼容反序列化

**父类没实现 Serializable**：
- 反序列化时，父类字段通过**无参构造器**初始化（所以父类必须有可访问的无参构造器）
- 父类字段不会从序列化流里恢复

**私有 writeObject / readObject 的调用原理**：
```java
// ArrayList 里的写法
private void writeObject(java.io.ObjectOutputStream s) throws ... {
    s.defaultWriteObject();
    s.writeInt(size);  // 只序列化有效元素，不序列化整个数组
}
// ObjectOutputStream 用反射调用这个私有方法！（特例）
```

**Java 原生序列化的问题**：
| 问题 | 说明 |
|------|------|
| 效率低 | 文本形式，体积大 |
| 不安全 | 可反序列化任意类，造成远程代码执行漏洞 |
| 跨语言差 | 只有 Java 能读 |

替代方案：protobuf、Kryo、Jackson（JSON）

</details>

---

## 下一步

1. 盲答后，对比参考要点，找到卡壳的地方
2. 打开 `[[序列化]]` 主题文档，把 `writeObject/readObject` 的自定义序列化机制整理进去
3. 在 Obsidian 里建双向链接：`[[06_中间件/Redis序列化]]` 关联学习
4. 在 `[[12_面试训练/每日一题跟踪表]]` 里勾选「今日完成」，打 1~5 分
