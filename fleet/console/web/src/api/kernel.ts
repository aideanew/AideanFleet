/**
 * Kernel 投影 API（TASK-104）。只用 packages/contracts 生成的类型（types.ts），
 * 禁止在本文件手写与契约重复的接口类型（守门口径见 TASK-104 验收）。
 */

import { request } from './client'
import type {
  AttentionResponse,
  GoalsCreateRequest,
  GoalsCreateResponse,
  GoalsListResponse,
  EventsListResponse,
  TodosGetResponse,
  TodosListResponse,
  TodosReopenResponse,
} from './types'

export function createGoal(body: GoalsCreateRequest, idempotencyKey: string): Promise<GoalsCreateResponse> {
  return request<GoalsCreateResponse>('/api/kernel/goals', {
    method: 'POST',
    headers: { 'Idempotency-Key': idempotencyKey },
    body: JSON.stringify(body),
  })
}

export function listGoals(params: { limit?: number; cursor?: string } = {}): Promise<GoalsListResponse> {
  const search = new URLSearchParams()
  if (params.limit) search.set('limit', String(params.limit))
  if (params.cursor) search.set('cursor', params.cursor)
  const query = search.toString()
  return request<GoalsListResponse>(`/api/kernel/goals${query ? `?${query}` : ''}`)
}

export function attention(): Promise<AttentionResponse> {
  return request<AttentionResponse>('/api/kernel/attention')
}

export function listTodos(params: { goal_id?: string; status?: string; limit?: number; cursor?: string } = {}): Promise<TodosListResponse> {
  const search = new URLSearchParams()
  for (const [key, value] of Object.entries(params)) {
    if (value !== undefined && value !== null && `${value}` !== '') search.set(key, String(value))
  }
  const query = search.toString()
  return request<TodosListResponse>(`/api/kernel/todos${query ? `?${query}` : ''}`)
}

export function getTodo(todoId: string): Promise<TodosGetResponse> {
  return request<TodosGetResponse>(`/api/kernel/todos/${encodeURIComponent(todoId)}`)
}

export function reopenTodo(todoId: string): Promise<TodosReopenResponse> {
  return request<TodosReopenResponse>(`/api/kernel/todos/${encodeURIComponent(todoId)}/reopen`, {
    method: 'POST',
  })
}

export function listKernelEvents(limit = 100): Promise<EventsListResponse> {
  return request<EventsListResponse>(`/api/kernel/events?limit=${limit}`)
}
