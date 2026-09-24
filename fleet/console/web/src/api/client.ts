/**
 * 控制台 REST 客户端。
 * - 默认同源（server.py 已托管 dist，且 dev 模式经 vite 代理到 127.0.0.1:5000）
 * - 令牌三层兼容：Authorization Bearer > cookie fleet_token > ?token=（与 server.py token_of 对齐）
 * - VITE_USE_MOCK=true 时全部走 src/mock，不等后端联调
 */

import type {
  ConfigGetResponse,
  ConfigPostResponse,
  ConfigSectionName,
  EmailConfig,
  EventsResponse,
  ExecutorItem,
  ExtensionsMap,
  ExtensionsResponse,
  HealthInfo,
  ModeResponse,
  ModelItem,
  NotifyConfig,
  NotifyTriggersResponse,
  PlanSnapshot,
  ProjectItem,
  RequestConfig,
  RoleItem,
  SessionInfo,
  TaskDetail,
} from './types'

export const USE_MOCK = import.meta.env.VITE_USE_MOCK === 'true'
export const API_BASE = (import.meta.env.VITE_API_BASE ?? '').replace(/\/$/, '')

/** 会话令牌（登录后由 auth store 写入；WS 与 REST 共用） */
let authToken = ''

export function setAuthToken(token: string): void {
  authToken = token || ''
}

export function getAuthToken(): string {
  return authToken
}

export class ApiFail extends Error {
  status: number
  body: Record<string, unknown>

  constructor(status: number, body: Record<string, unknown>, message?: string) {
    super(message || String(body.error || body.reason || `HTTP ${status}`))
    this.name = 'ApiFail'
    this.status = status
    this.body = body
  }
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers || {})
  if (init.body && !headers.has('Content-Type')) {
    headers.set('Content-Type', 'application/json; charset=utf-8')
  }
  if (authToken) {
    headers.set('Authorization', `Bearer ${authToken}`)
  }
  let response: Response
  try {
    response = await fetch(`${API_BASE}${path}`, {
      credentials: 'include',
      ...init,
      headers,
    })
  } catch (error) {
    throw new ApiFail(0, { ok: false, reason: 'network_error' }, `网络不可达：${String(error)}`)
  }
  const text = await response.text()
  let body: Record<string, unknown> = {}
  if (text) {
    try {
      body = JSON.parse(text) as Record<string, unknown>
    } catch {
      throw new ApiFail(response.status, { ok: false, reason: 'bad_json' }, '服务端返回了非 JSON 内容')
    }
  }
  if (!response.ok) {
    throw new ApiFail(response.status, body)
  }
  return body as T
}

function qs(params: Record<string, string | number | undefined>): string {
  const search = new URLSearchParams()
  for (const [key, value] of Object.entries(params)) {
    if (value !== undefined && value !== null && `${value}` !== '') {
      search.set(key, String(value))
    }
  }
  const text = search.toString()
  return text ? `?${text}` : ''
}

/* ------------------------------ mock 桥接 ------------------------------ */

type MockModule = typeof import('@/mock/api')

let mock: MockModule | null = null

async function mockApi(): Promise<MockModule> {
  if (!mock) {
    mock = await import('@/mock/api')
  }
  return mock
}

/* ------------------------------ 具体接口 ------------------------------ */

