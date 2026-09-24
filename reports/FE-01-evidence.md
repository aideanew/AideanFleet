# FLEET-FE-01 验收证据 · 网页控制端 1.0

执行角色：角色B（网页控制端全栈）
日期：2026-09-15
服务：`python fleet/console/server.py`（默认 127.0.0.1:5000，本机 5000 被角色A旧服务占用，本次以 `FLEET_CONSOLE_PORT=5010` 验证）
交付物：`fleet/console/server.py`、`fleet/console/envstore.py`、`fleet/console/store.py`、`fleet/console/static/{index.html,style.css,app.js}`

## 1. UI 验收清单对照（用户设计"网页控制端"一节逐条）

| 设计要点 | 实现 | 证据 |
|---|---|---|
| 深色科技风：深底色/青碧强调色/等宽数字字体 | style.css `--bg-deep #0a0f16`、`--teal #2dd4bf`、`--mono` | assets/FE-01-overview.png |
| 无底部信息栏 | 布局仅顶栏+三栏，无 footer | 同上 |
| 锁屏：输入项目名解锁，.env 默认 1 小时有效期 | POST /api/session 校验 projects 数据；`[settings] lock_screen_seconds`（默认 3600） | T1–T4、T20 |
| 顶部栏右上角：锁定键+设置按钮 | 🔒 锁定（DELETE /api/session 回锁屏）；⚙ 设置（请求超时/重试次数 → POST /api/config/settings） | 浏览器快照 |
| 左菜单七页固定顺序[总览,对话,模型,角色,执行体,拓展,消息] | index.html 菜单数组 MENU 顺序一致 | 快照 |
| 左菜单可缩起/展开、边缘可拖拽调宽 | 折叠按钮 + sidebar-resizer 拖拽（56~420px） | 代码 app.js initResizer |
| 右进度条从顶部栏到底、默认缩起、可拖拽展开 | rail.collapsed 默认 34px；rail-resizer 拖拽 + 点击展开 | assets/FE-01-overview.png 右缘 |
| 缩起呈空心圆列：完成绿/未完成红/当前青碧且更大/圆心百分比 | .rail-dot 三态 CSS；当前圆 30px 且 textContent=总百分比 | 快照 "20%初始化Manager" |
| 总览主体永远是当前执行步骤，已执行折叠顶部可点击展开过程 | ov-current 主面板 + ov-done 折叠点击展开 detail | 快照 + 浏览器验证 |
| 支持鼠标滚轮上下查看 | .overview-scroll overflow-y:auto | — |
| 固定 10 步准备清单原文 | store.py DEFAULT_PREPARE_STEPS 与设计原文逐字一致（含"一切就绪!是否启动?"） | T5 |
| 右上角"每步确认/自动执行"切换；确认模式底部输入框；结果写入事件流 | /api/mode、/api/confirm 均写 events.jsonl（action=mode_change/step_confirm） | T12 |
| 对话页：底部输入框+消息流，发送转 Manager，回执渲染 | POST /api/chat + 1 秒轮询渲染；plan 修正后 /api/plan 自动刷新 | T11、assets/FE-01-chat.png |
| 模型页：name/level/base_url/model_id/api_key掩码/双proxy | 卡片表单 → POST /api/config/models | assets/FE-01-models.png |
| 角色页：role_name/system_prompt/bind_model_name | 卡片表单 → /api/config/roles（bind_model_name 逗号分隔数组） | 代码 |
| 执行体页：列表+启动命令 | 卡片表单 → /api/config/executors | 代码 |
| 拓展页：执行体 skills/mcp 勾选清单 | 勾选 + 回车新增 → /api/config/extensions | 代码 |
| 消息页：SMTP 参数+四开关（开始=关/结束=开/Manager额度=开/执行角色额度=开）+自定义触发项 | 默认值与设计一致；保存写 .env [message] | T17 |
| api_key 一律掩码、永不明文回显 | type=password + ${VAR} 占位；真值只进 secrets/.env | T13–T15、模型页验证 |

## 2. API / 安全测试记录（curl 实测）

