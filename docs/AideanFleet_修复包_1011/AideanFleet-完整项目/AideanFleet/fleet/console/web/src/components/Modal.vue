<script setup lang="ts">
import { onBeforeUnmount, watch } from 'vue'

const props = withDefaults(
  defineProps<{
    modelValue?: boolean
    title?: string
    confirmText?: string
    cancelText?: string
    dangerous?: boolean
    width?: number
  }>(),
  { modelValue: false, title: '确认', confirmText: '确定', cancelText: '取消', dangerous: false, width: 460 },
)

const emit = defineEmits<{
  (e: 'update:modelValue', value: boolean): void
  (e: 'confirm'): void
  (e: 'cancel'): void
}>()

function close() {
  emit('update:modelValue', false)
  emit('cancel')
}

function confirm() {
  emit('confirm')
}

function onKeydown(event: KeyboardEvent) {
  if (event.key === 'Escape') close()
}

watch(
  () => props.modelValue,
  (open) => {
    if (open) window.addEventListener('keydown', onKeydown)
    else window.removeEventListener('keydown', onKeydown)
  },
)

onBeforeUnmount(() => window.removeEventListener('keydown', onKeydown))
</script>

<template>
  <Teleport to="body">
    <Transition name="fade">
      <div v-if="modelValue" class="overlay" @click.self="close">
        <div class="modal" :style="{ width: `${width}px` }" role="dialog" aria-modal="true">
          <header class="head">
            <h3>{{ title }}</h3>
            <button class="btn btn-ghost close" type="button" aria-label="关闭" @click="close">✕</button>
          </header>
          <div class="body">
            <slot />
          </div>
          <footer class="foot">
            <slot name="footer">
              <button class="btn" type="button" @click="close">{{ cancelText }}</button>
              <button class="btn" :class="dangerous ? 'btn-danger' : 'btn-primary'" type="button" @click="confirm">
                {{ confirmText }}
              </button>
            </slot>
          </footer>
        </div>
      </div>
    </Transition>
  </Teleport>
</template>

<style scoped>
.overlay {
  position: fixed;
  inset: 0;
  z-index: 90;
  display: flex;
  align-items: center;
  justify-content: center;
  background: rgba(4, 8, 16, 0.66);
  backdrop-filter: blur(2px);
}

.modal {
  max-width: calc(100vw - 48px);
  border-radius: var(--radius-lg);
  border: 1px solid var(--line-strong);
  background: var(--bg-elevated);
  overflow: hidden;
}

.head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 13px 16px;
  border-bottom: 1px solid var(--line);
}

.head h3 {
  font-size: 14px;
}

.close {
  padding: 2px 8px;
  font-size: 13px;
}

.body {
  padding: 16px;
  font-size: 13px;
  line-height: 1.7;
  color: var(--text-dim);
  max-height: 60vh;
  overflow: auto;
}

.foot {
  display: flex;
  justify-content: flex-end;
  gap: 10px;
  padding: 12px 16px;
  border-top: 1px solid var(--line);
  background: var(--bg-panel-2);
}

.fade-enter-active,
.fade-leave-active {
  transition: opacity var(--dur) var(--ease);
}

.fade-enter-from,
.fade-leave-to {
  opacity: 0;
}
</style>
