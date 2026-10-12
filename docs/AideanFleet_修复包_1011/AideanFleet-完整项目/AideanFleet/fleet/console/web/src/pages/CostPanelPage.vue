<script setup lang="ts">
/**
 * CostPanelPage · 成本面板（UI-03R §9.5）
 *
 * 口径（docs/契约/控制台API.md §13 + GOV-01 实测）：
 *   用量只来自 events.jsonl 里的 `model:call` 事件，经 UsageAggregator 聚合；
 *   预算由 BudgetManager.get_status() 按 task / project / daily 三级返回。
 *
 * 数据源真相（2026-09-15 实测，带有效会话令牌）：
 *   GET /api/usage/total、/api/usage/by_date、/api/budget → 全部 **404 not_found**。
 *   → 走契约形状兜底并在页头显式标注「后端未就绪」，绝不伪造已对接。
 *
 * 派生字段（remaining / usage_pct / is_exceeded / is_warning）与 Python property 同口径，
 * 在此前端重算，保证两种数据源下展示一致。
 */
import { computed, onMounted, ref } from 'vue'
import StatusBadge from '@/components/StatusBadge.vue'
import {
  budgetIsExceeded,
  budgetIsWarning,
  budgetRemaining,
  budgetStatus,
  budgetUsagePct,
  detectGovSource,
  usageByDate,
  usageTotals,
  type BudgetLimit,
  type BudgetStatus,
  type GovSource,
  type UsageRow,
  type UsageTotals,
} from '@/api/governance'

const source = ref<GovSource>('contract-mock')
const budget = ref<BudgetStatus>({})
const totals = ref<UsageTotals>({ prompt_tokens: 0, completion_tokens: 0, total_tokens: 0, call_count: 0 })
const rows = ref<UsageRow[]>([])
const loading = ref(false)
const lastError = ref('')

const LEVEL_LABEL: Record<string, string> = {
  task: '任务级预算',
  project: '项目级预算',
  daily: '当日预算',
}

/** 固定顺序展示三级预算，缺失的级别不渲染 */
const levels = computed<Array<{ key: string; limit: BudgetLimit }>>(() => {
  const order: Array<'task' | 'project' | 'daily'> = ['task', 'project', 'daily']
  const out: Array<{ key: string; limit: BudgetLimit }> = []
  for (const key of order) {
    const limit = budget.value[key]
    if (limit) out.push({ key, limit })
  }
  return out
})

function fmt(value: number): string {
  return new Intl.NumberFormat('en-US').format(Math.round(value || 0))
}

function barTone(limit: BudgetLimit): 'danger' | 'warn' | 'cyan' {
  if (budgetIsExceeded(limit)) return 'danger'
  if (budgetIsWarning(limit)) return 'warn'
  return 'cyan'
}

function barState(limit: BudgetLimit): string {
  if (budgetIsExceeded(limit)) return '已超限'
  if (budgetIsWarning(limit)) return '接近上限'
  return '正常'
}

const exceededCount = computed(() => levels.value.filter((item) => budgetIsExceeded(item.limit)).length)
const warningCount = computed(
  () => levels.value.filter((item) => !budgetIsExceeded(item.limit) && budgetIsWarning(item.limit)).length,
)

async function load(): Promise<void> {
  loading.value = true
  lastError.value = ''
  try {
    source.value = await detectGovSource()
    const [budgetRes, totalsRes, rowsRes] = await Promise.all([
      budgetStatus(undefined, 'AideanFleet'),
      usageTotals(),
      usageByDate(),
    ])
    source.value = budgetRes.source
    budget.value = budgetRes.data
    totals.value = totalsRes.data
    rows.value = [...rowsRes.data].sort((a, b) => String(b.period).localeCompare(String(a.period)))
  } catch (error) {
    lastError.value = error instanceof Error ? error.message : '成本数据加载失败'
  } finally {
    loading.value = false
  }
}

onMounted(load)
</script>

