# 一、先给结论：这不是普通的“多 Agent 项目”

你现在设计的东西，本质上应该被定义为：

> **一个本地运行的、可配置的 Multi-Agent Software Engineering Orchestrator（多智能体软件工程自动化执行器）。**

它和“调用几个 Claude Code / Codex / OpenCode”的区别非常大。

真正的核心不是 Agent，而是：

```text
用户需求
    ↓
Manager
    ↓
Project Plan
    ↓
Task DAG
    ↓
Role
    ↓
Execution Agent
    ↓
Execution Result
    ↓
Review
    ↓
PASS / REWORK / BLOCKED
    ↓
DAG重新计算
    ↓
释放新的READY任务
    ↓
继续执行
```

也就是说：

**Agent 是执行资源，不是系统核心。**

你的核心应该是：

```text
                ┌──────────────────────┐
                │      Web Console     │
                │ 自动 / 每步确认 / 对话 │
                └──────────┬───────────┘
                           │
                    ┌──────▼──────┐
CLI ───────────────►│ Application │◄──────── Hermes
                    │   Runtime   │
                    └──────┬──────┘
                           │
              ┌────────────▼────────────┐
              │       Manager           │
              │ Planning / Scheduling   │
              │ Review / Rework         │
              └────────────┬────────────┘
                           │
                    ┌──────▼──────┐
                    │   Task DAG  │
                    └──────┬──────┘
                           │
        ┌──────────────────┼──────────────────┐
        ▼                  ▼                  ▼
   Role Worker        Role Worker        Role Worker
        │                  │                  │
        ▼                  ▼                  ▼
   Claude Code          Codex             OpenCode
        │                  │                  │
        └──────────────────┼──────────────────┘
                           ▼
                    Execution Result
                           │
                           ▼
                        Review
                           │
                    ┌──────┴──────┐
                    ▼             ▼
                  PASS          REWORK
                    │             │
                    └──────┬──────┘
                           ▼
                       Scheduler
```

---

# 二、第一件必须解决的事情：把“模型、角色、执行体”彻底分层

这是你整个架构里最重要的设计之一。

你现在已经明确区分：

* 模型
* 角色
* 执行体
* Skills
* MCP

这是正确的。

但开发时一定不能把它们写成互相调用的硬编码。

应该建立：

```text
Model
   ↓
Role
   ↓
Execution Agent
   ↓
Tools
```

例如：

```text
模型池

agnes3
agnes2
claude
custom-model
...
```

角色池：

```text
manager
ui
frontend
data
backend-1
backend-2
reviewer
```

执行体池：

```text
claudecode
codex
opencode
hermes-agent
custom-cli
```

然后角色只声明：

```text
role = backend-1

preferred_models:
    - agnes3
    - agnes2

executor:
    opencode
```

而不是：

```text
backend-1 -> 直接调用 OpenCode
```

这样以后才能做到：

```text
后端1
  ↓
OpenCode
  ↓
Model A

或者

后端1
  ↓
Claude Code
  ↓
Model B
```

甚至：

```text
同一个角色
    ↓
执行体失败
    ↓
自动切换执行体
    ↓
另一个执行体
```

这会直接决定你的系统以后是不是“真正可配置”。

你的设计已经明确提出模型可配置，包括 `name / level / base_url / model_id / api_key / proxy` 等信息；角色则通过 `bind_model_name` 绑定模型；执行体又是 ClaudeCode、OpenCode、Codex、Hermes 子 Agent 等。

---

# 三、第二件必须解决的事情：Manager 不能直接等于 LLM

这是整个项目最容易走偏的地方。

不要设计成：

```text
Manager = 一个LLM
```

应该是：

```text
Manager
├── Manager LLM
├── Planner
├── Scheduler
├── DAG Engine
├── Reviewer
├── State Manager
├── Rework Manager
└── User Interaction
```

也就是说：

**LLM 负责“思考”，系统负责“执行规则”。**

例如 Manager LLM 说：

