# Changelog · 变更日志

> 类型：release ｜ 状态：active ｜ 更新：2026-09-22 ｜ 基线：HEAD `eb7a63c`
>
> 记录**已发生的正式交付**。每个条目回答：发生了什么、为什么、影响什么、证据在哪。
> **未发生的事不写在这里。**

---

## 记录格式

```text
### <批次或提交> · <日期>

- 变化：<做了什么>
- 原因：<为什么>
- 影响：<涉及哪些模块/契约/需求>
- 证据：<reports/ 路径或测试数字>
- 遗留：<未完成部分，如实写>
```

---

## 2026-09-22 · 归属更正（修订版）

- 变化：更正 `.docs/` 初版对 `DELIVERY/` 讨论稿的**错误归属**，共 8 处
- 原因：初版把 Aidean/AideanBot 兄弟项目的讨论稿当作 AideanFleet 的需求来源与阶段依据。
  核验发现三份文档基线分别为 `f1068e4`、`205c151`、`5b17da2`，均非本仓库 `eb7a63c`
- 影响：`document-index.md`、`project-map.md`、`document-standard.md`、`README.md`、
  `product-definition.md`、`product-requirements.md`、`02_requirements/README.md`、
  `roadmap.md`；新增 `lessons-learned.md` L-22 与 `legacy-planning.md` §2.5 存档登记
- 证据：本条目；`lessons-learned.md` L-22 记录了核验事实与判定依据
- 纠正的口径：删除"Aidean 14 问 6 达标/6 部分达标/2 结构性缺口"作为本项目阶段依据的引用，
  阶段定位改由本项目自身的 E07/E10/E11 证据与 W1–W10/G0–G4 支撑；
  "只信实测，不信自述"的出处由 AideanBot 讨论稿更正为执行方案 §5.5
- 遗留：三份讨论稿已入库但未迁移至兄弟项目仓库，待用户指示
  （**已更新**：后续提交已将 `DELIVERY/` 从仓库撤出，见下方条目）

## 2026-09-22 · 兄弟项目文档撤出仓库

- 变化：`DELIVERY/` 执行 `git rm -r --cached` 撤出仓库；`.gitignore` 新增
  `DELIVERY/`、`.cluster/`、`.openclaw/`、`.openclaw-attachments/`
- 原因：`DELIVERY/` 内容为 Aidean/AideanBot 兄弟项目产物，不应进入 AideanFleet 仓库
- 影响：**文件保留在本机磁盘，不销毁**。`.docs` 中所有 DELIVERY 引用改为纯文本登记
  （不再是可点链接）
- 附加修正：`.gitignore` 不支持行内注释——首轮把注释写在模式同一行，导致两条模式整行失效，
  已由 `git check-ignore` 发现并改为注释独立成行

## 2026-09-22 · TASK-001 建立（首个原子任务文档）

- 变化：新增 `05_execution/tasks/TASK-001-health-contract-gap.md`，
  登记 `task-index.md`（状态统计 ready=1），`lessons-learned.md` L-03 补实证
- 原因：填补"58 个原子任务全在执行方案里、`tasks/` 目录为空"的缺口
- 影响：**仅新增文档**。未改动 `fleet/`、`tests/` 任何代码文件
- 证据：TASK-001 §9.1 / §9.2 的实测记录

### 本次拆解的两个实质发现

**发现 1：3.1.1 已基本完成，执行方案勾选框 `[ ]` 是过时口径**

| 项 | 事实 |
| --- | --- |
| 实现 | `server.py:306-309` 四键返回；`launch_core.py:173-176` 严格布尔消费 |
| 测试 | `test_health_contract`（4 用例）+ `test_health_exact_contract_shape`（四键形状） |
| 实测 | `23 passed, 3 warnings in 1.16s`（系统 Python 3.13.7） |
| 七场景探针 | 全部符合预期，含三种异常路径均返回 `console=False` |
| **唯一缺口** | `except Exception` 异常路径**无提交的测试断言** |

→ TASK-001 因此定为"测试补齐"而非"功能实现"，状态 `ready` 但本轮不执行
（加测试需改 `tests/`，超出"只改文档"边界）。

**发现 2：`.venv` 已损坏**

`.venv/Scripts/pyvenv.cfg` 缺失，执行方案 §5.1/5.2 全部命令
（`& '.venv\Scripts\python.exe' -m pytest …`）报 `No pyvenv.cfg file`。
本次改用系统 `Python 3.13.7` 实测通过。

**影响面**：这是环境债，会影响**所有**后续任务的验证命令。
建议列为独立待办：重建 venv，或统一改定命令口径。

## 2026-09-22 · 项目文档体系建立

- 变化：新增 `.docs/` 文档体系（治理层 + 需求入口 + 模板 + 指针层），共 20 份文档 + 8 个目录占位
- 原因：项目已有大量实质文档（ADR、三份 FROZEN 契约、E01–E20 证据索引、W1–W10 工作包），
  但缺少统一地图与需求入口规范，新成员与 AI Agent 无法只靠文档恢复项目上下文
- 影响：**仅新增文档**。未改动任何代码文件，未移动/改名/删除任何既有文件，
  未编辑根目录其他 `.` 开头目录
- 证据：本目录树本身；核验记录见 `00_governance/project-map.md` §3
- 遗留：正式 REQ 编号体系尚未建立（需求以工作包+证据形式存在，见
  `02_requirements/product-requirements.md` §2 的 44 条候选）

## 提交级变更（Git 历史，`git log --oneline`）

