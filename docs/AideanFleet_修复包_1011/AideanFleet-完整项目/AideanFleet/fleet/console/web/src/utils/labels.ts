/** 中文文案字典与状态语义色映射（工作包 §9.5-4：全部中文、零英文残留） */

import type { TaskState } from '@/api/types'

export type Tone = 'ok' | 'danger' | 'warn' | 'info' | 'cyan' | 'violet' | 'mute'

/** 任务状态 -> 中文标签（docs/契约/任务状态机.md 10 态） */
export const TASK_STATE_LABEL: Record<string, string> = {
  DRAFT: '草稿',
  ASSIGNED: '已派工',
  DOING: '执行中',
  SUBMITTED: '已提交',
  REVIEWING: '审查中',
  DONE: '完成',
  PARTIAL: '部分完成',
  REWORK: '返工中',
  BLOCKED: '阻塞',
  ESCALATED: '已升级（需人工介入）',
}

export const TASK_STATE_TONE: Record<string, Tone> = {
  DRAFT: 'mute',
  ASSIGNED: 'info',
  DOING: 'cyan',
  SUBMITTED: 'violet',
  REVIEWING: 'warn',
  DONE: 'ok',
  PARTIAL: 'warn',
  REWORK: 'danger',
  BLOCKED: 'mute',
  ESCALATED: 'danger',
}

export const REVIEW_STATUS_LABEL: Record<string, string> = {
  PENDING: '待审',
  REVIEWING: '审查中',
  PASS: '通过',
  PARTIAL: '部分通过',
  REWORK: '退回重做',
  BLOCKED: '审查阻塞',
}

export const REVIEW_STATUS_TONE: Record<string, Tone> = {
  PENDING: 'mute',
  REVIEWING: 'warn',
  PASS: 'ok',
  PARTIAL: 'warn',
  REWORK: 'danger',
  BLOCKED: 'mute',
}

/** 事件 action -> 中文动作名（未知动作原样回退，不丢信息） */
export const ACTION_LABEL: Record<string, string> = {
  'task:assigned': '已派工',
  'task:reassigned': '重新派工',
  'task:doing': '开始执行',
  'task:submitted': '已提交',
  'task:reviewing': '转交审查',
  'task:done': '审查通过',
  'task:partial': '部分通过',
  'task:rework': '退回重做',
  'task:blocked': '阻塞',
  'task:blocked_release': '阻塞解除',
  'task:escalated': '升级人工',
  'task:created': '任务创建',
  'gate:passed': '机器门通过',
  'gate:failed': '机器门失败',
  'launch:model_switch': '模型降级切换',
  'chat': '用户发言',
  'chat_reply': 'Manager 回执',
  step_confirm: '人工确认',
  'mode:changed': '模式切换',
}

export function actionLabel(action: string): string {
  return ACTION_LABEL[action] ?? action
}

/** 调度模式中文 */
export const MODE_LABEL: Record<string, string> = {
  auto: '自动执行',
  step: '每步确认',
  confirm: '每步确认',
}

/** 10 步准备清单（原文照抄初始设计/核心2.md，不得改写） */
export const PREPARE_STEPS: string[] = [
  '接收指令',
  '分析需求',
  '初始化Manager',
  '建立项目主体计划',
  '确认创建模型库',
  '确认创建角色库',
  '确认创建执行体',
  '确认创建工具库',
  '确认创建提示词',
  '一切就绪!是否启动?',
]

/** 执行阶段是否已开始：plan 中任一任务离开 DRAFT 即视为已启动 */
export function hasExecutionStarted(states: string[]): boolean {
  return states.some((state) => state !== undefined && (state as TaskState) !== 'DRAFT')
}

export function formatTime(iso: string | null | undefined): string {
  if (!iso) return '—'
  const date = new Date(iso)
  if (Number.isNaN(date.getTime())) return iso
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${pad(date.getHours())}:${pad(date.getMinutes())}:${pad(date.getSeconds())}`
}

/** 相对时间（对话页用） */
export function relativeTime(iso: string | null | undefined): string {
  if (!iso) return '—'
  const date = new Date(iso)
  if (Number.isNaN(date.getTime())) return iso
  const diff = Date.now() - date.getTime()
  if (diff < 10_000) return '刚刚'
  if (diff < 60_000) return `${Math.floor(diff / 1000)} 秒前`
  if (diff < 3_600_000) return `${Math.floor(diff / 60_000)} 分钟前`
  if (diff < 86_400_000) return `${Math.floor(diff / 3_600_000)} 小时前`
  return formatTime(iso)
}

/** 是否为“掩码占位值”：提交时应视为未修改（工作包 §9.5-2） */
export function isMaskedPlaceholder(value: string): boolean {
  const text = String(value ?? '').trim()
  if (!text) return true
  return text.startsWith('${') || text === '***' || /^\*+$/.test(text)
}
