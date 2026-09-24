# 架构要点分析（头脑风暴展开）

## 关键设计决策梳理

**1. 双启动模式**
- CLI引导启动：用户通过终端交互式初始化，适合首次配置
- Hermes直接启动：Agent-to-Agent调用，适合自动化pipeline
- 两种模式最终都汇聚到同一个WebSocket通道 → 网页控制端接管

**2. 网页控制端是核心枢纽**
- 不是辅助工具，是运行时唯一的控制界面
- 必须在任何启动方式后第一时间打开
- 实时性要求高：进度、对话、状态全部动态更新
- 前后端分离但需要极低延迟通信（SSE或WebSocket）

**3. 数据层设计**
- .env：配置，实时读取，无缓存
- 文本型数据库（SQLite最合适）：任务进度表
- plan.json：三级大纲，结构化任务树，实时同步
- 三者职责分离清晰

**4. 角色体系**
- Manager（项目技术经理）：主控大脑，分析需求，建立plan
- 执行角色（产品/UI、前端、数据交互、后端×2、审查）：具体执行
- 执行体（claudecode/opencode/codex/hermes子agent）：实际运行工具

**5. 模型池与故障转移**
- bind_model_name列表：第一个不通切第二个，链式fallback
- level优先级控制调度顺序
- 额度不足触发邮件通知

**6. 审查机制**
- 执行状态与审查状态双轨并行
- 审查不通过 → 触发REWORK回路
- 这是系统可靠性的核心保障

---

# 完整开发计划

```markdown
# 自动化执行器 · 完整开发计划

---

## 元信息

- 项目代号：Hermes Executor
- 角色数量：3个并发角色
  - 角色A：全栈架构师（负责后端核心引擎 + 数据层 + API）
  - 角色B：前端工程师（负责网页控制端完整实现）
  - 角色C：项目经理兼集成工程师（负责CLI/Hermes启动层 + 集成 + 配置体系）
- 并行策略：Phase 1三角色全并行，Phase 2依赖契约并行，Phase 3集成收敛

---

## 阶段总览

```
Phase 0: 环境奠基（串行，全员依赖）
    ↓
Phase 1: 三域并行开发（角色A/B/C全并行）
    ├── A: 后端引擎 + 数据层 + API体系
    ├── B: 网页控制端完整UI + 实时通信
    └── C: 启动层 + 配置体系 + 执行体调度
    ↓
Phase 2: 角色集成 + 联调（依赖Phase 1全部PASS）
    ↓
Phase 3: 审查回路 + 通知体系 + 容错完善
    ↓
Phase 4: 端到端验收 + 压测 + 交付
```

---

## Phase 0：环境奠基

> 目标：建立可运行的基础骨架，让三个角色可以真正并行
> 执行者：项目经理（角色C）主导，其余角色配合确认
> 预计工作量：半天

### 0.1 技术选型确认

#### 0.1.1 后端语言与框架
- 选型：Python 3.11+
- Web框架：FastAPI（原生async、自动OpenAPI文档、WebSocket支持）
- 理由：与AI模型调用库生态最兼容，httpx异步请求，符合项目需求

#### 0.1.2 数据库选型
- 选型：SQLite（通过SQLAlchemy ORM）
- 文件路径：`./data/executor.db`
- 理由：文本型、零配置、可随项目目录迁移、符合"文本型数据库"设计要求

#### 0.1.3 前端框架
- 选型：Vue 3 + Vite + TypeScript
- UI组件：自建（深色科技风，不依赖重型组件库）
- 实时通信：WebSocket（主通道）+ SSE（备用流式）
- 理由：响应式状态管理契合实时面板需求，Vite热更新提升开发效率

#### 0.1.4 通信协议
- 前后端主通道：WebSocket（ws://localhost:PORT/ws）
- REST API：FastAPI路由（配置读写、历史查询）
- Hermes接入：HTTP POST端点（/api/hermes/invoke）

#### 0.1.5 配置格式
- .env文件：python-dotenv实时读取（force_reload=True，无缓存）
- plan.json：标准JSON，原子写入（写临时文件再rename，防止损坏）

### 0.2 仓库结构初始化

#### 0.2.1 创建根目录骨架
- 按照最终目录结构创建所有空目录
- 创建`.gitignore`（排除.env、*.db、__pycache__、node_modules、dist）
- 创建根目录`README.md`（项目说明）

#### 0.2.2 创建.env.example
- 写入所有配置项的注释说明和默认值
- 包含：基础信息、模型池、角色模型、启动方式、邮件配置、超时/重试设置
- 此文件只读，禁止程序写入

#### 0.2.3 初始化前端工程
- `cd frontend && npm create vite@latest . -- --template vue-ts`
- 安装依赖：`npm install`
- 验证：`npm run dev` 可以访问

#### 0.2.4 初始化后端工程
- 创建`backend/requirements.txt`
- 写入核心依赖：fastapi、uvicorn、sqlalchemy、python-dotenv、httpx、aiofiles
- `pip install -r requirements.txt`
- 验证：创建最小FastAPI应用可启动

#### 0.2.5 建立API契约文档
- 创建`docs/api-contract.md`
- 定义前后端之间所有WebSocket消息类型（JSON Schema）
- 定义所有REST API端点签名
- 这是角色A和角色B可以并行的关键契约

---

## Phase 1：三域并行开发

> 三个角色在Phase 0完成后立即并行启动
> 共享契约：`docs/api-contract.md`

---

### 角色A工作包：后端核心引擎 + 数据层 + API体系

#### A-01：数据层完整实现

##### A-01-1 数据库模型定义（SQLAlchemy ORM）

###### A-01-1-1 任务进度表（Task）
- 字段：id（主键UUID）、role（角色名）、issued_by（下发角色）、receipt_by（回执角色）
- 字段：platform（平台）、model（模型名）、task_type（1=分配/2=执行/3=审查）
- 字段：token_used（token数量）、duration_ms（耗时毫秒）、detail（详情JSON文本）
- 字段：remark（备注）、exec_status（1=等待/2=执行中/3=执行完成）
- 字段：review_status（1=等待/2=审查中/3=审查通过/4=审查不通过）
- 字段：created_at（创建时间ISO8601）、updated_at（更新时间ISO8601）
- 所有时间字段使用UTC存储

###### A-01-1-2 数据库初始化逻辑
- 应用启动时自动`create_all()`
- 数据库文件不存在时自动创建
- 数据库文件存在时保留数据（不覆盖）

###### A-01-1-3 数据访问层（Repository Pattern）
- `TaskRepository`类：封装所有数据库操作
- 方法列表：`create_task()`、`get_task(id)`、`update_task(id, **fields)`、`list_tasks(filters)`、`delete_task(id)`
- 所有方法使用async/await
- 统一错误处理：数据库异常转换为应用层异常

##### A-01-2 plan.json读写模块

###### A-01-2-1 PlanManager类
- `load_plan()`：读取plan.json，不存在返回空结构
- `save_plan(plan_data)`：原子写入（先写.tmp文件再rename）
- `update_task_in_plan(task_id, status)`：更新单个任务状态
- `get_outline()`：返回三级大纲结构

###### A-01-2-2 plan.json数据结构定义
```json
{
  "version": 1,
  "created_at": "ISO8601",
  "updated_at": "ISO8601",
  "title": "项目标题",
  "stages": [
    {
      "id": "stage_001",
      "title": "阶段标题",
      "status": "pending|executing|done",
      "children": [
        {
          "id": "task_001",
          "title": "任务标题",
          "task_db_id": "uuid",
          "status": "pending|executing|done|failed",
          "children": []
        }
      ]
    }
  ]
}
```

##### A-01-3 配置读取模块（EnvConfig）

###### A-01-3-1 EnvConfig类设计
- 每次调用属性时实时从.env重新读取（禁止任何缓存）
- 使用python-dotenv的`load_dotenv(override=True)`实现
- 提供类型安全的属性：`timeout_seconds`、`retry_count`、`models`、`roles`、`executors`

###### A-01-3-2 .env解析规则
- 模型池：以`MODEL_`前缀的配置块，支持多个模型
- 角色配置：以`ROLE_`前缀的配置块
- 执行体配置：以`EXECUTOR_`前缀的配置块
- 邮件配置：`EMAIL_`前缀

###### A-01-3-3 配置热更新通知
- 使用watchdog库监听.env文件变化
- 变化时通过WebSocket广播`config_changed`事件
- 前端收到后刷新对应面板

#### A-02：模型调用引擎

##### A-02-1 ModelClient抽象层

###### A-02-1-1 BaseModelClient接口定义
```python
class BaseModelClient:
    async def chat(self, messages: list, **kwargs) -> ChatResponse
    async def stream_chat(self, messages: list, **kwargs) -> AsyncGenerator
    async def check_quota(self) -> QuotaStatus
