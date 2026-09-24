<script setup lang="ts">
/**
 * ExecutorsPage · 执行体
 * 上半区（需求4）：运行中执行体实时读数——哪个执行体在跑、PID/进程名/挂哪个任务/跑了多久；
 * 数据源 GET /api/executors/running（进程内登记表），页面停留期间每 2 秒轮询。
 * 下半区：执行体与启动命令配置。每个执行体可编辑 name / command / timeout；
 * 在本页可一眼看到各执行体已挂载的技能与 MCP 数量（详细维护在「拓展」页）。
 */
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import FormInput from '@/components/FormInput.vue'
import { useConfigStore } from '@/stores/config'
import { useAuthStore } from '@/stores/auth'
import { api } from '@/api/client'
import { toast } from '@/composables/useToast'
import type { ExecutorItem, RunningExecutor } from '@/api/types'

const config = useConfigStore()
const auth = useAuthStore()
const saving = ref(false)

const executors = computed(() => config.executors)

/* ---------------- 需求4：运行中执行体（轮询登记表快照） ---------------- */
const running = ref<RunningExecutor[]>([])
const runningError = ref('')
const autoRefresh = ref(true)
const lastPulledAt = ref('')
let pollTimer: number | null = null

async function pullRunning(): Promise<void> {
  try {
    const result = await api.executorsRunning(auth.project || undefined)
    running.value = result.executors ?? []
    runningError.value = ''
    lastPulledAt.value = new Date().toLocaleTimeString('zh-CN', { hour12: false })
  } catch (error) {
    runningError.value = error instanceof Error ? error.message : '运行读数拉取失败'
  }
}

function setTimer(): void {
  if (pollTimer !== null) {
    window.clearInterval(pollTimer)
    pollTimer = null
  }
  if (autoRefresh.value) pollTimer = window.setInterval(() => void pullRunning(), 2000)
}

function elapsedText(row: RunningExecutor): string {
  const total = Math.max(0, Math.floor(row.elapsed_s))
  const h = Math.floor(total / 3600)
  const m = Math.floor((total % 3600) / 60)
  const s = total % 60
  if (h) return `${h}小时${m}分${s}秒`
  if (m) return `${m}分${s}秒`
  return `${s}秒`
}

function extCount(name: string): string {
  const record = config.extensions[name]
  if (!record) return '技能 0 · MCP 0'
  return `技能 ${record.skills.length} · MCP ${record.mcp.length}`
}

function addExecutor(): void {
  config.executors = [...config.executors, { name: '', command: '', timeout: 600 } as ExecutorItem]
}

function removeExecutor(index: number): void {
  const next = [...config.executors]
  next.splice(index, 1)
  config.executors = next
}

async function save(): Promise<void> {
  const invalid = config.executors.find((e) => !e.name.trim() || !e.command.trim())
  if (invalid) {
    toast.warn('校验未通过', '每个执行体都必须填写 name 与 command')
    return
  }
  saving.value = true
  try {
    const message = await config.saveExecutors(config.executors.map((e) => ({ ...e })))
    toast.ok('执行体已保存', message)
  } catch (error) {
    toast.fail('保存失败', error instanceof Error ? error.message : '')
  } finally {
    saving.value = false
  }
}

watch(autoRefresh, setTimer)
watch(() => auth.project, () => void pullRunning())

onMounted(() => {
  if (!config.executors.length) void config.loadAll()
  void config.loadExtensions()
  void pullRunning()
  setTimer()
})

onBeforeUnmount(() => {
  if (pollTimer !== null) window.clearInterval(pollTimer)
})
</script>

