# Decisions · ADR 索引（指针）

> 类型：decision ｜ 状态：pointer ｜ 更新：2026-09-22
>
> **ADR 正文的唯一权威来源是 [`docs/adr.md`](../../../docs/adr.md)。**
> 本文件只做编号索引，避免双份维护。

---

## 现有决策

| ID | 标题 | 状态 | 裁决日期 |
| --- | --- | --- | --- |
| ADR-010 | MVP UI 使用 Streamlit，核心代码不得依赖 Streamlit | **SUPERSEDED**（被 ADR-016 取代） | 2026-09-15 |
| ADR-016 | 前端 = Vue3 + Vite + Pinia，核心代码零前端依赖 | ACCEPTED | 2026-09-15 |
| ADR-017 | 端口定版：UI = 控制台 = 5000 | ACCEPTED | 2026-09-15 |
| ADR-018 | server.py 归属：控制台服务归角色 A | ACCEPTED | 2026-09-15 |
| ADR-019 | WebSocket 实时通道写入契约 v1.1 | ACCEPTED | 2026-09-15 |
| ADR-020 | UI 模式五值 + 调度模式二值，两个正交概念 | ACCEPTED | 2026-09-15 |
| ADR-021 | 派工默认命令 = 单次、非交互 | ACCEPTED | 2026-09-15 |
| ADR-022 | 边界划分：启动器/执行体/通知归 C，控制面与契约归 A | ACCEPTED | 2026-09-15 |
| ADR-023 | 项目名统一 AideanFleet | ACCEPTED | 2026-09-15 |

## 编号占用

| 编号 | 状态 |
| --- | --- |
| ADR-001 ~ ADR-012 | 源自 `初始设计/d7.md` 收敛建议 |
| ADR-015 | 源自 `初始设计/d9.md` |
| **ADR-013 / ADR-014** | **留空未占用 —— 不要占用** |
| ADR-016 起 | 实施阶段新增裁决（工作包 CORE-03 落盘，2026-09-15） |

**下一个可用编号：ADR-024。**

---

## ADR 模板（写入 `docs/adr.md` 时使用）

沿用既有写法：一句话结论 + 理由 + 裁决日期。

```markdown
## ADR-024：<决策标题>

- 状态：ACCEPTED / SUPERSEDED（指向替代者）
- 结论：<一句话结论>
- 理由：<为什么>
- 裁决日期：YYYY-MM-DD
```

如需更完整的结构（Options / Consequences / Rationale），使用：

````markdown
# ADR-NNN：决策标题

## 1. Context

## 2. Problem

## 3. Options
### Option A
### Option B
### Option C

## 4. Decision

## 5. Rationale

## 6. Consequences
### Positive
### Negative
### Risks

## 7. Status

proposed / accepted / rejected / superseded

## 8. Related

- REQ：
- SOL：
- PLAN：
- TASK：
- Architecture：
````

---

## ADR 生命周期

**重要决策不得通过覆盖旧内容来"修改历史"。**

```text
ADR-010  ──superseded──►  ADR-016
```

* 旧 ADR 标 `SUPERSEDED` 并**指向替代者**，保留原文与作废理由
* 不得删除旧 ADR
* 扩展只能"新增状态 / 新增迁移"，不得修改既有语义

本项目实例：ADR-010 被 ADR-016 取代，但"核心代码不得依赖前端框架"的边界原则被 ADR-016 **继承**。这是正确写法。

---

## Solution 与 ADR 的区别

| 文档 | 回答的问题 |
| --- | --- |
| ADR | 为什么做这个决策？考虑了哪些选项？ |
| Solution | 这个需求具体怎么实现？执行路径是什么？ |

两者服务不同问题，**不可合并**。Solution 存 [`../solutions/`](../solutions/)。
