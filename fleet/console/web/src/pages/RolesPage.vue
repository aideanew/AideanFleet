<script setup lang="ts">
/**
 * RolesPage · 角色
 * 角色提示词与模型绑定。bind_model_name 是有序数组（顺序即降级优先级），
 * 支持从模型池加入/移除，并可拖拽排序。adapter 绑定执行体。
 */
import { computed, onMounted, ref } from 'vue'
import FormInput from '@/components/FormInput.vue'
import FormSelect from '@/components/FormSelect.vue'
import { useConfigStore } from '@/stores/config'
import { toast } from '@/composables/useToast'
import type { RoleItem } from '@/api/types'

const config = useConfigStore()
const saving = ref(false)

const roles = computed(() => config.roles)
const modelNames = computed(() => config.models.map((m) => m.name))
const adapterOptions = computed(() => config.executors.map((e) => ({ label: e.name, value: e.name })))

const dragIndex = ref<number | null>(null)
const dragRole = ref<number | null>(null)
const pickerRole = ref<number | null>(null)

function addRole(): void {
  config.roles = [
    ...config.roles,
    { name: '', system_prompt: '', bind_model_name: [], adapter: config.executors[1]?.name ?? '' } as RoleItem,
  ]
}

function removeRole(index: number): void {
  const next = [...config.roles]
  next.splice(index, 1)
  config.roles = next
}

function addBinding(roleIndex: number, modelName: string): void {
  if (!modelName) return
  const role = config.roles[roleIndex]
  if (role.bind_model_name.includes(modelName)) {
    toast.warn('已绑定', `${role.name || '该角色'} 已包含模型 ${modelName}`)
    return
  }
  const next = [...config.roles]
  next[roleIndex] = { ...role, bind_model_name: [...role.bind_model_name, modelName] }
  config.roles = next
  pickerRole.value = null
}

function removeBinding(roleIndex: number, modelName: string): void {
  const role = config.roles[roleIndex]
  const next = [...config.roles]
  next[roleIndex] = { ...role, bind_model_name: role.bind_model_name.filter((m) => m !== modelName) }
  config.roles = next
}

function onDragStart(roleIndex: number, modelIndex: number): void {
  dragRole.value = roleIndex
  dragIndex.value = modelIndex
}

function onDrop(roleIndex: number, modelIndex: number): void {
  if (dragRole.value !== roleIndex || dragIndex.value === null || dragIndex.value === modelIndex) {
    dragIndex.value = null
    dragRole.value = null
    return
  }
  const next = [...config.roles]
  const role = next[roleIndex]
  const bound = [...role.bind_model_name]
  const [moved] = bound.splice(dragIndex.value, 1)
  bound.splice(modelIndex, 0, moved)
  next[roleIndex] = { ...role, bind_model_name: bound }
  config.roles = next
  dragIndex.value = null
  dragRole.value = null
}

async function save(): Promise<void> {
  const invalid = config.roles.find((r) => !r.name.trim())
  if (invalid) {
    toast.warn('校验未通过', '每个角色都必须填写 name')
    return
  }
  saving.value = true
  try {
    const message = await config.saveRoles(config.roles.map((r) => ({ ...r })))
    toast.ok('角色已保存', message)
  } catch (error) {
    toast.fail('保存失败', error instanceof Error ? error.message : '')
  } finally {
    saving.value = false
  }
}

onMounted(() => {
  if (!config.roles.length || !config.models.length) void config.loadAll()
})
</script>