<template>
  <section class="page">
    <header class="page-head">
      <div class="page-title">
        <h2>执行体</h2>
        <span class="page-sub">执行体与启动命令 · 命令以 JSON 输出为约定（--output-format json / --json）</span>
      </div>
      <div class="row">
        <button class="btn" type="button" @click="addExecutor">新增执行体</button>
        <button class="btn btn-primary" type="button" :disabled="saving" @click="save">
          {{ saving ? '保存中…' : '保存执行体' }}
        </button>
      </div>
    </header>

    <p v-if="config.lastError" class="err-text">{{ config.lastError }}</p>

    <!-- 需求4：运行中执行体（实时） -->
    <div class="card" data-testid="running-executors">
      <div class="card-title">
        <span>运行中执行体（{{ running.length }}）</span>
        <span class="row">
          <label class="runtime-toggle" title="每 2 秒自动刷新">
            <input v-model="autoRefresh" type="checkbox" />
            自动刷新
          </label>
          <span v-if="lastPulledAt" class="hint">更新于 {{ lastPulledAt }}</span>
          <button class="btn btn-ghost" type="button" @click="pullRunning">刷新</button>
        </span>
      </div>
      <p v-if="runningError" class="err-text">{{ runningError }}</p>
      <div class="table-wrap">
        <table class="grid">
          <thead>
            <tr>
              <th style="width: 110px">执行体</th>
              <th style="width: 140px">进程名</th>
              <th style="width: 90px">PID</th>
              <th style="width: 120px">任务</th>
              <th style="width: 110px">角色</th>
              <th style="width: 110px">已运行</th>
              <th>状态</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="row in running" :key="row.key" data-testid="running-row"><!--
              --><td class="mono">{{ row.adapter || '—' }}</td><!--
              --><td class="mono" :title="row.cmd.join(' ')">{{ row.process_name }}</td><!--
              --><td class="mono">{{ row.pid }}</td><!--
              --><td class="mono">{{ row.task_id || '—' }}</td><!--
              --><td>{{ row.role || '—' }}</td><!--
              --><td class="mono">{{ elapsedText(row) }}</td><!--
              --><td><span class="tag" :class="row.alive ? 'tag-live' : 'tag-dead'">{{ row.alive ? '运行中' : '已退出' }}</span></td><!--
              --></tr>
            <tr v-if="!running.length && !runningError">
              <td colspan="7">
                <p class="empty">当前项目此刻没有正在执行的执行体进程。派工开始后本页会实时列出 PID 与运行时长。</p>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
      <p class="hint">
        · 读数来源：控制台进程内的执行体登记表（spawn 点自动登记/回收），只覆盖经 Fleet 派工的执行体；
        独立进程运行的调度器不在此读数内。进程名可点开悬停查看完整命令行。
      </p>
    </div>

    <div class="table-wrap">
      <table class="grid">
        <thead>
          <tr>
            <th style="width: 150px">名称</th>
            <th>启动命令</th>
            <th style="width: 120px">超时（秒）</th>
            <th style="width: 170px">已挂载拓展</th>
            <th style="width: 64px" />
          </tr>
        </thead>
        <tbody>
          <tr v-for="(executor, index) in executors" :key="index">
            <td><FormInput v-model="executor.name" placeholder="如 codex" /></td>
            <td><FormInput v-model="executor.command" mono placeholder="如 codex exec --json" /></td>
            <td><FormInput v-model="executor.timeout" type="number" /></td>
            <td><span class="tag">{{ extCount(executor.name) }}</span></td>
            <td>
              <button class="btn btn-ghost" type="button" title="移除" @click="removeExecutor(index)">✕</button>
            </td>
          </tr>
          <tr v-if="!executors.length">
            <td colspan="5"><p class="empty">暂无执行体。点击「新增执行体」开始配置。</p></td>
          </tr>
        </tbody>
      </table>
    </div>

    <p class="hint">
      · 执行体是真正拉起模型进程的载体，角色通过 adapter 字段绑定到执行体；超时用于约束单次调用。
      · 技能（skills）与工具（MCP）在各执行体下独立维护，请前往「拓展」页编辑。
    </p>
  </section>
</template>

<style scoped>
.runtime-toggle {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  font-size: 12px;
  color: var(--text-dim);
  cursor: pointer;
}

.tag-live {
  color: var(--ok);
  border-color: rgba(34, 197, 94, 0.35);
  background: var(--ok-dim);
}

.tag-dead {
  color: var(--text-mute);
}
</style>
