<script setup lang="ts">
/**
 * ModelsPage · 模型
 * 模型池与优先级。掩码规则（工作包 §10-3）：api_key 全程零明文——
 * 页面只回显后端给的 ${VAR} 占位；若用户试图写入明文，立即拒绝并提示，绝不落 DOM / 网络。
 */
import { computed, onMounted, ref } from 'vue'
import FormInput from '@/components/FormInput.vue'
import { useConfigStore } from '@/stores/config'
import { toast } from '@/composables/useToast'
import { isMaskedPlaceholder } from '@/utils/labels'
import type { ModelItem } from '@/api/types'

const config = useConfigStore()
const saving = ref(false)
const keyEditing = ref<Record<number, boolean>>({})
const keyDraft = ref<Record<number, string>>({})

const models = computed(() => config.models)
const sorted = computed(() => [...models.value].sort((a, b) => a.level - b.level))

function blank(): ModelItem {
  return { name: '', level: models.value.length + 1, base_url: '', model_id: '', api_key: '', http_proxy: '', https_proxy: '' }
}

function addModel(): void {
  config.models = [...config.models, blank()]
}

function removeModel(index: number): void {
  const next = [...config.models]
  next.splice(index, 1)
  config.models = next
  toast.info('已移除', '记得点击“保存模型池”使改动生效')
}

function move(index: number, dir: -1 | 1): void {
  const next = [...config.models]
  const target = index + dir
  if (target < 0 || target >= next.length) return
  const a = next[index]
  const b = next[target]
  const tmp = a.level
  a.level = b.level
  b.level = tmp
  next[index] = b
  next[target] = a
  config.models = next
}

function beginKey(index: number): void {
  keyEditing.value = { ...keyEditing.value, [index]: true }
  keyDraft.value = { ...keyDraft.value, [index]: config.models[index]?.api_key ?? '' }
}

function commitKey(index: number): void {
  const draft = String(keyDraft.value[index] ?? '').trim()
  // 只接受 ${VAR} 占位或留空；明文一律拒绝（零明文红线）
  if (draft && !draft.startsWith('${')) {
    toast.fail('拒绝写入明文密钥', '该字段只接受 ${环境变量名} 占位符，真值请放 secrets/.env 或系统环境变量')
    return
  }
  const next = [...config.models]
  next[index] = { ...next[index], api_key: draft }
  config.models = next
  keyEditing.value = { ...keyEditing.value, [index]: false }
}

function cancelKey(index: number): void {
  keyEditing.value = { ...keyEditing.value, [index]: false }
}

async function save(): Promise<void> {
  const invalid = config.models.find((m) => !m.name.trim() || !m.model_id.trim())
  if (invalid) {
    toast.warn('校验未通过', '每个模型都必须填写 name 与 model_id')
    return
  }
  saving.value = true
  try {
    const message = await config.saveModels(config.models.map((m) => ({ ...m })))
    toast.ok('模型池已保存', message)
  } catch (error) {
    toast.fail('保存失败', error instanceof Error ? error.message : '')
  } finally {
    saving.value = false
  }
}

onMounted(() => {
  if (!config.models.length) void config.loadAll()
})
</script>

