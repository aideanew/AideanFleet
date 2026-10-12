/**
 * useConfigStore · 七段配置 + 拓展 + 通知触发
 *
 * 掩码规则（工作包 §10-3）：api_key / 授权码在页面源码、网络响应、localStorage 中零明文，
 * 回显一律为 ${VAR} 占位；提交时占位值视为“未修改”，不下发、不覆盖。
 *
 * 通知开关（UI-03R §9.4 收口）：6 项**全部**取后端真实值，**零 localStorage**。
 *   实测契约（2026-09-15，带有效令牌）：
 *     GET  /api/config/notify   → {on_task_start,on_task_end,on_manager_quota,on_role_quota}
 *     POST /api/config/notify   → {applied:{...}, ignored:[...]}（键必须为 snake_case 短键）
 *     GET  /api/notify/triggers → {task_started,task_completed,manager_quota_low,
 *                                  worker_quota_low,task_escalated,daily_summary,task_failed}
 *                                 source = <root>/config/notifications.json
 *   因此：
 *     · 4 项（on_*）走 /api/config/notify，**可写**，落 .env 的 [SECTION: notify]；
 *     · 2 项（task_escalated / daily_summary）走 /api/notify/triggers，**真实只读**
 *       （POST /api/config/notify 对这两个键返回 ignored，后端暂无写路径）。
 */
import { computed, ref } from 'vue'
import { defineStore } from 'pinia'
import { api } from '@/api/client'
import { isMaskedPlaceholder } from '@/utils/labels'
import type {
  ConfigSectionName,
  EmailConfig,
  ExecutorItem,
  ExtensionsMap,
  ModelItem,
  NotifyTriggerItem,
  RequestConfig,
  RoleItem,
} from '@/api/types'

/** 开关取值来源：env = .env 可写；triggers = config/notifications.json 只读 */
export type NotifySwitchSource = 'env' | 'triggers'

export interface NotifySwitch {
  key: string
  label: string
  hint: string
  defaultState: boolean
  source: NotifySwitchSource
  /** 后端触发器清单里的对应键（source=triggers 时使用） */
  triggerKey?: string
}

