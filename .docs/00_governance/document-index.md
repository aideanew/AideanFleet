# Document Index · 文档总索引

> 类型：document-index ｜ 状态：active ｜ 最后更新：2026-09-22 ｜ 基线：HEAD `eb7a63c`
>
> 回答"当前项目有哪些文档、在哪里"。目录结构与关联关系见 [`project-map.md`](./project-map.md)。
> **本文件只登记指针，不承载正文。**

---

## 治理层（Governance）

- [文档系统入口](./README.md)
- [项目文档地图](./project-map.md)
- [文档规范（本项目裁剪版）](./document-standard.md)
- [文档总索引](./document-index.md)
- [术语表](./glossary.md)

## 产品定义（Product）

- [产品定义：为什么存在 / 目标 / 范围](../01_product/product-definition.md)

## 需求（Requirements）

- [需求入口与归档规则](../02_requirements/README.md)
- [需求基线（当前有效需求）](../02_requirements/product-requirements.md)
- [Backlog 待办池](../02_requirements/backlog.md)
- 新需求原始入口目录：`../02_requirements/inbox/`
- 功能需求目录：`../02_requirements/features/`
- 非功能需求目录：`../02_requirements/non-functional/`
- 约束需求目录：`../02_requirements/constraints/`

## 方案与决策（Solution / Decision）

- [架构方案（指针）](../03_solution/architecture.md)
- [ADR 决策记录索引（指针 → docs/adr.md）](../03_solution/decisions/README.md)
- [契约索引（指针 → docs/契约/）](../03_solution/contracts.md)
- 执行方案目录：`../03_solution/solutions/`

## 计划（Planning）

- [Roadmap 长期路线（指针）](../04_planning/roadmap.md)
- [Current Plan 当前执行计划](../04_planning/current-plan.md)

## 执行（Execution）

- [原子任务模板](../05_execution/task-template.md)
- [任务索引](../05_execution/task-index.md)
- 任务目录：`../05_execution/tasks/`

## 验证与证据（Validation / Evidence）

- [验证计划与完成定义](../06_validation/validation-plan.md)
- 新证据目录：`../06_validation/evidence/`

## 发布（Release）

- [变更日志](../07_release/changelog.md)

## 知识沉淀（Knowledge）

- [经验与教训](../08_knowledge/lessons-learned.md)

## 历史归档（Archive）

- [旧规划文件处置台账](../09_archive/legacy-planning.md)

---

# 既有工程资料（权威来源，不在 `.docs/` 内复制）

以下文件**保持原地不动**，`.docs/` 只做引用。这是 Single Source of Truth 的具体体现。

## 架构决策与契约

- [`docs/adr.md`](../../docs/adr.md) — ADR-010(SUPERSEDED)、ADR-016~023(ACCEPTED)；**ADR-013/014 留空未占用**
- [`docs/契约/任务状态机.md`](../../docs/契约/任务状态机.md) — FROZEN v1.1，10 状态，唯一权威实现 `fleet/core/state_machine.py`
- [`docs/契约/任务进度表字段.md`](../../docs/契约/任务进度表字段.md) — FROZEN v1.2，15 契约字段 + CORE-04 三扩展列
- [`docs/契约/控制台API.md`](../../docs/契约/控制台API.md) — 827 行，对外字段名与契约一致

## 规划与执行方案

- [`docs/规划总览.md`](../../docs/规划总览.md) — 1689 行，两份材料逐项取舍（M1 24 条、M2 各条）
- [`docs/plans/2026-09-17-evidence-driven-remaining-work.md`](../../docs/plans/2026-09-17-evidence-driven-remaining-work.md) — **当前执行方案权威源**，E01–E20 证据索引 + W1–W8 工作包 + §3.0 统一原子执行规则
- [`docs/plans/控制台可观测性与项目身份增强大纲-2026-09-17.md`](../../docs/plans/控制台可观测性与项目身份增强大纲-2026-09-17.md)
- [`docs/plans/控制台项目身份与联动修复大纲-2026-09-17.md`](../../docs/plans/控制台项目身份与联动修复大纲-2026-09-17.md)

## 验收与证据

