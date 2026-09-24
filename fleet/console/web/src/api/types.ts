/**
 * 与 fleet/console/server.py（角色A · CORE-02）及 docs/契约/控制台API.md 严格对齐的类型定义。
 * 字段名一律沿用后端原始拼写（含 tasks[].state、事件行的驼峰 taskId），不做本地重命名。
 */

/* ------------------------------ 通用 ------------------------------ */

export interface ApiError {
  ok: false
  error?: string
  reason?: string
  missing?: string[]
  [key: string]: unknown
}

export interface HealthInfo {
  version: string
  db: boolean
  events: boolean
  config: boolean
}

export interface SessionInfo {
  ok: boolean
  token?: string
  project?: string
  expires_in?: number
}

export interface ProjectItem {
  id: string
  name: string
  path: string
  port: number | null
}

/* ------------------------------ 计划 ------------------------------ */

export interface PlanStageTask {
  子任务: string
  task_id: string | null
}

export interface PlanStage {
  名称: string
  任务: PlanStageTask[]
}

/** 任务状态（docs/契约/任务状态机.md，10 态冻结） */
export type TaskState =
  | 'DRAFT'
  | 'ASSIGNED'
  | 'DOING'
  | 'SUBMITTED'
  | 'REVIEWING'
  | 'DONE'
  | 'PARTIAL'
  | 'REWORK'
  | 'BLOCKED'
  | 'ESCALATED'

/** 审查状态（docs/契约/任务进度表字段.md §4，6 值冻结） */
export type ReviewStatus = 'PENDING' | 'REVIEWING' | 'PASS' | 'PARTIAL' | 'REWORK' | 'BLOCKED'

export interface PlanTask {
  id: string
  title: string
  state: TaskState | string
  assignee: string
  reviewer: string
  verify_cmd?: string
  task_type: number
  review_status: ReviewStatus | string
  stage: string
  subtask: string
  rework_count: number
  updated_at: string
  [key: string]: unknown
}

/** 进度树叶子（任务）：weight_pct 为该任务在其阶段内的份额占比说明，
 *  contrib_pct 为对项目总进度的贡献（全部叶子 contrib 之和恒 = 100） */
export interface ProgressTaskNode {
  id: string
  subtask: string
  weight_pct: number
  contrib_pct: number
  state: string
  done: boolean
}

/** 进度树节点（阶段）：virtual=「未归入计划」虚拟阶段 */
export interface ProgressStageNode {
  name: string
  virtual: boolean
  weight_pct: number
  contrib_pct: number
  total: number
  done: number
  tasks: ProgressTaskNode[]
}

export interface ProgressInfo {
  project?: string
  total: number
  done: number
  percent: number
  /** equal=未配置权重（与旧版等权口径一致）；weighted=存在显式权重 */
  mode?: 'equal' | 'weighted' | string
  stages?: ProgressStageNode[]
}

export interface PlanSnapshot {
  ok: boolean
  project: string
  name?: string
  updated_at?: string
  run_started_at?: string
  /** plan.json 是否已生成（需求2：区分「没指定」与「没刷新出来」） */
  plan_exists?: boolean
  阶段: PlanStage[]
  tasks: PlanTask[]
  progress: ProgressInfo
  total: number
  done: number
  percent: number
  reason?: string
}

/* ------------------------------ 执行体运行时（需求4） ------------------------------ */

export interface RunningExecutor {
  key: string
  pid: number
  process_name: string
  adapter: string
  task_id: string
  role: string
  project: string
  model: string
  cwd: string
  cmd: string[]
  started_at: string
  elapsed_s: number
  alive: boolean
}

/* ------------------------------ 历史任务（需求5） ------------------------------ */

export interface HistoryTaskRow {
  task_id: string
  title: string
  stage: string
  subtask: string
  role: string
  assignee: string
  reviewer: string
  exec_status: string
  review_status: string
  duration_ms: number
  token: number
  model: string
  adapter: string
  rework_count: number
  created_at: string
  updated_at: string
}

/* ------------------------------ 角色工作档案（需求6） ------------------------------ */

export interface RoleProfileTask {
  task_id: string
  title: string
  stage: string
  state: string
  review_status: string
  duration_ms: number
  token: number
  rework_count: number
  updated_at: string
}

export interface RoleProfile {
  role: string
  executed: RoleProfileTask[]
  executed_count: number
  done_count: number
  reviewed: RoleProfileTask[]
  reviewed_count: number
  future: RoleProfileTask[]
  future_count: number
  duration_ms: number
  total_tokens: number
  call_count: number
}

/* ------------------------------ 事件 ------------------------------ */

export interface EventRow {
  seq: number
  timestamp: string
  actor: string
  action: string
  taskId: string | null
  summary: string
  url: string | null
  project?: string | null
  extra?: Record<string, unknown> | null
}

export interface EventsResponse {
  ok: boolean
  project: string
  since: number
  seq: number
  events: EventRow[]
}

/* ------------------------------ 配置 ------------------------------ */

export interface ModelItem {
  name: string
  level: number
  base_url: string
  model_id: string
  api_key: string
  http_proxy: string
  https_proxy: string
  env_scope?: string
  resolved?: boolean
}

