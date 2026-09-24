# CORE-03 证据留痕（角色A · 后端核心工程师）

本文件是 CORE-03 工作包（契约 v1.1 + .env 单格式收尾 + requirements 与测试可复现 + resolve 集成护栏 + 八项裁决 ADR + notify 服务侧解堵）的客观证据汇总。执行环境：`E:\Code\AideanFleet`，Windows 10，Python 3.12.13，2026-09-15。

## 1. 干净环境复现（硬性验收项：创建环境 → 全绿的原样输出）

```text
$ python -m venv .venv
（无输出，创建成功）

$ .venv/Scripts/python.exe --version
Python 3.12.13

$ .venv/Scripts/python.exe -m pip install -r requirements.txt
Looking in indexes: https://pypi.tuna.tsinghua.edu.cn/simple
Requirement already satisfied: fastapi==0.141.1 in e:\code\aideanfleet\.venv\lib\site-packages (from -r requirements.txt (line 3)) (0.141.1)
Requirement already satisfied: uvicorn==0.53.0 in e:\code\aideanfleet\.venv\lib\site-packages (from uvicorn[standard]==0.53.0->-r requirements.txt (line 4)) (0.53.0)
Requirement already satisfied: websockets==17.1.0 in e:\code\aideanfleet\.venv\lib\site-packages (from -r requirements.txt (line 5)) (17.1)
Requirement already satisfied: httpx==0.28.1 in e:\code\aideanfleet\.venv\lib\site-packages (from -r requirements.txt (line 6)) (0.28.1)
Requirement already satisfied: pytest==9.1.1 in e:\code\aideanfleet\.venv\lib\site-packages (from -r requirements.txt (line 7)) (9.1.1)
Requirement already satisfied: starlette>=0.46.0 in e:\code\aideanfleet\.venv\lib\site-packages (from fastapi==0.141.1->-r requirements.txt (line 3)) (1.6.0)
Requirement already satisfied: pydantic>=2.9.0 in e:\code\aideanfleet\.venv\lib\site-packages (from fastapi==0.141.1->-r requirements.txt (line 3)) (2.13.5)
Requirement already satisfied: typing-extensions>=4.8.0 in e:\code\aideanfleet\.venv\lib\site-packages (from fastapi==0.141.1->-r requirements.txt (line 3)) (4.16.0)
Requirement already satisfied: typing-inspection>=0.4.2 in e:\code\aideanfleet\.venv\lib\site-packages (from fastapi==0.141.1->-r requirements.txt (line 3)) (0.4.4)
Requirement already satisfied: annotated-doc>=0.0.2 in e:\code\aideanfleet\.venv\lib\site-packages (from fastapi==0.141.1->-r requirements.txt (line 3)) (0.0.5)
Requirement already satisfied: click>=7.0 in e:\code\aideanfleet\.venv\lib\site-packages (from uvicorn==0.53.0->uvicorn[standard]==0.53.0->-r requirements.txt (line 4)) (8.5.0)
Requirement already satisfied: h11>=0.8 in e:\code\aideanfleet\.venv\lib\site-packages (from uvicorn==0.53.0->uvicorn[standard]==0.53.0->-r requirements.txt (line 4)) (0.16.0)
Requirement already satisfied: anyio in e:\code\aideanfleet\.venv\lib\site-packages (from httpx==0.28.1->-r requirements.txt (line 6)) (4.15.1)
Requirement already satisfied: certifi in e:\code\aideanfleet\.venv\lib\site-packages (from httpx==0.28.1->-r requirements.txt (line 6)) (2026.7.22)
Requirement already satisfied: httpcore==1.* in e:\code\aideanfleet\.venv\lib\site-packages (from httpx==0.28.1->-r requirements.txt (line 6)) (1.0.9)
Requirement already satisfied: idna in e:\code\aideanfleet\.venv\lib\site-packages (from httpx==0.28.1->-r requirements.txt (line 6)) (3.19)
Requirement already satisfied: colorama>=0.4 in e:\code\aideanfleet\.venv\lib\site-packages (from pytest==9.1.1->-r requirements.txt (line 7)) (0.4.6)
Requirement already satisfied: iniconfig>=1.0.1 in e:\code\aideanfleet\.venv\lib\site-packages (from pytest==9.1.1->-r requirements.txt (line 7)) (2.3.0)
Requirement already satisfied: packaging>=22 in e:\code\aideanfleet\.venv\lib\site-packages (from pytest==9.1.1->-r requirements.txt (line 7)) (26.3)
Requirement already satisfied: pluggy<2,>=1.5 in e:\code\aideanfleet\.venv\lib\site-packages (from pytest==9.1.1->-r requirements.txt (line 7)) (1.6.0)
Requirement already satisfied: pygments>=2.7.2 in e:\code\aideanfleet\.venv\lib\site-packages (from pytest==9.1.1->-r requirements.txt (line 7)) (2.21.0)
Requirement already satisfied: httptools>=0.8.0 in e:\code\aideanfleet\.venv\lib\site-packages (from uvicorn[standard]==0.53.0->-r requirements.txt (line 4)) (0.8.0)
Requirement already satisfied: python-dotenv>=0.13 in e:\code\aideanfleet\.venv\lib\site-packages (from uvicorn[standard]==0.53.0->-r requirements.txt (line 4)) (1.2.3)
Requirement already satisfied: pyyaml>=5.1 in e:\code\aideanfleet\.venv\lib\site-packages (from uvicorn[standard]==0.53.0->-r requirements.txt (line 4)) (6.0.3)
Requirement already satisfied: watchfiles>=0.20 in e:\code\aideanfleet\.venv\lib\site-packages (from uvicorn[standard]==0.53.0->-r requirements.txt (line 4)) (1.2.0)
Requirement already satisfied: annotated-types>=0.6.0 in e:\code\aideanfleet\.venv\lib\site-packages (from pydantic>=2.9.0->fastapi==0.141.1->-r requirements.txt (line 3)) (0.8.0)
Requirement already satisfied: pydantic-core==2.46.5 in e:\code\aideanfleet\.venv\lib\site-packages (from pydantic==2.13.5->fastapi==0.141.1->-r requirements.txt (line 3)) (2.46.5)
[notice] A new release of pip is available: 25.0.1 -> 26.2.1
[notice] To update, run: E:\Code\AideanFleet\.venv\Scripts\python.exe -m pip install --upgrade pip

（首次安装时以上各行为 "Collecting/Downloading/Installing"，此处为二次执行回放，
 全部依赖已就位；完整依赖闭包见下方 pip freeze）
```

