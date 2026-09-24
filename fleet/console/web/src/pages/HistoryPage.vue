<script setup lang="ts">
/**
 * HistoryPage · 历史进度（需求5）
 *
 * 数据源：GET /api/history/tasks（tasks 表按 updated_at 倒序）。
 * 每一行回答三件事：这个任务是谁执行的（assignee）、谁审查的（reviewer）、执行了多久（duration_ms）。
 * 行点击复用 TaskDetailModal，与总览页同一套详情弹窗（证据路径、阻塞原因等）。
 */
import { computed, onMounted, ref } from 'vue'
import StatusBadge from '@/components/StatusBadge.vue'
import TaskDetailModal from '@/components/TaskDetailModal.vue'
import { api } from '@/api/client'
import { useAuthStore } from '@/stores/auth'
import type { HistoryTaskRow } from '@/api/types'
import { formatTime } from '@/utils/labels'

const auth = useAuthStore()

const rows = ref<HistoryTaskRow[]>([])
const loading = ref(false)
const error = ref('')
const keyword = ref('')
const statusFilter = ref('')
const roleFilter = ref('')
const detailTaskId = ref<string | null>(null)

async function load(): Promise<void> {
  loading.value = true
  error.value = ''
  try {
    const result = await api.historyTasks(auth.project || undefined, 500)
    rows.value = result.tasks ?? []
  } catch (caught) {
    error.value = caught instanceof Error ? caught.message : '历史任务加载失败'
    rows.value = []
  } finally {
    loading.value = false
  }
}

onMounted(() => { void load() })

/** 下拉可选项：状态与角色都从当前数据里归纳，避免维护第二份枚举 */
const statusOptions = computed(() => {
  const set = new Set(rows.value.map((row) => row.exec_status).filter(Boolean))
  return [...set].sort()
})

const roleOptions = computed(() => {
  const set = new Set<string>()
  for (const row of rows.value) {
    if (row.assignee) set.add(row.assignee)
    if (row.reviewer) set.add(row.reviewer)
  }
  return [...set].sort()
})

const filtered = computed(() => {
  const kw = keyword.value.trim().toLowerCase()
  return rows.value.filter((row) => {
    if (statusFilter.value && row.exec_status !== statusFilter.value) return false
    if (roleFilter.value && row.assignee !== roleFilter.value && row.reviewer !== roleFilter.value) return false
    if (!kw) return true
    return [row.task_id, row.title, row.subtask, row.stage]
      .some((field) => String(field ?? '').toLowerCase().includes(kw))
  })
})

const summary = computed(() => {
  const done = filtered.value.filter((row) => row.exec_status === 'DONE' || row.exec_status === 'PARTIAL').length
  const duration = filtered.value.reduce((acc, row) => acc + Number(row.duration_ms ?? 0), 0)
  const tokens = filtered.value.reduce((acc, row) => acc + Number(row.token ?? 0), 0)
  return { count: filtered.value.length, done, duration, tokens }
})

function durationText(ms: number): string {
  const value = Number(ms ?? 0)
  if (!value) return '—'
  const total = Math.round(value / 1000)
  if (total < 60) return `${total}秒`
  const m = Math.floor(total / 60)
  const s = total % 60
  if (m < 60) return `${m}分${s}秒`
  return `${Math.floor(m / 60)}时${m % 60}分`
}

function tokenText(n: number): string {
  return new Intl.NumberFormat('en-US').format(Math.round(n || 0))
}

function who(row: HistoryTaskRow): string {
  const parts = [row.assignee || row.role].filter(Boolean)
  return parts.join(' / ') || '—'
}
</script>