```

###### A-02-1-2 OpenAICompatibleClient实现
- 支持base_url自定义（兼容所有OpenAI格式API）
- 支持http_proxy/https_proxy配置
- 超时：从EnvConfig实时读取
- 重试：指数退避，从EnvConfig读取重试次数

###### A-02-1-3 模型Fallback路由器（ModelRouter）
- 输入：bind_model_name列表（有序）
- 逻辑：依次尝试列表中的模型，失败（超时/额度不足/错误）则切换下一个
- 额度不足时触发邮件通知（异步，不阻塞主流程）
- 所有模型均失败时抛出`AllModelsExhaustedError`
- 记录每次调用的模型名、token数、耗时到Task表

##### A-02-2 角色管理器（RoleManager）

###### A-02-2-1 Role数据类
- name、system_prompt、bind_model_name列表
- 从.env实时加载（每次获取角色时重读）

###### A-02-2-2 RoleManager类
- `get_role(name)`：按名称获取角色配置
- `list_roles()`：列出所有配置的角色
- `assign_task(role_name, task_content)`：创建任务记录并调度

#### A-03：任务执行引擎

##### A-03-1 TaskExecutor核心

###### A-03-1-1 执行流水线设计
```
接收任务
    ↓
创建Task记录（exec_status=1等待）
    ↓
选择角色 → 选择模型（ModelRouter）
    ↓
更新Task记录（exec_status=2执行中）
    ↓
调用模型（支持流式输出）
    ↓
结果写入Task.detail
    ↓
更新Task记录（exec_status=3执行完成）
    ↓
触发审查流程（task_type=3）
    ↓
更新review_status
    ↓
WebSocket广播进度事件
```

###### A-03-1-2 异步任务队列
- 使用asyncio.Queue管理待执行任务
- 支持并发执行多个任务（可配置并发数）
- 任务优先级：Manager任务 > 执行任务 > 审查任务

###### A-03-1-3 审查子流程
- 执行任务完成后自动触发审查角色
- 审查角色读取执行结果，输出通过/不通过+原因
- 不通过时更新review_status=4，触发REWORK回路
- REWORK：重新创建执行任务，携带审查意见

##### A-03-2 Manager初始化流程

###### A-03-2-1 10步初始化序列（与网页控制端对应）
- Step 1：接收指令（解析用户输入的项目需求）
- Step 2：分析需求（Manager角色调用模型分析）
- Step 3：初始化Manager（加载Manager角色配置）
- Step 4：建立项目主体计划（生成三级大纲，写入plan.json）
- Step 5：确认创建模型库（验证所有配置的模型可用）
- Step 6：确认创建角色库（加载所有角色配置）
- Step 7：确认创建执行体（初始化所有执行体）
- Step 8：确认创建工具库（加载MCP/Skills配置）
- Step 9：确认创建提示词（编译所有角色系统提示词）
- Step 10：一切就绪，等待启动确认
- 每步完成后通过WebSocket广播进度事件

#### A-04：REST API + WebSocket端点

##### A-04-1 REST API路由

###### A-04-1-1 配置类API
- `GET /api/config/models` - 获取所有模型配置
- `PUT /api/config/models/{name}` - 更新模型配置（写入.env）
- `GET /api/config/roles` - 获取所有角色配置
- `PUT /api/config/roles/{name}` - 更新角色配置
- `GET /api/config/executors` - 获取所有执行体配置
- `PUT /api/config/executors/{name}` - 更新执行体配置
- `GET /api/config/settings` - 获取超时/重试等全局设置
- `PUT /api/config/settings` - 更新全局设置
- `GET /api/config/notifications` - 获取邮件通知配置
- `PUT /api/config/notifications` - 更新邮件通知配置

###### A-04-1-2 任务类API
- `GET /api/tasks` - 查询任务列表（支持过滤：status、type、role、分页）
- `GET /api/tasks/{id}` - 获取任务详情
- `POST /api/tasks` - 手动创建任务（供CLI/Hermes调用）
- `GET /api/plan` - 获取当前plan.json内容
- `POST /api/plan/sync` - 手动触发plan同步

###### A-04-1-3 控制类API
- `POST /api/control/start` - 启动执行（每步确认模式下的确认）
- `POST /api/control/pause` - 暂停执行
- `POST /api/control/stop` - 停止执行
- `POST /api/control/mode` - 切换执行模式（每步确认/自动执行）
- `POST /api/hermes/invoke` - Hermes入口端点

###### A-04-1-4 认证API
- `POST /api/auth/unlock` - 输入项目名解锁（返回session token，有效期1小时）
- `POST /api/auth/lock` - 手动锁定
- `GET /api/auth/status` - 查询锁定状态

##### A-04-2 WebSocket通信协议

###### A-04-2-1 连接建立
- 端点：`ws://localhost:PORT/ws`
- 连接后服务端立即推送当前状态快照

