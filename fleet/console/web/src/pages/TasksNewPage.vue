<script setup lang="ts">
/**
 * 新建任务页（TASK-104，ux-states new_goal 五态）。
 * 提交后跳转 /tasks?goal=<id>；带 Idempotency-Key 防重复提交。
 */
import { computed, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ApiFail } from '@/api/client'
import { createGoal } from '@/api/kernel'

const router = useRouter()

const title = ref('')
const requirements = ref('')
const workspace = ref('')
const submitting = ref(false)
const errorMessage = ref('')
const fieldErrors = ref<Record<string, string>>({})

const canSubmit = computed(() => title.value.trim().length > 0 && requirements.value.trim().length > 0 && !submitting.value)

function defaultWorkspace(): string {
  // 缺省留空 = 服务端推导 allowed_roots[0]/<slug>
  return ''
}

async function submit() {
  if (!canSubmit.value) return
  submitting.value = true
  errorMessage.value = ''
  fieldErrors.value = {}
  try {
    const key = (crypto?.randomUUID?.() ?? `web-${Date.now()}-${Math.random().toString(16).slice(2)}`)
    const payload = { title: title.value.trim(), requirements: requirements.value.trim() }
    if (workspace.value.trim()) Object.assign(payload, { workspace: workspace.value.trim() })
    const response = await createGoal(payload as typeof payload & { workspace?: string }, key)
    await router.push({ path: '/tasks', query: { goal: response.goal.id, just_created: '1' } })
  } catch (error) {
    if (error instanceof ApiFail) {
      if (error.status === 409 && error.body.reason === 'SETUP_INCOMPLETE') {
        errorMessage.value = String(error.body.error || '还没有可用的规划模型')
      } else if (error.status === 422) {
        errorMessage.value = String(error.body.error || '请求不合法')
        const details = error.body.details as Record<string, string> | undefined
        if (details) fieldErrors.value = details
      } else if (error.status === 401) {
        errorMessage.value = '请先在总览页解锁会话'
      } else {
        errorMessage.value = String(error.body.error || `提交失败（HTTP ${error.status}）`)
      }
    } else {
      errorMessage.value = `提交失败：${String(error)}`
    }
  } finally {
    submitting.value = false
  }
}

void defaultWorkspace
</script>

<template>
  <section class="page">
    <header class="page-head">
      <h2>新建任务</h2>
      <p class="hint">用一句话描述你想做什么，Fleet 会自动拆解计划并调度执行体完成。</p>
    </header>

    <form class="card form" @submit.prevent="submit">
      <label>
        <span class="label">任务标题</span>
        <input v-model="title" type="text" maxlength="120" placeholder="例如：做一个命令行计算器" />
        <em v-if="fieldErrors.title" class="field-error">{{ fieldErrors.title }}</em>
      </label>

      <label>
        <span class="label">你想做什么？（需求全文）</span>
        <textarea
          v-model="requirements"
          rows="8"
          maxlength="20000"
          placeholder="描述目标、边界与验收期望。计划拆解、执行与验收由 Fleet 自动推进。"
        ></textarea>
        <em v-if="fieldErrors.requirements" class="field-error">{{ fieldErrors.requirements }}</em>
      </label>

      <label>
        <span class="label">工作区（可选，留空自动选择）</span>
        <input v-model="workspace" type="text" placeholder="例如 E:/Demo/MyProject" />
        <em v-if="fieldErrors.workspace" class="field-error">{{ fieldErrors.workspace }}</em>
      </label>

      <p v-if="errorMessage" class="error-banner" role="alert">{{ errorMessage }}</p>

      <div class="actions">
        <button type="submit" class="primary" :disabled="!canSubmit">
          <span v-if="submitting">正在拆解计划…</span>
          <span v-else>提交并开始</span>
        </button>
        <span v-if="submitting" class="loading-hint">提交后自动生成计划 todo，请勿重复提交</span>
      </div>
    </form>
  </section>
</template>

<style scoped>
.page { padding: 16px 20px; max-width: 760px; margin: 0 auto; }
.page-head h2 { margin: 0 0 4px; }
.hint { color: var(--text-dim, #8a93a6); margin: 0 0 16px; }
.card { background: var(--panel, #161a23); border: 1px solid var(--border, #262c3a); border-radius: 10px; padding: 18px; }
.form { display: flex; flex-direction: column; gap: 14px; }
.form label { display: flex; flex-direction: column; gap: 6px; }
.label { font-size: 13px; color: var(--text-dim, #8a93a6); }
input, textarea {
  background: var(--bg, #0d1017); color: var(--text, #e7ebf3);
  border: 1px solid var(--border, #262c3a); border-radius: 8px; padding: 10px 12px;
  font: inherit; width: 100%; box-sizing: border-box;
}
textarea { resize: vertical; }
.field-error { color: #ff7b81; font-size: 12px; font-style: normal; }
.error-banner { background: rgba(255, 99, 104, 0.12); border: 1px solid #ff6368; color: #ff9ea2; border-radius: 8px; padding: 10px 12px; margin: 0; }
.actions { display: flex; align-items: center; gap: 12px; }
button.primary {
  background: var(--accent, #4f8cff); border: none; color: #fff;
  padding: 10px 22px; border-radius: 8px; font: inherit; cursor: pointer;
}
button.primary:disabled { opacity: 0.5; cursor: not-allowed; }
.loading-hint { color: var(--text-dim, #8a93a6); font-size: 12px; }
</style>
