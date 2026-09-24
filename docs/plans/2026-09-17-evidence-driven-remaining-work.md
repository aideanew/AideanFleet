# AideanFleet 证据驱动剩余任务实施方案

日期：2026-09-17。目标：让用户从需求输入，经可控执行、可信验收和人工纠偏，获得可追溯交付，而不是只有可展示的任务状态。

架构：保留 Python/FastAPI、SQLite、JSONL、Vue3/Vite/Pinia 和既有执行体契约；先收敛执行所有权与数据一致性，再补需求决策和治理闭环，最后做有界并发与性能优化。不引入消息中间件、ORM或微服务作为本轮前提。

## 0. 基线与证据边界

- 基础提交：`0c94fc73953623bf5e2f28920740d1fba25f28dc`，分支 main；结论针对已读工作区源代码，不只针对 HEAD。
- 本轮重读了四份参考材料的核心论述、ADR、状态/字段契约、API相关条款、部署/验收文档和关键生产路径。部分长文工具输出被截断；**不声称全部历史文档逐字读完，也不声称全仓无遗漏**。
- 历史验收数、CLI版本和其他方案文档的实跑数字仅作历史资料，不替代本轮证据。
- 本轮初始选择测试：9 passed / 1.73s；扩大后的既有选择测试：76 passed / 16 warnings / 9.59s。
- 新增离线集成测试第一次失败：五任务 DONE 后项目用量为0，预期10。字段映射修复后，最终选择回归：**77 passed / 16 warnings / 12.79s**。不是全量测试基线。
- 前端 `vue-tsc --noEmit`：首次失败，`ChatPage.vue(98,14) TS2339`；最终复核发现其他并行工作已在auth store导出apply，重新检查当前通过。该改动不是本轮完成；项目切换、TTL和刷新行为仍待验收。Vite build不是类型检查的替代。
- 未执行真实模型调用、真实执行体任务、SMTP发送、浏览器全量E2E、性能压测及故障攻击复现。
- 本轮实际改动仅两文件：`E:\Code\AideanFleet\fleet\governance\usage.py`（兼容真实事件字段）与 `E:\Code\AideanFleet\tests\core\test_intake_to_done_integration.py`（新增隔离测试）。本方案为新增文档。不覆盖工作区其他人的截图/方案改动，不提交、不发布。

## 1. 参考材料逐项取舍

### 1.1 原始用户需求
`E:\Code\AideanFleet\docs\参考\base.md:25-61,63-87,106-112`：三级规划、双入口、七页面、对话中修正任务、模型/角色/执行体分层、工具配置、提醒。它回答“用户需要什么”，优先于实现者自评。项目名锁屏是本机便利交互，不能等同强身份鉴权。该文件97、103行仍有疑似明文邮件授权信息，不复述值，应按历史泄露处理并由凭证所有者确认轮换。

### 1.2 chatpgt参考
`E:\Code\AideanFleet\docs\参考\chatpgt.md:5-39,89-115,1851-1983,1987-2182`：采纳DAG/调度为核心、入口共享应用服务、Fake先行、自动执行有边界。不能把“有DAG文件”视为生产并发正确；也不能把先做核心理解为废弃现成前端。任务包保持完整工程价值，包内才拆最小动作。

### 1.3 claude参考
`E:\Code\AideanFleet\docs\参考\claude.md:5-35,82-107,1240-1247`：采纳实时控制台、计划原子写、配置职责分离、通知不阻塞。SQLAlchemy、python-dotenv、SSE和旧目录是历史建议，未经当前代码确认不得强加。现有sqlite3和WS+轮询可继续复用。

### 1.4 glm参考
`E:\Code\AideanFleet\docs\参考\glm.md:3-24,32-48`：采纳治理前置、Machine Gate优先、worktree/租约、组织智能与执行控制分离、只预留通用领域接口。拒绝把目录预留当成实现；SQLite事务不能回滚已追加JSONL，必须通过持久化待投递事件及可重建投影兑现一致性。

### 1.5 当前裁决
`E:\Code\AideanFleet\docs\adr.md:17-72`：Vue3+Vite+Pinia；工作模式五值与调度模式二值正交；执行体单向依赖manager契约；server归控制面。`E:\Code\AideanFleet\docs\契约\任务状态机.md:68-89`明确**第4次返工升级**，不可沿用历史“×3即升级”模糊口径。扩展须升级契约，而不是以“冻结”为由保留错误。

## 2. 实际执行路径与证据索引

下列编号供全部任务引用。证据中的风险若未动态复现，以静态缺口描述，不冒称实测事故。

