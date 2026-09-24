/**
 * useChatStore · 对话历史
 *
 * 缺陷修复：旧版只保留最近 300 条事件。本 store 全量保留，并用“分页加载”+ 触底续载
 * 代替截断（首屏只渲染最新一页，向上滚动按需追加更早的一页）。
 */
import { computed, ref } from 'vue'
import { defineStore } from 'pinia'
import { api, USE_MOCK } from '@/api/client'
import type { EventRow } from '@/api/types'

const CHAT_ACTIONS = new Set(['chat', 'chat_reply'])

/** 增量流来源：server = 真实 WS 推送；injected = 调试/测试注入（后端生产方缺位时的验证手段） */
export type ChatStreamSource = 'server' | 'injected'

export interface ChatStreamState {
  /** 已累积的增量文本 */
  text: string
  /** 是否仍在流式接收中 */
  active: boolean
  /** 所属消息标识 */
  messageId: string
  /** 来源 */
  source: ChatStreamSource
  /** 已收到的增量帧数（用于证据与去抖） */
  chunks: number
  /** 最后一帧到达时间（ISO） */
  lastAt: string
}

function emptyStream(): ChatStreamState {
  return { text: '', active: false, messageId: '', source: 'injected', chunks: 0, lastAt: '' }
}

export const useChatStore = defineStore('chat', () => {
  /** 全量对话事件（升序），永不截断 */
  const all = ref<EventRow[]>([])
  /** 当前渲染条数（从尾部往前“页”增量放开） */
  const pageSize = ref(40)
  const visibleCount = ref(40)
  const sending = ref(false)
  const lastError = ref('')
  const lastReplyAt = ref('')
  /** stream_chunk 累积态（§9.6） */
  const stream = ref<ChatStreamState>(emptyStream())

  const total = computed(() => all.value.length)

  /** 当前可见窗口（末尾 visibleCount 条） */
  const messages = computed<EventRow[]>(() => {
    if (all.value.length <= visibleCount.value) return all.value
    return all.value.slice(all.value.length - visibleCount.value)
  })

  const hasOlder = computed(() => all.value.length > visibleCount.value)

  /** 是否正在流式输出（供页面展示“正在输入”指示） */
  const streaming = computed(() => stream.value.active || Boolean(stream.value.text))

  function roleOf(row: EventRow): 'user' | 'manager' {
    return row.action === 'chat' ? 'user' : 'manager'
  }

  function pushEvent(row: EventRow): void {
    if (!CHAT_ACTIONS.has(String(row.action ?? ''))) return
    if (all.value.some((item) => item.seq === row.seq)) return
    all.value = [...all.value, row]
    if (row.action === 'chat_reply') {
      lastReplyAt.value = row.timestamp
      // 完整回执已落事件流 → 清空增量缓冲，避免与历史气泡重复显示
      stream.value = emptyStream()
    }
  }

  function ingest(rows: EventRow[]): void {
    for (const row of rows) pushEvent(row)
  }

  /** 接收一帧 stream_chunk：追加增量；done=true 表示本条消息结束 */
  function appendChunk(
    delta: string,
    options: { done?: boolean; messageId?: string | number | null; source?: ChatStreamSource } = {},
  ): void {
    const text = String(delta ?? '')
    const done = Boolean(options.done)
    stream.value = {
      text: stream.value.text + text,
      active: !done,
      messageId: options.messageId !== undefined && options.messageId !== null ? String(options.messageId) : stream.value.messageId,
      source: options.source ?? stream.value.source,
      chunks: stream.value.chunks + 1,
      lastAt: new Date().toISOString(),
    }
  }

  function resetStream(): void {
    stream.value = emptyStream()
  }

  /** 向上加载更早一页（不截断任何历史） */
  function loadOlder(): void {
    visibleCount.value = Math.min(all.value.length, visibleCount.value + pageSize.value)
  }

  async function send(project: string | undefined, message: string, via?: (payload: unknown) => boolean): Promise<boolean> {
    const text = message.trim()
    if (!text || sending.value) return false
    sending.value = true
    lastError.value = ''
    try {
      const delivered = via ? via({ type: 'chat', project, message: text }) : false
      if (delivered) return true
      // WS 不可用则走 REST，服务端同样会写入事件流
      await api.chat(project, text)
      return true
    } catch (error) {
      lastError.value = error instanceof Error ? error.message : '发送失败'
      return false
    } finally {
      sending.value = false
    }
  }

  function clear(): void {
    all.value = []
    visibleCount.value = pageSize.value
  }

  return {
    all,
    messages,
    total,
    pageSize,
    visibleCount,
    hasOlder,
    sending,
    lastError,
    lastReplyAt,
    stream,
    streaming,
    useMock: USE_MOCK,
    roleOf,
    pushEvent,
    ingest,
    appendChunk,
    resetStream,
    loadOlder,
    send,
    clear,
  }
})
