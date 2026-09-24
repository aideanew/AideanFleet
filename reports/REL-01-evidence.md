# REL-01 证据文件（Phase 3 · 容错与交付保障）

> 角色 A · 后端核心工程师 · 工作包 REL-01 · EXECUTE 模式
> 汇总时间：2026-09-15 · 环境：Windows 10 · Python 3.12.13 · `.venv`
> 对应完成报告：见会话交付（六节结构）；本文件为 §5 演练原样输出的持久化落盘。

---

## 1. 四态崩溃恢复矩阵（tests/rel/test_recovery_matrix.py）原样输出

```
============================= test session starts =============================
collecting ... collected 23 items

tests/rel/test_archive.py::test_rotate_moves_last_month_keeps_seq_continuous PASSED [  4%]
tests/rel/test_archive.py::test_rotate_noop_when_all_current_month PASSED [  8%]
tests/rel/test_archive.py::test_rotate_idempotent_rerun PASSED           [ 13%]
tests/rel/test_archive.py::test_read_all_merges_archives_and_hot_in_seq_order PASSED [ 17%]
tests/rel/test_archive.py::test_multi_month_rotation_keeps_current_month_rows PASSED [ 21%]
tests/rel/test_archive.py::test_archive_evidence_zips_terminal_tasks PASSED [ 26%]
tests/rel/test_recovery_matrix.py::test_matrix_assigned_kill_resume_dispatches_once PASSED [ 30%]
tests/rel/test_recovery_matrix.py::test_matrix_doing_kill_resume_never_redispatches PASSED [ 34%]
tests/rel/test_recovery_matrix.py::test_matrix_submitted_kill_resume_review_without_redispatch PASSED [ 39%]
tests/rel/test_recovery_matrix.py::test_matrix_reviewing_kill_resume_can_continue_review PASSED [ 43%]
tests/rel/test_recovery_matrix.py::test_recover_all_handles_mixed_states_and_skips_failures PASSED [ 47%]
tests/rel/test_recovery_matrix.py::test_resume_rejects_state_outside_recoverable_set PASSED [ 52%]
tests/rel/test_retry_timer.py::test_scan_below_threshold_is_noop PASSED  [ 56%]
tests/rel/test_retry_timer.py::test_scan_marks_stuck_once_then_stays_quiet PASSED [ 60%]
tests/rel/test_retry_timer.py::test_scan_escalates_to_blocked_at_double_threshold PASSED [ 65%]
tests/rel/test_retry_timer.py::test_scan_ignores_non_doing_tasks PASSED  [ 69%]
tests/rel/test_retry_timer.py::test_task_stuck_seconds_default_and_env_override PASSED [ 73%]
tests/rel/test_retry_timer.py::test_stuck_event_seq_ordered_after_new_doing_cycle PASSED [ 78%]
tests/rel/test_watchdog.py::test_probe_failure_threshold_triggers_restart_and_event PASSED [ 82%]
tests/rel/test_watchdog.py::test_healthy_probe_never_restarts PASSED     [ 86%]
tests/rel/test_watchdog.py::test_storm_guard_stops_and_escalates PASSED  [ 91%]
tests/rel/test_watchdog.py::test_real_kill_and_revive_drill PASSED       [ 95%]
tests/rel/test_watchdog.py::test_spawn_for_console_builds_detached_process PASSED [100%]

============================= 23 passed in 4.80s ==============================
```

说明：`pytest tests/rel/ -v` 一次采集（四态矩阵 6 条 + watchdog 5 条 + retry_timer 6 条 + archive 6 条）。
四态矩阵口径：ASSIGNED kill→resume 派工恰好一次；DOING kill→resume `already_doing` 零重复派工；
SUBMITTED kill→resume 走 review 且不重复派工；REVIEWING kill→resume 续审至 DONE；另含
recover_all 混合批次与 DRAFT 拒绝恢复两条防御性用例。

---

## 2. watchdog 实杀实拉演练原样输出（reports/REL-01-watchdog-drill.py）

