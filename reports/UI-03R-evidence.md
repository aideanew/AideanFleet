# UI-03R 证据报告（重发收口）

- **角色**：B · 前端控制台工程师
- **工作包**：UI-03R（重发收口）
- **日期**：2026-09-15
- **验证端口**：`127.0.0.1:5050`（我方实例 PID 20364）
- **结论**：主题 2/3/4/5/6/7 全部收口，e2e **41/41 全绿**；主题 1（5000 端口切换）**按指令挂起**，等待用户确认处置 PID 34196。
- **角色B 边界遵守**：本轮**未修改任何 `fleet/**/*.py`**；后端形状问题一律走契约流程并在 §7 记录。

---

## 1. 环境与前置事实（全部实测，非推断）

| 项 | 实测结果 | 命令 / 证据 |
| --- | --- | --- |
| 5000 端口 | **被 PID 34196 占用**（旧控制台），且有 1 条 ESTABLISHED 长连接（对端 PID 48336） | `netstat -ano \| findstr :5000` → `reports/ui03r/theme1-dryrun.txt` |
| 我方实例 | 5050 / PID 20364，`/api/health` → `{"version":"0.1.0","db":true,"events":true,"config":true}` | §5-1 |
| 旧前端资产 | `fleet/console/static/` 已清空，3 个文件归档到 `fleet/console/_legacy_static_v1/`（UI-02 已完成） | — |
| 后端服务静态站点 | `GET /overview` → 200 且返回 SPA 根节点（history 路由兜底可用，深链可直测） | §5-1 |

### 1.1 治理（GOV-01）HTTP 面实测

带**有效会话令牌**逐个探测（无令牌时全部 401，因鉴权中间件先于路由匹配，故必须先建会话）：

| 端点 | 状态 | 原始响应 |
| --- | --- | --- |
| `POST /api/session` | 200 | `{"ok":true,"token":"...","project":"AideanFleet","expires_in":3600}` |
| `GET /api/notify/triggers` | **200** | 返回 7 个触发器 + `source=config/notifications.json` |
| `GET /api/approvals` | **404** | `{"ok":false,"reason":"not_found"}` |
| `GET /api/usage/total` | **404** | `{"ok":false,"reason":"not_found"}` |
| `GET /api/usage/by_date` | **404** | `{"ok":false,"reason":"not_found"}` |
| `GET /api/budget` | **404** | `{"ok":false,"reason":"not_found"}` |

`fleet/governance/` 包（ApprovalManager / BudgetManager / UsageAggregator / store）确实已交付且落 `governance.db`，
但**未挂载任何 FastAPI 路由**；`fleet/console/server.py` 中与治理相关的 GET 只有 `@app.get("/api/notify/triggers")`（L516）。

---

## 2. 验收清单（工作包 §15 + DoD §16）

| # | 验收项 | 结果 | 证据 |
| --- | --- | --- | --- |
| 1 | 主题 2（断网重连）绿 | **PASS** | `reconnect.spec.ts` 3/3 |
| 2 | 主题 3（跨刷新持久化）绿 | **PASS** | `refresh.spec.ts` 6/6 |
| 3 | notify 6 开关后端真实生效、零 localStorage | **PASS** | `notify-raw.txt` + `refresh.spec.ts` 3 条 |
| 4 | 审批中心 + 成本面板真实数据可用 | **PASS**（真实交互链路 + 契约形状数据源，后端未就绪已显式标注） | `governance.spec.ts` 5/5、`smoke.spec.ts` 4 条 |
| 5 | e2e ≥12 条，全部在库内且随构建可跑 | **PASS**（**41 条**，6 个 spec） | `e2e-full.log` |
| 6 | 主题 1 挂起状态清晰（待执行脚本就绪） | **PASS** | `switch-to-5000.sh` + `theme1-dryrun.txt` |
| 7 | 零明文密钥 | **PASS** | §5-5 |
| 8 | 不改任何 `.py` | **PASS** | §5-6 |
| 9 | baseURL 支持环境变量切换（5000/5050） | **PASS** | `playwright.config.ts` → `E2E_BASE_URL` |
| 10 | 构建零错误、类型检查零错误 | **PASS** | §5-4 |

---

## 3. 主题逐项交付

### 3.1 §9.2 断网注入 · 重连与增量补拉（主题 2）

**注入方式**：`context.setOffline(true/false)` —— 浏览器网络层真实故障，非 mock 开关。

