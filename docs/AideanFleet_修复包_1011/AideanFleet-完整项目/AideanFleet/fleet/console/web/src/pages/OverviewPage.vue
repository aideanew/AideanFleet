<script setup lang="ts">
/**
 * OverviewPage · 总览（工作包 §9.3-3，缺陷 #3 的修复页）
 *
 * 缺陷 #3「总览不滑动」的修复：
 *  - 按阶段分组渲染（不再是长列表平铺）；
 *  - 当前阶段居中、全宽展开；
 *  - 已完成阶段自动上移、折叠为标题行（Collapsible 可展开过程）；
 *  - 阶段切换用 CSS transition（max-height + opacity + translateY），并 scrollIntoView({behavior:'smooth', block:'center'})；
 *  - 执行前的 10 步准备清单保留展示（数据源与进度条解耦）。
 * 另：调度模式切换（自动执行 / 每步确认）与人工确认栏常驻本页。
 */
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import Collapsible from '@/components/Collapsible.vue'
import ProgressRing from '@/components/ProgressRing.vue'
import StatusBadge from '@/components/StatusBadge.vue'
import TaskDetailModal from '@/components/TaskDetailModal.vue'
import RoleProfileDrawer from '@/components/RoleProfileDrawer.vue'
import { useAuthStore } from '@/stores/auth'
import { useExecutionStore } from '@/stores/execution'
import { usePlanStore } from '@/stores/plan'
import { useTaskStore } from '@/stores/task'
import { useWebSocket } from '@/composables/useWebSocket'
import { toast } from '@/composables/useToast'
import { actionLabel, formatTime } from '@/utils/labels'
import { api } from '@/api/client'
import type { SchedulerMode } from '@/api/types'

const auth = useAuthStore()
const plan = usePlanStore()
const execution = useExecutionStore()
const task = useTaskStore()
const ws = useWebSocket()

const currentStageEl = ref<HTMLElement | null>(null)
const opened = ref<Record<string, boolean>>({})
const refreshing = ref(false)
const detailTaskId = ref<string | null>(null)
/** 角色下钻（需求6）：点击角色贡献行打开角色档案 */
const roleDetail = ref<string | null>(null)

/** 角色贡献（大纲 L1-C 3.3）：role → 任务/耗时/token */
interface RoleSummary {
  role: string
  tasks_total: number
  tasks_done: number
  duration_ms: number
  total_tokens: number
  call_count: number
}
const roleSummary = ref<RoleSummary[]>([])

async function loadRolesSummary(): Promise<void> {
  if (!auth.project) return
  try {
    const result = await api.rolesSummary(auth.project)
    roleSummary.value = result.roles ?? []
  } catch {
    roleSummary.value = []
  }
}

function durationText(ms: number): string {
  if (!ms) return '—'
  const total = Math.round(ms / 1000)
  const m = Math.floor(total / 60)
  const s = total % 60
  return m ? `${m}分${s}秒` : `${s}秒`
}

function tokenText(n: number): string {
  return new Intl.NumberFormat('en-US').format(Math.round(n || 0))
}

const emptyText = '项目尚未开始执行'

function ringStatus(status: string): 'done' | 'todo' | 'current' {
  if (status === 'done') return 'done'
  if (status === 'current') return 'current'
  return 'todo'
}

function isOpen(name: string): boolean {
  return opened.value[name] ?? false
}

function toggle(name: string): void {
  opened.value = { ...opened.value, [name]: !isOpen(name) }
}

function lastSummary(taskId: string): string {
  const row = task.lastEventOf(taskId)
  if (!row) return '暂无过程事件'
  return `${actionLabel(row.action)} · ${row.summary}`
}

async function refresh(): Promise<void> {
  refreshing.value = true
  await plan.load(auth.project || undefined)
  void loadRolesSummary()
  refreshing.value = false
  toast.ok('计划已刷新', `已完成 ${plan.done}/${plan.total}（${plan.percent}%）`)
}

