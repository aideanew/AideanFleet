import { reactive, readonly } from 'vue'

export type ToastTone = 'ok' | 'danger' | 'warn' | 'info'

export interface ToastItem {
  id: number
  tone: ToastTone
  title: string
  detail: string
  ttl: number
}

const items = reactive<ToastItem[]>([])
let nextId = 1

export function dismissToast(id: number): void {
  const index = items.findIndex((item) => item.id === id)
  if (index >= 0) items.splice(index, 1)
}

export function pushToast(
  title: string,
  options: { tone?: ToastTone; detail?: string; ttl?: number } = {},
): number {
  const ttl = options.ttl ?? 3600
  const id = nextId++
  items.push({ id, tone: options.tone ?? 'info', title, detail: options.detail ?? '', ttl })
  if (ttl > 0) {
    window.setTimeout(() => dismissToast(id), ttl)
  }
  return id
}

/** 统一入口：成功/失败/警告/提示，全部中文提示（工作包 §9.5-4「错误必提示」） */
export const toast = {
  ok: (title: string, detail = '') => pushToast(title, { tone: 'ok', detail }),
  fail: (title: string, detail = '') => pushToast(title, { tone: 'danger', detail, ttl: 5200 }),
  warn: (title: string, detail = '') => pushToast(title, { tone: 'warn', detail, ttl: 4600 }),
  info: (title: string, detail = '') => pushToast(title, { tone: 'info', detail }),
}

export function useToast() {
  return { toasts: readonly(items), pushToast, dismissToast, toast }
}