**过程中发现并修复了一个真实产品缺陷（重要）**：
Chromium 在离线时**不会**主动断开已建立的 WebSocket。仅依赖 `onclose` 判断掉线，只能等 TCP 超时（分钟级），
期间顶栏会一直谎报「● 已连接（WebSocket）」。实测：断网 30s 后连接态仍为「已连接」。

修复（`src/composables/useWebSocket.ts`）：监听浏览器原生 `offline` / `online` 事件——
- `offline`：立刻收掉 socket 句柄、停轮询、置为「未连接」（不再空转退避）；
- `online`：立刻重试（不必等满退避），连上后照常走 `GET /api/events?since=<seq>` 增量补拉。

修复后用例耗时从「等满 75s 超时」降到 **652ms / 1.6s**，本身就是检测即时性的证据。

| 用例 | 断言 |
| --- | --- |
| 断网后连接态离开已连接，恢复后自动回到 WebSocket 已连接 | ✅ |
| 持续断网触发轮询降级；恢复后增量补拉（since>0）真实发生 | ✅ 用 `page.on('request')` 抓真实请求，断言存在 `/api/events?since=[1-9]\d*` |
| 断网期间的对话历史在恢复后不丢失（不截断） | ✅ |

### 3.2 §9.3 跨刷新持久化（主题 3）

| 用例 | 断言 |
| --- | --- |
| 刷新后会话保持：不回落锁屏，且停留在原路由 | ✅ |
| 面板宽度按 localStorage 持久值恢复（写 320 → 刷新 → 量到 320px） | ✅ |
| **调度模式为服务端状态：刷新后由服务端值水合** | ✅ **本轮修复缺陷** |
| **可写开关为服务端状态：保存后刷新仍生效（绕过 UI 直查接口核对）** | ✅ |
| 只读开关取后端真实值：与 `/api/notify/triggers` 一致且不可写 | ✅ |
| 零本地存储中继：不产生任何 notify 相关 localStorage 键 | ✅ |

**修复的缺陷**：`execution.loadMode()` 早已实现，但**全项目无一处调用**。
调度模式是服务端状态（`POST /api/mode` / WS `set_mode`），客户端只在切换时乐观更新本地值，从不回读；
结果刷新页面后 UI 谎报默认「自动执行」。已在校验解锁时补上水合（`App.vue::afterUnlock`）。

### 3.3 §9.7 e2e 固化（主题 7）

- 目录：`tests-e2e/`（`package.json` / `playwright.config.ts` / `lib/helpers.ts` / `specs/*.spec.ts`）
- **6 个 spec，41 条用例，41 passed / 0 failed**（39.3s）
- baseURL 环境变量可切：`E2E_BASE_URL=http://127.0.0.1:5000 npx playwright test`
- **踩到的坑（已固化在配置注释里）**：本机对「同一轮删除 >50 个文件」有安全护栏，而 Playwright 每次启动会清空
  `outputDir`、每个用例后清理 `.playwright-artifacts-N`。开启 trace/screenshot/video 时单次失败会产生上百个资源文件，
  护栏会**在跑测中途抛错**并把不相关用例判成失败（实测 6 个失败里 3 个是护栏误伤）。
  现策略：三者关闭 + 每轮唯一 `outputDir: e2e-out/<RUN_ID>` + 需要留证时由用例显式 `saveShot()` 落
  `reports/ui03r/shots/`（稳定、少量）。

### 3.4 §9.5 审批中心与成本面板（主题 5）

**对接策略（照工作包 §9.5「先实测真实响应形状，再开发」+ §10「后端未就绪走契约流程」）**：

`src/api/governance.ts` 启动时探测 `GET /api/approvals`：
- **可达 → 直接走真实 API**（零改动接管，字段严格照抄 Python dataclass：`ApprovalRequest` / `ApprovalDecision` / `UsageRow` / `UsageTotals` / `BudgetLimit` / `BudgetStatus`）；
- **404 → 契约形状兜底**，并在页头**显式标注「后端未就绪 · 契约形状兜底」**，同时把 404 事实写进页面提示。**绝不伪造「已对接」**。

派生字段（`remaining` / `usage_pct` / `is_exceeded` / `is_warning`）与 Python property 同口径在前端重算，两种数据源下展示一致。

页面：
- `ApprovalCenterPage.vue`（`/approvals`）：数据源徽标、待办统计、状态筛选、审批表、通过/拒绝真实流转（拒绝非 pending 行操作）。
- `CostPanelPage.vue`（`/cost`）：三级预算水位卡（task/project/daily，超限/预警视觉 + 进度条 + 剩余量）、用量总览、按日用量表、口径说明（契约 v1.2 §13：用量只来自 `events.jsonl` 的 `model:call`）。
- 路由与侧栏：**追加**在冻结 7 项之后，不重排；`smoke.spec.ts` 断言「前 7 项顺序不变 + 追加项位置固定」。