###### A-04-2-2 服务端→客户端消息类型
```json
// 进度更新
{"type": "progress", "step": 3, "total": 10, "message": "正在准备...3.初始化Manager", "status": "executing"}

// 任务状态变更
{"type": "task_update", "task_id": "uuid", "exec_status": 2, "review_status": 1}

// plan变更
{"type": "plan_update", "plan": {...}}

// 对话消息（Manager回复）
{"type": "chat_message", "role": "manager", "content": "已收到您的意见...", "timestamp": "ISO8601"}

// 流式输出片段
{"type": "stream_chunk", "task_id": "uuid", "chunk": "生成的文字片段"}

// 配置变更通知
{"type": "config_changed", "section": "models"}

// 系统通知
{"type": "notification", "level": "info|warn|error", "message": "..."}
```

###### A-04-2-3 客户端→服务端消息类型
```json
// 用户对话输入
{"type": "chat", "content": "用户输入的意见或确认"}

// 执行模式切换
{"type": "set_mode", "mode": "step|auto"}

// 确认当前步骤
{"type": "confirm_step"}
```

#### A-05：邮件通知服务

##### A-05-1 EmailNotifier类

###### A-05-1-1 基础发送能力
- 使用smtplib.SMTP_SSL
- 配置从EnvConfig实时读取（每次发送前重读，防止配置变更失效）
- 异步包装（使用asyncio.run_in_executor，不阻塞主线程）

###### A-05-1-2 触发条件实现（4个默认+可拓展）
- 触发1：任务开始时（默认关闭）→ TaskExecutor在exec_status变为2时检查
- 触发2：任务结束时（默认开启）→ TaskExecutor在exec_status变为3时触发
- 触发3：Manager模型额度不够时（默认开启）→ ModelRouter在AllModelsExhaustedError且角色=Manager时触发
- 触发4：执行角色模型额度不够时（默认开启）→ ModelRouter在AllModelsExhaustedError且角色≠Manager时触发
- 触发5（拓展）：审查不通过时（默认关闭）→ 审查子流程在review_status=4时触发
- 触发6（拓展）：REWORK超过N次时（默认开启，N=3）→ REWORK计数器超限时触发
- 触发7（拓展）：执行超时时（默认开启）→ asyncio.wait_for超时时触发

---

### 角色B工作包：网页控制端完整实现

#### B-01：前端工程基础设施

##### B-01-1 项目配置

###### B-01-1-1 Vite配置
- 开发代理：`/api` → `http://localhost:8000`（后端FastAPI）
- WebSocket代理：`/ws` → `ws://localhost:8000`
- 构建输出：`../backend/static/`（由FastAPI静态托管）

###### B-01-1-2 TypeScript类型定义
- 创建`src/types/index.ts`
- 定义所有WebSocket消息类型（与api-contract.md保持一致）
- 定义Task、Plan、Model、Role、Executor、Settings等核心类型

###### B-01-1-3 全局状态管理（Pinia）
- `useConnectionStore`：WebSocket连接状态
- `useProgressStore`：10步初始化进度
- `usePlanStore`：三级大纲数据
- `useTaskStore`：任务列表
- `useChatStore`：对话历史
- `useAuthStore`：认证/锁屏状态
- `useConfigStore`：所有配置（模型/角色/执行体/设置/通知）
- `useExecutionStore`：执行模式（每步确认/自动执行）

###### B-01-1-4 WebSocket客户端封装
- 创建`src/composables/useWebSocket.ts`
- 自动重连（指数退避，最大5次）
- 消息分发器（type→handler映射）
- 连接状态响应式绑定（useConnectionStore）

#### B-02：设计系统（深色科技风）

##### B-02-1 CSS设计令牌

###### B-02-1-1 颜色系统
```css
/* 背景层级 */
--bg-base: #0a0e1a;        /* 最底层背景 */
--bg-surface: #0f1525;      /* 面板背景 */
--bg-elevated: #161d2e;     /* 浮层背景 */
--bg-hover: #1e2840;        /* 悬停背景 */

/* 强调色 */
--accent-cyan: #00d4ff;     /* 主强调（青碧色，当前位置） */
--accent-green: #00ff88;    /* 完成状态 */
--accent-red: #ff4466;      /* 未完成/错误状态 */
--accent-yellow: #ffb800;   /* 警告状态 */

/* 文字 */
--text-primary: #e8f0ff;    /* 主文字 */
--text-secondary: #7a8ab0;  /* 次要文字 */
--text-muted: #3d4d6e;      /* 淡文字 */

/* 边框 */
--border-subtle: #1e2840;   /* 细边框 */
--border-active: #00d4ff33; /* 激活边框（带透明度） */
```

###### B-02-1-2 间距与圆角
- 使用4px为基础单位的间距系统
- 圆角：4px（小）、8px（中）、12px（大）

