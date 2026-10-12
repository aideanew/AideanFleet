# AGENTS.md — AideanFleet 项目规范

> 版本：v3.0  日期：2026-10-11（Kernel 重构轮）
> 本文件是所有 Agent（执行体、Planner、worker、控制台）在 AideanFleet 仓库内工作时的规范。
> 规则不再靠文字冻结，靠测试守门：违反者过不了 CI。

---

## 一、必读（按顺序）

| 序号 | 文件 | 作用 |
|------|------|------|
| 1 | `README.md` | 一句话架构 + 快速开始 |
| 2 | `docs/架构.md` | 分层、内核生命周期、import 边界 |
| 3 | `docs/契约.md` | 状态迁移、写回协议、verify 约定（活文档） |
| 4 | `docs/运维指南.md` | 配置/启动/诊断 |
| 5 | `docs/进度与决策.md` | 当前进度与决策记录（改架构先读这里） |

---

## 二、环境命令

```bash
make setup            # 创建 .venv + 安装依赖
make run              # 控制台 → http://127.0.0.1:3100
make test             # 单元测试（pytest，含 timeout 守门）
make test-all         # 全部测试
make frontend-build   # 构建前端 → fleet/console/dist（产物入库）

fleet init / up / doctor / worker / next / writeback / skills   # 新 CLI 入口
```

---

## 三、目录归属

```
fleet/
├── kernel/    单写者状态内核（L0，只依赖标准库）
├── planner/   LLM 规划器（L1）
├── harness/   声明式执行体 profile + 流式执行器（L1）
├── runner/    Turn Runner：worker/packet/gates（L2）
├── cli/       fleet 命令入口
├── core/      旧链路配置(.env) + fleet.toml + 路径/DB/事件
├── console/   FastAPI 控制台 + Vue 前端
├── manager/ gates/ models/ executors/ launcher/ notify/ rel/ governance/   旧链路（保留复用）
tests/
├── architecture/   import 边界测试（守门）
├── core/ rel/ int/ 旧链路测试
└── kernel/ e2e/    内核与 fake-harness e2e 测试
docs/               文档（≤5 份）
```

---

## 四、依赖方向（tests/architecture/test_import_boundaries.py 守门）

```
fleet.kernel      → 只依赖标准库
fleet.planner     → 可依赖 kernel
fleet.harness     → 可依赖 executors.base / core.fleet_toml
fleet.runner      → 可依赖 kernel / harness / planner / core.fleet_toml
受控包禁止 import console / manager / launcher / governance / notify / rel
```

---

## 五、变更铁律（测试守门，不再 FROZEN 签字）

1. 改内核状态迁移 → 同步改 `tests/kernel/`；改契约 → 先改测试再改 `docs/契约.md`。
2. verify 命令必须是真实命令（A5）；`{python}` 占位由 `gates.verify.run_command` 替换。
3. 内核状态变更只走 `Kernel` 方法；events 在同事务落 outbox。
4. 验证通过并写回才算进度、才计费；禁止任何"自称完成"的路径绕过机器门。

---

## 六、禁止行为

| # | 禁止 | 理由 |
|---|------|------|
| 1 | 引入 Redis/MySQL 等外部服务依赖 | 纯 Python + SQLite 零外部依赖 |
| 2 | 在任何文件硬编码 AK/SK/token | 安全铁律，只写环境变量名或 `${VAR}` 占位 |
| 3 | 绕过 kernel.transition 直接 UPDATE 内核表 | 单写者铁律 |
| 4 | 引入 PyYAML/Jinja2 等可避免依赖 | yaml_min / str.format 即够 |
| 5 | git push --force 不经确认 | 安全铁律 |
| 6 | 提交时跳过 `python -m pytest tests -q` | CI 会拦，本地先跑省一轮 |

---

## 七、Git 提交规范

- commit message 用中文，格式：`[类型] 简述`，类型：feat / fix / docs / refactor / test / chore
- 一个 commit 只做一件事；推送 main 前全量测试通过
- 改前端必须重新 `npm run build` 并一并提交 dist
