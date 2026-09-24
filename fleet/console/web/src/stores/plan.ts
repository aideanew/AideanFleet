/**
 * usePlanStore · 三级大纲与进度
 *
 * 缺陷 #2 的核心：进度条数据源改为 plan.json 三级大纲的**阶段聚合完成度**
 * （逐阶段累计 done/tasks → 总百分比），彻底摆脱旧版“10 步准备清单”做数据源的问题。
 * 执行尚未开始时（全部任务仍是 DRAFT），进度条显示空态文案“项目尚未开始执行”。
 */
import { computed, ref } from 'vue'
import { defineStore } from 'pinia'
import { api } from '@/api/client'
import { useAuthStore } from '@/stores/auth'
import { PREPARE_STEPS } from '@/utils/labels'
import type { PlanSnapshot, PlanStage, PlanTask, ProgressStageNode } from '@/api/types'

export interface StageView {
  名称: string
  任务: PlanStage['任务']
  tasks: PlanTask[]
  total: number
  done: number
  ratio: number
  status: 'done' | 'current' | 'todo'
}

const DONE_STATES = new Set(['DONE', 'PARTIAL'])

export const usePlanStore = defineStore('plan', () => {
  const snapshot = ref<PlanSnapshot | null>(null)
  const loading = ref(false)
  const error = ref('')
  const updatedAt = ref('')
  const currentProjectId = ref('')
  /** 项目执行起点（事件流第一条任务类事件时间；未开始为空） */
  const runStartedAt = ref('')

  const tasks = computed<PlanTask[]>(() => snapshot.value?.tasks ?? [])
  const rawStages = computed<PlanStage[]>(() => snapshot.value?.阶段 ?? [])

  /** 执行是否已开始：任一任务离开 DRAFT 即视为已启动 */
  const started = computed(() => tasks.value.some((task) => task.state !== 'DRAFT'))

  /** 阶段聚合：逐阶段统计 done/total，再汇总为总百分比 */
  const stageViews = computed<StageView[]>(() => {
    const byId = new Map(tasks.value.map((task) => [task.id, task]))
    let currentAssigned = false
    return rawStages.value.map((stage) => {
      const stageTasks = stage.任务
        .map((item) => (item.task_id ? byId.get(item.task_id) : undefined))
        .filter((task): task is PlanTask => Boolean(task))
      const total = stageTasks.length
      const done = stageTasks.filter((task) => DONE_STATES.has(String(task.state))).length
      const ratio = total ? done / total : 0
      let status: StageView['status'] = 'todo'
      if (total > 0 && done === total) {
        status = 'done'
      } else if (!currentAssigned) {
        status = 'current'
        currentAssigned = true
      }
      return { 名称: stage.名称, 任务: stage.任务, tasks: stageTasks, total, done, ratio, status }
    })
  })

  /** 任务计数（旧口径保留给指标卡；进度百分比已改为权重口径） */
  const total = computed(() => stageViews.value.reduce((sum, stage) => sum + stage.total, 0))
  const done = computed(() => stageViews.value.reduce((sum, stage) => sum + stage.done, 0))

  /**
   * 总进度（需求3）：优先用服务端权重树 progress.percent（叶子权重和恒=100，
   * 未配权重时该树退化为等权，数值与旧版 Σdone/Σtotal 完全一致）；
   * 兜底旧响应缺 progress 时回落等权口径。
   */
  const percentTree = computed<ProgressStageNode[]>(() => snapshot.value?.progress?.stages ?? [])
  const progressMode = computed(() => snapshot.value?.progress?.mode ?? 'equal')
  const percent = computed(() => {
    const serverPercent = snapshot.value?.progress?.percent
    if (typeof serverPercent === 'number' && Number.isFinite(serverPercent)) return serverPercent
    return total.value ? Math.round((done.value / total.value) * 1000) / 10 : 0
  })

  /**
   * 计划状态（需求2）：回答“是没指定还是没刷新出来”。
   *   missing     —— plan.json 不存在且无任务：从未生成过计划
   *   empty       —— plan.json 存在但没有任何阶段条目
   *   unplanned   —— 库里已有任务但大纲没归组（虚拟阶段承接）
   *   planned     —— 大纲已生成、全部任务仍为草稿（等待派工/启动）
   *   running     —— 已有任务离开草稿态
   */
  const planState = computed<'none' | 'missing' | 'empty' | 'unplanned' | 'planned' | 'running'>(() => {
    const snap = snapshot.value
    if (!snap) return 'none'
    const stages = snap.阶段 ?? []
    if (!snap.plan_exists && stages.length === 0 && snap.tasks.length === 0) return 'missing'
    if (stages.length === 0 && snap.tasks.length === 0) return 'empty'
    if (stages.length === 0) return 'unplanned'
    return started.value ? 'running' : 'planned'
  })

  const planStateText = computed(() => {
    const stageCount = snapshot.value?.阶段?.length ?? 0
    switch (planState.value) {
      case 'missing':
        return '未生成任务计划：plan.json 不存在。请先在「对话」页让 Manager 生成大纲，或用启动器创建计划。'
      case 'empty':
        return '计划文件存在但为空：尚无任何阶段条目，等待 Manager 写入三级大纲。'
      case 'unplanned':
        return `计划大纲未归组：库里有 ${snapshot.value?.tasks.length ?? 0} 个任务，进度按「未归入计划」等权计入。`
      case 'planned':
        return `计划已生成：${stageCount} 个阶段 · ${snapshot.value?.tasks.length ?? 0} 个任务，等待开始执行。`
      case 'running':
        return `计划已生成：${stageCount} 个阶段 · ${snapshot.value?.tasks.length ?? 0} 个任务，正在执行。`
      default:
        return ''
    }
  })

  const currentStage = computed(() => stageViews.value.find((stage) => stage.status === 'current') ?? null)
  const doneStages = computed(() => stageViews.value.filter((stage) => stage.status === 'done'))
  const todoStages = computed(() => stageViews.value.filter((stage) => stage.status === 'todo'))

  /** 执行开始前的 10 步准备清单（原文照抄，不得改写） */
  const prepareSteps = computed(() => PREPARE_STEPS.map((text, index) => ({ index: index + 1, text })))

  /**
   * 写入快照。projectId 显式传入调用方期望的项目（缺陷①修复）：
   * 不再依赖内部 currentProjectId 兜底判断——那会让过期结果借助旧内部状态通过校验。
   */
  function apply(next: PlanSnapshot | null, projectId?: string): void {
    if (!next || next.ok === false) return
    const auth = useAuthStore()
    const expected = String(projectId ?? auth.project ?? '')
    const incomingProject = String(next.project ?? '')
    if (expected && incomingProject && incomingProject !== expected) {
      return
    }
    snapshot.value = next
    currentProjectId.value = incomingProject || expected
    updatedAt.value = next.updated_at ?? ''
    if (next.run_started_at) runStartedAt.value = next.run_started_at
  }

  async function load(project?: string): Promise<void> {
    const auth = useAuthStore()
    const targetProject = project || auth.project || ''
    loading.value = true
    error.value = ''
    // 清空旧快照避免闪现
    snapshot.value = null
    currentProjectId.value = targetProject
    try {
      const result = await api.getPlan(targetProject)
      // 单条件校验：会话项目已切走即丢弃响应（缺陷①：旧版 && 逻辑在
      // 「切走 + 响应仍是目标项目」时恰好不拦截，导致串台）
      if (auth.project !== targetProject) {
        return
      }
      apply(result, targetProject)
    } catch (caught) {
      error.value = caught instanceof Error ? caught.message : '计划加载失败'
    } finally {
      loading.value = false
    }
  }

  function stateOf(taskId: string): string {
    return String(tasks.value.find((task) => task.id === taskId)?.state ?? '')
  }

  return {
    snapshot,
    loading,
    error,
    updatedAt,
    runStartedAt,
    tasks,
    stageViews,
    started,
    total,
    done,
    percent,
    percentTree,
    progressMode,
    planState,
    planStateText,
    currentStage,
    doneStages,
    todoStages,
    prepareSteps,
    apply,
    load,
    stateOf,
  }
})
