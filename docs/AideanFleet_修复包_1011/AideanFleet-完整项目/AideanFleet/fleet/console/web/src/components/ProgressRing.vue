<script setup lang="ts">
/**
 * ProgressRing · 空心圆进度（工作包 §9.3-2 / 用户原始设计）
 * 三态视觉规则：
 *   done    = 绿实心
 *   todo    = 红空心
 *   current = 青碧色、圆更大、圆心写百分比
 */
import { computed } from 'vue'

const props = withDefaults(
  defineProps<{
    percent?: number
    status?: 'done' | 'todo' | 'current'
    size?: number
    /** 圆心百分比文字仅在 current 态默认显示 */
    showText?: boolean
    title?: string
  }>(),
  { percent: 0, status: 'todo', size: 22, showText: undefined, title: '' },
)

const clamped = computed(() => Math.max(0, Math.min(100, Number(props.percent) || 0)))

const showText = computed(() => props.showText ?? props.status === 'current')

const strokeWidth = computed(() => (props.size >= 40 ? 4 : 2.5))

const radius = computed(() => (props.size - strokeWidth.value) / 2)

const circumference = computed(() => 2 * Math.PI * radius.value)

const dashOffset = computed(() => circumference.value * (1 - clamped.value / 100))

const color = computed(() => {
  if (props.status === 'done') return 'var(--ok)'
  if (props.status === 'current') return 'var(--accent-cyan)'
  return 'var(--danger)'
})

const textSize = computed(() => Math.max(9, Math.round(props.size * 0.3)))
</script>

<template>
  <span class="ring" :title="title" :style="{ width: `${size}px`, height: `${size}px` }">
    <svg :width="size" :height="size" :viewBox="`0 0 ${size} ${size}`" aria-hidden="true">
      <circle
        v-if="status === 'done'"
        :cx="size / 2"
        :cy="size / 2"
        :r="radius"
        :fill="color"
        stroke="none"
      />
      <circle
        v-else-if="status === 'todo'"
        :cx="size / 2"
        :cy="size / 2"
        :r="radius"
        fill="none"
        :stroke="color"
        :stroke-width="strokeWidth"
      />
      <template v-else>
        <circle
          :cx="size / 2"
          :cy="size / 2"
          :r="radius"
          fill="none"
          :stroke="'var(--accent-cyan-dim)'"
          :stroke-width="strokeWidth"
        />
        <circle
          class="arc"
          :cx="size / 2"
          :cy="size / 2"
          :r="radius"
          fill="none"
          :stroke="color"
          :stroke-width="strokeWidth"
          stroke-linecap="round"
          :stroke-dasharray="circumference"
          :stroke-dashoffset="dashOffset"
          :transform="`rotate(-90 ${size / 2} ${size / 2})`"
        />
      </template>
    </svg>
    <b v-if="showText" class="ring-text" :style="{ fontSize: `${textSize}px` }">
      {{ Math.round(clamped) }}%
    </b>
  </span>
</template>

<style scoped>
.ring {
  position: relative;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  flex: 0 0 auto;
}

.ring svg {
  display: block;
}

.arc {
  transition: stroke-dashoffset var(--dur-slow) var(--ease);
}

.ring-text {
  position: absolute;
  inset: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  color: var(--accent-cyan);
  font-family: var(--font-mono);
  font-weight: 600;
  letter-spacing: -0.4px;
  pointer-events: none;
}
</style>
