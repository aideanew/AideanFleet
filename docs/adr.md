# AideanFleet 架构决策记录（ADR）

> 编号脉络：ADR-001 ~ ADR-012 源自 `初始设计/d7.md`（收敛建议），ADR-015 源自 `初始设计/d9.md`；
> ADR-013/014 留空未占用；ADR-016 起为本项目实施阶段的新增裁决（工作包 CORE-03 落盘，2026-09-15）。
> 每条 ADR 一句话结论 + 理由 + 裁决日期；变更既有 ADR 必须标注 SUPERSEDED 并指向替代者。

---

## ADR-001：不使用第三方 Agent 框架做核心 Orchestrator

- 状态：ACCEPTED
- 原文（`初始设计/d7.md`）：不用 MetaGPT/CrewAI/LangGraph/Mastra/OpenClaw 做核心 Orchestrator。
- 理由：这些框架的抽象层（Role/Task/Crew）与本项目"契约驱动+事件溯源+Machine Gate"的控制面设计冲突，
  引入它们会导致双控制流并存的复杂性。自研薄 Control Plane 更可控。
- 裁决日期：2026-09-10（d7.md 收敛建议冻结）

## ADR-002：Python 3.11+ 自研薄 Control Plane

- 状态：ACCEPTED
- 原文（`初始设计/d7.md`）：Python 3.11+ 自研薄 Control Plane。
- 理由：Python 生态与 LLM 工具链（SDK/CLI）最贴合；3.11+ 提供 match 语句、异常组等特性。
  "薄"意味着 Control Plane 只管调度/状态/事件，不碰业务逻辑。
- 裁决日期：2026-09-10

## ADR-003：所有 Coding Agent 视为 Worker Backend

- 状态：ACCEPTED
- 原文（`初始设计/d7.md`）：Claude Code / Codex / OpenCode / pi 全部视为 Worker Backend。
- 理由：Agent 是执行资源，不是系统核心。统一通过 Adapter 层适配，差异隔离在 Adapter 内。
- 裁决日期：2026-09-10

## ADR-004：CLI 差异只能存在于 Adapter 层

- 状态：ACCEPTED
- 原文（`初始设计/d7.md`）：CLI 差异只能存在于 Adapter 层。
- 理由：不同 Coding Agent CLI 的调用方式、输出格式、退出码各异，但 Manager 不应感知这些差异。
  Adapter 模式保证核心逻辑不被 CLI 变更污染。
- 裁决日期：2026-09-10

## ADR-005：确定性恢复由 Policy Engine 执行

- 状态：ACCEPTED
- 原文（`初始设计/d7.md`）：确定性恢复由 Policy Engine 执行，Manager 不处理机械重试。
- 理由：重试、降级、超时等恢复策略是确定性规则，不应由 Manager（可能调用 LLM）处理。
  Policy Engine 作为纯函数闸门，按规则决定 retry/fail/escalate。
- 裁决日期：2026-09-10

## ADR-006：Machine Gate 权威高于 Agent 自述

- 状态：ACCEPTED
- 原文（`初始设计/d7.md`）：Machine Gate 权威高于 Agent 自述。
- 理由：Agent 可能报告"任务完成"但实际产物不达标。Machine Gate（编译/测试/lint 等确定性检查）
  的判定结果权威，Agent 自述仅作参考。这与 ADR-015"LLM 可以提出决策，但不能直接改变事实"一致。
- 裁决日期：2026-09-10

## ADR-007：Evidence immutable/raw-first

- 状态：ACCEPTED
- 原文（`初始设计/d7.md`）：Evidence immutable/raw-first，report.html 从事实数据生成。
- 理由：验收依据必须是不可变的原始证据（stdout/stderr/exit code/产物文件），而非 Agent 的总结。
  report.html 从原始证据数据生成，不作为权威源。
- 裁决日期：2026-09-10

## ADR-008：并发写任务使用独立 git worktree + Lease

