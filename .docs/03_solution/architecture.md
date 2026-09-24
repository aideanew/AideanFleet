# Architecture · 架构方案（指针）

> 类型：architecture ｜ 状态：pointer ｜ 更新：2026-09-22
>
> **本文件不承载架构正文。** 架构事实的权威来源是下列既有文档，
> 本文件只做导航，避免同一事实出现两个版本。

---

## 权威来源

| 事实 | 权威文件 |
| --- | --- |
| 核心定位、分层铁律、开发顺序、六个 Domain 拆分、24 条取舍结论 | [`docs/规划总览.md`](../../docs/规划总览.md)（1689 行） |
| 架构决策（ADR） | [`docs/adr.md`](../../docs/adr.md) |
| 任务状态机 | [`docs/契约/任务状态机.md`](../../docs/契约/任务状态机.md)（FROZEN v1.1） |
| 任务字段与磁盘布局 | [`docs/契约/任务进度表字段.md`](../../docs/契约/任务进度表字段.md)（FROZEN v1.2） |
| 控制台 API 与 WS 通道 | [`docs/契约/控制台API.md`](../../docs/契约/控制台API.md)、ADR-019 |
| 最小接口边界提案 | [`docs/plans/2026-09-17-evidence-driven-remaining-work.md`](../../docs/plans/2026-09-17-evidence-driven-remaining-work.md) §4.2 |
| 证据到代码位置的映射（E01–E20） | 同上，§2 |

---

## 架构要点速览（引自权威来源，仅作索引）

### 定位

**Multi-Agent Software Engineering Orchestrator** —— Agent 是执行资源，不是系统核心。
（`规划总览.md` M1-核心架构定位）

### 分层铁律

```text
Model → Role → Executor → Tools
```

依赖方向固定，接口需抽象，防止硬编码。（M1-分层铁律）

### 关键不变式

| 不变式 | 出处 |
| --- | --- |
| Manager = 系统 + LLM；DAG 的 READY 判断必须由系统代码完成 | `规划总览.md` M1-Manager不等于LLM |
| plan.json 是人类可读快照，不是第二数据库；单向 DB → plan.json | `规划总览.md` M1-plan.json是快照 |
| CLI 与 Hermes 是两个 Adapter，共享同一 Application API | `规划总览.md` M1-CLI和Hermes是两个Adapter |
| 自动/确认模式只是 ExecutionPolicy 参数，不是两套引擎 | `规划总览.md` M1-自动/确认模式只是ExecutionPolicy |
| SQLite 存"现在在哪"，`events.jsonl` 存"发生过什么"，evidence 存"证据在哪"，三者不混用 | `任务进度表字段.md` 引言（源自 `初始设计/d7.md`） |
| 契约层冻结 + 单向依赖（executors → manager） | ADR-022 |
| 核心代码零前端依赖 | ADR-016 |

### 目录归属（ADR-018 / ADR-022）

| 归属 | 路径 |
| --- | --- |
| 角色 A（控制面核心与契约） | `fleet/core/`、`fleet/manager/`、`fleet/console/server.py`、三份契约 |
| 角色 B（前端） | 仅消费契约交付静态产物 |
| 角色 C（启动器/执行体/通知） | `fleet/launcher/`、`fleet/executors/`、`fleet/notify/` |

`fleet/manager/contracts.py` 是执行体接入的**唯一契约层**，角色 C 只 import 不修改。

---

## 待建立的详细设计

如需更细的设计文档，按以下位置创建（**不要在本文件展开**）：

```text
.docs/03_solution/design/DES-NNN-<slug>.md     # 详细设计
.docs/03_solution/solutions/SOL-NNN-<slug>.md  # 执行方案
```

创建后同步登记 [`../00_governance/document-index.md`](../00_governance/document-index.md)。
