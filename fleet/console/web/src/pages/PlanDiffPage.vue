<script setup lang="ts">
/**
 * 计划变更确认页（TASK-603，ux-states plan_diff_review 五态）。
 * 三段列表（新增/取消/修改）+ 确认/驳回；409 显示既有决定并只读。
 */
import { computed, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ApiFail } from '@/api/client'
import { getTodo } from '@/api/kernel'
import { request } from '@/api/client'
import type { PlanDiff } from '@/api/types'

const route = useRoute()
const router = useRouter()

const diff = ref<PlanDiff | null>(null)
const decision = ref<string>('pending')
const loadError = ref('')
const deciding = ref(false)
const actionError = ref('')

const todoId = computed(() => String(route.params.todo_id || ''))
const readonly = computed(() => decision.value !== 'pending')
const hasChanges = computed(() =>
  !!diff.value && (diff.value.add.length + diff.value.cancel.length + diff.value.modify.length > 0))

async function load() {
  try {
    const payload = await request<{ ok: boolean; diff: PlanDiff; decision: string }>(
      `/api/kernel/todos/${encodeURIComponent(todoId.value)}/diff`)
    diff.value = payload.diff
    decision.value = payload.decision
  } catch (error) {
    loadError.value = error instanceof ApiFail ? String(error.body.error || '加载失败') : String(error)
  }
}

async function decide(kind: 'approve' | 'reject') {
  deciding.value = true
  actionError.value = ''
  try {
    await request(`/api/kernel/todos/${encodeURIComponent(todoId.value)}/decision`, {
      method: 'POST',
      body: JSON.stringify({ decision: kind }),
    })
    await router.push('/tasks')
  } catch (error) {
    if (error instanceof ApiFail && error.status === 409) {
      decision.value = 'approved'
      actionError.value = '该变更已被处理，当前为只读'
    } else {
      actionError.value = error instanceof ApiFail ? String(error.body.error || '操作失败') : String(error)
    }
  } finally {
    deciding.value = false
  }
}

onMounted(load)
</script>

<template>
  <section class="page">
    <header class="page-head">
      <h2>计划变更确认</h2>
      <p class="hint">来自你的对话指示，由 Planner 生成的变更待确认。</p>
    </header>

    <div v-if="loadError" class="error-banner">{{ loadError }}</div>
    <p v-if="readonly" class="readonly-banner">
      {{ decision === 'approved' ? '✅ 已确认生效' : '⛔ 已驳回' }}（只读）
    </p>

    <div v-if="diff && !hasChanges" class="card"><p class="dim">无待确认变更。</p></div>

    <template v-else-if="diff">
      <div class="card" v-if="diff.add.length">
        <h3 class="add">新增任务（{{ diff.add.length }}）</h3>
        <ul>
          <li v-for="item in diff.add" :key="item.id">
            <b>{{ item.title }}</b>
            <span class="dim"> · 角色 {{ item.role }} · 验收 {{ item.verify?.join('；') }}</span>
          </li>
        </ul>
      </div>
      <div class="card" v-if="diff.cancel.length">
        <h3 class="cancel">取消任务（{{ diff.cancel.length }}）</h3>
        <ul><li v-for="id in diff.cancel" :key="id" class="dim">{{ id }}</li></ul>
      </div>
      <div class="card" v-if="diff.modify.length">
        <h3 class="modify">修改任务（{{ diff.modify.length }}）</h3>
        <ul>
          <li v-for="m in diff.modify" :key="m.todo_id">
            <b>{{ m.todo_id }}</b>
            <pre class="fields">{{ JSON.stringify(m.fields, null, 1) }}</pre>
          </li>
        </ul>
      </div>
    </template>

    <p v-if="actionError" class="error-banner">{{ actionError }}</p>

    <div class="actions" v-if="!readonly">
      <button class="primary" :disabled="deciding" @click="decide('approve')">确认生效</button>
      <button class="ghost" :disabled="deciding" @click="decide('reject')">驳回</button>
    </div>
  </section>
</template>

<style scoped>
.page { padding: 16px 20px; max-width: 760px; margin: 0 auto; }
.card { background: var(--panel, #161a23); border: 1px solid var(--border, #262c3a); border-radius: 10px; padding: 14px 16px; margin-bottom: 12px; }
h3 { margin: 0 0 8px; font-size: 14px; }
.add { color: #58d68d; } .cancel { color: #ff7b81; } .modify { color: #ffc46b; }
.dim { color: var(--text-dim, #8a93a6); font-size: 12px; }
.hint { color: var(--text-dim, #8a93a6); margin: 0 0 14px; }
ul { margin: 0; padding-left: 18px; font-size: 13px; }
li { margin-bottom: 4px; }
.fields { background: var(--bg, #0d1017); padding: 6px 8px; border-radius: 6px; font-size: 11px; overflow: auto; }
.error-banner { background: rgba(255, 99, 104, 0.12); border: 1px solid #ff6368; color: #ff9ea2; border-radius: 8px; padding: 10px 14px; margin-bottom: 12px; }
.readonly-banner { background: rgba(88, 214, 141, 0.1); border: 1px solid #58d68d; color: #58d68d; border-radius: 8px; padding: 10px 14px; margin-bottom: 12px; }
.actions { display: flex; gap: 12px; }
button.primary { background: var(--accent, #4f8cff); border: none; color: #fff; padding: 9px 20px; border-radius: 8px; cursor: pointer; font: inherit; }
button.primary:disabled { opacity: 0.5; }
button.ghost { background: transparent; border: 1px solid var(--border, #262c3a); color: var(--text, #e7ebf3); border-radius: 8px; padding: 9px 20px; cursor: pointer; font: inherit; }
</style>
