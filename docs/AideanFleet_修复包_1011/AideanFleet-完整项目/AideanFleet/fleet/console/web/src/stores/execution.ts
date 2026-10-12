/**
 * useExecutionStore · 执行控制面
 * 负责：调度模式（auto 自动执行 / step 每步确认）、人工确认栏状态、
 * gate / model:switch / launch 等“过程记录”事件（结构化，不再笼统塞进某一步 detail）、
 * 以及 notify:ready 通知通道就绪标志（解锁消息页的“发送测试邮件”按钮）。
 */
import { computed, ref } from 'vue'
import { defineStore } from 'pinia'
import { api } from '@/api/client'
import type { EventRow, SchedulerMode } from '@/api/types'

const PROCESS_ACTIONS = /^(gate:|launch:|mode:|step_confirm$)/

export const useExecutionStore = defineStore('execution', () => {
  const mode = ref<SchedulerMode>('step')  // 默认每步确认（用户口径）
  const awaitingConfirm = ref(false)
  const note = ref('')
  const confirmBusy = ref(false)
  /** 总览“过程记录”：机器门、模型降级、启动阶段、人工确认 */
  const processLog = ref<EventRow[]>([])
  /** 角色C 的通知通道是否就绪（notify:ready） */
  const notifyReady = ref(false)
  const lastConfirmAt = ref('')

  const modeLabel = computed(() => (mode.value === 'auto' ? '自动执行' : '每步确认'))

  function isProcessAction(action: string): boolean {
    return PROCESS_ACTIONS.test(action) || action === 'step_confirm'
  }

  function pushEvent(row: EventRow): void {
    const action = String(row.action ?? '')
    if (action === 'notify:ready' || action === 'notify_ready') {
      notifyReady.value = true
    }
    if (action === 'mode:changed' || action === 'mode_change') {
      const next = String((row.extra?.mode as string) ?? row.summary ?? '').includes('auto') ? 'auto' : 'step'
      mode.value = next
    }
    if (!isProcessAction(action)) return
    if (processLog.value.some((item) => item.seq === row.seq)) return
    processLog.value = [...processLog.value, row]
  }

  function ingest(rows: EventRow[]): void {
    for (const row of rows) pushEvent(row)
  }

  function setMode(next: SchedulerMode): void {
    mode.value = next
  }

  async function loadMode(): Promise<void> {
    try {
      const result = await api.getMode()
      mode.value = result.mode === 'auto' ? 'auto' : 'step'
      awaitingConfirm.value = Boolean(result.awaiting_confirm)
    } catch {
      /* 服务端未就绪时保持默认值 */
    }
  }

  async function switchMode(next: SchedulerMode, via?: (payload: unknown) => boolean): Promise<void> {
    const previous = mode.value
    mode.value = next
    try {
      const delivered = via ? via({ type: 'set_mode', mode: next, actor: '用户' }) : false
      if (!delivered) await api.setMode(next)
    } catch {
      mode.value = previous
    }
  }

  /** 每步确认模式下的“确认 / 提意见” */
  async function confirm(project: string | undefined, decision: 'confirm' | 'note'): Promise<{ ok: boolean; message: string }> {
    const text = note.value.trim()
    if (decision === 'note' && !text) {
      return { ok: false, message: '意见内容不能为空' }
    }
    confirmBusy.value = true
    try {
      await api.confirm({ project, decision, note: text })
      lastConfirmAt.value = new Date().toISOString()
      if (decision === 'note') note.value = ''
      awaitingConfirm.value = false
      return { ok: true, message: decision === 'note' ? '意见已提交给 Manager' : '已确认当前步骤' }
    } catch (error) {
      return { ok: false, message: error instanceof Error ? error.message : '确认失败' }
    } finally {
      confirmBusy.value = false
    }
  }

  function clear(): void {
    processLog.value = []
  }

  return {
    mode,
    modeLabel,
    awaitingConfirm,
    note,
    confirmBusy,
    processLog,
    notifyReady,
    lastConfirmAt,
    pushEvent,
    ingest,
    setMode,
    loadMode,
    switchMode,
    confirm,
    clear,
  }
})
