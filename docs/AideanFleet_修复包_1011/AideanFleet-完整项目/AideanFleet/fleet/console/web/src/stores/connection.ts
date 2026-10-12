/**
 * useConnectionStore · 实时通道状态
 * 记录 WS 连接状态、重连次数、事件游标；WS 不可用时降级为 1 秒轮询。
 */
import { computed, ref } from 'vue'
import { defineStore } from 'pinia'
import { useAuthStore } from '@/stores/auth'
import type { ConnectionState } from '@/api/types'

export const useConnectionStore = defineStore('connection', () => {
  const state = ref<ConnectionState>('connecting')
  const retryCount = ref(0)
  const retryIn = ref(0)
  /** 按项目隔离的事件游标 */
  const lastSeqMap = ref<Record<string, number>>({})
  const lastEventAt = ref<string>('')
  const droppedEvents = ref(0)

  const auth = useAuthStore()
  const project = computed(() => auth.project || '')

  const lastSeq = computed(() => lastSeqMap.value[project.value] ?? 0)

  const label = computed(() => {
    switch (state.value) {
      case 'online':
        return '● 已连接（WebSocket）'
      case 'connecting':
        return '● 正在连接…'
      case 'reconnecting':
        return retryIn.value > 0 ? `● 连接中断，${retryIn.value} 秒后重连` : '● 正在重连…'
      case 'polling':
        return '● 降级为轮询（1 秒）'
      default:
        return '● 未连接'
    }
  })

  const tone = computed(() => {
    if (state.value === 'online') return 'ok'
    if (state.value === 'polling') return 'warn'
    if (state.value === 'connecting') return 'info'
    return 'danger'
  })

  function setState(next: ConnectionState): void {
    state.value = next
  }

  /**
   * 推进事件游标。projectId 必须显式传入事件所属项目（4.1 修复）：
   * 旧版用 auth.project 作键，飞行中切项目时会把 A 项目的 seq 写进 B 的游标，
   * 抬高后 B 的增量补拉会漏事件。无法归属项目的事件（空 project 的全局事件）
   * 不记游标——它们也不参与按项目增量补拉。
   */
  function markEvent(seq: number, timestamp: string, projectId?: string): void {
    const proj = String(projectId ?? '')
    if (!proj) return
    const cur = lastSeqMap.value[proj] ?? 0
    if (seq > cur) {
      lastSeqMap.value = { ...lastSeqMap.value, [proj]: seq }
    }
    lastEventAt.value = timestamp
  }

  function reset(): void {
    retryCount.value = 0
    retryIn.value = 0
    // 清空当前项目的游标
    const proj = project.value
    if (proj && lastSeqMap.value[proj]) {
      const { [proj]: _, ...rest } = lastSeqMap.value
      lastSeqMap.value = rest
    }
  }

  function clearProject(projectId: string): void {
    if (lastSeqMap.value[projectId]) {
      const { [projectId]: _, ...rest } = lastSeqMap.value
      lastSeqMap.value = rest
    }
  }

  return { state, label, tone, retryCount, retryIn, lastSeq, lastEventAt, droppedEvents, setState, markEvent, reset, clearProject, lastSeqMap }
})
