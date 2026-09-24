/**
 * LLM mock 层（工作包 UI-02 §9.1-3）。
 * 与 docs/契约/控制台API.md 同签名的 REST mock + WS mock，
 * VITE_USE_MOCK=true 时启用，保证不等角色A 即可全速开发。
 * 所有 mock 数据仅存在于内存，页面刷新即复位；不含任何密钥明文。
 */

import type {
  ConfigGetResponse,
  ConfigPostResponse,
  ConfigSectionName,
  EmailConfig,
  EventRow,
  EventsResponse,
  ExecutorItem,
  ExtensionRecord,
  ExtensionsMap,
  ExtensionsResponse,
  HealthInfo,
  ModeResponse,
  ModelItem,
  NotifyConfig,
  NotifyTriggersResponse,
  PlanSnapshot,
  PlanStage,
  PlanTask,
  ProjectItem,
  RequestConfig,
  RoleItem,
  SessionInfo,
  TaskDetail,
  TaskState,
} from '@/api/types'

export const MOCK_PROJECT = 'AideanFleet'

/* ------------------------------ 内存状态 ------------------------------ */

interface MockTaskSeed {
  id: string
  title: string
  stage: string
  subtask: string
  state: TaskState
  assignee: string
  reviewer: string
  review: string
  rework: number
}

const TASK_SEEDS: MockTaskSeed[] = [
  { id: 'T-001', title: '写三份契约文件', stage: '阶段0 契约与地基', subtask: '写三份契约文件', state: 'DONE', assignee: 'be-1', reviewer: 'reviewer-1', review: 'PASS', rework: 0 },
  { id: 'T-002', title: '冻结字段与状态机', stage: '阶段0 契约与地基', subtask: '冻结字段与状态机', state: 'DONE', assignee: 'be-1', reviewer: 'reviewer-1', review: 'PASS', rework: 0 },
  { id: 'T-003', title: 'FastAPI+WS 控制台重建', stage: '阶段1 控制面核心', subtask: 'FastAPI+WS 控制台重建', state: 'DONE', assignee: 'be-2', reviewer: 'reviewer-1', review: 'PASS', rework: 1 },
  { id: 'T-004', title: '调度器与返工闭环', stage: '阶段1 控制面核心', subtask: '调度器与返工闭环', state: 'REVIEWING', assignee: 'be-2', reviewer: 'reviewer-1', review: 'REVIEWING', rework: 0 },
  { id: 'T-005', title: 'Vue3 工程落地', stage: '阶段2 网页控制端', subtask: 'Vue3 工程落地', state: 'DOING', assignee: 'fe-1', reviewer: 'reviewer-1', review: 'PENDING', rework: 0 },
  { id: 'T-006', title: '四项缺陷修复', stage: '阶段2 网页控制端', subtask: '四项缺陷修复', state: 'ASSIGNED', assignee: 'fe-1', reviewer: 'reviewer-1', review: 'PENDING', rework: 0 },
  { id: 'T-007', title: '30 条验收清单', stage: '阶段2 网页控制端', subtask: '30 条验收清单', state: 'DRAFT', assignee: 'fe-1', reviewer: 'reviewer-1', review: 'PENDING', rework: 0 },
]

const taskStates: Record<string, TaskState> = Object.fromEntries(TASK_SEEDS.map((t) => [t.id, t.state]))
let seq = 0
const eventRows: EventRow[] = []

/** 供 WS mock 推进任务状态，使进度环与阶段折叠动画可被真实观察 */
export function mockSetTaskState(taskId: string, state: TaskState): void {
  if (taskId in taskStates) {
    taskStates[taskId] = state
  }
}

function nowIso(): string {
  const date = new Date()
  const pad = (n: number) => String(n).padStart(2, '0')
  const offset = -date.getTimezoneOffset()
  const sign = offset >= 0 ? '+' : '-'
  const abs = Math.abs(offset)
  return (
    `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}T` +
    `${pad(date.getHours())}:${pad(date.getMinutes())}:${pad(date.getSeconds())}` +
    `${sign}${pad(Math.floor(abs / 60))}:${pad(abs % 60)}`
  )
}

