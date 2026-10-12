<script setup lang="ts">
/**
 * 首次运行向导 /setup（TASK-205 第 1 步 + TASK-303 第 2/3 步，ux-states setup_wizard 五态）。
 * 第 1 步：组件列表（来自 setup.status，无硬编码名单）+ 一键安装 + 逐组件进度/重试/镜像切换。
 * 第 2 步：模型密钥（只写不读）。第 3 步：执行体登录（拉起 + 轮询）。
 */
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { ApiFail, request } from '@/api/client'
import { INSTALL_ERROR_TEXT, setupInstall, setupJob, setupStatus } from '@/api/setup'
import type { SetupStatus } from '@/api/types'

const status = ref<SetupStatus | null>(null)
const loadError = ref('')
const jobRunning = ref(false)
const jobState = ref('')
const stepByComponent = ref<Record<string, { state: string; error_code: string | null; log_tail: string }>>({})
const mirror = ref<'auto' | 'official' | 'cn'>('auto')
const pollTimer = ref<number | undefined>(undefined)
const jobTimer = ref<number | undefined>(undefined)

/* —— 第 2 步：模型密钥（TASK-303） —— */
const modelName = ref('')
const baseUrl = ref('')
const modelId = ref('')
const apiKeyEnv = ref('')
const keyValue = ref('')
const keyMessage = ref('')
const keyError = ref('')
const testResult = ref<{ reachable: boolean; latency_ms: number; detail: string } | null>(null)
const savedModels = ref<{ name: string; api_key_env: string; key_present: boolean; base_url: string; model_id: string }[]>([])

/* —— 第 3 步：执行体登录（TASK-303） —— */
const launching = ref<string>('')
const loginError = ref('')

const ready = computed(() => status.value?.ready ?? false)
const missingComponents = computed(() =>
  (status.value?.components ?? []).filter(c => c.state === 'missing' || c.state === 'outdated'))
const installableNow = computed(() => {
  const busy = new Set(Object.entries(stepByComponent.value)
    .filter(([, s]) => s.state === 'running').map(([name]) => name))
  return missingComponents.value
    .filter(c => c.kind === 'cli' && !busy.has(c.name))
    .map(c => c.name)
})
// 审计修复：原表达式 `c.state === 'outdated' === false` 按优先级恒为真（非 outdated 即通过），
// 运行时 missing/failed、CLI installing/failed 都会被当作"第 1 步已完成"。git/grok 为可选组件。
const OPTIONAL_COMPONENTS = new Set(['git', 'grok'])
const componentsReady = computed(() =>
  (status.value?.components ?? []).every(c => c.state === 'installed' || OPTIONAL_COMPONENTS.has(c.name)))

async function refresh() {
  try {
    const payload = await setupStatus()
    status.value = payload.status
    savedModels.value = payload.status.models
    loadError.value = ''
  } catch (error) {
    loadError.value = error instanceof ApiFail
      ? String(error.body.error || '无法获取安装状态')
      : `无法获取安装状态：${String(error)}`
  }
}

async function installAll() {
  const names = installableNow.value
  if (!names.length || jobRunning.value) return
  try {
    const payload = await setupInstall(names, mirror.value)
    jobRunning.value = true
    jobState.value = 'queued'
    if (pollTimer.value) window.clearInterval(pollTimer.value)
    pollTimer.value = window.setInterval(async () => {
      const job = await setupJob(payload.job_id)
      jobState.value = job.state
      const map: typeof stepByComponent.value = {}
      for (const step of job.steps) map[step.component] = step
      stepByComponent.value = map
      if (job.state === 'succeeded' || job.state === 'failed') {
        jobRunning.value = false
        if (pollTimer.value) window.clearInterval(pollTimer.value)
        await refresh()
      }
    }, 1000)
  } catch (error) {
    jobRunning.value = false
    loadError.value = error instanceof ApiFail
      ? String(error.body.error || '安装任务启动失败')
      : `安装任务启动失败：${String(error)}`
  }
}

function errorText(code: string | null): string {
  if (!code) return ''
  return INSTALL_ERROR_TEXT[code] || code
}

