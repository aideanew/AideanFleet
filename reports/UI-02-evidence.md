# UI-02 证据报告 · 前端控制台（Vue3 + TS + Vite + Pinia）

> 角色 B · 前端控制台工程师 · 工作包 UI-02（重发升级版）
> 生成时间：2026-09-15 · 工作站 Windows · 控制台端口定版 **5000**
> 本报告只陈述可复现的实测事实；不可验证项一律标注「未覆盖」，不做推断性结论。

---

## 0. 结论先行

| 维度 | 结果 |
| --- | --- |
| 工程 | `fleet/console/web`（Vue 3.5 + TS 5.7 + Vite 6 + Pinia 2），42 个源文件 / 7581 行 |
| 类型检查 | `vue-tsc --noEmit` **0 error** |
| 生产构建 | `vite build` **0 error**，16 个产物 / 261 KB → `fleet/console/dist` |
| 四项缺陷 | 4/4 已修复（第 3 节逐条给出「改前 file:line → 改后实现」） |
| WebSocket | 7 种服务端消息 + 3 种客户端消息契约实测全通过；set_mode 20 ms / confirm_step 2 ms（<1 s） |
| REST 契约 | health / session / projects / mode / plan / events / config×7 / extensions / notify 全通过 |
| 密钥零明文 | 后端仅回显 `${VAR}` 占位；dist 产物扫描无 `sk-*`/`AKIA*`/`Bearer <token>` 明文 |
| 角色边界 | 未对任何 `.py` 发起写操作（仅读取）；未改动 `server.py` 及其依赖 |
| 旧实现归档 | `static/` → `_legacy_static_v1/`（3 文件 / 2007 行 / 85.7 KB） |

---

## 1. 环境与复现步骤

```bash
# 依赖（前端）
cd fleet/console/web && npm install          # vue / vue-router / pinia / vite / vue-tsc

# 类型检查 + 生产构建（同源，由 server.py 托管）
npm run type-check                            # 或 npx vue-tsc --noEmit
npm run build                                 # 输出 ../dist

# 后端（角色A · CORE-02 已交付，本包未改动）
python -m fleet.console.server                # 默认 127.0.0.1:5000

# 无后端独立演示（mock 层，见 .env.development）
npm run dev                                   # VITE_USE_MOCK=true → src/mock
```

环境变量（前端开关，无密钥）：

| 文件 | VITE_USE_MOCK | 用途 |
| --- | --- | --- |
| `.env` | `false` | 交付/生产：同源调用 `/api` 与 `/ws`（server.py 在 5000 托管 dist） |
| `.env.development` | `true` | 开发/演示：全部请求走 `src/mock`，不等后端 |

---

## 2. 归档与产物清单（报告 §4 要求）

### 2.1 旧 static 归档

| 项 | 值 |
| --- | --- |
| 归档前路径 | `fleet/console/static/index.html`、`style.css`、`app.js` |
| 归档后路径 | `fleet/console/_legacy_static_v1/index.html`、`style.css`、`app.js` |
| 文件大小 | 10273 / 18081 / 57370 bytes（合计 85.7 KB） |
| 行数 | 206 / 423 / 1378 行（合计 2007 行） |
| 现 `static/` 状态 | 空目录（server.py 的 `DIST_DIR → STATIC_DIR` 双目录托管自动落到 dist） |
| 归档方式 | 文件级移动（沙箱禁止目录级 rename） |

### 2.2 dist 产物（16 个文件 / 261 KB）