| 证据 | 已核实位置与事实 | 对用户的影响 |
|---|---|---|
| E01 | `E:\Code\AideanFleet\fleet\console\server.py:489-518`：非启动消息只固定回执；启动走intake再建线程 | 普通需求修正并未形成计划变更，回执夸大实际动作 |
| E02 | `E:\Code\AideanFleet\fleet\manager\intake.py:94-172,202-250`：固定3阶段5任务；验收主要检查文件/目录存在；集成与终局验收同阶段；允许/禁止文件为空 | 不能代表任意需求分解；终局验收不依赖集成完成 |
| E03 | `E:\Code\AideanFleet\fleet\console\server.py:1012-1055`：项目线程与全项目循环同时创建；`E:\Code\AideanFleet\fleet\manager\dispatcher.py:342-403`读取后迁移；`E:\Code\AideanFleet\fleet\core\db.py:309-326`读状态与更新分离 | 缺原子claim；多循环可能竞态，不应直接扩大并发 |
| E04 | `E:\Code\AideanFleet\fleet\manager\scheduler.py:64-76,125-155,177-195`：确认队列的task_id未用于选任务；一次step调用run_to_completion可内部返工多轮；`E:\Code\AideanFleet\fleet\console\server.py:426-448`意见也入确认队列 | 用户意见不应等同放行；确认对象和一步语义不可靠 |
| E05 | `E:\Code\AideanFleet\fleet\manager\dag.py:22-34,74-94,106-157`：坏依赖返回空；后继用ID前缀；只比对DOING范围；`E:\Code\AideanFleet\fleet\manager\scheduler.py:141-144`同步逐个派工 | 错误依赖可能被当成无依赖；SUBMITTED产物缺保护；单项目不是并行执行 |
| E06 | `E:\Code\AideanFleet\fleet\core\db.py:348-383`先提交状态再写事件；`E:\Code\AideanFleet\fleet\core\plan.py:98-129,147-181`结构来自JSON，读改写锁范围不足；`E:\Code\AideanFleet\fleet\manager\dispatcher.py:299-326`未将stage/subtask持久化到任务行 | JSONL/快照失败不能整体回滚；计划结构不能完全从DB重建 |
| E07 | `E:\Code\AideanFleet\fleet\manager\dispatcher.py:420-425`报告已存在就不写新结果；`E:\Code\AideanFleet\fleet\gates\verify.py:317-351,355-373`只持久化输出尾部，证据写失败不强制失败 | 返工可能读取旧报告，证据可能被覆盖或缺失而仍通过 |
| E08 | `E:\Code\AideanFleet\fleet\manager\reviewer.py:78-96,232-278`判定优先取首个匹配，最终任务model写成审查模型；`E:\Code\AideanFleet\fleet\manager\rework_manager.py:54-69,92-120`证据路径含gate目录与根目录两种 | 矛盾审查、历史执行身份、返工证据需要更严谨结构 |
| E09 | `E:\Code\AideanFleet\fleet\governance\usage.py:27-113`原先误读字段，本轮已修；`E:\Code\AideanFleet\fleet\governance\store.py:30-44,83-109`仍无事件唯一键，扫描全量插入 | 字段修复不等于计量幂等，重复扫描仍可能重复计费 |
| E10 | `E:\Code\AideanFleet\fleet\governance\budget.py:110-175,199-236`消费先读后写、三级分开更新，同步遗漏daily；`E:\Code\AideanFleet\fleet\console\server.py:824-862`仅查询/设置；生产调用检索未见派工前预算检查 | 上下文裁剪不是消费预算；目前不能证明真正熔断 |
| E11 | `E:\Code\AideanFleet\fleet\governance\approval.py:78-171`有审批和过期方法；`E:\Code\AideanFleet\fleet\console\server.py:785-821`决定主要写存储/事件；生产检索未见过期检查调度与审批执行消费 | 页面审批不等于关键动作受控；通过不等于预算已解除 |
| E12 | `E:\Code\AideanFleet\fleet\rel\recovery.py:20-101`具四态恢复函数；`E:\Code\AideanFleet\fleet\console\server.py:1017`活跃集合缺REVIEWING；`E:\Code\AideanFleet\fleet\rel\maintenance.py:20-42`只轮转与stuck扫描 | 恢复函数测试通过不等于启动会实际调用 |
| E13 | `E:\Code\AideanFleet\fleet\core\events.py:37-38,64-90,126-161`线程锁分配seq，增量查询仍全文件读取；`E:\Code\AideanFleet\fleet\console\server.py:195-222`每秒扫描并逐事件算进度 | 多进程一致性与大事件文件性能尚不满足扩展要求 |
| E14 | `E:\Code\AideanFleet\fleet\notify\triggers.py:47-79,172-183,310-417`配置/游标依赖相对路径；按行号而非event.seq追踪；每项目全文件读取 | 轮转后游标语义失配；重复消费者、配置刷新与路径隔离需收敛 |
| E15 | `E:\Code\AideanFleet\fleet\launcher\launch_core.py:137-173,257-338`健康读status但API无该键；忽略若干步骤返回值；固定5000/9900，watchdog用request.port | 启动总结不可信，端口配置与实际守护可能不一致 |
| E16 | `E:\Code\AideanFleet\fleet\console\server.py:593-641`拓展存JSON、角色完整兜底链明确待派工侧支持；生产检索无执行侧读取这两个配置文件 | 保存成功不代表skills/MCP或多执行体兜底已生效 |
| E17 | `E:\Code\AideanFleet\fleet\console\web\src\pages\ChatPage.vue:93-101`调用auth.apply；首次读取store未导出、类型检查失败；最终其他并行改动在`E:\Code\AideanFleet\fleet\console\web\src\stores\auth.ts:129`导出apply，复检通过 | 缺导出已解除；TTL、项目切换和刷新行为尚无本轮浏览器验证 |
| E18 | `E:\Code\AideanFleet\fleet\console\server.py:234-245,865-878,925-971`鉴权范围与执行路由不统一，WS主要在握手检查；`E:\Code\AideanFleet\fleet\launcher\launch_core.py:198-211`与intake路径规则不同 | 需统一控制面授权及工作区验证；本轮仅防御性静态检查 |
| E19 | `E:\Code\AideanFleet\pyproject.toml:9-28`与`E:\Code\AideanFleet\requirements.txt:3-7`依赖口径不同；`E:\Code\AideanFleet\.github\workflows\tests.yml:9-42`只有Python测试；`E:\Code\AideanFleet\tests-e2e\playwright.config.ts:13-47`依赖外部启动服务 | 干净安装、前端检查、端到端基线尚未形成统一出口 |
| E20 | `E:\Code\AideanFleet\tests\core\test_ten_scenarios.py:259-285`手动预置交付/审查；`E:\Code\AideanFleet\tests\core\test_intake.py:19-63`只验建册和推进；本轮新增集成测试补到DONE及计量 | 既有测试不能代替真实需求理解、浏览器和外部执行体验收 |

