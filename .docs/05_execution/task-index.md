# Task Index · 当前任务索引

> 类型：task-index ｜ 状态：active ｜ 更新：2026-09-22 ｜ 基线：HEAD `eb7a63c`
>
> 回答"当前有哪些原子任务文档、各自状态如何"。

---

## 当前状态

**已登记的 `TASK-NNN` 文档：1 份。**

| TASK | 标题 | 状态 | 优先级 | 角色 | 工作包 | 执行方案条目 | 运行时 ID | 证据 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| [TASK-001](./tasks/TASK-001-health-contract-gap.md) | 补齐健康判定契约的异常路径测试 | `ready` | P0 | C | W1 | 3.1.1 | 无 | E15 |

模板见 [`task-template.md`](./task-template.md)。

### 为什么只有 1 份，以及其余任务在哪里

本项目的**原子任务权威定义不在本目录**，而在既有执行方案：

**[`docs/plans/2026-09-17-evidence-driven-remaining-work.md`](../../docs/plans/2026-09-17-evidence-driven-remaining-work.md) §3.1–3.10**

| 项 | 数值 |
| --- | --- |
| 工作包 | 10 个（W1–W10） |
| 三级行为项（原子任务） | 58 项 |
| 每项粒度 | 2–15 分钟，`.a`~`.e` 五个四级动作 |
| 每项自带 | 证据编号（E0x）、角色归属、验收条件 |

即：**58 个原子任务已经存在且有验收条件，只有 1 项被拆成了独立文档。**

⚠️ **TASK-001 的拆解同时推翻了一个假设**：3.1.1 的实现与 4/7 场景测试**早已存在并通过**，
执行方案勾选框 `[ ]` 并不等于"未开始"。详见
[`tasks/TASK-001-health-contract-gap.md`](./tasks/TASK-001-health-contract-gap.md) §4 与
`../08_knowledge/lessons-learned.md` L-03。

**结论：其余 57 项同样不能凭勾选框判定进度，须逐项实测后再决定是否需要建 TASK 文档。**

---

## 迁移规则（当需要拆分任务文档时）

### 何时需要建 `TASK-NNN`

满足任一条件即需要：

1. 任务跨会话/跨执行体执行，需要独立上下文
2. 任务被 AI Agent 执行，需要明确的执行方案与关联字段（见
   `00_governance/document-standard.md` §5.3）
3. 任务需要独立评审与独立证据
4. 任务预计超过 5 个四级动作，无法在一条三级项内表达

### 命名与编号

```text
.docs/05_execution/tasks/TASK-NNN-<slug>.md
```

* `TASK-NNN`：三位数，稳定不变，不随标题变化
* 建议从 `TASK-001` 开始，按登记的先后顺序分配
* **必须**在任务文档 §2 写明对应的执行方案条目（如 `§3.2.2`）与运行时 `T-NNN`

### 登记流程

```text
从执行方案 §3.x.y 拆分出原子任务
  ↓
按 task-template.md 建 TASK-NNN 文档
  ↓
回填 §2 来源（Requirement / SOL / Plan / WP / ADR / E0x / T-NNN）
  ↓
在本索引登记一行
  ↓
更新 00_governance/document-index.md
```

---

## 任务登记表（模板）

| TASK | 标题 | 状态 | 优先级 | 角色 | 工作包 | 执行方案条目 | 运行时 ID | 证据 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| — | 暂无登记 | — | — | — | — | — | — | — |

---

## 状态统计

| 状态 | 数量 |
| --- | --- |
| draft | 0 |
| ready | 1（TASK-001） |
| in-progress | 0 |
| blocked | 0 |
| review | 0 |
| verified | 0 |
| completed | 0 |
| cancelled | 0 |

---

## 与 backlog 的关系

| 文档 | 回答的问题 |
| --- | --- |
| [`../02_requirements/backlog.md`](../02_requirements/backlog.md) | 有哪些工作、什么顺序、什么优先级 |
| 本文件 | 有哪些原子任务文档、各自状态 |
| 执行方案 §3 | 原子任务的权威定义与验收条件 |

**三者不重复承载任务正文。** Backlog 是顺序，本文件是任务文档索引，执行方案是定义。

---

## 更新规则

* 新增任务文档 → 本文件登记一行 + 更新状态统计 + 更新 `document-index.md`
* 任务状态变化 → 更新本文件对应行（状态写在任务文档 Front Matter，本文件同步）
* 任务完成 → 同步更新 `06_validation/` 证据 + `07_release/changelog.md`
* **不要通过移动文件表达状态**——路径固定，状态写 Front Matter