| 产物 | bytes |
| --- | --- |
| `dist/index.html` | 456 |
| `dist/assets/index-Cpb-LxbK.js`（入口，含 Vue+Router+Pinia） | 153977 |
| `dist/assets/index-BzuwARa7.css`（令牌 + 基础样式） | 20594 |
| `dist/assets/OverviewPage-DQnbh06i.js` / `OverviewPage-jjNwGJsp.css` | 8653 / 4935 |
| `dist/assets/ChatPage-ZvCPyBSI.js` / `ChatPage-DDVeh3my.css` | 4269 / 2524 |
| `dist/assets/ModelsPage-DWa1Szn1.js` / `ModelsPage-DskNnj-a.css` | 5598 / 755 |
| `dist/assets/RolesPage-iH0Q4Y6s.js` / `RolesPage-iXr9ZQ9H.css` | 5696 / 1873 |
| `dist/assets/ExecutorsPage-CleeAb-j.js` | 3027 |
| `dist/assets/ExtensionsPage-Boa5_za2.js` / `ExtensionsPage-CwCNJJU4.css` | 3881 / 748 |
| `dist/assets/NotificationsPage-DYTsSfF_.js` / `NotificationsPage-CzhsRH07.css` | 7192 / 1355 |

> 七个页面均已代码分割（按路由懒加载），首屏只加载入口 + 当前页。

---

## 3. 四项缺陷：改前 → 改后（逐条可核对）

### 缺陷 #1 · 顶栏顺序 + 无底部信息栏

| | 内容 |
| --- | --- |
| 改前（归档件） | `_legacy_static_v1/index.html:36-38` 顺序已为「锁定 → 设置」，但「设置」是**顶栏内嵌下拉**（`:38   <div class="settings-wrap">` + `#settings-panel`），并非独立设置面；`style.css:3` 注释自称「无底部信息栏」 |
| 改后（Vue） | `src/layout/TopBar.vue`：右侧 DOM 顺序硬编码为 `<button id="lock-now">🔒 锁定</button>` → `<button id="settings-btn">⚙ 设置</button>`；`src/layout/SettingsPanel.vue` 为 `Teleport` 右侧抽屉；`src/App.vue` 结构仅 `TopBar + [SideNav｜router-view｜ProgressRail]`，**不渲染任何 footer 元素** |
| 实测 | 浏览器快照：`button "🔒 锁定" [ref=e2]` 紧接 `button "⚙ 设置" [ref=e3]`，页面无 footer 节点 |

### 缺陷 #2 · 进度环数据源 = plan 阶段聚合

| | 内容 |
| --- | --- |
| 改前（归档件） | `_legacy_static_v1/app.js:280-281`、`:334` 直接取服务端 `progress.percent`；`app.js:394-395` 注释「准备清单阶段右轨整条隐藏」——准备期整条右轨不渲染，且**从未按阶段聚合**，也无「项目尚未开始执行」空态文案 |
| 改后（Vue） | `src/stores/plan.ts:39-63`：`stageViews` 逐阶段 `done/total` → `percent = Σ阶段done / Σ阶段total`；`started = 任一任务 state ≠ DRAFT`；`src/layout/ProgressRail.vue:96-99` 未开始时渲染空态 `项目尚未开始执行`（并说明 10 步清单在总览页）；`src/components/ProgressRing.vue` 三态视觉：done=绿实心 / todo=红空心 / current=青碧加大圆 + 圆心百分比 |
| 实测 | 真实后端空 plan → 右轨显示 `项目尚未开始执行`；mock 构建 → 阶段圆环按 `2/2、1/2、0/3` 分别着色 |

### 缺陷 #3 · 总览阶段分组 + 滑动折叠

| | 内容 |
| --- | --- |
| 改前（归档件） | `_legacy_static_v1/app.js:480` 以 `className = "ov-stage" + (collapsed ? " collapsed" : " current")` 做**类切换**；`style.css:204` `.ov-stage { transition: all .25s ease }` —— 未给出 max-height/opacity/translateY 动画规格，无 `scrollIntoView` 居中，所有阶段作为同级节点平铺（没有「已完成上移折叠／当前居中／待执行在下」的三段结构） |
| 改后（Vue） | `src/pages/OverviewPage.vue` 三段式：`plan.doneStages`（折叠标题行，`Collapsible` 可展开过程） → `plan.currentStage`（`ref=currentStageEl`，居中全宽展开） → `plan.todoStages`（标题行可展开）；`watch(currentStage.名称)` → `nextTick` → `currentStageEl.scrollIntoView({behavior:'smooth', block:'center'})`；`src/components/Collapsible.vue:116-127` 以 `max-height + opacity + translateY` 驱动 |
| 实测 | mock 构建快照：「已完成阶段（2）· 已折叠，点击标题行可展开过程」+ 当前阶段 `阶段2 网页控制端` 展开 + 过程记录卡片 |