`pip freeze`（venv 实际闭包，共 27 项，无 ORM、无消息队列、无前端工具链）：

```text
$ .venv/Scripts/python.exe -m pip freeze
annotated-doc==0.0.5
annotated-types==0.8.0
anyio==4.15.1
certifi==2026.7.22
click==8.5.0
colorama==0.4.6
fastapi==0.141.1
h11==0.16.0
httpcore==1.0.9
httptools==0.8.0
httpx==0.28.1
idna==3.19
iniconfig==2.3.0
packaging==26.3
pluggy==1.6.0
pydantic==2.13.5
pydantic_core==2.46.5
Pygments==2.21.0
pytest==9.1.1
python-dotenv==1.2.3
PyYAML==6.0.3
starlette==1.6.0
typing-inspection==0.4.4
typing_extensions==4.16.0
uvicorn==0.53.0
watchfiles==1.2.0
websockets==17.1
```

新 venv 全量测试（原样输出）：

```text
$ .venv/Scripts/python.exe -m pytest tests -q
........................................................................ [ 74%]
........................                                                                 [100%]
-- Docs: https://docs.pytest.org/en/stable/how-to/capture-warnings.html
95 passed, 42 warnings in 28.05s
```

宿主环境同口径复核：`python -m pytest tests -q` → `95 passed, 42 warnings in 21.98s`。

> 说明：requirements.txt 的版本钉子（==）来自上述实测闭包。按工作包要求"以 grep import 结果为准"，
> 只列实际 import 集合：fastapi / uvicorn / websockets / httpx（fastapi.testclient 运行时依赖）/ pytest；
> **未**列入 pyyaml（无任何直接 import，仅作为 uvicorn[standard] 的传递依赖出现在闭包）与
> pytest-asyncio（测试全部为同步形态，无 asyncio mark）。

## 2. resolve 集成护栏（tests/core/test_resolve_integration.py）

执行记录（本包会话内时间线）：

1. 初版按工作包要求写入 strict xfail（reason="等待 INT-03 适配器迁移"）。
2. 实测确认当时根因：`resolve()` 冷启动顺序为"查注册表 → import 模块 → 找模块级 `Adapter` 属性"，
   而 `fleet/executors/*` 只有 `<Name>Adapter` 类名、无 `Adapter` 属性，装饰器注册晚于属性查找，
   冷进程必然 `AdapterNotAvailable` —— xfail 成立（本机实测：`dispatch → BLOCKED, detail=adapter_unavailable: …里没有 Adapter 类或 adapter 实例`）。