// 任务状态拆解（大纲 L1-C 3.1）：3/5 一眼看出差在哪
const statusBreakdown = computed(() => {
  const counts: Record<string, number> = {}
  for (const t of plan.tasks) {
    const key = String(t.state)
    counts[key] = (counts[key] ?? 0) + 1
  }
  const order = ['DONE', 'DOING', 'SUBMITTED', 'REVIEWING', 'ASSIGNED', 'REWORK', 'BLOCKED', 'ESCALATED', 'PARTIAL', 'DRAFT']
  return order.filter((key) => counts[key]).map((key) => ({ state: key, count: counts[key] }))
})

async function switchMode(next: SchedulerMode): Promise<void> {
  if (execution.mode === next) return
  await execution.switchMode(next, ws.send)
  toast.ok('调度模式已切换', next === 'auto' ? '自动执行：Manager 连续推进' : '每步确认：每个步骤等待你确认')
}

async function decide(decision: 'confirm' | 'note'): Promise<void> {
  const result = await execution.confirm(auth.project || undefined, decision)
  if (result.ok) toast.ok(result.message)
  else toast.fail('操作失败', result.message)
}

// 当前阶段变化 → 平滑滚动到视口中央（缺陷 #3 的“滑动”体验）
watch(
  () => plan.currentStage?.名称,
  async () => {
    await nextTick()
    currentStageEl.value?.scrollIntoView({ behavior: 'smooth', block: 'center' })
  },
)

const started = computed(() => plan.started)

/** 角色贡献自动刷新（需求7）：5s 轮询 + 任务完成时立即触发 */
const ROLE_REFRESH_MS = 5000
let roleTimer = 0
function startRoleTimer(): void {
  stopRoleTimer()
  roleTimer = window.setInterval(() => { void loadRolesSummary() }, ROLE_REFRESH_MS)
}
function stopRoleTimer(): void {
  if (roleTimer) { window.clearInterval(roleTimer); roleTimer = 0 }
}
// plan.done 变化（任务完成/审查通过）→ 立即刷新角色贡献
watch(() => plan.done, () => { void loadRolesSummary() })
// 项目切换 → 立即刷新 + 重启定时器
watch(() => auth.project, () => { void loadRolesSummary() })

onMounted(() => {
  void loadRolesSummary()
  startRoleTimer()
})
onBeforeUnmount(() => { stopRoleTimer() })
</script>

