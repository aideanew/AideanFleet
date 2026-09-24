<script setup lang="ts">
import { computed } from 'vue'
import { relativeTime } from '@/utils/labels'

const props = withDefaults(
  defineProps<{
    role?: 'user' | 'manager' | 'system' | 'worker'
    time?: string | null
    /** 发送中：气泡半透明并显示“发送中…” */
    pending?: boolean
    /** 流式输出中 */
    streaming?: boolean
  }>(),
  { role: 'system', time: null, pending: false, streaming: false },
)

const meta = computed(() => {
  if (props.role === 'user') return { name: '我', cls: 'user' }
  if (props.role === 'manager') return { name: 'Manager', cls: 'manager' }
  if (props.role === 'worker') return { name: '执行角色', cls: 'manager' }
  return { name: '系统', cls: 'system' }
})
</script>

<template>
  <article class="bubble" :class="[meta.cls, { pending, streaming }]">
    <div class="meta">
      <span class="who">{{ meta.name }}</span>
      <span class="when mono">{{ pending ? '发送中…' : relativeTime(time) }}</span>
    </div>
    <div class="content">
      <slot />
    </div>
  </article>
</template>

<style scoped>
.bubble {
  display: flex;
  flex-direction: column;
  gap: 4px;
  max-width: 76%;
  padding: 10px 13px;
  border-radius: var(--radius);
  border: 1px solid var(--line);
  background: var(--bg-panel-2);
  transition: opacity var(--dur) var(--ease);
}

.bubble.pending {
  opacity: 0.62;
}

.bubble.user {
  align-self: flex-end;
  background: rgba(0, 212, 255, 0.1);
  border-color: var(--line-accent);
}

.bubble.manager {
  align-self: flex-start;
}

.bubble.system {
  align-self: center;
  max-width: 92%;
  background: transparent;
  border-style: dashed;
}

.meta {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 11px;
  color: var(--text-mute);
}

.who {
  color: var(--text-dim);
  font-weight: 600;
}

.bubble.user .who {
  color: var(--accent-cyan);
}

.content {
  font-size: 13px;
  line-height: 1.7;
  word-break: break-word;
  white-space: pre-wrap;
}

.streaming .content::after {
  content: '▍';
  color: var(--accent-cyan);
  animation: blink 1s steps(2, start) infinite;
}

@keyframes blink {
  to {
    visibility: hidden;
  }
}
</style>
