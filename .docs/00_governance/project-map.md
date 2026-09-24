# Project Map · AideanFleet 文档地图

> 类型：project-map ｜ 状态：active ｜ 建立：2026-09-22 ｜ 基线：HEAD `eb7a63c`
>
> 本文件是整个文档体系的**导航地图**。它只做两件事：回答"项目里有哪些文档、各承担什么事实"，
> 以及"这些事实之间怎么关联"。本文件**不承载任何需求、方案、任务、决策的正文**。

---

## 1. 文档根与两条文档线的关系

本仓库存在**两条并行的文档线**，本地图负责把它们串起来：

| 文档线 | 根目录 | 性质 | 权威程度 |
| --- | --- | --- | --- |
| **项目规范文档** | `.docs/` | 项目级规范体系（本文件所属） | 治理层权威 |
| **工程资料** | `docs/`、`reports/`、`DELIVERY/`、`初始设计/` | 既有工程文档、证据、讨论稿、历史设计 | 各自在其领域内权威 |

**关键原则**：`.docs/` 不复制 `docs/` 的内容。凡 `docs/` 已有权威文件（ADR、契约、规划总览），
`.docs/` 只建**指针**，不复述正文——否则立刻违反 Single Source of Truth。

受保护边界（本次建立规范时严格遵守，后续亦然）：

* 根目录下 `.` 开头的目录，除 `.docs/` 外一律不编辑（`.cluster/`、`.openclaw/`、`.openclaw-attachments/`、
  `.box-agent/`、`.opencode/`、`.claude/` 等）。
* `fleet/`、`tests/`、`scripts/`、`config/`、`prompts/`、`pyproject.toml` 等代码文件不改动。
* `docs/` 既有文件不移动、不覆盖、不改名——历史保留优先于结构整洁。

---

## 2. `.docs/` 目录结构

```text
.docs/
│
├── 00_governance/                    # 治理层（本体系入口）
│   ├── README.md                     # 文档系统入口
│   ├── project-map.md                # ← 本文件：目录结构与关联关系
│   ├── document-index.md             # 全部文档总索引
│   ├── document-standard.md          # 文档规范（本项目裁剪版）
│   └── glossary.md                   # 术语表
│
├── 01_product/                       # 产品定义
│   └── product-definition.md         # 项目为什么存在、目标、范围
│
├── 02_requirements/                  # 需求系统
│   ├── README.md                     # 新需求入口与归档规则
│   ├── inbox/                        # 新需求原始入口 ★
│   │   └── REQ-INBOX-YYYYMMDD-NNN.md
│   ├── features/                     # 功能需求   REQ-F-NNN
│   ├── non-functional/               # 非功能需求 REQ-NF-NNN
│   ├── constraints/                  # 约束需求   REQ-C-NNN
│   ├── product-requirements.md       # 当前需求基线（指针）
│   └── backlog.md                    # 待办池（指针）
│
├── 03_solution/                      # 方案与决策
│   ├── architecture.md               # 架构（指针 → 既有资料）
│   ├── decisions/                    # ADR（指针 → docs/adr.md）
│   ├── contracts.md                  # 契约索引（指针 → docs/契约/）
│   └── solutions/                    # 执行方案   SOL-NNN
│
├── 04_planning/                      # 计划
│   ├── roadmap.md                    # 长期路线（指针）
│   └── current-plan.md               # 当前执行计划（指针 + 本轮目标）
│
├── 05_execution/                     # 执行任务
│   ├── task-template.md              # 原子任务模板 ★
│   ├── tasks/                        # 原子任务 TASK-NNN
│   └── task-index.md                 # 当前任务索引（指针）
│
├── 06_validation/                    # 验证与证据
│   ├── validation-plan.md            # 验证口径与完成定义 ★
│   └── evidence/                     # 新证据落点（指针 → reports/）
│
├── 07_release/                       # 发布
│   └── changelog.md                  # 变更日志
│
├── 08_knowledge/                     # 知识沉淀
│   └── lessons-learned.md            # 经验与教训
│
└── 09_archive/                       # 历史归档
    └── legacy-planning.md            # 旧规划文件处置台账
```