async function retryOne(name: string) {
  await installNamed([name])
}

async function switchMirrorAndRetry(name: string) {
  mirror.value = mirror.value === 'cn' ? 'official' : 'cn'
  await installNamed([name])
}

async function installNamed(names: string[]) {
  try {
    const payload = await setupInstall(names, mirror.value)
    jobRunning.value = true
    if (jobTimer.value) window.clearInterval(jobTimer.value)
    jobTimer.value = window.setInterval(async () => {
      const job = await setupJob(payload.job_id)
      const map: typeof stepByComponent.value = { ...stepByComponent.value }
      for (const step of job.steps) map[step.component] = step
      stepByComponent.value = map
      if (job.state === 'succeeded' || job.state === 'failed') {
        jobRunning.value = false
        if (jobTimer.value) window.clearInterval(jobTimer.value)
        await refresh()
      }
    }, 1000)
  } catch (error) {
    loadError.value = error instanceof ApiFail ? String(error.body.error || '重试失败') : String(error)
  }
}

/* —— 第 2 步动作（TASK-301 提供的 API） —— */
async function saveModelAndKey() {
  keyMessage.value = ''
  keyError.value = ''
  try {
    const config = {
      workspace: { allowed_roots: [] as string[] },
      models: {
        [modelName.value || 'default']: {
          base_url: baseUrl.value, model_id: modelId.value,
          api_key_env: apiKeyEnv.value || 'CUSTOM_API_KEY',
        },
      },
      roles: {}, runtime: {},
    }
    if (modelName.value) {
      await request('/api/config/fleet', {
        method: 'PUT',
        body: JSON.stringify(config),
      })
    }
    if (keyValue.value) {
      const envName = apiKeyEnv.value || 'CUSTOM_API_KEY'
      const result = await request<{ ok: boolean; key_present: boolean }>(
        `/api/setup/secrets/${encodeURIComponent(envName)}`,
        { method: 'PUT', body: JSON.stringify({ value: keyValue.value }) })
      keyMessage.value = result.key_present ? '密钥已保存（只写不读）' : '保存失败'
    }
    keyValue.value = ''
    await refresh()
    await testConnectivity()
  } catch (error) {
    keyError.value = error instanceof ApiFail ? String(error.body.error || '保存失败') : String(error)
  }
}

async function testConnectivity() {
  testResult.value = null
  try {
    const name = modelName.value || (savedModels.value[0]?.name ?? '')
    if (!name) return
    testResult.value = await request<{ reachable: boolean; latency_ms: number; detail: string }>(
      `/api/setup/models/${encodeURIComponent(name)}/test`, { method: 'POST' })
  } catch (error) {
    testResult.value = { reachable: false, latency_ms: 0,
      detail: error instanceof ApiFail ? String(error.body.error) : String(error) }
  }
}

/* —— 第 3 步动作 —— */
async function launchLogin(harness: string) {
  launching.value = harness
  loginError.value = ''
  try {
    await request(`/api/setup/login/${encodeURIComponent(harness)}`, { method: 'POST' })
    const poll = window.setInterval(async () => {
      await refresh()
      const row = (status.value?.harness_auth ?? []).find(h => h.harness === harness)
      if (row?.authed) {
        window.clearInterval(poll)
        launching.value = ''
      }
    }, 3000)
  } catch (error) {
    launching.value = ''
    loginError.value = error instanceof ApiFail ? String(error.body.error || '拉起登录失败') : String(error)
  }
}

onMounted(refresh)
onBeforeUnmount(() => {
  if (pollTimer.value) window.clearInterval(pollTimer.value)
  if (jobTimer.value) window.clearInterval(jobTimer.value)
})
</script>

