# Contracts · 契约索引（指针）

> 类型：contract-index ｜ 状态：pointer ｜ 更新：2026-09-22
>
> **三份契约保持原地不动，均为 FROZEN。** 本文件只做导航与关键事实摘录。

---

## 三份契约

| 契约 | 文件 | 版本 | 唯一权威实现 |
| --- | --- | --- | --- |
| 任务状态机 | [`docs/契约/任务状态机.md`](../../docs/契约/任务状态机.md) | **FROZEN v1.1** | `fleet/core/state_machine.py` |
| 任务进度表字段 | [`docs/契约/任务进度表字段.md`](../../docs/契约/任务进度表字段.md) | **FROZEN v1.2** | `fleet/core/db.py` |
| 控制台 API | [`docs/契约/控制台API.md`](../../docs/契约/控制台API.md) | v1.1 | `fleet/console/server.py` |

**契约之间的同源关系**（三份文件互相引用，字段名必须一致）：

```text
任务状态机.md  ──exec_status 取值──►  任务进度表字段.md
任务进度表字段.md  ──对外字段名──►  控制台API.md
```

---

## 关键事实速查

### 状态机（10 状态）

`DRAFT` → `ASSIGNED` → `DOING` → `SUBMITTED` → `REVIEWING` → `DONE` / `PARTIAL`
分支：`REWORK`（返工）、`BLOCKED`（阻塞）、`ESCALATED`（升级，终态）

* 合法迁移 14 条，新增迁移必须**同时**改迁移表 + 状态机实现 + 单测
* 唯一权威实现 `fleet/core/state_machine.py`，**任何其他模块不得自行判断状态合法性**
* 状态名、迁移方向、异常名一经冻结**不得改名**

**返工升级口径（易错）**：

* 迁移 #12 `REWORK → ASSIGNED`：`rework_count <= 3`，事件 `task:rework_dispatch`
* 迁移 #13 `REWORK → ESCALATED`：`rework_count > 3`，事件 `task:escalated`
* 即 **第 4 次返工升级**。历史"×3 即升级"的模糊口径不可沿用。

### 字段契约

* `tasks` 表 **15 个契约字段**，字段名与顺序冻结
* `task_id` 形如 `T-001`，TEXT 主键
* 必填字段：`task_id`、`role`、`task_type`、`exec_status`、`updated_at`
* `token` 未知时为 `NULL`，**不得填 0 冒充**
* v1.2 新增三扩展列：`context_budget` / `memory_refs` / `retry_context`（§2.1）

### 磁盘布局（设计原则，源自 `初始设计/d7.md`）

```text
SQLite（data/fleet.db）    存"现在在哪"     ← 路径可由 FLEET_DATA_DIR 覆盖
events.jsonl               存"发生过什么"
evidence 目录              存"证据在哪"
```

**三者不得混用。**

v1.2 新增 `data/memory/<project_id>.json`（Project Memory，条目 schema 见 `控制台API.md` §13.3）。

### 运行时权威 vs 快照

```text
数据库 = 运行时权威状态
plan.json = 人类可读快照
方向：DB → plan.json（单向，不双向同步）
```

---

## 契约优先级

**契约与 ADR 的优先级高于所有 `.docs/` 文档。**

`.docs/` 任何文件（含 `00_governance/document-standard.md`）都**不得重定义**：

* 状态机状态名、迁移方向、事件动作码
* 契约字段名、类型、必填性
* API 路径、请求/响应形状

如需扩展 → 走 ADR 流程（下一个编号 **ADR-024**，写入 `docs/adr.md`），
然后按契约文件的版本记录方式原位升级（参考任务字段契约 v1.1→v1.2 的做法）。

---

## 冻结流程

```text
提议变更
  ↓
新增 ADR（记录 Context / Problem / Options / Decision / Rationale / Consequences）
  ↓
影响分析（哪些模块依赖该语义）
  ↓
同步修改契约文档 + 实现 + 单测
  ↓
记录版本变更（旧版本记录保留，标注升级原因）
```