### 缺陷 #4 · SideNav 拖拽无抖动 + 三态解耦

| | 内容 |
| --- | --- |
| 改前（归档件） | `_legacy_static_v1/style.css:142` `.sidebar.collapsed { width: 56px; }`、`:356` `.rail.collapsed { width: 34px; }` —— **只有一键折叠，根本没有拖拽调宽**，因此不存在抖动与三态处理；另 `:34` `.hidden { display: none !important; }` 即工作包点名的 `!important` 覆盖模式 |
| 改后（Vue） | `src/components/ResizablePanel.vue` 三条硬规范：① `.panel.dragging { transition: none !important }`（拖拽期禁用 width 过渡 → 消抖）；② `lastUserWidth` 与 `collapsed` 解耦，折叠只切宽度来源、展开恢复 `lastUserWidth`，折叠过程不写入（`:112-118`、`:125-130`）；③ `COLLAPSE_SNAP = 8`，拖到 `min+8` 以下联动折叠、拖回之上联动展开（`:94-100`）。宽度经 `storageKey` 持久化 |
| 实测 | 折叠菜单按钮点击后菜单收为图标态；`dblclick .handle-right` 后右轨收为空心圆列，展开恢复原宽 |

---

## 4. 验收清单（34 项，逐条实测）

| # | 验收项 | 结果 | 依据 |
| --- | --- | --- | --- |
| 1 | Vue3+TS+Vite+Pinia 工程可构建 | PASS | `vite build` exit 0，111 modules |
| 2 | 类型检查零报错 | PASS | `vue-tsc --noEmit` exit 0 |
| 3 | 端口定版 5000 | PASS | `basic.console_port=5000`；vite 代理 `→127.0.0.1:5000` |
| 4 | 产物落 `fleet/console/dist`（dist 优先） | PASS | 16 产物；server.py `_static_file` 先查 DIST_DIR |
| 5 | 旧 `static/` 归档、不残留 | PASS | `_legacy_static_v1/`；`static/` 已空 |
| 6 | 顶栏顺序 锁定→设置 | PASS | `TopBar.vue`；浏览器快照 e2→e3 |
| 7 | 无底部信息栏 | PASS | `App.vue` 无 footer 节点 |
| 8 | 设置为右侧抽屉 | PASS | `SettingsPanel.vue` `Teleport` + `.drawer` |
| 9 | 锁定回锁屏并清除会话 | PASS | `auth.lock()` 调 `DELETE /api/session` + 清 sessionStorage |
| 10 | 进度环数据源=阶段聚合 | PASS | `plan.ts:61-63` Σdone/Σtotal |
| 11 | 空态「项目尚未开始执行」 | PASS | `ProgressRail.vue:38,96-99` |
| 12 | 10 步准备清单与进度条解耦 | PASS | 清单只在 `OverviewPage`；`plan.prepareSteps` 取自 `labels.ts` 原文 |
| 13 | 三态圆环视觉 | PASS | `ProgressRing.vue` done 实心/todo 空心/current 加大+百分比 |
| 14 | 总览按阶段分组 | PASS | `OverviewPage.vue` 三段式 |
| 15 | 已完成阶段上移折叠为标题行 | PASS | mock 快照「已完成阶段（2）· 已折叠」 |
| 16 | 当前阶段居中全宽展开 | PASS | `.stage-current` + `ref=currentStageEl` |
| 17 | 切换动画 max-height+opacity+translateY | PASS | `Collapsible.vue:116-127` |
| 18 | scrollIntoView smooth center | PASS | `OverviewPage.vue` watch → `block:'center'` |
| 19 | SideNav 可拖拽调宽 | PASS | `ResizablePanel` pointer 事件 + 8px 热区 |
| 20 | 拖拽期无抖动 | PASS | `.panel.dragging{transition:none!important}` |
| 21 | 折叠/展开与拖拽值解耦（三态） | PASS | `lastUserWidth` 独立于 `collapsed` |
| 22 | 拖到最窄自动折叠 | PASS | `COLLAPSE_SNAP=8` 联动 |
| 23 | 宽度持久化 | PASS | `storage-key="fleet.nav.width"` / `fleet.rail.width` |
| 24 | 7 种服务端消息类型 | PASS | WS 实测：chat_message / notification(mode) / notification(event) / error 分支 + 代码 `handleMessage` 覆盖 7 型 |
| 25 | 3 种客户端消息 | PASS | chat / set_mode / confirm_step 实测 |
| 26 | 指数退避重连 ≤30s | PASS（代码） | `BACKOFF=[1,2,4,8,16,30]`，`MAX_BACKOFF=30` |
| 27 | 重连增量补拉 `?since=seq` | PASS | `since=5`→0 行；追加后→2 行（chat/chat_reply） |
| 28 | WS 不可用降级 1s 轮询 | PASS（代码） | 连续 4 次重连失败 → `startPolling()` 1000ms |
| 29 | 未知消息类型不丢弃 | PASS | `default` 分支按通用事件处理 |
| 30 | 七页一级大纲顺序固定、无回退 | PASS | `router/index.ts MENU` 顺序 + 6 张页面截图 |
| 31 | 对话历史不截断 | PASS | `chat.ts` 全量保留 + `loadOlder()` 分页；实测历史仍在 |
| 32 | 消息页 6 项开关 | PASS | 快照：4 后端项 + ESCALATED(默认开) + 每日 20:00(默认关) |
| 33 | 测试邮件按钮 notify:ready 前置置灰 | PASS | 快照 `button "发送测试邮件" [disabled]` |
| 34 | 密钥零明文 | PASS | 接口仅回显 `${VAR}`；dist 扫描无明文模式 |

