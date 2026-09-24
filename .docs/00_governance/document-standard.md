# 项目文档规范（AideanFleet 裁剪版）

> 类型：document-standard ｜ 状态：active ｜ 版本：v1.0 ｜ 建立：2026-09-22
>
> 通用规范参照《PROJECT DOCUMENTATION SPECIFICATION v1.1》（53 节）。
> 本文件是**本项目落地版**：只保留与 AideanFleet 实际情况相关的条款，
> 并补齐通用规范未覆盖、而本项目必需的条款（ID 双体系、契约冻结、点目录边界）。

---

## 1. 本规范回答什么问题

一个新人或 AI Agent 在不依赖口头说明、聊天记录的情况下，应能回答：

1. 这个项目为什么存在？→ `01_product/product-definition.md`
2. 当前有哪些正式需求？→ `02_requirements/`
3. 新需求该放哪？→ 本规范 §4
4. 当前采用什么方案、为什么？→ `03_solution/` + `docs/adr.md`
5. 现在准备交付什么？→ `04_planning/current-plan.md`
6. 正在执行什么、每个任务的完成定义是什么？→ `05_execution/`
7. 怎么证明做完了？→ `06_validation/` + `reports/`
8. 完整目录结构与关联关系？→ `00_governance/project-map.md`
9. 哪些东西已过期但仍需保留？→ `09_archive/`

---

## 2. 核心原则（七条，按优先级）

### 2.1 单一事实源

同一种事实只有一个权威来源。本项目映射：

| 事实类型 | 唯一权威来源 |
| --- | --- |
| 项目目标与定位 | `01_product/product-definition.md` |
| 正式需求 | `02_requirements/{features,non-functional,constraints}/` |
| 需求原始入口 | `02_requirements/inbox/` |
| 待办顺序 | `02_requirements/backlog.md` |
| 技术决策 | `docs/adr.md` |
| 运行时契约（状态机/字段/API） | `docs/契约/` 三份 FROZEN 文档 |
| 架构方案 | `03_solution/architecture.md` → 指向 `docs/规划总览.md` |
| 当前计划 | `04_planning/current-plan.md` → 指向 `docs/plans/2026-09-17-evidence-driven-remaining-work.md` |
| 任务定义 | `05_execution/tasks/` |
| 验收结果 | `06_validation/`、`docs/验收清单-Phase2.md` |
| 完成证据 | `reports/` |
| 发布事实 | `07_release/changelog.md` |
| 目录结构与关联 | `00_governance/project-map.md` |

其他文档**可以引用**上述事实，**不得复制并维护第二份**。
发现冲突时：以权威来源为准，把副本改为链接。

### 2.2 历史不被覆盖

已产生的决策、需求、验收结论，不用删除或覆盖来制造"从未发生"。
使用状态标记：`superseded`、`rejected`、`cancelled`、`archived`。
本项目实例：`docs/adr.md` 中 ADR-010 标为 SUPERSEDED 并指向 ADR-016，这是正确做法，保持这个写法。

### 2.3 按复杂度裁剪

不允许为"看起来完整"而批量创建空文档。
本规范落地时已遵守：`features/`、`non-functional/`、`constraints/`、`solutions/`、`tasks/`、`evidence/`
只建目录与规则，**不预填占位内容**；有真实条目时再创建文件。

### 2.4 当前状态与历史状态分离

* 当前状态回答"现在怎样"：`current-plan.md`、`backlog.md`、`product-requirements.md`
* 历史状态回答"为什么变成这样"：`09_archive/`、ADR 的 SUPERSEDED 段、证据文件

两者都必须保留。

### 2.5 完成 = 实现 + 验收 + 验证 + 证据

"代码写完"不是完成。最小完成条件：

```text
目标已实现
 + 验收条件逐条满足
 + 验证已实际执行（不是推断）
 + 验证结果明确（PASS / FAIL / PARTIAL / BLOCKED）
 + 证据已保存且可定位
```

本项目落地要求见 `06_validation/validation-plan.md`。

### 2.6 契约优先于文档

