# 一、要点讨论（按文档脉络归组）

**1. 愿景层（d0/d1）——从“AI 员工”还原为“技术原语”**
d0 的最大价值是治理层五件套（唯一身份、权限最小化、append-only 审计、审批门、预算池）必须先于业务层落地。你的网页控制端 7 个菜单恰好可以一一映射：模型→模型池路由、角色→能力画像+权限白名单、执行体→Worker Runtime、拓展→Skills/MCP、消息→通知策略、总览/对话→事件流投影。拟人词（招聘/KPI/日报）在实现层全部翻译为：能力画像+基准测试、可观测指标、事件溯源日志。

**2. 架构层（d2/d3/d4）——“任务协议”而非“AI 互相聊天”**
两份长文结论一致且已互相印证：Orchestrator 必须独立于任何单一工具；Single Source of Truth 用文件/数据库承载（正好对应你的 `plan.json` + 任务进度表）；Contract First（先定 API/Schema 契约再并行）；三级 Review（机器 Gate→专业审查角色→Manager）；“测试通过≠项目正确”，验收必须证据驱动。d4 对“100% 全自动”的边界判断很清醒：高风险动作保留人工审批门，目标定 Level 3 而非幻想 Level 4。

**3. 选型层（d4/d5/d7）——ADR 已可冻结**
d7 是全项目最关键的收敛文档：自研薄 Control Plane + 可插拔 Worker Runtime；Machine Gate 权威高于 Manager（LLM 不能把 `exit_code=1` 解释成 PASS）；SQLite 存状态、JSONL 存事件、文件系统存证据；worktree + 资源 Lease；ADR-001~012 可直接沿用。你的设计与之完全兼容，且额外贡献了两个好设计：**模型池优先级+降级链**（对应 d7 缺失的 Provider 路由）和**实时网页控制端**（对应 d7 里 Streamlit MVP 的升级版）。

**4. 通用化层（d8/d9）——Kernel 不写死 Coding**
d8 的“通用内核 + Domain Pack”、d9 的“组织智能层与执行控制层分离（ADR-015）”建议只做**架构预留**不做提前实现：目录上给 `domains/` 留位、Kernel 只认 Task/Gate/Evidence 概念，但 MVP 只交付 Coding Domain。GSD/三省六部可以未来作为 Manager 的组织智能层接入，但不能替代 Machine Gate 当事实裁判。

**5. 执行层（核心.md、核心2.md、提示词启动.md、docs/6 份）——你已经有一套可跑的纪律**
- 重试口径已定：429/超时 = 10 秒 × 10 次 → 换下一候选；401/配额耗尽/`model_not_found` = 硬失败直接切，不空耗。
- 启动器红线已定：只启动/传话/监督，禁写业务代码、禁 commit/push、禁改 state/audit、派工只经 Manager。
- 任务状态机已定：DRAFT→ASSIGNED→DOING→SUBMITTED→REVIEWING→DONE/PARTIAL/REWORK/BLOCKED，REWORK>3 次→ESCALATED。
- 验收契约已定：六节报告 + verify_cmd 机器门 + 证据链表格；管理员用“执行就绪总表”驱动输出，非立即执行的角色不出提示词块。
- ⚠️ **安全提醒**：`核心.md` 中历史明文 Key/邮箱授权码已视为泄露（文档自身也已标注），请在各平台后台轮换；新体系里 Key 只允许出现在 `.env`/secrets，任何代码、日志、报告、提示词中一律用 `${VAR}` 占位。

**6. 你的设计与文档收敛结论的两处差异（建议采纳文档口径）**
- 你的数据库任务进度表字段 `审查状态(1~4)` 与 docs 的状态机是两套粒度：建议数据库表存状态机全量枚举（DRAFT/ASSIGNED/DOING/SUBMITTED/REVIEWING/DONE/PARTIAL/REWORK/BLOCKED/ESCALATED），`任务类型(分配/执行/审查)` 作为事件类别字段，两者正交。
- 你要求“实时读取无缓存”的 `.env`：可行，但建议规定**只有控制台写、引擎轮询读**（如 1 秒间隔 mtime 检查），避免角色执行中读到半写状态。

---

# 二、完整开发计划（多层级 · 原子化 · 小白按序执行）

> 总原则：每个方括号 [ ] 是一个可独立勾选的原子步骤，做完一项勾一项；每阶段末尾有“过关检查”，不过关不进入下一阶段。

