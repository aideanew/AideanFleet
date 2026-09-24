<script setup lang="ts">
/**
 * ApprovalCenterPage · 审批中心（UI-03R §9.5）
 *
 * 数据源：`fleet/governance/`（GOV-01）+ server.py 治理 HTTP 面
 *   GET /api/approvals[?project=] · GET /api/approvals/{id}
 *   POST /api/approvals/{id}/approve · POST /api/approvals/{id}/reject
 * 后端已挂载：source = api；探测失败时走契约形状兜底并显式标注「后端未就绪」。
 */
import { computed, onMounted, ref } from 'vue'
import StatusBadge from '@/components/StatusBadge.vue'
import {
  APPROVAL_ACTION_LABEL,
  decideApproval,
  detectGovSource,
  listApprovals,
  type ApprovalRequest,
  type GovSource,
} from '@/api/governance'
import { toast } from '@/composables/useToast'
import { useAuthStore } from '@/stores/auth'

const auth = useAuthStore()

const source = ref<GovSource>('contract-mock')
const rows = ref<ApprovalRequest[]>([])
const loading = ref(false)
const busyId = ref('')
const lastError = ref('')
const filter = ref<'all' | 'pending' | 'approved' | 'rejected'>('all')

const filtered = computed(() => {
  if (filter.value === 'all') return rows.value
  return rows.value.filter((row) => String(row.status) === filter.value)
})

const pendingCount = computed(() => rows.value.filter((row) => row.status === 'pending').length)
const approvedCount = computed(() => rows.value.filter((row) => row.status === 'approved').length)
const rejectedCount = computed(() => rows.value.filter((row) => row.status === 'rejected').length)

const STATUS_META: Record<string, { label: string; tone: 'warn' | 'ok' | 'danger' | 'mute' }> = {
  pending: { label: '待审批', tone: 'warn' },
  approved: { label: '已通过', tone: 'ok' },
  rejected: { label: '已拒绝', tone: 'danger' },
  expired: { label: '已过期', tone: 'mute' },
}

function statusMeta(status: string): { label: string; tone: 'warn' | 'ok' | 'danger' | 'mute' } {
  return STATUS_META[status] ?? { label: status || '未知', tone: 'mute' }
}

function actionLabel(action: string): string {
  return APPROVAL_ACTION_LABEL[action] ?? action
}