export function mockAppendEvent(input: {
  actor: string
  action: string
  summary: string
  taskId?: string | null
  url?: string | null
  project?: string | null
  extra?: Record<string, unknown> | null
}): EventRow {
  seq += 1
  const row: EventRow = {
    seq,
    timestamp: nowIso(),
    actor: input.actor,
    action: input.action,
    taskId: input.taskId ?? null,
    summary: input.summary,
    url: input.url ?? (input.taskId ? `/tasks/${input.taskId}` : null),
    project: input.project ?? MOCK_PROJECT,
    extra: input.extra ?? null,
  }
  eventRows.push(row)
  return row
}

/** 预置几条历史事件，避免首屏空白 */
function seedEvents(): void {
  if (eventRows.length) return
  mockAppendEvent({ actor: 'manager', action: 'task:assigned', summary: 'T-001 已派工给 be-1', taskId: 'T-001' })
  mockAppendEvent({ actor: 'manager', action: 'task:doing', summary: 'T-001 进入执行中', taskId: 'T-001' })
  mockAppendEvent({ actor: 'be-1', action: 'task:submitted', summary: 'T-001 已提交六节报告与证据', taskId: 'T-001' })
  mockAppendEvent({ actor: 'reviewer-1', action: 'task:done', summary: 'T-001 审查 PASS', taskId: 'T-001' })
  mockAppendEvent({ actor: 'system', action: 'launch:model_switch', summary: 'T-003 模型从 amd 切换到 modelscope（429 重试耗尽）', taskId: 'T-003', extra: { from: 'amd', to: 'modelscope', attempts: 10 } })
}
seedEvents()

/* ------------------------------ 派生数据 ------------------------------ */

function buildTasks(): PlanTask[] {
  return TASK_SEEDS.map((seed) => ({
    id: seed.id,
    title: seed.title,
    state: taskStates[seed.id],
    assignee: seed.assignee,
    reviewer: seed.reviewer,
    verify_cmd: '',
    task_type: 2,
    review_status: seed.review,
    stage: seed.stage,
    subtask: seed.subtask,
    rework_count: seed.rework,
    updated_at: nowIso(),
  }))
}

function buildStages(tasks: PlanTask[]): PlanStage[] {
  const order: string[] = []
  const bucket = new Map<string, PlanStage>()
  for (const task of tasks) {
    if (!bucket.has(task.stage)) {
      order.push(task.stage)
      bucket.set(task.stage, { 名称: task.stage, 任务: [] })
    }
    bucket.get(task.stage)!.任务.push({ 子任务: task.subtask, task_id: task.id })
  }
  return order.map((name) => bucket.get(name)!)
}

function computeProgress(tasks: PlanTask[]): { total: number; done: number; percent: number } {
  const total = tasks.length
  const done = tasks.filter((t) => t.state === 'DONE' || t.state === 'PARTIAL').length
  return { total, done, percent: total ? Math.round((done / total) * 1000) / 10 : 0 }
}

export function mockPlanSnapshot(): PlanSnapshot {
  const tasks = buildTasks()
  const progress = { project: MOCK_PROJECT, ...computeProgress(tasks) }
  return {
    ok: true,
    project: MOCK_PROJECT,
    name: MOCK_PROJECT,
    updated_at: nowIso(),
    阶段: buildStages(tasks),
    tasks,
    progress,
    total: progress.total,
    done: progress.done,
    percent: progress.percent,
  }
}

/* ------------------------------ 配置 mock ------------------------------ */