<template>
  <section class="page">
    <header class="page-head">
      <div class="page-title">
        <h2>成本面板</h2>
        <span class="page-sub">Token 用量与三级预算（GOV-01 · 口径见契约 v1.2 §13）</span>
      </div>
      <button class="btn" type="button" :disabled="loading" @click="load">
        {{ loading ? '加载中…' : '刷新' }}
      </button>
    </header>

    <div class="card source-card" :class="source === 'api' ? 'src-api' : 'src-mock'">
      <div class="card-title">
        <span>数据源</span>
        <StatusBadge
          data-testid="gov-source-badge"
          :label="source === 'api' ? '真实 API · /api/usage + /api/budget' : '后端未就绪 · 契约形状兜底'"
          :tone="source === 'api' ? 'ok' : 'warn'"
        />
      </div>
      <p v-if="source === 'api'" class="hint">
        已连通治理 HTTP 面。用量聚合自 <span class="mono">events.jsonl</span> 的
        <span class="mono">model:call</span> 事件，预算取自 <span class="mono">BudgetManager</span>。
      </p>
      <p v-else class="hint">
        实测 <span class="mono">GET /api/usage/total</span>、<span class="mono">/api/usage/by_date</span>、
        <span class="mono">/api/budget</span> 均返回 <span class="mono">404 not_found</span>。
        下列数据为**契约形状兜底**（按 Python 侧默认额度 task 200000 / project 2000000 / daily 500000 种子化），
        角色A 暴露端点后本页自动切换真实数据。
      </p>
    </div>

    <!-- 三级预算 -->
    <div class="card">
      <div class="card-title">
        <span>预算水位</span>
        <span class="hint">
          超限 {{ exceededCount }} 级 · 预警 {{ warningCount }} 级（阈值 80%）
        </span>
      </div>

      <div v-if="levels.length" class="budget-grid" data-testid="budget-cards">
        <div v-for="item in levels" :key="item.key" class="budget-card" data-testid="budget-card">
          <div class="b-head">
            <b>{{ LEVEL_LABEL[item.key] ?? item.key }}</b>
            <StatusBadge :label="barState(item.limit)" :tone="barTone(item.limit)" />
          </div>
          <div class="b-scope mono">{{ item.limit.scope || '—' }}</div>

          <div class="b-bar">
            <span :class="`fill-${barTone(item.limit)}`" :style="{ width: `${Math.min(100, budgetUsagePct(item.limit))}%` }" />
          </div>

          <div class="b-foot">
            <span class="mono">{{ fmt(item.limit.used_tokens) }} / {{ fmt(item.limit.limit_tokens) }}</span>
            <span class="pct mono">{{ budgetUsagePct(item.limit) }}%</span>
          </div>
          <div class="b-meta tiny muted">
            剩余 <span class="mono">{{ fmt(budgetRemaining(item.limit)) }}</span> tokens
            <span class="dot-sep">·</span>
            超限动作 <span class="mono">{{ item.limit.action || 'pause' }}</span>
          </div>
        </div>
      </div>
      <p v-else class="empty">无预算记录。</p>
    </div>

    <!-- 用量总览 -->
    <div class="card">
      <div class="card-title">
        <span>用量总览</span>
        <span class="hint">全量累计（UsageAggregator.total）</span>
      </div>
      <div class="totals" data-testid="usage-totals">
        <div class="t-item">
          <b class="mono">{{ fmt(totals.total_tokens) }}</b>
          <span>总 tokens</span>
        </div>
        <div class="t-item">
          <b class="mono">{{ fmt(totals.prompt_tokens) }}</b>
          <span>prompt</span>
        </div>
        <div class="t-item">
          <b class="mono">{{ fmt(totals.completion_tokens) }}</b>
          <span>completion</span>
        </div>
        <div class="t-item">
          <b class="mono">{{ fmt(totals.call_count) }}</b>
          <span>调用次数</span>
        </div>
      </div>
    </div>

    <!-- 按日用量 -->
    <div class="card">
      <div class="card-title">
        <span>按日用量</span>
        <span class="hint">{{ rows.length }} 天</span>
      </div>
      <div v-if="rows.length" class="table-wrap">
        <table class="grid" data-testid="usage-by-date">
          <thead>
            <tr>
              <th style="width: 130px">日期</th>
              <th>prompt</th>
              <th>completion</th>
              <th>合计</th>
              <th style="width: 96px">调用次数</th>
              <th>缓存命中</th>
              <th style="width: 110px">未知用量</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="row in rows" :key="row.period">
              <td class="cell-mono">{{ row.period }}</td>
              <td class="cell-mono">{{ fmt(row.prompt_tokens) }}</td>
              <td class="cell-mono">{{ fmt(row.completion_tokens) }}</td>
              <td class="cell-mono">{{ fmt(row.total_tokens) }}</td>
              <td class="cell-mono">{{ fmt(row.call_count) }}</td>
              <td class="cell-mono">{{ fmt(row.cached_tokens ?? 0) }}</td>
              <td class="cell-mono">{{ fmt(row.unknown_usage ?? 0) }}</td>
            </tr>
          </tbody>
        </table>
      </div>
      <p v-else class="empty">暂无按日用量。</p>

      <p v-if="lastError" class="err-text">{{ lastError }}</p>
    </div>
  </section>
</template>

<style scoped>
.source-card {
  border-left: 3px solid var(--warn);
}
.source-card.src-api {
  border-left-color: var(--ok);
}
.source-card.src-mock {
  background: var(--warn-dim);
}

.budget-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 14px;
}

@media (max-width: 1180px) {
  .budget-grid {
    grid-template-columns: minmax(0, 1fr);
  }
}

.budget-card {
  padding: 12px 14px;
  border: 1px solid var(--line);
  border-radius: var(--radius-sm);
  background: var(--bg-input);
}

.b-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
}

.b-head b {
  font-size: 13px;
  color: var(--text);
}

.b-scope {
  margin-top: 3px;
  font-size: 11px;
  color: var(--text-mute);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.b-bar {
  margin: 10px 0 7px;
  height: 7px;
  border-radius: 999px;
  background: var(--mute-dim);
  overflow: hidden;
}

.b-bar span {
  display: block;
  height: 100%;
  border-radius: 999px;
  transition: width var(--dur) var(--ease);
}

.fill-cyan {
  background: var(--accent-cyan);
}
.fill-warn {
  background: var(--warn);
}
.fill-danger {
  background: var(--danger);
}

.b-foot {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  font-size: 12px;
  color: var(--text-dim);
}

.b-foot .pct {
  color: var(--text);
}

.b-meta {
  margin-top: 5px;
}

.dot-sep {
  margin: 0 6px;
}

.totals {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 14px;
}

@media (max-width: 900px) {
  .totals {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}

.t-item {
  display: flex;
  flex-direction: column;
  gap: 3px;
  padding: 12px 14px;
  border: 1px solid var(--line);
  border-radius: var(--radius-sm);
  background: var(--bg-input);
}

.t-item b {
  font-size: 20px;
  color: var(--text);
}

.t-item span {
  font-size: 12px;
  color: var(--text-mute);
}
</style>