## 3. 可执行多层级大纲：先正确性，再能力，再性能

### 3.0 统一原子执行规则
每个三级编号是一个可独立验收的行为变更，不是笼统“完善模块”。每项继续拆为五个四级动作：`.a`增加一个行为测试；`.b`运行并记录真实失败（已有行为则记录通过，不造红灯）；`.c`最小实现；`.d`运行目标测试及相关回归；`.e`同步契约/证据并提交独立评审。建议单动作2–15分钟，超出则继续分解，不承诺未经估算的项目天数。提交须由执行阶段明确安排，本轮不提交。

每项证据自动继承所在工作包的E编号；具体实现文件即对应E编号内绝对路径。新文件和测试落点另列。A=后端核心，B=前端，C=启动/执行体/可靠性；跨边界修改由文件owner执行。

### 3.1 W1：可信启动与可用控制台（P0；B/C并行）
依据 E15/E17/E18，用户需求为双入口启动与对话中切换项目。

- [ ] **3.1.1 健康判定契约对齐**（C，E15）：消费version/db/events/config，三项能力必须为布尔真；不改变现有health四键。验收：真实API形状通过，缺键/false/异常响应不通过。
- [ ] **3.1.2 启动结果传播**（C，E15）：每一步记录真实成功/失败/可选降级，必需依赖失败停止后续执行；Hermes不可用不伪装为可用。验收：子进程未启动/早退时总结果失败或明确degraded，不创建可执行假项目。
- [ ] **3.1.3 端口单源**（C，E15）：console/manager/project三个端口分别解析，所有探测、打开浏览器、守护使用同一配置对象。验收：修改console端口后不存在遗留5000监听目标；不擅自停止已有进程。
- [ ] **3.1.4 前端新项目切换**（B，E17）：增加受控会话刷新/切换动作，禁止页面调用未导出私有方法；从服务端取剩余有效期而非重置完整TTL。验收：type-check通过，新项目回复后plan/会话/刷新均指向新项目。
- [ ] **3.1.5 统一工作区校验**（A/C，E18）：入口复用规范化路径和根目录包含判定，空allowlist一致拒绝；保证注册返回路径与已存项目路径一致。验收：合法工作区、未配置根、跨平台路径三类单元验证，无真实受保护目录操作。

测试落点：`E:\Code\AideanFleet\tests\test_cli_launch.py`、`E:\Code\AideanFleet\tests\core\test_intake.py`、`E:\Code\AideanFleet\tests-e2e\specs\intake.spec.ts`（新增）。W1出口：不依赖真实CLI即可证明启动结果可信、项目切换正常。

### 3.2 W2：唯一调度者与严格人工控制（P0；A；并发扩展的前置）
依据 E03/E04/E05，保留一个引擎及auto/step两种策略，不创建两套执行系统。

