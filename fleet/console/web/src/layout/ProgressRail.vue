<script setup lang="ts">
/**
 * ProgressRail · 最右侧进度条（缺陷 #2）
 *
 * 数据源：plan.json 三级大纲的**阶段聚合完成度**（Σ阶段 done / Σ阶段 total）。
 * —— 旧版用“10 步准备清单”做数据源，导致进度条在项目尚未执行时就开始跳动，本组件彻底修正。
 * 准备阶段（10 步）不出现在此；执行尚未开始时显示空态文案「项目尚未开始执行」。
 * 视觉规则（沿用用户原始设计）：完成=绿实心、未完成=红空心、当前=青碧色加大圆+圆心百分比。
 */
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import ResizablePanel from '@/components/ResizablePanel.vue'
import ProgressRing from '@/components/ProgressRing.vue'
import Collapsible from '@/components/Collapsible.vue'
import StatusBadge from '@/components/StatusBadge.vue'
import { usePlanStore } from '@/stores/plan'
import { useProjectsStore } from '@/stores/projects'
import { useAuthStore } from '@/stores/auth'
import { formatTime } from '@/utils/labels'

const props = defineProps<{ collapsed: boolean }>()
const emit = defineEmits<{ (e: 'update:collapsed', value: boolean): void }>()

const plan = usePlanStore()
const projects = useProjectsStore()
const auth = useAuthStore()
const openedStages = ref<Record<string, boolean>>({})

/* 需求1：标题带上当前项目名（会话只有 P-xxx，按 id→name 映射还原） */
const projectName = computed(() => projects.nameOf(auth.project) || auth.project || '')
onMounted(() => {
  void projects.load()
})

/* 需求3：权重树（阶段名 → weight_pct/contrib_pct），等权模式下隐藏权重角标 */
const weightByName = computed(() => {
  const map = new Map<string, { weight_pct: number; contrib_pct: number }>()
  for (const node of plan.percentTree) map.set(node.name, node)
  return map
})
function weightText(stageName: string): string {
  if (plan.progressMode !== 'weighted') return ''
  const node = weightByName.value.get(stageName)
  return node ? `${node.weight_pct}%` : ''
}

function ringStatus(status: string): 'done' | 'todo' | 'current' {
  if (status === 'done') return 'done'
  if (status === 'current') return 'current'
  return 'todo'
}

function toggleStage(name: string) {
  openedStages.value = { ...openedStages.value, [name]: !isOpen(name) }
}

function isOpen(name: string): boolean {
  return openedStages.value[name] ?? false
}

const emptyText = computed(() => '项目尚未开始执行')

/* 已执行时间：从 run_started_at 起计时；已收口（done===total）时冻结在完成时刻（大纲 L1-C 3.4 / 4.1） */
const nowTick = ref(Date.now())
const tickTimer = window.setInterval(() => { nowTick.value = Date.now() }, 1000)
onBeforeUnmount(() => window.clearInterval(tickTimer))

const runStartedMs = computed(() => {
  const raw = plan.runStartedAt
  if (!raw) return null
  const ms = Date.parse(raw)
  return Number.isFinite(ms) ? ms : null
})

/** 是否冻结计时：全部完成 OR 无任务在执行中（BLOCKED/ESCALATED 等终态不再跳动，需求8）。
 * P-008 实测：3/5 DONE + 2 BLOCKED 时 done≠total 但无活跃执行态，计时器应冻结。 */
const _ACTIVE_STATES = new Set(['DOING', 'ASSIGNED', 'REVIEWING', 'SUBMITTED'])
const finished = computed(() => {
  if (plan.total > 0 && plan.done === plan.total) return true
  // 有任务但无活跃执行态 → 项目实际已停止（BLOCKED/ESCALATED/DRAFT 不再跳动）
  return plan.total > 0 && !plan.tasks.some((t) => _ACTIVE_STATES.has(String(t.state)))
})

/** 有效任务 updated_at 的最大值（有则用真实完成时间，4.1.2） */
const maxUpdatedMs = computed(() => {
  const times = plan.tasks
    .map((task) => Date.parse(String(task.updated_at ?? '')))
    .filter((ms) => Number.isFinite(ms))
  return times.length ? Math.max(...times) : null
})

/**
 * 无有效 updated_at 时冻结的观察时刻（4.1.2/4.1.3）。
 * 收口瞬间捕获一次 Date.now()，之后不随 nowTick 被动跳动；
 * 退出收口或运行起点变化时重置，下轮重新捕获。
 */
const frozenFallback = ref<number | null>(null)

