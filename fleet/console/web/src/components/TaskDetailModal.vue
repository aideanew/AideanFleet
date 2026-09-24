<script setup lang="ts">
/**
 * TaskDetailModal · 任务详情弹窗（大纲 L1-C 3.2）
 * 数据源 GET /api/tasks/{id}：状态、执行角色、耗时、模型、返工次数与证据路径。
 */
import { ref, watch } from 'vue'
import Modal from '@/components/Modal.vue'
import StatusBadge from '@/components/StatusBadge.vue'
import { api } from '@/api/client'
import type { TaskDetail } from '@/api/types'
import { formatTime } from '@/utils/labels'

const props = defineProps<{ taskId: string | null }>()
const emit = defineEmits<{ (e: 'close'): void }>()

const detail = ref<TaskDetail | null>(null)
const loading = ref(false)
const error = ref('')

async function load(id: string): Promise<void> {
  loading.value = true
  error.value = ''
  detail.value = null
  try {
    const result = await api.getTask(id)
    detail.value = result.task ?? null
    if (!result.task) error.value = '任务不存在'
  } catch (caught) {
    error.value = caught instanceof Error ? caught.message : '详情加载失败'
  } finally {
    loading.value = false
  }
}

watch(
  () => props.taskId,
  (id) => {
    if (id) void load(id)
  },
)

function durationText(ms: unknown): string {
  const value = Number(ms ?? 0)
  if (!value) return '—'
  const total = Math.round(value / 1000)
  const m = Math.floor(total / 60)
  const s = total % 60
  return m ? `${m}分${s}秒` : `${s}秒`
}

function row(label: string, value: unknown): { label: string; value: string } {
  return { label, value: String(value ?? '—') }
}
</script>

<template>
  <Modal
    :model-value="Boolean(props.taskId)"
    :title="`任务详情 ${props.taskId ?? ''}`"
    :width="560"
    @update:model-value="emit('close')"
  >
    <div v-if="loading" class="hint">加载中…</div>
    <div v-else-if="error" class="err-text">{{ error }}</div>
    <template v-else-if="detail">
      <div class="head-row">
        <b class="title">{{ detail.title || detail.task_id }}</b>
        <StatusBadge :state="String(detail.exec_status ?? '')" />
      </div>
      <dl class="grid">
        <div v-for="item in [
          row('执行角色', detail.assignee),
          row('审查角色', detail.reviewer),
          row('执行耗时', durationText(detail.duration_ms)),
          row('模型', detail.model),
          row('执行体会话', detail.executor_session_id),
          row('返工次数', detail.rework_count),
          row('审查结论', detail.review_status),
          row('阻塞原因', detail.blocked_reason),
          row('最近更新', detail.updated_at ? formatTime(String(detail.updated_at)) : '—'),
          row('证据报告', detail.report_path),
        ]" :key="item.label" class="cell">
          <dt>{{ item.label }}</dt>
          <dd :class="{ mono: item.label === '证据报告' }">{{ item.value }}</dd>
        </div>
      </dl>
    </template>
  </Modal>
</template>

<style scoped>
.head-row {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 12px;
}

.title {
  font-size: 14px;
}

.grid {
  margin: 0;
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 10px 16px;
}

.cell dt {
  font-size: 11px;
  color: var(--text-mute);
  margin-bottom: 2px;
}

.cell dd {
  margin: 0;
  font-size: 12.5px;
  color: var(--text);
  word-break: break-all;
}

.mono {
  font-family: var(--font-mono, monospace);
  font-size: 11.5px;
  color: var(--text-dim);
}
</style>