- [ ] **3.2.1 生命周期统一**（E03）：取消重复的全局/项目派工循环所有权，创建受管理runtime实例；启动、停止、失败退出均可观察并注销。验收：同项目重复启动只存在一个有效调度者，异常退出可恢复。
- [ ] **3.2.2 数据库原子领取**（E03）：用条件更新及事务生成execution attempt；只允许唯一领取者进入外部调用。验收：同任务并发请求只获得一个claim，实际adapter调用一次，失败竞争者不记成功派工。
- [ ] **3.2.3 确认绑定对象**（E04）：确认持久化project/task/action/plan_version和一次性消费状态。验收：A项目确认不推进B项目；陈旧版本拒绝；重复确认只消费一次。
- [ ] **3.2.4 意见不等同放行**（E04）：note写意见事件但不生成执行许可。验收：step模式提交意见后任务保持原状，confirm才推进。
- [ ] **3.2.5 一次确认只走一个动作**（E04）：将dispatch/review/rework拆为runtime调度动作；step路径不得调用内部自动返工多轮的长闭环。验收：一次确认只执行一次已展示动作，重做需下一次确认。
- [ ] **3.2.6 严格依赖关系**（E05）：坏JSON/未知依赖明确报错；用显式predecessor/successor关系代替ID前缀推断。验收：非法依赖不落任务；只有绑定的DONE后继可满足原依赖。
- [ ] **3.2.7 产物生命周期保护**（E05）：资源lease覆盖执行、提交、审查直至产物已固化；同一workspace跨项目仍参与资源冲突判断。验收：待审产物不被下一任务写入污染，释放后下游才能进入。

新增落点：`E:\Code\AideanFleet\fleet\manager\runtime.py`、`E:\Code\AideanFleet\tests\core\test_runtime_ownership.py`、`E:\Code\AideanFleet\tests\core\test_claim.py`。复用测试：`E:\Code\AideanFleet\tests\core\test_scheduler.py`、`E:\Code\AideanFleet\tests\core\test_dag.py`。出口：唯一执行、精确确认、无隐式放行。

### 3.3 W3：状态、事件与计划一致性（P0；A；依赖W2数据模型）
依据 E06/E13。不承诺SQLite与JSONL跨介质的同步原子回滚。

- [ ] **3.3.1 事务内状态与待投递事件**（E06）：SQLite同一事务写task/attempt和outbox，记录事件唯一ID及递增序号。验收：事务失败两者都不存在，成功两者均存在。
- [ ] **3.3.2 可重入事件导出**（E06/E13）：JSONL由单一导出者追加，持久化checkpoint，恢复后不重号、不漏投；规定尾部部分写恢复策略。验收：在导出前后故障点中断后，DB事件与JSONL可逐条对账。
- [ ] **3.3.3 计划结构入库**（E06）：持久化stage/subtask/parent/order/plan_version，迁移现有JSON时单独验证和备份；迁移后禁止JSON反写运行态。验收：丢失计划快照可仅从DB重建完整三级顺序及状态。
- [ ] **3.3.4 快照投影原子发布**（E06）：按版本生成快照，唯一临时文件名与过期版本保护；失败标记投影滞后而非假回滚任务。验收：并发任务更新不丢节点、快照版本单调、重建幂等。
- [ ] **3.3.5 存储上下文贯通**（E06/E12）：ensure_paths、_block、review返工、plan等调用一致传递存储上下文，去掉导入时固定数据路径。验收：指定非默认db_file/数据根时默认库无写入。

新增测试：`E:\Code\AideanFleet\tests\core\test_outbox.py`、`E:\Code\AideanFleet\tests\core\test_plan_projection.py`、`E:\Code\AideanFleet\tests\core\test_storage_context.py`。数据迁移先在副本演练，不能原位破坏真实数据。

### 3.4 W4：需求驱动规划和变更闭环（P1；A；依赖W2/W3）
依据 E01/E02/E20。模型提出结构化建议，系统校验并执行，不让模型直接修改权威状态。

- [ ] **3.4.1 结构化需求契约**（E01/E02）：为requirement/acceptance/risk/assignee/dependencies/deliverables建立可校验请求；区分产品名与稳定项目ID。验收：缺验收标准或角色不合法不能进入可执行计划。
- [ ] **3.4.2 可替换规划提供者**（E02）：保留模板为显式demo fallback，生产由规划provider返回任务建议，经DAG与边界校验后事务落盘。验收：两种不同需求产生对应验收任务，不再无条件固定5条。
- [ ] **3.4.3 计划变更命令**（E01）：普通对话生成变更提案、影响集合、待确认状态；确认后版本更新；没有调用能力时回复“仅记录”而不是“将自动调整”。验收：改需求影响明确的未执行任务，已执行attempt不可篡改。
- [ ] **3.4.4 五工作模式执行策略**（E01/E15）：run执行已批准计划；intake形成需求；plan只提出计划；audit/discuss只读且有轮次上限。验收：非执行模式的adapter写能力不可用，不仅改变提示词文字。
- [ ] **3.4.5 终局验收依赖**（E02）：集成任务完成后再开放终局验收；不可由同一执行身份自审同一交付。验收：集成未DONE时终局不可READY；未覆盖需求不能宣告项目完成。
- [ ] **3.4.6 变更/暂停的运行态语义**（E01/E04）：定义暂停新派工、正在运行的安全终止/等待策略及取消结果留痕；新增状态必须先升级契约。验收：暂停期间零新增claim，运行结果不会被静默删除。