<template>
  <section class="page overview">
    <header class="page-head">
      <div class="page-title">
        <h2>总览</h2>
        <span class="page-sub">当前执行步骤与阶段进度 · 数据源：三级大纲 stage 聚合</span>
      </div>
      <div class="row">
        <div class="seg" role="group" aria-label="调度模式">
          <button
            class="seg-item"
            :class="{ on: execution.mode === 'auto' }"
            type="button"
            @click="switchMode('auto')"
          >
            自动执行
          </button>
          <button
            class="seg-item"
            :class="{ on: execution.mode === 'step' }"
            type="button"
            @click="switchMode('step')"
          >
            每步确认
          </button>
        </div>
        <button class="btn" type="button" :disabled="refreshing" @click="refresh">
          {{ refreshing ? '刷新中…' : '刷新计划' }}
        </button>
      </div>
    </header>

    <p v-if="plan.error" class="err-text">{{ plan.error }}</p>

    <!-- 概览指标 -->
    <div class="metrics">
      <div class="metric">
        <span class="k">当前阶段</span>
        <b class="v">{{ plan.currentStage?.名称 ?? (plan.percent >= 100 && started ? '全部阶段已完成' : '—') }}</b>
      </div>
      <div class="metric">
        <span class="k">任务完成</span>
        <b class="v mono">{{ plan.done }} / {{ plan.total }}</b>
        <!-- 状态拆解（大纲 L1-C 3.1）：3/5 差在哪一眼看出 -->
        <span v-if="statusBreakdown.length" class="breakdown">
          <StatusBadge v-for="item in statusBreakdown" :key="item.state" :state="item.state" :label="`${item.state} ${item.count}`" />
        </span>
      </div>
      <div class="metric">
        <span class="k">整体进度</span>
        <b class="v mono">{{ started ? `${plan.percent}%` : '—' }}</b>
      </div>
      <div class="metric">
        <span class="k">调度模式</span>
        <b class="v">{{ execution.modeLabel }}</b>
      </div>
    </div>

    <!-- 角色贡献（大纲 L1-C 3.3）：某角色做了什么、用了多少时间与 token -->
    <div v-if="started && roleSummary.length" class="card" data-testid="roles-summary">
      <div class="card-title">
        <span>角色贡献</span>
        <span class="hint">点击角色行看该角色的工作档案（做过什么 · 耗时/token · 未来分配）· 耗时 = 任务执行时长合计 · Token = 模型调用（含审查）按角色归属</span>
      </div>
      <table class="roles-table">
        <thead>
          <tr><th>角色</th><th>任务</th><th>完成</th><th>耗时</th><th>Token</th><th>调用</th></tr>
        </thead>
        <tbody>
          <tr
            v-for="role in roleSummary"
            :key="role.role"
            class="clickable"
            :title="`点击查看 ${role.role} 的工作档案`"
            @click="roleDetail = role.role"
          >
            <td class="rname">{{ role.role }}</td>
            <td class="mono">{{ role.tasks_total }}</td>
            <td class="mono">{{ role.tasks_done }}</td>
            <td class="mono">{{ durationText(role.duration_ms) }}</td>
            <td class="mono">{{ tokenText(role.total_tokens) }}</td>
            <td class="mono">{{ role.call_count }}</td>
          </tr>
        </tbody>
      </table>
    </div>

    <!-- 每步确认：人工确认栏 -->
    <div v-if="execution.mode === 'step'" class="card confirm-bar">
      <div class="card-title">
        <span>每步确认 · 等待你的决定</span>
        <StatusBadge :label="execution.awaitingConfirm ? '等待确认' : '暂无待确认步骤'" :tone="execution.awaitingConfirm ? 'warn' : 'mute'" />
      </div>
      <textarea
        v-model="execution.note"
        class="control"
        rows="3"
        placeholder="可填写意见/补充要求（点击“提意见”时必填）；留空可直接确认当前步骤"
      />
      <div class="form-actions">
        <button class="btn" type="button" :disabled="execution.confirmBusy" @click="decide('note')">提意见</button>
        <button class="btn btn-primary" type="button" :disabled="execution.confirmBusy" @click="decide('confirm')">
          确认当前步骤
        </button>
      </div>
    </div>

    <!-- 未开始：10 步准备清单（保留展示，与进度条解耦） -->
    <div v-if="!started" class="card">
      <div class="card-title">
        <span>启动前准备 · 10 步</span>
        <span class="hint">项目尚未开始执行，进度条不计入这 10 步</span>
      </div>
      <ol class="prep" data-testid="prep-list">
        <li v-for="step in plan.prepareSteps" :key="step.index" class="prep-item">
          <span class="idx mono">{{ String(step.index).padStart(2, '0') }}</span>
          <span class="text">{{ step.text }}</span>
        </li>
      </ol>
      <p class="hint prep-foot">{{ emptyText }} —— 一旦有任务离开「草稿」态，本页将切换为阶段执行视图。</p>
    </div>

    <!-- 已开始：阶段分组（缺陷 #3 核心） -->
    <template v-else>
      <!-- 已完成阶段：上移 + 折叠为标题行 -->
      <div v-if="plan.doneStages.length" class="group" data-testid="done-group">
        <p class="group-label">已完成阶段（{{ plan.doneStages.length }}）· 已折叠，点击标题行可展开过程</p>
        <Collapsible
          v-for="stage in plan.doneStages"
          :key="`done-${stage.名称}`"
          headless
          :open="isOpen(stage.名称)"
          @update:open="toggle(stage.名称)"
        >
          <template #header>
            <button class="stage-row done" type="button" @click="toggle(stage.名称)">
              <ProgressRing :percent="100" status="done" :size="22" />
              <span class="sname">{{ stage.名称 }}</span>
              <span class="scount mono">{{ stage.done }}/{{ stage.total }}</span>
              <span class="chev">{{ isOpen(stage.名称) ? '▾ 展开' : '▸ 过程' }}</span>
            </button>
          </template>
          <ul class="task-list">
            <li v-for="t in stage.tasks" :key="t.id" class="task clickable" role="button" :title="`查看 ${t.id} 详情`" @click="detailTaskId = t.id">
              <span class="tid mono">{{ t.id }}</span>
              <span class="ttitle">{{ t.subtask || t.title }}</span>
              <span class="assignee tiny mute2">{{ t.assignee }}</span>
              <StatusBadge :state="String(t.state)" />
              <span class="trace hint">{{ lastSummary(t.id) }}</span>
            </li>
          </ul>
        </Collapsible>
      </div>

      <!-- 当前阶段：居中、全宽展开 -->
      <article v-if="plan.currentStage" ref="currentStageEl" class="stage-current" data-testid="stage-current">
        <header class="sc-head">
          <ProgressRing :percent="plan.currentStage.ratio * 100" status="current" :size="56" />
          <div class="sc-meta">
            <span class="sc-tag">当前阶段</span>
            <h3>{{ plan.currentStage.名称 }}</h3>
            <span class="hint">该阶段 {{ plan.currentStage.done }}/{{ plan.currentStage.total }} 个任务已完成</span>
          </div>
        </header>
        <ul class="task-list">
          <li v-for="t in plan.currentStage.tasks" :key="t.id" class="task clickable" role="button" :title="`点击查看 ${t.id} 详情`" @click="detailTaskId = t.id">
            <span class="tid mono">{{ t.id }}</span>
            <span class="ttitle">{{ t.subtask || t.title }}</span>
            <span class="assignee tiny mute2">{{ t.assignee }}</span>
            <span v-if="t.rework_count" class="rework tiny">返工 {{ t.rework_count }}</span>
            <StatusBadge :state="String(t.state)" />
            <span class="trace hint">{{ lastSummary(t.id) }}</span>
          </li>
          <li v-if="!plan.currentStage.tasks.length" class="task muted">该阶段暂无可识别任务</li>
        </ul>
      </article>

      <div v-else class="card done-banner">
        <ProgressRing :percent="100" status="done" :size="40" />
        <span>全部阶段已完成（{{ plan.done }}/{{ plan.total }}），项目已收口。</span>
      </div>

      <!-- 待执行阶段：标题行，可展开 -->
      <div v-if="plan.todoStages.length" class="group">
        <p class="group-label">待执行阶段（{{ plan.todoStages.length }}）</p>
        <Collapsible
          v-for="stage in plan.todoStages"
          :key="`todo-${stage.名称}`"
          headless
          :open="isOpen(stage.名称)"
          @update:open="toggle(stage.名称)"
        >
          <template #header>
            <button class="stage-row todo" type="button" @click="toggle(stage.名称)">
              <ProgressRing :percent="stage.ratio * 100" status="todo" :size="20" />
              <span class="sname">{{ stage.名称 }}</span>
              <span class="scount mono">{{ stage.done }}/{{ stage.total }}</span>
              <span class="chev">{{ isOpen(stage.名称) ? '▾ 收起' : '▸ 展开' }}</span>
            </button>
          </template>
          <ul class="task-list">
            <li v-for="t in stage.tasks" :key="t.id" class="task clickable" role="button" :title="`点击查看 ${t.id} 详情`" @click="detailTaskId = t.id">
              <span class="tid mono">{{ t.id }}</span>
              <span class="ttitle">{{ t.subtask || t.title }}</span>
              <span class="assignee tiny mute2">{{ t.assignee }}</span>
              <StatusBadge :state="String(t.state)" />
            </li>
            <li v-if="!stage.tasks.length" class="task muted">该阶段暂无可识别任务</li>
          </ul>
        </Collapsible>
      </div>
    </template>

    <!-- 过程记录：机器门 / 模型降级 / 启动阶段 / 人工确认 -->
    <div class="card">
      <div class="card-title">
        <span>过程记录</span>
        <span class="hint">gate:* / launch:* / 人工确认，结构化存储（不再塞进某一步的 detail）</span>
      </div>
      <ul v-if="execution.processLog.length" class="log">
        <li v-for="row in execution.processLog" :key="row.seq" class="log-row">
          <span class="mono t">{{ formatTime(row.timestamp) }}</span>
          <span class="act">{{ actionLabel(row.action) }}</span>
          <span class="sum">{{ row.summary }}</span>
          <span v-if="row.taskId" class="tid mono">{{ row.taskId }}</span>
        </li>
      </ul>
      <p v-else class="empty">暂无过程记录（机器门、模型降级切换、人工确认会显示在这里）</p>
    </div>
    <TaskDetailModal :task-id="detailTaskId" @close="detailTaskId = null" />
    <RoleProfileDrawer :role="roleDetail" @close="roleDetail = null" />
  </section>
