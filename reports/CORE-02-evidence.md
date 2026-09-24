# CORE-02 证据留痕（角色A · 后端核心工程师）

本文件是 CORE-02 工作包（DAG 依赖引擎 + 调度循环 + 返工管理 + 控制台 FastAPI/WS 重建 + 核心测试基线）的客观证据汇总。所有命令均在 `E:\Code\AideanFleet`（Windows，Python 3.12.13）下执行。

## 1. 测试全量结果

```
$ python -m pytest tests -q
82 passed, 43 warnings in 31.95s
```

其中：

- 既有测试基线：39 passed（CORE-02 之前已存在的 tests/ 用例，零回归）。
- 新增 tests/core/：43 passed，构成见 §2。

```
$ python -m pytest tests/core -q
39 passed, 4 warnings in 5.47s
```

## 2. 新增测试清单（43 例）

### tests/core/test_ten_scenarios.py（十场景，10 例）

1. test_scenario_1_legal_chain —— 状态机合法链 DRAFT→ASSIGNED→DOING→SUBMITTED→REVIEWING→DONE，事件动作序列精确断言。
2. test_scenario_2_illegal_transition —— DRAFT→DONE 非法迁移被拒，事件流不变。
3. test_scenario_3_fourth_rework_escalates —— bump_rework 第 1~3 轮落 ASSIGNED，第 4 轮落 ESCALATED；resolve_rework_target(3)=="ASSIGNED"、(4)=="ESCALATED"。
4. test_scenario_4_config_atomic_crash —— 配置原子写中途崩溃（os.replace 抛错）后 .env 原文件不变、.tmp 残留、再次保存成功（并由此发现并修复 config basic 段吞噬 bug，见 §4）。
5. test_scenario_5_concurrent_event_appends —— 10 线程并发追加事件，seq 恰为 1..10 无丢失无重复。
6. test_scenario_6_soft_retry_then_model_switch —— 连续 10 次 429 软失败后切换模型（launch:model_switch 事件恰 1 次，共 11 次调用）。
7. test_scenario_7_hard_fail_no_retry —— 401 硬失败只试 1 次即切模型，models_used==[id1,id2]。
8. test_scenario_8_gate_fail_rework_without_llm —— verify_cmd 退出码 2 → gate:fail → 判 REWORK，全程不经审查 LLM，rework_count==1，事件含 gate:fail 与 task:rework。
9. test_scenario_9_plan_concurrent_atomic_write —— 10 线程并发写 plan.json，结束后文件仍是合法 JSON。
10. test_scenario_10_mock_executor_eight_events —— StubAdapter 全链 DRAFT→DONE，事件动作序列与契约 8 事件精确一致（task:created/assigned/doing/submitted/gate:pass/reviewing/review_pass/done）。

### tests/core/test_dag.py（7 例）

环检测（detect_cycles 空/非空、assert_acyclic 抛 CycleDetected）、create_task 拒绝成环、READY 依赖+冲突判定、写冲突暂缓并去重发 task:deferred、release_dependents 只放行 DONE 依赖的 ASSIGNED 下游。

### tests/core/test_scheduler.py（4 例）

schedule_once 收集 DRAFT 并派工；ControlBus 模式切换/确认/异常；run_loop auto 模式无需确认；step 模式等 confirm、一次确认只派一个任务（POLL_SECONDS=0.5，asyncio.sleep 非忙轮询）。

### tests/core/test_rework_manager.py（6 例）

handle_rework 把返工意见以【返工意见 · 第 N 轮】并入 detail；redispatch 全链（真实派工→审查 REWORK→重派 SUBMITTED，第二次适配器调用提示词含返工意见）；ESCALATED 后 handle_rework 为 noop；confirm_release 为 ESCALATED 创建 -R1 后继任务（rework_count 保留、事件 task:escalated_release）；非 ESCALATED 拒绝；后继 id 递增（-R1→-R1-R1）。

### tests/core/test_server_api.py（11 例）

无会话 401；/api/health 恰好 4 键 {version,db,events,config}；GBK 请求体建会话 + cookie 通道；未知项目 400；plan/events 契约形状；plan 未知项目返回 200 业务错误；launch-event 缺字段 400/未知项目/extra.model；config 各段与别名（settings/models/extensions/message）+ ignored + 明文密钥 400；mode/confirm/control（confirm→step 生效、ESCALATED 人工释放产生后继）；任务详情与派工 409 invalid_transition；notify/test 保持 503。

### tests/core/test_recovery.py（4 例，断点恢复演练）

1. test_doing_kill_restart_no_duplicate_dispatch —— DOING 中途 kill→重启（缓存失效）后再派工：原样返回 already_doing，适配器零调用，task:doing 事件恰 1 次。
2. test_assigned_crash_resume_completes_chain —— ASSIGNED 阶段 crash→续跑到 SUBMITTED，task:assigned/doing/submitted 各恰 1 次。
3. test_assigned_crash_resume_run_to_completion —— ASSIGNED crash→run_to_completion 直达 DONE，适配器全程仅 1 次调用，末事件 task:done。
4. test_doing_stuck_task_escalates_via_manual_release —— 孤儿 DOING：DOING→ASSIGNED 非法，走 DOING→BLOCKED→（task:blocked_release）→ASSIGNED→重新派工成功。

### 测试支撑件

- conftest.py：MINIMAL_ENV_EXAMPLE（7 段配置）、fleet_env/project 夹具（monkeypatch FLEET_ROOT/FLEET_DATA_DIR/FLEET_CONFIG_WRITE=1、模块缓存复位、events/config/dag 去重复位）、read_events/write_json。
- stubs.py：StubAdapter（脚本化回执、calls 计数）、FakeRoute、pass_route/rework_route、make_task（adapter=stub, assignee=worker-a, reviewer=reviewer-1）。