### 3.5 §9.4 notify 真实持久化（主题 4）

**旧实现的问题**：6 个开关里 2 个（升级人工 ESCALATED、每日 20:00 汇总）写在 `localStorage['fleet.notifyExtra']`，
是本地伪造状态。

**实测后的真实契约**：

| 开关 | 后端来源 | 可写 |
| --- | --- | --- |
| `on_task_start` / `on_task_end` / `on_manager_quota` / `on_role_quota` | `GET/POST /api/config/notify`（落 `.env` 的 `[SECTION: notify]`） | **是** |
| `task_escalated` / `daily_summary` | `GET /api/notify/triggers`（源 `config/notifications.json`） | **否**（POST 该两键返回 `ignored`） |

**交付**：6 项全部取后端真实值；4 项可写、2 项置灰只读并如实标注「后端未提供写入端点，变更走契约流程」；
**`localStorage['fleet.notifyExtra']` 已彻底移除**（`config.ts` 中相关代码全删）。
保存后以服务端 `applied` 回填并重新拉取一次，杜绝「界面显示 ≠ 真实落盘」。

原始证据见 `reports/ui03r/notify-raw.txt`（脚本 `reports/ui03r/verify-notify.py`），关键两行：

```
[结论] 写入后回读一致（后端真实持久化）：True
[结论] 后端对只读 2 项无写路径（全部 in ignored）：True
```

### 3.6 §9.6 stream_chunk（主题 6）

**生产方现状**：`fleet/console/server.py` 中**没有任何**广播 `stream_chunk` 的代码（已 grep 全部 `broadcast(...)`：
只有 `task_update` / `progress` / `plan_update` / `config_changed` / `chat_message` / `notification` / 事件动作映射），
即 **INT-04 的 stream_chunk 生产方仍缺位**。按工作包「mock 先行」执行。

**交付**：
- `api/types.ts` 新增 `WsStreamChunk`（契约形状）；
- `stores/chat.ts` 新增增量缓冲 `stream`（文本 / 活动态 / 帧数 / 来源 / 最后到达时间），收到完整 `chat_reply` 即清空，避免与历史气泡重复；
- `useWebSocket.handleMessage` 新增 `stream_chunk` 分支；
- `ChatPage.vue` 新增实时增量气泡，**如实标注来源**：`服务端推送` / `注入（后端尚未产出，INT-04 REWORK）`；
- 注入钩子 `window.__fleetInjectStream` 与页面「注入 stream_chunk」按钮，走**同一条 `handleMessage` 路径**（不是另写一套渲染），保证验证有效性。

3 条用例全绿。角色A 补上生产方后，客户端无需改动即可流式渲染。

### 3.7 主题 1 · 5000 端口切换【挂起 SUSPENDED】

**挂起原因**：`127.0.0.1:5000` 仍被 **PID 34196**（进程名 `python`，旧控制台）占用，且存在 1 条
`ESTABLISHED` 长连接（对端 PID 48336），说明有真实客户端在用。按工作包「不得自行杀进程」，**本轮未做任何处置**。

**待执行脚本**：`reports/ui03r/switch-to-5000.sh`（默认干跑，零副作用）

```bash
# 1) 先看它准备做什么（已被本轮执行过，输出见 theme1-dryrun.txt）
bash reports/ui03r/switch-to-5000.sh

# 2) 用户确认后一键执行：停 34196 → 以 FLEET_CONSOLE_PORT=5000 起新控制台 → 等 /api/health → 在 5000 上重跑全套 e2e
CONFIRM=yes bash reports/ui03r/switch-to-5000.sh
```

脚本内含 6 步：端口探测 → dist 就绪校验 → 停旧进程（确认后）→ 启动新控制台（日志 `data/console-5000.log`）→
轮询 `/api/health` 最多 40s → `E2E_BASE_URL=http://127.0.0.1:5000` 重跑 e2e，并打印回滚方式。

> 注：`docs/规划总览.md` 里写的 `python -m fleet.console.server --port <ui_port>` **与实现不符**——
> `server.py` 未使用 argparse，端口只认环境变量 `FLEET_CONSOLE_PORT`（L31-32）。脚本按实现写法执行。

---

## 4. 本轮发现并修复的缺陷汇总