###### B-02-1-3 字体
- 代码/数据：Fira Code、JetBrains Mono（等宽）
- 界面文字：Inter、system-ui（无衬线）

##### B-02-2 基础组件库

###### B-02-2-1 必须实现的基础组件
- `StatusBadge.vue`：状态徽章（等待/执行中/完成/失败）
- `ProgressRing.vue`：空心圆进度（右侧进度条用）
- `Collapsible.vue`：可折叠容器（总览历史步骤用）
- `ResizablePanel.vue`：可拖拽宽度面板（左右菜单栏用）
- `ChatBubble.vue`：对话气泡
- `StreamText.vue`：流式文字渲染（逐字显示）
- `FormInput.vue`、`FormSelect.vue`、`FormToggle.vue`：表单基础组件
- `Modal.vue`：弹窗容器
- `Tooltip.vue`：悬停提示
- `LoadingSpinner.vue`：加载动画

#### B-03：布局骨架

##### B-03-1 整体布局（AppLayout.vue）

###### B-03-1-1 布局结构
```
┌─────────────────────────────────────────┐
│  顶部栏（TopBar）                         │
├────┬────────────────────────────────┬───┤
│ 左 │                                │ 右 │
│ 侧 │       主内容区                   │ 侧 │
│ 菜 │    （RouterView）               │ 进 │
│ 单 │                                │ 度 │
│ 栏 │                                │ 条 │
└────┴────────────────────────────────┴───┘
```

###### B-03-1-2 顶部栏（TopBar.vue）
- 左侧：Logo + 项目名称
- 右侧：锁定按钮 + 设置按钮（点击展开设置表单下拉）
- 高度固定48px
- 背景：--bg-elevated，底部1px边框

###### B-03-1-3 左侧菜单栏（SideNav.vue）
- 可展开/收起（图标模式/完整模式）
- 可左右拖拽调整宽度（最小48px，最大280px）
- 一级菜单项（7个）：总览、对话、模型、角色、执行体、拓展、消息
- 每项支持展开二级/三级子菜单
- 当前激活项高亮（左侧3px青碧色竖线）
- 折叠时显示图标（SVG图标，每个菜单项一个）

###### B-03-1-4 右侧进度条（ProgressPanel.vue）
- 默认折叠（收起状态）
- 折叠态：一列空心圆，完成=绿色实心，未完成=红色空心，当前=青碧色（更大，中间显示百分比）
- 展开态：显示任务名称 + 状态
- 可拖拽调整宽度
- 数据来源：usePlanStore（三级大纲）

#### B-04：七大页面完整实现

##### B-04-1 总览页（OverviewPage.vue）

###### B-04-1-1 执行模式切换
- 右上角：「每步确认」/「自动执行」切换按钮
- 状态存储在useExecutionStore
- 切换时调用`POST /api/control/mode`

###### B-04-1-2 动态信息面板
- 主体区域：当前正在执行的步骤（全屏展示）
- 历史步骤：折叠到顶部（Collapsible组件），点击展开
- 支持鼠标滚轮上下滑动浏览历史
- 实时接收WebSocket的`progress`类型消息更新

###### B-04-1-3 10步初始化展示
- 每步显示：序号、名称、当前/总数、状态图标
- 当前步骤：完整展示，带动画光标
- 已完成步骤：折叠，仅显示标题+绿色✓
- 未开始步骤：灰色，显示序号

###### B-04-1-4 每步确认模式下的输入框
- 仅在`每步确认`模式下显示（底部固定）
- 输入框：多行，支持Enter发送，Shift+Enter换行
- 按钮：确认（发送confirm_step）+ 发送意见（发送chat消息）
- 底部显示当前等待确认的提示

##### B-04-2 对话页（ChatPage.vue）

###### B-04-2-1 对话界面
- 消息列表（ScrollView，自动滚动到最新）
- 支持两种消息来源：用户（右侧气泡）、Manager（左侧气泡，带角色名和模型名标注）
- 流式输出：Manager回复逐字显示（StreamText组件）
- 时间戳显示（相对时间，悬停显示绝对时间）

###### B-04-2-2 输入区域
- 底部固定输入框
- 多行文本（最高6行自动扩展）
- Enter发送，Shift+Enter换行
- 发送时禁用（等待回复），显示加载状态

###### B-04-2-3 程序未运行时的状态
- 显示提示：「程序未运行时，对话不可用」
- 基于useExecutionStore判断

##### B-04-3 模型页（ModelsPage.vue）

###### B-04-3-1 模型列表
- 卡片列表展示所有模型
- 每个卡片显示：name、level（优先级徽章）、model_id、base_url（截断显示）
- 状态指示：是否可用（需要发送测试请求）
- 排序：按level从高到低

###### B-04-3-2 模型详情/编辑表单
- 点击卡片展开编辑表单（右侧抽屉或行内展开）
- 字段：name、level（数字输入）、base_url、model_id、api_key（密码框，点击显示）、http_proxy、https_proxy
- 保存：`PUT /api/config/models/{name}`（实时写入.env）
- 测试连接按钮：发送测试请求，显示延迟和结果
- 删除按钮：带确认弹窗

###### B-04-3-3 新增模型
- 顶部「+ 新增模型」按钮
- 展开空白表单

##### B-04-4 角色页（RolesPage.vue）

###### B-04-4-1 角色列表
- 卡片展示6个默认角色
- 每个卡片：角色名、绑定模型列表（带Fallback箭头可视化）、系统提示词预览（首行）

###### B-04-4-2 角色编辑
- role_name输入
- system_prompt：大文本域（代码风格等宽字体）
- bind_model_name：可拖拽排序的模型列表（第一个不通切第二个，顺序即优先级）
- 保存：写入.env

##### B-04-5 执行体页（ExecutorsPage.vue）

###### B-04-5-1 执行体列表
- 展示所有配置的执行体
- 每个执行体：名称、启动命令、当前状态（运行中/停止）

###### B-04-5-2 执行体编辑
- 名称、启动命令（命令行文本框）
- 默认启动命令说明（来自.env.example的注释）

##### B-04-6 拓展页（ExtensionsPage.vue）

###### B-04-6-1 Skills配置
- 列表展示已配置的Skills
- 支持启用/禁用开关