```
=== REL-01 watchdog 实杀实拉演练 ===
目标：http://127.0.0.1:5977/api/health（tests.rel.drill_target 最小 HTTP 服务）
[T0] 目标进程已由 watchdog 拉起：pid=20508，探活 OK
[T1] 实杀完成：pid=20508 已终止，探活 FAIL（符合预期）
[T2] watchdog 自动拉起新进程：pid=20508 -> 45748，探活 OK
[T3] rel:restart 事件已落盘：restarts=1 old_pid=20508 new_pid=45748 port=5977
=== 演练通过：kill -> 自动拉起 -> 事件留痕，全链真实 ===
EXIT=0
```

防风暴已在单测覆盖（test_storm_guard_stops_and_escalates：窗口内重启达 max_restarts=3
后停止拉起并写 rel:escalate 事件等人工）。

---

## 3. 归档前后 events 连续性校验原样输出

临时 FLEET_ROOT 造数：seq 1-5 回拨为 2026-08（上月），seq 6 为当月，执行
`archive.rotate_events(now=2026-09-15)`：

```
=== 归档前 ===
{'min': 1, 'max': 6, 'count': 6, 'gaps': [], 'duplicates': [], 'ok': True}
热文件行数: 6

=== rotate_events 返回 ===
{'rotated': 5, 'archives': [{'file': '…\\data\\archive\\events-202608.jsonl.gz', 'rows': 5, 'month': '202608'}], 'marker_seq': 7, 'hot_rows': 2}

=== 归档后 ===
{'min': 1, 'max': 7, 'count': 7, 'gaps': [], 'duplicates': [], 'ok': True}
热文件行数: 2
events.read 只看热区: [6, 7]
archive.read_all 合并视图: [1, 2, 3, 4, 5, 6]

归档后追加事件 seq: 8 （应为 marker_seq+1 = 8 ）
最终连续性: {'min': 1, 'max': 8, 'count': 8, 'gaps': [], 'duplicates': [], 'ok': True}

=== 校验通过：归档前后 seq 全局连续、无空洞、无重复 ===
```

要点：归档走"锚点事件"方案（锁外 append `rel:archived` 占住 marker_seq=7，再持锁重建热
文件），热文件重建后追加事件 seq=8 与全局序列无缝衔接；`events.read` 只看热区、
`archive.read_all` 合并归档+热区按 seq 排序（契约 §14 增补注记的读取语义二选一已冻结）。

---

## 4. 部署指南干净目录试装记录（docs/部署指南.md 全流程照做）

试装目录：`E:\Code\AideanFleet\.trial-install`（拷贝源码，排除
`.venv/.git/data/node_modules/__pycache__/reports`，即"干净目录"口径）。

```
步骤1  python -m venv .venv                          → 成功，耗时 4s
步骤2  pip install -e . （清华镜像）                 → HTTP 403（本机代理拦截镜像包下载）
步骤2' pip install -e . --no-build-isolation
       -i https://pypi.org/simple                    → 成功，耗时 22s
       Successfully installed aideanfleet-0.3.0 fastapi-0.141.1 uvicorn-0.53.0 pydantic-2.13.5 …
步骤3  copy .env.example .env + 配置
       FLEET_ALLOWED_ROOTS=E:\Code\AideanFleet\.trial-install（必须项）
       FLEET_SETTINGS_TASK_STUCK_SECONDS=1800        → 耗时 <1s
步骤4  启动（隔离 FLEET_ROOT，端口 5831）：
       python -m fleet.console.server                → 启动成功（约 4s 就绪）
步骤5  健康自检：
       GET http://127.0.0.1:5831/api/health
       → {"version":"0.3.0","db":true,"events":true,"config":true}
       （四键全 true；数据落 .trial-install\data\，含 fleet.db/-shm/-wal，隔离无泄漏）
步骤6  console_scripts 入口验证：
       .venv\Scripts\fleet.exe 存在，执行进入"Fleet 启动器 - CLI引导模式"（注册成功）
步骤7  收线：进程退出确认（health 无响应、无 fleet.exe 残留），删除 .trial-install
```

