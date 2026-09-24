# Glossary · 术语表

> 类型：glossary ｜ 状态：active ｜ 最后更新：2026-09-22 ｜ 基线：HEAD `eb7a63c`
>
> 本文件解释项目内反复出现、容易误读的术语。**权威定义以契约文件为准**，此处只作导航与澄清。

---

## 系统分层

| 术语 | 含义 | 出处 |
| --- | --- | --- |
| **Control Plane（控制面）** | 调度、治理、控制台、状态机所在的系统核心 | `docs/规划总览.md` M1-分层铁律 |
| **Manager** | 系统 + LLM，不是单纯 LLM。LLM 负责"思考"，系统代码负责"执行规则"；DAG 的 READY 判断必须由系统代码完成 | `docs/规划总览.md` M1-Manager不等于LLM |
| **Executor（执行体）** | 实际干活的 CLI/Agent（cline/gemini/grok/claude/codex/opencode/hermes 等） | `fleet/executors/`、ADR-022 |
| **Adapter（适配器）** | 执行体接入控制面的桥接层。契约层冻结，语义调整一律在 executors 侧桥接解决 | `fleet/executors/base.py`、ADR-022 |
| **Application API** | 统一入口 `startProject(request)`。CLI 与 Hermes 是两个 Adapter，共享同一 Application API | `docs/规划总览.md` M1-CLI和Hermes是两个Adapter |
| **ExecutionPolicy** | 自动/确认模式只是策略参数，不是两套引擎。一个 Execution Engine，Policy 控制行为 | `docs/规划总览.md` M1-自动/确认模式只是ExecutionPolicy |

## 架构与数据

| 术语 | 含义 | 出处 |
| --- | --- | --- |
| **DAG** | 任务依赖图，系统心脏。是核心数据结构，不是 Prompt 里的概念 | `docs/规划总览.md` M1-DAG是系统心脏 |
| **plan.json** | 人类可读快照，**不是第二数据库**。数据库 = 运行时权威状态，单向 DB→plan.json，不双向同步 | `docs/规划总览.md` M1-plan.json是快照 |
| **attempt（执行尝试）** | 一次任务执行尝试。返工产生新 attempt；证据必须按 attempt 隔离，防止第二次执行读到第一轮报告 | `docs/plans/...evidence-driven-remaining-work.md` E07、§3.5 |
| **lease（租约）** | 资源占用保护。覆盖执行、提交、审查直至产物固化 | 同文件 E05、§3.2.7 |
| **outbox（待投递事件）** | 事务内持久化的待投递事件队列，保证 SQLite 提交与 JSONL 追加的原子性 | 同文件 E06、§3.3.1 |
| **Project Memory** | `data/memory/<project_id>.json`，条目 schema 见 `docs/契约/控制台API.md` §13.3 | `docs/契约/任务进度表字段.md` v1.2 §6 |
| **六节报告** | 执行体提交时必须返回的六节结构化报告 + 证据文件 | `docs/契约/任务状态机.md` 迁移 #4 |

## 任务状态机（10 状态，FROZEN v1.1）

权威：[`docs/契约/任务状态机.md`](../../docs/契约/任务状态机.md)。名称一经冻结不得改名。

| 状态 | 中文 | 终态 |
| --- | --- | --- |
| `DRAFT` | 草稿，已建档未派工 | 否 |
| `ASSIGNED` | 已派工，assignee/reviewer 已定 | 否 |
| `DOING` | 执行中，适配器已被调用 | 否 |
| `SUBMITTED` | 已提交六节报告与证据 | 否 |
| `REVIEWING` | 审查判别中 | 否 |
| `REWORK` | 返工，`rework_count += 1` | 否 |
| `BLOCKED` | 阻塞：外部依赖/网关/额度/证据不足，**非实现失败** | 否 |
| `DONE` | 完成 | **是** |
| `PARTIAL` | 部分完成 | **是** |
| `ESCALATED` | 升级：返工次数超上限，必须人工介入 | **是** |

**返工上限口径**：迁移 #12 `REWORK → ASSIGNED` 条件 `rework_count <= 3`，迁移 #13 `REWORK → ESCALATED` 条件 `rework_count > 3`。
即**第 4 次返工升级**。历史文档中"×3 即升级"的模糊口径不可沿用。