> BE-03 可以执行。

不能直接执行。

系统必须判断：

```text
BE-03
    ↓
依赖任务是否 PASS？
    ↓
是
    ↓
是否 BLOCKED？
    ↓
否
    ↓
是否存在冲突？
    ↓
否
    ↓
READY
```

然后 Scheduler 才真正启动。

否则你的“DAG”最终只是 Prompt 里的一个概念，而不是一个真正可靠的调度系统。

---

# 四、第三件必须解决的事情：DAG 应该成为系统的“心脏”

你目前已经设计：

```text
READY
EXECUTING
REVIEW
WAITING
BLOCKED
REWORK
DONE
```

这是非常重要的。

任务对象建议至少抽象为：

```text
Task
├── id
├── projectId
├── stageId
├── parentId
├── roleId
├── executorId
├── modelId
├── type
├── status
├── reviewStatus
├── dependencies
├── dependents
├── input
├── output
├── scope
├── conflictScope
├── acceptanceCriteria
├── createdAt
└── updatedAt
```

你目前数据库设计已经包含任务 ID、角色、下发角色、回执角色、平台、模型、任务类型、token、耗时、详情、备注、执行状态、审查状态以及创建/更新时间。

但是开发时我建议：

> **数据库字段负责持久化，Task Domain Object 负责业务逻辑。**

不要让业务代码到处直接：

```ts
UPDATE task SET status = ...
```

而应该：

```ts
task.start()
task.complete()
task.requestReview()
task.pass()
task.rework()
task.block()
```

这样状态转换规则才能集中。

---

# 五、plan.json 不应该成为真正的数据库

你目前设计：

> `plan.json` = 三级大纲规划目录，每次 Manager 分配后实时同步更新。

我建议保留，但重新定义它：

```text
数据库
= 真正运行状态

plan.json
= 项目计划快照 / 可读计划
```

不要让：

```text
数据库
↕
plan.json
```

形成双向状态源。

正确：

```text
              ┌──────────────┐
              │ Task Domain  │
              └──────┬───────┘
                     │
          ┌──────────┴──────────┐
          ▼                     ▼
      Database              plan.json
    Runtime State          Human-readable
```

这样可以避免以后出现：

```text
数据库说 BE-01 DONE
plan.json 说 BE-01 EXECUTING
```

这种灾难。

---

# 六、CLI 和 Hermes：应该是两个入口，而不是两个系统

你要求：

> CLI 可以启动，Hermes 也可以启动。

最合理的架构是：

```text
CLI
 │
 ▼
┐
│
├── Application Runtime
│
┘
▲
 │
Hermes Adapter
```

而不是：

```text
CLI → 一套代码

Hermes → 另一套代码
```

两个入口最终都执行：

```ts
startProject(request)
```

所以：

```text
CLI
   ↓
Command Adapter
   ↓
Application API
   ↓
Project Runtime
```

Hermes：

```text
Hermes
   ↓
Hermes Adapter
   ↓
Application API
   ↓
Project Runtime
```

这样以后增加：

```text
HTTP API
WebSocket
Telegram
WeChat
其他 Agent
```

都只是增加 Adapter。

---

# 七、Web 控制端实际上应该是“控制台”，不是普通前端页面

你设计的 Web UI 非常明确：

* 深色科技风
* 锁屏
* 左侧一级菜单
* 中央实时执行区
* 右侧 DAG/进度
* 自动/确认模式
* 实时与 Manager 对话
* 动态展开三级大纲
* 鼠标中键滚动
* 面板宽度拖拽

所以它应该被定义为：

> **Execution Control Console**

而不是简单 Dashboard。

你的页面结构可以抽象成：

```text
AppShell
│
├── LockScreen
│
├── Header
│   ├── Lock
│   └── Settings
│
├── Sidebar
│   ├── Overview
│   ├── Conversation
│   ├── Models
│   ├── Roles
│   ├── Executors
│   ├── Extensions
│   └── Messages
│
├── MainWorkspace
│
└── ProgressRail
```

