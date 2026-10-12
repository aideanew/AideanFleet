/**
 * useWebSocket · 实时通道（工作包 §9.4-2）
 *
 * 职责：
 *  1. 消费服务端消息（task_update / progress / plan_update / config_changed /
 *     chat_message / notification）并分发到对应 store —— 不再有“非步骤事件笼统塞 detail”；
 *  2. 断线指数退避重连（1→2→4→8→16→30 秒，上限 30s）；
 *  3. 重连成功后用 GET /api/events?since=<seq> 增量补拉，保证不丢事件；
 *  4. WS 不可用时降级为 1 秒轮询，且 plan 只在“确有事件到达”时刷新，不再每秒全量拉。
 */
import { computed, ref } from 'vue'
import { api, USE_MOCK, wsUrl } from '@/api/client'
import { useAuthStore } from '@/stores/auth'
import { useChatStore } from '@/stores/chat'
import { useConfigStore } from '@/stores/config'
import { useConnectionStore } from '@/stores/connection'
import { useExecutionStore } from '@/stores/execution'
import { usePlanStore } from '@/stores/plan'
import { useTaskStore } from '@/stores/task'
import type { EventRow, WsServerMessage } from '@/api/types'

const BACKOFF = [1, 2, 4, 8, 16, 30]
const MAX_BACKOFF = 30
/** 连续重连超过该次数后改用轮询兜底 */
const POLL_AFTER_RETRIES = 4

const socket = ref<WebSocket | null>(null)
const connected = ref(false)
const polling = ref(false)

let retryIndex = 0
let reconnectTimer: ReturnType<typeof setTimeout> | null = null
let countdownTimer: ReturnType<typeof setInterval> | null = null
let pollTimer: ReturnType<typeof setInterval> | null = null
let planRefreshTimer: ReturnType<typeof setTimeout> | null = null
let heartbeatTimer: ReturnType<typeof setInterval> | null = null
let started = false
let mockSocket: { close(): void; send(data: string): void } | null = null
/** 注入 stream_chunk 期间为真，用于如实标注来源（不能冒充服务端推送） */
let injecting = false
let networkListenersInstalled = false

/* ------------------------------ 内部工具 ------------------------------ */

function stores() {
  return {
    auth: useAuthStore(),
    connection: useConnectionStore(),
    plan: usePlanStore(),
    task: useTaskStore(),
    chat: useChatStore(),
    config: useConfigStore(),
    execution: useExecutionStore(),
  }
}

function clearTimers(): void {
  if (reconnectTimer) clearTimeout(reconnectTimer)
  if (countdownTimer) clearInterval(countdownTimer)
  if (pollTimer) clearInterval(pollTimer)
  if (planRefreshTimer) clearTimeout(planRefreshTimer)
  reconnectTimer = null
  countdownTimer = null
  pollTimer = null
  planRefreshTimer = null
}

/** plan 刷新做 300ms 去抖，避免事件风暴下反复拉取 */
function schedulePlanRefresh(project?: string): void {
  if (planRefreshTimer) clearTimeout(planRefreshTimer)
  planRefreshTimer = setTimeout(() => {
    void stores().plan.load(project)
  }, 300)
}

/* ------------------------------ 事件分发 ------------------------------ */

function dispatchEvent(row: EventRow): void {
  const s = stores()
  const action = String(row.action ?? '')

  // 全量事件都要推进游标（用于断线增量补拉）；按事件所属项目记账，
  // 不带 project 的全局事件（mode:changed 等）不污染任何项目游标
  s.connection.markEvent(Number(row.seq) || 0, String(row.timestamp ?? ''), String(row.project ?? ''))

  if (action === 'chat' || action === 'chat_reply') {
    s.chat.pushEvent(row)
    return
  }
  // 任务级 / 机器门 / 启动 / 模式 / 确认 全部走结构化分桶
  s.task.pushEvent(row)
  s.execution.pushEvent(row)
}

