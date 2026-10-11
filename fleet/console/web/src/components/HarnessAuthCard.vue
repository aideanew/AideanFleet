<script setup lang="ts">
/**
 * 执行体登录态卡片（TASK-502）：消费 setup.status 的 harness_auth，
 * 未安装/未登录标红 + 『去登录』（setup.login 拉起官方登录命令，MN-02 不代填凭据）。
 * 供 ExecutorsPage 顶部嵌入（双数据源并存，U-06 保守口径：不替换旧页）。
 */
import { onBeforeUnmount, onMounted, ref } from 'vue'
import { ApiFail, request } from '@/api/client'
import { setupStatus } from '@/api/setup'
import type { SetupStatus } from '@/api/types'

const status = ref<SetupStatus | null>(null)
const loadError = ref('')
const launching = ref('')
const loginError = ref('')
let pollTimer: number | undefined

async function refresh() {
  try {
    const payload = await setupStatus()
    status.value = payload.status
    loadError.value = ''
  } catch (error) {
    loadError.value = error instanceof ApiFail
      ? String(error.body.error || '无法获取执行体状态')
      : String(error)
  }
}

async function launchLogin(harness: string) {
  launching.value = harness
  loginError.value = ''
  try {
    await request(`/api/setup/login/${encodeURIComponent(harness)}`, { method: 'POST' })
    pollTimer = window.setInterval(async () => {
      await refresh()
      const row = (status.value?.harness_auth ?? []).find(h => h.harness === harness)
      if (row?.authed) {
        window.clearInterval(pollTimer)
        launching.value = ''
      }
    }, 3000)
  } catch (error) {
    launching.value = ''
    loginError.value = error instanceof ApiFail ? String(error.body.error || '拉起登录失败') : String(error)
  }
}

onMounted(() => {
  void refresh()
  pollTimer = window.setInterval(refresh, 5000)
})
onBeforeUnmount(() => {
  if (pollTimer) window.clearInterval(pollTimer)
})
</script>

<template>
  <div class="card harness-card">
    <h3>可用性与登录态</h3>
    <p v-if="loadError" class="err">{{ loadError }}</p>
    <p v-if="loginError" class="err">{{ loginError }}</p>
    <ul class="list">
      <li v-for="harness in status?.harness_auth ?? []" :key="harness.harness">
        <b>{{ harness.harness }}</b>
        <span class="badge" :class="harness.installed ? 'ok' : 'bad'">
          {{ harness.installed ? '已安装' : '未安装' }}
        </span>
        <span class="badge" :class="harness.authed ? 'ok' : 'bad'">
          {{ harness.authed ? '已登录' : '未登录' }}
        </span>
        <span class="dim">{{ harness.detail?.slice(0, 80) }}</span>
        <button
          v-if="harness.installed && !harness.authed"
          class="ghost" :disabled="launching === harness.harness"
          @click="launchLogin(harness.harness)">
          {{ launching === harness.harness ? '已拉起，等待登录…' : '去登录' }}
        </button>
      </li>
      <li v-if="status && status.harness_auth.length === 0" class="dim">
        未安装任何执行体——前往 <router-link to="/setup">/setup</router-link> 一键安装。
      </li>
    </ul>
  </div>
</template>

<style scoped>
.harness-card { background: var(--panel, #161a23); border: 1px solid var(--border, #262c3a); border-radius: 10px; padding: 14px 16px; margin-bottom: 14px; }
h3 { margin: 0 0 10px; font-size: 14px; }
.list { list-style: none; margin: 0; padding: 0; }
.list li { display: flex; align-items: center; gap: 10px; padding: 6px 0; flex-wrap: wrap; }
.badge { font-size: 11px; padding: 1px 8px; border-radius: 10px; border: 1px solid var(--border, #262c3a); }
.ok { color: #58d68d; border-color: #58d68d; }
.bad { color: #ff7b81; border-color: #ff7b81; }
.dim { color: var(--text-dim, #8a93a6); font-size: 12px; }
.err { color: #ff9ea2; font-size: 12px; }
.ghost { background: transparent; border: 1px solid var(--border, #262c3a); color: var(--text, #e7ebf3); border-radius: 6px; padding: 4px 10px; cursor: pointer; font-size: 12px; }
</style>