这与你当前设计中的七个一级模块基本一致。

---

# 八、Web 与 Runtime 不应该直接耦合

推荐：

```text
Web UI
   │
   │ HTTP
   ▼
API
   │
   │ WebSocket / SSE
   ▼
Runtime
```

例如：

```text
POST /projects
POST /projects/:id/start
POST /projects/:id/pause
POST /projects/:id/resume
POST /tasks/:id/approve
POST /tasks/:id/rework
POST /projects/:id/chat
```

实时状态：

```text
Runtime
   ↓
Event Bus
   ↓
WebSocket/SSE
   ↓
UI
```

这样你的：

> “动态实时信息面板”

就不会变成前端不断轮询数据库。

---

# 九、自动执行 / 每步确认，本质上不应该做两套流程

这是一个很好的设计点。

你当前要求：

```text
自动执行
每步确认
```

不要实现成：

```text
AutoEngine

ConfirmEngine
```

应该只有一个：

```text
Execution Engine
```

区别只有：

```text
Execution Policy
```

例如：

```ts
executionMode = AUTO
```

或者：

```ts
executionMode = CONFIRM
```

执行过程：

```text
Task完成
   ↓
Review
   ↓
PASS
   ↓
Policy判断
   ↓
AUTO
 ───────→ 自动释放后继任务

CONFIRM
 ───────→ WAIT_USER_CONFIRMATION
```

这样非常干净。

---

# 十、用户随时和 Manager 对话，是“控制平面”而不是普通聊天

你设计：

> 程序主体还在执行时，用户可以通过对话和 Manager 交流，实时调整/修正任务信息。

这个功能非常重要。

建议定义：

```text
Control Plane
```

而不是：

```text
Chat
```

因为用户说：

> “后端不要用 Redis。”

实际上可能影响：

```text
当前任务
↓
后续任务
↓
架构
↓
已有工作包
```

因此 Manager 收到对话以后应该：

```text
User Message
    ↓
Manager Analysis
    ↓
Impact Analysis
    ↓
Affected Tasks
    ↓
DAG Mutation
    ↓
Re-plan
    ↓
Continue
```

而不是简单把消息发给一个聊天 LLM。

---

# 十一、你这个系统最核心的六个 Domain

我建议最终 Domain 层明确拆成：

```text
Project
Plan
Task
Agent
Execution
Review
```

进一步：

```text
Project
 ├── ProjectLifecycle
 └── ProjectContext

Plan
 ├── Stage
 ├── WorkPackage
 └── Dependency

Task
 ├── TaskLifecycle
 ├── TaskState
 └── TaskDependency

Agent
 ├── Model
 ├── Role
 ├── Executor
 └── Capability

Execution
 ├── ExecutionSession
 ├── ExecutionAttempt
 └── ExecutionResult

Review
 ├── ReviewSession
 ├── ReviewResult
 └── Rework
```

这样才真正体现：

> **Manager 管的是软件工程能力，而不是文件修改。**

你给出的管理规范最终也明确把目标定义为“软件工程能力的持续交付”，并强调有效并行度最大化、碎片化最低以及每个工作包拥有真实工程价值。

---

# 十二、推荐的高效项目目录结构

这里我建议不要采用传统：

```text
controllers/
services/
utils/
models/
```

这种“技术文件夹优先”的结构。

你的项目应该：

> **Domain 优先 + Application 次之 + Infrastructure 最后。**

推荐：

