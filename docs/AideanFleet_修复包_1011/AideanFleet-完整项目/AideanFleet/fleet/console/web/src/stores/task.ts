/**
 * useTaskStore · 任务事件的结构化消费
 *
 * 缺陷修复：旧版把 task_update / gate / model:switch 等事件统统塞进“当前步骤 detail”。
 * 本 store 按任务 id 分桶保存任务级事件，供总览页按阶段渲染“过程记录”。
 */
import { computed, ref } from 'vue'
import { defineStore } from 'pinia'
import { api } from '@/api/client'
import type { EventRow, TaskDetail } from '@/api/types'

const TASK_ACTIONS = /^task:/
const GATE_ACTIONS = /^gate:/

export const useTaskStore = defineStore('task', () => {
  /** 全部任务级事件（按 seq 升序） */
  const taskEvents = ref<EventRow[]>([])
  /** 任务 id -> 该任务的事件序列 */
  const byTask = ref<Record<string, EventRow[]>>({})
  /** gate:* 事件（机器门） */
  const gateEvents = ref<EventRow[]>([])
  /** 任务详情缓存 */
  const details = ref<Record<string, TaskDetail>>({})
  const lastUpdate = ref('')

  const eventCount = computed(() => taskEvents.value.length)

  function has(taskId: string): boolean {
    return Boolean(byTask.value[taskId]?.length)
  }

  function pushEvent(row: EventRow): void {
    const action = String(row.action ?? '')
    if (TASK_ACTIONS.test(action)) {
      taskEvents.value = [...taskEvents.value, row]
      if (row.taskId) {
        const bucket = byTask.value[row.taskId] ?? []
        if (!bucket.some((item) => item.seq === row.seq)) {
          byTask.value = { ...byTask.value, [row.taskId]: [...bucket, row] }
        }
      }
      lastUpdate.value = row.timestamp
      return
    }
    if (GATE_ACTIONS.test(action)) {
      if (!gateEvents.value.some((item) => item.seq === row.seq)) {
        gateEvents.value = [...gateEvents.value, row]
      }
      if (row.taskId) {
        const bucket = byTask.value[row.taskId] ?? []
        if (!bucket.some((item) => item.seq === row.seq)) {
          byTask.value = { ...byTask.value, [row.taskId]: [...bucket, row] }
        }
      }
    }
  }

  /** 批量接入（首屏全量 / 重连增量补拉） */
  function ingest(rows: EventRow[]): void {
    for (const row of rows) pushEvent(row)
  }

  function eventsOf(taskId: string): EventRow[] {
    return byTask.value[taskId] ?? []
  }

  function lastEventOf(taskId: string): EventRow | null {
    const bucket = eventsOf(taskId)
    return bucket.length ? bucket[bucket.length - 1] : null
  }

  async function loadDetail(taskId: string): Promise<TaskDetail | null> {
    try {
      const result = await api.getTask(taskId)
      if (result.task) {
        details.value = { ...details.value, [taskId]: result.task }
        return result.task
      }
      return null
    } catch {
      return null
    }
  }

  async function dispatch(taskId: string): Promise<{ ok: boolean; message: string }> {
    try {
      const result = await api.dispatchTask(taskId)
      const ok = Boolean((result as { ok?: boolean }).ok)
      return { ok, message: ok ? `${taskId} 派工已提交` : String((result as { reason?: string }).reason ?? '派工未成功') }
    } catch (error) {
      return { ok: false, message: error instanceof Error ? error.message : '派工失败' }
    }
  }

  function clear(): void {
    taskEvents.value = []
    byTask.value = {}
    gateEvents.value = []
    details.value = {}
  }

  return {
    taskEvents,
    byTask,
    gateEvents,
    details,
    lastUpdate,
    eventCount,
    has,
    pushEvent,
    ingest,
    eventsOf,
    lastEventOf,
    loadDetail,
    dispatch,
    clear,
  }
})