</template>

<style scoped>
.overview {
  padding-bottom: 40px;
}

.seg {
  display: inline-flex;
  padding: 2px;
  border: 1px solid var(--line-strong);
  border-radius: var(--radius-sm);
  background: var(--bg-input);
}

.seg-item {
  padding: 6px 12px;
  border: 0;
  border-radius: 4px;
  background: transparent;
  color: var(--text-dim);
  font-size: 12.5px;
  transition: background var(--dur-fast) var(--ease), color var(--dur-fast) var(--ease);
}

.seg-item.on {
  background: var(--accent-cyan-dim);
  color: var(--accent-cyan);
  font-weight: 600;
}

.metrics {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 12px;
}

.metric {
  display: flex;
  flex-direction: column;
  gap: 4px;
  padding: 12px 14px;
  border: 1px solid var(--line);
  border-radius: var(--radius);
  background: var(--bg-panel);
}

.metric .k {
  font-size: 12px;
  color: var(--text-mute);
}

.metric .v {
  font-size: 15px;
  color: var(--text);
}

.confirm-bar .control {
  width: 100%;
  padding: 9px 11px;
  border-radius: var(--radius-sm);
  border: 1px solid var(--line-strong);
  background: var(--bg-input);
  color: var(--text);
  resize: vertical;
  margin-bottom: 10px;
}

