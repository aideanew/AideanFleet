<script setup lang="ts">
/**
 * StreamText · 流式文本（逐字显现）
 * 用于 Manager 回执/执行过程的“打字机”效果；文本变化时自动从头播放。
 */
import { onBeforeUnmount, ref, watch } from 'vue'

const props = withDefaults(
  defineProps<{
    text?: string
    /** 每字间隔（毫秒） */
    speed?: number
    /** 关闭动画时直接整体显示 */
    instant?: boolean
    autoscroll?: boolean
  }>(),
  { text: '', speed: 18, instant: false, autoscroll: false },
)

const emit = defineEmits<{ (e: 'done'): void }>()

const shown = ref('')
let timer: ReturnType<typeof setInterval> | null = null

function stop() {
  if (timer !== null) {
    clearInterval(timer)
    timer = null
  }
}

function play(value: string) {
  stop()
  if (props.instant || !value) {
    shown.value = value
    emit('done')
    return
  }
  shown.value = ''
  let index = 0
  timer = setInterval(() => {
    index += 1
    shown.value = value.slice(0, index)
    if (index >= value.length) {
      stop()
      emit('done')
    }
  }, Math.max(4, props.speed))
}

watch(
  () => [props.text, props.instant] as const,
  ([value]) => play(value ?? ''),
  { immediate: true },
)

onBeforeUnmount(stop)
</script>

<template>
  <span class="stream">{{ shown }}</span>
</template>

<style scoped>
.stream {
  white-space: pre-wrap;
  word-break: break-word;
}
</style>
