<script setup lang="ts">
/**
 * NotificationsPage · 消息
 * 邮件提醒与触发条件。开关共 **6 项，全部取后端真实值，零 localStorage**：
 *   4 项（on_task_start / on_task_end / on_manager_quota / on_role_quota）
 *     → GET/POST /api/config/notify，落 .env 的 [SECTION: notify]，**可写**；
 *   2 项（任务升级人工 / 每日 20:00 汇总）
 *     → GET /api/notify/triggers，读 config/notifications.json，**后端只读**
 *       （POST /api/config/notify 对这两键返回 ignored，后端暂无写路径）。
 * 切换任一开关不再写任何浏览器存储；刷新后由接口重新取值。
 * 「发送测试邮件」按钮在 notify:ready 事件到达前保持置灰（角色C 的通知通道就绪信号）。
 */
import { computed, onMounted, ref } from 'vue'
import FormInput from '@/components/FormInput.vue'
import FormToggle from '@/components/FormToggle.vue'
import StatusBadge from '@/components/StatusBadge.vue'
import { api } from '@/api/client'
import { useConfigStore } from '@/stores/config'
import { useExecutionStore } from '@/stores/execution'
import { toast } from '@/composables/useToast'
import type { EmailConfig } from '@/api/types'

const config = useConfigStore()
const execution = useExecutionStore()

const saving = ref(false)
const testing = ref(false)
const email = ref<EmailConfig>({
  enabled: false,
  sender: '',
  receiver: '',
  host: '',
  port: 465,
  auth_code: '',
  use_ssl: true,
})
const beforeSave = ref<Record<string, boolean>>({})

const switches = computed(() => config.notifySwitches)
const canTest = computed(() => execution.notifyReady)
const readonlyCount = computed(() => switches.value.filter((item) => item.source === 'triggers').length)

/** 后端 /api/notify/triggers 返回的是 {小写下划线键: {enabled, default_enabled}}，无 event_type 字段 */
const TRIGGER_LABEL: Record<string, string> = {
  task_started: '任务开始',
  task_completed: '任务完成',
  task_failed: '任务失败',
  manager_quota_low: 'Manager 模型额度不足',
  worker_quota_low: '执行角色模型额度不足',
  task_escalated: '任务升级人工（ESCALATED）',
  daily_summary: '每日 20:00 汇总',
}

const triggers = computed(() =>
  Object.entries(config.notifyTriggers).map(([key, value]) => ({
    key,
    label: TRIGGER_LABEL[key] ?? key,
    enabled: Boolean(value?.enabled),
    defaultEnabled: Boolean((value as { default_enabled?: boolean })?.default_enabled),
  })),
)

async function loadEmail(): Promise<void> {
  try {
    const data = await api.getEmail()
    email.value = { ...email.value, ...data }
  } catch (error) {
    toast.fail('邮箱配置读取失败', error instanceof Error ? error.message : '')
  }
}

function onToggle(key: string, value: boolean): void {
  if (!beforeSave.value[key] && beforeSave.value[key] !== false) {
    beforeSave.value = { ...beforeSave.value, [key]: config.readNotifySwitch(key) }
  }
  config.writeNotifySwitch(key, value)
}

async function saveSwitches(): Promise<void> {
  saving.value = true
  try {
    const result = await config.saveNotify()
    if (result.ignored.length) {
      toast.warn('部分开关未生效', `后端拒绝了这些键：${result.ignored.join('、')}`)
    } else {
      toast.ok(
        '提醒开关已保存',
        `已写入 .env 的 notify 段（后端确认 ${Object.keys(result.applied).length} 项生效）`,
      )
    }
    beforeSave.value = {}
    // 以服务端实际落盘值重新拉取一次，杜绝“界面显示 ≠ 真实值”
    await config.loadAll()
  } catch (error) {
    toast.fail('保存失败', error instanceof Error ? error.message : '')
  } finally {
    saving.value = false
  }
}

async function saveEmail(): Promise<void> {
  saving.value = true
  try {
    if (email.value.auth_code && !email.value.auth_code.startsWith('${')) {
      toast.fail('拒绝写入明文授权码', '该字段只接受 ${环境变量名} 占位符')
      return
    }
    const message = await config.saveEmail({ ...email.value })
    toast.ok('邮箱配置已保存', message)
  } catch (error) {
    toast.fail('保存失败', error instanceof Error ? error.message : '')
  } finally {
    saving.value = false
  }
}

async function testEmail(): Promise<void> {
  testing.value = true
  try {
    const result = await api.notifyTest()
    const ok = Boolean((result as { ok?: boolean }).ok)
    if (ok) toast.ok('测试邮件已发送', String((result as { receiver?: string }).receiver ?? ''))
    else toast.fail('测试邮件未发送', String((result as { message?: string }).message ?? 'notify 通道未就绪'))
  } catch (error) {
    toast.fail('测试邮件发送失败', error instanceof Error ? error.message : '')
  } finally {
    testing.value = false
  }
}

onMounted(async () => {
  await Promise.all([config.loadAll(), config.loadNotifyTriggers(), loadEmail()])
})
</script>