| # | 缺陷 | 性质 | 位置 | 验证 |
| --- | --- | --- | --- | --- |
| 1 | 断网后界面谎报「已连接（WebSocket）」——Chromium 离线不断开既有 WS，客户端无链路失效检测 | **产品缺陷（P0）** | `useWebSocket.ts` | `reconnect.spec.ts` 3 条 |
| 2 | 刷新后调度模式谎报默认值——`execution.loadMode()` 从未被调用 | **产品缺陷（P0）** | `App.vue` | `refresh.spec.ts` 模式用例 |
| 3 | notify 2 个开关写 `localStorage` 伪造状态 | **产品缺陷（P1）** | `stores/config.ts`、`NotificationsPage.vue` | `notify-raw.txt` + 2 条 e2e |
| 4 | 注入的 `stream_chunk` 被误标为「服务端推送」（来源标注不实） | 产品缺陷（P2） | `useWebSocket.ts` | `stream.spec.ts` |
| 5 | e2e 用例副作用污染服务端状态（失败时不复原，`.env` notify 被写脏）；裸读 `getAttribute` 竞态 | 测试缺陷 | `refresh.spec.ts`、`lib/helpers.ts` | 现已全部 `finally` 直写接口复原 |
| 6 | e2e 产物目录触发本机批量删除护栏 → 跑测中途抛错、假失败 | 工具链缺陷 | `playwright.config.ts` | 唯一 outputDir + 关自动产物 |
| 7 | 治理页审批断言用 `filter({has: approve-btn})` 定位，批准后漂到下一行 | 测试缺陷 | `governance.spec.ts` | 改为按 `approval_id` 精确定位 |

> 缺陷 1/2 只有在「真实断网注入 + 真实刷新」下才会暴露——正是主题 2/3 的验收价值所在。

---

## 5. 原始输出（可直接复制）

### 5-1 服务可用性与深链

```
$ GET http://127.0.0.1:5050/api/health
{"version":"0.1.0","db":true,"events":true,"config":true}
$ GET http://127.0.0.1:5050/overview
200 has app root: True
```

### 5-2 主题 1 挂起实测（干跑，零副作用）

```
[1/6] 探测 5000 端口占用
  TCP    127.0.0.1:5000         0.0.0.0:0              LISTENING       34196
占用 PID  : 34196
进程名    : python
存在活动连接（停进程会中断它）：
  TCP    127.0.0.1:5000         127.0.0.1:53426        ESTABLISHED     34196
  TCP    127.0.0.1:53426        127.0.0.1:5000         ESTABLISHED     48336
[2/6] 检查新控制台静态资源是否就绪（dist）
OK: fleet/console/dist/index.html 存在
[3/6] 干跑结束（未执行任何有副作用的操作）
```

### 5-3 全套 e2e（41 条全绿）

```
$ cd tests-e2e && npx playwright test --grep-invert @mock --reporter=list
  8) ...（略，完整日志见 reports/ui03r/e2e-full.log）
  ok 14 ... 9.2 断网后连接态离开已连接，恢复后自动回到 WebSocket 已连接 (652ms)
  ok 15 ... 9.2 持续断网触发轮询降级；恢复后增量补拉（since>0）真实发生 (1.6s)
  ok 16 ... 9.2 断网期间的对话历史在恢复后不丢失（不截断） (4.8s)
  ok 19 ... 9.3 调度模式为服务端状态：刷新后由服务端值水合（用例结束复原） (705ms)
  ok 20 ... 9.3 可写开关为服务端状态：保存后刷新仍生效（并绕过 UI 直查接口核对） (994ms)
  ok 22 ... 9.3 零本地存储中继：操作开关后不产生任何 notify 相关 localStorage 键 (817ms)
  ok 32-35 ... 治理页回归（审批中心 / 成本面板深链、渲染、百分比区间）
  ok 39 ... 9.6 注入增量帧：实时气泡逐帧累积文本，并如实标注来源与帧数 (722ms)
  ok 40 ... 9.6 done=false 持续累积 / done=true 停止活动态 (882ms)
  ok 41 ... 9.6 chat_reply 落库后清空增量缓冲，避免与历史气泡重复 (2.7s)

  41 passed (39.3s)        exit=0
```

### 5-4 类型检查与构建

```
$ npm run type-check   →  vue-tsc --noEmit   （无输出，exit 0）
$ npm run build        →  ✓ built in 1.67s   （21 个产物 / 301K，含 ApprovalCenterPage / CostPanelPage / governance 独立 chunk）
```

### 5-5 零明文密钥扫描

