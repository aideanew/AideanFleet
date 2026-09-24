# 端到端主流程文档

> 版本：v1.0  日期：2026-09-24
> 上游：docs/规划总览.md, fleet/launcher/launch_core.py
> 下游：fleet/manager/intake.py, fleet/manager/dispatcher.py, fleet/manager/scheduler.py
> 关联 ADR：ADR-030, ADR-017, ADR-021

---

## 一、文字流程图

```
用户执行 `make run` 或 `python run_interactive.py`
       │
       ▼
┌──────────────────────────────────┐
│  1. 启动核心 (launch_core.py)     │
│     ├─ 环境探测 (Python/端口/路径) │
│     ├─ 端口预检 (5000 是否占用)    │
│     ├─ 确保 .env 文件存在          │
│     ├─ 启动控制台服务 (FastAPI)    │
│     ├─ 启动 Manager 网关           │
│     ├─ 健康检查                    │
│     ├─ 项目注册 (SQLite)           │
│     ├─ 打开浏览器 :5000            │
│     └─ 拉起事件监听循环            │
└──────────────────────────────────┘
       │
       ▼
┌──────────────────────────────────┐
│  2. 控制台就绪 (console/server.py) │
│     ├─ 锁屏页面 (token 验证)       │
│     ├─ WebSocket 连接建立          │
│     └─ 7 页前端就绪                │
└──────────────────────────────────┘
       │
       ▼
┌──────────────────────────────────┐
│  3. 接收需求 (intake.py)          │
│     ├─ 检测启动意图               │
│     ├─ 检测模式 (auto/step)       │
│     ├─ 创建项目 (db.create_project)│
│     ├─ 生成三级计划 (plan.json)   │
│     └─ 创建任务 (db.create_task)  │
└──────────────────────────────────┘
       │
       ▼
┌──────────────────────────────────┐
│  4. 锁定与配置                    │
│     ├─ 锁屏 token 验证            │
│     ├─ 会话超时配置               │
│     └─ 角色→模型映射加载          │
└──────────────────────────────────┘
       │
       ▼
┌──────────────────────────────────┐
│  5. 配置 Manager                   │
│     ├─ 加载 .env 角色配置          │
│     ├─ 加载执行体适配器            │
│     └─ 初始化调度器 (scheduler)   │
└──────────────────────────────────┘
       │
       ▼
┌──────────────────────────────────┐
│  6. 分解任务 (dispatcher.py)      │
│     ├─ DRAFT → ASSIGNED (分配)    │
│     ├─ ASSIGNED → DOING (执行)    │
│     ├─ 派工给执行体 (单次非交互)   │
│     ├─ 生成 baseline.json 快照    │
│     └─ DOING → SUBMITTED (回执)   │
└──────────────────────────────────┘
       │
       ▼
┌──────────────────────────────────┐
│  7. 组装执行体                     │
│     ├─ 读取角色配置                │
│     ├─ 构造 CLI 命令               │
│     ├─ 注入 prompt (模板 ADR-024) │
│     ├─ 启动子进程                  │
│     └─ 登记运行时 (registry)      │
└──────────────────────────────────┘
       │
       ▼
┌──────────────────────────────────┐
│  8. 监控 (scheduler.py)           │
│     ├─ 0.5s 定拍轮询              │
│     ├─ auto 模式: 自动推进         │
│     ├─ step 模式: 等待人工确认     │
│     ├─ WebSocket 实时推送状态      │
│     └─ 事件流 append (events.jsonl)│
└──────────────────────────────────┘
       │
       ▼
┌──────────────────────────────────┐
│  9. 验证 (gates/verify.py)        │
│     ├─ 机器门: 证据存在性检查      │
│     ├─ 六节报告完整性             │
│     ├─ 文件路径注入检查           │
│     ├─ SUBMITTED → REVIEWING      │
│     ├─ 审查通过 → DONE            │
│     ├─ 审查驳回 → REWORK           │
│     └─ 异常 → BLOCKED/ESCALATED   │
└──────────────────────────────────┘
       │
       ▼
┌──────────────────────────────────┐
│ 10. 循环                          │
│     ├─ 阶段内任务并行              │
│     ├─ 阶段间串行 (依赖前阶段完成) │
│     ├─ 全部 DONE → 项目完成        │
│     └─ 回到步骤 6 处理下一任务     │
└──────────────────────────────────┘
```

---

## 二、代码引用

| 步骤 | 代码文件 | 关键函数 |
|------|---------|---------|
| 1. 启动核心 | `fleet/launcher/launch_core.py` | `launch_core(LaunchRequest)` |
| 2. 控制台就绪 | `fleet/console/server.py` | `FastAPI app`, `_on_startup()` |
| 3. 接收需求 | `fleet/manager/intake.py` | `detect_launch_intent()`, `start_project()` |
| 4. 锁定与配置 | `fleet/console/server.py` | `_check_token()`, `_load_env()` |
| 5. 配置 Manager | `fleet/manager/scheduler.py` | `Scheduler.__init__()`, `_load_roles()` |
| 6. 分解任务 | `fleet/manager/dispatcher.py` | `dispatch()`, `run_to_completion()` |
| 7. 组装执行体 | `fleet/executors/base.py` | `run_subprocess_tree_safe()`, `register_adapter()` |
| 8. 监控 | `fleet/manager/scheduler.py` | `run_loop()`, `schedule_once()` |
| 9. 验证 | `fleet/manager/gates/verify.py` | `verify_evidence()`, `check_gate()` |
| 10. 循环 | `fleet/manager/scheduler.py` | `run_loop()` 内的 while True |

---

## 三、状态机联动

主流程中每一步对应的状态迁移：

```
启动:    (无状态) → 项目创建
步骤3:   DRAFT (任务草稿)
步骤6:   DRAFT → ASSIGNED → DOING → SUBMITTED
步骤9:   SUBMITTED → REVIEWING → DONE / REWORK / BLOCKED / ESCALATED
步骤10:  下一任务回到 DRAFT → ASSIGNED ...
```

状态机定义：`fleet/core/state_machine.py`（FROZEN v1.1）
契约文档：`docs/契约/任务状态机.md`

---

## 四、断点恢复

任一步骤中断后，重新启动会发生：

| 中断点 | 恢复行为 |
|--------|---------|
| 启动中断 | 重新 `make run`，launch_core 幂等 |
| 控制台中断 | SQLite 状态持久化，重启后恢复 |
| 任务执行中断 | DOING 状态任务重新 dispatch，不重复派工 |
| 审查中断 | SUBMITTED 状态保持，等待审查 |
| 事件流中断 | events.jsonl append-only，无数据丢失 |

---

## 五、模式切换

| 模式 | 值 | 行为 |
|------|-----|------|
| 调度-auto | `auto` | 任务自动推进，无需人工确认 |
| 调度-step | `step` | 每步需人工确认才推进 |
| UI-run | `run` | 正常执行模式 |
| UI-intake | `intake` | 接收需求模式 |
| UI-audit | `audit` | 审查模式 |
| UI-discuss | `discuss` | 讨论模式 |
| UI-plan | `plan` | 计划模式 |

模式切换通过 `/api/mode` 端点或 WebSocket `set_mode` 消息。