- 状态：ACCEPTED
- 原文（`初始设计/d7.md`）：每个并发写任务使用独立 git worktree；共享资源使用 Lease。
- 理由：多 Agent 并发写同一仓库会冲突。每任务一个 worktree 实现物理隔离；共享资源（如 DB）
  通过 Lease 机制串行化访问。
- 裁决日期：2026-09-10

## ADR-009：SQLite 存状态，JSONL 存事件，filesystem 存 artifact

- 状态：ACCEPTED
- 原文（`初始设计/d7.md`）：SQLite 存状态，JSONL 存事件，filesystem 存 artifact/evidence。
- 理由：三种存储各司其职——SQLite 支持事务和查询（任务状态）；JSONL append-only 不可变
  （事件溯源）；filesystem 存大文件（产物、证据）。不引入消息中间件或 ORM。
- 裁决日期：2026-09-10

## ADR-011：MCP 不代替内部 Scheduler/Event Bus

- 状态：ACCEPTED
- 原文（`初始设计/d7.md`）：MCP 是未来工具协议，不拿 MCP 代替内部 Scheduler/Event Bus。
- 理由：MCP（Model Context Protocol）适合工具调用场景，但本项目的事件总线和调度器
  是确定性控制面组件，不应依赖外部协议。MCP 留作未来工具层接入。
- 裁决日期：2026-09-10

## ADR-012：OpenClaw 不进入开发工厂核心依赖

- 状态：ACCEPTED
- 原文（`初始设计/d7.md`）：OpenClaw 保留给未来运营/客服/常驻 Agent 层，不进入当前开发工厂核心依赖。
- 理由：OpenClaw 作为常驻 Agent 适合运营/客服场景，但开发工厂的核心是"一次性任务编排"，
  不需要常驻 Agent。保持核心依赖最小化。
- 裁决日期：2026-09-10

## ADR-013（留空未占用）

> 编号保留，未分配决策内容。

## ADR-014（留空未占用）

> 编号保留，未分配决策内容。

## ADR-015：组织智能层与执行控制层分离

- 状态：ACCEPTED
- 原文（`初始设计/d9.md`）：组织智能层（需求理解/规划/分工/任务生成/语义判断）与
  执行控制层（DAG/Scheduler/State/Event/Lease/Worktree/Machine Gate/Policy/Evidence）分离。
- 理由：LLM 可以提出决策，但不能直接改变事实。组织智能层调用 LLM 做语义判断，
  执行控制层按确定性规则执行。两层通过 TaskPack 契约衔接。
- 裁决日期：2026-09-12（d9.md 新增冻结）

---

## ADR-010（SUPERSEDED）：MVP UI 使用 Streamlit，但核心代码不得依赖 Streamlit

- 状态：**SUPERSEDED**（被 ADR-016 取代）
- 原文（`初始设计/d7.md`）：MVP UI 使用 Streamlit，但核心代码不得依赖 Streamlit。
- 作废理由：用户定稿深色科技风 Vue3 设计（网页控制端 v1.0，角色B FLEET-FE-01 交付），
  Streamlit 路线不再使用；"核心代码不得依赖前端框架"的边界原则保留并由 ADR-016 继承。
- 裁决日期：2026-09-15（CORE-03 复核确认作废）

## ADR-016：前端 = Vue3 + Vite + Pinia，核心代码零前端依赖

- 状态：ACCEPTED（取代 ADR-010）
- 结论：网页控制端前端采用 Vue3 + Vite + Pinia（深色科技风），产物构建到 `fleet/console/dist/`；
  `fleet/core/`、`fleet/manager/` 等核心代码不得 import 任何前端框架或构建工具。
- 理由：控制端是实时看板（WS 推送、多视图状态共享），Vue3+Pinia 的响应式模型比 Streamlit
  服务端重绘更适合；同时保持"后端可无前端独立运行"的边界（static/ 目录兜底）。
- 裁决日期：2026-09-15