<template>
  <section class="page">
    <header class="page-head">
      <div class="page-title">
        <h2>模型</h2>
        <span class="page-sub">模型池与优先级 · 数字越小优先级越高，额度耗尽时按序降级</span>
      </div>
      <div class="row">
        <span class="hint">配置源：{{ config.envSource || '—' }}</span>
        <button class="btn" type="button" @click="addModel">新增模型</button>
        <button class="btn btn-primary" type="button" :disabled="saving" @click="save">
          {{ saving ? '保存中…' : '保存模型池' }}
        </button>
      </div>
    </header>

    <p v-if="config.lastError" class="err-text">{{ config.lastError }}</p>

    <div class="table-wrap">
      <table class="grid">
        <thead>
          <tr>
            <th style="width: 64px">优先级</th>
            <th style="width: 130px">名称</th>
            <th style="width: 210px">base_url</th>
            <th style="width: 170px">model_id</th>
            <th style="width: 200px">api_key（掩码）</th>
            <th style="width: 180px">http_proxy</th>
            <th style="width: 180px">https_proxy</th>
            <th style="width: 120px">排序</th>
            <th style="width: 64px" />
          </tr>
        </thead>
        <tbody>
          <tr v-for="model in sorted" :key="model.name + model.model_id">
            <td>
              <FormInput v-model="model.level" type="number" />
            </td>
            <td><FormInput v-model="model.name" placeholder="如 agnes" /></td>
            <td><FormInput v-model="model.base_url" mono placeholder="https://…/v1" /></td>
            <td><FormInput v-model="model.model_id" mono placeholder="模型 id" /></td>
            <td>
              <template v-if="keyEditing[config.models.indexOf(model)]">
                <input
                  class="key-input mono"
                  :value="keyDraft[config.models.indexOf(model)]"
                  placeholder="${ENV_VAR}"
                  @input="(e) => (keyDraft[config.models.indexOf(model)] = (e.target as HTMLInputElement).value)"
                  @keydown.enter="commitKey(config.models.indexOf(model))"
                />
                <div class="key-actions">
                  <button class="mini" type="button" @click="commitKey(config.models.indexOf(model))">确认</button>
                  <button class="mini" type="button" @click="cancelKey(config.models.indexOf(model))">取消</button>
                </div>
              </template>
              <template v-else>
                <span class="cell-mask">{{ model.api_key || '（未设置）' }}</span>
                <button class="mini" type="button" @click="beginKey(config.models.indexOf(model))">改占位符</button>
              </template>
            </td>
            <td><FormInput v-model="model.http_proxy" mono placeholder="可留空" /></td>
            <td><FormInput v-model="model.https_proxy" mono placeholder="可留空" /></td>
            <td>
              <div class="row">
                <button class="mini" type="button" title="上移" @click="move(config.models.indexOf(model), -1)">↑</button>
                <button class="mini" type="button" title="下移" @click="move(config.models.indexOf(model), 1)">↓</button>
              </div>
            </td>
            <td>
              <button class="mini danger" type="button" title="移除" @click="removeModel(config.models.indexOf(model))">✕</button>
            </td>
          </tr>
          <tr v-if="!config.models.length">
            <td colspan="9"><p class="empty">暂无模型。点击右上角「新增模型」开始配置模型池。</p></td>
          </tr>
        </tbody>
      </table>
    </div>

    <p class="hint">
      · 密钥字段只接受 <span class="mono">${VAR}</span> 占位，明文在此被拒绝；页面源码、网络响应、localStorage 全程无明文。
      · 硬失败（401/402/403/额度耗尽/模型不存在）不重试，直接切换下一候选；瞬时失败按 request 段重试。
    </p>
  </section>
</template>

<style scoped>
.key-input {
  width: 100%;
  padding: 6px 8px;
  border-radius: var(--radius-sm);
  border: 1px solid var(--line-strong);
  background: var(--bg-input);
  color: var(--text);
  font-size: 12px;
}

.key-input:focus {
  outline: none;
  border-color: var(--accent-cyan);
}

.key-actions {
  display: flex;
  gap: 6px;
  margin-top: 4px;
}

.mini {
  padding: 3px 8px;
  border-radius: var(--radius-sm);
  border: 1px solid var(--line-strong);
  background: var(--bg-panel-2);
  color: var(--text-dim);
  font-size: 12px;
  transition: border-color var(--dur-fast) var(--ease), color var(--dur-fast) var(--ease);
}

.mini:hover {
  border-color: var(--line-accent);
  color: var(--accent-cyan);
}

.mini.danger:hover {
  border-color: var(--danger);
  color: var(--danger);
}
</style>
