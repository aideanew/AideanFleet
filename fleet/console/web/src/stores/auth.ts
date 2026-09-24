/**
 * useAuthStore · 会话与锁屏
 * 与 server.py 对齐：POST /api/session 换 token（有效期 = basic.lock_ttl_minutes*60），
 * token 存 sessionStorage（刷新保持、关标签页即失效），并提供倒计时。
 */
import { computed, ref } from 'vue'
import { defineStore } from 'pinia'
import { api, setAuthToken } from '@/api/client'

const TOKEN_KEY = 'fleet.token'
const PROJECT_KEY = 'fleet.project'

export const useAuthStore = defineStore('auth', () => {
  const token = ref('')
  const project = ref('')
  const expiresIn = ref(0)
  const unlocked = ref(false)
  const busy = ref(false)
  const lastError = ref('')

  /** 剩余秒数（由 connection store 的心跳每秒调用 tick()） */
  const remain = ref(0)

  const remainText = computed(() => {
    if (remain.value <= 0) return '已失效'
    const minutes = Math.floor(remain.value / 60)
    const seconds = remain.value % 60
    if (minutes >= 60) {
      const hours = Math.floor(minutes / 60)
      return `${hours} 小时 ${minutes % 60} 分`
    }
    return `${String(minutes).padStart(2, '0')}:${String(seconds).padStart(2, '0')}`
  })

  function apply(tokenValue: string, projectValue: string, seconds: number) {
    token.value = tokenValue
    project.value = projectValue
    expiresIn.value = seconds
    remain.value = seconds
    unlocked.value = true
    setAuthToken(tokenValue)
    try {
      window.sessionStorage.setItem(TOKEN_KEY, tokenValue)
      window.sessionStorage.setItem(PROJECT_KEY, projectValue)
    } catch {
      /* 忽略 */
    }
  }

  async function unlock(projectName: string): Promise<boolean> {
    busy.value = true
    lastError.value = ''
    try {
      const result = await api.createSession(projectName.trim())
      apply(result.token ?? '', result.project ?? projectName.trim(), result.expires_in ?? 3600)
      return true
    } catch (error) {
      lastError.value = error instanceof Error ? error.message : '解锁失败，请重试'
      return false
    } finally {
      busy.value = false
    }
  }

  async function lock(): Promise<void> {
    try {
      await api.deleteSession()
    } catch {
      /* 服务端不可达也要允许本地回锁屏 */
    }
    token.value = ''
    unlocked.value = false
    remain.value = 0
    setAuthToken('')
    try {
      window.sessionStorage.removeItem(TOKEN_KEY)
      window.sessionStorage.removeItem(PROJECT_KEY)
    } catch {
      /* 忽略 */
    }
  }

  /** 切换当前会话绑定的项目：服务端更新 session，本地同步并落 sessionStorage */
  async function switchTo(project: string): Promise<boolean> {
    busy.value = true
    lastError.value = ''
    try {
      const result = await api.switchSession(project.trim())
      apply(token.value, result.project ?? project.trim(), result.expires_in ?? expiresIn.value)
      return true
    } catch (error) {
      lastError.value = error instanceof Error ? error.message : '切换失败，请重试'
      return false
    } finally {
      busy.value = false
    }
  }

  /** 刷新页面后尝试用 sessionStorage 的令牌恢复会话 */
  async function restore(): Promise<boolean> {
    let savedToken = ''
    let savedProject = ''
    try {
      savedToken = window.sessionStorage.getItem(TOKEN_KEY) ?? ''
      savedProject = window.sessionStorage.getItem(PROJECT_KEY) ?? ''
    } catch {
      return false
    }
    if (!savedToken) return false
    // 先写回请求头再校验，避免首个请求 401
    setAuthToken(savedToken)
    try {
      const current = await api.getSession()
      apply(savedToken, current.project ?? savedProject, current.expires_in ?? 3600)
      return true
    } catch {
      setAuthToken('')
      try {
        window.sessionStorage.removeItem(TOKEN_KEY)
      } catch {
        /* 忽略 */
      }
      return false
    }
  }

  function tick(): void {
    if (!unlocked.value) return
    remain.value = Math.max(0, remain.value - 1)
    if (remain.value === 0) {
      unlocked.value = false
      setAuthToken('')
    }
  }

  return {
    token,
    project,
    expiresIn,
    remain,
    remainText,
    unlocked,
    busy,
    lastError,
    apply,
    unlock,
    lock,
    switchTo,
    restore,
    tick,
  }
})