## ADR-017：端口定版 —— UI = 控制台 = 5000

- 结论：网页控制台（UI 与 API 同进程）固定监听 `127.0.0.1:5000`（`FLEET_CONSOLE_PORT` 可覆盖）；
  Manager 网关 `FLEET_MANAGER_PORT=9900`、项目端口 `FLEET_UI_PORT=3333` 各自独立互不相干。
- 理由：`docs/启动Hermes派工2(英文版).txt` §1 与 FE-01 交付均按 5000 落地；多端口分工避免
  启动器、控制台、被托管项目三方端口竞争。
- 裁决日期：2026-09-15

## ADR-018：server.py 归属 —— 控制台服务归角色A（后端核心）

- 结论：`fleet/console/server.py` 是控制面核心资产，路由/契约/会话/WS 由角色A（CORE-02/03）维护；
  角色B 只消费契约交付前端静态产物，不修改 server.py。
- 理由：API 契约与实现必须同 owner 才能保持"契约即实现"的同步；跨角色改服务端是 v1 契约脱节的根因之一。
- 裁决日期：2026-09-15

## ADR-019：WebSocket 实时通道写入契约 v1.1

- 结论：`ws://127.0.0.1:5000/ws` 入契约：服务端 7 种消息（task_update/plan_update/progress/
  stream_chunk/chat_message/notification/config_changed）、客户端 3 种（chat/set_mode/confirm_step），
  字段以 server.py 实现为准逐条冻结。
- 理由：轮询已无法满足实时看板与步进确认的时延要求；事件泵 + 类型化消息是角色B 前端对接的唯一依据。
- 裁决日期：2026-09-15

## ADR-020：UI 模式五值 + 调度模式二值，两个正交概念

- 结论：UI 工作模式五值 `run` / `intake` / `audit` / `discuss` / `plan`（前端状态机，启动器消费）；
  调度模式二值 `auto` / `step`（`/api/mode` 与 WS `set_mode` 承载，旧值 `confirm` 兼容等价 `step`）。
- 理由：工作模式回答"这一轮做什么"，调度模式回答"派工要不要人点头"；混在一个枚举里会把
  前端导航和调度语义耦死。
- 裁决日期：2026-09-15

## ADR-021：派工默认命令 = 单次、非交互

- 结论：启动器/调度器派工默认取 `.env` executors 段 `COMMAND`（如
  `claude --dangerously-skip-permissions`、`codex exec --full-auto`），一律单次执行、非交互模式。
- 理由：无人值守的调度循环里交互式 CLI 会挂死；单次进程天然可计时、可 kill、可断点恢复
  （DOING 原样返回语义依赖这一点）。
- 裁决日期：2026-09-15

## ADR-022：边界划分 —— 启动器/执行体/通知归角色C，控制面与契约归角色A

- 结论：`fleet/launcher/`、`fleet/executors/`、`fleet/notify/` 归角色C（INT-* 工作包）；
  `fleet/core/`、`fleet/manager/`、`fleet/console/server.py` 与三份契约归角色A。
  `fleet/manager/contracts.py` 是执行体接入的唯一契约层，角色C 只 import 不修改；
  语义调整一律在 executors 侧桥接解决（`fleet/executors/base.py` 桥接层即此产物）。
- 理由：契约层冻结 + 单向依赖（executors → manager）是防止两边互相漂移的结构性保障。
- 裁决日期：2026-09-15

## ADR-023：项目名统一 AideanFleet

- 结论：仓库、进程横幅、.env（`FLEET_PROJECT_NAME=AideanFleet`）、文档口径一律 AideanFleet，
  废弃散落的旧名（AideanCompany/AideanBot 等仅作历史文档引用保留）。
- 理由：多项目托管场景下项目名字段会被终端用户复用，平台自身必须名字唯一、可 grep、可区分。
- 裁决日期：2026-09-15


## ADR-024：Prompt 模板文件系统 = Markdown 单文件 + str.format