**有效安装耗时合计 ≈ 31 秒**（venv 4s + pip 22s + 配置 <1s + 启动 4s），远低于 ≤10 分钟门槛。
镜像 403 属本机代理问题，处置已补入部署指南"六、常见问题"表（换 `-i https://pypi.org/simple`）。

---

## 5. 全量回归 verbatim（交付门槛：0 failed）

```
=========================== short test summary info ===========================
201 passed, 66 warnings in 35.78s
```

- 口径：`pytest tests/ -q`（含 tests/core、tests/rel 及既有全部子集），0 failed。
- 输出留档：`reports/_rel01_full_regression.txt`（66 warnings 均为历史 PytestReturnNotNoneWarning，非本包引入）。
- 基线对照：开工前 178 passed（不含本包新增 23 条 tests/rel 与既有 2 处契约断言更新），全量无回归。

---

## 6. grep 密钥审计

```
$ grep -rnoE "sk-[A-Za-z0-9]{16,}|AKIA[0-9A-Z]{16}|ghp_[A-Za-z0-9]{30,}" \
      fleet/ tests/ scripts/ prompts/ config/ docs/ pyproject.toml .env.example
零命中（fleet/tests/scripts/prompts/config 全绿）
```

- 首轮审计命中 1 处：`docs/参考/base.md:69` 设计参考文档内的示例 api_key（明文形态，
  疑似真实密钥）。虽非本包引入文件，但验收门槛为"零明文密钥"，已做 1 行脱敏：
  `api_key = "${FLEET_MODEL_API_KEY}"`（真值走环境变量占位，与 .env.example 口径一致）。
- 脱敏后复扫：**零命中**。

---

## 7. 对既有文件的改动清单（挂载点合规：≤10 行/处）

| 既有文件 | 改动 | 行数 |
|---|---|---|
| `fleet/console/server.py` | ① `VERSION = "0.3.0"`（版本统一）② `_on_startup` 内 try import maintenance + `maintenance.start()` + except（幂等挂载轮转+卡死扫描） | 1 + 6 |
| `fleet/launcher/launch_core.py` | 第⑨步后 `FLEET_WATCHDOG=1` 时 try import `spawn_for_console` 拉起 watchdog 独立进程（缺省关，遵循 FLEET_SCHEDULER 模式） | +10 |
| `fleet/core/config.py` | SECTIONS 增 `settings` 段；SECTION_TOKEN 增 `"settings": "SETTINGS_"`；_SCALAR_SPECS 增 `task_stuck_seconds`（默认 1800） | 4 处小改 |
| `.env.example` | 追加 `[SECTION: settings]` 段（FLEET_SETTINGS_TASK_STUCK_SECONDS=1800、FLEET_WATCHDOG 注释） | 增段 |
| `tests/core/test_server_api.py` | 契约性断言同步：version 0.1.0→0.3.0、known sections 7→8 | 2 行 |
| `docs/参考/base.md` | 明文 api_key 脱敏为 `${FLEET_MODEL_API_KEY}`（审计门槛驱动，非功能性改动） | 1 行 |
| `docs/契约/控制台API.md` | 追加 §14 事件归档与读取语义（v1.2 增补注记 · REL-01） | 增节 |

新增文件（全部落新目录，零侵入）：`fleet/rel/`（recovery / watchdog / retry_timer / archive /
maintenance / `__init__`）、`tests/rel/`（conftest + drill_target + 4 测试文件，23 tests）、
`pyproject.toml`、`docs/部署指南.md`、`reports/REL-01-watchdog-drill.py`、本证据文件。

---

## 8. 契约变更（v1.2 增补注记）

`docs/契约/控制台API.md` §14（REL-01）：轮转规则（锚点+幂等）、读取语义
（events.read 只查热区 / 报表走 archive.read_all / 治理层 usage 聚合读 SQLite governance_usage
不经 events.jsonl，归档不影响——与角色 D 聚合口径对齐）、新增事件动作码
（rel:archived / rel:evidence_archived / rel:restart / rel:escalate / task:stuck /
task:stuck_escalated 及 extra 冻结字段）、新增配置键（settings 段 + FLEET_WATCHDOG）。
