# AideanFleet 项目结构规范 (PROJECT-STRUCTURE-SPEC)

> 版本：v1.0  日期：2026-09-24
> 本文件定义 AideanFleet 仓库的目录归属规则、依赖方向约束和文件命名规范。
> 所有贡献者（含 AI Agent）必须遵守。

---

## 一、目录树

```
AideanFleet/
├── fleet/                    # 运行时代码（Python 包）
│   ├── core/                 # 控制面核心：状态机、DB、事件、计划、路径
│   ├── manager/              # Manager 逻辑：调度、派工、intake、DAG、reviewer
│   ├── console/              # 控制台服务：FastAPI + WebSocket
│   │   ├── server.py         # HTTP/WS 服务入口
│   │   ├── web/              # Vue3 前端源码
│   │   │   ├── src/          # TypeScript + Vue 组件
│   │   │   └── dist/         # 构建产物（gitignored）
│   │   └── static/           # 静态资源
│   ├── executors/            # 执行体适配器（fake, mock_write, cline, hermes...）
│   ├── launcher/             # 启动器
│   ├── notify/               # 通知器（邮件触发）
│   ├── governance/           # 治理：用量统计、预算、审批
│   ├── rel/                  # 归档与维护：maintenance, watchdog
│   ├── models/               # 模型池、重试策略、传输层
│   ├── prompts/              # Prompt 模板（打包随 pip 分发）
│   └── gates/                # 机器门：verify, machine
├── docs/                     # 工程文档线
│   ├── 契约/                 # 冻结契约（状态机、字段、API）
│   ├── 参考/                 # 参考资料
│   └── adr.md                # 架构决策记录
├── .docs/                    # 治理文档线
│   ├── 00_governance/        # 规范入口
│   ├── 01_requirements/      # 需求
│   ├── 02_requirements/      # 模拟需求
│   ├── 03_solution/          # 方案
│   └── 04_release/           # 发布
├── tests/                    # 单元测试
├── tests-e2e/                # 端到端测试
├── scripts/                  # 脚本工具
├── config/                   # 配置文件（notifications.json）
├── data/                     # 运行时数据（gitignored）
├── .local/                   # 本地临时文件（gitignored）
├── 初始设计/                  # 历史设计文档（只读归档）
├── AGENTS.md                 # Agent 工作规范
├── Makefile                  # 统一命令入口
├── pyproject.toml            # Python 包配置
├── requirements.txt          # 依赖清单
└── .env.example              # 环境变量模板
```

---

## 二、归属规则

| 目录 | 归属角色 | 可写权限 | 说明 |
|------|----------|----------|------|
| `fleet/core/` | 角色A（控制面） | Manager 审批 | 状态机、DB、事件——冻结契约在此 |
| `fleet/manager/` | 角色A | Manager 审批 | 调度、派工、intake 逻辑 |
| `fleet/console/` | 角色A | Manager 审批 | FastAPI 服务 + Vue 前端 |
| `fleet/executors/` | 角色C（执行体） | 对应执行体 | 适配器实现，单向依赖 contracts |
| `fleet/launcher/` | 角色C | 对应执行体 | 启动入口，可依赖所有模块 |
| `fleet/notify/` | 角色C | 对应执行体 | 通知器，最小依赖 |
| `fleet/governance/` | 角色A | Manager 审批 | 用量统计、预算、审批 |
| `fleet/rel/` | 角色A | Manager 审批 | 归档、watchdog |
| `docs/` | 文档线 | 任何人 | 工程文档，PR 修改 |
| `.docs/` | 治理线 | 任何人 | 治理文档，PR 修改 |
| `tests/` | 测试 | 任何人 | 单元测试 |
| `scripts/` | 工具 | 任何人 | 脚本工具 |
| `data/` | 运行时 | 自动生成 | gitignored，不手动编辑 |
| `.local/` | 临时 | 本地 | gitignored，不提交 |
| `初始设计/` | 归档 | 只读 | 历史文档，不修改 |

---

## 三、依赖方向约束

```
fleet/core/        → 不依赖 manager/ 或 console/（零反向依赖）
fleet/manager/     → 可依赖 core/，不依赖 console/
fleet/console/     → 可依赖 core/ 和 manager/
fleet/executors/   → 可依赖 manager/contracts.py（单向，不反向）
fleet/launcher/    → 可依赖所有模块（启动入口，例外）
fleet/notify/      → 独立，最小依赖（仅 core/events）
fleet/governance/  → 可依赖 core/，不依赖 manager/
fleet/rel/         → 可依赖 core/ 和 manager/
fleet/models/      → 可依赖 core/（模型池、重试、传输）
fleet/gates/       → 可依赖 core/（verify, machine）
fleet/prompts/     → 无依赖（纯模板文件）
```

**铁律**：`fleet/core/` 是最底层，不依赖任何同级行政模块。违反依赖方向的 PR 不予合入。

---

## 四、文件命名规范

| 类型 | 规范 | 示例 |
|------|------|------|
| Python 模块 | `snake_case.py` | `dispatcher.py`, `state_machine.py` |
| Vue 组件 | `PascalCase.vue` | `ChatPage.vue`, `TaskCard.vue` |
| TypeScript | `camelCase.ts` / `PascalCase.ts` | `useWebSocket.ts`, `types.ts` |
| 文档 | 中文或 `kebab-case.md` | `规划总览.md`, `adr.md` |
| 测试 | `test_*.py` | `test_intake_to_done.py` |
| 配置 | `.env.example`, `*.json` | `.env.example`, `notifications.json` |

---

## 五、Git 忽略规则

以下目录/文件不入 git：

| 路径 | 原因 |
|------|------|
| `.venv/` | Python 虚拟环境 |
| `node_modules/` | 前端依赖 |
| `data/` | 运行时数据（DB、事件、证据） |
| `.local/` | 本地临时文件 |
| `fleet/console/web/dist/` | 前端构建产物（hash 每次变化） |
| `__pycache__/` | Python 编译缓存 |
| `.env` | 环境变量真值（只有 `.env.example` 入库） |

---

## 六、变更流程

1. **修改 `fleet/core/`**：需在 `docs/adr.md` 记录 ADR，说明变更原因和影响。
2. **新增执行体适配器**：在 `fleet/executors/` 下新建 `.py`，用 `@register_adapter` 注册。
3. **新增测试**：`tests/` 下按功能域组织，文件名 `test_*.py`。
4. **新增文档**：`docs/` 放工程文档，`.docs/` 放治理文档。
5. **修改本规范**：PR 中说明变更原因，更新版本号和日期。