新增落点：`E:\Code\AideanFleet\fleet\manager\planning.py`、`E:\Code\AideanFleet\tests\core\test_plan_changes.py`；扩展 `E:\Code\AideanFleet\fleet\manager\contracts.py` 须发布新版本并做旧字段兼容测试。出口：用户输入和计划变更具有可观察真实效果。

### 3.5 W5：可信验收与不可混淆的执行证据（P0/P1；A/C；依赖W2 attempt）
依据 E02/E07/E08。

- [ ] **3.5.1 每轮独立证据**（E07）：以project/task/attempt存基线、原始回执、命令输出、gate结果，任务只引用当前attempt。验收：第二次执行读取第二轮报告，首轮证据保持不变。
- [ ] **3.5.2 完整输出与摘要分离**（E07）：全量stdout/stderr写文件，API只读有界尾部，记录命令、cwd、退出码、时间和内容摘要。验收：长输出原文可核验，页面仍有界，不把尾部文件称完整证据。
- [ ] **3.5.3 证据写失败关闭验收**（E07）：必需证据失败使结果不可通过并标明确阻塞原因。验收：模拟证据目录写失败时不出现DONE，不调用后续PASS决策。
- [ ] **3.5.4 需求级机器门**（E02）：文件存在检查只作预检；业务行为测试、构建测试和需求ID覆盖进入正式gate。验收：只有空src目录不能通过“可启动/业务正确”的验收。
- [ ] **3.5.5 审查结构与身份历史**（E08）：严格单一verdict结构，保存执行/审查各自model/usage，而不是只看最终task.model；统一gate路径。验收：冲突判定拒绝，执行与审查模型均可追溯。
- [ ] **3.5.6 验证进程生命周期**（E07）：机器门与执行体共用可控进程运行抽象，有超时/输出上限/子进程清理；失败须保留退出事实。验收：仅在隔离测试进程树验证超时后无测试子进程残留。

新增测试：`E:\Code\AideanFleet\tests\core\test_attempt_evidence.py`、`E:\Code\AideanFleet\tests\core\test_gate_contract.py`；既有 `E:\Code\AideanFleet\tests\test_procguard.py` 可扩展。出口：DONE与指定需求、指定attempt、可读证据严格对应。

### 3.6 W6：计量、预算、审批真正进入执行路径（P0/P1；A；依赖W2/W3）
依据 E09/E10/E11。本轮仅修复事件字段映射，以下仍待完成。

- [ ] **3.6.1 事件计量幂等**（E09）：用稳定event_id/seq唯一约束，不用物理行号作为身份；迁移保留来源信息。验收：同事件扫描两次总量不变，轮转后仍可追踪。
- [ ] **3.6.2 持久消费检查点**（E09）：后台消费者接入运行时，不依赖用户打开成本页；错误数据显式隔离。验收：运行一次任务后无需手动scan即可查询用量，重启不漏不重。
- [ ] **3.6.3 完整调用计量**（E08/E09）：执行、审查、规划、失败但有usage的调用统一记账；unknown与0区分，报表返回unknown数量。验收：缺usage不冒充免费，模型/角色/任务归属可对账。
- [ ] **3.6.4 预算预留与结算**（E10）：在外部调用前原子检查三级余额并预留；调用后结算实际值、释放差额；统一时区日期。验收：并发消费不丢更新、不重复预留，余额不足时adapter未调用。
- [ ] **3.6.5 审批绑定具体动作**（E11）：审批包含动作摘要、任务/attempt/计划版本及过期时间；执行前消费一次性许可。验收：批准只放行对应动作一次，拒绝/过期不放行；审批不直接把任务判DONE。
- [ ] **3.6.6 审批恢复与超时执行**（E11）：运行时定时检查过期，批准预算申请须实际更新授权额度/例外再恢复；不是只写事件。验收：超时持久拒绝，重启不复活，批准后下一合法调度动作继续。

新增测试：`E:\Code\AideanFleet\tests\governance\test_usage_replay.py`、`E:\Code\AideanFleet\tests\governance\test_budget_reservation.py`、`E:\Code\AideanFleet\tests\core\test_governed_execution.py`。

### 3.7 W7：恢复、通知与可观察生命周期（P1；C/A；依赖W2/W3）
依据 E12/E13/E14。

