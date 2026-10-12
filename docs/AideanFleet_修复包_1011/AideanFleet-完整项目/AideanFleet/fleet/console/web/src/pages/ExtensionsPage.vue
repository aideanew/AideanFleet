<script setup lang="ts">
/**
 * ExtensionsPage · 拓展
 * 技能（skills）与工具（MCP）。按执行体分组，支持增删条目；保存写入 data/extensions.json。
 */
import { computed, onMounted, ref, watch } from 'vue'
import { useConfigStore } from '@/stores/config'
import { toast } from '@/composables/useToast'
import type { ExtensionRecord, ExtensionsMap } from '@/api/types'

const config = useConfigStore()
const saving = ref(false)
const draft = ref<ExtensionsMap>({})
const skillInput = ref<Record<string, string>>({})
const mcpInput = ref<Record<string, string>>({})

const groups = computed(() => Object.keys(draft.value))

function clone(source: ExtensionsMap): ExtensionsMap {
  const out: ExtensionsMap = {}
  for (const [name, record] of Object.entries(source)) {
    out[name] = { skills: [...(record.skills ?? [])], mcp: [...(record.mcp ?? [])] }
  }
  return out
}

/** 把已配置执行体并入草稿，保证每个执行体都能维护拓展 */
function syncDraft(): void {
  const next = clone(config.extensions)
  for (const executor of config.executors) {
    if (!next[executor.name]) next[executor.name] = { skills: [], mcp: [] }
  }
  draft.value = next
}

function addEntry(kind: 'skills' | 'mcp', group: string): void {
  const source = kind === 'skills' ? skillInput : mcpInput
  const value = String(source.value[group] ?? '').trim()
  if (!value) {
    toast.warn('请输入内容')
    return
  }
  const record = draft.value[group] ?? { skills: [], mcp: [] }
  if (record[kind].includes(value)) {
    toast.warn('已存在', `${value} 已在列表中`)
    return
  }
  draft.value = {
    ...draft.value,
    [group]: { ...record, [kind]: [...record[kind], value] } as ExtensionRecord,
  }
  source.value = { ...source.value, [group]: '' }
}

function removeEntry(kind: 'skills' | 'mcp', group: string, value: string): void {
  const record = draft.value[group]
  draft.value = {
    ...draft.value,
    [group]: { ...record, [kind]: record[kind].filter((item) => item !== value) } as ExtensionRecord,
  }
}

async function save(): Promise<void> {
  saving.value = true
  try {
    const message = await config.saveExtensions(clone(draft.value))
    toast.ok('拓展已保存', message)
  } catch (error) {
    toast.fail('保存失败', error instanceof Error ? error.message : '')
  } finally {
    saving.value = false
  }
}

onMounted(async () => {
  if (!config.executors.length) await config.loadAll()
  await config.loadExtensions()
  syncDraft()
})

watch(() => [config.extensions, config.executors], syncDraft)
</script>

<template>
  <section class="page">
    <header class="page-head">
      <div class="page-title">
        <h2>拓展</h2>
        <span class="page-sub">技能与工具（MCP）· 按执行体分组维护</span>
      </div>
      <div class="row">
        <span class="hint">配置源：data/extensions.json</span>
        <button class="btn btn-primary" type="button" :disabled="saving" @click="save">
          {{ saving ? '保存中…' : '保存拓展' }}
        </button>
      </div>
    </header>

    <p v-if="config.lastError" class="err-text">{{ config.lastError }}</p>

    <div v-for="group in groups" :key="group" class="item-card">
      <div class="item-head">
        <b>{{ group }}</b>
        <span class="tag">{{ draft[group].skills.length }} 技能 / {{ draft[group].mcp.length }} MCP</span>
      </div>

      <div class="section">
        <div class="section-head">
          <span class="label">技能（skills）</span>
          <div class="adder">
            <input
              v-model="skillInput[group]"
              class="mini-input mono"
              placeholder="技能名，如 backend-test"
              @keydown.enter="addEntry('skills', group)"
            />
            <button class="btn" type="button" @click="addEntry('skills', group)">添加</button>
          </div>
        </div>
        <div class="chips">
          <span v-for="skill in draft[group].skills" :key="skill" class="tag removable">
            {{ skill }}
            <button class="x" type="button" title="移除" @click="removeEntry('skills', group, skill)">✕</button>
          </span>
          <span v-if="!draft[group].skills.length" class="hint">暂无技能</span>
        </div>
      </div>

      <div class="section">
        <div class="section-head">
          <span class="label">工具（MCP）</span>
          <div class="adder">
            <input
              v-model="mcpInput[group]"
              class="mini-input mono"
              placeholder="MCP 名，如 filesystem"
              @keydown.enter="addEntry('mcp', group)"
            />
            <button class="btn" type="button" @click="addEntry('mcp', group)">添加</button>
          </div>
        </div>
        <div class="chips">
          <span v-for="mcp in draft[group].mcp" :key="mcp" class="tag removable">
            {{ mcp }}
            <button class="x" type="button" title="移除" @click="removeEntry('mcp', group, mcp)">✕</button>
          </span>
          <span v-if="!draft[group].mcp.length" class="hint">暂无 MCP 工具</span>
        </div>
      </div>
    </div>

    <p v-if="!groups.length" class="empty">暂无可维护的执行体拓展。请先在「执行体」页配置执行体。</p>
  </section>
</template>

<style scoped>
.section {
  padding-top: 12px;
  border-top: 1px solid var(--line);
}

.section + .section {
  margin-top: 12px;
}

.section-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 10px;
  flex-wrap: wrap;
}

.section-head .label {
  font-size: 12px;
  color: var(--text-dim);
}

.adder {
  display: flex;
  align-items: center;
  gap: 8px;
}

.mini-input {
  width: 240px;
  padding: 6px 9px;
  border-radius: var(--radius-sm);
  border: 1px solid var(--line-strong);
  background: var(--bg-input);
  color: var(--text);
  font-size: 12.5px;
}

.mini-input:focus {
  outline: none;
  border-color: var(--accent-cyan);
}

.chips {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  align-items: center;
}
</style>