.confirm-bar .control:focus {
  outline: none;
  border-color: var(--accent-cyan);
}

/* 10 步准备清单 */
.prep {
  list-style: none;
  margin: 0;
  padding: 0;
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 8px 16px;
}

.prep-item {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 8px 11px;
  border: 1px dashed var(--line-strong);
  border-radius: var(--radius-sm);
  background: var(--bg-panel-2);
}

.prep-item .idx {
  color: var(--accent-cyan);
  font-size: 12px;
}

.prep-item .text {
  font-size: 13px;
  color: var(--text-dim);
}

.prep-foot {
  margin-top: 12px;
}

/* 阶段分组 */
.group {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.group-label {
  margin: 4px 0 2px;
  font-size: 12px;
  color: var(--text-mute);
}

.stage-row {
  display: flex;
  align-items: center;
  gap: 10px;
  width: 100%;
  padding: 9px 12px;
  border: 1px solid var(--line);
  border-radius: var(--radius-sm);
  background: var(--bg-panel);
  color: var(--text-dim);
  text-align: left;
  transition: border-color var(--dur-fast) var(--ease), background var(--dur-fast) var(--ease),
    opacity var(--dur) var(--ease), transform var(--dur) var(--ease);
}

.stage-row:hover {
  border-color: var(--line-accent);
  background: var(--bg-hover);
}

.stage-row.done {
  opacity: 0.82;
}

.stage-row .sname {
  font-size: 13px;
  color: var(--text);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.stage-row .scount {
  font-size: 11.5px;
  color: var(--text-mute);
}

.stage-row .chev {
  margin-left: auto;
  font-size: 11.5px;
  color: var(--accent-cyan);
}

/* 当前阶段：居中全宽 */
.stage-current {
  border: 1px solid var(--line-accent);
  border-radius: var(--radius);
  background: var(--bg-panel);
  padding: 16px 18px;
  box-shadow: inset 0 0 0 1px rgba(0, 212, 255, 0.06);
  transition: box-shadow var(--dur-slow) var(--ease), border-color var(--dur-slow) var(--ease);
}

.sc-head {
  display: flex;
  align-items: center;
  gap: 16px;
  padding-bottom: 12px;
  margin-bottom: 12px;
  border-bottom: 1px solid var(--line);
}

.sc-meta {
  display: flex;
  flex-direction: column;
  gap: 3px;
  min-width: 0;
}

.sc-tag {
  align-self: flex-start;
  padding: 1px 9px;
  border-radius: 999px;
  border: 1px solid var(--line-accent);
  background: var(--accent-cyan-dim);
  color: var(--accent-cyan);
  font-size: 11px;
}

.sc-meta h3 {
  font-size: 15px;
  color: var(--text);
}

.done-banner {
  display: flex;
  align-items: center;
  gap: 14px;
  font-size: 13px;
  color: var(--text-dim);
}

/* 任务行 */
.task-list {
  list-style: none;
  margin: 0;
  padding: 0 2px;
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.task {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 7px 8px;
  border-radius: var(--radius-sm);
  transition: background var(--dur-fast) var(--ease);
}

.task:hover {
  background: var(--bg-hover);
}

.task .tid {
  flex: 0 0 auto;
  font-size: 11.5px;
  color: var(--text-mute);
}

.task .ttitle {
  font-size: 13px;
  color: var(--text-dim);
  white-space: nowrap;
}

.task .assignee {
  flex: 0 0 auto;
}

.task .rework {
  color: var(--danger);
}

.task .trace {
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  text-align: right;
}

/* 过程记录 */
.log {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.log-row {
  display: flex;
  align-items: center;
  gap: 10px;
  font-size: 12.5px;
  padding: 6px 8px;
  border-radius: var(--radius-sm);
  background: var(--bg-panel-2);
}

.log-row .t {
  color: var(--text-mute);
  font-size: 11.5px;
}

.log-row .act {
  flex: 0 0 auto;
  color: var(--accent-cyan);
}

.log-row .sum {
  flex: 1;
  min-width: 0;
  color: var(--text-dim);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

/* 角色贡献表：行可点击 → 角色档案抽屉（需求6） */
.roles-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 12.5px;
}

.roles-table th {
  text-align: left;
  font-weight: 500;
  font-size: 11.5px;
  color: var(--text-mute);
  padding: 6px 10px;
  border-bottom: 1px solid var(--line);
  white-space: nowrap;
}

.roles-table td {
  padding: 7px 10px;
  border-bottom: 1px solid var(--line);
  color: var(--text-dim);
}

.roles-table .rname {
  color: var(--text);
}

.roles-table tr.clickable {
  cursor: pointer;
}

.roles-table tr.clickable:hover td {
  background: var(--bg-hover);
}

@media (max-width: 1280px) {
  .metrics {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
  .prep {
    grid-template-columns: minmax(0, 1fr);
  }
}
</style>