```text
project-root/
│
├── .env.example
├── .gitignore
├── package.json
├── tsconfig.json
├── README.md
├── AGENTS.md
│
├── config/
│   ├── defaults.ts
│   ├── schema.ts
│   └── loader.ts
│
├── data/
│   ├── database/
│   ├── projects/
│   ├── plans/
│   ├── logs/
│   └── runtime/
│
├── src/
│   │
│   ├── cli/
│   │   ├── commands/
│   │   ├── prompts/
│   │   └── index.ts
│   │
│   ├── web/
│   │   ├── api/
│   │   ├── websocket/
│   │   └── server.ts
│   │
│   ├── domain/
│   │   │
│   │   ├── project/
│   │   │   ├── entities/
│   │   │   ├── value-objects/
│   │   │   ├── services/
│   │   │   └── repository.ts
│   │   │
│   │   ├── plan/
│   │   │   ├── entities/
│   │   │   ├── dependency/
│   │   │   ├── dag/
│   │   │   └── repository.ts
│   │   │
│   │   ├── task/
│   │   │   ├── entities/
│   │   │   ├── lifecycle/
│   │   │   ├── state-machine/
│   │   │   └── repository.ts
│   │   │
│   │   ├── agent/
│   │   │   ├── model/
│   │   │   ├── role/
│   │   │   ├── executor/
│   │   │   └── capability/
│   │   │
│   │   ├── execution/
│   │   │   ├── session/
│   │   │   ├── attempt/
│   │   │   ├── result/
│   │   │   └── lifecycle/
│   │   │
│   │   └── review/
│   │       ├── review-session/
│   │       ├── result/
│   │       └── rework/
│   │
│   ├── application/
│   │   │
│   │   ├── project/
│   │   ├── planning/
│   │   ├── scheduling/
│   │   ├── execution/
│   │   ├── review/
│   │   ├── rework/
│   │   ├── conversation/
│   │   ├── confirmation/
│   │   └── notification/
│   │
│   ├── infrastructure/
│   │   │
│   │   ├── database/
│   │   ├── filesystem/
│   │   ├── logger/
│   │   ├── event-bus/
│   │   │
│   │   ├── llm/
│   │   │   ├── openai-compatible/
│   │   │   └── providers/
│   │   │
│   │   ├── executors/
│   │   │   ├── claude-code/
│   │   │   ├── codex/
│   │   │   ├── opencode/
│   │   │   ├── hermes/
│   │   │   └── custom/
│   │   │
│   │   ├── hermes/
│   │   │   └── adapter.ts
│   │   │
│   │   ├── notifications/
│   │   │   └── email/
│   │   │
│   │   └── process/
│   │
│   ├── shared/
│   │   ├── types/
│   │   ├── errors/
│   │   ├── constants/
│   │   ├── result/
│   │   └── utils/
│   │
│   └── index.ts
│
├── frontend/
│   ├── app/
│   ├── components/
│   ├── features/
│   │   ├── overview/
│   │   ├── conversation/
│   │   ├── models/
│   │   ├── roles/
│   │   ├── executors/
│   │   ├── extensions/
│   │   └── messages/
│   ├── hooks/
│   ├── stores/
│   ├── services/
│   └── styles/
│
├── prompts/
│   ├── manager/
│   ├── reviewer/
│   ├── roles/
│   └── system/
│
├── skills/
│
├── mcp/
│
├── tests/
│   ├── unit/
│   ├── integration/
│   ├── contract/
│   ├── e2e/
│   └── fixtures/
│
└── scripts/
    ├── dev.ts
    ├── build.ts
    └── migrate.ts
```

---

# 十三、为什么这个目录结构适合你

最重要的是：

```text
src/domain
```

永远不知道：

```text
Claude Code
Codex
OpenCode
Hermes
OpenAI
Agnes
```

这些东西。

例如：

```text
Task
```

只知道：

```text
ExecutionPort
```

而不是：

```ts
import OpenCode from "...";
```

真正实现：

```text
domain
   ↓
application
   ↓
port
   ↓
infrastructure
```

也就是：

```text
┌───────────────────────────┐
│         Domain            │
│     不知道外部世界        │
└─────────────▲─────────────┘
              │
┌─────────────┴─────────────┐
│       Application         │
│       编排业务流程        │
└─────────────▲─────────────┘
              │
┌─────────────┴─────────────┐
│      Infrastructure       │
│ LLM / CLI / DB / Hermes   │
└───────────────────────────┘
```

这会让你未来替换：

