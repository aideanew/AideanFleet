# 契约 · 控制台 API（FROZEN v1.2）

> 由工作包 FLEET-BE-01（角色A·控制面核心）第 1 步产出，**产出即冻结**。
> v1.1 由工作包 CORE-03（角色A·后端核心）原位升级：把 CORE-02 已交付并经 82 例测试覆盖的
> WebSocket、会话、调度控制、人工放行、拓展与通知接口补入契约，并修正 §6.2 派工响应等实现偏差。
> v1.2 由工作包 CORE-04 原位升级：新增 §13 上下文成本引擎契约（TaskPack 三个可选字段、
> model:call/prompt:assembled/budget:* 事件字段、Project Memory 条目 schema、
> retry_context 增量返工、Prompt Cache 前缀分离与 MODEL_N_CACHE、token 计量口径），供角色D（GOV-01）纯消费。
> 实现位置：`fleet/console/server.py`（FastAPI + WebSocket 版，唯一权威实现）。
> 消费方：角色B（前端）、CLI 引导器/启动器（`docs/启动Hermes派工.txt` §6、`docs/启动Hermes派工2(英文版).txt` §7）。
> 同源契约：[`任务状态机.md`](./任务状态机.md)（`state` 取值）、[`任务进度表字段.md`](./任务进度表字段.md)（字段名）。
>
> **v1.1 变更摘要**：
> 1. 新增 §7 会话与鉴权（/api/session 三方法 + 401 闸门 + token 三层来源 + GBK 请求体回退）。
> 2. 新增 §8 WebSocket 实时通道（/ws：7 种服务端消息、3 种客户端消息、4401 拒绝语义）。
> 3. 新增 §9 调度与人工控制（/api/mode、/api/confirm、/api/control/confirm、/api/chat）。
> 4. 新增 §10 启动解析 /api/launch-resolve（豁免会话）。
> 5. 新增 §11 项目 / 拓展 / 通知接口（/api/projects、/api/extensions、/api/notify/*）。
> 6. §2 补充 legacy 进度字段（progress/total/done/percent）；§5 补充段名别名与键名↔.env 段映射表；§6.2 响应体改为实现口径（rounds）。
> 7. §12 定版裁决：端口 5000、UI 模式五值与调度模式 auto/step 的关系。
>
> **v1.2 变更摘要（CORE-04）**：
> 1. 新增 §13 上下文成本引擎契约（四件套：Project Memory / Task Context 预算裁剪 / Incremental Diff / Prompt Cache）。
> 2. §3 动作码清单增补：`model:call`、`prompt:assembled`、`budget:check`、`budget:exceeded`、`memory:recorded`。
> 3. `model:call` 事件必含 `usage:{prompt_tokens, cached_tokens, completion_tokens, total_tokens}`（字段冻结）。
> 4. 新事件 `budget:check` / `budget:exceeded`（供 GOV-01 消费，字段先冻结，熔断策略归角色D）。
> 5. Project Memory 条目 schema 冻结（`data/memory/<project_id>.json`，本地存储，不上传任何外部服务）。
> 6. `.env` 模型池新增可选键 `FLEET_MODEL_<i>_CACHE`（对外键 `cache`，默认 `false`），见 §5.1 / §13.6。

## 0. 通用约定

| 项 | 约定 |
|---|---|
| 监听地址 | `http://127.0.0.1:5000`（ADR 裁决：UI=控制台=5000，可用 `FLEET_CONSOLE_PORT` 覆盖） |
| 编码 | 请求/响应均 `application/json; charset=utf-8`；**请求体 UTF-8 解码失败时回退 GBK**（兼容 Windows 终端/旧客户端中文请求体） |
| 成功响应 | 顶层含 `"ok": true`（`/api/health` 除外，见 §1） |
| 失败响应 | 顶层含 `"ok": false` + `"reason"`（机器可读码）或 `"error"`（人类可读信息）；HTTP 状态码见各接口 |
| 鉴权 | 除豁免面（§7.3）外，所有 `/api/*` 请求必须持有效会话，否则 HTTP `401` + `{"ok": false, "reason": "unauthorized"}` |
| 时间格式 | ISO-8601 带本机时区偏移，如 `2026-09-15T13:20:31+08:00` |
| Key 安全 | 任何响应**不得**出现 Key 明文；模型池的 `api_key` 一律返回 `${VAR}` 占位或被遮蔽为 `***` |
| 未知路由 | HTTP `404` + `{"ok": false, "reason": "not_found"}` |
| 未知项目 | HTTP `200` + `{"ok": false, "reason": "project_not_found"}`（保证前端可机读，不用 404 表达业务态） |
| 静态资源 | `fleet/console/dist/` 优先，`fleet/console/static/` 兜底；无后缀路径 SPA 回 `index.html` |

---

## 1. `GET /api/health`

工作包 §9.6 硬性口径：返回体必须恰好包含 `version`、`db`、`events`、`config` 四个键。**豁免会话。**

**请求**
```http
GET /api/health HTTP/1.1
Host: 127.0.0.1:5000
```

**响应 200**
```json
{
  "version": "0.1.0",
  "db": true,
  "events": true,
  "config": true
}
```

| 字段 | 类型 | 含义 |
|---|---|---|
| `version` | string | 控制台版本，本工作包固定 `"0.1.0"` |
| `db` | bool | SQLite 可打开且 `tasks`/`projects` 表存在 |
| `events` | bool | `data/events.jsonl` 可读（不存在则视为 true，首次追加时创建） |
| `config` | bool | `.env` 可读且七段可解析 |

`false` 表示该子系统不可用，**不得**用 `true` 掩盖（`docs/启动Hermes派工2(英文版).txt` §2.3）。

---

## 2. `GET /api/plan?project=<project_id>`

三级大纲 + 任务当前状态的合并快照，供启动器轮询（`docs/启动Hermes派工2(英文版).txt` §7）。
未传 `project` 时取会话绑定的项目。

**请求**
```http
GET /api/plan?project=P-001 HTTP/1.1
Host: 127.0.0.1:5000
```

**响应 200（正常）**
```json
{
  "ok": true,
  "project": "P-001",
  "name": "AideanBot",
  "updated_at": "2026-09-15T13:20:31+08:00",
  "阶段": [
    {
      "名称": "阶段0 契约与地基",
      "任务": [
        {"子任务": "写三份契约文件", "task_id": "T-001"}
      ]
    }
  ],
  "tasks": [
    {
      "id": "T-001",
      "title": "写三份契约文件",
      "state": "DONE",
      "assignee": "worker-a",
      "reviewer": "reviewer-1",
      "verify_cmd": "python -c \"print(1)\"",
      "task_type": 2,
      "review_status": "PASS",
      "stage": "阶段0 契约与地基",
      "subtask": "写三份契约文件",
      "rework_count": 0,
      "updated_at": "2026-09-15T13:20:31+08:00"
    }
  ],
  "progress": {"project": "P-001", "total": 1, "done": 1, "percent": 100.0},
  "total": 1,
  "done": 1,
  "percent": 100.0
}
```

**响应 200（项目不存在）**
```json
{"ok": false, "reason": "project_not_found", "project": "P-999"}
```

**字段说明**：`tasks[].id` 与 `阶段[].任务[].task_id` 是同一标识（`初始设计/核心2.md`"每个阶段任务通过<任务id>对应"）。
`tasks[].state` 取值见 [`任务状态机.md`](./任务状态机.md)；`tasks[].verify_cmd` 供启动器执行机器门。
`progress/total/done/percent` 为 legacy 兼容字段（旧前端与启动器轮询用），`DONE` 与 `PARTIAL` 计入完成。

---

## 3. `GET /api/events?project=<project_id>&since=<seq>`

append-only 事件流读取。`since` 语义：**只返回 `seq > since` 的行**（`since=0` 返回全部）。

**请求**
```http
GET /api/events?project=P-001&since=3 HTTP/1.1
Host: 127.0.0.1:5000
```

**响应 200**
```json
{
  "ok": true,
  "project": "P-001",
  "since": 3,
  "seq": 5,
  "events": [
    {
      "seq": 4,
      "timestamp": "2026-09-15T13:20:33+08:00",
      "actor": "manager",
      "action": "task:doing",
      "taskId": "T-001",
      "summary": "T-001 进入执行中",
      "url": "/tasks/T-001",
      "project": "P-001",
      "extra": {"assignee": "worker-a", "model": "agnes-3.0-flash"}
    }
  ]
}
```

**顶层字段**：`ok`、`project`、`since`、`seq`（当前最大 seq，即下次轮询的游标）、`events`（数组）。
`since` 非数字 → HTTP `400` + `{"ok": false, "error": "since 参数必须是数字"}`。

**事件行字段（7 个冻结字段 + 2 个扩展字段）**

| 字段 | 类型 | 冻结 | 含义 |
|---|---|---|---|
| `seq` | int | ✓ | 单调递增，从 1 开始，**永不复用、永不修改** |
| `timestamp` | string | ✓ | ISO-8601 带时区 |
| `actor` | string | ✓ | 事件发起者（角色名或 `system`） |
| `action` | string | ✓ | 动作码（如 `task:assigned`、`launch:model_switch`） |
| `taskId` | string\|null | ✓ | 关联任务 id（驼峰，来自 `docs/启动Hermes派工2(英文版).txt` §7） |
| `summary` | string | ✓ | 人类可读摘要 |
| `url` | string\|null | ✓ | 控制台内可点击路径，如 `/tasks/T-001` |
| `project` | string\|null | 扩展 | 所属项目 id（供按项目过滤） |
| `extra` | object\|null | 扩展 | 附加机读字段（如 `from`/`to`/`attempts`） |

**动作码清单（v1.2 口径）**：`task:created`、`task:assigned`、`task:doing`、`task:submitted`、
`gate:pass`、`gate:fail`、`task:reviewing`、`task:review_pass`、`task:done`、`task:partial`、
`task:rework`、`task:escalated`、`task:escalated_release`、`task:rework_dispatch`、`task:blocked_release`、
`task:blocked`、`task:deferred`、`launch:*`、
`launch:model_switch`、`mode:changed`、`step_confirm`、`chat`、`chat_reply`、`config*`、
`model:call`、`prompt:assembled`、`budget:check`、`budget:exceeded`、`memory:recorded`
（后五个为 v1.2 新增，字段见 §13）。

**不变式**：任何代码不得修改或删除历史行；无 `since` 参数时按项目过滤返回全部。见 `tests/core/test_events.py`。

---

## 4. `POST /api/launch-event`（豁免会话）

启动器上报进度用（`docs/启动Hermes派工3(中文版).txt` T5/T6）。启动器（Hermes/CLI）不带 token 直接 POST；
仅监听 127.0.0.1，事件写入前仍过 `events.scrub` 脱敏。

**必填字段**：`project`、`phase`、`detail`。缺任一 → HTTP `400` 且**不写事件流**。
**可选字段**：`role`、`cli`、`model`、`percent`、`taskId`、`url`。

**请求（合法）**
```http
POST /api/launch-event HTTP/1.1
Host: 127.0.0.1:5000
Content-Type: application/json

{
  "project": "P-001",
  "phase": "dispatch_begins",
  "detail": "开始派工 T-001",
  "role": "manager",
  "cli": "hermes",
  "model": "agnes-3.0-flash",
  "percent": "10"
}
```

**响应 200**
```json
{
  "ok": true,
  "seq": 6,
  "action": "launch:dispatch_begins",
  "taskId": null,
  "url": null
}
```

**响应 400（缺字段）**
```json
{
  "ok": false,
  "reason": "missing_fields",
  "missing": ["project"]
}
```

**响应 400（body 非法）**
```json
{"ok": false, "reason": "invalid_json", "missing": []}
```
（body 不是合法 JSON 对象时；空 body 同样返回 `400`）

**响应 200（项目不存在）**
```json
{"ok": false, "reason": "project_not_found", "project": "P-999"}
```

**写作规则**：`action` 由 `launch:` + `phase` 拼接；`summary` 取 `detail`；若传了 `model`，写入 `extra.model`。
**脱敏规则**：任何进入事件流的字符串都要过 `fleet/core/events.py::scrub`，
命中 `sk-` / 40 位邮箱授权码形态时替换为 `${REDACTED}`（防 Key 泄漏，见 §5 与工作包 §10-3）。

---

## 5. `GET /api/config/<section>` 与 `POST /api/config/<section>`

契约七段：`basic`、`model_pool`、`roles`、`executors`、`email`、`notify`、`request`。
v1.1 增补**旧段名别名层**（写回时一律落契约段）：

| 请求段名（别名） | 落到契约段 |
|---|---|
| `settings` | `basic` |
| `models` | `model_pool` |
| `extensions` | `request` |
| `message` | `notify` |

**请求（GET）**
```http
GET /api/config/notify HTTP/1.1
Host: 127.0.0.1:5000
```

**响应 200（GET `notify`）**
```json
{
  "ok": true,
  "section": "notify",
  "data": {
    "on_task_start": false,
    "on_task_end": true,
    "on_manager_quota": true,
    "on_role_quota": true
  },
  "source": "E:\\Code\\AideanFleet\\.env",
  "mtime": "2026-09-15T13:19:58+08:00"
}
```

**响应 200（GET `model_pool`，Key 一律占位）**
```json
{
  "ok": true,
  "section": "model_pool",
  "data": {
    "models": [
      {
        "name": "agnes3",
        "level": 5,
        "base_url": "https://apihub.agnes-ai.com/v1",
        "model_id": "agnes-3.0-flash",
        "api_key": "${AGNES_API_KEY}",
        "http_proxy": "",
        "https_proxy": ""
      }
    ]
  },
  "source": "E:\\Code\\AideanFleet\\.env",
  "mtime": "2026-09-15T13:19:58+08:00"
}
```

**请求（POST）**
```http
POST /api/config/notify HTTP/1.1
Host: 127.0.0.1:5000
Content-Type: application/json

{"on_task_start": true, "on_task_end": false}
```

**响应 200（POST）**
```json
{
  "ok": true,
  "section": "notify",
  "applied": {"on_task_start": true, "on_task_end": false},
  "ignored": ["on_role_quota"],
  "mtime": "2026-09-15T13:24:10+08:00"
}
```

**响应 400（未知段）**
```json
{"ok": false, "reason": "unknown_section", "section": "foo",
 "known": ["basic", "model_pool", "roles", "executors", "email", "notify", "request"]}
```

**响应 403（引擎侧只读进程试图写盘）**
```json
{"ok": false, "reason": "config_write_denied"}
```

**响应 400（明文密钥拒绝写盘）**
```json
{"ok": false, "reason": "plaintext_secret_rejected", "error": "…"}
```

**写盘规则**（工作包 §9.2-4/5）：
1. 只有控制台进程允许写（`config.allow_write(True)`）；引擎侧调用 `config.save()` 抛 `ConfigWriteDenied`（`FLEET_CONFIG_WRITE=1` 可临时放开，测试用）。
2. 原子写：写入同目录临时文件 `.<name>.tmp` → `os.replace()` 覆盖（进程内串行锁防 Windows WinError 32）。
3. 段内**未知键被忽略并在 `ignored` 中列出**，不得静默丢弃（`ignored` 语义 = 请求里带了但没有对应 .env 键、因而未生效的键）。
4. `.env.example` 永不被写；`.env` 不存在时由 `config.ensure_env_file()` 原样复制生成。
5. `POST /api/config/model_pool` 的 `data` 结构同 GET；`api_key` 只能写 `${VAR}` 占位，控制台**拒绝**写入形如 `sk-...` 或 16 位大写形态的明文。

### 5.1 config section 键名 ↔ `.env` 段映射表（v1.1 新增）

`.env` 中所有程序键以 `FLEET_` 为前缀；一个 `.env` 文件同时承载七个逻辑段，靠键名前缀区分：

| 契约段 | `.env` 键前缀 | 键示例 | 说明 |
|---|---|---|---|
| `basic` | `FLEET_<语义>`（无中间前缀） | `FLEET_PROJECT_NAME`、`FLEET_CONSOLE_HOST`、`FLEET_CONSOLE_PORT`、`FLEET_MANAGER_PORT`、`FLEET_UI_PORT`、`FLEET_ALLOWED_ROOTS`、`FLEET_DEFAULT_PROJECT`、`FLEET_TIMEZONE`、`FLEET_LOCK_TTL_MINUTES` | 基础设置；空 token 段**最后**匹配，避免吞噬其他段新键 |
| `model_pool` | `FLEET_MODEL_<i>_` | `FLEET_MODEL_1_NAME/LEVEL/BASE_URL/MODEL_ID/API_KEY/HTTP_PROXY/HTTPS_PROXY/ENV_SCOPE/CACHE` | 列表段：`i` 从 1 递增；`API_KEY` 只存 `${VAR}` 占位；`CACHE` 可选（`true/false`，默认 `false`，Prompt Cache 开关，见 §13.6） |
| `roles` | `FLEET_ROLE_<i>_` | `FLEET_ROLE_1_NAME/SYSTEM_PROMPT/BIND_MODEL_NAME/ADAPTER` | 列表段；`ADAPTER` 即 `fleet/executors/<name>` 适配器名 |
| `executors` | `FLEET_EXECUTOR_<i>_` | `FLEET_EXECUTOR_1_NAME/COMMAND/TIMEOUT` | 列表段；`COMMAND` 为派工默认命令（ADR：单次非交互） |
| `email` | `FLEET_SMTP_` | `FLEET_SMTP_ENABLED/SENDER/RECEIVER/HOST/PORT/AUTH_CODE/USE_SSL` | 授权码真值只放环境变量，`.env` 存 `${VAR}` |
| `notify` | `FLEET_NOTIFY_` | `FLEET_NOTIFY_ON_TASK_START/ON_TASK_END/ON_MANAGER_QUOTA/ON_ROLE_QUOTA` | 通知触发开关（角色C triggers 同源） |
| `request` | `FLEET_REQUEST_` | `FLEET_REQUEST_TIMEOUT/RETRY_MAX/RETRY_DELAY` | 网关重试策略（默认 600 秒 / 10 次 / 10 秒） |

解析顺序（`fleet/core/config.py::_section_of_env_key`）：`FLEET_MODEL_*` → `FLEET_ROLE_*` → `FLEET_EXECUTOR_*`
→ `FLEET_SMTP_*` → `FLEET_NOTIFY_*` → `FLEET_REQUEST_*` → 其余 `FLEET_*` 归 `basic`（空 token 必须最后匹配）。

---

## 6. 扩展接口（非第 9.1-3 条必需，但启动器协议需要）

`docs/启动Hermes派工2(英文版).txt` §5 要求 `POST /tasks/<task_id>/dispatch` 作为首选派工方式，故一并暴露。

### 6.1 `GET /api/tasks/<task_id>`

```json
{
  "ok": true,
  "task": {
    "task_id": "T-001",
    "project_id": "P-001",
    "title": "写三份契约文件",
    "role": "worker-a",
    "dispatcher_role": "manager",
    "receipt_role": "reviewer-1",
    "platform": "modelscope",
    "model": "ZhipuAI/GLM-5.2",
    "task_type": 2,
    "token": null,
    "duration_ms": 1234,
    "detail": "……",
    "remark": "",
    "exec_status": "SUBMITTED",
    "review_status": "PENDING",
    "created_at": "2026-09-15T13:20:31+08:00",
    "updated_at": "2026-09-15T13:21:02+08:00",
    "assignee": "worker-a",
    "reviewer": "reviewer-1",
    "verify_cmd": "python -c \"print(1)\"",
    "workspace": "E:\\Code\\AideanBot",
    "allowed_files": "data/smoke.txt",
    "forbidden_files": ".env",
    "adapter": "fake",
    "evidence_path": "data/projects/P-001/evidence/T-001/",
    "report_path": "",
    "baseline_path": "",
    "rework_count": 0,
    "blocked_reason": "",
    "retry_limit": 3
  }
}
```

响应 200（不存在）：`{"ok": false, "reason": "task_not_found", "taskId": "T-999"}`

### 6.2 `POST /tasks/<task_id>/dispatch`

触发"派工→机器门→审查→（返工循环）→终态"的完整链条（`dispatcher.run_to_completion`）。
**v1.1 修正**：响应体以实现口径为准——每轮结果收进 `rounds` 数组，不再平铺 gate/review 字段。

```http
POST /tasks/T-001/dispatch HTTP/1.1
Content-Type: application/json
{}
```

**响应 200（走到终态或阻塞）**
```json
{
  "ok": true,
  "taskId": "T-001",
  "state": "DONE",
  "rounds": [
    {
      "round": 1,
      "state": "DONE",
      "verdict": "PASS",
      "gate": {"passed": true, "reasons": [], "exit_code": 0},
      "rework_count": 0
    }
  ]
}
```

**响应 200（阻塞，如适配器不可用）**
```json
{"ok": false, "reason": "blocked", "taskId": "T-001", "state": "BLOCKED", "detail": "adapter_unavailable: …"}
```

**响应 200（任务不存在）**
```json
{"ok": false, "reason": "task_not_found", "taskId": "T-999"}
```

**响应 409（非法迁移，如对 `DONE` 任务再次派工）**
```json
{"ok": false, "reason": "invalid_transition", "from": "DONE", "to": "ASSIGNED", "taskId": "T-001", "error": "…"}
```

---

## 7. 会话与鉴权（v1.1 新增）

控制台为"项目名解锁"模型：输入已注册项目名 → 换取内存会话 token → 后续请求带 token。

### 7.1 `POST /api/session`（豁免会话）

**请求**（`project` 必填；请求体 UTF-8 解码失败回退 GBK）
```http
POST /api/session HTTP/1.1
Host: 127.0.0.1:5000
Content-Type: application/json

{"project": "P-001", "user": "操作员"}
```

**响应 200**
```json
{"ok": true, "token": "9f1c…64 位 hex", "project": "P-001", "expires_in": 3600}
```
同时 `Set-Cookie: fleet_token=<token>; Max-Age=<expires_in>; SameSite=Lax`（cookie 与 Bearer 双通道同值）。

**响应 400（缺项目名）** `{"ok": false, "error": "请输入项目名"}`
**响应 400（项目未注册）** `{"ok": false, "error": "项目不存在，请检查项目名是否正确"}`
**响应 400（body 非法）** `{"ok": false, "error": "请求体必须是 JSON 对象"}`

### 7.2 `GET /api/session` 与 `DELETE /api/session`

```json
// GET 200：会话有效
{"ok": true, "project": "P-001", "expires_in": 3541}
// GET 401：无效或过期
{"ok": false, "error": "会话无效或已过期"}
// DELETE 200：登出（幂等，token 无效也返回）
{"ok": true}
```

### 7.3 会话闸门（中间件语义）

- **豁免路径**：`/api/health`、`/api/session`（全部方法）、`/api/launch-resolve`、`/api/launch-event`，以及所有非 `/api/` 路径（静态页面）。
- **其余 `/api/*`**：无有效会话 → HTTP `401` + `{"ok": false, "error": "会话无效或已过期，请重新输入项目名解锁", "reason": "unauthorized"}`。
- **token 三层来源**（优先级从高到低）：`Authorization: Bearer <token>` → cookie `fleet_token` → 查询参数 `?token=`。
- **有效期**：`FLEET_SESSION_EXPIRE_SECONDS` > `.env` basic 段 `lock_ttl_minutes`×60 > 旧键 `FLEET_LOCK_SCREEN_SECONDS`/`FLEET_LOCK_TTL_MINUTES` > 默认 3600。

---

## 8. WebSocket 实时通道（v1.1 新增）

### 8.1 连接

```text
ws://127.0.0.1:5000/ws?token=<会话token>
```

- token 也可来自 `Authorization` 头或 cookie（与 §7.3 三层一致）。
- **无有效会话**：连接被拒（accept 前拒闭，客户端表现为 HTTP 403 握手失败 / 关闭码 4401 语义）。
- 首个连接建立时启动**事件泵**：每秒一拍扫（a）新增事件行→按动作码映射为服务端消息广播；
  （b）各项目 `plan.json` mtime 变化→`plan_update` + `progress`；（c）`.env` mtime 变化→`config_changed`。
- 服务端消息体均为 JSON 对象，第一字段固定为 `type`（下表 7 种之一）。

### 8.2 服务端 → 客户端（7 种，type 字段冻结）

| type | 载荷字段 | 产生时机 |
|---|---|---|
| `task_update` | `event`（完整事件行）或 `taskId`+`state` 或 `dispatch`（派工结果） | `task:*`/`gate:*`/`task:deferred` 事件；派工与人工放行动作 |
| `plan_update` | `project`、`plan`（完整 plan.json 快照） | plan.json 变化 |
| `progress` | `project`、`total`、`done`、`percent` | 每条带项目的事件后；plan 变化后 |
| `stream_chunk` | `taskId`、`chunk`（预留） | **预留**：执行体流式输出（INT-03 接入），当前无产生方 |
| `chat_message` | `event`（`chat`/`chat_reply` 事件行）或回执 | 用户发言、Manager 回执 |
| `notification` | 任意附加字段（如 `mode`、`error`、`event`） | `mode:changed`、错误提示、系统提醒等兜底类型 |
| `config_changed` | `section?`、`mtime?` | `.env` 或拓展配置变化 |

示例：
```json
{"type": "task_update", "event": {"seq": 9, "action": "task:doing", "taskId": "T-001", "…": "…"}}
{"type": "progress", "project": "P-001", "total": 12, "done": 3, "percent": 25.0}
```

### 8.3 客户端 → 服务端（3 种，type 字段冻结）

| type | 载荷 | 服务端回执 |
|---|---|---|
| `chat` | `{"type": "chat", "message": "…", "project"?}` | 写 `chat` 事件 + 广播，回 `{"type": "chat_message", "event": {…}}` |
| `set_mode` | `{"type": "set_mode", "mode": "auto\\|step", "actor"?}` | 切换调度模式（发 `mode:changed` 事件），回 `{"type": "notification", "mode": "auto"}`；非法值回 `{"type": "notification", "mode": null}` |
| `confirm_step` | `{"type": "confirm_step", "taskId"?, "note"?}` | 喂调度总线确认 + 写 `step_confirm` 事件，回 `{"type": "notification", "event": {…}}` |

- 消息非 JSON / 非对象 → `{"type": "notification", "error": "消息必须是 JSON 对象"}`。
- 未知 `type` → `{"type": "notification", "error": "未知消息类型：<type>"}`。
- 旧值 `confirm` 与新值 `step` 等价（入参兼容，`effective` 一律为 `step`）。

---

## 9. 调度与人工控制（v1.1 新增）

### 9.1 `GET /api/mode` 与 `POST /api/mode`

```json
// GET 200
{"ok": true, "mode": "auto", "awaiting_confirm": false}
// POST 请求
{"mode": "step", "actor": "用户"}
// POST 200（mode 回显入参原值，effective 为归一化后值）
{"ok": true, "mode": "step", "effective": "step"}
// POST 400
{"ok": false, "error": "mode 只能为 confirm/step（每步确认）或 auto（自动执行）"}
```

> **mode 语义说明（v1.1 定版）**：`/api/mode` 承载的是**调度模式**（`auto` 自动执行 / `step` 每步人工确认），
> 与 UI 工作模式五值 `run/intake/audit/discuss/plan`（ADR-020，前端状态机，启动器 `hermes_entry` 消费）是两个正交概念。

### 9.2 `POST /api/confirm`（旧步进确认路由，保留兼容）

**请求**：`{"taskId"?, "decision": "confirm|note", "note"?, "project"?}`
**响应 200**：`{"ok": true, "event": {…step_confirm 事件行…}}`
`decision=confirm` 且无 note → 摘要"用户确认当前步骤"；`decision=note` 必须带 note（"意见内容不能为空"，400）。
同时喂给调度总线（步进模式下放行下一拍派工）。

### 9.3 `POST /api/control/confirm`（人工放行，按任务状态分流）

**请求**：`{"taskId": "T-001", "note"?}`（兼容 `task_id`/`message` 字段名）

| 任务当前状态 | 动作 | 响应 200 |
|---|---|---|
| `ESCALATED` | `rework_manager.confirm_release`：创建 `-R{n}` 后继任务（rework_count 保留），原任务保持 ESCALATED | `{"ok": true, "successor": "T-001-R1", "…": "…"}` |
| `REWORK` | `rework_manager.redispatch`：返工意见并入 detail 后重新派工 | `{"ok": true, "taskId": "T-001", "state": "SUBMITTED", "detail": "…"}` |
| `BLOCKED` | `task:blocked_release` 迁回 ASSIGNED 并派工，广播 task_update | `{"ok": true, "taskId": "T-001", "state": "SUBMITTED", "detail": "…"}` |
| 其余（运行中） | 按步进确认处理（同 §9.2 语义） | `{"ok": true, "event": {…}}` |

缺 `taskId` → 400 `{"ok": false, "error": "缺少 taskId"}`；任务不存在 → 200 `{"ok": false, "reason": "task_not_found", "taskId": "…"}`。

### 9.4 `POST /api/chat`

**请求**：`{"message": "…", "project"?}`（空消息 → 400 `{"ok": false, "error": "消息内容不能为空"}`）
**响应 200**：`{"ok": true, "user_event": {…}, "manager_event": {…}, "reply": "【Manager·回执】…"}`。
写 `chat` 与 `chat_reply` 两条事件（经脱敏），Manager 回执由 WS `chat_message` 广播。

---

## 10. 启动解析（v1.1 新增，豁免会话）

### `GET /api/launch-resolve?project=<pid>&mode=<BOOT|RUN>`

启动器/浏览器在解锁前预检项目与启动参数。

```json
// 200（未知项目也是 200，业务态用 ok 表达）
{"ok": false, "reason": "project_not_found", "missing": ["project"]}
// 200
{"ok": true, "mode": "BOOT", "ui_url": "http://127.0.0.1:5000/?project=P-001",
 "profile_source": "E:\\Code\\AideanFleet\\.env", "missing": []}
```

`mode` 只接受 `BOOT`/`RUN`，其他值记入 `missing: ["mode"]` 但整体仍 `ok: true`（由调用方决定是否继续）。

---

## 11. 项目 / 拓展 / 通知（v1.1 新增）

### 11.1 `GET /api/projects`

```json
{"ok": true, "projects": [{"id": "P-001", "name": "演示项目", "path": "E:\\Code\\DemoProject", "port": null}]}
```

### 11.2 `GET /api/extensions` 与 `POST /api/extensions`

执行体 skills/mcp 勾选配置，落 `data/extensions.json`（原子写），变化广播 `config_changed`。

```json
// GET 200
{"ok": true, "data": {"worker-a": {"skills": ["search"], "mcp": []}}, "source": "…\\data\\extensions.json"}
// POST 请求（{"data": {...}} 或平铺均可；非 dict 记录忽略）
{"data": {"worker-a": {"skills": ["search", " "], "mcp": ["fetch"]}}}
// POST 200（空串项被剔除）
{"ok": true, "message": "拓展配置已保存", "count": 1}
```

### 11.3 `POST /api/notify/test`

发送测试邮件，参数取 `.env` email 段。三种结果：

```json
// 200（配置缺失：不发送，指明缺什么）
{"ok": false, "error": "邮件配置不完整，缺少：发件邮箱、收件邮箱、授权码。请到「消息」页填好后重试（授权码真值只放环境变量，.env 存 ${VAR}）。"}
// 503（fleet.notify 模块不可用：try import 探测失败）
{"ok": false, "reason": "notify接线未完成", "error": "…"}
// 200（发送完成）
{"ok": true, "message": "…", "receiver": "ops@example.com"}
```

### 11.4 `GET /api/notify/triggers`

角色C 触发开关清单（`config/notifications.json`，控制台只读展示）：

```json
{"ok": true, "data": {"task_start": {"enabled": true}}, "source": "…\\config\\notifications.json"}
// 文件不存在时 data 为 {}；读取失败 500 {"ok": false, "error": "读取触发器配置失败：…"}
```

---

## 12. 定版裁决（v1.1）

| 项 | 定版 | 依据 |
|---|---|---|
| 端口 | UI = 控制台 = `5000`（`FLEET_CONSOLE_PORT` 可覆盖；Manager 网关端口 `FLEET_MANAGER_PORT=9900` 与项目端口互不相干） | ADR-017 |
| UI 工作模式 | 五值 `run` / `intake` / `audit` / `discuss` / `plan`（intake 产出 PRD 后转 plan；audit 只读体检；discuss 圆桌 ≤3 轮只读） | ADR-020，启动器 `fleet/launcher/hermes_entry.py` 消费 |
| 调度模式 | 二值 `auto` / `step`（旧值 `confirm` 兼容等价 `step`），由 `/api/mode` 与 WS `set_mode` 承载 | ADR-020 关联 |
| 派工默认 | 启动器默认命令取 `.env` executors 段 `COMMAND`，**单次、非交互**（如 `claude --dangerously-skip-permissions`） | ADR-021 |

---

## 13. 上下文成本引擎契约（v1.2 新增，字段冻结）

> 目标：派工 prompt 不再携带全量上下文，而是"项目记忆条目 + 按预算裁剪的任务上下文"；
> 返工任务只携带增量（上轮 diff + 失败证据）；稳定前缀命中 provider 前缀缓存。
> 唯一接口是 `events.jsonl`：角色D（GOV-01）只消费 `model:call` / `prompt:assembled` / `budget:*` 事件做聚合与熔断，
> 不写引擎；熔断策略与审批门归角色D，本契约只冻结事件字段与计量口径。

### 13.1 TaskPack 三个可选字段（向后兼容，缺省行为不变）

| 字段 | 类型 | 缺省 | 含义 |
|---|---|---|---|
| `context_budget` | int | `8000` | 本任务 prompt 上下文 token 上限（估算口径见 §13.7）；`<300` 视为非法，按缺省处理 |
| `memory_refs` | list[str] | `[]` | 允许引用的项目记忆条目 id（见 §13.3）；**空列表 = 不注入记忆头**（与 v1.1 行为一致） |
| `retry_context` | object\|null | `null` | 返工增量上下文（见 §13.5），由返工管理器自动填充，外部不得手工伪造 |

- 三字段同时落 `tasks` 表扩展列（`context_budget` INTEGER / `memory_refs` TEXT(JSON) / `retry_context` TEXT(JSON)），
  列名与语义见 [`任务进度表字段.md`](./任务进度表字段.md) §2；旧库由 `db.init_db()` 轻量迁移自动补列。
- `retry_context` 是派生数据（可由事件流/工作区重建），跨重启不保证保留，执行体不得依赖其持久性。

### 13.2 计量事件字段（冻结，供 GOV-01 聚合）

**`model:call`**（actor=`router` 或 `manager`）：每次真实模型调用成功后发一条，`extra` 必含：

```json
{
  "role": "be-1", "model": "m1", "model_id": "demo-1", "adapter": "stub",
  "usage": {"prompt_tokens": 1200, "cached_tokens": 800, "completion_tokens": 350, "total_tokens": 1550}
}
```

- `usage` 四个键**必须齐全**；服务端未返回的值如实填 `0`，**不得省略键、不得估算冒充**。
- `cached_tokens` 口径：OpenAI 兼容取 `usage.prompt_tokens_details.cached_tokens`；
  DeepSeek 口径取 `usage.prompt_cache_hit_tokens`；其余取不到时为 `0`（如实降级，不做假装缓存）。

**`prompt:assembled`**（actor=`manager`）：每次派工 prompt 组装后发一条，`extra` 必含：

```json
{
  "budget": 8000, "actual": 2650, "fixed_tokens": 350,
  "files": ["a.py", "b.md"], "trimmed": ["big.log"],
  "memory_refs": ["M-0001"], "rework": false
}
```

**`budget:check`**：每次组装后发一条（`extra` 含 `budget`/`actual`/`within` 布尔，供 GOV-01 直接聚合）。
**`budget:exceeded`**：仅当固定段（system_prompt+记忆头+任务说明）本身就超预算、裁剪无法挽回时发，
`extra` 必含 `budget`、`actual`、`oversize_tokens`；此时仍按原样派工（不阻断，熔断决策归角色D）。
**`memory:recorded`**：每写入一条项目记忆发一条，`extra` 含 `memory_id`、`kind`、`task_id`、`source`（`decision`/`distill`/`correction`）。

### 13.3 Project Memory（`fleet/core/memory.py`）

- 存储：`data/memory/<project_id>.json`，原子写（临时文件 + `os.replace`），**只落本地 `data/`，不上传任何外部服务**。
- 条目 schema（字段冻结）：

```json
{
  "id": "M-0001", "kind": "decision|artifact|fact",
  "title": "≤80 字标题", "summary": "≤200 字摘要",
  "refs": ["相关文件/任务 id"], "created_at": "ISO-8601", "task_id": "T-001"
}
```

- 条目来源三类：① Manager 重大决策（`record_decision`）；② 任务 DONE 时六节报告自动提炼 1 条
  （`distill_from_report`：title=任务标题，summary=改动要点+关键决策 ≤200 字）；③ 用户对话中的显式修正（`record_correction`）。
- `build_memory_header(project_id, memory_refs) -> str`：把引用的条目渲染为 prompt 头部，
  **每条只输出 ≤200 字摘要，绝不内嵌全文/全代码**；`memory_refs` 为空时返回空串。

### 13.4 Task Context 预算裁剪（`fleet/manager/context_budget.py`）

- `assemble_prompt(task, memory_header, context_files, budget) -> str`，固定顺序：
  `system_prompt + memory_header + 任务说明（DISPATCH 模板） + 上下文文件内容`。
- 裁剪规则：上下文文件按序处理；每文件先取文件头 + 尾部 + 与任务关键词命中段，单文件上限与总预算双重约束；
  超预算按序截断，prompt 尾部附固定清单：`（上下文已按预算裁剪，完整文件路径如下，可按需读取）` + 逐行列出全部涉及文件路径。
- 每次组装必须发 `prompt:assembled` + `budget:check`（固定段本身超预算时加发 `budget:exceeded`，见 §13.2）。

### 13.5 Incremental Diff（返工增量，`fleet/manager/rework_manager.py`）

- 返工时自动生成 `retry_context`：

```json
{
  "attempt": 2,
  "failure": {"gate": {"passed": false, "reasons": ["…"]}, "review": "审查意见…"},
  "previous_diff": {"stat": "…git diff --stat 截尾…", "files": {"a.py": "…diff 截尾…"}},
  "evidence_paths": ["…/evidence/T-001/gate/stdout.txt"]
}
```

- 返工 prompt 组装规则：**不重复发送项目记忆全文与全量上下文**——只发 `retry_context` + 修复指令；
  执行体提示词模板必须包含固定句：`这是第 N 轮返工，只需基于以下增量信息修复，不要重新调查全项目`。
- `previous_diff` 来源：优先 `git diff --stat` + 关键文件 diff（在 workspace 内执行，截尾）；无 git 仓库时回退
  `gates/verify.py` 的基线快照对比；两者皆无时留空并在其中注明，不得编造。

### 13.6 Prompt Cache（`fleet/models/transport.py`）

- 请求体分离**稳定前缀**与**动态后缀**：前缀段 = `system_prompt` + `memory_header`（同角色同项目内字节级稳定，
  内容变化即版本号 +1 重建，见 `transport.set_stable_prefix/get_stable_prefix`）；动态后缀 = 任务说明 + 上下文 + 返工增量。
- `.env` 模型池新增可选键 `FLEET_MODEL_<i>_CACHE=true|false`（对外键 `cache`，默认 `false`）：
  开启时对支持前缀缓存的服务透传启用标记（message 级 `cache_control`，Anthropic 口径；OpenAI 兼容自动前缀缓存无需标记也可命中）；
  不支持的服务如实降级——请求照发、`cached_tokens` 记 `0`，**不做假装缓存**。
- 缓存命中与否以响应 `usage.cached_tokens` 为准（口径见 §13.2）。

### 13.7 token 计量口径（冻结）

- 服务端返回 `usage` 时以服务端为准；无服务端计量时，估算口径统一为 **tokens ≈ 字符数 ÷ 4**（中英混排经验值，
  仅供预算裁剪与 GOV-01 聚合，不冒充服务端计量）。所有估算值写入事件时必须走 `prompt:assembled` / `budget:*`，
  与 `model:call` 的服务端 `usage` 严格区分。

## 14. 事件归档与读取语义（v1.2 增补注记 · REL-01，字段冻结）

### 14.1 轮转规则（`fleet/rel/archive.py`）

- `data/events.jsonl` 为**热文件**；时间戳月份早于当前月的行按月压缩到
  `data/archive/events-YYYYMM.jsonl.gz`（gzip 文本，一行一个 JSON，内容逐字保留）。
- 轮转锚点：归档前先追加一条锚点事件 `rel:archived`（actor=rel，extra={months, rows}），
  随后热文件原子重建为 `seq >= 锚点 seq` 的行——`events.append` 的 seq 由此保持全局单调连续。
- 归档写入幂等：已有同 seq 行的归档文件跳过重复写入（中断重跑安全）。

### 14.2 读取语义（与角色D 对齐）

- `GET /api/events`（`events.read` / `read_events_since`）：**只查热数据**。客户端游标 `since`
  在轮转后依然有效——热文件行数减少但 seq 不回退，增量拉取语义不变。
- 归档数据走报表通道：`fleet.rel.archive.read_all(project, since, limit)` 按 seq 全序合并
  归档与热数据；`verify_continuity()` 校验合并后 seq 从 1 开始、无空洞、无重复。
- **usage 聚合不受影响**：GOV-01 的计量聚合读 SQLite（`governance_usage` 表，写入点为
  `model:call` 落库链路），不经 events.jsonl；事件归档不改变其任何口径。

### 14.3 新增事件动作码（v1.2 增补）

| action | 触发方 | 语义 | extra 冻结字段 |
|---|---|---|---|
| `rel:archived` | archive | 归档锚点事件 | `months: list[str]`, `rows: int` |
| `rel:evidence_archived` | archive | 任务证据目录已归档 | `zip: str`, `files: int` |
| `rel:restart` | watchdog | 控制台进程被拉起 | `restarts: int`, `old_pid`, `new_pid`, `port: int` |
| `rel:escalate` | watchdog | 防风暴触发，停止拉起等人工 | `restarts: int`, `window_seconds: int`, `max_restarts: int`, `port: int` |
| `task:stuck` | retry_timer | DOING 超过阈值，疑似卡死 | `stuck_seconds: int`, `threshold_seconds: int` |
| `task:stuck_escalated` | retry_timer | 超过 2 倍阈值，升级 BLOCKED | `stuck_seconds: int`, `threshold_seconds: int` |

### 14.4 新增配置键（v1.2 增补）

- `.env` 新增 `[SECTION: settings]` 段：`FLEET_SETTINGS_TASK_STUCK_SECONDS`（int，默认 1800，
  非法/缺省回默认）。模型调用重试口径仍归 §13.7 与 `models/retry.py`，本键只管卡死检测与升级。
- watchdog 开关：`FLEET_WATCHDOG=1` 时由 `launch_core` 第⑨步以独立进程拉起
  `python -m fleet.rel.watchdog`（缺省关闭，遵循 `FLEET_SCHEDULER` 模式）。
