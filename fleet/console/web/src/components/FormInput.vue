<script setup lang="ts">
import { computed } from 'vue'

const props = withDefaults(
  defineProps<{
    modelValue?: string | number
    label?: string
    type?: 'text' | 'password' | 'number' | 'email'
    placeholder?: string
    hint?: string
    error?: string
    disabled?: boolean
    /** 多行文本域 */
    multiline?: boolean
    rows?: number
    /** 等宽字体（用于命令、路径、密钥占位） */
    mono?: boolean
    /** 掩码字段：显示为只读占位，聚焦后允许覆盖 */
    masked?: boolean
  }>(),
  {
    modelValue: '',
    label: '',
    type: 'text',
    placeholder: '',
    hint: '',
    error: '',
    disabled: false,
    multiline: false,
    rows: 3,
    mono: false,
    masked: false,
  },
)

const emit = defineEmits<{ (e: 'update:modelValue', value: string | number): void }>()

const current = computed(() => (props.modelValue === undefined || props.modelValue === null ? '' : String(props.modelValue)))

function onInput(event: Event) {
  const target = event.target as HTMLInputElement | HTMLTextAreaElement
  if (props.type === 'number') {
    const raw = target.value
    emit('update:modelValue', raw === '' ? '' : Number(raw))
    return
  }
  emit('update:modelValue', target.value)
}
</script>

<template>
  <label class="field" :class="{ disabled, invalid: !!error }">
    <span v-if="label" class="label">
      {{ label }}
      <em v-if="masked" class="mask-tag" title="出于安全考虑，密钥以占位符回显">掩码</em>
    </span>

    <textarea
      v-if="multiline"
      class="control"
      :class="{ mono }"
      :rows="rows"
      :value="current"
      :placeholder="placeholder"
      :disabled="disabled"
      @input="onInput"
    />
    <input
      v-else
      class="control"
      :class="{ mono }"
      :type="type"
      :value="current"
      :placeholder="placeholder"
      :disabled="disabled"
      :autocomplete="type === 'password' ? 'new-password' : 'off'"
      :spellcheck="false"
      @input="onInput"
    />

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
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 12px;
  color: var(--text-dim);
}

.mask-tag {
  font-style: normal;
  font-size: 10px;
  padding: 0 6px;
  border-radius: 999px;
  color: var(--accent-cyan);
  background: var(--accent-cyan-dim);
}

.control {
  width: 100%;
  padding: 8px 10px;
  border-radius: var(--radius-sm);
  border: 1px solid var(--line-strong);
  background: var(--bg-input);
  color: var(--text);
  transition: border-color var(--dur-fast) var(--ease), background var(--dur-fast) var(--ease);
  resize: vertical;
}

.control.mono {
  font-family: var(--font-mono);
  font-size: 12.5px;
}

.control:focus {
  outline: none;
  border-color: var(--accent-cyan);
  background: #0b1424;
}

.control::placeholder {
  color: var(--text-mute);
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
