# AGENTS.md — AideanFleet 项目规范

> 版本：v2.0  日期：2026-09-24
> 本文件是所有 Agent（含执行体适配器、Manager、审查器）在 AideanFleet 仓库内工作时的**强制规范**。
> 违反本文件的代码不予合入。

---

## 一、必读规范（按顺序读）

| 序号 | 文件 | 作用 |
|------|------|------|
| 1 | `docs/规划总览.md` | 架构权威来源，24 条取舍结论 |
| 2 | `docs/契约/任务状态机.md` | 10 状态 + 迁移表（FROZEN v1.1） |
| 3 | `docs/契约/任务进度表字段.md` | 15 字段冻结 |
| 4 | `docs/契约/控制台API.md` | REST + WS 端点契约 |
| 5 | `docs/adr.md` | ADR-001 ~ ADR-030 架构决策记录 |
| 6 | `docs/项目开发-多方案评审标准指令.txt` | 开发阶段评审清单 |
| 7 | `.docs/00_governance/project-map.md` | 文档体系总入口 |

---

## 二、环境命令

```bash
# 初始化环境
make setup                    # 创建 .venv + 安装依赖

# 启动控制台
make run                      # → http://127.0.0.1:5000

# CLI 交互模式
make run-cli

# 测试
make test                     # 单元测试
make test-e2e                 # 端到端测试
make test-all                 # 全部测试

# 前端
make frontend-install         # 安装前端依赖
make frontend-build           # 构建前端 → static/

# 清理
make clean-cache              # 清理 __pycache__ / .pyc
make clean-data               # 清空 data/（运行时数据）
```

---

## 三、目录归属规则

```
fleet/
├── core/           控制面核心（状态机、DB、事件、计划）—— 角色A
├── manager/        Manager 逻辑（调度、派工、intake）—— 角色A
├── console/        控制台服务（FastAPI + WS）—— 角色A
├── executors/      执行体适配器 —— 角色C
├── launcher/       启动器 —— 角色C
├── notify/         通知器 —— 角色C
└── prompts/        Prompt 模板（ADR-024）—— 角色A

docs/               工程文档线（设计、契约、计划、参考）
.docs/              治理文档线（规范、标准、追溯链）
tests/              单元测试
tests-e2e/          端到端测试
scripts/            脚本工具
config/             配置文件（notifications.json）
data/               运行时数据（gitignored）
.local/             本地临时文件（gitignored）
初始设计/            历史设计文档（只读归档）
```

---

## 四、依赖方向约束（违反 = 不予合入）

```
fleet/core/        → 不依赖 manager/ 或 console/
fleet/manager/     → 可依赖 core/，不依赖 console/
fleet/console/     → 可依赖 core/ 和 manager/
fleet/executors/   → 可依赖 manager/contracts.py（单向）
fleet/launcher/    → 可依赖所有模块（启动入口）
fleet/notify/      → 独立，最小依赖
```

---

## 五、契约变更铁律

1. `docs/契约/` 下文件为 **FROZEN**，修改需全体维护者签字 + 版本号升级
2. 修改契约 → 必须同步改代码 → 必须同步改测试 → 必须更新 ADR
3. 状态机新增状态/迁移 → 必须更新 `fleet/core/state_machine.py` + `tests/test_state_machine.py`
4. API 新增/删除端点 → 必须更新 `docs/契约/控制台API.md`

---

## 六、禁止行为

| # | 禁止 | 理由 |
|---|------|------|
| 1 | 禁止引入 Redis/MySQL 等外部服务依赖 | ADR-026，违反零外部依赖铁律 |
| 2 | 禁止在 .tf/.py 中硬编码 AK/SK | 安全铁律，用环境变量 |
| 3 | 禁止修改 events.jsonl 历史行 | append-only 铁律 |
| 4 | 禁止跳过状态机直接改 DB 状态 | 状态机是唯一状态变更入口 |
| 5 | 禁止在 core/ 中 import console/ | 依赖方向违反 |
| 6 | 禁止引入 Jinja2 等模板引擎 | ADR-024，str.format 即够 |
| 7 | 禁止自动安装 CLI 执行体 | ADR-027，提供脚本不自动执行 |
| 8 | 禁止 git push --force 不经确认 | 安全铁律 |

---

## 七、结构审计清单（每次提交前自检）

```
[ ] 新增代码不超过 200 行（不含测试）？
[ ] 新增依赖不超过 1 个？
[ ] 是否修改了 FROZEN 契约？（如是→停止）
[ ] 依赖方向是否正确？（core → manager → console）
[ ] 用户输入是否经过验证？
[ ] 密钥/Token 是否通过环境变量传入？
[ ] events.jsonl 写入前是否过 scrub()？
[ ] SQLite 写操作是否在事务内？
[ ] 新增 I/O 是否批量处理？
[ ] 测试是否通过？（make test）
```

---

## 八、Git 提交规范

- commit message 用中文，格式：`[类型] 简述（ADR-XXX）`
- 类型：feat / fix / docs / refactor / test / chore
- 示例：`[feat] 新增 prompt 模板系统（ADR-024）`
- 一个 commit 只做一件事
- 推送到 main 分支前确保 `make test` 通过

---

## 九、文档更新规则

- 代码变更涉及接口语义 → 同步更新契约文档
- 新增 ADR → 更新 `.docs/00_governance/document-index.md`
- 新增文档 → 更新 `.docs/00_governance/project-map.md`
- 文档末尾标注追溯链：上游 / 下游 / 关联 ADR

---

## 十、相关文件

- `SOUL.md` — Agent 人格定义（Manager 角色：苏格拉底式追问）
- `IDENTITY.md` — 身份卡
- `TOOLS.md` — 工具清单
- `USER.md` — 用户画像
- `HEARTBEAT.md` — 心跳检查清单