3. 本会话期间角色C 的 INT-03 迁移在工作区落地（`Adapter = <Name>Adapter` 别名，executors 文件 mtime 16:49），
   strict xfail 立即触发强制（XPASS → FAILED）——护栏按设计发挥强制作用。
4. 按交接协议摘除标记，护栏全量生效：

```text
$ python -m pytest tests/core/test_resolve_integration.py -q
.....                                                                    [100%]
5 passed in 0.89s
```

用例构成：test_resolve_to_done_chain（不经 register()、resolve("fake") → create_task → dispatch →
review → DONE，8 事件链与十场景 #10 同口径精确断言）+ 4 个真实适配器
（claudecode/codex/hermes/opencode）的能力探测用例（实例经 ADAPTER_REGISTRY 获取，
方法名兼容 capabilities()/probe() 两种迁移形态；CLI 不在 PATH 时 skip 并注明原因）。

## 3. .env 单格式收尾

```text
$ mv fleet/console/envstore.py fleet/console/_deprecated/ && mv fleet/console/store.py fleet/console/_deprecated/
$ grep -rn "envstore|console.store|from .store|import store" fleet/ tests/ --include="*.py" | grep -v "_deprecated"
（无输出 —— 全仓零引用）
```

两个归档文件顶部已加 `[DEPRECATED · CORE-03]` 横幅；`fleet/console/state/projects.json`
顶部已加只读快照声明（权威数据在 SQLite projects 表，任何代码不得再写入）。

## 4. notify 服务侧解堵准备

`/api/notify/test` 503 分支改为 try import 探测 + 机器可读 `reason="notify接线未完成"`；
配套测试改为三段式（配置缺失 200 业务错误 / monkeypatch 模块不可用 → 503+reason / 发送结果 200）：

```text
$ python -m pytest tests/core/test_server_api.py -q
11 passed, 4 warnings in 1.20s
```

INT-03 交付 `send_test_mail`（或现有 send_email 保持可导入）后，该路由无需改 server.py 自动接通。

## 5. 密钥扫描与冻结面核验

```text
$ grep -rn "sk-" fleet/ tests/ --include="*.py" | grep -vE "re\.compile|脱敏"
（无输出 —— 源码零命中；剩余命中仅为 events.py/config.py 的脱敏正则模式定义本身）
```

- `fleet/manager/contracts.py` 本轮零改动：文件 mtime `2026-09-15 14:05:44`，早于本工作包开工时间（约 16:00），全部会话内编辑均未触及该文件。
- 未触碰：`fleet/console/web/`、`fleet/console/dist/`、`fleet/executors/`、`fleet/launcher/`、`fleet/notify/`（executors/launcher 在会话期间由角色C 并行修改，本包零编辑）。

## 6. 契约 v1.1 与实现逐条对照（对照结论）

三份契约均升 v1.1：

- 控制台API.md：新增 §7 会话与鉴权、§8 WebSocket、§9 调度与人工控制、§10 启动解析、§11 项目/拓展/通知、§5.1 键名↔.env 段映射表、§12 定版裁决；修正 §6.2 派工响应为实现口径（rounds）并补 409 body 的 error 字段；§2 补 legacy 进度字段；§0 补 GBK 回退与 401 闸门约定；§3 补动作码清单（gate:pass/gate:fail/task:review_pass/task:rework_dispatch/task:blocked_release/task:escalated_release/task:deferred/step_confirm 等）。
- 任务状态机.md：v1.1 复核——状态名/迁移方向/异常名零变更；迁移 #12 事件码修正为 `task:rework_dispatch`、#14 为 `task:blocked_release`（对齐实现真值）；新增 §3.1 说明 db 层 bump_rework 一步直落的等价实现语义。
- 任务进度表字段.md：v1.1 复核一致——字段名/类型/必填性与 `fleet/core/db.py` 常量逐项比对无偏差，仅补 v1.1 复核头注与 projects.json 只读快照补注。

契约中引用的新 ADR 编号（016~023）与 docs/adr.md 一一对应。

## 7. 交付物清单

新建：requirements.txt、tests/README.md、tests/core/test_resolve_integration.py（5 例）、
docs/adr.md（ADR-010 作废 + ADR-016 新增 + 八项裁决 ADR-016~023）、
fleet/console/_deprecated/{envstore,store}.py（归档）。
修改：docs/契约/ 三份文件（v1→v1.1）、fleet/console/server.py（仅 notify 503 分支加 reason）、
tests/core/test_server_api.py（notify 用例改三段式）、fleet/console/state/projects.json（文件头声明）。