export interface RoleItem {
  name: string
  system_prompt: string
  bind_model_name: string[]
  adapter: string
}

export interface ExecutorItem {
  name: string
  command: string
  timeout: number
}

export interface BasicConfig {
  project_name: string
  console_host: string
  console_port: number
  manager_port: number
  ui_port: number
  allowed_roots: string[]
  default_project: string
  timezone: string
  lock_ttl_minutes: number
}

export interface EmailConfig {
  enabled: boolean
  sender: string
  receiver: string
  host: string
  port: number
  auth_code: string
  use_ssl: boolean
}

export interface NotifyConfig {
  on_task_start: boolean
  on_task_end: boolean
  on_manager_quota: boolean
  on_role_quota: boolean
}

export interface RequestConfig {
  timeout: number
  retry_max: number
  retry_delay: number
}

export type ConfigSectionName =
  | 'basic'
  | 'model_pool'
  | 'roles'
  | 'executors'
  | 'email'
  | 'notify'
  | 'request'

export interface ConfigGetResponse<T = unknown> {
  ok: boolean
  section: string
  data: T
  source: string
  mtime: string | null
}

export interface ConfigPostResponse {
  ok: boolean
  section: string
  applied?: unknown
  ignored?: string[]
  mtime?: string | null
  reason?: string
  error?: string
}

/* ------------------------------ 拓展 / 通知触发 ------------------------------ */

export interface ExtensionRecord {
  skills: string[]
  mcp: string[]
}

export type ExtensionsMap = Record<string, ExtensionRecord>

export interface ExtensionsResponse {
  ok: boolean
  data: ExtensionsMap
  source: string
}

export interface NotifyTriggerItem {
  enabled?: boolean
  default?: boolean
  event_type?: string
  [key: string]: unknown
}

export interface NotifyTriggersResponse {
  ok: boolean
  data: Record<string, NotifyTriggerItem> | NotifyTriggerItem[]
  source: string
}

/* ------------------------------ 调度 / 任务 ------------------------------ */

export type SchedulerMode = 'auto' | 'step'

export interface ModeResponse {
  ok: boolean
  mode: SchedulerMode
  awaiting_confirm?: boolean
}

/* ------------------------------ WebSocket 消息 ------------------------------ */

export interface WsTaskUpdate {
  type: 'task_update'
  event?: EventRow
  taskId?: string
  state?: string
  dispatch?: unknown
}

export interface WsProgress {
  type: 'progress'
  project: string
  total: number
  done: number
  percent: number
}

export interface WsPlanUpdate {
  type: 'plan_update'
  project: string
  plan: PlanSnapshot
}

export interface WsConfigChanged {
  type: 'config_changed'
  section?: string
  mtime?: string | null
}

export interface WsChatMessage {
  type: 'chat_message'
  event?: EventRow
}

export interface WsNotification {
  type: 'notification'
  error?: string
  mode?: SchedulerMode | null
  event?: EventRow
  [key: string]: unknown
}

/**
 * stream_chunk · 增量文本流（UI-03R §9.6）
 *
 * 生产方现状：`fleet/console/server.py` 当前**没有**任何地方广播该类型
 * （grep 全部 broadcast 调用：task_update / progress / plan_update / config_changed /
 *  chat_message / notification / 事件动作映射），P1-A-3 后 dispatcher 已产出 stream_chunk 事件。
 * 故本类型先按契约形状落地，客户端完整实现消费逻辑，并用注入钩子做自动化验证；
 * 角色A 一旦补上生产方，客户端无需改动即可流式渲染。
 */
export interface WsStreamChunk {
  type: 'stream_chunk'
  /** 文本增量（可为空串，仅用于携带 done 标志） */
  delta?: string
  /** 该条消息是否已结束 */
  done?: boolean
  /** 所属消息标识（事件 seq 或服务端 message id） */
  messageId?: string | number | null
  /** 产出角色，如 Manager */
  role?: string
  taskId?: string | null
  [key: string]: unknown
}

/** 兜底：未来新增消息类型时按通用事件处理，不丢弃 */
export interface WsGeneric {
  type: string
  event?: EventRow
  [key: string]: unknown
}

export type WsServerMessage =
  | WsTaskUpdate
  | WsProgress
  | WsPlanUpdate
  | WsConfigChanged
  | WsChatMessage
  | WsNotification
  | WsStreamChunk
  | WsGeneric

export interface WsClientChat {
  type: 'chat'
  project?: string
  message: string
}

export interface WsClientSetMode {
  type: 'set_mode'
  mode: string
  actor?: string
}

export interface WsClientConfirmStep {
  type: 'confirm_step'
  taskId?: string | null
  note?: string
}

export type WsClientMessage = WsClientChat | WsClientSetMode | WsClientConfirmStep

/* ------------------------------ 连接状态 ------------------------------ */

export type ConnectionState = 'connecting' | 'online' | 'reconnecting' | 'offline' | 'polling'

export interface TaskDetail {
  task_id: string
  project_id?: string
  title?: string
  role?: string
  exec_status?: string
  review_status?: string
  rework_count?: number
  blocked_reason?: string
  /** 每步派工的执行体会话 id（SUBMITTED 时由 dispatcher 落库；提取不到为空） */
  executor_session_id?: string | null
  [key: string]: unknown
}