- 结论：`fleet/prompts/{role}.md` 单文件模板，Python `str.format()` 填充变量，不引入 Jinja2 或任何模板引擎。
- 变量命名：中文直白（`{任务描述}`、`{验收标准}`、`{项目路径}`），降低非程序员编辑门槛。
- 理由：当前角色仅 3 种，prompt 变化频率低；str.format 零依赖、零学习成本，符合"初中生可完成"原则。
- 评估文档：SOL-001 §1
- 裁决日期：2026-09-24

## ADR-025：本地 Skills 系统 = 缓行（Phase 3 再评估）

- 结论：当前不实现项目级 skills 系统；用 `docs/执行体/` 下 Markdown 指导文件代替。
- 触发重评条件：执行体适配层稳定 + 角色种类超过 5 种 + 技能复用频率可量化。
- 理由：Skills 系统 = 注册表 + 加载器 + 发现机制 + 版本管理，框架级复杂度不匹配 Phase 2 正确性优先目标。
- 评估文档：SOL-001 §2
- 裁决日期：2026-09-24

## ADR-026：存储方案 = SQLite + JSONL 不变，拒绝 Redis

- 结论：任务状态存储继续用 SQLite，事件流继续用 JSONL append-only，不引入 Redis。
- 理由：①引入 Redis 违反"零外部服务依赖"铁律；②"初中生可完成"原则下 Redis 安装维护门槛过高；
  ③AideanFleet 并发量级（单机几十任务）下 SQLite WAL 模式性能完全够用；
  ④events.jsonl 的 append-only 语义无法用内存数据库替代（宕机丢数据）；
  ⑤WebSocket 实时推送已通过内存消息队列 + asyncio 实现。
- 性能瓶颈预案：如真出现，先优化 SQLite（WAL、索引、批量写），再考虑换存储。
- 评估文档：SOL-001 §3
- 裁决日期：2026-09-24

## ADR-027：CLI 执行体安装 = 提供脚本不自动执行

- 结论：提供 `scripts/setup-executors.sh` 检测 + 提示安装命令，不自动下载安装。
- 文档补充：README 中写清楚每个 CLI 的安装步骤和验证方法。
- 理由：自动安装涉及平台/架构检测、版本管理、签名验证、API Key 配置——复杂度和安全风险远超收益。
- 评估文档：SOL-001 §4
- 裁决日期：2026-09-24

## ADR-028：模型切换 = 任务间切换，非任务中切换

- 结论：支持任务之间的间隙切换模型（任务 A 用 GPT-4，任务 B 用 Claude）；
  不支持任务执行中切换（进程级限制，ADR-021 单次非交互模式决定）。
- 实现路径：`.env` 角色模型映射 + 控制台 `/api/model` 端点，任务派工前读取当前模型配置。
- 理由：CLI 执行体是单次进程，启动后模型已锁定；kill+重启会丢失执行体上下文。
- 评估文档：SOL-001 §5
- 裁决日期：2026-09-24

## ADR-029：基础环境初始化 = 缓行（Phase 3 用 Docker 镜像）

- 结论：当前假设运行环境已就绪，README 列出前置依赖；Phase 3 提供 Dockerfile 统一环境。
- 理由：环境初始化是 DevOps 工具职责（Docker/Devbox/Nix），不是编排器职责；
  自动安装系统级软件需要 root 权限，安全风险高。
- 评估文档：SOL-001 §6
- 裁决日期：2026-09-24

## ADR-030：主执行流程文档化 = 端到端流程文档

- 结论：在 `.docs/03_solution/main-flow.md` 创建端到端流程文档，三段式描述：
  ①文字流程图 ②代码引用 ③状态机联动。
- 理由：当前主流程散落在 launch_core.py、intake.py、dispatcher.py、scheduler.py 中，
  没有一份端到端文档；文档化后新人（和初中生）能快速理解全局。
- 评估文档：SOL-001 §7
- 裁决日期：2026-09-24
