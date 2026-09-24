<script setup lang="ts">
/**
 * Collapsible · 可折叠容器
 * 用 max-height + opacity + translateY 做上移缩起动画（工作包 §9.3-3 缺陷 #3 依赖它）。
 */
import { nextTick, onMounted, ref, watch } from 'vue'

const props = withDefaults(
  defineProps<{
    open?: boolean
    /** 仅渲染内容，不渲染默认标题行（调用方自带头部） */
    headless?: boolean
    duration?: number
    /** 标题行左侧强调色条 */
    accent?: 'cyan' | 'ok' | 'mute' | 'danger' | 'warn'
  }>(),
  { open: true, headless: false, duration: 320, accent: 'cyan' },
)

const emit = defineEmits<{ (e: 'update:open', value: boolean): void }>()

const bodyRef = ref<HTMLElement | null>(null)
const maxHeight = ref('0px')
const ready = ref(false)

function toOpen() {
  const el = bodyRef.value
  if (!el) {
    maxHeight.value = 'none'
    return
  }
  maxHeight.value = `${el.scrollHeight}px`
  window.setTimeout(() => {
    if (props.open) maxHeight.value = 'none'
  }, props.duration)
}

function toClosed() {
  const el = bodyRef.value
  if (!el) {
    maxHeight.value = '0px'
    return
  }
  maxHeight.value = `${el.scrollHeight}px`
  window.requestAnimationFrame(() => {
    maxHeight.value = '0px'
  })
}

function sync() {
  if (props.open) toOpen()
  else toClosed()
  ready.value = true
}

function toggle() {
  emit('update:open', !props.open)
}

watch(() => props.open, () => nextTick(sync))
onMounted(() => nextTick(sync))

defineExpose({ sync })
</script>

<template>
  <section class="collapsible" :class="{ open }">
    <header v-if="!headless" class="head" :class="`accent-${accent}`" @click="toggle">
      <span class="caret" :class="{ open }">▸</span>
      <slot name="header" />
    </header>
    <div
      ref="bodyRef"
      class="body"
      :style="{ maxHeight, transitionDuration: `${duration}ms` }"
      :aria-hidden="!open"
    >
      <div class="body-inner" :class="{ hidden: !ready }">
        <slot />
      </div>
    </div>
  </section>
</template>

<style scoped>
.collapsible {
  border-radius: var(--radius);
}

.head {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 10px;
  border-radius: var(--radius-sm);
  cursor: pointer;
  user-select: none;
  transition: background var(--dur-fast) var(--ease);
}

.head:hover {
  background: var(--bg-hover);
}

.caret {
  display: inline-block;
  color: var(--text-mute);
  font-size: 11px;
  transition: transform var(--dur) var(--ease);
}

.caret.open {
  transform: rotate(90deg);
}

.body {
  overflow: hidden;
  opacity: 1;
  transform: translateY(0);
  transition-property: max-height, opacity, transform;
  transition-timing-function: var(--ease);
}

.collapsible:not(.open) > .body {
  opacity: 0;
  transform: translateY(-6px);
}

.body-inner.hidden {
  visibility: hidden;
}

.accent-cyan {
  border-left: 2px solid var(--accent-cyan);
}
.accent-ok {
  border-left: 2px solid var(--ok);
}
.accent-danger {
  border-left: 2px solid var(--danger);
}
.accent-warn {
  border-left: 2px solid var(--warn);
}
.accent-mute {
  border-left: 2px solid var(--line-strong);
}
</style>