<template>
  <section class="page">
    <header class="page-head">
      <div class="page-title">
        <h2>历史</h2>
        <span class="page-sub">历史任务列表 · 谁执行、谁审查、执行了多久 · 点击行查看详情</span>
      </div>
      <div class="row">
        <button class="btn" type="button" :disabled="loading" @click="load">
          {{ loading ? '加载中…' : '刷新' }}
        </button>
      </div>
    </header>

    <p v-if="error" class="err-text">{{ error }}</p>

    <!-- 汇总指标：随筛选联动 -->
    <div class="metrics" data-testid="history-metrics">
      <div class="metric">
        <span class="k">任务数</span>
        <b class="v mono">{{ summary.count }}</b>
      </div>
      <div class="metric">
        <span class="k">已完成</span>
        <b class="v mono">{{ summary.done }}</b>
      </div>
      <div class="metric">
        <span class="k">总耗时</span>
        <b class="v mono">{{ durationText(summary.duration) }}</b>
      </div>
      <div class="metric">
        <span class="k">总 Token</span>
        <b class="v mono">{{ tokenText(summary.tokens) }}</b>
      </div>
    </div>

    <div class="card" data-testid="history-table-card">
      <div class="card-title">
        <span>历史任务 · {{ summary.count }} 条</span>
        <div class="filters">
          <input v-model="keyword" class="control filter" type="search" placeholder="搜任务ID / 标题 / 子任务" />
          <select v-model="statusFilter" class="control filter">
            <option value="">全部状态</option>
            <option v-for="s in statusOptions" :key="s" :value="s">{{ s }}</option>
          </select>
          <select v-model="roleFilter" class="control filter">
            <option value="">全部角色</option>
            <option v-for="r in roleOptions" :key="r" :value="r">{{ r }}</option>
          </select>
        </div>
      </div>

      <div class="table-wrap">
        <table class="history-table">
          <thead>
            <tr>
              <th>任务</th>
              <th>阶段</th>
              <th>执行角色</th>
              <th>审查角色</th>
              <th>执行状态</th>
              <th>审查结论</th>
              <th>耗时</th>
              <th>Token</th>
              <th>返工</th>
              <th>最近更新</th>
            </tr>
          </thead>
          <tbody>
            <tr
              v-for="row in filtered"
              :key="row.task_id"
              class="clickable"
              :title="`点击查看 ${row.task_id} 详情`"
              @click="detailTaskId = row.task_id"
            >
              <td>
                <span class="mono tid">{{ row.task_id }}</span>
                <span class="ttitle">{{ row.subtask || row.title }}</span>
              </td>
              <td class="mute2 tiny">{{ row.stage || '—' }}</td>
              <td>{{ who(row) }}</td>
              <td>{{ row.reviewer || '—' }}</td>
              <td><StatusBadge :state="row.exec_status" /></td>
              <td><StatusBadge v-if="row.review_status" :review="row.review_status" /></td>
              <td class="mono">{{ durationText(row.duration_ms) }}</td>
              <td class="mono">{{ tokenText(row.token) }}</td>
              <td class="mono" :class="{ rework: row.rework_count }">{{ row.rework_count || '—' }}</td>
              <td class="mono tiny mute2">{{ row.updated_at ? formatTime(row.updated_at) : '—' }}</td>
            </tr>
            <tr v-if="!filtered.length && !loading">
              <td colspan="10" class="empty-cell">暂无历史任务（任务执行收口后会出现在这里）</td>
            </tr>
          </tbody>
        </table>
      </div>
      <p class="hint">· 耗时为该任务执行阶段的累计时长；Token 为任务记录的用量；审查角色为空表示该任务未安排审查环节。</p>
    </div>

    <TaskDetailModal :task-id="detailTaskId" @close="detailTaskId = null" />
  </section>
</template>

<style scoped>
.metrics {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 12px;
  margin-bottom: 14px;
}

.metric {
  display: flex;
  flex-direction: column;
  gap: 4px;
  padding: 12px 14px;
  border: 1px solid var(--line);
  border-radius: var(--radius);
  background: var(--bg-panel);
}

.metric .k {
  font-size: 12px;
  color: var(--text-mute);
}

.metric .v {
  font-size: 15px;
  color: var(--text);
}

.filters {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
}

.filter {
  height: 28px;
  padding: 0 9px;
  font-size: 12px;
  border-radius: var(--radius-sm);
  border: 1px solid var(--line-strong);
  background: var(--bg-input);
  color: var(--text);
}

.filter:focus {
  outline: none;
  border-color: var(--accent-cyan);
}

.history-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 12.5px;
}

.history-table th {
  text-align: left;
  font-weight: 500;
  color: var(--text-mute);
  font-size: 11.5px;
  padding: 6px 10px;
  border-bottom: 1px solid var(--line);
  white-space: nowrap;
}

.history-table td {
  padding: 8px 10px;
  border-bottom: 1px solid var(--line);
  color: var(--text-dim);
  vertical-align: middle;
}

.history-table tr.clickable {
  cursor: pointer;
}

.history-table tr.clickable:hover td {
  background: var(--bg-hover);
}

.tid {
  color: var(--text-mute);
  margin-right: 8px;
  font-size: 11.5px;
}

.ttitle {
  color: var(--text);
}

.rework {
  color: var(--danger);
}

.empty-cell {
  text-align: center;
  color: var(--text-mute);
  padding: 24px 0;
}

@media (max-width: 1280px) {
  .metrics {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}
</style>