- [`docs/验收清单-Phase2.md`](../../docs/验收清单-Phase2.md) — 状态"修订中"，需经理复核后方可作出口依据
- 工作包证据：`reports/CORE-02-evidence.md`、`reports/CORE-03-evidence.md`、`reports/CORE-04-evidence.md`、`reports/FE-01-evidence.md`、`reports/GOV-01-evidence.md`、`reports/INT-02-evidence.md`、`reports/INT-03-evidence.md`、`reports/INT-04-evidence.md`、`reports/2026-09-18_剩余任务方案_P008与控制台收口.md`
- ⚠️ `reports/INT-04R-evidence.md` **缺失**（`docs/验收清单-Phase2.md` 亦记载缺失）

## 参考与原始需求

- [`docs/参考/base.md`](../../docs/参考/base.md) — 原始用户需求（证据 E01 已引用其行号 25-61, 63-87, 106-112）
- [`docs/参考/chatpgt.md`](../../docs/参考/chatpgt.md) — 2182 行，外部参考
- [`docs/参考/claude.md`](../../docs/参考/claude.md) — 1247 行，外部参考
- [`docs/参考/glm.md`](../../docs/参考/glm.md) — 615 行，外部参考

## 部署与安装

- [`docs/CLI安装与自动化部署指南.md`](../../docs/CLI安装与自动化部署指南.md)
- [`docs/CLI安装决策单.md`](../../docs/CLI安装决策单.md)
- [`docs/部署指南.md`](../../docs/部署指南.md)

## 派工与管理员配置模板

- `docs/启动Hermes派工.txt`、`docs/启动Hermes派工1(英文版).txt`、`docs/启动Hermes派工2(英文版).txt`、`docs/启动Hermes派工3(中文版).txt`、`docs/启动Hermes派工3(英文版).txt`、`docs/启动Hermes派工4(中文版).txt`
- `docs/管理员全局设定示例.txt`、`docs/任务提交给管理员示例.txt`

## 兄弟项目文档（⚠️ 非本项目需求来源）

`DELIVERY/` 下三份讨论稿的分析对象是 **Aidean / AideanBot**（TypeScript + Prisma + Next.js 的
采集/知识库产品），**不是 AideanFleet**。证据：三者基线提交 `f1068e4`、`205c151`、`5b17da2`
均不属于本仓库（本仓库基线 `eb7a63c`），内容涉及 Prisma model、`seed.ts`、RedFox 积分、
LangBot 对接等 AideanBot 专属概念。

它们仅作为"用 AideanFleet 方法论分析外部项目的过程记录"存留，**不得**作为 AideanFleet 的
需求、验收或阶段依据引用。

**状态（2026-09-22）**：`DELIVERY/` 已**从本仓库撤出**（`git rm -r --cached` 后加入 `.gitignore`），
文件仅保留在本机磁盘上。因此下面三条**是纯文本登记，不是可点击链接**——GitHub 上看不到它们。

- `DELIVERY/需求复核与再设计-20260922.md` — 对象：AideanBot；基线 `5b17da2`
- `DELIVERY/启动前讨论稿-20260922-核验版.md` — 对象：AideanBot；基线 `205c151`；`.cluster/aideanbot/` 有字节级相同副本
- `DELIVERY/aidean-深析讨论稿-20260922.md` — 对象：Aidean；基线 `f1068e4`→`d17cfed`

⚠️ 其中"14 **问**"是 AideanBot 的复核问题数，**不是 AideanFleet 的"关卡"**。
AideanFleet 全仓无"14 关"这一概念，见 `08_knowledge/lessons-learned.md` L-22。

## 历史设计存档

- `初始设计/d0.md` ~ `初始设计/d12.md`、`初始设计/核心.md`、`初始设计/核心2.md`、`初始设计/提示词启动.md`、`初始设计/temp.md`
- 处置说明见 [`../09_archive/legacy-planning.md`](../09_archive/legacy-planning.md)

## 既有规划草稿（已被取代，保留）

- `docs/剩余任务与实施方案大纲-v1.md`（618 行）
- `docs/剩余任务方案大纲-2026-09-17.md`
- `docs/剩余任务方案大纲-2026-09-17-v2.md`
- `docs/剩余任务方案大纲-2026-09-17-核验版.md`

---

## 更新规则

* 新增文档 → 在本文件对应分类下登记一行
* 目录结构变化 → 同步更新 [`project-map.md`](./project-map.md) 第 2 节
* 既有权威文件**不迁入 `.docs/`**，只在本文件登记
* 删除文档前 → 先在本文件改为归档标记，并写入 `09_archive/` 台账