> 仓库当前 8 个提交，**无 tag**。REL-01 为文档级发布批次，无对应 git tag。

| 提交 | 说明 |
| --- | --- |
| `eb7a63c` | feat: 新增 cline/gemini/grok 执行体适配器并补齐全口径一致 |
| `6a2b46f` | test: 更新完成通知主题进度断言 |
| `52f25e5` | feat: 邮件通知升级为移动端 HTML 模板，附带项目进度与 ETA 计算 |
| `a7ce658` | docs: 新增六款执行体 CLI 安装与自动化部署指南 |
| `4294bd3` | feat: complete remaining task plan and console observability |
| `4595e82` | fix: 派工异常落 BLOCKED 并兜住 step 模式异常，避免 run_loop 被静默杀死 |
| `f8571a4` | test: 修复 usage 测试跨午夜 UTC 日期断言缺陷；CI 工作流中文化并增加失败日志构件 |
| `1e10034` | first commit |

**版本口径**：`pyproject.toml` 声明 `0.3.0`。

---

## 工作包批次（已有交付，证据在 `reports/`）

| 批次 | 内容 | 证据 | 日期 |
| --- | --- | --- | --- |
| CORE-02 | 控制面核心（角色 A） | `reports/CORE-02-evidence.md` | — |
| CORE-03 | 契约复核 + ADR-016~023 落盘 | `reports/CORE-03-evidence.md` | 2026-09-15 |
| CORE-04 | 上下文成本三扩展列 + Project Memory（契约 v1.1→v1.2） | `reports/CORE-04-evidence.md` | — |
| FE-01 | 网页控制端 v1.0（Vue3/Vite/Pinia 深色科技风） | `reports/FE-01-evidence.md` | — |
| GOV-01 | 治理层 usage/budget/approval（28 tests） | `reports/GOV-01-evidence.md` | — |
| INT-02 | 集成 | `reports/INT-02-evidence.md` | — |
| INT-03 | 集成 | `reports/INT-03-evidence.md` | — |
| INT-04 | 集成（含 CLI 探测与 A 档安装决策） | `reports/INT-04-evidence.md` | — |
| INT-04R | 集成复核 | ⚠️ **`reports/INT-04R-evidence.md` 缺失** | — |
| REL-01 | 首次发布 | `reports/REL-01-evidence.md`（Phase2 清单记载已确认存在） | — |
| P008 | 剩余任务方案与控制台收口 | `reports/2026-09-18_剩余任务方案_P008与控制台收口.md` | 2026-09-18 |

---

## 契约与决策变更

| 变更 | 内容 | 日期 |
| --- | --- | --- |
| ADR-010 → SUPERSEDED | Streamlit 路线作废，被 ADR-016 取代 | 2026-09-15 |
| ADR-016 | 前端 = Vue3 + Vite + Pinia，核心代码零前端依赖 | 2026-09-15 |
| ADR-017 | 端口定版 UI = 5000 | 2026-09-15 |
| ADR-018 | server.py 归角色 A | 2026-09-15 |
| ADR-019 | WebSocket 实时通道写入契约 v1.1 | 2026-09-15 |
| ADR-020 | UI 模式五值 + 调度模式二值正交 | 2026-09-15 |
| ADR-021 | 派工默认单次非交互 | 2026-09-15 |
| ADR-022 | 边界划分 C / A，契约层冻结 | 2026-09-15 |
| ADR-023 | 项目名统一 AideanFleet | 2026-09-15 |
| 任务状态机 v1.1 | FROZEN；迁移 #12/#14 事件动作码对齐实现真值 | — |
| 任务字段契约 v1.2 | §2 新增三扩展列，§6 新增 Project Memory 磁盘布局 | — |

> ADR-013 / ADR-014 **留空未占用**。下一个可用编号：**ADR-024**。

---

## 已知未交付项（阻塞/缺失）

| 项 | 状态 | 说明 |
| --- | --- | --- |
| `reports/INT-04R-evidence.md` | ❌ 缺失 | `docs/验收清单-Phase2.md` 亦记载缺失 |
| `docs/验收清单-Phase2.md` | 🚧 修订中 | 文件头自述"需经理复核后再作为出口依据" |
| W1–W10 共 58 个三级行为项 | 🚧 | 方案文件勾选框 0 项已勾选 |
| W6/3.6.1 事件计量幂等 | 🚧 部分 | 同一事件流已验证；跨流隔离、历史对账、轮转、多进程未验证 |
| 干净安装 / 前端检查 / 端到端统一出口 | ❌ 未形成 | 证据 E19 |

---

## 发布记录模板（REL）

```markdown
# REL-NN

## Release

vX.Y.Z

## Date

YYYY-MM-DD

## Included Requirements

- REQ-F-NNN

## Included Solutions

- SOL-NNN

## Included Work Packages / Tasks

- W1 / TASK-NNN

## Validation

- VAL-NNN（必须声明证据等级 L1–L4 与覆盖边界）

## Known Issues

-

## Not Verified（明确不在本次发布承诺内）

-

## Git

- HEAD：
- 提交区间：
```

---

## 更新规则

* 每次发布必须写本文件，含 **Not Verified** 段——未验证项要明确排除在发布承诺外
* 真实外部依赖（模型/邮件/SMTP）另设授权与预算并单独留证（G4 出口条件）
* 不得把"模块存在"写为"能力已兑现"
* 变更影响需求 → 同步更新 `02_requirements/product-requirements.md`
* 关联文档同步见 `00_governance/document-standard.md` §7