<template>
  <section class="page">
    <header class="page-head">
      <h2>安装与首次配置</h2>
      <p class="hint">三步：① 安装运行环境与执行体 → ② 填模型密钥 → ③ 登录执行体。全程不需要打开终端或编辑文件。</p>
    </header>

    <div v-if="loadError" class="error-banner" role="alert">
      {{ loadError }}
      <p class="forbidden-hint">如果这不是本机浏览器，请在安装 AideanFleet 的电脑上打开控制台。</p>
    </div>

    <!-- 第 1 步：组件 -->
    <div class="card">
      <h3>① 安装运行环境与执行体</h3>
      <p v-if="!status" class="dim">正在读取组件状态…</p>
      <template v-else>
        <table class="components">
          <thead>
            <tr><th>组件</th><th>状态</th><th>版本</th><th>来源</th><th></th></tr>
          </thead>
          <tbody>
            <tr v-for="component in status.components" :key="component.name"
                :class="{ bad: component.state === 'failed' || component.state === 'outdated' }">
              <td>{{ component.name }}</td>
              <td>
                <span class="badge" :class="`st-${component.state}`">
                  {{ { missing: '未安装', installing: '安装中', installed: '已安装', outdated: '版本过旧', failed: '失败' }[component.state] }}
                </span>
              </td>
              <td>{{ component.version || '—' }}</td>
              <td>{{ { managed: '私有副本', system: '系统', none: '—' }[component.source] }}</td>
              <td>
                <template v-if="stepByComponent[component.name]">
                  <span class="badge" :class="`st-${stepByComponent[component.name].state}`">
                    {{ { pending: '排队中', running: '安装中', succeeded: '成功', failed: '失败', skipped: '已跳过' }[stepByComponent[component.name].state] }}
                  </span>
                  <pre v-if="stepByComponent[component.name].log_tail" class="log">{{ stepByComponent[component.name].log_tail.slice(-300) }}</pre>
                  <p v-if="stepByComponent[component.name].error_code" class="err-text">
                    {{ errorText(stepByComponent[component.name].error_code) }}
                  </p>
                  <button v-if="stepByComponent[component.name].state === 'failed'" class="ghost" @click="retryOne(component.name)">重试此项</button>
                  <button v-if="stepByComponent[component.name].state === 'failed'" class="ghost" @click="switchMirrorAndRetry(component.name)">切换{{ mirror === 'cn' ? '官方' : '国内' }}镜像重试</button>
                </template>
              </td>
            </tr>
          </tbody>
        </table>

        <div class="actions">
          <button class="primary" :disabled="jobRunning || installableNow.length === 0" @click="installAll">
            <span v-if="jobRunning">安装中（{{ jobState }}）…</span>
            <span v-else>一键安装缺失组件</span>
          </button>
          <span class="dim">镜像：{{ { auto: '自动', official: '官方源', cn: '国内镜像' }[mirror] }}</span>
          <span v-if="jobState === 'running'" class="dim">安装进行中，请勿关闭页面</span>
        </div>
      </template>
    </div>

    <!-- 第 2 步：模型密钥 -->
    <div class="card">
      <h3>② 填模型密钥（只写不读）</h3>
      <p class="dim">已保存模型：{{ savedModels.map(m => `${m.name}(${m.key_present ? '有 key' : '无 key'})`).join('、') || '（无）' }}</p>
      <div class="grid3">
        <label>名称<input v-model="modelName" placeholder="例如 agnes" /></label>
        <label>Base URL<input v-model="baseUrl" placeholder="https://api.example.com/v1" /></label>
        <label>模型 ID<input v-model="modelId" placeholder="例如 agnes-3.0-flash" /></label>
        <label>密钥环境变量名<input v-model="apiKeyEnv" placeholder="例如 AGNES_API_KEY" /></label>
        <label>密钥<input v-model="keyValue" type="password" placeholder="粘贴后提交，提交即清空" /></label>
      </div>
      <div class="actions">
        <button class="primary" @click="saveModelAndKey">保存并测试连通</button>
        <span v-if="keyMessage" class="ok-text">{{ keyMessage }}</span>
        <span v-if="keyError" class="err-text">{{ keyError }}</span>
      </div>
      <p v-if="testResult" class="dim">
        连通测试：{{ testResult.reachable ? `可达（${testResult.latency_ms}ms）` : `不可达：${testResult.detail}` }}
      </p>
      <p class="dim small">密钥保存到本机 secrets/.env，任何界面都不会再显示它。</p>
    </div>

    <!-- 第 3 步：执行体登录 -->
    <div class="card">
      <h3>③ 登录执行体</h3>
      <p v-if="loginError" class="err-text">{{ loginError }}</p>
      <ul class="harness-list">
        <li v-for="harness in status?.harness_auth ?? []" :key="harness.harness">
          <span class="badge" :class="harness.authed ? 'st-installed' : 'st-missing'">
            {{ harness.authed ? '已登录' : (harness.installed ? '未登录' : '未安装') }}
          </span>
          <b>{{ harness.harness }}</b>
          <span class="dim">{{ harness.detail?.slice(0, 80) }}</span>
          <button
            v-if="harness.installed && !harness.authed"
            class="ghost" :disabled="launching === harness.harness"
            @click="launchLogin(harness.harness)">
            {{ launching === harness.harness ? '已拉起，等待登录…' : '去登录' }}
          </button>
        </li>
      </ul>
    </div>

    <div v-if="ready" class="card success">
      <h3>✅ 全部就绪</h3>
      <router-link class="primary link-btn" to="/tasks/new">开始第一个任务</router-link>
    </div>
  </section>