const mockConfigs: Record<string, unknown> = {
  basic: {
    project_name: 'AideanFleet',
    console_host: '127.0.0.1',
    console_port: 5000,
    manager_port: 9900,
    ui_port: 3333,
    allowed_roots: ['E:/Code'],
    default_project: 'AideanFleet',
    timezone: 'Asia/Shanghai',
    lock_ttl_minutes: 60,
  },
  model_pool: {
    models: [
      { name: 'bai', level: 1, base_url: 'https://api.b.ai/v1', model_id: 'qwen3.8-flash', api_key: '${BAI_API_KEY}', http_proxy: 'http://127.0.0.1:10808', https_proxy: 'http://127.0.0.1:10808', env_scope: 'all', resolved: false },
      { name: 'modelscope', level: 3, base_url: 'https://api-inference.modelscope.cn/v1', model_id: 'ZhipuAI/GLM-5.2', api_key: '${MODELSCOPE_API_KEY}', http_proxy: '', https_proxy: '', env_scope: 'all', resolved: true },
      { name: 'agnes', level: 5, base_url: 'https://apihub.agnes-ai.com/v1', model_id: 'agnes-3.0-flash', api_key: '${AGNES_API_KEY}', http_proxy: '', https_proxy: '', env_scope: 'all', resolved: true },
    ] as ModelItem[],
  },
  roles: {
    roles: [
      { name: 'manager', system_prompt: '你是 Manager，负责拆解、派工、验收与返工决策，不写业务代码。', bind_model_name: ['agnes', 'modelscope', 'amd'], adapter: 'hermes' },
      { name: 'fe-1', system_prompt: '你是前端开发角色，只改被允许的前端文件。', bind_model_name: ['agnes', 'modelscope'], adapter: 'codex' },
      { name: 'reviewer-1', system_prompt: '你是审查角色，只审查不改码，回执只能是 PASS/PARTIAL/REWORK/BLOCKED。', bind_model_name: ['modelscope'], adapter: 'hermes' },
    ] as RoleItem[],
  },
  executors: {
    executors: [
      { name: 'claudecode', command: 'claude -p --output-format json', timeout: 600 },
      { name: 'codex', command: 'codex exec --json', timeout: 600 },
      { name: 'opencode', command: 'opencode run', timeout: 600 },
      { name: 'hermes', command: 'hermes', timeout: 600 },
      { name: 'cline', command: 'cline --yolo --json', timeout: 600 },
      { name: 'gemini', command: 'gemini -p --approval-mode=yolo --output-format json', timeout: 600 },
      { name: 'grok', command: 'grok --no-auto-update --always-approve -p --output-format json', timeout: 600 },
    ] as ExecutorItem[],
  },
  email: {
    enabled: false,
    sender: '${SMTP_SENDER}',
    receiver: '${SMTP_RECEIVER}',
    host: '${SMTP_HOST}',
    port: 465,
    auth_code: '${SMTP_AUTH_CODE}',
    use_ssl: true,
  } satisfies EmailConfig,
  notify: {
    on_task_start: false,
    on_task_end: true,
    on_manager_quota: true,
    on_role_quota: true,
  } satisfies NotifyConfig,
  request: { timeout: 600, retry_max: 10, retry_delay: 10 } satisfies RequestConfig,
}

let mockExtensions: ExtensionsMap = {
  claudecode: { skills: ['backend-test', 'ruff-mypy'], mcp: ['filesystem', 'git'] },
  codex: { skills: ['react', 'playwright'], mcp: ['browser'] },
  opencode: { skills: ['api-contract'], mcp: ['database'] },
}

const MOCK_IGNORED_NOTIFY_KEYS = ['on_task_escalated', 'daily_summary']

/* ------------------------------ REST mock ------------------------------ */

export async function mockHealth(): Promise<HealthInfo> {
  return { version: '0.1.0', db: true, events: true, config: true }
}

let mockSession: { project: string; expires_in: number } | null = null