```text
OpenCode
→ Claude Code
```

或者：

```text
SQLite
→ PostgreSQL
```

或者：

```text
WebSocket
→ SSE
```

不会影响 Domain。

---

# 十四、完整开发计划

下面是我认为最适合你这个项目的开发顺序。

**不要按照“页面 → API → 后端 → Agent”这种传统方式开发。**

应该按照：

> **基础运行能力 → Domain → DAG → 执行 → Review → Web → 双入口 → 完整自动化**

---

## Phase 0：工程基线

### P0-01 项目运行基线

目标：

```text
npm install
npm run dev
```

能够稳定启动。

完成：

* TypeScript
* Node.js runtime
* package scripts
* 环境变量加载
* 日志
* 错误处理
* 开发/生产模式
* 本地数据目录

---

### P0-02 配置系统

实现：

```text
.env.example
      ↓
初始化
      ↓
.env
      ↓
Runtime Config
```

必须做到：

> `.env` 可读可写，并且实时读取，不使用永久缓存。

你原始设计明确要求 `.env.example` 是模板、禁止写入，而 `.env` 在初始化时由它复制，并且实时读取。

建议配置领域：

```text
System
Models
Roles
Executors
Extensions
Notifications
Runtime
Security
```

---

# Phase 1：Domain 核心

这是整个项目最重要的一阶段。

---

## P1-01 Project Domain

实现：

```text
Project
ProjectStatus
ProjectContext
ProjectLifecycle
```

能力：

```text
create
initialize
start
pause
resume
complete
fail
```

---

## P1-02 Task Domain

实现完整状态机：

```text
WAITING
READY
EXECUTING
REVIEW
REWORK
BLOCKED
DONE
```

重点：

> 所有状态变化必须经过 Domain。

不能到处直接修改状态。

---

## P1-03 Task DAG

实现：

```text
dependencies
dependents
ready detection
blocked detection
cycle detection
topological relationship
```

核心能力：

```text
Task A PASS
     ↓
检查 B
     ↓
B 所有依赖满足？
     ↓
READY
```

---

## P1-04 Work Package

把你目前 Prompt 中的：

> 工作包

正式变成 Domain 对象。

必须支持：

```text
目标
输入
输出
依赖
冲突范围
验收标准
角色
阶段
状态
```

---

# Phase 2：Agent Registry

---

## P2-01 Model Pool

实现：

```text
Model
ModelProvider
ModelPriority
ModelAvailability
```

支持：

```text
name
level
baseUrl
modelId
apiKey
proxy
```

并支持：

```text
Model A 失败
↓
Model B
↓
Model C
```

---

## P2-02 Role Pool

实现：

```text
Role
SystemPrompt
ModelBinding
ExecutorBinding
```

例如：

```text
manager
ui
frontend
data
backend-1
backend-2
reviewer
```

---

## P2-03 Executor Pool

定义统一接口：

```ts
Executor
```

然后分别实现：

```text
ClaudeCodeExecutor
CodexExecutor
OpenCodeExecutor
HermesExecutor
CustomExecutor
```

这是以后整个系统可扩展性的关键。

---

# Phase 3：Execution Engine

这一阶段开始真正“跑 Agent”。

---

## P3-01 Execution Session

每个任务执行必须拥有：

```text
ExecutionSession
```

包含：

```text
task
role
executor
model
startTime
endTime
attempts
logs
result
```

---

## P3-02 Process Manager

负责：

```text
启动 CLI
传入 Prompt
读取 stdout
读取 stderr
监听退出
超时
Kill
Retry
```

---

## P3-03 Executor Adapter

例如：

```text
Task
 ↓
ExecutorFactory
 ↓
OpenCodeExecutor
 ↓
spawn
 ↓
OpenCode CLI
```

不能让 Application 层直接 `spawn("opencode")`。

---

## P3-04 Retry

你已经有：

> 请求超时时间 + 请求重试次数

建议分成两个概念：

```text
LLM Retry
Executor Retry
```

