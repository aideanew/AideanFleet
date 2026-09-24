<script setup lang="ts">
import { computed } from 'vue'

interface Option {
  label: string
  value: string
}

const props = withDefaults(
  defineProps<{
    modelValue?: string
    label?: string
    options?: Option[]
    hint?: string
    error?: string
    disabled?: boolean
    placeholder?: string
  }>(),
  {
    modelValue: '',
    label: '',
    options: () => [],
    hint: '',
    error: '',
    disabled: false,
    placeholder: '请选择',
  },
)

const emit = defineEmits<{ (e: 'update:modelValue', value: string): void }>()

const current = computed(() => String(props.modelValue ?? ''))

function onChange(event: Event) {
  emit('update:modelValue', (event.target as HTMLSelectElement).value)
}
</script>

<template>
  <label class="field" :class="{ disabled, invalid: !!error }">
    <span v-if="label" class="label">{{ label }}</span>
    <select class="control" :value="current" :disabled="disabled" @change="onChange">
      <option v-if="placeholder" value="" disabled>{{ placeholder }}</option>
      <option v-for="option in options" :key="option.value" :value="option.value">
        {{ option.label }}
      </option>
    </select>
    <span v-if="error" class="msg err-text">{{ error }}</span>
    <span v-else-if="hint" class="msg hint">{{ hint }}</span>
  </label>
</template>

<style scoped>
.field {
  display: flex;
  flex-direction: column;
  gap: 5px;
  min-width: 0;
}

.label {
  font-size: 12px;
  color: var(--text-dim);
}

.control {
  width: 100%;
  padding: 8px 10px;
  border-radius: var(--radius-sm);
  border: 1px solid var(--line-strong);
  background: var(--bg-input);
  color: var(--text);
  transition: border-color var(--dur-fast) var(--ease);
}

.control:focus {
  outline: none;
  border-color: var(--accent-cyan);
}

.disabled .control {
  opacity: 0.55;
  cursor: not-allowed;
}

.invalid .control {
  border-color: var(--danger);
}

.msg {
  font-size: 12px;
  line-height: 1.6;
}
</style>