###### B-04-6-2 MCP配置
- JSON格式编辑器（代码风格）
- 验证JSON格式有效性

##### B-04-7 消息页（NotificationsPage.vue）

###### B-04-7-1 邮箱配置区域
- 发件人邮箱、授权码（密码框）、SMTP服务器、端口
- 收件人邮箱
- 「发送测试邮件」按钮
- 数据从.env读取，保存写入.env

###### B-04-7-2 触发条件配置
- 列表展示所有触发条件（7项）
- 每项：说明文字 + 开关（Toggle组件）
- 开关状态实时保存到.env

#### B-05：锁屏与设置

##### B-05-1 锁屏页（LockScreen.vue）

###### B-05-1-1 锁屏界面
- 全屏遮罩（深色模糊背景）
- 居中卡片：项目名输入框 + 解锁按钮
- 输入框placeholder：「输入项目名以解锁」
- 错误提示：项目名不匹配时显示红色错误文字
- 解锁后：调用`POST /api/auth/unlock`，成功则隐藏遮罩

###### B-05-1-2 自动锁定
- 使用sessionStorage存储token和过期时间
- 每次页面操作刷新有效期
- 过期后自动显示锁屏页
- 顶部栏锁定按钮：立即触发锁定

##### B-05-2 设置面板（SettingsPanel.vue）

###### B-05-2-1 下拉展开式设置
- 点击顶部栏设置按钮展开
- 点击外部或再次点击收起

###### B-05-2-2 设置项
- 请求超时时间（数字输入，单位秒，范围1-300）
- 请求重试次数（数字输入，范围0-10）
- 执行模式（每步确认/自动执行，同总览页切换按钮联动）
- 有效期时长（数字输入，单位分钟，默认60）
- 主题色调（预设几个色调可选，未来拓展）
- 保存按钮（`PUT /api/config/settings`）

---

### 角色C工作包：启动层 + 配置体系 + 执行体调度

#### C-01：CLI引导启动模块

##### C-01-1 CLI入口（cli/main.py）

###### C-01-1-1 CLI框架选型
- 使用`click`库（成熟、交互友好）
- 入口命令：`python -m executor` 或 `executor`（通过setup.py配置）

###### C-01-1-2 引导启动流程（Interactive Mode）

步骤1：欢迎界面
- ASCII艺术Logo（Hermes Executor）
- 版本号
- 清屏后显示

步骤2：检查.env文件
- 若不存在：提示「未检测到.env，将从.env.example复制」
- 执行复制：`shutil.copy('.env.example', '.env')`
- 若存在：提示「检测到已有.env，是否重新初始化？[y/N]」

步骤3：基础信息配置
- 交互式输入：项目名称（将写入.env的PROJECT_NAME）
- 交互式输入：后端监听端口（默认8000）
- 交互式输入：前端端口（默认3000）

步骤4：模型配置引导
- 展示当前.env中已有的模型配置
- 询问「是否修改模型配置？[y/N]」
- 若是：引导用户逐项输入（或提示「可在网页控制端配置」）

步骤5：启动确认
- 展示配置摘要
- 确认启动：「一切就绪，是否启动？[Y/n]」

步骤6：启动服务
- 调用启动函数（同方式二的启动逻辑）
- 打开浏览器：`webbrowser.open(f'http://localhost:{port}')`
- 进入日志输出模式

###### C-01-1-3 CLI命令列表
```
executor start          # 引导式启动（默认）
executor start --no-gui # 不打开浏览器
executor start --port 8080  # 指定端口
executor status         # 查看运行状态
executor stop           # 停止服务
executor config show    # 展示当前配置
executor config reset   # 重置.env（从.env.example重新复制）
executor logs           # 查看日志
executor version        # 查看版本
```

#### C-02：Hermes直接启动模块

##### C-02-1 Hermes接入端点

###### C-02-1-1 /api/hermes/invoke端点设计
- HTTP POST
- 请求体（JSON）：
```json
{
  "instruction": "创建一个TODO应用，包含前端Vue3和后端FastAPI",
  "mode": "auto|step",
  "project_name": "todo-app",
  "callback_url": "http://..." // 可选，完成后回调
}
```
- 响应（立即返回）：
```json
{
  "session_id": "uuid",
  "status": "accepted",
  "websocket_url": "ws://localhost:8000/ws",
  "dashboard_url": "http://localhost:8000"
}
```
- 异步执行：接受请求后立即返回，后台启动执行流程

###### C-02-1-2 Hermes Agent格式兼容
- 支持标准OpenAI Function Call格式的调用
- 支持纯文本指令格式
- 支持携带上下文（previous_tasks字段）

#### C-03：启动协调器（AppOrchestrator）

##### C-03-1 统一启动逻辑

###### C-03-1-1 AppOrchestrator类
- 无论CLI还是Hermes启动，最终都调用此类
- `startup(instruction, mode, project_name)`方法
- 职责：初始化所有服务 → 启动WebSocket服务 → 启动Manager → 广播进度

###### C-03-1-2 服务启动顺序
```
1. 加载EnvConfig（验证.env存在且有效）
2. 初始化数据库（创建表）
3. 启动FastAPI应用（uvicorn，后台线程）
4. 建立WebSocket服务
5. 启动文件监听（watchdog监听.env）
6. 通知调用者（CLI打印URL，Hermes返回response）
7. 等待10步初始化完成
8. 进入主执行循环
```

###### C-03-1-3 优雅关闭
- 捕获SIGINT、SIGTERM信号
- 关闭前：等待当前执行任务完成（超时30秒）
- 保存所有状态到数据库
- 广播`shutdown`事件到前端

#### C-04：执行体调度器（ExecutorDispatcher）

##### C-04-1 执行体抽象层

###### C-04-1-1 BaseExecutor接口
```python
class BaseExecutor:
    name: str
    start_command: str
    
    async def invoke(self, task: Task, context: dict) -> ExecutorResult
    async def check_available(self) -> bool
    async def terminate(self)
```

###### C-04-1-2 SubprocessExecutor实现
- 适用于claudecode、opencode等命令行工具
- 通过subprocess启动，通过stdin/stdout通信
- 支持配置启动命令（从.env读取）
- 超时控制

