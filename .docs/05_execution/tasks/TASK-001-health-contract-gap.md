---
id: TASK-001
type: task
title: 补齐健康判定契约的异常路径测试
status: ready
priority: P0
role: C
work_package: W1
plan_ref: "3.1.1 健康判定契约对齐"
evidence_ref: E15
created: 2026-09-22
updated: 2026-09-22
owner:
reviewer:
---

# TASK-001：补齐健康判定契约的异常路径测试

## 1. 基本信息

- ID：TASK-001
- 类型：测试补齐（test-coverage gap），**不是功能实现**
- 状态：`ready`（条件齐全，可执行；但本轮不执行——见 §13）
- 优先级：P0（W1 属 P0）
- 角色：C（启动器/执行体/可靠性）
- 工作包：W1 可信启动与可用控制台
- 执行方案条目：`3.1.1`
- 证据编号：E15

## 2. 来源（双向追溯）

- Requirement：候选 REQ-F-101（见 `../../02_requirements/product-requirements.md` 候选组 1）
- Solution：无独立 SOL，直接由执行方案驱动
- Plan：`../../../docs/plans/2026-09-17-evidence-driven-remaining-work.md` §3.1
- Work Package：W1
- Decision：无（不涉及新决策；契约 §1 已冻结）
- Evidence Ref：**E15** —— `fleet/launcher/launch_core.py:137-173,257-338`
  健康读 status 但 API 无该键；忽略若干步骤返回值；固定 5000/9900，watchdog 用 request.port
- **运行时任务 ID：无**（本任务尚未产生运行时任务，未写入 SQLite）

> `TASK-001`（文档层）与 `T-NNN`（运行时）是两套 ID，禁止混用。

## 3. 目标

让执行方案 3.1.1 的验收条件「**异常响应不通过**」从"实测成立"变为"有提交的测试断言"，
使该行为可在回归中被守护，而不是只存在于一次性探针中。

## 4. 背景：3.1.1 的真实状态（与勾选框不一致）

⚠️ 执行方案中 3.1.1 的勾选框是 `[ ]` 未勾选，但**实现与大部分测试早已存在**。
这是执行方案 §5.5 已警告过的"勾选框 0 ≠ 无进展"（见
`../../08_knowledge/lessons-learned.md` L-03）。

**已存在的实现**：

| 位置 | 事实 |
| --- | --- |
| `fleet/console/server.py:306-309` | `/api/health` 返回体**恰好四个键** `version/db/events/config`（契约 §1） |
| `fleet/launcher/launch_core.py:173-176` | 消费四键；`version` 须为真非空 str，`db/events/config` 须 `is True` |
| `fleet/launcher/launch_core.py:179-181` | `except Exception` 静默捕获并返回 `console=False` |

**已存在的测试**：

| 测试 | 位置 | 覆盖 |
| --- | --- | --- |
| `test_health_contract` | `tests/test_cli_launch.py:29-43` | 4 个参数化用例：正常四键 / `db=false` / 仅 `status` 键 / `db` 为字符串 |
| `test_health_exact_contract_shape` | `tests/core/test_server_api.py:24-30` | 断言返回键集合恰好为四键、`version=="0.3.0"` |

**唯一缺口**：`_health_check` 的 `except Exception` 异常路径（连接失败、超时、坏 JSON）
**没有任何提交的测试断言**。此前只由本任务的临时探针验证过，探针不留存。

## 5. 输入

### 文档输入

- 执行方案 §3.0（统一原子执行规则）、§3.1（W1）
- 证据索引 E15
- `../../../docs/契约/任务状态机.md`（不涉及，仅确认无影响）

### 前置条件

- ⚠️ **`.venv` 当前不可用**：缺 `.venv/Scripts/pyvenv.cfg`，
  执行方案 §5.1/5.2 给出的 `.venv\Scripts\python.exe` 命令会报
  `No pyvenv.cfg file`。本次改用系统 `Python 3.13.7` 实测通过。
  需在执行前决定：重建 venv，或改命令口径。

### 已知约束

- 契约 §1 冻结：`/api/health` **不得**增删键（`test_health_exact_contract_shape` 是守护）
- 不得修改 `/api/health` 返回形状来"通过"测试
- 不得启动真实服务、不得连接真实端口、不得操作受保护目录
- 不得改动生产代码 `fleet/`（本任务只加测试）

## 6. 输出

任务完成后必须产生：

- `tests/test_cli_launch.py` 新增 2–3 个用例（或一个参数化用例）覆盖异常路径
- 运行结果记录（命令原文 + 退出码 + 通过数）
- 本文件 §14 Completion Record 填写
- `../../task-index.md` 状态更新为 `completed`

**明确不产生**：任何 `fleet/` 下生产代码改动。

## 7. Execution Steps

按 §3.0 的五个四级动作：

- [ ] `.a` 在 `tests/test_cli_launch.py` 增加行为测试：`urlopen` 分别抛
  `urllib.error.URLError`、`TimeoutError`、`ValueError` 时，
  `_health_check` 返回 `{"console": False, "manager": False}`，且不向外抛异常
- [ ] `.b` 运行并记录真实结果（预期为**绿**——行为已实现，不是造红灯）
- [ ] `.c` 最小实现：**无需实现**。若 `.b` 出现红灯，说明行为已回归，
  此时才回到 `launch_core.py:179-181` 修 `except` 分支
- [ ] `.d` 运行目标测试 + 相关回归（见 §9）
- [ ] `.e` 同步证据到 `../../../reports/`，提交独立评审