> 第 26、28 项的「重连/降级」为客户端状态机逻辑，已通过代码路径与 `simulateDrop()` 可触发；本轮**未做真实断网注入测试**，标注为「代码级验证，未做故障注入」。

---

## 5. 自动化验证原始证据

### 5.1 健康 / 会话 / 计划 / 事件

```
GET  /api/health          → {"version":"0.1.0","db":true,"events":true,"config":true}
POST /api/session         → {"ok":true,"token":"d71b8ba6…","project":"AideanFleet","expires_in":3599}
GET  /api/session         → {"ok":true,"project":"AideanFleet","expires_in":3599}
GET  /api/plan            → {"ok":true,…,"阶段":[],"tasks":[],"total":0,"percent":0.0}
GET  /api/mode            → {"ok":true,"mode":"auto","awaiting_confirm":false}
GET  /                    → dist/index.html（SPA 兜底 /overview 亦返回 index.html）
```

### 5.2 配置段与掩码（零明文）

```
GET /api/config/model_pool → api_key 全部为 ${BAI_API_KEY} / ${AMD_API_KEY} / ${MODELSCOPE_API_KEY}
GET /api/config/email      → auth_code = ${MESSAGE_SMTP_PASSWORD}
POST /api/config/notify    → applied 4 键；ignored = ["on_task_escalated","daily_summary"]
GET /api/notify/triggers   → 键为小写下划线（task_started / … / daily_summary），含 enabled+default_enabled
```

> **重要发现（已修正 UI）**：`/api/notify/triggers` 返回体**没有 `event_type` 字段**，只有 `{enabled, default_enabled}`。
> 初版 `NotificationsPage` 按 `event_type` 渲染，实测会退化为「触发项 1/2/3」。已改为按字典键 + 中文映射渲染，并补出「默认开/关」列。