## 阶段 0 · 准备与契约（半天）
- [ ] 0.1 安装环境：Python 3.11+、Node 20+、Git；终端分别执行 `python --version`、`node -v`、`git --version`，三条都有版本号即通过
- [ ] 0.2 轮换所有历史泄露的 Key（见安全提醒），新 Key 只登记进 `secrets/KEY_INVENTORY.md` 对应关系表
- [ ] 0.3 编写 `.env.example`（模板，禁止写真实值）：基础信息 / 模型池（name、level、base_url、model_id、api_key=${VAR}、http_proxy、https_proxy）/ 角色及绑定模型链 / 执行体启动命令 / 邮箱 SMTP 参数（全部 ${VAR}）/ 提醒开关 4 项 / 请求超时与重试次数
- [ ] 0.4 冻结三大契约文件（先写文档再写代码）：
  - [ ] `docs/契约/任务状态机.md`：DRAFT→ASSIGNED→DOING→SUBMITTED→REVIEWING→DONE/PARTIAL/REWORK/BLOCKED，REWORK×3→ESCALATED
  - [ ] `docs/契约/任务进度表字段.md`：任务id、角色、下发角色、回执角色、平台、模型、任务类型(1分配/2执行/3审查)、token、耗时、详情、备注、执行状态、审查状态、创建/更新时间
  - [ ] `docs/契约/控制台API.md`：/api/health、/api/plan、/api/events、/api/launch-event、/api/config/* 的请求响应 JSON 形状
- [ ] 0.5 过关检查：三个契约文件互相引用的字段名完全一致（人工对照一遍）

## 阶段 1 · 地基：配置中心 + 数据库 + 事件流（1~2 天）
- [ ] 1.1 建项目骨架（按下方目录结构逐个 mkdir）
- [ ] 1.2 配置中心模块：首次运行从 `.env.example` 复制生成 `.env`；提供 `load()` 每次实时读盘（mtime 变化才重新解析）；提供 `save()` 原子写（先写临时文件再改名）
- [ ] 1.3 数据库模块：SQLite 建任务进度表（字段按 0.4 契约）；每条任务变更同时追加写 `data/events.jsonl`（append-only，一行一个 JSON 事件）
- [ ] 1.4 plan.json 模块：三级大纲结构 {阶段→任务→子任务}，每个节点带任务id；Manager 每次分配后实时重写
- [ ] 1.5 单元测试：配置读写、状态机非法迁移拒绝（如 DRAFT→DONE 必须报错）、事件追加不可变
- [ ] 1.6 过关检查：`pytest`（或等价命令）全绿；手工把一条任务从 DRAFT 推到 ASSIGNED，能在 tasks 表和 events.jsonl 里同时看到

## 阶段 2 · 核心引擎：模型池 + 执行体适配 + Manager（2~3 天）
- [ ] 2.1 模型池模块：加载 .env 模型池；`call(model, prompt)` 统一入口；按 level 优先级排序
- [ ] 2.2 重试策略引擎：429/超时 → 10 秒 × 10 次 → 切下一候选；401/配额耗尽/model_not_found → 直接切；每次切换写 launch:model_switch 事件（含 from→to、attempts）
- [ ] 2.3 执行体适配器（统一接口 `run(prompt, workdir, model, timeout)`）：
  - [ ] ClaudeCodeAdapter（`claude -p --output-format json`）
  - [ ] CodexAdapter（`codex exec --json`）
  - [ ] OpenCodeAdapter（`opencode run`）
  - [ ] Hermes子agentAdapter
  - 每个适配器先单独跑一次 `echo hi` 级冒烟测试
- [ ] 2.4 Manager 派工模块：接收 TaskPack → 选角色 → 经适配器下发 → 收结构化回执（六节报告）；Manager 无权改机器事实
- [ ] 2.5 机器验收 Gate：verify_cmd 执行（grep/测试/构建命令）、禁改文件扫描、证据文件存在性检查；PASS 才允许状态进入 DONE
- [ ] 2.6 过关检查：手工构造一个最小任务（“在指定文件写入一行字”），走完 派工→执行→机器门→DONE 全链路，events.jsonl 有完整事件序列

## 阶段 3 · 网页控制端（2~3 天，可与阶段 2 尾部并行）
- [ ] 3.1 控制台后端 API（FastAPI/Flask）：health / plan / events / config 读写 / launch-event；非法事件 400 拒绝且不污染事件流
- [ ] 3.2 控制台前端骨架：深色科技风格；1920 自适应；无底部栏
- [ ] 3.3 锁屏页：输入项目名解锁；会话默认 1 小时有效期（读 .env）
- [ ] 3.4 顶部栏：右上角锁定键 + 设置按钮（展开设置表单：请求超时、重试次数等，写回 .env）
- [ ] 3.5 左侧菜单（可折叠、可拖拽调宽）：总览/对话/模型/角色/执行体/拓展/消息 七个页面，默认显示一级大纲，点击展开二三级
- [ ] 3.6 右侧进度条（默认缩起、可拖拽）：空心圆=未完成红、完成绿、当前青碧色加大圈内显百分比；从顶部栏到底
- [ ] 3.7 总览页：实时信息面板（滚轮查看）；当前步骤置顶，已完成步骤折叠到顶部可展开；固定 10 步准备清单（接收指令→…→一切就绪）；右上角“每步确认/自动执行”切换；每步确认模式底部出输入框
- [ ] 3.8 对话页：与 Manager 实时交流，修正任务信息后回写 plan.json
- [ ] 3.9 模型/角色/执行体/拓展/消息页：对 .env 对应段落的表单化读写
- [ ] 3.10 过关检查：浏览器开两个窗口，一个触发事件、另一个 1 秒内看到进度变化

## 阶段 4 · 启动链路（1 天）
- [ ] 4.1 CLI 引导启动：`fleet start` 交互式问项目名/路径/端口 → 写 project.json → 拉起控制台(5000) → 打开浏览器
- [ ] 4.2 Hermes 直启：按 docs 模板 `[fleet-launch]` 块解析 mode(run/intake/audit/discuss) → 走同一启动流程
- [ ] 4.3 启动器红线固化：禁写业务代码、禁 commit/push、禁改 state/audit、派工只经 Manager；资源被占时只向用户提 Y/N 问题
- [ ] 4.4 过关检查：两种方式各启动一次，控制台 health 全 true

## 阶段 5 · 消息提醒 + 设置表单（半天）
- [ ] 5.1 邮件模块：SMTP_SSL 发送，收发件人/授权码全部从 .env 读
- [ ] 5.2 触发策略勾选：任务开始(默认关)、任务结束(默认开)、Manager 额度不足(默认开)、执行角色额度不足(默认开)、+扩展：任务 ESCALATED、每日汇总
- [ ] 5.3 过关检查：勾选“任务结束”跑通一个任务，邮箱收到通知

## 阶段 6 · 端到端验收（1 天）
- [ ] 6.1 T0~T10 验收命令清单照 docs 执行并留痕
- [ ] 6.2 终局完成度表：| 角色 | 平台 | 模型 | 任务 | 评分 |，禁止自评
- [ ] 6.3 断点恢复演练：中途杀进程 → 重启 → 从 SQLite 状态续跑
- [ ] 6.4 全绿后打 tag

---

# 三、高效项目目录结构

```text
AideanFleet/
├── .env.example                  # 模板：基础信息/模型池/角色/执行体/邮箱/开关。禁止写真实值
├── .env                          # 首次运行自动从模板复制；控制台可写，引擎实时读
├── AGENTS.md                     # 全局系统提示词（你已写好的那份）
├── secrets/
│   └── KEY_INVENTORY.md          # Key 变量名↔平台对应关系（不存真值）
├── docs/
│   ├── 契约/                     # 阶段0冻结：状态机/表字段/控制台API
│   └── 初始设计/ docs/           # 现有资料原位保留
├── fleet/
│   ├── core/                     # ① 配置中心 config.py ② 数据库 db.py(SQLite) 
│   │                             # ③ 事件总线 events.py(jsonl append-only)
│   │                             # ④ 状态机 state_machine.py ⑤ plan.py(plan.json)
│   ├── models/                   # 模型池 pool.py / 路由 router.py / 重试策略 retry.py
│   ├── executors/                # 执行体适配器 base.py + claudecode.py + codex.py
│   │                             #   + opencode.py + hermes.py
│   ├── roles/                    # 角色库：role.py(能力画像+权限白名单+模型绑定链)
│   ├── manager/                  # Manager：派工 dispatcher.py / 审查 reviewer.py
│   ├── gates/                    # 机器验收：verify_cmd / 禁改文件扫描 / 证据检查
│   ├── notify/                   # 邮件提醒 smtp.py + 触发策略 triggers.py
│   ├── launcher/                 # cli_start.py(引导启动) + hermes_entry.py(直启)
│   │                             #   + 启动器红线 redlines.py
│   └── console/                  # 网页控制端
│       ├── server.py             #   后端 API(5000)：health/plan/events/config/launch-event
│       ├── static/               #   前端：锁屏/顶栏/左菜单/右进度条/七页面
│       └── state/                #   projects.json / tasks.json / roster.json / audit.log
├── data/                         # 运行时数据：fleet.db + events.jsonl + plan.json
├── prompts/                      # 角色提示词模板 + 六节报告模板
├── skills/                       # 执行体可用的 SKILL.md
├── domains/                      # 预留：coding/ (MVP)  media/ research/ (未来)
├── tests/                        # 单元测试 + T0~T10 验收脚本
└── reports/                      # 完成报告与终局完成度表落盘处
```

依赖方向铁律：`domains → core`；`core` 永远不 import 任何执行体/控制台；Key 只进 `.env`。

---

# 四、本轮开发任务总览

```markdown
# 本轮开发任务总览

## 当前阶段

阶段：阶段 0（准备与契约）+ 阶段 1~3 的首轮并行开发启动
目标：冻结三大契约后，三条线并行完成控制面核心、网页控制端、执行体集成与启动链路的首个可运行闭环

## 当前项目状态

- 已完成：22 份设计文档全部阅读收敛；技术基线（自研薄 Control Plane + 可插拔执行体 + Machine Gate）冻结；重试口径（10s×10→切模型）、任务状态机、启动器红线、六节报告契约均有文档依据
- 未完成：全部代码（仓库当前只有文档）；三大契约文件未落盘
- 当前风险：历史明文 Key 已泄露需轮换；三线并行若契约先行不彻底会造成接口漂移
- 当前阻塞：无

## 本轮调度

| 角色 | 状态 | 工作包 | 原因 | 依赖 |
|---|---|---|---|---|
| 角色A · 控制面核心（后端） | EXECUTE | FLEET-BE-01 地基与核心引擎 | 一切模块的地基，最关键路径 | 无（契约由其工作包内先行产出） |
| 角色B · 网页控制端（前端） | EXECUTE | FLEET-FE-01 控制台全量 UI 与实时同步 | UI 契约已由用户设计完整给定，可立即并行 | 与角色A通过控制台API契约对齐（契约见其工作包） |
| 角色C · 集成与启动 | EXECUTE | FLEET-INT-01 执行体适配+启动链路+消息 | 适配器只依赖模型池接口契约，可并行开发 | 与角色A通过 BaseAdapter 接口契约对齐 |

## 并行关系

- A/B/C 三者文件边界完全不相交：A 只写 fleet/core|models|manager|gates，B 只写 fleet/console/static 与 server.py，C 只写 fleet/executors|launcher|notify
- 三个接口契约（任务状态机、控制台API、BaseAdapter）在各自工作包第 1 步产出后立即互相抄送对齐，之后不再变更字段名
- 任一角色完成后即时审查、即时释放后继任务，不等整轮

## 全局注意事项

- Key 只进 .env，任何输出禁止明文
- Machine Gate 权威高于一切角色自述
- 禁止为了并行而制造碎片任务；等待依赖时先找其他 READY 工作
```

---

# 五、3 角色并发规划

```markdown
# 角色A · 控制面核心（后端）· 工作包 FLEET-BE-01

## 1. 角色身份

你是 AideanFleet 自动化执行器的控制面核心工程师。你负责整个系统的"地基与发动机"：
配置中心、数据库、事件流、模型池调度、Manager 派工、机器验收 Gate。
你不写前端页面，不写执行体适配器，不写启动器。

## 2. 本轮执行状态

EXECUTE

## 3. 当前工作包

FLEET-BE-01：完成 AideanFleet 的配置中心 + 任务数据库 + 事件流 + 模型池调度引擎 + Manager 派工与机器验收闭环。

## 4. 工作目标

完成后系统具备：读 .env 驱动全部行为、任务状态机可持久化且可断点恢复、
模型按优先级自动降级、一个任务能从派工走到机器验收 PASS 的完整后端能力，
并通过控制台 API 对外暴露。

## 5. 开始工作前必须检查

1. `python --version` ≥ 3.11；`git status` 确认工作区干净。
2. 阅读三个输入：本工作包、`AGENTS.md`（全局提示词）、`初始设计/核心2.md`（用户设计）。
3. 确认 `fleet/core/`、`fleet/models/`、`fleet/manager/`、`fleet/gates/` 目录当前为空，你从零创建。
4. 确认 `.env.example` 尚不存在——由你创建（阶段0步骤 0.3）。

## 6. 当前阶段审查结果

无（首轮）。项目尚无代码。

## 7. 当前发现的问题

1. 历史文档中存在已泄露的明文 Key 与邮箱授权码（初始设计/核心.md）——你绝不可复用，
   全部改为 `${VAR}` 占位，并在交付报告中提醒用户轮换。
2. 用户设计的"审查状态(1~4)"与 docs 的状态机粒度不一致——按本工作包第 9.2 条的融合口径实现。

## 8. 问题根因

设计文档分批演进，粒度未统一；密码管理早期未规范。

## 9. 本轮核心工作

### 9.1 契约先行（第 1 步，产出后立即定稿，字段名此后不变）
1) 写 `docs/契约/任务状态机.md`：
   DRAFT→ASSIGNED→DOING→SUBMITTED→REVIEWING→DONE/PARTIAL/REWORK/BLOCKED；REWORK 次数>3 → ESCALATED。
2) 写 `docs/契约/任务进度表字段.md`：
   任务id、角色、下发角色、回执角色、平台、模型、任务类型(1分配/2执行/3审查)、token、耗时、
   详情、备注、执行状态(状态机枚举)、审查状态(PASS/PARTIAL/REWORK/BLOCKED)、创建时间、更新时间。
3) 写 `docs/契约/控制台API.md`：
   GET /api/health；GET /api/plan?project=；GET /api/events?project=&since=；
   POST /api/launch-event（非法缺字段→400 且不写事件流）；GET/POST /api/config/<section>。
   每个接口给出请求/响应 JSON 完整示例。

### 9.2 配置中心（fleet/core/config.py）
1) 首次运行检测 `.env` 不存在 → 从 `.env.example` 原样复制。
2) `.env.example` 分七段：基础信息 / 模型池 / 角色与绑定模型链 / 执行体启动命令 /
   邮箱 SMTP（收发件人、host、port、授权码全用 ${VAR}）/ 提醒开关 4 项（开始=关、结束=开、
   Manager额度不足=开、执行角色额度不足=开）/ 请求超时与重试次数。
3) `load(section)`：每次调用实时读盘，先用文件 mtime 判断是否重新解析（无缓存语义）。
4) `save(section, data)`：原子写（临时文件 + os.replace）。
5) 约束：只有控制台进程允许写；引擎侧只读。

### 9.3 数据库与事件流（fleet/core/db.py、events.py）
1) SQLite 建 `tasks` 表，字段按 9.1-2 契约；建 `projects` 表（项目名、路径、端口）。
2) 状态机类（state_machine.py）：定义合法迁移表；任何非法迁移（如 DRAFT→DONE）
   抛 InvalidTransition 且不落库。
3) 事件总线：tasks/projects 每次变更同步追加一行 JSON 到 `data/events.jsonl`
   （字段：seq、timestamp、actor、action、taskId、summary、url）；seq 单调递增；
   任何代码不得修改或删除历史行。
4) plan.json（core/plan.py）：结构 {阶段:[{任务:[{子任务, task_id}]}]}；
   提供 update_stage/update_task 接口，Manager 每次分配后调用重写（原子写）。

### 9.4 模型池与重试（fleet/models/）
1) pool.py：解析 .env 模型池段为列表，按 level 升序（数字小=优先）。
2) retry.py 策略（硬编码为本项目标准口径）：
   - 429 / 超时：等 10 秒重试，最多 10 次；10 次仍败 → 切换下一候选模型；
   - 401 / 402 / 403 / quota_exhausted / model_not_found：硬失败，立即切换，不空耗 10 次；
   - 全部候选耗尽 → 返回 BLOCKED，附每家失败原因。
3) router.py：`call(role, prompt)` 按角色绑定的模型链（bind_model_name 顺序）依次尝试；
   每次切换发事件 launch:model_switch（含 from、to、attempts）。

### 9.5 Manager 与机器验收（fleet/manager/、fleet/gates/）
1) dispatcher.py：输入 TaskPack（id、title、detail、verify_cmd、assignee、reviewer、
   workspace、allowed_files、forbidden_files）→ 状态置 ASSIGNED → 调用执行体适配器接口
   （本工作包只定义 `BaseAdapter.run(prompt, workdir, model, timeout) -> AgentResult` 抽象基类，
   具体适配器由角色C实现）→ 状态 DOING → 收六节报告 → SUBMITTED。
2) reviewer.py：把回执转交审查（审查角色同走适配器），只接受 PASS/PARTIAL/REWORK/BLOCKED 四值。
3) gates/verify.py 机器门（在人工/LLM 审查之前强制执行）：
   - verify_cmd 原样执行，记录 exit_code 与原始输出（截尾 2000 字）；
   - 禁改文件扫描：比对 allowed/forbidden 清单；
   - 证据文件存在性检查；
   - 任一失败 → 直接 REWORK，Manager/LLM 无权改判。
4) 六节报告契约（prompts/报告模板.md）：改动清单 / 命令记录 / 证据链 / 四要素 / 未完成事项 / 模型自述。

### 9.6 控制台 API 骨架（fleet/console/server.py 仅留路由注册与 health，页面由角色B负责）
health 返回 {"version":"0.1.0","db":true,"events":true,"config":true}。

## 10. 执行要求

1. Python 3.11+，标准库 + pyyaml + sqlite3（内置），不引入重型框架。
2. 每个模块配 pytest 单测；状态机非法迁移、配置原子写、事件不可变必须有测试。
3. 所有事件/日志/报告中出现 Key 的位置一律 `${VAR}`；提交前跑一次
   `grep -rn "sk-" fleet/ tests/`（应对你自己的代码零命中，模板占位除外）。
4. 小白友好：每个模块文件头部写 5 行以内"这是什么、怎么用"注释。

## 11. 与其他角色的关系

- 角色B：消费你 9.1-3 的控制台API契约；契约第 1 步产出后立即发给调度方同步给B，此后字段名冻结。
- 角色C：消费你 9.5-1 的 BaseAdapter 抽象与 TaskPack 结构；同样契约先行、字段冻结。
- 你不改 fleet/executors/、fleet/launcher/、fleet/notify/、fleet/console/static/ 任何文件。

## 12. 依赖关系

无外部前置依赖。你是关键路径。

## 13. 不属于本工作包的内容

前端页面、具体执行体 CLI 封装、CLI 引导/Hermes 直启、邮件发送实现、git commit/push。

## 14. 测试与验证

1. `pytest tests/ -q` 全绿。
2. 手工链路：写一条最小任务（"在 data/smoke.txt 写入 hello"）→ 派工 → 用一个
   FakeAdapter（直接返回成功+证据）走完 DRAFT→DONE，events.jsonl 出现完整事件序列。
3. 断点恢复：走查中途 kill 进程 → 重启 → 从 SQLite 状态继续，不重复派工。
4. 模型降级：构造假 429 → 验证 10s×10 → 切换 → launch:model_switch 事件。

## 15. 验收标准

1. 三份契约文件存在且互相引用字段名一致。
2. `.env.example` 七段齐全、零真实密钥。
3. 状态机、事件流、模型降级、机器门各有测试且通过。
4. 手工链路与断点恢复两条演练各留一份命令+输出证据到 reports/BE-01-evidence.md。

## 16. Definition of Done

上述 15 全部满足 + 六节完成报告按模板提交 + 不修改任何其他角色边界内文件。

## 17. 完成后汇报要求

按全局提示词第 32 节格式输出 `# 工作包完成报告`（工作包 / 最终状态 / 调查结果 /
实际执行过程 / 设计决策 / 实际修改 / 测试 / 集成验证 / 证据 / 遗留问题 / 风险 /
对其他工作包的影响 / 下一步建议），整体置于一个 ```markdown 源码块内。
```

```markdown
# 角色B · 网页控制端（前端）· 工作包 FLEET-FE-01

## 1. 角色身份

你是 AideanFleet 网页控制端的全栈工程师（后端 API 路由 + 前端页面）。
你负责把用户设计中的"深色科技风控制台"完整实现：锁屏、顶栏、左菜单七页面、
右进度条、总览实时面板、设置表单。你不写控制面核心逻辑，不写执行体适配器。

## 2. 本轮执行状态

EXECUTE

## 3. 当前工作包

FLEET-FE-01：完成网页控制端 1.0——七个菜单页全部可用、与事件流实时同步、配置表单可读写 .env。

## 4. 工作目标

用户打开 http://127.0.0.1:5000 → 输入项目名解锁 → 在总览页实时看到 10 步准备清单与
任务进度 → 能在模型/角色/执行体/拓展/消息五页修改配置 → 对话页能给 Manager 发指令。

## 5. 开始工作前必须检查

1. `python --version`、`node -v` 可用；浏览器可打开 localhost。
2. 确认 fleet/console/ 目录为空，由你从零创建（server.py 的路由注册骨架可能与角色A
   并行产生冲突——约定：你只写 fleet/console/server.py 中"路由注册到 handler 函数"的部分，
   核心数据读写一律调用 fleet/core 模块；若角色A尚未交付该模块，先按契约 mock 数据开发）。
3. 通读用户设计（初始设计/核心2.md 网页控制端一节）逐条列成 UI 验收清单。

## 6. 当前阶段审查结果

无（首轮）。

## 7. 当前发现的问题

1. 设计要求"实时同步"，未指定机制——按本工作包 9.7 的轮询+增量游标方案实现（简单可靠，小白可维护）。
2. 设计含 1 小时锁屏有效期——从 .env 读取，缺失时默认 3600 秒。

## 8. 问题根因

设计文档给定了外观与交互，未给定实现机制。

## 9. 本轮核心工作

### 9.1 控制台后端（fleet/console/server.py）
1) 用 Flask/FastAPI 实现：
   - GET /api/health
   - GET /api/plan?project=<pid>（转发 fleet/core/plan.py）
   - GET /api/events?project=<pid>&since=<seq>（增量返回，字段与 events.jsonl 一致）
   - POST /api/launch-event（校验必填字段；缺字段→400 且不写事件流）
   - GET/POST /api/config/<section>（读/原子写 .env 对应段）
2) 会话：锁屏成功后签发内存 session（有效期读 .env）；其余 API 未带有效 session 一律 401。
3) 静态资源由同一服务托管，单进程即可运行。

### 9.2 前端骨架（fleet/console/static/）
1) 深色科技风：深底色、青碧强调色、等宽数字字体；无底部信息栏。
2) 布局三栏：左菜单（可折叠、边缘可拖拽调宽）/ 中间内容 / 右进度条（默认缩起、可拖拽展开）。
3) 顶部栏右上角：锁定键（点击回锁屏）+ 设置按钮（展开设置表单：请求超时、重试次数，
   提交写 /api/config/settings）。

### 9.3 锁屏页
1) 输入项目名 → POST 校验（项目存在于 projects 数据）→ 成功进入主界面并启动会话计时。

### 9.4 左侧菜单（一级大纲固定顺序：总览、对话、模型、角色、执行体、拓展、消息）
1) 每页默认只显示一级大纲，点击展开二三级（无则不显示）。
2) 七页内容：
   - 总览：见 9.5
   - 对话：底部输入框 + 消息流；发送 → POST 转给 Manager → 回执渲染；Manager 修正
     任务后前端轮询 /api/plan 自动刷新
   - 模型：按模型池段落渲染卡片表单（name/level/base_url/model_id/api_key 显示为
     ${VAR} 掩码/http_proxy/https_proxy），保存写 /api/config/models
   - 角色：role_name/system_prompt/bind_model_name 表单
   - 执行体：执行体列表 + 启动命令表单
   - 拓展：执行体可用 skills 和 mcp 的勾选清单
   - 消息：SMTP 参数表单 + 四个提醒开关勾选（开始=关/结束=开/Manager额度=开/
     执行角色额度=开）+ 自定义触发项
3) 所有 api_key 输入框一律掩码显示，永不明文回显。

### 9.5 总览页（实时信息面板）
1) 主体永远是"当前正在执行的步骤"；已执行步骤折叠到顶部，点击展开查看过程。
2) 支持鼠标滚轮上下查看。
3) 首次进入显示固定 10 步准备清单（接收指令 1/10 → … → 一切就绪 10/10），
   内容与顺序按用户设计原文。
4) 右上角"每步确认 / 自动执行"切换按钮；每步确认模式下底部出现输入框，
   用户可填意见或点确认；选择结果写入事件流。

### 9.6 右侧进度条
1) 从顶部栏到底；缩起时呈一列空心圆。
2) 颜色规则：完成=绿、未完成=红、当前位置=青碧色且圆更大、圆心显示百分比数字。
3) 数据源：/api/plan 的三级大纲聚合出百分比。

### 9.7 实时同步机制
1) 前端每 1 秒调用 /api/events?since=<本地最大seq> 增量拉取；
   收到新事件即更新总览面板与进度条。
2) 断线自动重连（重试间隔 3 秒），重连后从上次 seq 续拉，不丢事件。

## 10. 执行要求

1. 前端零构建链：原生 HTML/CSS/JS 或单文件引入的轻量库，保证小白双击即可理解目录结构。
2. 每个 API 调用失败都要有中文错误提示，不许静默失败。
3. 页面文案全部中文。
4. 你不改 fleet/core/、fleet/models/、fleet/executors/、fleet/launcher/、fleet/notify/。

## 11. 与其他角色的关系

- 角色A：你消费其控制台API契约（/api/health /plan /events /launch-event /config）；
  契约到手前用 mock JSON 开发，字段名与契约草稿一致。
- 角色C：消息页的"发送测试邮件"按钮调 POST /api/notify/test（路由归你，实现转发给
  角色C 的 notify 模块；其未交付前按钮置灰并提示"依赖角色C"）。

## 12. 依赖关系

- 与角色A契约对齐后即可全速开发；无串行等待点（mock 先行）。

## 13. 不属于本工作包的内容

状态机/数据库实现、模型调度、执行体封装、邮件发送实现。

## 14. 测试与验证

1. 双窗口测试：窗口A用 curl POST /api/launch-event，窗口B控制台 1 秒内显示新事件。
2. 非法事件：缺字段 POST → 400，且事件流 seq 不增长。
3. 锁屏：1 小时有效期手动改为 10 秒 → 到期自动回锁屏。
4. 七页面逐页：读取→修改→保存→刷新页面→值保持。
5. 掩码检查：页面源码与网络响应中无明文 Key。

## 15. 验收标准

1. 用户设计"网页控制端"一节逐条对照全部实现（含颜色、缩起、拖拽宽度、10 步清单原文）。
2. 实时同步 1 秒内可见；断线重连不丢事件。
3. 无英文残留、无明文密钥、所有错误有中文提示。
4. 证据截图（或 DOM 文本导出）落 reports/FE-01-evidence.md。

## 16. Definition of Done

上述 15 全部满足 + 六节完成报告 + 未改其他角色边界内文件。

## 17. 完成后汇报要求

按全局提示词第 32 节格式输出完整 `# 工作包完成报告`，整体置于一个 ```markdown 源码块内。
```

```markdown
# 角色C · 集成与启动（执行体适配+启动链路+消息）· 工作包 FLEET-INT-01

## 1. 角色身份

你是 AideanFleet 的集成工程师。你负责系统与外部世界的全部接缝：
四个执行体（ClaudeCode/Codex/OpenCode/Hermes子agent）的 CLI 适配器、
CLI 引导启动与 Hermes 直启两条入口、邮件消息提醒。你不写控制面核心与前端页面。

## 2. 本轮执行状态

EXECUTE

## 3. 当前工作包

FLEET-INT-01：完成执行体适配器四件套 + 启动链路（CLI/Hermes）+ 启动器红线 + 邮件提醒模块。

## 4. 工作目标

完成后：四类执行体可用统一接口被派工；`fleet start` 引导启动全流程可走通；
Hermes 发 [fleet-launch] 块可直启；任务结束时控制台能按开关发邮件通知。

## 5. 开始工作前必须检查

1. 本机实际探测（逐条执行并记录输出）：
   `claude --version`、`codex --version`、`opencode --version`、`hermes --version`、
   `python --version`。
   某个执行体未安装 → 该适配器标记 unavailable 并写入报告，不得伪造测试结果。
2. 确认 fleet/executors/、fleet/launcher/、fleet/notify/ 为空，由你从零创建。
3. 等待/索取角色A的两份契约：BaseAdapter 抽象签名、TaskPack 字段。拿到前先写
   邮件模块与启动器骨架（无依赖部分先行，不许空等）。

## 6. 当前阶段审查结果

无（首轮）。

## 7. 当前发现的问题

1. 各 CLI 参数格式不同且随版本变化——适配器必须带 capability discovery：
   启动时先跑 `<cli> --help` 探测，不支持的能力（如流式/会话恢复）在
   Capabilities 数据类中如实标注，不许假设四家能力一致。
2. 设计要求"默认启动命令=.env 初始化时从 .env.example 复制"——即启动命令可配置，
   缺省值来自 .env.example 的执行体段。

## 8. 问题根因

外部 CLI 是第三方演进物，只能适配不能假设。

## 9. 本轮核心工作

### 9.1 执行体适配器（fleet/executors/）
1) base.py（若角色A已交付则直接复用其抽象）：`run(prompt, workdir, model, timeout) -> AgentResult`；
   AgentResult 含 ok/output/error_code(429/400/TIMEOUT/TOOL_FAIL)/error_msg(截尾2000字)/usage。
2) 四个适配器统一行为：
   - 子进程调用，cwd=workdir，超时杀进程树；
   - stderr/stdout 中含 "429" → error_code=429；"400" → 400；超时 → TIMEOUT；
   - 每次调用把完整原始输出写 evidence 文件（data/evidence/<task_id>/attempt-N.log），
     不修改、不摘要。
3) hermes.py：实现两类调用——`hermes -p manager gateway run`（拉起 Manager 网关）
   与子 agent 消息转发（原文转发，不改写证据）。

### 9.2 CLI 引导启动（fleet/launcher/cli_start.py）
1) `python -m fleet.launcher.cli_start` 交互式依次问：项目名、项目路径、UI 端口
   （默认 3333）——每步有默认值，直接回车即采用。
2) 流程（对齐 docs/启动Hermes派工.txt）：
   ① 探测 python/hermes 版本与 5000/9900 端口占用；
   ② 端口被占 → 只提示"是否清理？Y/N"，等用户答复，不擅自杀进程；
   ③ 起控制台(5000)；④ 起 Manager 网关(9900)；⑤ 探活
   GET /api/health 与 GET 9900/.well-known/agent-card.json(name=Hermes-Manager)；
   ⑥ projects.json 无该项目则创建 pid（workspace 必须在 ALLOWED_ROOTS 内，否则停止）；
   ⑦ 打开浏览器指向控制台。
3) 全程打印每步结果，失败即停并说明原因。

### 9.3 Hermes 直启（fleet/launcher/hermes_entry.py）
1) 解析 [fleet-launch] 块字段：project/mode(run|intake|audit|discuss)/tasks/
   requirements/port/notes/model。
2) mode 映射：run=按 plan 全量执行；intake=先派产品角色产 PRD 落盘再转 plan；
   audit=只读体检产出 defects 清单；discuss=多执行体圆桌（≤3 轮、read-only）。
3) 解析成功 → 走 9.2 同一启动流程；解析失败 → 打印中文错误与期望格式示例。

### 9.4 启动器红线（fleet/launcher/redlines.py + 提示词模板）
1) 固化五条红线并注入启动器提示词模板（prompts/launcher.template.md）：
   禁写业务代码；禁 commit/push；禁删任务/改 state/audit.log；派工只经 Manager；
   危险命令（DENY_RE 正则清单：rm -rf、format、注册表写入等）拦截。
2) 资源占用等少数需用户确认的场景，只允许 Y/N 问答。

### 9.5 邮件提醒（fleet/notify/）
1) smtp.py：SMTP_SSL(465) 发送；host/port/收发件人/授权码全部从 .env 读取；
   授权码用 ${VAR}，日志与报告零明文。
2) triggers.py：订阅事件流，按开关触发——任务开始(默认关)/任务结束(默认开)/
   Manager 额度不足(默认开)/执行角色额度不足(默认开)；另扩展两项：
   任务 ESCALATED(默认开)/每日 20:00 汇总(默认关)。
3) 每次发送结果写事件 notify:sent / notify:failed，失败不重试超过 3 次且不阻塞主流程。

## 10. 执行要求

1. 只用标准库 subprocess/smtplib/email + pyyaml；适配器失败绝不重试超过策略上限
   （重试决策归角色A的重试引擎，适配器只如实上报 error_code）。
2. 每个适配器配一个"冒烟测试"：注入 prompt="回复 OK" 验证链路，真实 CLI 未安装则 skip 并注明。
3. Windows 环境：所有子进程调用带 creationflags 兼容处理；路径用 pathlib。
4. 你不改 fleet/core/、fleet/models/、fleet/console/ 任何文件。

## 11. 与其他角色的关系

- 角色A：你实现其 BaseAdapter 抽象；TaskPack/AgentResult 字段以其契约为准，
  发现契约缺陷记录上报，不擅自改字段。
- 角色B：其"发送测试邮件"按钮依赖你暴露的内部函数（经角色A的路由转发）；
  你交付前该按钮由B置灰。

## 12. 依赖关系

- BaseAdapter 契约（角色A，工作包第 1 步即产出）——等待期间先完成 9.2/9.3/9.4/9.5。
- 四个 CLI 的本机可用性（第 5 节探测）——缺哪个标哪个，不阻塞其他适配器。

## 13. 不属于本工作包的内容

数据库/状态机/模型调度实现、控制台页面、任务派工逻辑本身。

## 14. 测试与验证

1. 启动演练×2：CLI 引导启动与 Hermes 直启各走一遍，health 全 true 截图/输出留证。
2. 适配器冒烟：已安装的执行体逐个跑通"回复 OK"；未安装的输出 unavailable 证据。
3. 邮件：用测试收件箱触发"任务结束"通知，收到即过；错误授权码场景验证 notify:failed 事件。
4. 红线：模拟危险命令 → DENY_RE 拦截并留审计事件。
5. 证据落 reports/INT-01-evidence.md。

## 15. 验收标准

1. 四适配器统一接口 + capability discovery + 原始输出留痕。
2. 两条启动链路可复现走通；红线拦截有证据。
3. 五+二提醒触发项与默认开关与设计一致；零明文密钥。
4. 未改其他角色边界内文件。

## 16. Definition of Done

上述 15 全部满足 + 六节完成报告 + 对不可用外部依赖（未装 CLI、SMTP 授权码未配）
逐项如实列出而非隐藏。

## 17. 完成后汇报要求

按全局提示词第 32 节格式输出完整 `# 工作包完成报告`，整体置于一个 ```markdown 源码块内。
```

---

**本轮自检**：总览已置于源码块 ✓｜仅 3 个 EXECUTE 角色且各自独立源码块 ✓｜工作包均为阶段级工程能力而非碎片任务 ✓｜边界互斥（A=core/models/manager/gates，B=console，C=executors/launcher/notify）✓｜契约先行、依赖不阻塞（mock 先行/无依赖部分先行）✓｜小白可按步骤序号逐项执行 ✓。