不要混为一谈。

例如：

```text
LLM API失败
→ LLM retry

OpenCode进程失败
→ executor retry
```

---

# Phase 4：Manager Engine

这是项目真正开始“自动化”的阶段。

---

## P4-01 Manager Context

Manager 每次思考之前自动获取：

```text
项目
阶段
任务 DAG
角色状态
执行状态
Review 状态
最新代码状态
用户消息
历史决策
```

---

## P4-02 Planner

Manager 输出：

```text
Stage
WorkPackage
Dependency
Parallel Group
Acceptance Criteria
```

---

## P4-03 Scheduler

Scheduler 不负责思考。

它负责：

```text
READY
 ↓
选择可用角色
 ↓
检查冲突
 ↓
检查依赖
 ↓
启动 Execution
```

---

## P4-04 Rolling Scheduler

这是你需求里非常关键的能力。

不能：

```text
一轮任务
↓
全部完成
↓
下一轮
```

而应该：

```text
A完成
 ↓
Review
 ↓
PASS
 ↓
释放A的后继任务
 ↓
A继续下一任务

B继续
C继续
```

你现有管理规范已经明确要求“一个角色完成后立即审查、更新 DAG、释放后继任务”，而不是等待整轮完成。

---

# Phase 5：Review Engine

---

## P5-01 Review

Review 必须独立于执行。

```text
Execution
   ↓
Result
   ↓
Reviewer
```

Review 至少检查：

```text
功能
架构
代码
数据
异常
测试
集成
回归
```

这些检查维度与你现有规范一致。

---

## P5-02 Review Result

只允许：

```text
PASS
PARTIAL
REWORK
BLOCKED
```

---

## P5-03 Rework

形成：

```text
Original Task
      ↓
Review
      ↓
REWORK
      ↓
Rework Work Package
      ↓
Execution
      ↓
Review
```

而不是简单：

```text
“你再修一下”
```

---

# Phase 6：Event System

这是 Web 和 Runtime 解耦的关键。

建立统一事件：

```text
ProjectCreated
ProjectStarted

TaskCreated
TaskReady
TaskStarted
TaskCompleted

ReviewStarted
ReviewPassed
ReviewFailed

TaskBlocked
TaskRework

AgentStarted
AgentStopped

UserMessageReceived

ConfirmationRequired
```

然后：

```text
Event Bus
├── WebSocket
├── Database
├── Logger
├── Notification
└── UI
```

---

# Phase 7：Web Console

现在才开始重点开发 UI。

因为此时后台已经拥有真正的状态。

---

## P7-01 Lock Screen

实现：

```text
项目名
↓
解锁
↓
Session
```

---

## P7-02 Overview

中央主体：

```text
当前步骤
```

历史步骤：

```text
折叠
```

支持：

```text
实时更新
滚动
当前步骤突出
执行日志
结果
```

---

## P7-03 Progress Rail

实现：

```text
阶段
 ↓
任务
 ↓
当前进度
```

你的：

```text
绿色 = 完成
红色 = 未完成
青碧 = 当前
```

应该属于 UI 状态映射，而不是后端业务逻辑。

---

## P7-04 Conversation

实现：

```text
用户
 ↓
WebSocket
 ↓
Manager
 ↓
Impact Analysis
 ↓
DAG
```

---

## P7-05 Configuration

统一：

```text
Models
Roles
Executors
Extensions
Messages
Runtime
```

---

# Phase 8：Confirmation Engine

实现：

```text
AUTO
CONFIRM
```

统一 Execution Engine。

CONFIRM 模式：

```text
任务完成
 ↓
Review PASS
 ↓
等待用户确认
 ↓
用户确认
 ↓
Scheduler继续
```

如果用户输入修改意见：

```text
User Feedback
 ↓
Manager
 ↓
重新规划
```

---

# Phase 9：Hermes Integration

此时再接 Hermes。

架构：

```text
Hermes
 ↓
Hermes Adapter
 ↓
Application Runtime
```

