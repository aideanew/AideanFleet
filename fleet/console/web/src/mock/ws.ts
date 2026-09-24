/**
 * WS mock（工作包 UI-02 §9.1-3）：用本地定时器 + 事件回调模拟服务端 7 种消息推送，
 * 让 useWebSocket 在没有后端时也能走完全部实时链路（含断线重连与增量补拉）。
 */

import type { WsClientMessage, WsServerMessage } from '@/api/types'
import { mockAppendEvent, mockPlanSnapshot, mockSetTaskState } from './api'

export interface SocketLike {
  readyState: number
  send(data: string): void
  close(): void
  onopen: ((ev: Event) => void) | null
  onmessage: ((ev: MessageEvent) => void) | null
  onclose: ((ev: CloseEvent) => void) | null
  onerror: ((ev: Event) => void) | null
}

const CONNECTING = 0
const OPEN = 1
const CLOSING = 2
const CLOSED = 3

/** mock 的“实时心跳”：每 2 秒推进一个任务阶段，制造可见的事件与进度变化 */
const FLOW: Array<{ taskId: string; from: string; to: string; action: string; summary: string }> = [
  { taskId: 'T-004', from: 'REVIEWING', to: 'DONE', action: 'task:done', summary: 'T-004 审查 PASS' },
  { taskId: 'T-006', from: 'ASSIGNED', to: 'DOING', action: 'task:doing', summary: 'T-006 进入执行中' },
  { taskId: 'T-006', from: 'DOING', to: 'SUBMITTED', action: 'task:submitted', summary: 'T-006 已提交六节报告与证据' },
  { taskId: 'T-006', from: 'SUBMITTED', to: 'REVIEWING', action: 'task:reviewing', summary: 'T-006 转交审查' },
  { taskId: 'T-006', from: 'REVIEWING', to: 'DONE', action: 'task:done', summary: 'T-006 审查 PASS' },
  { taskId: 'T-007', from: 'DRAFT', to: 'ASSIGNED', action: 'task:assigned', summary: 'T-007 已派工给 fe-1' },
]

export class MockSocket implements SocketLike {
  readyState = CONNECTING
  onopen: ((ev: Event) => void) | null = null
  onmessage: ((ev: MessageEvent) => void) | null = null
  onclose: ((ev: CloseEvent) => void) | null = null
  onerror: ((ev: Event) => void) | null = null

  private openTimer: ReturnType<typeof setTimeout> | null = null
  private flowTimer: ReturnType<typeof setInterval> | null = null
  private flowIndex = 0

  constructor() {
    this.openTimer = setTimeout(() => {
      if (this.readyState === CLOSED) return
      this.readyState = OPEN
      this.onopen?.(new Event('open'))
      // 首帧：plan + progress + 一条 config_changed，模拟 server.py _event_pump 的启动行为
      this.emit({ type: 'plan_update', project: 'AideanFleet', plan: mockPlanSnapshot() })
      const snapshot = mockPlanSnapshot()
      this.emit({
        type: 'progress',
        project: snapshot.project,
        total: snapshot.total,
        done: snapshot.done,
        percent: snapshot.percent,
      })
      this.emit({ type: 'config_changed', mtime: new Date().toISOString() })
      this.flowTimer = setInterval(() => this.tick(), 2000)
    }, 120)
  }

  private emit(payload: WsServerMessage): void {
    if (this.readyState !== OPEN) return
    this.onmessage?.({ data: JSON.stringify(payload) } as MessageEvent)
  }

  private tick(): void {
    if (this.flowIndex >= FLOW.length) {
      // 剧本走完后只保留轻量心跳，避免无限循环制造重复事件
      const snapshot = mockPlanSnapshot()
      this.emit({
        type: 'progress',
        project: snapshot.project,
        total: snapshot.total,
        done: snapshot.done,
        percent: snapshot.percent,
      })
      return
    }
    const step = FLOW[this.flowIndex]
    this.flowIndex += 1
    mockSetTaskState(step.taskId, step.to as never)
    const row = mockAppendEvent({
      actor: step.action === 'task:done' ? 'reviewer-1' : 'manager',
      action: step.action,
      taskId: step.taskId,
      summary: step.summary,
      extra: { from: step.from, to: step.to },
    })
    this.emit({ type: 'task_update', event: row })
    const snapshot = mockPlanSnapshot()
    this.emit({ type: 'plan_update', project: snapshot.project, plan: snapshot })
    this.emit({
      type: 'progress',
      project: snapshot.project,
      total: snapshot.total,
      done: snapshot.done,
      percent: snapshot.percent,
    })
  }

  send(data: string): void {
    if (this.readyState !== OPEN) return
    let message: WsClientMessage
    try {
      message = JSON.parse(data) as WsClientMessage
    } catch {
      this.emit({ type: 'notification', error: '消息必须是 JSON 对象' })
      return
    }
    if (message.type === 'chat') {
      const text = String((message as { message?: string }).message || '')
      const row = mockAppendEvent({ actor: '用户', action: 'chat', summary: text || '(空消息)' })
      const reply = `【Manager·回执】已收到你的指令：「${text.slice(0, 80)}」。已进入事件流，调度器将据此调整任务计划。`
      const replyRow = mockAppendEvent({ actor: 'Manager', action: 'chat_reply', summary: reply })
      this.emit({ type: 'chat_message', event: row })
      // §9.6：先逐帧推送 stream_chunk，最后落完整 chat_reply 事件（与真实服务端完成态语义一致）
      const parts = reply.match(/[\s\S]{1,6}/g) ?? [reply]
      parts.forEach((delta, index) => {
        setTimeout(() => {
          this.emit({
            type: 'stream_chunk',
            delta,
            done: index === parts.length - 1,
            messageId: replyRow.seq,
            role: 'Manager',
          })
        }, 60 * (index + 1))
      })
      setTimeout(() => this.emit({ type: 'chat_message', event: replyRow }), 60 * (parts.length + 1))
      return
    }
    if (message.type === 'set_mode') {
      const raw = String((message as { mode?: string }).mode || '')
      const mode = raw === 'confirm' || raw === 'step' ? 'step' : 'auto'
      this.emit({ type: 'notification', mode })
      return
    }
    if (message.type === 'confirm_step') {
      const taskId = (message as { taskId?: string | null }).taskId ?? null
      const note = String((message as { note?: string }).note || '')
      const row = mockAppendEvent({
        actor: '用户',
        action: 'step_confirm',
        taskId,
        summary: note || '用户确认当前步骤',
      })
      this.emit({ type: 'notification', event: row })
      return
    }
    this.emit({ type: 'notification', error: `未知消息类型：${(message as { type?: string }).type}` })
  }

  close(): void {
    if (this.readyState === CLOSED) return
    this.readyState = CLOSED
    if (this.openTimer) clearTimeout(this.openTimer)
    if (this.flowTimer) clearInterval(this.flowTimer)
    this.openTimer = null
    this.flowTimer = null
    this.onclose?.(new CloseEvent('close', { code: 1000, wasClean: true }))
  }
}

/** 模拟服务端“踢下线”，用于验证指数退避重连（控制台可调 window.__mockKick()） */
export function installMockKick(getSocket: () => MockSocket | null): void {
  ;(window as unknown as Record<string, unknown>).__mockKick = () => {
    const socket = getSocket()
    socket?.close()
    return '已模拟服务端断开，客户端应进入重连'
  }
}