`docs/契约/` 三份 FROZEN 文档与 `docs/adr.md` 的决策，**优先级高于本规范文件**。
本规范不得重定义状态机状态名、字段名、API 路径。
如需扩展，走 ADR 流程（新增 ADR-NNN），不得直接改契约语义。

### 2.7 无破坏性编辑

* 不移动、不改名、不删除既有文件（`docs/`、`初始设计/`、`reports/`、`DELIVERY/` 均原地保留）。
* 根目录 `.` 开头目录除 `.docs/` 外不编辑。
* 代码文件（`fleet/`、`tests/`、`scripts/`、`config/`、`prompts/`、`pyproject.toml` 等）不修改。
* 新内容一律**新增文件**，不覆盖既有文件。

---

## 3. 分层关系（不要混为一谈）

本项目最容易混淆的四层，严格区分：

```text
ROADMAP          长期准备做什么（W1…W8 的分层意图）
   ↓
WORK PACKAGE     一块相对独立的交付集合（如 W2「唯一调度者与严格人工控制」）
   ↓
ATOMIC TASK      最小可独立执行且可独立验证的工作单元
   ↓
EXECUTION STEPS  完成任务的具体操作步骤
```

* **Roadmap 不写**"修改 xxx 文件 / 新增 xxx API"——那是任务层。
* **Work Package ≠ Task**：工作包是交付集合，Task 是执行单位。
* **WBS ≠ Execution Steps**：WBS 分解交付成果，Steps 描述执行过程。
* **Solution ≠ ADR**：Solution 回答"这个需求具体怎么实现"，ADR 回答"为什么做出这个决策、考虑过哪些选项"。

本项目已有的良好示范：`docs/plans/2026-09-17-evidence-driven-remaining-work.md` §3.0
定义"每个三级编号是一个可独立验收的行为变更"，且 §3.0 统一规定每个任务拆 `.a`~`.e` 五个四级动作——
这正是 Atomic Task 与 Execution Steps 的正确分层，后续任务沿用该口径。

---

## 4. 新需求管理（本项目落地规则）

### 4.1 统一入口

任何来源的新需求**先进入**：

```text
.docs/02_requirements/inbox/REQ-INBOX-YYYYMMDD-NNN.md
```

来源包括：用户、管理者、AI Agent 自查、市场反馈、运行事故、技术探索。

⚠️ **注意**：`DELIVERY/` 下的讨论稿**不是**本项目的需求来源——它们的分析对象是
Aidean / AideanBot 兄弟项目（见 `09_archive/legacy-planning.md` 与本规范 §8.11）。
本项目需求的唯一原始来源是 `docs/参考/base.md` 与 `02_requirements/inbox/`。

### 4.2 Inbox 只存原始事实

Inbox 保存**原始表述**，原则上不修改措辞，只补元数据：

```yaml
---
id: REQ-INBOX-20260922-001
type: requirement-inbox
status: new
source: user
created: 2026-09-22
---
```

### 4.3 三类需求分流

| 类型 | ID 前缀 | 归档位置 | 判断标准 |
| --- | --- | --- | --- |
| 功能需求 | `REQ-F-NNN` | `features/` | 系统**必须能做什么** |
| 非功能需求 | `REQ-NF-NNN` | `non-functional/` | 性能、安全、可用性、兼容性等质量属性 |
| 约束需求 | `REQ-C-NNN` | `constraints/` | 技术栈、法规、预算、时间等外部限制 |

判断示例：

* "能切换项目会话" → `REQ-F`
* "API 响应 < 200ms" → `REQ-NF`
* "核心代码不得 import 前端框架" → `REQ-C`（本仓库已由 ADR-016 裁决）

### 4.4 批准后

* 需要分析实现路径（多方案对比、跨模块、预计 >3 个 Task、由 AI 执行）→ 建 `SOL-NNN`
* 简单需求（改文案、调样式）→ 直接从 Requirement 到 Task，不建 Solution
* 涉及关键技术选择 → 建 `ADR-NNN`（沿用 `docs/adr.md` 的编号与写法，013/014 已留空勿占用）

---

## 5. 原子任务定义

一个合格的原子任务必须同时满足 8 条：