function handleMessage(message: WsServerMessage): void {
  const s = stores()
  const row = (message as { event?: EventRow }).event
  // 项目隔离：丢弃非当前项目的推送
  const msgProject = (message as { project?: string }).project
  if (msgProject && s.auth.project && msgProject !== s.auth.project) {
    return
  }
  switch (message.type) {
    case 'plan_update': {
      const payload = message as { plan?: unknown }
      s.plan.apply(payload.plan as never, s.auth.project)
      break
    }
    case 'progress': {
      const payload = message as { percent?: number; project?: string }
      // 服务端聚合值与本地阶段聚合同源；不一致时以事件驱动刷新 plan 校正
      const serverPercent = Number(payload.percent ?? 0)
      if (Math.abs(serverPercent - s.plan.percent) > 0.01) {
        schedulePlanRefresh(payload.project)
      }
      break
    }
    case 'config_changed': {
      const section = (message as { section?: string }).section
      if (section === 'extensions') void s.config.loadExtensions()
      else void s.config.loadAll()
      break
    }
    case 'chat_message': {
      if (row) s.chat.pushEvent(row)
      break
    }
    case 'stream_chunk': {
      // §9.6 增量文本流。生产方现存缺位（server.py 未广播该类型，INT-04 REWORK），
      // 客户端先按契约形状完整实现；来源只认「真实 socket 送达」，其余一律标 injected。
      const payload = message as { delta?: string; done?: boolean; messageId?: string | number | null }
      s.chat.appendChunk(String(payload.delta ?? ''), {
        done: Boolean(payload.done),
        messageId: payload.messageId ?? null,
        source: injecting || USE_MOCK ? 'injected' : 'server',
      })
      break
    }
    case 'task_update': {
      if (row) dispatchEvent(row)
      else {
        const taskId = (message as { taskId?: string }).taskId
        if (taskId) schedulePlanRefresh()
      }
      break
    }
    case 'notification': {
      const mode = (message as { mode?: string | null }).mode
      if (mode) s.execution.setMode(mode === 'step' ? 'step' : 'auto')
      const sessionSwitch = (message as { session_switch?: boolean }).session_switch
      if (sessionSwitch) {
        // 会话切换通知：强制刷新计划并重置连接游标
        s.connection.reset()
        void s.plan.load(s.auth.project)
      }
      if (row) s.execution.pushEvent(row)
      break
    }
    default: {
      // 未知类型不丢弃：按通用事件处理，便于后端扩展
      if (row) dispatchEvent(row)
      break
    }
  }
}

/* ------------------------------ 增量补拉 ------------------------------ */

async function catchUp(): Promise<void> {
  const s = stores()
  if (!s.auth.unlocked) return
  try {
    const result = await api.getEvents(s.auth.project || undefined, s.connection.lastSeq)
    applyCatchUp(result.events ?? [])
    if (result.events?.length) schedulePlanRefresh(s.auth.project)
  } catch (err) {
    console.warn('[WebSocket] catchUp failed:', err)
  }
}

function applyCatchUp(rows: EventRow[]): void {
  const s = stores()
  const ordered = [...rows].sort((a, b) => a.seq - b.seq)
  for (const row of ordered) dispatchEvent(row)
  s.task.ingest(ordered)
  s.chat.ingest(ordered)
  s.execution.ingest(ordered)
}

/* ------------------------------ 轮询兜底 ------------------------------ */

function startPolling(): void {
  const s = stores()
  if (polling.value) return
  polling.value = true
  s.connection.setState('polling')
  if (pollTimer) clearInterval(pollTimer)
  pollTimer = setInterval(async () => {
    if (!s.auth.unlocked) return
    try {
      const result = await api.getEvents(s.auth.project || undefined, s.connection.lastSeq)
      const rows = result.events ?? []
      if (rows.length) {
        applyCatchUp(rows)
        // plan 只在“收到事件”时刷新
        schedulePlanRefresh(s.auth.project)
      }
    } catch (err) {
      console.warn('[WebSocket] poll failed:', err)
    }
  }, 1000)
}

function stopPolling(): void {
  polling.value = false
  if (pollTimer) clearInterval(pollTimer)
  pollTimer = null
}

/* ------------------------------ 连接生命周期 ------------------------------ */

function scheduleReconnect(): void {
  const s = stores()
  const delay = BACKOFF[Math.min(retryIndex, BACKOFF.length - 1)] ?? MAX_BACKOFF
  retryIndex += 1
  s.connection.retryCount = retryIndex
  s.connection.setState('reconnecting')
  if (reconnectTimer) clearTimeout(reconnectTimer)
  let remain = delay
  s.connection.retryIn = remain
  if (countdownTimer) clearInterval(countdownTimer)
  countdownTimer = setInterval(() => {
    remain -= 1
    s.connection.retryIn = Math.max(0, remain)
  }, 1000)
  reconnectTimer = setTimeout(() => {
    if (countdownTimer) clearInterval(countdownTimer)
    connect()
  }, delay * 1000)

  if (retryIndex >= POLL_AFTER_RETRIES) {
    // 连续失败 → 轮询兜底，保证功能可用
    startPolling()
  }
}

function onOpen(): void {
  const s = stores()
  retryIndex = 0
  s.connection.retryCount = 0
  s.connection.retryIn = 0
  connected.value = true
  stopPolling()
  s.connection.setState('online')
  void catchUp()
}

function onClose(): void {
  connected.value = false
  socket.value = null
  scheduleReconnect()
}

function connect(): void {
  const s = stores()
  if (!s.auth.unlocked || !s.auth.token) {
    s.connection.setState('offline')
    return
  }
  if (socket.value || mockSocket) return
  s.connection.setState('connecting')

  if (USE_MOCK) {
    void import('@/mock/ws').then(({ MockSocket }) => {
      const fake = new MockSocket()
      fake.onopen = () => onOpen()
      fake.onmessage = (event) => {
        try {
          handleMessage(JSON.parse(String((event as MessageEvent).data)) as WsServerMessage)
        } catch (err) {
          console.debug('[WebSocket] malformed message:', err)
        }
      }
      fake.onclose = () => {
        mockSocket = null
        onClose()
      }
      mockSocket = fake
    })
    return
  }

  try {
    const real = new WebSocket(wsUrl(s.auth.token))
    real.onopen = () => onOpen()
    real.onmessage = (event) => {
      try {
        handleMessage(JSON.parse(String(event.data)) as WsServerMessage)
      } catch (err) {
        console.debug('[WebSocket] malformed message:', err)
      }
    }
    real.onclose = () => onClose()
    real.onerror = () => {
      /* onclose 会紧随其后，统一在那里重连 */
    }
    socket.value = real
  } catch (err) {
    console.warn('[WebSocket] connect failed:', err)
    scheduleReconnect()
  }
}

