# AideanFleet 架构决策记录（ADR）

> 编号脉络：ADR-001 ~ ADR-012 源自 `初始设计/d7.md`（收敛建议），ADR-015 源自 `初始设计/d9.md`；
> ADR-013/014 留空未占用；ADR-016 起为本项目实施阶段的新增裁决（工作包 CORE-03 落盘，2026-09-15）。
> 每条 ADR 一句话结论 + 理由 + 裁决日期；变更既有 ADR 必须标注 SUPERSEDED 并指向替代者。

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