1. 有明确目标
2. 有明确输入
3. 有明确输出
4. 有明确验收条件
5. 有明确验证方法
6. 有明确依赖
7. 可以判断完成与否
8. 不应继续拆成多个彼此独立的交付结果

任务文档使用 `05_execution/task-template.md`。
执行步骤的粒度参照既有规划 §3.0：`.a` 增加行为测试 → `.b` 记录真实结果 → `.c` 最小实现
→ `.d` 运行目标测试与回归 → `.e` 同步契约/证据。**单动作 2–15 分钟，超出继续分解。**

### 5.1 任务 ID 与路径

* 文档任务 ID：`TASK-NNN`（三位数，稳定不变，不随标题变化而变）
* 固定存放路径：`.docs/05_execution/tasks/TASK-NNN-<slug>.md`
* 状态写在文件 Front Matter 的 `status:` 字段，**不通过移动文件表达状态**

### 5.2 状态枚举

```text
draft → ready → in-progress → review → verified → completed
                    ↓
                 blocked / cancelled
```

### 5.3 Blocked 规则

遇到以下情况**不得自行假设**：需求冲突、核心设计冲突、缺失必要输入、超出任务范围、
无法满足验收标准、关键依赖不可用。此时置 `status: blocked` 并记录：
阻塞原因、缺失信息、已尝试方案、需要谁决策。

特别地，**契约与 ADR 属于上层事实**，AI Agent 不得擅自重定义。
发现冲突 → 记录 → blocked / review → 等待正式决策。

---

## 6. 验证与证据

Task 完成 ≠ 已验证。三层分离：

```text
Task        做了什么
Validation  是否真的完成并满足要求
Evidence    用什么证明
```

证据必须可检查、可定位、与任务相关、尽可能可复现、不依赖口头解释。
本项目落点：`.docs/06_validation/evidence/`（新证据）与 `reports/<WORK-PACKAGE>-evidence.md`（既有）。

---

## 7. 变更记录

任何重要变化回答五个问题：发生了什么、为什么、影响什么、谁确认、后续要改什么。
登记在 `07_release/changelog.md`，影响需求时同步更新 Requirement / Solution / Plan / Task / Validation。

---

## 8. 禁止事项

1. 用 README 承载全部项目管理信息（README 只负责入口与概览）
2. 用 Backlog 保存完整需求正文
3. 用聊天记录作为唯一决策依据（正式决策必须进 ADR）
4. 用 WBS 代替任务执行计划
5. 用 Solution 替代 ADR
6. 把功能需求、非功能需求、约束需求混为一类
7. 为每个概念机械创建独立文件（信息需要独立管理时才独立成文档）
8. 把运行时 `T-NNN` 与文档 `TASK-NNN` 混用
9. 直接覆盖 FROZEN 契约或既有 ADR 语义
10. 通过移动/删除/改名既有文件来"整理结构"
11. **把兄弟项目（Aidean / AideanBot）的文档当作本项目的需求、验收或阶段依据**——
    `DELIVERY/` 三份讨论稿是兄弟项目产物（基线 `f1068e4`/`205c151`/`5b17da2`），
    仅存档，不入追溯链。判断文档归属必须核基线提交号与技术栈，不能看文件名或方法论署名
    （见 `08_knowledge/lessons-learned.md` L-22，本轮实际犯过）
12. 引用未经核验的数字或结论（跨项目结论、无证据的"达标"判定）

---

## 9. 文档质量自检（定期执行）

- **完整性**：目标、需求（三类）、方案、决策、计划、任务、验证、证据、发布是否都在？
- **一致性**：是否存在"需求 A → 方案实现 B → 任务做 C → 代码做 D"的漂移？
- **可追溯性**：需求 → 方案 → 任务 → 验证 → 证据 是否双向可查？
- **时效性**：当前状态是否真实反映项目现状？
- **唯一事实源**：同一事实是否在多处有不同版本？
- **可验证性**：能否证明"这个任务真的完成了"？
- **地图同步**：`project-map.md` 是否反映最新目录结构？`document-index.md` 是否包含新增文档？
