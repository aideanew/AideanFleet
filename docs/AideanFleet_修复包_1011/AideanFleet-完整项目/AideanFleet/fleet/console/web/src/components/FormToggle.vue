<script setup lang="ts">
const props = withDefaults(
  defineProps<{
    modelValue?: boolean
    label?: string
    hint?: string
    disabled?: boolean
    /** 默认态（用于展示“默认开/默认关”提示） */
    defaultState?: boolean
    /** 透传到 switch 按钮的 data-testid（e2e 钩子必须落在承载 aria-checked 的元素上） */
    testId?: string
  }>(),
  { modelValue: false, label: '', hint: '', disabled: false, defaultState: undefined, testId: undefined },
)

const emit = defineEmits<{ (e: 'update:modelValue', value: boolean): void }>()

function toggle() {
  if (props.disabled) return
  emit('update:modelValue', !props.modelValue)
}
</script>

<template>
  <div class="toggle-row" :class="{ disabled }">
    <button
      type="button"
      class="switch"
      :class="{ on: modelValue }"
      role="switch"
      :data-testid="testId"
      :aria-checked="modelValue"
      :aria-label="label || '开关'"
      :disabled="disabled"
      @click="toggle"
    >
      <span class="knob" />
    </button>
    <div class="text">
      <span class="label">
        {{ label }}
        <em v-if="defaultState !== undefined" class="dft">默认{{ defaultState ? '开' : '关' }}</em>
      </span>
      <span v-if="hint" class="hint">{{ hint }}</span>
    </div>
  </div>
</template>

<style scoped>
.toggle-row {
  display: flex;
  align-items: flex-start;
  gap: 10px;
}

.toggle-row.disabled {
  opacity: 0.55;
}

.switch {
  flex: 0 0 auto;
  width: 40px;
  height: 22px;
  margin-top: 1px;
  padding: 0;
  border-radius: 999px;
  border: 1px solid var(--line-strong);
  background: var(--bg-input);
  position: relative;
  transition: background var(--dur) var(--ease), border-color var(--dur) var(--ease);
}

.switch.on {
  background: rgba(0, 212, 255, 0.22);
  border-color: var(--accent-cyan);
}

.knob {
  position: absolute;
  top: 2px;
  left: 2px;
  width: 16px;
  height: 16px;
  border-radius: 50%;
  background: var(--text-mute);
  transition: transform var(--dur) var(--ease), background var(--dur) var(--ease);
}

.switch.on .knob {
  transform: translateX(18px);
  background: var(--accent-cyan);
}

.text {
  display: flex;
  flex-direction: column;
  gap: 2px;
  min-width: 0;
}

.label {
  font-size: 13px;
  color: var(--text);
  display: flex;
  align-items: center;
  gap: 8px;
}

.dft {
  font-style: normal;
  font-size: 10px;
  padding: 0 6px;
  border-radius: 999px;
  color: var(--text-dim);
  background: var(--mute-dim);
}

.hint {
  font-size: 12px;
  color: var(--text-mute);
  line-height: 1.6;
}
</style>