> 注意 `.a` 的探针签名陷阱：`_health_check` 内部调用
> `urllib.request.urlopen(req, timeout=5)`，用**关键字**传 `timeout`。
> 若替身 lambda 写成 `lambda r: ...` 而不收 `timeout`，所有用例都会误落进 except，
> 得到全 False 的**假绿**。替身必须写成 `def h(req, timeout=5): ...`。

## 8. Acceptance Criteria

- [ ] `urlopen` 抛 `urllib.error.URLError` 时 `console is False`，且测试不抛异常
- [ ] `urlopen` 抛 `TimeoutError` 时 `console is False`
- [ ] `urlopen` 抛 `ValueError`（坏 JSON 路径）时 `console is False`
- [ ] 原有 4 个参数化用例与 `test_health_exact_contract_shape` 全部保持通过
- [ ] `/api/health` 返回键集合未变（仍恰好四键）

## 9. Verification

### 9.1 本任务实测基线（2026-09-22，系统 Python 3.13.7）

```bash
python -m pytest -p no:cacheprovider tests/test_cli_launch.py tests/core/test_server_api.py -q --tb=short
```

**结果：`23 passed, 3 warnings in 1.16s`**（警告为既有 FastAPI `on_event` 弃用与
`datetime.utcnow` 弃用，与本题无关）

### 9.2 七场景探针实测（同一天，临时探针，未提交）

| 场景 | 实测返回 | 判定 |
| --- | --- | --- |
| 正常四键全真 | `console=True, manager=True` | ✓ 应通过 |
| `db=False` | `console=False` | ✓ 不通过 |
| 仅 `status` 键（缺 db/events/config） | `console=False` | ✓ 不通过（对应 E15 的"读 status 但 API 无该键"） |
| `db` 为字符串 `"true"` | `console=False` | ✓ 不通过（严格布尔） |
| `urlopen` 抛 `URLError` | `console=False, manager=False` | ✓ 不通过（**无测试覆盖**） |
| `urlopen` 抛 `TimeoutError` | `console=False, manager=False` | ✓ 不通过（**无测试覆盖**） |
| `urlopen` 抛 `ValueError` | `console=False, manager=False` | ✓ 不通过（**无测试覆盖**） |

结论：**3.1.1 的验收条件「真实API形状通过，缺键/false/异常响应不通过」已全部实测满足。**

### 9.3 执行后应跑的相关回归

```bash
python -m pytest -p no:cacheprovider tests/test_cli_launch.py -q --tb=short
python -m pytest -p no:cacheprovider tests/core/test_server_api.py -q --tb=short
```

预期：目标测试全绿，且相对 9.1 基线**无新增失败**。
（注意：「无新增失败」≠「全绿」，既有失败须如实登记。）

## 10. Evidence

- 本文件 §9.1 / §9.2 的实测记录
- 执行后追加：`../../../reports/W1-3.1.1-health-contract-evidence.md`
  （含命令原文、cwd、退出码、耗时、警告数）
- Commit：待执行阶段安排（执行方案 §3.0 明确"提交须由执行阶段明确安排"）

## 11. Dependencies

### Depends On

- 无（实现已存在，可独立执行）
- 环境前置：`.venv` 重建或命令口径改定（见 §5）

### Blocks

- W1 出口判定（"不依赖真实CLI即可证明启动结果可信"）
- 执行方案 3.1.1 勾选框转绿的**合法性**——补齐测试前，勾选框只能算"实现已验证"，
  不能算"验收已固化"

## 12. Risks

- **假绿风险**（已在 §7 警示）：探针替身不收 `timeout` 关键字参数会全 False，
  可能误判为通过
- **`.venv` 不可用**：执行方案 §5 全部命令基于 `.venv\Scripts\python.exe`，
  当前该路径报 `No pyvenv.cfg file`。这是环境债，会影响所有后续任务
- 契约冻结边界：若有人为"简化"删掉 `except` 分支，异常将外抛，
  启动流程可能中断——本任务的测试正是守护这一点

## 13. Blocked Rules / 本轮为何不执行

本任务**判定为 `ready` 但不执行**，原因：

1. 本任务需新增 `tests/test_cli_launch.py` 用例——属于**代码文件**，
   而本轮工作边界为「只改文档，不改代码」
2. 执行方案 §3.0 明确「提交须由执行阶段明确安排，本轮不提交」

因此本文件只把缺口**精确定位并提交**，实际改动待执行阶段授权后进行。

若执行阶段发现 §4 的判断有误（例如异常路径其实已有测试），
则本任务应置 `status: cancelled` 并在 §14 记录原因，**不得**为凑数强行加测试。

## 14. Completion Record

- 实际完成时间：（未执行）
- 实际结果：（未执行）
- 验证结果：**N/A — 本任务未执行；但 3.1.1 的验收条件已实测全部满足**
- Evidence：本文件 §9.1 / §9.2

---

## 附：本任务带来的口径更正

执行方案 §3.1 的 3.1.1 勾选框此前为 `[ ]`，本任务查明其**实现与 4/7 场景测试已存在且通过**。
建议将勾选框口径修正为「已实现 / 测试覆盖 4/7，异常路径待补」，
而不是直接勾选为完成。

同类情况可能存在于 W1–W10 其余 57 项——**勾选框不可作为进度依据**，
须逐项实测。见 `../../08_knowledge/lessons-learned.md` L-03。