export const api = {
  async health(): Promise<HealthInfo> {
    if (USE_MOCK) return (await mockApi()).mockHealth()
    return request<HealthInfo>('/api/health')
  },

  async createSession(project: string): Promise<SessionInfo> {
    if (USE_MOCK) return (await mockApi()).mockCreateSession(project)
    return request<SessionInfo>('/api/session', {
      method: 'POST',
      body: JSON.stringify({ project }),
    })
  },

  async getSession(): Promise<SessionInfo> {
    if (USE_MOCK) return (await mockApi()).mockGetSession()
    return request<SessionInfo>('/api/session')
  },

  async deleteSession(): Promise<{ ok: boolean }> {
    if (USE_MOCK) return (await mockApi()).mockDeleteSession()
    return request<{ ok: boolean }>('/api/session', { method: 'DELETE' })
  },

  async listProjects(): Promise<{ ok: boolean; projects: ProjectItem[] }> {
    if (USE_MOCK) return (await mockApi()).mockListProjects()
    return request<{ ok: boolean; projects: ProjectItem[] }>('/api/projects')
  },

  /** 锁屏候选：免会话端点，只含 id/name */
  async listProjectNames(): Promise<{ ok: boolean; projects: { id: string; name: string }[] }> {
    return request<{ ok: boolean; projects: { id: string; name: string }[] }>('/api/projects/names')
  },

  /** 切换当前会话绑定的项目（project 可传 id 或名称，返回规范化后的 project_id） */
  async switchSession(project: string): Promise<{ ok: boolean; project: string; expires_in: number }> {
    return request<{ ok: boolean; project: string; expires_in: number }>('/api/session/switch', {
      method: 'POST',
      body: JSON.stringify({ project }),
    })
  },

  /** 角色贡献聚合：任务数/完成数/耗时/token（大纲 L1-B） */
  async rolesSummary(project: string): Promise<{ ok: boolean; project: string; roles: Array<{ role: string; tasks_total: number; tasks_done: number; duration_ms: number; total_tokens: number; call_count: number }> }> {
    return request(`/api/roles/summary${qs({ project })}`)
  },

  /** 运行中执行体实时读数（需求4）：pid/进程名/任务归属/角色/已运行秒数 */
  async executorsRunning(project?: string): Promise<{ ok: boolean; project: string; count: number; executors: import('./types').RunningExecutor[] }> {
    return request(`/api/executors/running${qs({ project })}`)
  },

  /** 历史任务列表（需求5）：执行/审查角色、耗时、token，按更新时间倒序 */
  async historyTasks(project?: string, limit = 200): Promise<{ ok: boolean; project: string; total: number; tasks: import('./types').HistoryTaskRow[] }> {
    return request(`/api/history/tasks${qs({ project, limit })}`)
  },

  /** 角色工作档案（需求6）：做过什么、耗时/token、未来任务分配 */
  async roleProfile(role: string, project?: string): Promise<{ ok: boolean; project: string; role: string; profile: import('./types').RoleProfile }> {
    return request(`/api/roles/${encodeURIComponent(role)}/profile${qs({ project })}`)
  },

  async getMode(): Promise<ModeResponse> {
    if (USE_MOCK) return (await mockApi()).mockGetMode()
    return request<ModeResponse>('/api/mode')
  },

  async setMode(mode: string, actor = '用户'): Promise<Record<string, unknown>> {
    if (USE_MOCK) return (await mockApi()).mockSetMode(mode)
    return request<Record<string, unknown>>('/api/mode', {
      method: 'POST',
      body: JSON.stringify({ mode, actor }),
    })
  },

  async getPlan(project?: string): Promise<PlanSnapshot> {
    if (USE_MOCK) return (await mockApi()).mockGetPlan(project)
    return request<PlanSnapshot>(`/api/plan${qs({ project })}`)
  },

  async getEvents(project?: string, since = 0): Promise<EventsResponse> {
    if (USE_MOCK) return (await mockApi()).mockGetEvents(project, since)
    return request<EventsResponse>(`/api/events${qs({ project, since })}`)
  },

  async launchResolve(project: string, mode: string): Promise<Record<string, unknown>> {
    if (USE_MOCK) return (await mockApi()).mockLaunchResolve(project, mode)
    return request<Record<string, unknown>>(`/api/launch-resolve${qs({ project, mode })}`)
  },

  async confirm(payload: {
    project?: string
    decision?: 'confirm' | 'note'
    note?: string
    taskId?: string | null
  }): Promise<Record<string, unknown>> {
    if (USE_MOCK) return (await mockApi()).mockConfirm(payload)
    return request<Record<string, unknown>>('/api/confirm', {
      method: 'POST',
      body: JSON.stringify(payload),
    })
  },

  async controlConfirm(taskId: string, note = ''): Promise<Record<string, unknown>> {
    if (USE_MOCK) return (await mockApi()).mockControlConfirm(taskId, note)
    return request<Record<string, unknown>>('/api/control/confirm', {
      method: 'POST',
      body: JSON.stringify({ taskId, note }),
    })
  },

  async chat(project: string | undefined, message: string): Promise<Record<string, unknown>> {
    if (USE_MOCK) return (await mockApi()).mockChat(project, message)
    return request<Record<string, unknown>>('/api/chat', {
      method: 'POST',
      body: JSON.stringify({ project, message }),
    })
  },

  async notifyTest(): Promise<Record<string, unknown>> {
    if (USE_MOCK) return (await mockApi()).mockNotifyTest()
    return request<Record<string, unknown>>('/api/notify/test', { method: 'POST' })
  },

  async notifyTriggers(): Promise<NotifyTriggersResponse> {
    if (USE_MOCK) return (await mockApi()).mockNotifyTriggers()
    return request<NotifyTriggersResponse>('/api/notify/triggers')
  },

  async getExtensions(): Promise<ExtensionsResponse> {
    if (USE_MOCK) return (await mockApi()).mockGetExtensions()
    return request<ExtensionsResponse>('/api/extensions')
  },

  async saveExtensions(data: ExtensionsMap): Promise<Record<string, unknown>> {
    if (USE_MOCK) return (await mockApi()).mockSaveExtensions(data)
    return request<Record<string, unknown>>('/api/extensions', {
      method: 'POST',
      body: JSON.stringify({ data }),
    })
  },

  async getConfig<T = unknown>(section: ConfigSectionName): Promise<ConfigGetResponse<T>> {
    if (USE_MOCK) return (await mockApi()).mockGetConfig(section) as Promise<ConfigGetResponse<T>>
    return request<ConfigGetResponse<T>>(`/api/config/${section}`)
  },

  async saveConfig(section: ConfigSectionName, data: Record<string, unknown>): Promise<ConfigPostResponse> {
    if (USE_MOCK) return (await mockApi()).mockSaveConfig(section, data)
    return request<ConfigPostResponse>(`/api/config/${section}`, {
      method: 'POST',
      body: JSON.stringify({ data }),
    })
  },

  async getModels(): Promise<ModelItem[]> {
    const res = await api.getConfig<{ models: ModelItem[] }>('model_pool')
    return res.data?.models ?? []
  },

  async saveModels(models: ModelItem[]): Promise<ConfigPostResponse> {
    return api.saveConfig('model_pool', { models })
  },

  async getRoles(): Promise<RoleItem[]> {
    const res = await api.getConfig<{ roles: RoleItem[] }>('roles')
    return res.data?.roles ?? []
  },

  async saveRoles(roles: RoleItem[]): Promise<ConfigPostResponse> {
    return api.saveConfig('roles', { roles })
  },

  async getExecutors(): Promise<ExecutorItem[]> {
    const res = await api.getConfig<{ executors: ExecutorItem[] }>('executors')
    return res.data?.executors ?? []
  },

  async saveExecutors(executors: ExecutorItem[]): Promise<ConfigPostResponse> {
    return api.saveConfig('executors', { executors })
  },

  async getEmail(): Promise<EmailConfig> {
    return (await api.getConfig<EmailConfig>('email')).data
  },

  async getNotify(): Promise<NotifyConfig> {
    return (await api.getConfig<NotifyConfig>('notify')).data
  },

  async getRequest(): Promise<RequestConfig> {
    return (await api.getConfig<RequestConfig>('request')).data
  },

  async getBasic() {
    return (await api.getConfig('basic')).data
  },

  async getTask(taskId: string): Promise<{ ok: boolean; task?: TaskDetail }> {
    if (USE_MOCK) return (await mockApi()).mockGetTask(taskId)
    return request<{ ok: boolean; task?: TaskDetail }>(`/api/tasks/${encodeURIComponent(taskId)}`)
  },

  async dispatchTask(taskId: string): Promise<Record<string, unknown>> {
    if (USE_MOCK) return (await mockApi()).mockDispatchTask(taskId)
    return request<Record<string, unknown>>(`/tasks/${encodeURIComponent(taskId)}/dispatch`, {
      method: 'POST',
      body: JSON.stringify({}),
    })
  },
}

/** WS 连接地址（令牌走 query，与 server.py ws_endpoint 对齐） */
export function wsUrl(token: string): string {
  const base = API_BASE || window.location.origin
  const url = new URL('/ws', base.startsWith('http') ? base : window.location.origin)
  url.protocol = url.protocol === 'https:' ? 'wss:' : 'ws:'
  if (token) {
    url.searchParams.set('token', token)
  }
  return url.toString()
}