Hermes 不知道：

```text
Task DAG内部细节
Database
Web UI
```

它只是：

> 外部启动/控制入口。

---

# Phase 10：CLI Integration

CLI：

```text
ctxhs
```

或者你未来确定的实际 CLI 名称。

最终：

```bash
ctxhs
```

启动：

```text
CLI
 ↓
创建/选择项目
 ↓
启动 Runtime
 ↓
打开 Web Console
```

这样与你要求的：

> CLI 引导启动 → Hermes 接收指令

以及：

> Hermes 直接接收指令

能够统一起来。

---

# 十一、最终完整运行链路

最终应该达到：

```text
                    USER
                     │
          ┌──────────┴──────────┐
          │                     │
         CLI                  Hermes
          │                     │
          └──────────┬──────────┘
                     ▼
              Application Runtime
                     │
                     ▼
              Project Initialize
                     │
                     ▼
                  Manager
                     │
                     ▼
              Analyze Requirement
                     │
                     ▼
                Create Plan
                     │
                     ▼
               Build Task DAG
                     │
          ┌──────────┼──────────┐
          ▼          ▼          ▼
        READY      READY      READY
          │          │          │
          ▼          ▼          ▼
        Role A     Role B     Role C
          │          │          │
          ▼          ▼          ▼
      Executor    Executor    Executor
          │          │          │
          ▼          ▼          ▼
        Agent      Agent      Agent
          │          │          │
          └──────────┼──────────┘
                     ▼
                  Results
                     │
                     ▼
                  Reviewer
                     │
            ┌────────┼────────┐
            ▼        ▼        ▼
          PASS     REWORK   BLOCKED
            │        │        │
            │        ▼        │
            │      Fix        │
            │        │        │
            │        └───┐    │
            ▼            ▼    ▼
             DAG Scheduler
                     │
                     ▼
               New READY Tasks
                     │
                     ▼
                  Continue
```

---

# 十二、我认为你现在最应该避免的 7 个坑

### 1. 不要先做 UI

否则很容易做出一个漂亮的：

> “假实时控制台”。

应该先把 Runtime 跑通。

---

### 2. 不要先接 Claude Code / Codex / OpenCode

先做：

```text
MockExecutor
```

把整个：

```text
Task → Execute → Result → Review → Scheduler
```

跑通。

之后接真实 Agent。

---

### 3. 不要让 Manager 直接控制进程

错误：

```text
Manager LLM
 ↓
spawn opencode
```

正确：

```text
Manager
 ↓
Scheduler
 ↓
ExecutionService
 ↓
Executor
 ↓
Process
```

---

### 4. 不要让数据库承担业务规则

数据库只负责：

```text
Persistence
```

Domain 负责：

```text
Lifecycle
```

---

### 5. 不要让 plan.json 成为第二个状态数据库

它应该是：

```text
Plan Snapshot
```

---

### 6. 不要让角色之间直接互相调用

应该：

```text
Role A
 ↓
Task / Event / Contract
 ↓
Scheduler
 ↓
Role B
```

不要：

```text
Backend Agent
 ↓
直接调用 Frontend Agent
```

否则 DAG 最终会失控。

---

### 7. 不要让“全自动”变成“无限自动”

你已经定义了真正需要人工介入的情况：

* 产品需求冲突
* 商业选择
* 不可逆架构决策
* 缺关键凭证
* 无法合理推断
* 重大安全/数据风险
* 多方案且无法由技术负责人决定

这部分应该成为正式的：

```text
HumanDecisionRequired
```

状态，而不是 Manager 随便：

> “我不知道，问用户。”

你的现有规则也明确要求普通技术问题不得轻易请求用户。

---

# 十三、推荐的实际开发顺序

如果由我来给你的 AI Coding Team 排序，我不会直接让 3 个角色去“开发三个页面”。

而会这样推进：