<template>
  <section class="page">
    <header class="page-head">
      <div class="page-title">
        <h2>消息</h2>
        <span class="page-sub">
          邮件提醒与触发条件 · 共 6 项开关（4 项可写 .env + {{ readonlyCount }} 项后端只读）· 零本地存储
        </span>
      </div>
      <button class="btn btn-primary" type="button" data-testid="save-switches" :disabled="saving" @click="saveSwitches">
        {{ saving ? '保存中…' : '保存提醒开关' }}
      </button>
    </header>

    <!-- 6 项开关 -->
    <div class="card" data-testid="switch-list">
      <div class="card-title">
        <span>提醒开关</span>
        <span class="hint">全部值来自后端接口；刷新页面后由接口重新读取，不写任何浏览器存储</span>
      </div>
      <div class="switch-list">
        <FormToggle
          v-for="item in switches"
          :key="item.key"
          :test-id="`switch-${item.key}`"
          :model-value="config.readNotifySwitch(item.key)"
          :label="item.label"
          :hint="
            item.hint +
            (item.source === 'env' ? '　［可写 · .env notify 段］' : '　［只读 · config/notifications.json 提供］')
          "
          :default-state="item.defaultState"
          :disabled="!config.isNotifyWritable(item.key)"
          @update:model-value="(value: boolean) => onToggle(item.key, value)"
        />
      </div>
      <p class="hint foot-note">
        后 2 项由 <span class="mono">GET /api/notify/triggers</span> 提供真实值（源：
        <span class="mono">{{ config.notifyTriggerSource || 'config/notifications.json' }}</span>）。后端当前未提供写入端点，
        故置灰只读；变更需求走契约流程（§10），本页不做本地伪造。
      </p>
    </div>

    <!-- 测试邮件 -->
    <div class="card">
      <div class="card-title">
        <span>测试通道</span>
        <StatusBadge
          :label="canTest ? 'notify:ready 已就绪' : 'notify:ready 未就绪'"
          :tone="canTest ? 'ok' : 'mute'"
        />
      </div>
      <div class="row">
        <button class="btn btn-primary" type="button" :disabled="!canTest || testing" @click="testEmail">
          {{ testing ? '发送中…' : '发送测试邮件' }}
        </button>
        <span class="hint">
          按钮在收到 <span class="mono">notify:ready</span> 事件前保持置灰；该信号由角色C 的通知通道在准备就绪时发出。
        </span>
      </div>
    </div>

    <!-- 邮箱配置 -->
    <div class="card">
      <div class="card-title">
        <span>邮箱配置</span>
        <button class="btn" type="button" :disabled="saving" @click="saveEmail">保存邮箱配置</button>
      </div>
      <div class="form-grid">
        <FormToggle v-model="email.enabled" label="启用邮件提醒" hint="关闭后即使开关打开也不会发信" class="span-2" />
        <FormInput v-model="email.sender" label="发件人" placeholder="${SMTP_SENDER}" />
        <FormInput v-model="email.receiver" label="收件人" placeholder="${SMTP_RECEIVER}" />
        <FormInput v-model="email.host" label="SMTP 主机" placeholder="${SMTP_HOST}" />
        <FormInput v-model="email.port" label="端口" type="number" hint="SSL 常用 465，STARTTLS 常用 587" />
        <FormInput
          v-model="email.auth_code"
          label="授权码"
          masked
          mono
          placeholder="${SMTP_AUTH_CODE}"
          hint="只接受 ${VAR} 占位，明文将被拒绝"
        />
        <FormToggle v-model="email.use_ssl" label="使用 SSL" hint="465 端口请开启；587 端口请关闭" />
      </div>
    </div>

    <!-- 触发条件 -->
    <div class="card">
      <div class="card-title">
        <span>触发条件（只读）</span>
        <span class="hint">来自 config/notifications.json 的事件类型清单</span>
      </div>
      <div v-if="triggers.length" class="table-wrap">
        <table class="grid" data-testid="triggers-table">
          <thead>
            <tr>
              <th style="width: 300px">触发条件</th>
              <th>事件键</th>
              <th style="width: 130px">状态</th>
              <th style="width: 110px">默认</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="trigger in triggers" :key="trigger.key">
              <td>{{ trigger.label }}</td>
              <td class="cell-mono">{{ trigger.key }}</td>
              <td>
                <StatusBadge
                  :label="trigger.enabled ? '已启用' : '未启用'"
                  :tone="trigger.enabled ? 'ok' : 'mute'"
                />
              </td>
              <td>
                <span class="tag">{{ trigger.defaultEnabled ? '默认开' : '默认关' }}</span>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
      <p v-else class="empty">暂无触发条件清单。</p>
    </div>
  </section>
</template>

<style scoped>
.switch-list {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 16px 24px;
}

.foot-note {
  margin-top: 14px;
  padding-top: 12px;
  border-top: 1px solid var(--line);
  line-height: 1.7;
}

@media (max-width: 1280px) {
  .switch-list {
    grid-template-columns: minmax(0, 1fr);
  }
}
</style>