- [ ] **3.7.1 启动实际调用恢复**（E12）：按attempt和lease接入ASSIGNED/DOING/SUBMITTED/REVIEWING恢复；未知DOING不盲重跑。验收：四态均从真实startup入口验证，而非只直接调resume函数。
- [ ] **3.7.2 优雅停止与租约回收**（E03/E12）：关闭调度/事件/通知循环并持久化未完动作；lease过期先核验执行进程和证据。验收：重复启动/停止无重复消费者，未知结果进入待核验状态。
- [ ] **3.7.3 通知使用事件身份**（E14）：游标改event.seq/id，存储路径统一paths；每项目独占消费者。验收：归档前后持续消费无重复跳过，改变CWD不改变数据位置。
- [ ] **3.7.4 统一通知配置源**（E14）：控制台保存的开关与SMTP设置按配置版本应用，不保留陈旧闭包。验收：使用fake sender验证开关变更无需重启即可生效。
- [ ] **3.7.5 通知结果可重试可去重**（E14）：持久通知任务与有界重试，sent/failed纳入统一事件；SMTP不可保证远端恰好一次，应提供稳定消息标识和不确定状态。验收：本地重启不丢待发通知，失败可见，不阻塞派工。
- [ ] **3.7.6 后台错误可观察**（E12/E13）：替换关键静默吞异常为脱敏事件/日志，暴露调度心跳、投影滞后与队列积压；保留原health契约，另增运行时状态接口。验收：消费者失败可在控制台定位，基础健康不冒充完整就绪。

新增测试：`E:\Code\AideanFleet\tests\rel\test_runtime_recovery.py`、`E:\Code\AideanFleet\tests\test_notify_replay.py`。

### 3.8 W8：真实扩展能力与控制面边界（P1；A/B/C）
依据 E16/E18及原始材料1.1。只做防御性实现与权限测试，不提供绕过/攻击流程。

- [ ] **3.8.1 执行体能力声明**（E16）：明确支持的模型覆盖、工具配置、流式、只读和取消能力；不支持时阻塞或显式降级，不显示已生效。
- [ ] **3.8.2 角色执行体兜底链**（E16）：运行时消费有序链，按失败类别有限切换，并避免未知执行结果重复执行。验收：首选不可用才切下一候选，切换原因有事件。
- [ ] **3.8.3 扩展配置消费**（E16）：将已批准skills/MCP配置转换为各adapter实际支持的入参，版本随attempt记录。验收：fake adapter收到预期配置，禁用后下一attempt不携带。
- [ ] **3.8.4 统一控制面授权**（E18）：所有执行/修改路径在应用服务层检查会话与资源范围；WS续期/锁定/退出行为一致。验收：权限单元测试覆盖每种控制动作，锁定后不能继续变更任务。
- [ ] **3.8.5 历史凭证处置**（原始材料1.1）：由所有者轮换/撤销已暴露凭证；文档替换为变量名，扫描报告仅输出文件/行号，不输出值。验收：有轮换确认记录及脱敏扫描；删文档不等于撤销旧凭证。

新增测试：`E:\Code\AideanFleet\tests\core\test_executor_configuration.py`、`E:\Code\AideanFleet\tests\core\test_control_permissions.py`。不将本机项目名锁屏宣传为多租户强认证；是否扩展远程服务需单独威胁建模与ADR。

### 3.9 W9：有界高性能与前端真实反馈（P1/P2；A/B；依赖W2/W3/W5）
依据 E05/E13/E14/E17/E20。以下性能数字是建议验收目标，**不是实测性能**。

- [ ] **3.9.1 DAG索引与增量就绪**（E05）：建立task_id映射/反向依赖索引，状态变更仅重算受影响下游；验收：与全量参考算法结果一致，基准记录O(V+E)构建成本。
- [ ] **3.9.2 有界执行并发**（E03/E05）：线程/进程运行槽按全局、项目、执行体设置上限；配合lease，不以项目数无限增加线程。验收：慢任务不阻塞独立项目，队列饥饿有上限，默认并发保守。
- [ ] **3.9.3 有界事件查询**（E13）：基于索引/offset或DB事件查询分页，不每秒全量读JSONL；定义next_cursor/has_more。验收：增量开销随新事件量而非历史总量增长，翻页不漏中间事件。
- [ ] **3.9.4 WS背压与按项目订阅**（E13/E18）：连接有界队列、批量状态合并、慢客户端恢复游标；进度按项目批量算一次。验收：慢连接不拖累其他连接，断线重连得到同一最终状态。
- [ ] **3.9.5 真实进度与流式来源**（E17/E20）：区分真实模型帧、回执动画、测试注入；前端展示计划版本、审批原因、attempt与证据链接。验收：不把动画冒充模型实时输出，项目切换清理旧游标/订阅。
- [ ] **3.9.6 可重现性能基准**（E13/E19）：在固定硬件/依赖下以1万任务、10万历史事件、100条新增事件/秒、10个连接测试；建议本机列表/增量API p95≤200ms、状态可见p95≤1.5s，30分钟稳态无持续内存增长。未达标先定位，不能通过缩减正确性检查达标。