```text
阶段 0
工程基线
       │
       ▼
阶段 1
Domain + State Machine
       │
       ▼
阶段 2
Task DAG + Scheduler
       │
       ▼
阶段 3
Model / Role / Executor Registry
       │
       ▼
阶段 4
Execution Engine
       │
       ▼
阶段 5
Review + Rework
       │
       ▼
阶段 6
Event System
       │
       ▼
阶段 7
Manager Engine
       │
       ▼
阶段 8
Web Console
       │
       ▼
阶段 9
Auto / Confirm
       │
       ▼
阶段 10
Hermes Adapter
       │
       ▼
阶段 11
CLI
       │
       ▼
阶段 12
端到端真实 Agent
       │
       ▼
阶段 13
压力测试 / 故障恢复 / 并发测试
       │
       ▼
阶段 14
发布
```

其中真正的“技术核心”其实只有：

```text
Domain
   +
DAG
   +
Scheduler
   +
Executor
   +
Review
   +
Manager
```

Web、CLI、Hermes 都属于外围入口/控制层。

---

# 十四、如果采用你现有的多角色管理制度，第一轮并发应该这样设计

你要求**不要为了并发而制造垃圾任务**。这个原则是对的。你的管理规范也明确要求工作包必须形成完整工程能力，而不能只是修改一个文件、增加一个接口、跑一次测试或检查端口。

因此第一阶段可以真正形成三个大型并行工作包：

```text
                    P0 工程基线
                         │
                         ▼
                ┌────────┼────────┐
                │        │        │
                ▼        ▼        ▼
             Worker A Worker B Worker C
                │        │        │
                ▼        ▼        ▼
          Domain核心   配置/Agent   Web基础
                │        │        │
                └────────┼────────┘
                         ▼
                    Integration
                         │
                         ▼
                    DAG Runtime
```

### Worker A

```text
Project / Task / State Machine / Work Package
```

### Worker B

```text
Config / Model / Role / Executor Registry
```

### Worker C

```text
Web Console Shell / API Contract / Realtime Event UI基础
```

这三个工作包**真实独立**，而且都能持续工作，不是：

```text
A写一个文件
B改一个按钮
C检查端口
```

而是三个具有完整工程价值的能力域。

---

# 十五、最终架构一句话

如果让我把你的整个项目压缩成一句架构定义，我会定成：

> **一个以 Task DAG + Scheduler 为核心，以 Manager 为智能决策层，以 Domain 为业务内核，以 Executor Registry 为 Agent 执行抽象，以 Web Console 为控制平面，并通过 CLI / Hermes 提供多入口的本地 Multi-Agent 软件工程自动化执行平台。**

对应到代码就是：

```text
                 CLI / Hermes
                       │
                       ▼
              ┌────────────────┐
              │ Application     │
              │ Runtime         │
              └───────┬────────┘
                      │
          ┌───────────▼───────────┐
          │       Manager         │
          │ Plan / Review / Rework│
          └───────────┬───────────┘
                      │
                 ┌────▼────┐
                 │ Task DAG│
                 └────┬────┘
                      │
                 Scheduler
                      │
          ┌───────────┼───────────┐
          ▼           ▼           ▼
        Role        Role        Role
          │           │           │
        Model       Model       Model
          │           │           │
      Executor    Executor    Executor
          │           │           │
       Agent        Agent       Agent
          └───────────┼───────────┘
                      ▼
                  Execution
                      │
                      ▼
                    Review
                      │
                PASS / REWORK
                      │
                      ▼
                  Scheduler
```

**我认为你现在最应该先做的，不是 UI，也不是接 Hermes，而是先把 `Domain → Task State Machine → DAG → Scheduler → Mock Executor → Review → Rework` 这一条闭环做出来。**

只要这条闭环成立，后面的 Claude Code、Codex、OpenCode、Hermes、Web UI、模型池，本质上都是“接入不同适配器”；如果这条闭环没成立，哪怕 UI 做得再漂亮，最后也很容易变成一个“多 Agent 控制面板”，而不是你真正想要的**自动化软件开发执行器**。