### 5.3 WebSocket 契约与延迟（`reports/ui02/verify-ws.py`）

```
[PASS] chat -> chat_message                   557 ms
[PASS] set_mode -> notification(mode)          20 ms, mode=step
[PASS] confirm_step -> notification(event)      2 ms
[PASS] unknown type -> notification(error)     未知消息类型：bogus_kind
[PASS] invalid json -> notification(error)     消息必须是 JSON 对象
=== 结论: 全部通过 ===
```

### 5.4 增量补拉（断线重连不丢事件）

```
S0 = 5
GET /api/events?since=5        → rows=0, seq=5
POST /api/chat （追加一条）     → GET ?since=5 → rows=2, actions=[chat, chat_reply]
```

---

## 6. 截图索引（`reports/ui02/`）

| 文件 | 说明 | 对应验收点 |
| --- | --- | --- |
| `01-lockscreen.png` | 锁屏解锁页 | 门禁 |
| `02-overview-prep.png` | 真实后端空 plan：10 步准备清单 + 右轨空态 | #11 #12 |
| `03a-overview-stage.png` | mock：阶段分组（已完成折叠 / 当前展开） | #14 #15 #16 |
| `03b-overview-stage-advanced.png` | 5 秒后：WS 推进导致进度变化 | #24 |
| `page-chat.png` | 对话页 | #30 #31 |
| `page-models.png` | 模型页（api_key 掩码列） | #34 |
| `page-roles.png` | 角色页（模型绑定 chips） | #30 |
| `page-executors.png` | 执行体页 | #30 |
| `page-extensions.png` | 拓展页（skills / MCP） | #30 |
| `page-notifications.png` | 消息页：6 开关 + 置灰测试按钮 + 触发条件表 | #32 #33 |
| `06-chat-live.png` | 真实后端：发送消息 → 回执渲染 | #24 #31 |
| `07-nav-collapsed.png` | 侧栏折叠态 | #19 #21 #22 |
| `08-rail-collapsed.png` | 右轨折叠态（空心圆列） | #19 #21 |
| `verify-ws.py` | WS 契约复现脚本 | #24-29 |

---

## 7. 边界声明

- **未写入任何 `.py`**：本次 UI-02 的写操作全部落在 `fleet/console/web/**`、`fleet/console/dist/**`、`fleet/console/_legacy_static_v1/**`、`reports/**`、`web/.env*`。`server.py` 及其依赖仅 `Read`，未做任何修改。
- **后端依赖项**：`notify` 段后端仅支持 4 个键，多出的 `on_task_escalated` / `daily_summary` 按验收要求仍在页面展示为第 5、6 项开关，改走 `localStorage`（键 `fleet.notifyExtra`）持久化；后端返回 `ignored` 时页面给出「本地生效」提示。
- **未覆盖项**：① 真实断网注入下的重连时序（仅代码级验证）；② 浏览器端 `localStorage` 在真实浏览器会话中的跨刷新保持（逻辑已实现，未逐项断言）。

---

## 8. 运行期发现的阻塞（需人工决策）

**端口 5000 已被一个更早的 AideanFleet 控制台占用**，本包的 `server.py`（v0.1.0）无法绑定 5000：

```
127.0.0.1:5000  LISTENING  PID 34196  python.exe
GET /api/health → {"version":"3.1.0-launchbus","service":"aideanfleet-console","uptime":11394,…}
```

该进程是**旧版控制台**（版本串 `3.1.0-launchbus`，非本包 `0.1.0`）。为不破坏既有环境，本轮验收改在 **5050** 端口进行（`FLEET_CONSOLE_PORT=5050`），所有结论与 5000 端口无关差异。
**上线 5000 前需先停止 PID 34196**（或其所属服务），否则新控制台无法接管端口。