export async function mockCreateSession(project: string): Promise<SessionInfo> {
  if (!project.trim()) {
    const error = new Error('请输入项目名') as Error & { status?: number }
    error.status = 400
    throw error
  }
  if (project !== MOCK_PROJECT) {
    const error = new Error('项目不存在，请检查项目名是否正确') as Error & { status?: number }
    error.status = 400
    throw error
  }
  mockSession = { project, expires_in: 3600 }
  return { ok: true, token: 'mock-token-ui02', project, expires_in: 3600 }
}

export async function mockGetSession(): Promise<SessionInfo> {
  if (!mockSession) {
    const error = new Error('会话无效或已过期') as Error & { status?: number }
    error.status = 401
    throw error
  }
  return { ok: true, project: mockSession.project, expires_in: mockSession.expires_in }
}

export async function mockDeleteSession(): Promise<{ ok: boolean }> {
  mockSession = null
  return { ok: true }
}

export async function mockListProjects(): Promise<{ ok: boolean; projects: ProjectItem[] }> {
  return {
    ok: true,
    projects: [{ id: MOCK_PROJECT, name: MOCK_PROJECT, path: 'E:/Code/AideanFleet', port: 3333 }],
  }
}

let mockMode: ModeResponse['mode'] = 'auto'

export async function mockGetMode(): Promise<ModeResponse> {
  return { ok: true, mode: mockMode, awaiting_confirm: false }
}

export async function mockSetMode(mode: string): Promise<Record<string, unknown>> {
  mockMode = mode === 'confirm' || mode === 'step' ? 'step' : 'auto'
  return { ok: true, mode, effective: mockMode }
}

export async function mockGetPlan(project?: string): Promise<PlanSnapshot> {
  const snapshot = mockPlanSnapshot()
  if (project && project !== MOCK_PROJECT) {
    return { ...snapshot, ok: false, reason: 'project_not_found', project }
  }
  return snapshot
}

export async function mockGetEvents(project?: string, since = 0): Promise<EventsResponse> {
  const rows = eventRows.filter((row) => row.seq > since && (!project || row.project === project || !row.project))
  return { ok: true, project: project || MOCK_PROJECT, since, seq, events: rows }
}

export async function mockLaunchResolve(project: string, mode: string): Promise<Record<string, unknown>> {
  if (project !== MOCK_PROJECT) {
    return { ok: false, reason: 'project_not_found', missing: ['project'] }
  }
  return {
    ok: true,
    mode: mode || 'BOOT',
    ui_url: `http://127.0.0.1:5000/?project=${project}`,
    profile_source: 'E:/Code/AideanFleet/.env',
    missing: [],
  }
}

export async function mockConfirm(payload: { note?: string; decision?: string; taskId?: string | null }): Promise<Record<string, unknown>> {
  const row = mockAppendEvent({
    actor: '用户',
    action: 'step_confirm',
    taskId: payload.taskId ?? null,
    summary: payload.decision === 'note' && payload.note ? `用户意见：${payload.note}` : '用户确认当前步骤',
  })
  return { ok: true, event: row }
}

export async function mockControlConfirm(taskId: string, note = ''): Promise<Record<string, unknown>> {
  const row = mockAppendEvent({
    actor: '用户',
    action: 'step_confirm',
    taskId,
    summary: note || `用户确认 ${taskId} 当前步骤`,
  })
  return { ok: true, event: row }
}

export async function mockChat(project: string | undefined, message: string): Promise<Record<string, unknown>> {
  if (!message.trim()) {
    const error = new Error('消息内容不能为空') as Error & { status?: number }
    error.status = 400
    throw error
  }
  const userRow = mockAppendEvent({ actor: '用户', action: 'chat', summary: message, project: project || MOCK_PROJECT })
  const reply = `【Manager·回执】已收到你的指令：「${message.slice(0, 80)}」。已进入事件流，调度器将据此调整任务计划。`
  const managerRow = mockAppendEvent({ actor: 'Manager', action: 'chat_reply', summary: reply, project: project || MOCK_PROJECT })
  return { ok: true, user_event: userRow, manager_event: managerRow, reply }
}

