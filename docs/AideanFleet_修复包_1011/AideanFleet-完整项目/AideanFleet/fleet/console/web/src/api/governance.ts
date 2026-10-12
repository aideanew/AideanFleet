/**
 * UI-03R · 治理数据层（审批中心 / 成本面板）
 *
 * 数据源真相：`fleet/governance/`（GOV-01 PASS）—— **角色A 已在 server.py 暴露 HTTP 面**
 * （GET /api/approvals[?project=]、GET /api/approvals/{id}、POST /api/approvals/{id}/approve|reject、
 *   GET /api/usage/total[?since=]、GET /api/usage/by_date[?since=]、GET /api/budget、POST /api/budget）。
 * 本层策略：
 *   1. 类型 **严格照抄** Python dataclass 字段（ApprovalRequest / BudgetLimit / UsageAggregator 返回形状）；
 *   2. 启动时探测 `/api/approvals`：可达 → 走真实 API；404/异常 → 走契约形状 mock 兜底，并在页面显式标注「后端未就绪」；
 *   3. 不臆造字段、不伪造「已对接」。
 */
import { API_BASE, getAuthToken } from './client'

/* ------------------------------ 类型（照抄 dataclass） ------------------------------ */

export type ApprovalActionType = 'delete_overwrite' | 'smtp_first_send' | 'budget_warning'

/** fleet/governance/approval.py::ApprovalRequest */
export interface ApprovalRequest {
  approval_id: string
  action_type: ApprovalActionType | string
  description: string
  task_id: string
  project_id: string
  requested_by: string
  /** pending / approved / rejected / expired（store 侧 status 字段） */
  status: string
  /** "" | "approve" | "reject" */
  decision: string
  decided_by: string
  decided_at: string
  created_at: string
  expires_at: string
}

/** fleet/governance/approval.py::ApprovalDecision */
export interface ApprovalDecision {
  approved: boolean
  approval_id: string
  decision: string
  decided_by: string
  decided_at: string
}

/** fleet/governance/store.py::sum_usage 行（group_by 后 period 为该组键） */
export interface UsageRow {
  period: string
  prompt_tokens: number
  completion_tokens: number
  total_tokens: number
  call_count: number
  cached_tokens?: number
  unknown_usage?: number
}

/** fleet/governance/usage.py::UsageAggregator.total() */
export interface UsageTotals {
  prompt_tokens: number
  completion_tokens: number
  total_tokens: number
  call_count: number
}

/** fleet/governance/budget.py::BudgetLimit（remaining/usage_pct/is_exceeded/is_warning 为 Python property，前端同口径派生） */
export interface BudgetLimit {
  level: string
  scope: string
  limit_tokens: number
  used_tokens: number
  action: string
}

/** fleet/governance/budget.py::BudgetManager.get_status() */
export interface BudgetStatus {
  task?: BudgetLimit
  project?: BudgetLimit
  daily?: BudgetLimit
}

export type GovSource = 'api' | 'contract-mock'

/* ------------------------------ 派生（与 Python property 同口径） ------------------------------ */

export function budgetRemaining(b: BudgetLimit): number {
  return Math.max(0, b.limit_tokens - b.used_tokens)
}

export function budgetUsagePct(b: BudgetLimit): number {
  if (b.limit_tokens <= 0) return 0
  return Math.round((b.used_tokens / b.limit_tokens) * 1000) / 10
}

export function budgetIsExceeded(b: BudgetLimit): boolean {
  return b.limit_tokens > 0 && b.used_tokens >= b.limit_tokens
}

export function budgetIsWarning(b: BudgetLimit): boolean {
  return b.limit_tokens > 0 && budgetUsagePct(b) >= 80
}

export const APPROVAL_ACTION_LABEL: Record<string, string> = {
  delete_overwrite: 'delete/overwrite 超出红线',
  smtp_first_send: '首次真实 SMTP 发送',
  budget_warning: '任务预算超 80% 阈值（仅告警）',
}

/* ------------------------------ 契约形状 mock（无产生方时的兜底） ------------------------------ */

