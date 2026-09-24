# 02_requirements · 需求系统入口

> 类型：requirement-inbox ｜ 状态：active ｜ 建立：2026-09-22
>
> **新需求第一步永远在这里。** 读完本文件再动手，30 秒。

---

## 一句话规则

**任何来源的新需求，先写入 `inbox/`，不直接写进 `features/`。**

原因：Inbox 存的是**原始需求事实**。直接归档会丢失来源、背景与提出时的原话，
日后就无法回答"这个需求当时是怎么提出的"。

---

## 三步流程

```text
① 写 inbox/REQ-INBOX-YYYYMMDD-NNN.md     原始表述 + 元数据，不改措辞
        ↓
② 分析与类型判断                          功能 / 非功能 / 约束？
        ↓
③ 归档到对应子目录                         REQ-F-NNN / REQ-NF-NNN / REQ-C-NNN
   同步更新 product-requirements.md 与 backlog.md
```

---

## ① Inbox 模板

文件名：`inbox/REQ-INBOX-YYYYMMDD-NNN.md`

````markdown
---
id: REQ-INBOX-20260922-001
type: requirement-inbox
status: new
source: user
created: 2026-09-22
---

# 原始需求

## 原始描述

<提出者的原话，尽量逐字记录，不要改写>

## 背景

<需求出现的场景、当时正在做什么、遇到了什么>

## 来源

<用户 / 管理者 / AI Agent 自查 / 运行事故 / 市场反馈 / 技术探索>

## 附加上下文

<相关讨论稿、Issue、链接、附件、涉及的证据编号 E0x>
````

Inbox 状态值：`new` → `analyzed` → `classified` → `archived`（或 `rejected`）。

---

## ② 三类需求判断

| 类型 | ID | 目录 | 一句话判断标准 |
| --- | --- | --- | --- |
| 功能需求 | `REQ-F-NNN` | `features/` | 系统**必须能做什么** |
| 非功能需求 | `REQ-NF-NNN` | `non-functional/` | 必须满足什么**质量属性**（性能/安全/可用/兼容/可观测） |
| 约束需求 | `REQ-C-NNN` | `constraints/` | 外部**限制条件**（技术栈/法规/预算/时间/依赖） |

### 本项目判断示例

| 需求 | 归类 | 理由 |
| --- | --- | --- |
| "能对话中切换项目会话" | `REQ-F` | 系统必须具备的行为 |
| "API 响应 < 200ms" | `REQ-NF` | 性能质量属性 |
| "核心代码不得 import 前端框架" | `REQ-C` | 架构边界限制（已由 ADR-016 裁决） |
| "派工默认单次非交互执行" | `REQ-C` | 运行环境约束（已由 ADR-021 裁决） |
| "证据写失败不得判定 DONE" | `REQ-F` | 系统行为；也含非功能成分，取主项 |
| "预算不足时 adapter 未调用" | `REQ-NF` | 治理可靠性属性 |

**分不清时**：如果一句话能说成"系统要能做 X"，就是 `REQ-F`。
如果必须带数字/阈值/时间窗口，多半是 `REQ-NF`。
如果一句话是"必须/不得 + 外部环境"，是 `REQ-C`。

---

## ③ 正式需求模板

文件名：`features/REQ-F-NNN-<slug>.md`（非功能/约束同理）

````markdown
---
id: REQ-F-001
type: requirement-feature
status: draft
owner:
reviewer:
created: 2026-09-22
updated: 2026-09-22
version: 1.0
---

# REQ-F-001：需求名称

## 1. 基本信息

- ID：REQ-F-001
- 类型：functional / non-functional / constraint
- 状态：
- Owner：
- Reviewer：
- 创建时间：
- 更新时间：
- 来源 Inbox：REQ-INBOX-YYYYMMDD-NNN

## 2. 背景

## 3. 目标

## 4. 需求描述

## 5. 范围

### In Scope

### Out of Scope

## 6. 约束

## 7. 依赖

## 8. 验收条件

## 9. 影响分析

## 10. 状态变化

| 时间 | 旧状态 | 新状态 | 原因 | 变更者 |
| --- | --- | --- | --- | --- |

## 11. 关联文档

- Solution：SOL-NNN
- Decision：ADR-NNN
- Design：
- Plan：
- Task：TASK-NNN（运行时对应 T-NNN）
- Validation：VAL-NNN
- Release：
````

---

## 分流后的同步义务

需求归档到 `features/`/`non-functional/`/`constraints/` 后，必须同步：

1. [`product-requirements.md`](./product-requirements.md) — 更新当前有效需求基线
2. [`backlog.md`](./backlog.md) — 登记状态与优先级
3. [`../00_governance/document-index.md`](../00_governance/document-index.md) — 登记新文档
4. 若涉及技术决策 → 新建 `ADR-NNN`（写入 `../../docs/adr.md`，沿用既有编号，勿占用 013/014）

---

## 本项目需求来源现状

> 核验结论（2026-09-22）：项目**尚未建立正式 REQ 编号体系**。
> 实际需求以**工作包 + 证据索引**形式存在。详见 [`product-requirements.md`](./product-requirements.md)。

既有需求事实的权威来源：

| 来源 | 说明 |
| --- | --- |
| `../../docs/参考/base.md` | 原始用户需求（三级规划、双入口、七页面、对话中修正任务、Model/Role/Executor/Tools 分层、工具配置、提醒） |
| `../../docs/plans/2026-09-17-evidence-driven-remaining-work.md` §3.1–3.10 | W1–W10 工作包，每项带 E0x 证据与验收条件 |

⚠️ `DELIVERY/` 下的讨论稿**不是**本项目的需求来源——分析对象是 Aidean/AideanBot
兄弟项目（基线 `f1068e4`/`205c151`/`5b17da2`，均非本仓库 `eb7a63c`）。
已提交入库仅作存档，不得作为需求或验收依据。

**不要把讨论稿当成需求正文。** 讨论稿是分析过程；正式需求必须进入本目录。