/** 模拟角色C 的 notify 未就绪：测试邮件按钮应保持置灰 */
export async function mockNotifyTest(): Promise<Record<string, unknown>> {
  return { ok: false, message: 'notify:ready 未到达（mock 环境），按钮保持置灰', receiver: '' }
}

export async function mockNotifyTriggers(): Promise<NotifyTriggersResponse> {
  return {
    ok: true,
    data: {
      TASK_STARTED: { enabled: false, event_type: 'TASK_STARTED' },
      TASK_COMPLETED: { enabled: true, event_type: 'TASK_COMPLETED' },
      MANAGER_QUOTA_LOW: { enabled: true, event_type: 'MANAGER_QUOTA_LOW' },
      WORKER_QUOTA_LOW: { enabled: true, event_type: 'WORKER_QUOTA_LOW' },
      TASK_ESCALATED: { enabled: true, event_type: 'TASK_ESCALATED' },
      TASK_FAILED: { enabled: true, event_type: 'TASK_FAILED' },
      DAILY_SUMMARY: { enabled: false, event_type: 'DAILY_SUMMARY' },
    },
    source: 'E:/Code/AideanFleet/config/notifications.json',
  }
}

export async function mockGetExtensions(): Promise<ExtensionsResponse> {
  return { ok: true, data: JSON.parse(JSON.stringify(mockExtensions)) as ExtensionsMap, source: 'data/extensions.json' }
}

export async function mockSaveExtensions(data: ExtensionsMap): Promise<Record<string, unknown>> {
  const out: ExtensionsMap = {}
  for (const [name, rec] of Object.entries(data)) {
    out[name] = {
      skills: (rec?.skills ?? []).filter((x) => String(x).trim()),
      mcp: (rec?.mcp ?? []).filter((x) => String(x).trim()),
    } satisfies ExtensionRecord
  }
  mockExtensions = out
  return { ok: true, message: '拓展配置已保存', count: Object.keys(out).length }
}

export async function mockGetConfig(section: ConfigSectionName): Promise<ConfigGetResponse> {
  return {
    ok: true,
    section,
    data: mockConfigs[section] ?? {},
    source: 'E:/Code/AideanFleet/.env',
    mtime: nowIso(),
  }
}

export async function mockSaveConfig(
  section: ConfigSectionName,
  data: Record<string, unknown>,
): Promise<ConfigPostResponse> {
  const ignored: string[] = []
  const payload = { ...data }
  if (section === 'notify') {
    for (const key of MOCK_IGNORED_NOTIFY_KEYS) {
      if (key in payload) {
        ignored.push(key)
        delete payload[key]
      }
    }
    mockConfigs.notify = {
      ...(mockConfigs.notify as NotifyConfig),
      ...(payload as unknown as Partial<NotifyConfig>),
    }
  } else {
    mockConfigs[section] = { ...(mockConfigs[section] as Record<string, unknown>), ...payload }
  }
  return { ok: true, section, applied: payload, ignored, mtime: nowIso() }
}

export async function mockGetTask(taskId: string): Promise<{ ok: boolean; task?: TaskDetail }> {
  const seed = TASK_SEEDS.find((t) => t.id === taskId)
  if (!seed) return { ok: false }
  return {
    ok: true,
    task: {
      task_id: seed.id,
      project_id: MOCK_PROJECT,
      title: seed.title,
      role: seed.assignee,
      exec_status: taskStates[seed.id],
      review_status: seed.review,
      rework_count: seed.rework,
      blocked_reason: '',
    },
  }
}

export async function mockDispatchTask(taskId: string): Promise<Record<string, unknown>> {
  if (!TASK_SEEDS.some((t) => t.id === taskId)) {
    return { ok: false, reason: 'task_not_found', taskId }
  }
  taskStates[taskId] = 'DOING'
  mockAppendEvent({ actor: 'console', action: 'task:doing', taskId, summary: `${taskId} 进入执行中（mock）` })
  return { ok: true, taskId, state: 'DOING', rounds: [] }
}