let mockApprovals: ApprovalRequest[] = []
let mockUsage: UsageRow[] = []
let mockBudget: BudgetStatus = {}

function iso(minutesAgo: number): string {
  return new Date(Date.now() - minutesAgo * 60_000).toISOString()
}

/** 按 Python 侧默认值种子化（task 200000 / project 2000000 / daily 500000，action=pause） */
function seedMock(project: string): void {
  if (mockApprovals.length) return
  mockApprovals = [
    {
      approval_id: 'appr-9f3c1a2b7d40',
      action_type: 'delete_overwrite',
      description: 'delete/overwrite command outside redlines',
      task_id: 'T-006',
      project_id: project,
      requested_by: 'be-2',
      status: 'pending',
      decision: '',
      decided_by: '',
      decided_at: '',
      created_at: iso(42),
      expires_at: iso(-24 * 60 + 42),
    },
    {
      approval_id: 'appr-2e8d0c4f91ab',
      action_type: 'smtp_first_send',
      description: 'first real SMTP send',
      task_id: 'T-007',
      project_id: project,
      requested_by: 'system',
      status: 'pending',
      decision: '',
      decided_by: '',
      decided_at: '',
      created_at: iso(15),
      expires_at: iso(-24 * 60 + 15),
    },
    {
      approval_id: 'appr-77b1c9e5a3f2',
      action_type: 'budget_warning',
      description: 'task budget >80% threshold (warn only)',
      task_id: 'T-003',
      project_id: project,
      requested_by: 'system',
      status: 'approved',
      decision: 'approve',
      decided_by: 'user',
      decided_at: iso(120),
      created_at: iso(150),
      expires_at: iso(-24 * 60 + 150),
    },
  ]

  mockUsage = [
    { period: '2026-09-14', prompt_tokens: 412_300, completion_tokens: 88_120, total_tokens: 500_420, call_count: 96, cached_tokens: 120_400, unknown_usage: 0 },
    { period: '2026-09-15', prompt_tokens: 268_940, completion_tokens: 61_780, total_tokens: 330_720, call_count: 63, cached_tokens: 88_200, unknown_usage: 1 },
  ]

  mockBudget = {
    task: { level: 'task', scope: 'T-006', limit_tokens: 200_000, used_tokens: 171_400, action: 'pause' },
    project: { level: 'project', scope: project, limit_tokens: 2_000_000, used_tokens: 831_140, action: 'pause' },
    daily: { level: 'daily', scope: new Date().toISOString().slice(0, 10), limit_tokens: 500_000, used_tokens: 330_720, action: 'pause' },
  }
}

/* ------------------------------ 探测与读取 ------------------------------ */

let detected: GovSource | null = null

function authHeaders(): HeadersInit {
  const token = getAuthToken()
  const headers: Record<string, string> = {}
  if (token) headers.Authorization = `Bearer ${token}`
  return headers
}

/**
 * 探测治理 HTTP 面是否已由角色A 暴露。
 * 404 → 端点未部署（若 401/403 说明路由存在但鉴权失败，仍视为未就绪以免误报）。
 */
export async function detectGovSource(): Promise<GovSource> {
  if (detected) return detected
  try {
    const res = await fetch(`${API_BASE}/api/approvals`, {
      headers: authHeaders(),
      credentials: 'include',
    })
    detected = res.ok ? 'api' : 'contract-mock'
  } catch {
    detected = 'contract-mock'
  }
  return detected
}

export function govSourceSync(): GovSource | null {
  return detected
}

async function apiGet<T>(path: string): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, { headers: authHeaders(), credentials: 'include' })
  if (!res.ok) throw new Error(`HTTP ${res.status}`)
  return (await res.json()) as T
}

/* ------------------------------ 对外接口 ------------------------------ */

export interface GovResult<T> {
  source: GovSource
  data: T
}