## 模式与口径

| 术语 | 含义 | 出处 |
| --- | --- | --- |
| **UI 工作模式（五值）** | `run` / `intake` / `audit` / `discuss` / `plan`。前端状态机，启动器消费 | ADR-020 |
| **调度模式（二值）** | `auto` / `step`。由 `/api/mode` 与 WS `set_mode` 承载；旧值 `confirm` 兼容等价 `step` | ADR-020 |
| **两个正交概念** | 工作模式回答"这一轮做什么"，调度模式回答"派工要不要人点头"。不可合并为一个枚举 | ADR-020 |

## 工作包与角色

| 术语 | 含义 |
| --- | --- |
| **W1 ~ W8** | 当前执行方案 `docs/plans/2026-09-17-evidence-driven-remaining-work.md` §3 的工作包分层 |
| **角色 A / B / C** | A = 控制面核心与契约 owner；B = 前端；C = 启动器/执行体/通知。跨边界修改由文件 owner 执行（ADR-018、ADR-022） |
| **CORE / FE / GOV / INT** | 工作包角色前缀（CORE-02/03/04、FE-01、GOV-01、INT-02/03/04）。新批次沿用前缀递增 |
| **P0 / P1 / P2** | 优先级。P0 正确性优先，P1 能力，P2 性能 |

## ID 体系（易混，务必区分）

| 格式 | 用途 | 权威来源 |
| --- | --- | --- |
| `T-NNN`（如 `T-001`） | **运行时任务 ID**，SQLite `tasks.task_id` 主键 | `docs/契约/任务进度表字段.md` §1 |
| `TASK-NNN` | **文档层任务 ID**，`.docs/05_execution/tasks/` 中人可读追溯用 | `.docs/05_execution/` |
| `ADR-NNN` | 架构决策。013/014 留空未占用 | `docs/adr.md` |
| `E01`–`E20` | 证据索引编号 | `docs/plans/2026-09-17-...-remaining-work.md` §2 |
| `REQ-INBOX-YYYYMMDD-NNN` / `REQ-F-NNN` / `REQ-NF-NNN` / `REQ-C-NNN` | 需求（入口 / 功能 / 非功能 / 约束） | `.docs/02_requirements/` |
| `SOL-NNN` | 执行方案 | `.docs/03_solution/solutions/` |
| `VAL-NNN` | 验证记录 | `.docs/06_validation/`、`DELIVERY/` |
| `REL-NN` | 发布记录 | `DELIVERY/`（既有 REL-01） |

**禁止混用** `T-NNN` 与 `TASK-NNN`。两者关系需在任务文档中显式写明。

## 项目命名

| 术语 | 说明 |
| --- | --- |
| **AideanFleet** | **唯一正式项目名**。仓库、进程横幅、`.env` 的 `FLEET_PROJECT_NAME=AideanFleet`、文档口径一律统一（ADR-023） |
| AideanCompany / AideanBot | 废弃旧名，仅作历史文档引用保留 |

## 端口

| 变量 | 值 | 说明 |
| --- | --- | --- |
| `FLEET_CONSOLE_PORT` | `5000` | 网页控制台（UI 与 API 同进程）。**UI = 控制台 = 5000**（ADR-017） |
| `FLEET_MANAGER_PORT` | `9900` | Manager 网关，与控制台独立 |
| `FLEET_UI_PORT` | `3333` | 被托管项目端口，各自独立互不相干 |

## 其他

| 术语 | 含义 |
| --- | --- |
| **FROZEN（冻结）** | 契约产出即冻结。状态名、迁移方向、字段名不得改名；扩展只能"新增"，不得修改既有语义 |
| **Hermes** | 派工入口之一，与 CLI 并列为两个 Adapter |
| **机器门（Machine Gate）** | 进入审查判别前的自动验证门。机器门已执行完毕才进 `REVIEWING`（PASS 与失败都进） |
| **六档 CLI 执行体** | cline / gemini / grok / claude / codex / opencode 执行体适配器 |