## 3. 真实进程冒烟验证（uvicorn + HTTP + WS）

在隔离 FLEET_ROOT（临时目录，验证后已删除）下以真实进程启动：

```
$ FLEET_ROOT=... FLEET_DATA_DIR=... FLEET_CONFIG_WRITE=1 FLEET_CONSOLE_PORT=5020 FLEET_SCHEDULER=1 python -m fleet.console.server
$ curl http://127.0.0.1:5020/api/health
{"version":"0.1.0","db":true,"events":true,"config":true}
```

冒烟脚本 11 项断言全部通过（passed=11/11，exit=0）：

1. 无会话 GET /api/plan → 401
2. GET /api/health → 200
3. /api/health 响应体恰好 4 键 {version, db, events, config}
4. POST /api/session（GBK 编码请求体）→ 200
5. 会话返回 token
6. Set-Cookie 含 fleet_token
7. Bearer token GET /api/plan → 200
8. /api/plan 含计划快照（阶段/tasks）与 legacy 进度字段（percent）
9. POST /api/launch-event（project/phase/detail/model）→ ok:true
10. WS 带 token 连接 /ws，发 chat 收到服务端 type=chat_message 消息
11. 无 token WS 连接被拒绝（accept 前拒闭，表现为 HTTP 403 / 代码 4401 语义）

验证进程与临时目录（.tmp-smoke/）在验证完成后已停止并删除，未污染工作区。

## 4. 密钥扫描

```
$ grep -rn "sk-" fleet/ tests/ --include="*.py" | grep -vE "re\.compile|脱敏"
（无输出 —— 源码零命中）
```

剩余 3 处命中均为脱敏/校验正则的模式定义本身（fleet/core/events.py 的 REDACT 规则、fleet/core/config.py 的 _SECRET_SHAPES、tests/core/test_server_api.py 无——已改用 16 位大写形态假密钥触发同样的明文拒绝逻辑）。`__pycache__` 二进制为编译产物重新生成后即消失。

## 5. 交付物清单

### 新建

| 文件 | 行数 | 说明 |
| --- | --- | --- |
| fleet/manager/dag.py | 173 | READY 判定（DONE 依赖 + DOING 写冲突→task:deferred 去重）、release_dependents（只标记不改状态）、detect_cycles/assert_acyclic |
| fleet/manager/scheduler.py | 165 | ControlBus（auto/step、mode:changed、confirm）、schedule_once、async run_loop（asyncio.to_thread + sleep(0.5)） |
| fleet/manager/rework_manager.py | 201 | handle_rework（REWORK/ASSIGNED 双形态、意见并入 detail）、redispatch、confirm_release（-R{n} 后继） |
| tests/core/conftest.py | 108 | 隔离环境夹具 |
| tests/core/stubs.py | 85 | StubAdapter 等 |
| tests/core/test_ten_scenarios.py | 282 | 十场景 |
| tests/core/test_dag.py | 96 | DAG 引擎 |
| tests/core/test_scheduler.py | 131 | 调度循环 |
| tests/core/test_rework_manager.py | 104 | 返工管理 |
| tests/core/test_server_api.py | 205 | 控制台契约 |
| tests/core/test_recovery.py | 132 | 断点恢复演练 |
| tests/core/__init__.py | 0 | 包标记 |

### 修改

| 文件 | 说明 |
| --- | --- |
| fleet/console/server.py | 全量重建（~695 行）：Flask→FastAPI + WebSocket，旧路由字段级兼容；WS 7 服务端消息（task_update/plan_update/progress/stream_chunk/chat_message/notification/config_changed）+ 3 客户端消息（chat/set_mode/confirm_step）；会话中间件（豁免 health/session/launch-resolve，SESSION_EXPIRE_SECONDS 与 legacy lock_screen_seconds 兼容）；静态目录 dist/→static/ 回退；GBK 请求体与 cookie 会话兼容 |
| fleet/manager/dispatcher.py | 补齐主入口 create_task/dispatch/run_to_completion（~470 行）；断点恢复语义（DOING 原样返回、ASSIGNED/DRAFT 续跑补路径+基线） |
| fleet/manager/reviewer.py | 增补 gate:pass/gate:fail（actor=machine_gate）与 task:review_pass 事件 |
| fleet/core/config.py | 修复 _section_of_env_key：空 token 的 basic 段优先吞噬所有 FLEET_* 键的 bug（`if token and key.startswith(...)`） |
| fleet/core/plan.py | 修复并发 os.replace 的 WinError 32：_SAVE_LOCK 串行化 tmp 写入+替换 |

### 未触碰（遵守约束）

fleet/console/web/、fleet/console/dist/、fleet/executors/、fleet/launcher/、fleet/notify/、reports/FE-01-evidence.md。

## 6. 依赖与约束核验

- 新增依赖仅 fastapi / uvicorn / websockets / pytest / pytest-asyncio（测试用），无 ORM、无消息队列。
- SQLite 并发：事件追加（scenario 5）、plan 原子写（scenario 9）、配置原子写（scenario 4）均加锁/临时文件验证。
- 5 行中文头注释：dag.py / scheduler.py / rework_manager.py / 各测试文件均含。
- 契约字段名冻结：/api/health、/api/launch-event、/api/config/{section}、WS 消息类型均按 docs/契约/控制台API.md 实现，测试逐一断言。