export async function listApprovals(project?: string): Promise<GovResult<ApprovalRequest[]>> {
  const source = await detectGovSource()
  if (source === 'api') {
    const q = project ? `?project=${encodeURIComponent(project)}` : ''
    const body = await apiGet<{ approvals?: ApprovalRequest[]; data?: ApprovalRequest[] }>(`/api/approvals${q}`)
    return { source, data: body.approvals ?? body.data ?? [] }
  }
  seedMock(project || 'AideanFleet')
  return { source, data: [...mockApprovals] }
}

export async function decideApproval(
  approvalId: string,
  decision: 'approve' | 'reject',
  decidedBy = 'user',
): Promise<GovResult<ApprovalDecision>> {
  const source = await detectGovSource()
  if (source === 'api') {
    const res = await fetch(`${API_BASE}/api/approvals/${encodeURIComponent(approvalId)}/${decision}`, {
      method: 'POST',
      headers: { ...authHeaders(), 'Content-Type': 'application/json; charset=utf-8' },
      credentials: 'include',
      body: JSON.stringify({ decided_by: decidedBy }),
    })
    if (!res.ok) throw new Error(`HTTP ${res.status}`)
    return { source, data: (await res.json()) as ApprovalDecision }
  }
  seedMock('AideanFleet')
  const index = mockApprovals.findIndex((a) => a.approval_id === approvalId)
  const now = new Date().toISOString()
  const target = index >= 0 ? mockApprovals[index] : undefined
  const result: ApprovalDecision = {
    approved: decision === 'approve' && Boolean(target),
    approval_id: approvalId,
    decision,
    decided_by: decidedBy,
    decided_at: now,
  }
  if (target) {
    mockApprovals[index] = {
      ...target,
      status: decision === 'approve' ? 'approved' : 'rejected',
      decision,
      decided_by: decidedBy,
      decided_at: now,
    }
  }
  return { source, data: result }
}

export async function usageTotals(since?: string): Promise<GovResult<UsageTotals>> {
  const source = await detectGovSource()
  if (source === 'api') {
    const q = since ? `?since=${encodeURIComponent(since)}` : ''
    const body = await apiGet<UsageTotals & { data?: UsageTotals }>(`/api/usage/total${q}`)
    return { source, data: body.data ?? body }
  }
  seedMock('AideanFleet')
  return {
    source,
    data: mockUsage.reduce<UsageTotals>(
      (acc, row) => ({
        prompt_tokens: acc.prompt_tokens + row.prompt_tokens,
        completion_tokens: acc.completion_tokens + row.completion_tokens,
        total_tokens: acc.total_tokens + row.total_tokens,
        call_count: acc.call_count + row.call_count,
      }),
      { prompt_tokens: 0, completion_tokens: 0, total_tokens: 0, call_count: 0 },
    ),
  }
}

export async function usageByDate(since?: string): Promise<GovResult<UsageRow[]>> {
  const source = await detectGovSource()
  if (source === 'api') {
    const q = since ? `?since=${encodeURIComponent(since)}` : ''
    const body = await apiGet<{ rows?: UsageRow[]; data?: UsageRow[] }>(`/api/usage/by_date${q}`)
    return { source, data: body.rows ?? body.data ?? [] }
  }
  seedMock('AideanFleet')
  return { source, data: [...mockUsage] }
}

export async function budgetStatus(taskId?: string, projectId?: string): Promise<GovResult<BudgetStatus>> {
  const source = await detectGovSource()
  if (source === 'api') {
    const params = new URLSearchParams()
    if (taskId) params.set('task_id', taskId)
    if (projectId) params.set('project_id', projectId)
    const q = params.toString() ? `?${params.toString()}` : ''
    const body = await apiGet<BudgetStatus & { data?: BudgetStatus }>(`/api/budget${q}`)
    return { source, data: body.data ?? body }
  }
  seedMock(projectId || 'AideanFleet')
  return { source, data: { ...mockBudget } }
}

/** 仅测试/演示用：重置探测缓存与 mock 状态 */
export function _resetGovForTest(): void {
  detected = null
  mockApprovals = []
  mockUsage = []
  mockBudget = {}
}