export const useConfigStore = defineStore('config', () => {
  const models = ref<ModelItem[]>([])
  const roles = ref<RoleItem[]>([])
  const executors = ref<ExecutorItem[]>([])
  const email = ref<EmailConfig | null>(null)
  const request = ref<RequestConfig | null>(null)
  const notify = ref<Record<string, boolean>>({
    on_task_start: false,
    on_task_end: true,
    on_manager_quota: true,
    on_role_quota: true,
  })
  const extensions = ref<ExtensionsMap>({})
  const notifyTriggers = ref<Record<string, NotifyTriggerItem>>({})
  const notifyTriggerSource = ref('')
  const envSource = ref('')
  const envMtime = ref<string | null>(null)
  const loading = ref(false)
  const lastError = ref('')

  /** 密钥字段是否已配置（占位但可解析 → 视为已配置） */
  const smtpConfigured = computed(() => {
    if (!email.value) return false
    return Boolean(email.value.sender && email.value.receiver && email.value.auth_code)
  })

  /**
   * 6 项通知开关（顺序固定：4 项 .env 可写 + 2 项触发器只读）。
   * 全部值来自后端，不存在任何本地兜底状态。
   */
  const notifySwitches = computed<NotifySwitch[]>(() => [
    {
      key: 'on_task_start',
      label: '任务开始时提醒',
      hint: '项目开始执行时发一封邮件',
      defaultState: false,
      source: 'env',
    },
    {
      key: 'on_task_end',
      label: '任务结束时提醒',
      hint: '全部任务收口后发一封邮件',
      defaultState: true,
      source: 'env',
    },
    {
      key: 'on_manager_quota',
      label: 'Manager 模型额度不足',
      hint: 'Manager 所用模型额度耗尽时提醒',
      defaultState: true,
      source: 'env',
    },
    {
      key: 'on_role_quota',
      label: '执行角色模型额度不足',
      hint: '任一执行角色模型额度耗尽时提醒',
      defaultState: true,
      source: 'env',
    },
    {
      key: 'on_task_escalated',
      label: '任务升级人工（ESCALATED）',
      hint: '返工超过 3 次升级为人工介入时提醒',
      defaultState: true,
      source: 'triggers',
      triggerKey: 'task_escalated',
    },
    {
      key: 'daily_summary',
      label: '每日 20:00 汇总',
      hint: '每天 20:00 汇总当日进度与遗留项',
      defaultState: false,
      source: 'triggers',
      triggerKey: 'daily_summary',
    },
  ])

  /** 可写开关（走 .env）的键集合 */
  const writableNotifyKeys = computed(() =>
    notifySwitches.value.filter((item) => item.source === 'env').map((item) => item.key),
  )

  /** 读取某个开关的真实值；找不到时回落到 defaultState（仍是契约默认，而非本地缓存） */
  function readNotifySwitch(key: string): boolean {
    const def = notifySwitches.value.find((item) => item.key === key)
    if (!def) return false
    if (def.source === 'triggers' && def.triggerKey) {
      const record = notifyTriggers.value[def.triggerKey]
      if (record && typeof record.enabled === 'boolean') return record.enabled
      return def.defaultState
    }
    if (Object.prototype.hasOwnProperty.call(notify.value, key)) return Boolean(notify.value[key])
    return def.defaultState
  }

  /** 开关是否可写（triggers 来源为后端只读） */
  function isNotifyWritable(key: string): boolean {
    const def = notifySwitches.value.find((item) => item.key === key)
    return def ? def.source === 'env' : false
  }

  /**
   * 写入开关：**只写内存 + 后端**，不落 localStorage。
   * 只读项直接忽略；调用方据 isNotifyWritable 决定是否禁用 UI。
   */
  function writeNotifySwitch(key: string, value: boolean): void {
    if (!isNotifyWritable(key)) return
    notify.value = { ...notify.value, [key]: value }
  }

  async function loadAll(): Promise<void> {
    loading.value = true
    lastError.value = ''
    try {
      const [modelRes, roleRes, executorRes, emailRes, requestRes, notifyRes] = await Promise.all([
        api.getConfig<{ models: ModelItem[] }>('model_pool'),
        api.getConfig<{ roles: RoleItem[] }>('roles'),
        api.getConfig<{ executors: ExecutorItem[] }>('executors'),
        api.getConfig<EmailConfig>('email'),
        api.getConfig<RequestConfig>('request'),
        api.getConfig<Record<string, boolean>>('notify'),
      ])
      models.value = modelRes.data?.models ?? []
      roles.value = roleRes.data?.roles ?? []
      executors.value = executorRes.data?.executors ?? []
      email.value = emailRes.data
      request.value = requestRes.data
      notify.value = { ...notify.value, ...(notifyRes.data ?? {}) }
      envSource.value = modelRes.source ?? ''
      envMtime.value = modelRes.mtime ?? null
    } catch (error) {
      lastError.value = error instanceof Error ? error.message : '配置加载失败'
    } finally {
      loading.value = false
    }
  }

  async function loadExtensions(): Promise<void> {
    try {
      const result = await api.getExtensions()
      extensions.value = result.data ?? {}
    } catch (error) {
      lastError.value = error instanceof Error ? error.message : '拓展配置加载失败'
    }
  }

  async function loadNotifyTriggers(): Promise<void> {
    try {
      const result = await api.notifyTriggers()
      const data = result.data
      notifyTriggers.value = Array.isArray(data) ? {} : (data ?? {})
      notifyTriggerSource.value = result.source ?? ''
    } catch {
      notifyTriggers.value = {}
      notifyTriggerSource.value = ''
    }
  }

  async function saveModels(next: ModelItem[]): Promise<string> {
    const payload = next.map((item) => ({
      name: item.name,
      level: item.level,
      base_url: item.base_url,
      model_id: item.model_id,
      // 掩码值视为未修改：回传原占位串，后端不会写入明文
      api_key: item.api_key,
      http_proxy: item.http_proxy,
      https_proxy: item.https_proxy,
    }))
    const result = await api.saveModels(payload as ModelItem[])
    models.value = next
    return summarize(result.ignored)
  }

  async function saveRoles(next: RoleItem[]): Promise<string> {
    const result = await api.saveRoles(next)
    roles.value = next
    return summarize(result.ignored)
  }

  async function saveExecutors(next: ExecutorItem[]): Promise<string> {
    const result = await api.saveExecutors(next)
    executors.value = next
    return summarize(result.ignored)
  }

  async function saveEmail(next: EmailConfig): Promise<string> {
    const result = await api.saveConfig('email', next as unknown as Record<string, unknown>)
    email.value = next
    return summarize(result.ignored)
  }

  async function saveRequest(next: RequestConfig): Promise<string> {
    const result = await api.saveConfig('request', next as unknown as Record<string, unknown>)
    request.value = next
    return summarize(result.ignored)
  }

  /**
   * 保存 4 项 .env 开关。只下发可写键，避免把只读键塞给后端换回一堆 ignored。
   * 返回体保留 ignored（后端若因契约漂移拒绝某键，页面必须如实提示，不得静默）。
   */
  async function saveNotify(): Promise<{
    message: string
    ignored: string[]
    applied: Record<string, boolean>
    mtime: string | null
  }> {
    const payload: Record<string, boolean> = {}
    for (const key of writableNotifyKeys.value) {
      payload[key] = Boolean(notify.value[key])
    }
    const result = await api.saveConfig('notify', payload)
    const ignored = result.ignored ?? []
    const applied = (result.applied && typeof result.applied === 'object' ? result.applied : {}) as Record<
      string,
      boolean
    >
    // 以服务端 applied 为准回填，保证页面显示 = 后端真实落盘值
    for (const [key, value] of Object.entries(applied)) {
      if (typeof value === 'boolean') notify.value = { ...notify.value, [key]: value }
    }
    envMtime.value = result.mtime ?? envMtime.value
    return { message: summarize(ignored), ignored, applied, mtime: result.mtime ?? null }
  }

  async function saveExtensions(next: ExtensionsMap): Promise<string> {
    const result = await api.saveExtensions(next)
    extensions.value = next
    return String((result as { message?: string }).message ?? '拓展配置已保存')
  }

  function summarize(ignored?: string[]): string {
    if (!ignored || !ignored.length) return '已保存'
    return `已保存（后端忽略了不支持的字段：${ignored.join('、')}）`
  }

  function isPlaceholder(value: string | undefined | null): boolean {
    return isMaskedPlaceholder(String(value ?? ''))
  }

  return {
    models,
    roles,
    executors,
    email,
    request,
    notify,
    extensions,
    notifyTriggers,
    notifyTriggerSource,
    envSource,
    envMtime,
    loading,
    lastError,
    smtpConfigured,
    notifySwitches,
    writableNotifyKeys,
    readNotifySwitch,
    writeNotifySwitch,
    isNotifyWritable,
    loadAll,
    loadExtensions,
    loadNotifyTriggers,
    saveModels,
    saveRoles,
    saveExecutors,
    saveEmail,
    saveRequest,
    saveNotify,
    saveExtensions,
    isPlaceholder,
  }
})

export type ConfigStore = ReturnType<typeof useConfigStore>
export type { ConfigSectionName }
