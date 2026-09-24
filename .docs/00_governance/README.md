# AideanFleet 项目文档体系 · 入口

> 最后更新：2026-09-22 ｜ 基线：HEAD `eb7a63c`

这是项目文档体系的总入口。**先看这个文件，再按需进入其他文档。**

---

## 三分钟内找到东西

| 我想… | 去哪里 |
| --- | --- |
| 搞清楚整个文档体系长什么样 | [`project-map.md`](./project-map.md) |
| 查某一份文档在哪里 | [`document-index.md`](./document-index.md) |
| 了解文档该怎么写、放哪 | [`document-standard.md`](./document-standard.md) |
| 查术语含义 | [`glossary.md`](./glossary.md) |
| 了解项目为什么存在 | [`../01_product/product-definition.md`](../01_product/product-definition.md) |
| **提交一个新需求** | [`../02_requirements/README.md`](../02_requirements/README.md) |
| 查看当前计划要交付什么 | [`../04_planning/current-plan.md`](../04_planning/current-plan.md) |
| 领一个任务、看任务怎么写 | [`../05_execution/task-template.md`](../05_execution/task-template.md) |
| 证明一个任务真的完成了 | [`../06_validation/validation-plan.md`](../06_validation/validation-plan.md) |
| 查已做的架构决策 | [`../../docs/adr.md`](../../docs/adr.md) |
| 查运行时契约（状态机/字段/API） | [`../../docs/契约/`](../../docs/契约/) |

---

## 阅读顺序建议

**新成员**：`product-definition.md` → `project-map.md` → `current-plan.md` → `task-template.md`

**接手一个任务**：`task-template.md` → 任务文件 → 任务里引用的 SOL/ADR/Requirement → `validation-plan.md`

**提出新需求**：`02_requirements/README.md` → 写 Inbox → 等分流

**追溯一件事**：`project-map.md` §4 追溯链 → `document-index.md`

---

## 两条文档线

本仓库有两条并行的文档线，地图负责把它们串起来：

* **`.docs/`** — 项目规范体系（你在这里）。治理、需求入口、模板、追溯规则。
* **`docs/`、`reports/`、`初始设计/`** — 既有工程资料。ADR、契约、规划总览、工作包证据。
* **`DELIVERY/`** — ⚠️ **兄弟项目（Aidean/AideanBot）的讨论稿存档**，不是本项目的需求或验收依据。

**不要把两边内容复制一份。** `.docs/` 里大多数领域文件是**指针**，指向 `docs/` 中已有的权威文件——
避免同一事实出现两个版本。详见 [`project-map.md`](./project-map.md) §1、§3。

---

## 边界（本体系严格遵守）

* 根目录 `.` 开头目录，除 `.docs/` 外**不编辑**
* 代码文件（`fleet/`、`tests/`、`scripts/`、`config/`、`prompts/` 等）**不改动**
* 既有文档（`docs/`、`reports/`、`DELIVERY/`、`初始设计/`）**不移动、不改名、不删除**
* 新内容一律**新增文件**，历史用 `superseded` 标注而非覆盖