/** 客户端 → 服务端 3 种消息（chat / set_mode / confirm_step） */
function send(payload: unknown): boolean {
  const text = JSON.stringify(payload)
  if (USE_MOCK) {
    if (!mockSocket) return false
    mockSocket.send(text)
    return true
  }
  if (!socket.value || socket.value.readyState !== WebSocket.OPEN) return false
  socket.value.send(text)
  return true
}

function disconnect(): void {
  clearTimers()
  stopPolling()
  if (mockSocket) {
    mockSocket.close()
    mockSocket = null
  }
  if (socket.value) {
    socket.value.onclose = null
    socket.value.close()
    socket.value = null
  }
  connected.value = false
  retryIndex = 0
  // 复位 started 守卫：disconnect 后允许 start() 重新执行，
  // 否则「切换项目 → disconnect → start」会因幂等守卫直接返回，实时通道永久断链（缺陷④）
  started = false
  useConnectionStore().setState('offline')
}

/**
 * 注入一帧（或多帧）stream_chunk，走与真实 WS 完全相同的 handleMessage 路径。
 * 用途：真实服务端尚不产出该类型（INT-04 REWORK），此为**自动化验证手段**，
 * 不改变业务逻辑；来源标记为 injected，页面会如实显示，不冒充服务端推送。
 */
function injectStream(deltas: string[], done = true): number {
  const list = deltas.length ? deltas : ['']
  injecting = true
  try {
    list.forEach((delta, index) => {
      const last = index === list.length - 1
      handleMessage({
        type: 'stream_chunk',
        delta,
        done: last ? done : false,
        messageId: 'inject-probe',
        role: 'Manager',
      } as never)
    })
  } finally {
    injecting = false
  }
  return list.length
}

/** 关闭本地 socket 句柄（不触发 onclose 重连链，由调用方决定后续状态） */
function teardownSocket(): void {
  if (mockSocket) {
    mockSocket.close()
    mockSocket = null
  }
  if (socket.value) {
    socket.value.onclose = null
    socket.value.close()
    socket.value = null
  }
  connected.value = false
}

/**
 * 浏览器原生网络信号（§9.2 断网重连的可靠触发源）。
 *
 * 为什么必须监听它：Chromium 在「网络离线」时**不会**主动断开已建立的 WebSocket，
 * 单纯依赖 onclose 只能等 TCP 超时（分钟级），期间界面会一直谎报「已连接」。
 * 因此：
 *   · offline → 立刻判定链路失效，收掉 socket 句柄并置为「未连接」，不再空转退避；
 *   · online  → 立刻重试（不必等满退避），连上后照常走 since 增量补拉。
 */
function installNetworkListeners(): void {
  if (networkListenersInstalled || typeof window === 'undefined') return
  networkListenersInstalled = true

  window.addEventListener('offline', () => {
    const s = stores()
    if (!s.auth.unlocked) return
    teardownSocket()
    if (reconnectTimer) clearTimeout(reconnectTimer)
    if (countdownTimer) clearInterval(countdownTimer)
    reconnectTimer = null
    countdownTimer = null
    stopPolling()
    s.connection.retryCount = retryIndex
    s.connection.setState('offline')
  })

  window.addEventListener('online', () => {
    const s = stores()
    if (!s.auth.unlocked) return
    retryIndex = 0
    s.connection.retryCount = 0
    s.connection.retryIn = 0
    if (socket.value || mockSocket) void catchUp()
    else {
      s.connection.setState('connecting')
      connect()
    }
  })
}

function start(): void {
  if (started) return
  started = true
  const s = stores()
  // 调试/测试钩子：注入 stream_chunk（与 window.__mockKick 同一性质）
  ;(window as unknown as Record<string, unknown>).__fleetInjectStream = injectStream
  installNetworkListeners()
  // 会话心跳：每秒推进倒计时 + 过期自动回锁屏
  if (heartbeatTimer) clearInterval(heartbeatTimer)
  heartbeatTimer = setInterval(() => {
    s.auth.tick()
    if (!s.auth.unlocked) disconnect()
  }, 1000)
}

export function useWebSocket() {
  return {
    connected: computed(() => connected.value),
    polling: computed(() => polling.value),
    start,
    connect,
    disconnect,
    send,
    catchUp,
    injectStream,
    /** 供设置页/调试使用：模拟一次服务端断开，验证指数退避重连 */
    simulateDrop: () => {
      if (USE_MOCK) {
        mockSocket?.close()
        mockSocket = null
        return
      }
      socket.value?.close()
    },
  }
}
