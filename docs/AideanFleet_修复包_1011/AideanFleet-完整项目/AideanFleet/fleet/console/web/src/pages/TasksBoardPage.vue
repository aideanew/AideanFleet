<script setup lang="ts">
/**
 * 注意力看板（TASK-104，ux-states attention_board 五态）。
 * 四列：待你决定 / 运行中 / 卡住了 / 刚完成；blocked 卡片给原因与 reopen；done 可展开证据。
 * 每 2s 轮询 attention；失败显示顶部条并自动重试。
 */
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { useRoute } from 'vue-router'
import { ApiFail } from '@/api/client'
import { attention, getTodo, reopenTodo } from '@/api/kernel'
import type { AttentionResponse, Todo } from '@/api/types'

const route = useRoute()

const data = ref<AttentionResponse | null>(null)
const loadError = ref('')
const loading = ref(true)
const retryIn = ref(0)
const expanded = ref<string>('')
const evidenceByTodo = ref<Record<string, { name: string; kind: string; size: number; url: string }[]>>({})
const justCreated = ref(String(route.query.just_created || '') === '1')
const highlightGoal = ref(String(route.query.goal || ''))

let timer: number | undefined
let retryTimer: number | undefined

const columns = computed(() => [
  { key: 'needs_user', title: '待你决定', todos: data.value?.needs_user ?? [], tone: 'warn' },
  { key: 'running', title: '运行中', todos: data.value?.running ?? [], tone: 'info' },
  { key: 'blocked', title: '卡住了', todos: data.value?.blocked ?? [], tone: 'error' },
  { key: 'done', title: '刚完成', todos: data.value?.done_recent ?? [], tone: 'ok' },
])

const isEmpty = computed(() => {
  if (!data.value) return true
  const counts = data.value.counts
  return counts.needs_user + counts.running + counts.blocked + counts.done === 0
})

async function refresh() {
  try {
    data.value = await attention()
    loadError.value = ''
    loading.value = false
  } catch (error) {
    loading.value = false
    loadError.value = error instanceof ApiFail
      ? String(error.body.error || `连接控制台失败（HTTP ${error.status}）`)
      : `连接控制台失败：${String(error)}`
    scheduleRetry()
  }
}

function scheduleRetry() {
  retryIn.value = 5
  if (retryTimer) window.clearInterval(retryTimer)
  retryTimer = window.setInterval(() => {
    retryIn.value -= 1
    if (retryIn.value <= 0) {
      window.clearInterval(retryTimer)
      void refresh()
    }
  }, 1000)
}

async function toggleEvidence(todo: Todo) {
  if (expanded.value === todo.id) {
    expanded.value = ''
    return
  }
  expanded.value = todo.id
  if (!evidenceByTodo.value[todo.id]) {
    try {
      const detail = await getTodo(todo.id)
      evidenceByTodo.value = { ...evidenceByTodo.value, [todo.id]: detail.evidence }
    } catch {
      evidenceByTodo.value = { ...evidenceByTodo.value, [todo.id]: [] }
    }
  }
}

async function reopen(todo: Todo) {
  try {
    await reopenTodo(todo.id)
    await refresh()
  } catch (error) {
    loadError.value = error instanceof ApiFail
      ? String(error.body.error || '重新开始失败')
      : `重新开始失败：${String(error)}`
  }
}

function formatTime(value: string): string {
  return (value || '').replace('T', ' ').slice(0, 19)
}

function blockedNote(todo: Todo): string {
  // blocked 原因从事件流来；看板层不重复拉事件——直接展示 done_when/最后更新时间兜底
  return todo.done_when || ''
}

onMounted(() => {
  void refresh()
  timer = window.setInterval(refresh, 2000)
})
onBeforeUnmount(() => {
  if (timer) window.clearInterval(timer)
  if (retryTimer) window.clearInterval(retryTimer)
})
</script>