新增基准：`E:\Code\AideanFleet\tests\perf\test_runtime_baseline.py`；浏览器扩展 `E:\Code\AideanFleet\tests-e2e\specs\reconnect.spec.ts`、`E:\Code\AideanFleet\tests-e2e\specs\stream.spec.ts`。性能测试使用合成数据和fake worker，禁止真实调用放大成本。

### 3.10 W10：独立验收与可复现发布（P2；A/B/C；依赖全部发布范围任务）
依据 E19/E20与基线0。

- [ ] **3.10.1 离线/外部测试分层**（E20）：默认测试严格离线，真实CLI/SMTP单独标记、授权和费用上限；测试夹具在模块导入前隔离全部数据根。验收：默认CI不需要密钥或真实CLI，skip有具体原因。
- [ ] **3.10.2 垂直用户旅程E2E**（E01/E17/E20）：启动/解锁→输入需求→计划确认→DONE→计量→证据→修改需求→返工/审批→恢复；使用真实API和fake外部服务。验收：每一用户动作改变真实后台事实，不只验证控件存在。
- [ ] **3.10.3 前后端CI门禁**（E19）：Python矩阵、type-check、构建、隔离Playwright三组明确作业；失败日志和测试报告保留，不以重试掩盖失败。验收：任一检查失败阻止发布。
- [ ] **3.10.4 干净安装验收**（E19）：统一最低Python/开发基线、运行依赖及WS支持、包数据范围；wheel不夹带node_modules/本机配置。验收：干净环境安装产物后静态页、WS、CLI入口可用。
- [ ] **3.10.5 有界真实执行体验收**（E20）：仅在授权后对临时示例项目做一次实际交付，保留版本、费用、命令与机器门证据；失败分类为环境/适配/实现而非统称不可用。验收：真实交付满足真实需求，不把版本探测当作执行验收。
- [ ] **3.10.6 文档和发布定稿**（E19/E20）：README快速启动、契约差异、测试清单、历史结论有效期、已知限制同步；空文档按用途补全或标废弃，不能以“无空文件”替代质量。验收：每项发布需求链接到同一commit的测试/证据；版本号和tag由发布决策确定，不预设0.4.0。

## 4. 执行顺序、接口与阶段出口

### 4.1 并行关系
1. 第一批：B处理W1前端切换；C处理W1启动；A处理W2调度/claim和W3契约。凭证轮换由所有者独立完成，不阻塞离线测试。
2. 第二批：W2/W3稳定后，A处理W6治理与W4计划，C处理W5证据与W7恢复；同一文件只有一个owner，不能同时改dispatcher/server。
3. 第三批：W8执行体能力与前端消费对齐；W9性能只能在claim、lease和证据隔离通过后开展。
4. 第四批：W10在隔离环境验收；真实模型/邮件/发布操作另设授权和预算。

关键路径：**W2领取与人工控制 → W3状态/事件/计划一致性 → W5可信证据 + W6治理 → W4真实需求闭环 → W7恢复 → W9性能 → W10发布**。W1先行消除用户入口的确定错误。

### 4.2 最小接口边界（提案，尚未实现）
- 应用入口：`submit_requirement / propose_change / approve_plan / confirm_action`，统一承接HTTP/WS/CLI/Hermes；返回命令ID和计划版本，不同步等待长任务。
- 调度入口：`claim_action / execute_action / complete_attempt`；领取与状态校验在DB事务中，外部进程不占数据库写事务。
- 执行接口：保留既有BaseAdapter，通过兼容上下文桥接attempt、模型、权限和扩展配置，不强迫四家CLI具有同一能力。
- 治理接口：`reserve_budget / settle_usage / request_approval / consume_approval`；不把审批结果直接映射为业务DONE。
- 投影接口：`export_events / rebuild_plan / consume_notifications`；共享稳定事件ID，独立checkpoint，可重放可对账。

### 4.3 分阶段出口
- G0：目标回归与类型检查通过；启动结论可信，不声称所有功能完成。
- G1：重复请求只执行一次，确认只推进指定动作；状态与事件可恢复对账。
- G2：需求→计划→执行→机器验收→审查→交付完整闭环；意见能真实改变计划；预算/审批不能绕过应用约束。
- G3：运行时启动恢复、事件轮转、通知失败和慢客户端场景均有独立测试。
- G4：满足约定性能基准、干净安装和前后端CI；真实外部依赖另列证据，未验证项明确不在发布承诺内。

## 5. 验证命令与本轮已完成项

