# AideanFleet

自研「薄控制面 + 单写者内核 + 可插拔执行体」的多 CLI Agent 舰队编排器。Python + SQLite，零重型依赖；模型池与中文控制台是差异化能力。

## 一句话架构

```
入口：fleet CLI(init/up/down/service/run/doctor/worker/next/writeback/skills) · Web 控制台(投影+typed 动作) · 宿主内 /fleet skill
        ↓
Fleet Kernel（单写者）：goal · todo · claim/lease · gate · attempt · evidence · quota · events(outbox)
        ↓                          ↓
Turn Runner（fleet worker）    Planner（kind=plan 的 todo，LLM 出 JSON 计划，schema 校验后写入）
        ↓
Harness Profiles（claude/codex/opencode 声明式 YAML）+ Model Router（OpenAI 兼容池，服务直连模型角色）
```

- 状态机：`open → claimed → running → verifying → done | blocked | needs_user | superseded`
- 返工 = 同 lineage 的 successor todo；轮数超限自动 `needs_user`
- **验证通过并写回才算进度，写回才计费**（quota）
- 租约过期自动回收：worker 被 kill 后从断点接续

## 快速开始

**方式一（Windows 普通用户，推荐）**：使用 CI 构建的安装器（`installer.yml` 产物，按用户安装，自带私有 Python + Node，双击即用；公开发布渠道见 docs/进度与决策.md J-04）。安装后从开始菜单「AideanFleet」启动，或运行 `fleet service install` 设置开机自启。

**方式二（开发者）**：

```bash
python -m venv .venv
.venv\Scripts\activate          # Windows；Linux/macOS: source .venv/bin/activate
pip install -r requirements.txt
pip install -e .
fleet init        # 向导：扫描已装 CLI、探测模型 key、生成 fleet.toml
                   #   Node.js 缺失时提示一键安装（Linux/macOS 自动下载）
fleet doctor      # 执行体/配置体检（--config 查看生效值与来源）
fleet up          # 拉起 api(控制台 :3100) + worker，日志在 data/logs/
fleet down        # 停止 fleet up 拉起的进程（含 watchdog）
fleet service install   # 可选：开机自启（用户级 Startup，免管理员）
fleet run         # 旧交互式启动（兼容保留）
```

浏览器打开 `http://127.0.0.1:3100`。宿主内驱动（推荐）：`fleet skills install` 后在 Claude Code / Codex / OpenCode 里用 `/fleet <任务>`。

## 目录

| 路径 | 职责 |
| --- | --- |
| `fleet/kernel/` | 单写者状态内核（SQLite WAL，import 边界测试守门） |
| `fleet/runner/` | worker 进程：packet → harness → gate → writeback |
| `fleet/harness/` | 声明式执行体 profile（YAML）+ 流式解析器 + 探测 |
| `fleet/planner/` | LLM 规划器（计划 JSON schema 硬校验） |
| `fleet/core/` | 旧链路配置(.env) + fleet.toml 新配置 + 路径/DB/事件 |
| `fleet/console/` | FastAPI 控制台 + Vue 前端（dist 已入库，无 Node 也有 UI） |
| `fleet/manager/` `fleet/gates/` `fleet/models/` | 旧链路：dispatcher/scheduler、TaskPack 机器门、模型池路由（保留复用） |
| `fleet/cli/` | `fleet` 命令入口 |
| `tests/` | architecture（import 边界）/ core / kernel / e2e（fake harness goal→done） |

## 文档

- [docs/架构.md](docs/架构.md) — 分层、内核生命周期、import 边界
- [docs/运维指南.md](docs/运维指南.md) — 安装/部署/配置/诊断
- [docs/契约.md](docs/契约.md) — kernel 状态迁移、写回协议、HTTP API（不再是 FROZEN，靠测试守门）
- [docs/进度与决策.md](docs/进度与决策.md) — 当前进度与本轮重构决策记录