###### C-04-1-3 HermesSubAgentExecutor实现
- 适用于hermes子agent
- 通过HTTP调用（携带任务内容和上下文）
- 接收流式结果

###### C-04-1-4 执行体选择策略
- 根据Task的task_type选择合适的执行体
- 支持轮询（多个相同类型执行体负载均衡）
- 执行体不可用时自动切换

#### C-05：MCP/Skills集成

##### C-05-1 拓展加载器

###### C-05-1-1 SkillLoader
- 从配置读取skills列表
- 动态加载skill模块（Python模块或外部脚本）
- 提供skill调用接口给TaskExecutor

###### C-05-1-2 MCPClient
- 读取MCP配置（JSON格式）
- 建立MCP协议连接
- 提供工具调用接口

---

## Phase 2：集成与联调

> 依赖：Phase 1三个工作包全部PASS
> 执行者：角色C主导，角色A/B配合

### INTG-01：前后端WebSocket联调

#### INTG-01-1 消息类型全覆盖测试
- 逐一测试所有WebSocket消息类型
- 验证前端对每种消息的处理逻辑
- 验证数据格式与api-contract.md一致

#### INTG-01-2 断线重连测试
- 模拟后端重启
- 验证前端自动重连
- 验证重连后状态恢复

#### INTG-01-3 并发消息处理
- 模拟多任务同时执行，大量WebSocket消息推送
- 验证前端不丢消息、不乱序

### INTG-02：CLI→后端→前端端到端链路

#### INTG-02-1 完整启动链路测试
- 执行：`executor start`
- 验证：.env检查/复制、端口启动、浏览器打开、WebSocket连接建立
- 验证：10步初始化序列在前端正确显示

#### INTG-02-2 每步确认模式测试
- 切换到每步确认模式
- 输入用户意见
- 验证Manager接收意见并在对话页显示回复

#### INTG-02-3 自动执行模式测试
- 切换到自动执行模式
- 输入一个简单任务
- 验证全程自动推进，前端实时更新

### INTG-03：Hermes→后端→前端端到端链路

#### INTG-03-1 Hermes调用测试
- 使用curl/httpx发送POST /api/hermes/invoke
- 验证立即返回session_id
- 验证后台启动执行
- 验证WebSocket收到进度更新

### INTG-04：任务执行完整回路测试

#### INTG-04-1 分配→执行→审查→REWORK回路
- 创建一个测试任务
- 验证Task表状态流转：1→2→3
- 验证review_status流转：1→2→3/4
- 审查不通过时验证REWORK任务创建
- 验证plan.json实时更新

#### INTG-04-2 模型Fallback测试
- 故意配置一个无效模型为第一优先
- 验证自动切换到第二个模型
- 验证Task表记录的model字段是实际使用的模型

---

## Phase 3：容错、通知与完善

> 并行执行：角色A负责后端容错完善，角色B负责前端异常体验，角色C负责通知体系测试

### A-06：后端容错完善

#### A-06-1 全局异常处理
- FastAPI全局异常处理器
- 所有未捕获异常转换为标准ErrorResponse
- WebSocket异常不断连，转换为error类型消息

#### A-06-2 数据库事务保证
- 关键状态更新使用数据库事务
- 防止exec_status和review_status不一致

#### A-06-3 任务超时保护
- asyncio.wait_for对每个任务设置最大执行时间
- 超时后更新状态为failed
- 触发通知（如果配置了超时通知）

### B-06：前端异常体验

#### B-06-1 加载状态全覆盖
- 所有API请求期间显示骨架屏或加载指示器
- 防止用户在加载中重复操作

#### B-06-2 错误反馈设计
- 全局Toast通知（右上角）：info/warn/error三级
- 表单验证错误：字段级红色提示
- 网络断开提示：顶部黄色横幅

#### B-06-3 空状态设计
- 每个列表页面的空状态（无数据时的友好提示）
- 首次使用引导（模型未配置时的提示）

### C-06：通知体系完整测试

#### C-06-1 邮件发送测试
- 测试邮件发送是否正常（使用消息页的「发送测试邮件」）
- 测试每个触发条件是否正确触发

#### C-06-2 通知幂等性
- 同一事件只发一次通知（防止重复发送）
- 使用Redis或内存Set记录已发送通知的事件ID

---

## Phase 4：端到端验收与交付

### VAL-01：完整业务流程验收

#### VAL-01-1 场景一：CLI引导启动，每步确认模式
- 全程记录截图/录屏
- 验收每个UI细节（深色科技风、动画效果）
- 验收所有WebSocket消息的前端展示

#### VAL-01-2 场景二：Hermes直接启动，自动执行模式
- 通过API调用启动
- 全程自动执行，人工不介入
- 验收最终plan.json和Task表数据完整性

#### VAL-01-3 场景三：异常恢复
- 模拟模型API超时
- 模拟数据库文件损坏（删除后重新创建）
- 模拟网络中断后重连

### VAL-02：性能基线

#### VAL-02-1 WebSocket消息延迟
- 后端状态更新到前端显示的延迟 < 100ms

#### VAL-02-2 页面加载时间
- 首屏加载 < 2秒（本地）

#### VAL-02-3 并发任务
- 同时执行5个任务，系统无明显卡顿

### VAL-03：交付物清单

#### VAL-03-1 代码
- 完整源代码，所有文件有注释
- .env.example（完整，所有字段带说明）

#### VAL-03-2 文档
- README.md（安装、启动、使用说明）
- docs/api-contract.md（最终版）
- docs/architecture.md（架构说明图）

#### VAL-03-3 验收报告
- 所有场景的测试结果
- 已知问题和限制

---

## 全局约束与注意事项

### 文件修改边界

| 角色A负责 | 角色B负责 | 角色C负责 |
|---|---|---|
| backend/core/ | frontend/src/ | cli/ |
| backend/api/ | frontend/public/ | backend/hermes/ |
| backend/db/ | frontend/index.html | backend/orchestrator/ |
| backend/services/ | frontend/vite.config.ts | backend/executors/ |
| backend/models/ | | .env.example |

### 共享区域（需要协调）
- `docs/api-contract.md`：A和B的通信契约，任何修改需双方确认
- `backend/main.py`：A负责编写，C负责添加hermes路由，需要协调不同时修改
- `.env.example`：C负责，但A/B发现缺少字段需及时沟通