</template>

<style scoped>
.page { padding: 16px 20px; max-width: 860px; margin: 0 auto; }
.card { background: var(--panel, #161a23); border: 1px solid var(--border, #262c3a); border-radius: 10px; padding: 16px; margin-bottom: 14px; }
h3 { margin: 0 0 10px; }
.hint, .dim { color: var(--text-dim, #8a93a6); }
.small { font-size: 12px; }
.error-banner { background: rgba(255, 99, 104, 0.12); border: 1px solid #ff6368; color: #ff9ea2; border-radius: 8px; padding: 10px 14px; margin-bottom: 14px; }
.forbidden-hint { font-size: 12px; margin: 4px 0 0; }
.components { width: 100%; border-collapse: collapse; font-size: 13px; }
.components th, .components td { text-align: left; padding: 6px 8px; border-bottom: 1px solid var(--border, #262c3a); }
.badge { font-size: 11px; padding: 1px 8px; border-radius: 10px; border: 1px solid var(--border, #262c3a); }
.st-installed, .st-succeeded { color: #58d68d; border-color: #58d68d; }
.st-missing, .st-failed { color: #ff7b81; border-color: #ff7b81; }
.st-outdated, .st-running { color: #ffc46b; border-color: #ffc46b; }
tr.bad td { background: rgba(255, 99, 104, 0.06); }
.log { background: var(--bg, #0d1017); padding: 6px 8px; border-radius: 6px; max-width: 420px; overflow: auto; font-size: 11px; }
.err-text { color: #ff9ea2; font-size: 12px; margin: 4px 0; }
.ok-text { color: #58d68d; font-size: 13px; }
.actions { display: flex; align-items: center; gap: 12px; margin-top: 12px; flex-wrap: wrap; }
button.primary { background: var(--accent, #4f8cff); border: none; color: #fff; padding: 9px 20px; border-radius: 8px; cursor: pointer; font: inherit; }
button.primary:disabled { opacity: 0.5; cursor: not-allowed; }
button.ghost { background: transparent; border: 1px solid var(--border, #262c3a); color: var(--text, #e7ebf3); border-radius: 6px; padding: 4px 10px; cursor: pointer; font-size: 12px; }
.grid3 { display: grid; grid-template-columns: repeat(2, 1fr); gap: 10px; }
.grid3 label { display: flex; flex-direction: column; gap: 4px; font-size: 12px; color: var(--text-dim, #8a93a6); }
input { background: var(--bg, #0d1017); color: var(--text, #e7ebf3); border: 1px solid var(--border, #262c3a); border-radius: 8px; padding: 8px 10px; font: inherit; }
.harness-list { list-style: none; margin: 0; padding: 0; }
.harness-list li { display: flex; align-items: center; gap: 10px; padding: 6px 0; }
.link-btn { display: inline-block; text-decoration: none; margin-top: 8px; }
.success { border-color: #58d68d; }
</style>