function captureFallbackIfNeeded(): void {
  if (!finished.value) {
    frozenFallback.value = null
    return
  }
  // 有有效时间时由 maxUpdatedMs 直接提供，无需冻结回退
  frozenFallback.value = maxUpdatedMs.value !== null ? null : Date.now()
}

watch(finished, (isFinished, wasFinished) => {
  if (!isFinished) {
    frozenFallback.value = null
  } else if (!wasFinished) {
    captureFallbackIfNeeded()
  }
})

// 运行起点变化时重置冻结值（下轮重新捕获，4.1.3）
watch(runStartedMs, () => {
  if (finished.value) captureFallbackIfNeeded()
})
// 项目切换时重置冻结状态（大纲 1.2.1）
watch(() => auth.project, () => {
  frozenFallback.value = null
})


/** 收口时刻：有有效时间取最大 updated_at；无则用冻结的观察时刻 */
const finishedMs = computed(() => {
  if (!finished.value) return null
  if (maxUpdatedMs.value !== null) return maxUpdatedMs.value
  return frozenFallback.value
})

/** 是否使用观察时刻回退（非真实完成时间，4.1.3 标注） */
const usingFallback = computed(() =>
  finished.value && maxUpdatedMs.value === null && frozenFallback.value !== null,
)

const elapsedText = computed(() => {
  const start = runStartedMs.value
  if (!start) return '00小时00分00秒'
  const end = finishedMs.value ?? nowTick.value
  const total = Math.max(0, Math.floor((end - start) / 1000))
  const pad = (n: number) => String(n).padStart(2, '0')
  const h = Math.floor(total / 3600)
  const m = Math.floor((total % 3600) / 60)
  const s = total % 60
  return `${pad(h)}小时${pad(m)}分${pad(s)}秒`
})
</script>

<template>
  <ResizablePanel
    side="right"
    :collapsed="props.collapsed"
    :min="200"
    :max="420"
    :default-width="236"
    :collapsed-width="64"
    storage-key="fleet.rail.width"
    @update:collapsed="emit('update:collapsed', $event)"
  >
    <!-- 缩起态：空心圆列 -->
    <div v-if="collapsed" class="strip">
      <div v-if="!plan.started" class="strip-empty">
        <button class="strip-toggle" type="button" :title="`${emptyText}（点击展开）`" @click="emit('update:collapsed', false)">
          <span class="vertical">{{ emptyText }}</span>
        </button>
      </div>
      <template v-else>
        <button
          v-for="stage in plan.stageViews"
          :key="stage.名称"
          class="strip-item"
          type="button"
          :title="`${stage.名称}（${stage.done}/${stage.total}）`"
          @click="emit('update:collapsed', false)"
        >
          <ProgressRing
            :percent="stage.ratio * 100"
            :status="ringStatus(stage.status)"
            :size="stage.status === 'current' ? 46 : 24"
          />
        </button>
        <div class="strip-total mono">{{ plan.percent }}%</div>
      </template>
    </div>

    <!-- 展开态：阶段 + 任务二级/三级大纲 -->
    <div v-else class="full">
      <header class="head">
        <div class="title">
          <b>项目执行进度 · {{ projectName }}</b>
          <span class="hint">已执行时间</span>
          <span class="elapsed mono">{{ elapsedText }}</span>
          <span v-if="finished" class="tag-done">已收口</span>
          <span v-if="usingFallback" class="hint fallback-note" title="任务无有效 updated_at，按首次观察到收口的时刻冻结，非真实完成时间">
            完成时间缺失，按观察时刻计
          </span>
        </div>
        <ProgressRing
          :percent="plan.percent"
          :status="plan.started ? (plan.percent >= 100 ? 'done' : 'current') : 'todo'"
          :size="62"
          show-text
        />
      </header>

      <div class="summary">
        <span class="mono">{{ plan.done }} / {{ plan.total }}</span>
        <span class="hint">任务已完成</span>
        <span v-if="plan.progressMode === 'weighted'" class="tag" title="任务配置了显式权重，进度按权重加权（叶子和=100%）">按权重</span>
      </div>

      <!-- 需求2：一眼区分「没指定计划」与「计划没刷新出来」 -->
      <div v-if="!plan.started" class="empty-box" data-testid="rail-empty">
        <p class="empty-title">{{ emptyText }}</p>
        <p class="hint" data-testid="rail-plan-state">{{ plan.planStateText || '准备阶段的 10 步清单在「总览」页展示；进度条只反映项目执行进度。' }}</p>
      </div>

      <div v-else class="stages">
        <Collapsible
          v-for="stage in plan.stageViews"
          :key="stage.名称"
          headless
          :open="isOpen(stage.名称)"
          @update:open="toggleStage(stage.名称)"
        >
          <template #default>
            <div class="stage-open">
              <ul class="task-list">
                <li v-for="task in stage.tasks" :key="task.id" class="task">
                  <span class="tid mono">{{ task.id }}</span>
                  <span class="ttitle">{{ task.subtask || task.title }}</span>
                  <StatusBadge :state="String(task.state)" />
                </li>
                <li v-if="!stage.tasks.length" class="task muted">该阶段暂无可识别任务</li>
              </ul>
            </div>
          </template>
          <template #header>
            <div class="stage-head">
              <ProgressRing
                :percent="stage.ratio * 100"
                :status="ringStatus(stage.status)"
                :size="stage.status === 'current' ? 30 : 20"
                :show-text="false"
              />
              <span class="sname">{{ stage.名称 }}</span>
              <span class="scount mono">{{ stage.done }}/{{ stage.total }}</span>
              <span v-if="weightText(stage.名称)" class="wtag mono" title="该阶段的项目权重（叶子权重和=100%）">{{ weightText(stage.名称) }}</span>
            </div>
          </template>
        </Collapsible>
      </div>

      <footer class="foot">
        <span class="hint">最近更新 {{ formatTime(plan.updatedAt) }}</span>
      </footer>
    </div>
  </ResizablePanel>