### 技术债务预防
- 禁止任何角色使用`time.sleep()`替代`asyncio.sleep()`
- 禁止同步IO操作在async函数中（使用aiofiles）
- 禁止硬编码端口、路径、密钥（全部通过EnvConfig读取）
- 禁止前端hardcode后端URL（全部通过Vite代理或env变量）

```

---

# 项目目录结构

```
hermes-executor/
│
├── .env.example                    # 配置模板，禁止程序写入，人工维护
├── .env                            # 运行时配置，从.env.example复制，实时读取
├── .gitignore                      # 排除.env、*.db、__pycache__、dist等
├── README.md                       # 项目说明、安装、启动文档
├── plan.json                       # 三级大纲任务树，实时同步，原子写入
│
├── docs/                           # 项目文档
│   ├── api-contract.md             # 前后端WebSocket+REST API契约（A/B共享）
│   ├── architecture.md             # 架构说明与组件关系图
│   ├── hermes.md                   # Hermes接入协议说明
│   └── tech-stack.md               # 技术选型说明
│
├── data/                           # 运行时数据目录（gitignore）
│   └── executor.db                 # SQLite数据库，任务进度表
│
│
├── backend/                        # 后端（FastAPI + Python 3.11+）
│   ├── main.py                     # FastAPI应用入口，挂载所有路由和中间件
│   ├── requirements.txt            # Python依赖：fastapi uvicorn sqlalchemy python-dotenv httpx aiofiles watchdog click
│   │
│   ├── core/                       # 核心配置与基础设施
│   │   ├── __init__.py
│   │   ├── config.py               # EnvConfig类，实时读取.env，无缓存
│   │   ├── exceptions.py           # 应用层异常定义（AllModelsExhaustedError等）
│   │   ├── events.py               # 应用启动/关闭事件（lifespan）
│   │   └── logging.py              # 日志配置（结构化日志）
│   │
│   ├── db/                         # 数据层
│   │   ├── __init__.py
│   │   ├── database.py             # SQLAlchemy engine、session、Base定义
│   │   ├── models.py               # Task ORM模型，字段完整定义
│   │   └── repository.py           # TaskRepository，封装所有数据库操作
│   │
│   ├── plan/                       # plan.json管理
│   │   ├── __init__.py
│   │   ├── manager.py              # PlanManager，load/save/update，原子写入
│   │   └── schemas.py              # Plan数据结构（Pydantic）
│   │
│   ├── models_pool/                # 模型池与调用引擎
│   │   ├── __init__.py
│   │   ├── base.py                 # BaseModelClient接口定义
│   │   ├── openai_compatible.py    # OpenAICompatibleClient，支持proxy/超时/重试
│   │   └── router.py               # ModelRouter，Fallback链式路由逻辑
│   │
│   ├── roles/                      # 角色管理
│   │   ├── __init__.py
│   │   └── manager.py              # RoleManager，从.env加载角色，实时读取
│   │
│   ├── tasks/                      # 任务执行引擎
│   │   ├── __init__.py
│   │   ├── executor.py             # TaskExecutor，执行流水线，asyncio.Queue
│   │   ├── reviewer.py             # 审查子流程，触发REWORK
│   │   └── schemas.py              # Task相关Pydantic Schema（请求/响应）
│   │
│   ├── services/                   # 业务服务层
│   │   ├── __init__.py
│   │   ├── notification.py         # EmailNotifier，7种触发条件，异步发送
│   │   ├── file_watcher.py         # watchdog监听.env变化，广播config_changed
│   │   └── session.py              # 锁屏Session管理，1小时有效期
│   │
│   ├── executors/                  # 执行体调度器
│   │   ├── __init__.py
│   │   ├── base.py                 # BaseExecutor接口
│   │   ├── subprocess_executor.py  # SubprocessExecutor，命令行工具调用
│   │   ├── hermes_agent.py         # HermesSubAgentExecutor，HTTP调用子agent
│   │   └── dispatcher.py           # ExecutorDispatcher，选择策略与负载均衡
│   │
│   ├── extensions/                 # 拓展（MCP/Skills）
│   │   ├── __init__.py
│   │   ├── skill_loader.py         # SkillLoader，动态加载skill模块
│   │   └── mcp_client.py           # MCPClient，MCP协议连接与工具调用
│   │
│   ├── orchestrator/               # 启动协调器
│   │   ├── __init__.py
│   │   └── app.py                  # AppOrchestrator，统一启动逻辑，10步初始化
│   │
│   ├── hermes/                     # Hermes接入层
│   │   ├── __init__.py
│   │   ├── router.py               # /api/hermes/invoke 端点
│   │   └── schemas.py              # Hermes请求/响应Schema
│   │
│   ├── api/                        # REST API路由层
│   │   ├── __init__.py
│   │   ├── auth.py                 # /api/auth/* 认证端点
│   │   ├── config.py               # /api/config/* 配置读写端点
│   │   ├── tasks.py                # /api/tasks/* 任务查询端点
│   │   ├── control.py              # /api/control/* 执行控制端点
│   │   └── websocket.py            # /ws WebSocket端点，消息分发
│   │
│   └── static/                     # 前端构建产物（由Vite build输出到此）
│       └── index.html              # 前端入口（构建后）
│
│
├── frontend/                       # 前端（Vue 3 + Vite + TypeScript）
│   ├── index.html                  # 前端HTML入口
│   ├── vite.config.ts              # Vite配置，/api和/ws代理到后端
│   ├── tsconfig.json               # TypeScript配置
│   ├── package.json                # 前端依赖（vue pinia vue-router）
│   │
│   └── src/
│       ├── main.ts                 # Vue应用挂载入口
│       ├── App.vue                 # 根组件，路由出口，锁屏判断
│       ├── router.ts               # 路由配置（7个页面路由）
│       │
│       ├── types/
│       │   └── index.ts            # 所有TypeScript类型定义（Task/Plan/Model/Role/WsMessage等）
│       │
│       ├── stores/                 # Pinia状态管理
│       │   ├── connection.ts       # useConnectionStore，WebSocket连接状态
│       │   ├── progress.ts         # useProgressStore，10步初始化进度
│       │   ├── plan.ts             # usePlanStore，三级大纲数据
│       │   ├── tasks.ts            # useTaskStore，任务列表
│       │   ├── chat.ts             # useChatStore，对话历史
│       │   ├── auth.ts             # useAuthStore，锁屏/Session状态
│       │   ├── config.ts           # useConfigStore，所有配置
│       │   └── execution.ts        # useExecutionStore，执行模式
│       │
│       ├── composables/            # 可复用逻辑
│       │   ├── useWebSocket.ts     # WebSocket客户端，自动重连，消息分发
│       │   ├── useResizable.ts     # 面板宽度拖拽逻辑
│       │   └── useApi.ts           # REST API请求封装（带loading/error状态）
│       │
│       ├── styles/                 # 全局样式
│       │   ├── variables.css       # CSS设计令牌（颜色/间距/字体）
│       │   ├── reset.css           # 全局reset
│       │   └── global.css          # 全局基础样式
│       │
│       ├── components/             # 通用基础组件
│       │   ├── StatusBadge.vue     # 状态徽章（等待/执行中/完成/失败）
│       │   ├── ProgressRing.vue    # 空心圆进度（右侧进度条用）
│       │   ├── Collapsible.vue     # 可折叠容器
│       │   ├── ResizablePanel.vue  # 可拖拽宽度面板
│       │   ├── ChatBubble.vue      # 对话气泡
│       │   ├── StreamText.vue      # 流式文字逐字渲染
│       │   ├── FormInput.vue       # 表单输入框
│       │   ├── FormSelect.vue      # 表单选择框
│       │   ├── FormToggle.vue      # 开关组件
│       │   ├── Modal.vue           # 弹窗容器
│       │   ├── Tooltip.vue         # 悬停提示
│       │   ├── LoadingSpinner.vue  # 加载动画
│       │   └── Toast.vue           # 全局通知（info/warn/error）
│       │
│       ├── layout/                 # 布局组件
│       │   ├── AppLayout.vue       # 整体布局骨架（顶部+左侧+主体+右侧）
│       │   ├── TopBar.vue          # 顶部栏（Logo+锁定+设置按钮）
│       │   ├── SideNav.vue         # 左侧菜单栏（7项，可收起，可拖拽）
│       │   ├── ProgressPanel.vue   # 右侧进度条面板（折叠=空心圆，展开=列表）
│       │   ├── LockScreen.vue      # 全屏锁屏遮罩
│       │   └── SettingsPanel.vue   # 顶部栏设置下拉面板
│       │
│       └── pages/                  # 七大页面
│           ├── OverviewPage.vue    # 总览（动态信息面板+确认输入框）
│           ├── ChatPage.vue        # 对话（与Manager实时交流）
│           ├── ModelsPage.vue      # 模型（卡片列表+编辑表单+测试连接）
│           ├── RolesPage.vue       # 角色（角色卡片+绑定模型拖拽排序）
│           ├── ExecutorsPage.vue   # 执行体（列表+启动命令编辑）
│           ├── ExtensionsPage.vue  # 拓展（Skills开关+MCP JSON编辑器）
│           └── NotificationsPage.vue # 消息（邮箱配置+触发条件开关）
│
│
└── cli/                            # CLI启动层
    ├── __init__.py
    ├── main.py                     # click CLI入口，executor命令定义
    └── wizard.py                   # 交互式引导流程（10步初始化的CLI版本）