★ = 可直接使用的新模板；其余多数为**指针型**文件，指向既有权威资料。

---

## 3. 现有文档资产总览（当前事实状态）

下表是本次建立规范时逐一核验的结果。**状态列只记录事实，不臆断未核过的内容。**

| 领域 | 权威位置 | 状态 | 核验依据 |
| --- | --- | --- | --- |
| 架构决策 ADR | `docs/adr.md`（ADR-010 SUPERSEDED，ADR-016~023 ACCEPTED） | ✅ 已建立 | 逐条读取；ADR-013/014 明确留空未占用 |
| 任务状态机契约 | `docs/契约/任务状态机.md`（FROZEN v1.1，10 状态） | ✅ 已建立 | 读取文件头与版本记录 |
| 任务字段契约 | `docs/契约/任务进度表字段.md`（FROZEN v1.2，15 契约字段） | ✅ 已建立 | 同上；§2 含 CORE-04 三扩展列 |
| 控制台 API 契约 | `docs/契约/控制台API.md`（827 行） | ✅ 已建立 | 文件存在，行数已核 |
| 长期规划总览 | `docs/规划总览.md`（1689 行，含两份材料逐项取舍） | ✅ 已建立 | 读取头部 24 条 M1/M2 取舍结论 |
| 当前执行方案 | `docs/plans/2026-09-17-evidence-driven-remaining-work.md` | ✅ 已建立 | 读至 §3.8；含 W1–W8 与 E01–E20 证据索引 |
| 早期规划草稿（4 份） | `docs/剩余任务方案大纲-*.md`（2026-09-17，v1/v2/核验版 + 实施大纲） | 🗄 历史 | 已被证据驱动方案取代，保留不删 |
| Phase2 验收清单 | `docs/验收清单-Phase2.md` | 🚧 修订中 | 文件头自述"需经理复核后再作为出口依据" |
| 工作包证据 | `reports/CORE-02/03/04-evidence.md`、`FE-01`、`GOV-01`、`INT-02/03/04` | ✅ 已建立 | 目录列举行数 |
| INT-04R 证据 | 应有 `reports/INT-04R-evidence.md` | ❌ 缺失 | `ls` 确认不存在；Phase2 清单同样记载缺失 |
| CLI 安装与部署 | `docs/CLI安装与自动化部署指南.md`、`docs/CLI安装决策单.md`、`docs/部署指南.md` | ✅ 已建立 | 文件存在 |
| 原始用户需求 | `docs/参考/base.md` | ✅ 已建立 | 证据 E01 已引用其行号 |
| 外部参考资料 | `docs/参考/{chatpgt,claude,glm}.md` | ✅ 已建立 | 仅参考，非项目事实来源 |
| 深析与讨论稿 | `DELIVERY/`（3 组 md/html） | ⚠️ **兄弟项目** | 分析对象是 Aidean/AideanBot（基线 `f1068e4`/`205c151`/`5b17da2`），**不是 AideanFleet**，不得作为本项目需求来源 |
| 初始设计存档 | `初始设计/d0.md` ~ `d12.md`、`核心*.md`、`temp.md` | 🗄 历史 | 目录列出；含最早 TASK 编号雏形 |
| Hermes 派工指令 | `docs/启动Hermes派工*.txt`（6 份）、`管理员全局设定示例.txt`、`任务提交给管理员示例.txt` | ✅ 已建立 | 文件存在 |
| 正式需求基线 | `02_requirements/product-requirements.md` | 🚧 指针就位，基线内容待补 | 本轮新建 |
| 需求 Inbox | `02_requirements/inbox/` | 🚧 结构就位，无条目 | 本轮新建 |
| Backlog | `02_requirements/backlog.md` | 🚧 指针就位 | 本轮新建 |
| Roadmap / 里程碑 | `04_planning/roadmap.md` | 🚧 指针就位 | 本轮新建 |
| 任务模板 | `05_execution/task-template.md` | ✅ 已建立 | 本轮新建 |
| 验证计划 | `06_validation/validation-plan.md` | ✅ 已建立 | 本轮新建 |
| 变更日志 | `07_release/changelog.md` | ✅ 已建立 | 本轮新建 |