| # | 用例 | 结果 |
|---|---|---|
| T1 | POST /api/project 不存在 | 400 `项目不存在，请检查项目名是否正确` ✔ |
| T2 | POST /api/session 缺项目名 | 400 `请输入项目名` ✔ |
| T3 | 无 token 访问 /api/plan | 401 `会话无效或已过期…` ✔ |
| T4 | 正确项目名解锁 | 200 token + expires_in=3600 ✔ |
| T5 | GET /api/plan | 10 步清单原文，percent 聚合 ✔ |
| T6 | launch-event 缺 summary | 400，中文提示"缺字段…本次未写入事件流" ✔ |
| T7 | 400 后 GET /api/events | max_seq 不变（事件流未被污染） ✔ |
| T8 | 合法 launch-event(step_done) | 写入 seq=1，plan 步骤推进 done→current ✔ |
| T9 | GET /api/events?since=1 | 增量返回 seq>1 ✔ |
| T10 | plan 聚合 | done=1/10 → percent=10 → 20（第二步完成后） ✔ |
| T11 | POST /api/chat | 用户事件+Manager mock 回执 ✔ |
| T12 | POST /api/mode auto→confirm | 写入事件流 ✔ |
| T13 | POST /api/config/models 含真 Key | 响应 `masked:["agnes3.api_key"]` ✔ |
| T14 | GET /api/config/models | 响应中明文出现 0 次，仅 `${AGNES3_API_KEY}` ✔ |
| T15 | 落盘检查 | .env 明文 0 次；secrets/.env 含真值 ✔ |
| T16b | settings 合并更新 | 只改 request_timeout，lock_screen_seconds 保留 ✔（修复整段替换丢键 bug 后） |
| T17/18 | message 段保存真授权码 | 回显 `${MESSAGE_SMTP_PASSWORD}`；真值仅在 secrets/.env ✔ |
| T19 | POST /api/notify/test | 503 `依赖角色C的 notify 模块…` ✔ |
| T20 | lock_screen_seconds=10 | expires_in=9；11 秒后访问 HTTP 401；已还原 3600 ✔ |

## 3. 实时同步（双窗口测试）

- 窗口A（curl）：14:16:17.07 POST `/api/launch-event`（step_done prep-2）。
- 窗口B（浏览器总览页，1 秒轮询）：等待 1.1 秒后读取 DOM——
  `overview-done` = "1/10 接收指令 已完成 / 2/10 分析需求 已完成"；
  `overview-current` = "3/10 初始化Manager 执行中"；
  进度圆当前项 = "20% 初始化Manager"。
- 断线重连：pollEvents 失败后 3 秒重试，重连后从本地 maxSeq 续拉（`/api/events?since=<seq>`），顶栏显示"● 连接中断，3 秒后重连…"。代码路径 app.js `pollEvents()`。

## 4. 七页面读写持久化

保存后 `GET /api/config/<section>` 均返回保存值（T13/T16b/T17）；页面刷新后 sessionStorage 会话保持（浏览器实测：刷新直接回主界面，模型页数值保持），锁屏有效期到后自动回锁屏（T20）。

## 5. 截图

- assets/FE-01-overview.png —— 总览页：10 步清单、每步确认/自动执行切换、确认输入栏、右进度条、深色科技风
- assets/FE-01-models.png —— 模型页：卡片表单、api_key 密码掩码（`${VAR}` 占位）
- assets/FE-01-chat.png —— 对话页：用户消息 + Manager mock 回执

## 6. 测试期间发现并修复的问题

1. **Windows 中文请求体 GBK 编码**：bash/curl 发送中文 JSON 时服务端 utf-8 解码失败导致"缺必填字段"误报 → `_body()` 增加 GBK 回退解码。
2. **扁平配置段整段替换丢键**：保存 settings 会丢失未提交的 lock_screen_seconds → `set_section` 改为扁平段合并更新、结构化段整体替换。

## 7. 边界确认

未修改 fleet/core、fleet/models、fleet/executors、fleet/launcher、fleet/notify（均不存在，未越界创建）。
新增文件全部位于 fleet/console/ 与 reports/；.env 与 secrets/.env 为控制台按设计"初始化从模板复制/真值外置"职责生成。
