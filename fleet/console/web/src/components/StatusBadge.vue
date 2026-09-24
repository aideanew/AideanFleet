<script setup lang="ts">
import { computed } from 'vue'
import {
  REVIEW_STATUS_LABEL,
  REVIEW_STATUS_TONE,
  TASK_STATE_LABEL,
  TASK_STATE_TONE,
  type Tone,
} from '@/utils/labels'

const props = withDefaults(
  defineProps<{
    /** 任务状态（10 态） */
    state?: string
    /** 审查状态（6 值） */
    review?: string
    /** 直接指定文案（优先级最高） */
    label?: string
    /** 直接指定语义色 */
    tone?: Tone
    dot?: boolean
  }>(),
  { dot: true },
)

const resolved = computed<{ label: string; tone: Tone }>(() => {
  if (props.label) return { label: props.label, tone: props.tone ?? 'mute' }
  if (props.state) {
    return {
      label: TASK_STATE_LABEL[props.state] ?? props.state,
      tone: TASK_STATE_TONE[props.state] ?? 'mute',
    }
  }
  if (props.review) {
    return {
      label: REVIEW_STATUS_LABEL[props.review] ?? props.review,
      tone: REVIEW_STATUS_TONE[props.review] ?? 'mute',
    }
  }
  return { label: '未知', tone: 'mute' }
})
</script>

<template>
  <span class="badge" :class="`tone-${resolved.tone}`">
    <i v-if="dot" class="dot" />
    <span>{{ resolved.label }}</span>
  </span>
</template>

<style scoped>
.badge {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 2px 9px;
  border-radius: 999px;
  font-size: 12px;
  line-height: 1.7;
  white-space: nowrap;
  border: 1px solid transparent;
}

.dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: currentColor;
  flex: 0 0 auto;
}

.tone-ok {
  color: var(--ok);
  background: var(--ok-dim);
  border-color: rgba(34, 197, 94, 0.32);
}
.tone-danger {
  color: var(--danger);
  background: var(--danger-dim);
  border-color: rgba(239, 68, 68, 0.32);
}
.tone-warn {
  color: var(--warn);
  background: var(--warn-dim);
  border-color: rgba(245, 158, 11, 0.32);
}
.tone-info {
  color: var(--info);
  background: var(--info-dim);
  border-color: rgba(96, 165, 250, 0.32);
}
.tone-cyan {
  color: var(--accent-cyan);
  background: var(--accent-cyan-dim);
  border-color: var(--line-accent);
}
.tone-violet {
  color: #a9a3f0;
  background: rgba(127, 119, 221, 0.16);
  border-color: rgba(127, 119, 221, 0.34);
}
.tone-mute {
  color: var(--text-dim);
  background: var(--mute-dim);
  border-color: var(--line);
}
</style>
