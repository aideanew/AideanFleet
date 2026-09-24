# Backlog · 待办池

> 类型：backlog ｜ 状态：active ｜ 更新：2026-09-22 ｜ 基线：HEAD `eb7a63c`
>
> 回答"当前有哪些待处理工作、状态和顺序如何"。
> **本文件不承载需求正文**——正文见 [`product-requirements.md`](./product-requirements.md) 与任务文件。

---

## 1. 数据口径说明

本表来自 [`docs/plans/2026-09-17-evidence-driven-remaining-work.md`](../../docs/plans/2026-09-17-evidence-driven-remaining-work.md)
§3.1–3.10 的逐项勾选状态统计（核验命令见下方"核验命令"节）。

**核验事实**：

| 项 | 数值 |
| --- | --- |
| 工作包（W） | 10 个（W1–W10） |
| 三级原子任务 | 58 项 |
| 已勾选完成 | **0 项** |
| 未勾选 | 58 项 |

> ⚠️ 注意：勾选数为 0 **不等于**没有进展。执行方案的 §5 明确记录了本轮已完成项
> （新增集成测试已通过、选择回归 77 passed、前端类型检查最终复检通过）。
> 勾选框只反映该文件的编辑状态，**实际进度以 `reports/` 证据与 §5 记录为准**。

---

## 2. 工作包待办表

| ID | 名称 | 优先级 | 角色 | 三级任务数 | 依赖 | 状态 |
| --- | --- | --- | --- | --- | --- | --- |
| W1 | 可信启动与可用控制台 | P0 | B/C 并行 | 5 | — | 🚧 Ready |
| W2 | 唯一调度者与严格人工控制 | P0 | A | 7 | —（并发扩展的前置） | 🚧 Ready |
| W3 | 状态、事件与计划一致性 | P0 | A | 5 | W2 数据模型 | ⏳ Backlog |
| W4 | 需求驱动规划和变更闭环 | P1 | A | 6 | W2/W3 | ⏳ Backlog |
| W5 | 可信验收与不可混淆的执行证据 | P0/P1 | A/C | 6 | W2 attempt | ⏳ Backlog |
| W6 | 计量、预算、审批真正进入执行路径 | P0/P1 | A | 6 | W2/W3 | ⏳ Backlog |
| W7 | 恢复、通知与可观察生命周期 | P1 | C/A | 6 | W2/W3 | ⏳ Backlog |
| W8 | 真实扩展能力与控制面边界 | P1 | A/B/C | 5 | — | ⏳ Backlog |
| W9 | 有界高性能与前端真实反馈 | P1/P2 | A/B | 6 | W2/W3/W5 | ⏳ Backlog |
| W10 | 独立验收与可复现发布 | P2 | A/B/C | 6 | 全部发布范围任务 | ⏳ Backlog |

**排序原则（来自执行方案 §3 标题）**：先正确性（W1–W3），再能力（W4–W8），再性能（W9–W10）。

---

## 3. 已完成的批次（已交付，不再进 Backlog）

| 批次 | 内容 | 证据 |
| --- | --- | --- |
| CORE-02 | 控制面核心 | `../../reports/CORE-02-evidence.md` |
| CORE-03 | 契约复核 + ADR-016~023 落盘 | `../../reports/CORE-03-evidence.md` |
| CORE-04 | 上下文成本三扩展列 + Project Memory | `../../reports/CORE-04-evidence.md` |
| FE-01 | 网页控制端 v1.0（Vue3/Vite/Pinia 深色科技风） | `../../reports/FE-01-evidence.md` |
| GOV-01 | 治理层（usage/budget/approval），后已挂载 HTTP 面 | `../../reports/GOV-01-evidence.md` |
| INT-02 / INT-03 / INT-04 | 集成与工作流 | `../../reports/INT-02-evidence.md`、`INT-03`、`INT-04` |
| REL-01 | 发布 | `../../reports/REL-01-evidence.md`（Phase2 清单记载已确认存在） |

⚠️ **未交付项**：`reports/INT-04R-evidence.md` 缺失。
[`docs/验收清单-Phase2.md`](../../docs/验收清单-Phase2.md) 同样记载该项缺失。已核验 `ls` 确认不存在。

---

## 4. 状态定义

| 状态 | 含义 |
| --- | --- |
| Proposed | 已提出，待评估 |
| Backlog | 已评估，待排期 |
| Ready | 条件齐全，可执行 |
| In Progress | 正在执行 |
| Done | 已完成并验证 |
| Icebox | 暂缓 |
| Rejected | 已拒绝 |

---

## 5. 核验命令

```bash
# 三级任务总数
grep -cE '^- \[ \] \*\*[0-9]+\.[0-9]+\.[0-9]+' docs/plans/2026-09-17-evidence-driven-remaining-work.md

# 已勾选数
grep -cE '^- \[x\]' docs/plans/2026-09-17-evidence-driven-remaining-work.md

# 工作包清单
grep -nE '^### 3\.[0-9]+ W[0-9]+' docs/plans/2026-09-17-evidence-driven-remaining-work.md
```

---

## 6. 更新规则

* 本表是**指针型汇总**，不替代执行方案。执行方案的三级编号是原子任务的权威位置。
* 任务实际开始执行 → 在 `../05_execution/tasks/` 建 `TASK-NNN` 文档，并回填 `T-NNN` 对应关系。
* 任务完成 → 更新 `../05_execution/task-index.md` + 保存 `reports/` 证据 + 更新 `../07_release/changelog.md`。
* 需求变化 → 先更新 `product-requirements.md`，再调整本表顺序。
