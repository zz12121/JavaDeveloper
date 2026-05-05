# 题目：ArrayList 是线程安全的吗？如何得到一个线程安全的 List？各种方式的本质区别是什么？

---

## ⚠️ 先盲答

**不要看任何资料，用自己的话回答，写到纸上或心里默念也行。**

---

## 盲答引导

1. ArrayList 在并发场景下会发生什么问题？是一定会抛异常，还是数据错了但没异常？
2. Vector 为什么是线程安全的？它有什么缺陷，为什么现在不推荐用？
3. `Collections.synchronizedList` 是怎么实现线程安全的？它和 Vector 本质区别在哪？
4. CopyOnWriteArrayList 的名字里 "CopyOnWrite" 是什么意思？读操作和写操作各有什么特点？
5. 如果有一个 `List<String>`，多个线程只做遍历（不修改），需要加锁吗？

---

## 知识链提示

这道题应该让你联想到：

- `ArrayList扩容机制` → 并发场景下扩容会导致什么
- `fail-fast机制` → ConcurrentModificationException 的本质
- `synchronized底层` → Vector / synchronizedList 的锁粒度
- `COW副本思想` → 读写分离，适合读多写少
- `并发集合对比` → 不同场景选哪个

---

## 核心追问

1. `synchronizedList` 包装后的 list，遍历的时候需要手动加锁吗？为什么？
2. CopyOnWriteArrayList 的写操作每次都会复制整个数组吗？代价多大？
3. Vector 的 `add` 和 `remove` 都加了 synchronized，为什么还说它不好？
4. 读多写少场景下，COWArrayList 比 synchronizedList 好在哪里？
5. 如果要在高并发下做一个"精确计数"的 List 统计，选哪个？

---

## 参考要点（盲答后再看）


**ArrayList 线程不安全的原因**：
- 多线程同时 add，可能覆盖元素（size 计算错误）
- 扩容期间另一个线程访问，可能读到 null 或越界
- fail-fast：遍历期间有修改，抛 ConcurrentModificationException（但不是保证一定抛）

**Vector**：方法级 synchronized，锁的是整个对象。效率低，且复合操作（如"先检查再添加"）仍然不安全。

**Collections.synchronizedList**：包装一层，每个方法加 synchronized(this.syncObject)。遍历仍需手动同步：
```java
synchronized (list) {
    for (Object o : list) { ... }
}
```

**CopyOnWriteArrayList**（重点）：
- 读：不加锁，直接读当前数组（volatile 保证可见性）
- 写：复制整个数组，修改后替换引用
- 适合：读多写极少（如白名单、监听器列表）
- 代价：内存占用高，写延迟高，数据不是实时一致的

**选型建议**：
| 场景 | 推荐 |
|------|------|
| 单线程 | ArrayList |
| 并发读多写少 | CopyOnWriteArrayList |
| 并发读写均衡 | synchronizedList 或 ConcurrentLinkedQueue（如果只需要队列）|


---

## 下一步

1. 盲答后，对比参考要点，找到卡壳的地方
2. 打开 `[[02_并发编程/06_并发容器/CopyOnWriteArrayList/CopyOnWriteArrayList]]` 和 `[[02_并发编程/06_并发容器/CopyOnWriteArrayList/CopyOnWriteArrayList]]` 主题文档，补充细节
3. 在 Obsidian 里建双向链接：`[[02_并发编程/06_并发容器/CopyOnWriteArrayList/CopyOnWriteArrayList]]` ←→ 本卡片
4. 在 `[[13_面试训练/03_每日一题/每日一题跟踪表]]` 里勾选「今日完成」，打 1~5 分
