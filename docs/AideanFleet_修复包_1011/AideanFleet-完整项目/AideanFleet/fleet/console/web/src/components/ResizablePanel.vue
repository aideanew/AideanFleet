<script setup lang="ts">
/**
 * ResizablePanel · 可拖拽缩放的面板（工作包 §9.2-3，直接针对缺陷 #4）
 *
 * 三条硬规范：
 *  1. 拖拽期间禁用 width transition（.dragging 关闭过渡），松手恢复 → 消除抖动；
 *  2. 折叠/展开与拖拽值彻底解耦：折叠只改 collapsed，展开恢复 lastUserWidth，
 *     不再被旧版 `.collapsed{width:56px !important}` 覆盖；
 *  3. 拖到 min+8px 以下自动进入折叠态（联动），拖回 min+8px 以上自动展开。
 */
import { onMounted, ref, watch } from 'vue'

const props = withDefaults(
  defineProps<{
    side?: 'left' | 'right'
    min?: number
    max?: number
    defaultWidth?: number
    collapsedWidth?: number
    collapsed?: boolean
    /** 传入后把“最近一次拖拽宽度”持久化（仅存一个数字，无任何密钥） */
    storageKey?: string
    /** 折叠时是否仍显示拖拽热区 */
    handleWhenCollapsed?: boolean
  }>(),
  {
    side: 'left',
    min: 180,
    max: 460,
    defaultWidth: 208,
    collapsedWidth: 60,
    collapsed: false,
    storageKey: '',
    handleWhenCollapsed: true,
  },
)

const emit = defineEmits<{
  (e: 'update:collapsed', value: boolean): void
  (e: 'resize', width: number): void
}>()

const COLLAPSE_SNAP = 8

/** 最近一次用户拖拽宽度（与折叠状态无关，展开时恢复到它） */
const lastUserWidth = ref(props.defaultWidth)
const width = ref(props.collapsed ? props.collapsedWidth : props.defaultWidth)
const dragging = ref(false)
const handleEl = ref<HTMLElement | null>(null)

let startX = 0
let startWidth = 0
let activePointer = -1

function persist() {
  if (!props.storageKey) return
  try {
    window.localStorage.setItem(props.storageKey, String(Math.round(lastUserWidth.value)))
  } catch {
    /* localStorage 不可用时降级为会话内记忆 */
  }
}

function restore() {
  if (!props.storageKey) return
  try {
    const raw = window.localStorage.getItem(props.storageKey)
    if (!raw) return
    const value = Number(raw)
    if (Number.isFinite(value)) {
      lastUserWidth.value = Math.max(props.min, Math.min(props.max, value))
    }
  } catch {
    /* 忽略 */
  }
}

function onPointerDown(event: PointerEvent) {
  if (event.button !== 0) return
  dragging.value = true
  startX = event.clientX
  startWidth = width.value
  activePointer = event.pointerId
  handleEl.value?.setPointerCapture?.(event.pointerId)
  event.preventDefault()
}

function onPointerMove(event: PointerEvent) {
  if (!dragging.value) return
  const delta = props.side === 'left' ? event.clientX - startX : startX - event.clientX
  const raw = startWidth + delta

  // 规范 3：拖过折叠阈值即联动折叠 / 展开
  if (raw < props.min + COLLAPSE_SNAP) {
    if (!props.collapsed) emit('update:collapsed', true)
    width.value = props.collapsedWidth
    return
  }
  if (props.collapsed) emit('update:collapsed', false)
  width.value = Math.max(props.min, Math.min(props.max, raw))
}

function onPointerUp() {
  if (!dragging.value) return
  dragging.value = false
  try {
    handleEl.value?.releasePointerCapture?.(activePointer)
  } catch {
    /* 指针已释放 */
  }
  activePointer = -1
  if (!props.collapsed) {
    // 规范 2：只有这里写入 lastUserWidth；折叠过程不写
    lastUserWidth.value = width.value
    persist()
    emit('resize', Math.round(width.value))
  }
}

function onToggle() {
  emit('update:collapsed', !props.collapsed)
}

// 规范 2：折叠/展开只切换宽度来源，互不覆盖
watch(
  () => props.collapsed,
  (collapsed) => {
    width.value = collapsed ? props.collapsedWidth : lastUserWidth.value
  },
)

onMounted(() => {
  restore()
  width.value = props.collapsed ? props.collapsedWidth : lastUserWidth.value
})

defineExpose({ lastUserWidth, width, onToggle })
</script>

<template>
  <aside
    class="panel"
    :class="[`side-${side}`, { dragging, collapsed }]"
    :style="{ width: `${Math.round(width)}px` }"
  >
    <div class="panel-body">
      <slot />
    </div>

    <button
      v-show="!collapsed || handleWhenCollapsed"
      ref="handleEl"
      class="handle"
      :class="`handle-${side}`"
      type="button"
      :title="collapsed ? '向右拖出以展开' : '拖拽调整宽度（拖到最窄自动折叠，双击折叠/展开）'"
      aria-label="拖拽调整宽度"
      @pointerdown="onPointerDown"
      @pointermove="onPointerMove"
      @pointerup="onPointerUp"
      @pointercancel="onPointerUp"
      @dblclick="onToggle"
    >
      <span class="grip" />
    </button>
  </aside>
</template>

<style scoped>
.panel {
  position: relative;
  flex: 0 0 auto;
  display: flex;
  flex-direction: column;
  min-height: 0;
  background: var(--bg-panel);
  /* 规范 1：默认带过渡；拖拽时用 .dragging 关闭 */
  transition: width var(--dur) var(--ease);
}

.panel.dragging {
  transition: none !important;
}

.panel.side-left {
  border-right: 1px solid var(--line);
}

.panel.side-right {
  border-left: 1px solid var(--line);
}

.panel-body {
  flex: 1;
  min-height: 0;
  overflow: auto;
  overflow-x: hidden;
}

/* 8px 拖拽热区 */
.handle {
  position: absolute;
  top: 0;
  bottom: 0;
  width: 8px;
  padding: 0;
  border: 0;
  background: transparent;
  cursor: col-resize;
  z-index: 6;
  display: flex;
  align-items: center;
  justify-content: center;
}

.handle-left {
  right: -4px;
}

.handle-right {
  left: -4px;
}

.handle .grip {
  display: block;
  width: 2px;
  height: 34px;
  border-radius: 2px;
  background: var(--line-strong);
  transition: background var(--dur-fast) var(--ease), height var(--dur-fast) var(--ease);
}

.handle:hover .grip,
.panel.dragging .grip {
  background: var(--accent-cyan);
  height: 56px;
}
</style>