</template>

<style scoped>
.strip {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 14px;
  padding: 16px 0;
}

.strip-item {
  border: 0;
  background: transparent;
  padding: 2px;
  line-height: 0;
}

.strip-total {
  margin-top: 4px;
  font-size: 12px;
  color: var(--accent-cyan);
}

.strip-empty {
  padding: 20px 0;
  display: flex;
  justify-content: center;
}

.vertical {
  writing-mode: vertical-rl;
  text-orientation: upright;
  letter-spacing: 4px;
  font-size: 12px;
  color: var(--text-mute);
}

.full {
  display: flex;
  flex-direction: column;
  gap: 12px;
  padding: 14px 12px;
  min-height: 0;
}

.head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding-bottom: 10px;
  border-bottom: 1px solid var(--line);
}

.strip-toggle {
  border: 0;
  background: transparent;
  padding: 20px 6px;
  cursor: pointer;
}

.strip-toggle:hover .vertical {
  color: var(--accent-cyan);
}

.title {
  display: flex;
  flex-direction: column;
  gap: 2px;
  min-width: 0;
}

.title b {
  font-size: 13px;
}

.elapsed {
  font-size: 13.5px;
  color: var(--accent-cyan);
  letter-spacing: 0.5px;
}

.tag-done {
  display: inline-block;
  padding: 1px 8px;
  border-radius: 999px;
  border: 1px solid rgba(34, 197, 94, 0.32);
  background: var(--ok-dim);
  color: var(--ok);
  font-size: 11px;
  white-space: nowrap;
}

.fallback-note {
  font-size: 10.5px;
  color: var(--warn);
}

.summary {
  display: flex;
  align-items: baseline;
  gap: 8px;
}

.summary .mono {
  font-size: 17px;
  color: var(--text);
}

.empty-box {
  padding: 18px 12px;
  border: 1px dashed var(--line-strong);
  border-radius: var(--radius);
  text-align: center;
}

.empty-title {
  margin: 0 0 6px;
  font-size: 13px;
  color: var(--text-dim);
}

.stages {
  display: flex;
  flex-direction: column;
  gap: 6px;
  overflow: auto;
  min-height: 0;
}

.stage-head {
  display: flex;
  align-items: center;
  gap: 8px;
  min-width: 0;
  width: 100%;
}

.sname {
  font-size: 12.5px;
  color: var(--text);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.scount {
  margin-left: auto;
  font-size: 11px;
  color: var(--text-mute);
}

.summary .tag {
  margin-left: 8px;
  padding: 0 6px;
  border-radius: 999px;
  border: 1px solid var(--line);
  color: var(--accent-cyan);
  font-size: 10px;
}

.wtag {
  margin-left: 6px;
  padding: 0 6px;
  border-radius: 999px;
  border: 1px solid var(--line);
  background: var(--mute-dim);
  color: var(--accent-cyan);
  font-size: 10px;
  line-height: 16px;
  white-space: nowrap;
}

.stage-open {
  padding: 4px 4px 8px 14px;
}

.task-list {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 5px;
}

.task {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 12px;
  color: var(--text-dim);
}

.tid {
  color: var(--text-mute);
  font-size: 11px;
}

.ttitle {
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.foot {
  margin-top: auto;
  padding-top: 10px;
  border-top: 1px solid var(--line);
  display: flex;
  flex-direction: column;
  gap: 2px;
}
</style>