<template>
  <section class="page">
    <header class="page-head">
      <h2>任务看板</h2>
      <p class="hint">现在谁需要行动：待你决定 / 运行中 / 卡住了 / 刚完成。</p>
    </header>

    <p v-if="justCreated" class="info-banner">
      已提交，正在拆解计划。计划 todo 出现后自动推进。
    </p>

    <div v-if="loadError" class="error-banner" role="alert">
      {{ loadError }} <span v-if="retryIn > 0">（{{ retryIn }}s 后自动重试）</span>
    </div>

    <div v-if="loading" class="skeleton-grid">
      <div v-for="n in 4" :key="n" class="skeleton-column"></div>
    </div>

    <div v-else-if="isEmpty" class="empty">
      <p>还没有任何任务。</p>
      <router-link class="primary link-btn" to="/tasks/new">新建第一个任务</router-link>
    </div>

    <div v-else class="board">
      <div v-for="column in columns" :key="column.key" class="column" :class="`tone-${column.tone}`">
        <h3>{{ column.title }} <span class="count">{{ column.todos.length }}</span></h3>
        <p v-if="column.todos.length === 0" class="empty-column">—</p>
        <article
          v-for="todo in column.todos"
          :key="todo.id"
          class="card todo"
          :class="{ highlight: highlightGoal && todo.goal_id === highlightGoal }"
        >
          <h4>{{ todo.title }}</h4>
          <p class="meta">
            <span class="badge" :class="`status-${todo.status}`">{{ todo.status }}</span>
            <span v-if="todo.kind !== 'exec'" class="badge kind">{{ todo.kind }}</span>
            <span v-if="todo.role" class="dim">{{ todo.role }}</span>
            <span v-if="todo.attempt_count > 1" class="dim">第 {{ todo.attempt_count }} 轮</span>
          </p>
          <p class="dim time">更新于 {{ formatTime(todo.updated_at) }}</p>

          <div v-if="column.key === 'needs_user' && todo.plan_decision === 'pending'" class="blocked-box">
            <router-link class="ghost link" :to="`/tasks/${todo.id}/diff`">查看计划变更</router-link>
          </div>

          <div v-if="column.key === 'blocked'" class="blocked-box">
            <p class="blocked-reason">{{ blockedNote(todo) || '执行受阻，请查看原因后决定是否重新开始。' }}</p>
            <button class="ghost" @click="reopen(todo)">重新开始</button>
          </div>

          <div v-if="column.key === 'done'" class="done-box">
            <button class="ghost" @click="toggleEvidence(todo)">
              {{ expanded === todo.id ? '收起证据' : '查看证据' }}
            </button>
            <ul v-if="expanded === todo.id" class="evidence">
              <li v-for="item in evidenceByTodo[todo.id] || []" :key="item.name">
                <a :href="item.url" target="_blank" rel="noopener">{{ item.name }}</a>
                <span class="dim">（{{ item.size }} 字节）</span>
              </li>
              <li v-if="(evidenceByTodo[todo.id] || []).length === 0" class="dim">无证据文件</li>
            </ul>
          </div>
        </article>
      </div>
    </div>
  </section>
</template>

<style scoped>
.page { padding: 16px 20px; }
.page-head h2 { margin: 0 0 4px; }
.hint { color: var(--text-dim, #8a93a6); margin: 0 0 16px; }
.info-banner, .error-banner { border-radius: 8px; padding: 10px 14px; margin: 0 0 14px; }
.info-banner { background: rgba(79, 140, 255, 0.12); border: 1px solid var(--accent, #4f8cff); color: var(--accent, #4f8cff); }
.error-banner { background: rgba(255, 99, 104, 0.12); border: 1px solid #ff6368; color: #ff9ea2; }
.skeleton-grid { display: grid; grid-template-columns: repeat(4, 1fr); gap: 12px; }
.skeleton-column { min-height: 220px; border-radius: 10px; background: linear-gradient(90deg, #141821, #1b2130, #141821); background-size: 200% 100%; animation: shimmer 1.4s infinite; }
@keyframes shimmer { 0% { background-position: 200% 0; } 100% { background-position: -200% 0; } }
.empty { text-align: center; padding: 60px 0; color: var(--text-dim, #8a93a6); }
.link-btn { display: inline-block; margin-top: 12px; text-decoration: none; }
.board { display: grid; grid-template-columns: repeat(4, 1fr); gap: 12px; align-items: start; }
.column h3 { margin: 0 0 8px; font-size: 14px; display: flex; gap: 8px; align-items: center; }
.count { background: var(--bg, #0d1017); border-radius: 10px; padding: 0 8px; font-size: 12px; color: var(--text-dim, #8a93a6); }
.empty-column { color: var(--text-dim, #8a93a6); text-align: center; padding: 24px 0; }
.card { background: var(--panel, #161a23); border: 1px solid var(--border, #262c3a); border-radius: 10px; padding: 12px; margin-bottom: 10px; }
.card.highlight { border-color: var(--accent, #4f8cff); }
.todo h4 { margin: 0 0 6px; font-size: 13px; line-height: 1.4; }
.meta { display: flex; gap: 6px; flex-wrap: wrap; align-items: center; margin: 0 0 6px; }
.badge { font-size: 11px; padding: 1px 8px; border-radius: 10px; border: 1px solid var(--border, #262c3a); }
.badge.kind { color: var(--accent, #4f8cff); border-color: var(--accent, #4f8cff); }
.status-done { color: #58d68d; border-color: #58d68d; }
.status-blocked { color: #ff7b81; border-color: #ff7b81; }
.status-needs_user { color: #ffc46b; border-color: #ffc46b; }
.dim { color: var(--text-dim, #8a93a6); font-size: 12px; }
.time { margin: 0; }
.blocked-box, .done-box { margin-top: 8px; }
.blocked-reason { margin: 0 0 8px; font-size: 12px; color: #ff9ea2; }
.ghost { background: transparent; border: 1px solid var(--border, #262c3a); color: var(--text, #e7ebf3); border-radius: 8px; padding: 6px 12px; cursor: pointer; font-size: 12px; }
.ghost:hover { border-color: var(--accent, #4f8cff); color: var(--accent, #4f8cff); }
.evidence { margin: 8px 0 0; padding-left: 18px; font-size: 12px; }
.evidence a { color: var(--accent, #4f8cff); }
@media (max-width: 1100px) { .board, .skeleton-grid { grid-template-columns: repeat(2, 1fr); } }
</style>
