# 题目：LinkedList 的底层是什么？Java 里队列和栈的正确实现方式有哪些？

---

## ⚠️ 先盲答

**不要看任何资料，用自己的话回答，写到纸上或心里默念也行。**

---

## 盲答引导

1. LinkedList 实现了哪几个接口？为什么它既能当 List 又能当 Queue？
2. LinkedList 的底层是单向链表还是双向链表？为什么这样设计？
3. `ArrayDeque` 和 `LinkedList` 都能当栈/队列用，选哪个？为什么？
4. Java 里有没有真正的 `Stack` 类？为什么现在不推荐用？
5. `PriorityQueue` 的底层是什么结构？它保证有序吗？

---

## 知识链提示

这道题应该让你联想到：

- `双向链表` → LinkedList 节点的 prev/next 指针
- `数组实现环形缓冲区` → ArrayDeque 的底层，比 LinkedList 更高效
- `栈与队列抽象` → Deque 接口统一了栈和队列
- `堆结构` → PriorityQueue 的二叉堆实现
- `Vector弃用原因` → Stack 继承 Vector 是设计失误

---

## 核心追问

1. LinkedList 的 `get(int index)` 时间复杂度是 O(n) 还是 O(1)？怎么优化的？
2. ArrayDeque 的扩容时机是什么？容量有什么要求（2的幂）？
3. PriorityQueue 的 `offer` 和 `poll` 各是什么时间复杂度？
4. 为什么 Stack 继承 Vector 被认为是错误的设计？（里氏替换原则）
5. 如果要实现一个线程安全的队列，选哪个：ConcurrentLinkedQueue 还是 LinkedBlockingQueue？

---

## 参考要点（盲答后再看）


**LinkedList 底层**：双向链表，每个节点有 prev/next 指针。
- 优点：插入删除 O(1)（已知节点位置）
- 缺点：随机访问 O(n)，内存开销大（每个节点多两个引用）

**队列/栈的正确选型**：

| 需求 | 推荐 | 底层 |
|------|------|------|
| 普通队列/双端队列 | `ArrayDeque` | 循环数组（效率最高） |
| 需要优先级 | `PriorityQueue` | 二叉堆 |
| 需要线程安全（非阻塞） | `ConcurrentLinkedQueue` | CAS + 链表 |
| 需要线程安全（阻塞） | `LinkedBlockingQueue` | ReentrantLock + 链表 |
| 栈（LIFO） | `ArrayDeque` + `push/pop` | 循环数组 |

**为什么不推荐 Stack**：
```java
// Stack 继承 Vector，所有方法都 synchronized，且继承了不需要的方法（如 insertElementAt）
public class Stack<E> extends Vector<E>  // 设计失误
```
正确做法：`Deque<Integer> stack = new ArrayDeque<>();`

**ArrayDeque vs LinkedList**：
- ArrayDeque：数组实现，缓存友好，无指针开销，默认容量16且必须2的幂
- LinkedList：每个元素都有节点对象开销，缓存不友好，但不需要扩容时复制


---

## 下一步

1. 盲答后，对比参考要点，找到卡壳的地方
2. 打开 `[[13_面试训练/01_题目知识链/01_Java核心/13_LinkedList与队列栈实现]]` 和 `ArrayDeque` 主题文档，补充底层结构
3. 在 Obsidian 里建双向链接：`[[02_并发编程/07_阻塞队列/阻塞队列]]` 关联学习
4. 在 `[[13_面试训练/03_每日一题/每日一题跟踪表]]` 里勾选「今日完成」，打 1~5 分
