<script setup lang="ts">
import { useToast } from '@/composables/useToast'

const { toasts, dismissToast } = useToast()
</script>

<template>
  <Teleport to="body">
    <div class="toast-host" aria-live="polite">
      <TransitionGroup name="toast">
        <div v-for="item in toasts" :key="item.id" class="toast" :class="`tone-${item.tone}`">
          <div class="text">
            <b>{{ item.title }}</b>
            <span v-if="item.detail" class="detail">{{ item.detail }}</span>
          </div>
          <button class="btn btn-ghost x" type="button" aria-label="关闭提示" @click="dismissToast(item.id)">
            ✕
          </button>
        </div>
      </TransitionGroup>
    </div>
  </Teleport>
</template>

<style scoped>
.toast-host {
  position: fixed;
  top: calc(var(--topbar-h) + 12px);
  right: 16px;
  z-index: 200;
  display: flex;
  flex-direction: column;
  gap: 10px;
  width: 336px;
  max-width: calc(100vw - 32px);
  pointer-events: none;
}

.toast {
  display: flex;
  align-items: flex-start;
  gap: 10px;
  padding: 11px 12px;
  border-radius: var(--radius);
  border: 1px solid var(--line-strong);
  background: var(--bg-elevated);
  box-shadow: 0 6px 22px rgba(0, 0, 0, 0.35);
  pointer-events: auto;
}

.toast.tone-ok {
  border-left: 3px solid var(--ok);
}
.toast.tone-danger {
  border-left: 3px solid var(--danger);
}
.toast.tone-warn {
  border-left: 3px solid var(--warn);
}
.toast.tone-info {
  border-left: 3px solid var(--accent-cyan);
}

.text {
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: 3px;
  min-width: 0;
}

.text b {
  font-size: 13px;
  font-weight: 600;
  color: var(--text);
}

.detail {
  font-size: 12px;
  color: var(--text-dim);
  line-height: 1.6;
  word-break: break-word;
}

.x {
  padding: 0 6px;
  font-size: 12px;
  line-height: 1.4;
}

.toast-enter-active,
.toast-leave-active {
  transition: opacity var(--dur) var(--ease), transform var(--dur) var(--ease);
}

.toast-enter-from,
.toast-leave-to {
  opacity: 0;
  transform: translateX(14px);
}
</style>
