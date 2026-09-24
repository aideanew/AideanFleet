# 原子任务模板 · TASK-TEMPLATE

> 类型：task-template ｜ 状态：active ｜ 建立：2026-09-22
>
> 复制本文件为 `tasks/TASK-NNN-<slug>.md` 后填写。
> **状态写 Front Matter，不通过移动文件表达状态。**

---

## 原子任务判定（八条，全中才合格）

1. 有明确目标
2. 有明确输入
3. 有明确输出
4. 有明确验收条件
5. 有明确验证方法
6. 有明确依赖
7. 可以判断完成与否
8. 不应继续拆成多个彼此独立的交付结果

**粒度口径**：单动作 2–15 分钟。超出说明还不够原子，继续分解。
不承诺未经估算的项目天数。

---

## 模板正文

````markdown
---
id: TASK-001
type: task
title: 任务标题
status: draft          # draft / ready / in-progress / blocked / review / verified / completed / cancelled
priority: P0
role: A                # A=控制面核心与契约 / B=前端 / C=启动器执行体通知
work_package: W1
created: 2026-09-22
updated: 2026-09-22
owner:
reviewer:
---

# TASK-001：任务标题

## 1. 基本信息

- ID：TASK-001
- 类型：
- 状态：draft
- Owner：
- Reviewer：
- 创建时间：
- 更新时间：

## 2. 来源（双向追溯，必填）

- Requirement：REQ-F-NNN（或"候选组 N，见 product-requirements.md"）
- Solution：SOL-NNN
- Plan：`../../docs/plans/2026-09-17-evidence-driven-remaining-work.md` §3.x.y
- Work Package：W1
- Decision：ADR-NNN
- Evidence Ref：E0x（证据索引编号）
- **运行时任务 ID：T-NNN**（SQLite `tasks.task_id`；无则写"待创建"）

> `TASK-NNN`（文档层）与 `T-NNN`（运行时）**是两套 ID，禁止混用**。
> 这里显式写出对应关系，是本任务可被双向追溯的关键。

## 3. 目标

本任务完成后，应产生什么明确结果？（一句话，可验证）

## 4. 背景

为什么需要这个任务？引用证据编号与代码位置。

## 5. 输入

### 文档输入

- Solution / ADR / 契约 / 证据

### 前置条件

- 依赖的任务、依赖的外部服务、依赖的配置

### 已知约束

- 来自 ADR 与 FROZEN 契约的硬约束（**不得擅自修改**）

## 6. 输出

任务完成后必须产生哪些交付物？

- 代码变更：`fleet/...`（列出具体文件）
- 测试：`tests/...`
- 文档同步：
- 证据：`reports/...`

## 7. Execution Steps

按既有统一原子执行规则，**五个四级动作**（沿用执行方案 §3.0）：

- [ ] `.a` 增加一个行为测试，描述本任务的目标行为
- [ ] `.b` 运行该测试并记录真实结果（已有该行为则记录通过，**不造红灯**）
- [ ] `.c` 最小实现
- [ ] `.d` 运行目标测试及相关回归
- [ ] `.e` 同步契约 / 证据 / 文档，并提交独立评审

若本任务无法拆成上述五步，说明它不是原子任务，需要重新拆分。

补充执行说明（如需）：

- Step N：<具体操作>

## 8. Acceptance Criteria

- [ ] <验收条件 1>
- [ ] <验收条件 2>
- [ ] <验收条件 3>

每条验收条件必须可客观判定，避免"更健壮""更清晰"这类不可验证表述。

## 9. Verification

说明**如何证明**任务已经完成。必须给出可执行命令：

```bash
# 示例
pytest tests/core/test_xxx.py -q
pytest tests -q
```

预期结果：

```text
示例：N passed / 0 failed
```

## 10. Evidence

完成后必须提供可检查的证据：

- 测试结果：
- 输出文件 / 截图 / 日志：
- Commit：
- 证据目录：`reports/<WORK-PACKAGE>-evidence.md` 或 `.docs/06_validation/evidence/EVD-NNN/`

## 11. Dependencies

### Depends On

- TASK-NNN / T-NNN

### Blocks

- TASK-NNN

## 12. Risks

-

## 13. Blocked Rules

遇到以下情况**不得自行假设**，必须置 `status: blocked`：

- 需求冲突
- 核心设计冲突
- 缺失必要输入
- 超出任务范围
- 无法满足验收标准
- 关键依赖不可用
- **与 FROZEN 契约或既有 ADR 语义冲突**（契约与 ADR 属于上层事实，
  AI Agent 不得擅自重定义——见 `../00_governance/document-standard.md` §2.6）

此时必须记录：

- 阻塞原因（Blocked Reason）
- 缺失信息（Missing Input）
- 影响范围（Impact）
- 已尝试方案（Attempted Actions）
- 需要谁决策（Required Decision）

```yaml
status: blocked
```

## 14. Completion Record

- 实际完成时间：
- 实际结果：
- 验证结果：PASS / FAIL / PARTIAL / BLOCKED
- Evidence：
````

---

## 状态枚举速查

| 状态 | 含义 | 可否流转 |
| --- | --- | --- |
| `draft` | 尚未准备执行 | → ready |
| `ready` | 条件齐全，可以执行 | → in-progress |
| `in-progress` | 正在执行 | → review / blocked |
| `blocked` | 因外部或内部原因无法继续 | → in-progress（阻塞解除后） |
| `review` | 已执行，等待复核 | → verified / in-progress |
| `verified` | 已完成验证 | → completed |
| `completed` | 正式完成 | 终态 |
| `cancelled` | 已取消 | 终态 |

---

## 完成定义（Done）

```text
Done = Implementation + Acceptance + Verification + Evidence
```

四者缺一不可。**"代码写完"不是完成。** 详细口径见 [`../06_validation/validation-plan.md`](../06_validation/validation-plan.md)。