function shortTime(value: string): string {
  if (!value) return '—'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())} ${pad(date.getHours())}:${pad(date.getMinutes())}`
}

async function load(): Promise<void> {
  loading.value = true
  lastError.value = ''
  try {
    source.value = await detectGovSource()
    const result = await listApprovals(auth.project || 'AideanFleet')
    source.value = result.source
    rows.value = result.data
  } catch (error) {
    lastError.value = error instanceof Error ? error.message : '审批列表加载失败'
  } finally {
    loading.value = false
  }
}

async function decide(row: ApprovalRequest, decision: 'approve' | 'reject'): Promise<void> {
  if (row.status !== 'pending' || busyId.value) return
  busyId.value = row.approval_id
  try {
    await decideApproval(row.approval_id, decision)
    toast.ok(decision === 'approve' ? '已通过审批' : '已拒绝审批', `${row.approval_id} · ${actionLabel(row.action_type)}`)
    await load()
  } catch (error) {
    toast.fail('审批操作失败', error instanceof Error ? error.message : '')
  } finally {
    busyId.value = ''
  }
}

onMounted(load)
</script>

<template>
  <section class="page">
    <header class="page-head">
      <div class="page-title">
        <h2>审批中心</h2>
        <span class="page-sub">delete/overwrite 红线 · 首次真实 SMTP 发送 · 预算阈值告警（GOV-01）</span>
      </div>
      <button class="btn" type="button" :disabled="loading" @click="load">
        {{ loading ? '加载中…' : '刷新' }}
      </button>
    </header>

    <!-- 数据源标注：后端未就绪时显式声明，不伪装已对接 -->
    <div class="card source-card" :class="source === 'api' ? 'src-api' : 'src-mock'">
      <div class="card-title">
        <span>数据源</span>
        <StatusBadge
          data-testid="gov-source-badge"
          :label="source === 'api' ? '真实 API · /api/approvals' : '后端未就绪 · 契约形状兜底'"
          :tone="source === 'api' ? 'ok' : 'warn'"
        />
      </div>
      <p v-if="source === 'api'" class="hint">
        已连通角色A 的治理 HTTP 面，下列记录为 <span class="mono">governance.db</span> 真实落盘数据。
      </p>
      <p v-else class="hint">
        实测 <span class="mono">GET /api/approvals</span> 返回 <span class="mono">404 not_found</span>：GOV-01 的
        <span class="mono">fleet/governance/</span> 包已交付，但尚未挂载 HTTP 路由（契约流程待办）。
        下列记录为**契约形状兜底**（字段照抄 <span class="mono">ApprovalRequest</span> dataclass），
        用于验证本页交互链路；角色A 一暴露端点即自动切换为真实数据，本页零改动。
      </p>
    </div>

    <div class="stat-row">
      <div class="stat">
        <b>{{ pendingCount }}</b>
        <span>待审批</span>
      </div>
      <div class="stat">
        <b>{{ approvedCount }}</b>
        <span>已通过</span>
      </div>
      <div class="stat">
        <b>{{ rejectedCount }}</b>
        <span>已拒绝</span>
      </div>
      <div class="spacer" />
      <div class="seg">
        <button
          v-for="item in [
            { key: 'all', label: '全部' },
            { key: 'pending', label: '待审批' },
            { key: 'approved', label: '已通过' },
            { key: 'rejected', label: '已拒绝' },
          ]"
          :key="item.key"
          type="button"
          :class="{ on: filter === item.key }"
          @click="filter = item.key as typeof filter"
        >
          {{ item.label }}
        </button>
      </div>
    </div>

    <div class="card">
      <div class="card-title">
        <span>审批请求</span>
        <span class="hint">{{ filtered.length }} / {{ rows.length }} 条</span>
      </div>

      <div v-if="filtered.length" class="table-wrap">
        <table class="grid" data-testid="approvals-table">
          <thead>
            <tr>
              <th style="width: 232px">审批类型</th>
              <th>说明</th>
              <th style="width: 86px">任务</th>
              <th style="width: 96px">发起方</th>
              <th style="width: 132px">创建时间</th>
              <th style="width: 96px">状态</th>
              <th style="width: 150px">操作</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="row in filtered" :key="row.approval_id" data-testid="approval-row">
              <td>
                <div class="cell-title">{{ actionLabel(row.action_type) }}</div>
                <div class="cell-mono">{{ row.approval_id }}</div>
              </td>
              <td>{{ row.description }}</td>
              <td class="cell-mono">{{ row.task_id || '—' }}</td>
              <td class="cell-mono">{{ row.requested_by }}</td>
              <td class="cell-mono">{{ shortTime(row.created_at) }}</td>
              <td>
                <StatusBadge :label="statusMeta(row.status).label" :tone="statusMeta(row.status).tone" />
              </td>
              <td>
                <div v-if="row.status === 'pending'" class="row">
                  <button
                    class="btn btn-primary btn-sm"
                    type="button"
                    data-testid="approve-btn"
                    :disabled="busyId === row.approval_id"
                    @click="decide(row, 'approve')"
                  >
                    通过
                  </button>
                  <button
                    class="btn btn-danger btn-sm"
                    type="button"
                    data-testid="reject-btn"
                    :disabled="busyId === row.approval_id"
                    @click="decide(row, 'reject')"
                  >
                    拒绝
                  </button>
                </div>
                <span v-else class="muted tiny">
                  {{ row.decided_by || '—' }} · {{ shortTime(row.decided_at) }}
                </span>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
      <p v-else class="empty" data-testid="approvals-empty">
        {{ rows.length ? '当前筛选下没有记录。' : '暂无审批请求。' }}
      </p>

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

.stat-row {
  display: flex;
  align-items: center;
  gap: 18px;
  margin-bottom: 14px;
}

.stat {
  display: flex;
  align-items: baseline;
  gap: 8px;
}

.stat b {
  font-family: var(--font-mono);
  font-size: 22px;
  color: var(--text);
}

.stat span {
  font-size: 12px;
  color: var(--text-mute);
}

.seg {
  display: inline-flex;
  border: 1px solid var(--line);
  border-radius: var(--radius-sm);
  overflow: hidden;
}

.seg button {
  padding: 5px 12px;
  border: 0;
  background: transparent;
  color: var(--text-dim);
  font-size: 12px;
}

.seg button.on {
  background: var(--accent-cyan-dim);
  color: var(--accent-cyan);
}

.cell-title {
  font-size: 13px;
  color: var(--text);
}

.btn-sm {
  padding: 4px 10px;
  font-size: 12px;
}
</style>