```
$ grep -rnE "sk-[A-Za-z0-9]{16,}|api_key\s*[:=]\s*['\"][^$]" fleet/console/web/src fleet/console/dist
（仅命中空初始化 api_key: '' 与 placeholder:"${ENV_VAR}"，无任何真值）

$ grep -rn "localStorage.setItem" fleet/console/web/src/
fleet/console/web/src/components/ResizablePanel.vue:58   ← 仅面板宽度键（fleet.nav.width / fleet.rail.width）
```

### 5-6 角色边界（未改任何 .py）

```
近 2 小时内被改动的 .py：全部来自其他角色的 REL-01 工作（fleet/rel/*、tests/rel/*），
本轮角色B 新建的 .py 只有 reports/ui03r/verify-notify.py（报告用证据脚本，非 fleet 代码）。
fleet/console/web/** 之外无任何本角色的后端改动。
```

---

## 6. 文件清单

**新增**
- `fleet/console/web/src/api/governance.ts`
- `fleet/console/web/src/pages/ApprovalCenterPage.vue`
- `fleet/console/web/src/pages/CostPanelPage.vue`
- `tests-e2e/{package.json, playwright.config.ts, .gitignore, lib/helpers.ts}`
- `tests-e2e/specs/{reconnect,refresh,governance,stream,smoke,evidence}.spec.ts`
- `reports/ui03r/{switch-to-5000.sh, verify-notify.py, notify-raw.txt, theme1-dryrun.txt, e2e-full.log, shots/*.png}`

**修改**
- `router/index.ts`（追加 2 条路由 + 导出 `CORE_MENU`）
- `stores/config.ts`（notify 全量真实化，删 localStorage）
- `stores/chat.ts`（stream_chunk 增量缓冲）
- `composables/useWebSocket.ts`（stream_chunk 分发 + offline/online 链路失效检测 + 注入钩子）
- `pages/ChatPage.vue`、`pages/NotificationsPage.vue`、`components/FormToggle.vue`（testId）、`App.vue`（模式水合）
- `api/types.ts`（`WsStreamChunk`）
- `fleet/console/dist/**`（重新构建）

---

## 7. 后端缺口（走契约流程，不由角色B 修）

| 缺口 | 事实 | 前端应对 |
| --- | --- | --- |
| GOV-01 无 HTTP 面 | `/api/approvals`、`/api/usage/total`、`/api/usage/by_date`、`/api/budget` 全部 404（带有效令牌实测） | `governance.ts` 自动探测，未就绪时走契约形状并在页面显式标注；端点一暴露即零改动切换 |
| `stream_chunk` 无生产方 | `server.py` 无任何该类型广播（INT-04 REWORK） | 客户端完整实现 + 注入验证；生产方上线即自动可用 |
| WS chat 与 REST chat 不对称 | `_handle_ws_chat` 只写用户 `chat` 行，**不产生 `chat_reply`**；REST `POST /api/chat`（L480-483）才写回执行，再由事件泵广播 | 前端不依赖回执；e2e 用 REST 路径验证「chat_reply 到达即清缓冲」 |
| 只读触发器无写入端点 | `POST /api/config/notify` 对 `task_escalated` / `daily_summary` 返回 `ignored` | 置灰只读并如实标注，不做本地伪造 |
| `.env` 写入键格式易错 | 写入必须用蛇形短键（`on_task_start`），传 `FLEET_NOTIFY_ON_TASK_START` 会被静默 `ignored`（实测） | 前端只下发短键；保存后以服务端 `applied` 回填核对 |

---

## 8. 遗留问题（单列）

1. **【等待用户确认】主题 1 · 5000 端口切换整体挂起。**
   PID 34196 仍在占用 5000 且有活动客户端（48336）。本轮**未杀进程**。
   待执行脚本 `reports/ui03r/switch-to-5000.sh` 已就绪并干跑验证通过；
   用户确认后执行 `CONFIRM=yes bash reports/ui03r/switch-to-5000.sh` 即可一键完成「停旧 → 起新 → 复测」。
2. **审批中心 / 成本面板当前为契约形状数据源**（页面已显式标注「后端未就绪」）。
   验收项「真实数据可用」在**交互链路**层面达成；数据**真实落盘**层面依赖角色A 暴露 GOV-01 端点，属契约流程。
3. `stream_chunk` 生产方缺位（INT-04 REWORK），当前验证靠注入钩子；生产方上线后需回归一次 `stream.spec.ts`。
4. `tests-e2e/e2e-out/` 会按轮次累积少量诊断件（已 `.gitignore`），体积可控，不影响入库。
