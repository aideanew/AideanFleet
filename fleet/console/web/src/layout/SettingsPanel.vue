<script setup lang="ts">
/**
 * SettingsPanel · 设置抽屉（顶部栏 ⚙ 设置 打开）
 * 至少可调：请求超时时间、请求重试次数；并补充重试等待、锁屏有效期（来自 basic 段）。
 */
import { ref, watch } from 'vue'
import FormInput from '@/components/FormInput.vue'
import { api } from '@/api/client'
import { toast } from '@/composables/useToast'
import { useConfigStore } from '@/stores/config'
import type { RequestConfig } from '@/api/types'

const props = defineProps<{ open: boolean }>()
const emit = defineEmits<{ (e: 'update:open', value: boolean): void }>()

const config = useConfigStore()
const form = ref<RequestConfig>({ timeout: 600, retry_max: 10, retry_delay: 10 })
const lockTtl = ref(60)
const saving = ref(false)
const loaded = ref(false)

async function load() {
  try {
    const [requestRes, basicRes] = await Promise.all([api.getConfig<RequestConfig>('request'), api.getConfig<Record<string, number>>('basic')])
    form.value = { ...form.value, ...requestRes.data }
    lockTtl.value = Number(basicRes.data?.lock_ttl_minutes ?? 60)
    loaded.value = true
  } catch (error) {
    toast.fail('设置读取失败', error instanceof Error ? error.message : '')
  }
}

async function save() {
  saving.value = true
  try {
    const result = await api.saveConfig('request', form.value as unknown as Record<string, unknown>)
    const ignored = result.ignored ?? []
    if (ignored.length) {
      toast.warn('部分字段未生效', `后端忽略了：${ignored.join('、')}`)
    } else {
      toast.ok('设置已保存', '请求超时 / 重试次数 / 重试等待已写入 .env 的 request 段')
    }
    const basicResult = await api.saveConfig('basic', { lock_ttl_minutes: Number(lockTtl.value) || 60 })
    if ((basicResult.ignored ?? []).length) {
      toast.warn('锁屏有效期未生效', `后端忽略了：${(basicResult.ignored ?? []).join('、')}`)
    }
    await config.loadAll()
  } catch (error) {
    toast.fail('设置保存失败', error instanceof Error ? error.message : '')
  } finally {
    saving.value = false
  }
}

watch(
  () => props.open,
  (open) => {
    if (open && !loaded.value) void load()
  },
)
</script>

<template>
  <Teleport to="body">
    <Transition name="slide">
      <aside v-if="open" class="drawer" aria-label="设置">
        <header class="head">
          <div>
            <b>设置</b>
            <p class="hint">写入 .env 的 request / basic 段，实时生效无缓存</p>
          </div>
          <button class="btn btn-ghost" type="button" aria-label="关闭设置" @click="emit('update:open', false)">
            ✕
          </button>
        </header>

        <div class="body">
          <FormInput v-model="form.timeout" label="请求超时（秒）" type="number" hint="单次模型调用的最长等待时间，超时按瞬时失败重试" />
          <FormInput v-model="form.retry_max" label="请求重试次数" type="number" hint="429/超时等瞬时失败的最大重试次数，耗尽后切换下一候选模型" />
          <FormInput v-model="form.retry_delay" label="重试等待（秒）" type="number" hint="两次重试之间的间隔，默认 10 秒" />
          <FormInput v-model="lockTtl" label="锁屏有效期（分钟）" type="number" hint="解锁后会话保持时长，默认 60 分钟" />

          <div class="note">
            <p class="hint">
              · 401/402/403/额度耗尽/模型不存在 属于硬失败，立即切换下一候选模型，不重试。<br />
              · 密钥类字段不接受明文，只接受 <span class="mono">${VAR}</span> 占位；真值放环境变量或 secrets/.env。
            </p>
          </div>
        </div>

        <footer class="foot">
          <button class="btn" type="button" @click="emit('update:open', false)">关闭</button>
          <button class="btn btn-primary" type="button" :disabled="saving" @click="save">
            {{ saving ? '保存中…' : '保存设置' }}
          </button>
        </footer>
      </aside>
    </Transition>
  </Teleport>
</template>

<style scoped>
.drawer {
  position: fixed;
  top: var(--topbar-h);
  right: 0;
  bottom: 0;
  width: 380px;
  max-width: 100vw;
  z-index: 80;
  display: flex;
  flex-direction: column;
  border-left: 1px solid var(--line-strong);
  background: var(--bg-elevated);
}

.head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
  padding: 14px 16px;
  border-bottom: 1px solid var(--line);
}

.head b {
  font-size: 14px;
}

.body {
  flex: 1;
  overflow: auto;
  padding: 16px;
  display: flex;
  flex-direction: column;
  gap: 14px;
}

.note {
  padding: 10px 12px;
  border: 1px dashed var(--line-strong);
  border-radius: var(--radius);
}

.foot {
  display: flex;
  justify-content: flex-end;
  gap: 10px;
  padding: 12px 16px;
  border-top: 1px solid var(--line);
}

.slide-enter-active,
.slide-leave-active {
  transition: transform var(--dur) var(--ease), opacity var(--dur) var(--ease);
}

.slide-enter-from,
.slide-leave-to {
  transform: translateX(24px);
  opacity: 0;
}
</style>