```

---

# 并发规划总览

```markdown
# 本轮开发任务总览

## 当前阶段

阶段：Phase 0 → Phase 1 并行启动（项目从零开始）

目标：完成环境奠基后，三角色立即全并行推进核心开发

## 当前项目状态

- 已完成：架构设计（对话中确认）、技术选型（FastAPI+Vue3+SQLite）
- 未完成：所有代码（项目尚未创建）
- 当前风险：前后端WebSocket消息格式若未对齐，Phase 1并行会产生集成冲突
- 当前阻塞：api-contract.md未建立（Phase 1全部依赖此契约，必须Phase 0完成）

## 本轮调度

| 角色 | 状态 | 工作包 | 原因 | 依赖 |
|---|---|---|---|---|
| 角色A（全栈架构师） | EXECUTE | A-01~A-05：后端核心引擎+数据层+API体系 | Phase 0完成后立即并行 | Phase 0（api-contract.md） |
| 角色B（前端工程师） | EXECUTE | B-01~B-05：网页控制端完整实现 | Phase 0完成后立即并行 | Phase 0（api-contract.md） |
| 角色C（集成工程师） | EXECUTE | C-01~C-05：CLI/Hermes启动层+执行体调度 | Phase 0完成后立即并行 | Phase 0（.env.example+骨架） |

## 并行关系

```
Phase 0（串行，角色C主导）
    ├── 建立目录骨架
    ├── 创建.env.example
    ├── 初始化前后端工程
    └── 建立api-contract.md（关键契约）
            ↓ Phase 0完成
┌───────────────────────────────────────┐
│            Phase 1 三角色全并行           │
│  角色A：backend/                        │
│  角色B：frontend/                       │
│  角色C：cli/ + backend/hermes/ + 执行体  │
│                                        │
│  共享契约：docs/api-contract.md          │
│  冲突区域：backend/main.py（协调修改）    │
└───────────────────────────────────────┘
            ↓ Phase 1全部PASS
        Phase 2（集成联调）
            ↓
        Phase 3（容错完善）
            ↓
        Phase 4（验收交付）
```

## 全局注意事项

1. api-contract.md是Phase 1并行的关键前提，Phase 0必须完整定义所有WebSocket消息类型和REST API签名
2. backend/main.py由角色A编写主体，角色C添加hermes路由，双方需通过contract协调，避免同时修改
3. .env实时读取无缓存是硬性要求，任何角色不得在代码中缓存.env读取结果
4. plan.json写入必须使用原子操作（写临时文件再rename），防止执行中途崩溃导致文件损坏
5. 所有邮件发送必须异步（asyncio.run_in_executor），不得阻塞任务执行主流程
6. 前端构建产物输出到backend/static/，由FastAPI静态托管，生产环境无需单独前端服务器
```