### 5.1 本轮新增集成测试（已运行，已通过）
```powershell
& 'E:\Code\AideanFleet\.venv\Scripts\python.exe' -m pytest -p no:cacheprovider 'E:\Code\AideanFleet\tests\core\test_intake_to_done_integration.py' -q --tb=short
```
测试保留真实intake、scheduler、dispatcher、Machine Gate、SQLite、JSONL和usage扫描；仅外部执行体和审查模型为替身。执行体在临时目录创建满足当前模板门的交付物。它证明模板闭环与计量归属，不证明需求语义正确，也不覆盖HTTP/浏览器/真实CLI。本测试与当前intake一样依赖Windows路径语义，跨平台兼容是W1/W10任务。

### 5.2 本轮选择回归（最后实跑：77 passed，16 warnings，12.79s）
```powershell
& 'E:\Code\AideanFleet\.venv\Scripts\python.exe' -m pytest -p no:cacheprovider 'E:\Code\AideanFleet\tests\core\test_intake_to_done_integration.py' 'E:\Code\AideanFleet\tests\core\test_intake.py' 'E:\Code\AideanFleet\tests\core\test_scheduler.py' 'E:\Code\AideanFleet\tests\core\test_ten_scenarios.py' 'E:\Code\AideanFleet\tests\core\test_dag.py' 'E:\Code\AideanFleet\tests\core\test_context_budget.py' 'E:\Code\AideanFleet\tests\core\test_memory.py' 'E:\Code\AideanFleet\tests\governance\test_governance.py' 'E:\Code\AideanFleet\tests\rel\test_recovery_matrix.py' -q --tb=short
```
警告为既有datetime.utcnow弃用，用时不作为性能压测结论。

### 5.3 前端类型检查（首次失败；并行工作导出apply后最终复检通过）
```powershell
& 'E:\Code\AideanFleet\fleet\console\web\node_modules\.bin\vue-tsc.cmd' --noEmit -p 'E:\Code\AideanFleet\fleet\console\web\tsconfig.json'
```
构建和E2E在W10隔离服务就绪后运行，不能直接指向用户正在使用的5000/5050服务。不得将其他会话生成的截图当作本轮验证。

### 5.4 每项原子任务的验证执行方法
目标测试文件由各W包指定。命令统一为 `& 'E:\Code\AideanFleet\.venv\Scripts\python.exe' -m pytest -p no:cacheprovider '<该条指定的绝对测试路径>' -q --tb=short`，实际执行时替换为已创建的具体文件并记录命令；这里是执行规范，不是声称这些未来测试已存在或已通过。新增行为先记录失败、实现后退出码0，最后相关回归无新增失败。

### 5.5 本輪完成与剩余边界
- 已完成：真实事件字段与旧格式兼容映射；五任务DONE及项目/任务/角色/模型计量归属的隔离集成测试；证据驱动方案。
- 尚未完成：W1–W10内58个行为项，包括幂等计量、真实预算门、审批执行消费、自动规划/改计划、原子调度和性能验证。
- 不采纳既有未跟踪方案中的过度结论：有模块不等于全部分层已兑现；Fake验收不能推断真实执行“从未”发生；不能使用尚不存在的API路径作为可执行步骤；不能根据旧PID直接停止进程。
- 本轮未改变其他截图/方案文件，不执行commit、tag或push。交付时保留工作区归属差异，后续实施按W包独立评审。

## 6. 最终补充：重复扫描修复后的状态（晚于上述方案基线）

- 针对W6/3.6.1又新增一个隔离测试：同一条5-token事件扫描两次，修复前实际为10，测试失败（0.29s）。
- 最小修复：`E:\Code\AideanFleet\fleet\governance\store.py`增加可空event_key列及唯一索引，入账返回是否实际新增；`E:\Code\AideanFleet\fleet\governance\usage.py`以冻结流seq去重，旧格式回退文件路径+行号。手工记录event_key为空，不参与去重。
- 最新相关回归：新增测试文件两项 + 既有治理28项，**30 passed / 16 warnings / 4.91s**；diff --check通过。此前77项是字段映射修复时点的较大选择回归，不是此次幂等修复后的全量结果。
- W6/3.6.1状态为**部分完成**：同一事件流重复扫描已验证；跨流身份隔离、历史重复账目对账迁移、旧格式文件轮转和多进程迁移仍未验证。不能把当前seq唯一键扩展解释为支持多独立事件流；历史无event_key记录没有自动回填或去重，首次重新导入须先对账。
- 最终本轮代码改动为两个生产文件usage.py/store.py、一个测试文件；另新增本方案。auth.ts及截图等其他并行改动不属于本轮成果。
- 本文58个行为项是审计形成的实施清单，其中3.6.1已有上述部分进展；不是声称58项均完全未实施。其他条目状态按文中证据与最终复核为准。