---

## 4. 核心追溯链（本项目实际形态）

规范要求的最完整链路，在本项目的实际落点：

```text
用户需求（docs/参考/base.md 原始需求 + 02_requirements/inbox/ 新需求入口）
        ↓  需求分析与类型判断
  REQ-INBOX / REQ-F / REQ-NF / REQ-C
        ↓
  SOL（执行方案）      ← 03_solution/solutions/
  ADR（技术决策）      ← docs/adr.md（既有权威）
  契约（冻结语义）     ← docs/契约/（既有权威）
        ↓
  PLAN / ROADMAP       ← 04_planning/ → docs/plans/
        ↓
  WORK PACKAGE         ← W1…W8（见 current-plan 指针）
        ↓
  ATOMIC TASK          ← 05_execution/tasks/（模板已就位）
        ↓
  EXECUTION STEPS      ← 任务内 §7
        ↓
  VALIDATION           ← 06_validation/ + docs/验收清单-Phase2.md
        ↓
  EVIDENCE             ← reports/<WORK-PACKAGE>-evidence.md
        ↓
  RELEASE              ← 07_release/changelog.md
        ↓
  KNOWLEDGE            ← 08_knowledge/lessons-learned.md
```

**双向追溯要求**：任一个节点都应能向前追溯到需求，也能向后追溯到证据。
本项目已有的最强示范是 `docs/plans/2026-09-17-evidence-driven-remaining-work.md`：
E01–E20 证据索引 + W1–W8 工作包 + 三级编号任务，形成了 `证据 → 工作包 → 任务 → 验收` 的可用链路。

---

## 5. ID 命名口径（重要：两套并存，不要混用）

核验发现项目内存在**两套 ID 体系**，混用会造成追溯失败。规则如下：

| 用途 | 格式 | 权威来源 |
| --- | --- | --- |
| **运行时任务 ID** | `T-NNN`（如 `T-001`） | `docs/契约/任务进度表字段.md` §1 字段 `task_id`；代码中以 `"T-001"` 形式广泛出现 |
| **文档任务 ID** | `TASK-NNN` | `.docs/05_execution/`（文档层，用于人可读追溯） |
| 架构决策 | `ADR-NNN` | `docs/adr.md`；013/014 留空未占用，**不要占用** |
| 证据项 | `E01`–`E20` | `docs/plans/2026-09-17-evidence-driven-remaining-work.md` §2 |
| 工作包 | `W1`–`W8`（新批次可用 `CORE-05`、`INT-05` 等角色前缀） | 同上；`CORE`/`FE`/`GOV`/`INT` 为既有角色前缀 |

**禁止**：在文档里把运行时 `T-001` 改写成 `TASK-001` 当作同一对象，或反之。
两者关系应在任务文档中显式写出（"本任务对应运行时任务 `T-xxx`"）。

---

## 6. 更新规则

* 新增重要文档 → 同步更新 `document-index.md`，并在本文件第 3 节登记状态。
* 目录结构变化 → 更新本文件第 2 节。
* 发现"同一事实在两处有不同版本" → 立刻指定唯一权威来源，另一处改为指针。
* 历史文件**不删除、不移动、不改名**；以 `superseded` 标注并在 `09_archive/` 登记。
* 本文件不写需求正文、任务步骤、决策理由——那些内容属于各自权威文档。