<template>
  <section class="page">
    <header class="page-head">
      <div class="page-title">
        <h2>角色</h2>
        <span class="page-sub">角色提示词与模型绑定 · 绑定顺序即降级优先级，可拖拽调整</span>
      </div>
      <div class="row">
        <button class="btn" type="button" @click="addRole">新增角色</button>
        <button class="btn btn-primary" type="button" :disabled="saving" @click="save">
          {{ saving ? '保存中…' : '保存角色' }}
        </button>
      </div>
    </header>

    <p v-if="config.lastError" class="err-text">{{ config.lastError }}</p>

    <div v-for="(role, roleIndex) in roles" :key="roleIndex" class="item-card">
      <div class="item-head">
        <b>{{ role.name || `未命名角色 #${roleIndex + 1}` }}</b>
        <span class="spacer" />
        <button class="btn btn-ghost" type="button" @click="removeRole(roleIndex)">移除</button>
      </div>

      <div class="form-grid">
        <FormInput v-model="role.name" label="角色名" placeholder="如 manager / fe-1 / reviewer-1" />
        <FormSelect
          v-model="role.adapter"
          label="执行体（adapter）"
          :options="adapterOptions"
          placeholder="选择执行体"
          hint="该角色由哪个执行体进程承载"
        />
        <FormInput
          v-model="role.system_prompt"
          class="span-2"
          label="系统提示词"
          multiline
          :rows="4"
          placeholder="描述该角色的职责边界、可改动的文件范围、回执格式等"
        />
      </div>

      <div class="binding">
        <div class="binding-head">
          <span class="label">模型绑定（顺序即降级优先级）</span>
          <span class="spacer" />
          <select
            v-if="pickerRole === roleIndex"
            class="picker"
            @change="addBinding(roleIndex, ($event.target as HTMLSelectElement).value)"
          >
            <option value="">选择模型…</option>
            <option v-for="name in modelNames" :key="name" :value="name">{{ name }}</option>
          </select>
          <button v-else class="tag add" type="button" @click="pickerRole = roleIndex">+ 绑定模型</button>
        </div>

        <div v-if="role.bind_model_name.length" class="chips">
          <span
            v-for="(name, modelIndex) in role.bind_model_name"
            :key="name"
            class="chip"
            :class="{ dragging: dragRole === roleIndex && dragIndex === modelIndex }"
            draggable="true"
            :title="`优先级 ${modelIndex + 1} · 拖拽调整顺序`"
            @dragstart="onDragStart(roleIndex, modelIndex)"
            @dragover.prevent
            @drop="onDrop(roleIndex, modelIndex)"
            @dragend="dragIndex = null"
          >
            <span class="ord mono">{{ modelIndex + 1 }}</span>
            {{ name }}
            <button class="x" type="button" title="移除绑定" @click="removeBinding(roleIndex, name)">✕</button>
          </span>
        </div>
        <p v-else class="hint">尚未绑定模型，该角色将无法被调度。</p>
      </div>
    </div>

    <p v-if="!roles.length" class="empty">暂无角色。点击「新增角色」开始配置。</p>
  </section>
</template>

<style scoped>
.binding {
  margin-top: 14px;
  padding-top: 12px;
  border-top: 1px solid var(--line);
}

.binding-head {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 10px;
}

.binding-head .label {
  font-size: 12px;
  color: var(--text-dim);
}

.picker {
  padding: 5px 9px;
  border-radius: var(--radius-sm);
  border: 1px solid var(--line-strong);
  background: var(--bg-input);
  color: var(--text);
  font-size: 12.5px;
}

.picker:focus {
  outline: none;
  border-color: var(--accent-cyan);
}

.chips {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.chip {
  display: inline-flex;
  align-items: center;
  gap: 7px;
  padding: 4px 9px;
  border-radius: 999px;
  border: 1px solid var(--line-accent);
  background: var(--accent-cyan-dim);
  color: var(--accent-cyan);
  font-size: 12px;
  cursor: grab;
  transition: opacity var(--dur-fast) var(--ease), transform var(--dur-fast) var(--ease);
}

.chip.dragging {
  opacity: 0.5;
  transform: scale(0.97);
}

.chip .ord {
  display: inline-grid;
  place-items: center;
  width: 16px;
  height: 16px;
  border-radius: 50%;
  background: rgba(0, 212, 255, 0.24);
  font-size: 10.5px;
}

.chip .x {
  border: 0;
  background: transparent;
  color: inherit;
  font-size: 11px;
  line-height: 1;
  padding: 0 2px;
  opacity: 0.7;
}

.chip .x:hover {
  opacity: 1;
}
</style>
