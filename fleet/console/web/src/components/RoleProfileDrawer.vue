<script setup lang="ts">
/**
 * RoleProfileDrawer · 角色工作档案弹窗（需求6）
 *
 * 数据源 GET /api/roles/{role}/profile：
 *  - 做了什么：executed（assignee=该角色）与 reviewed（reviewer=该角色）；
 *  - 用了多少时间：duration_ms = 执行任务耗时合计；
 *  - 占了多少资源：total_tokens / call_count（模型调用按 extra.role 归属，含审查调用）；
 *  - 未来任务分配：future = 该角色名下尚未收口的任务（DRAFT/ASSIGNED/REWORK/BLOCKED/ESCALATED）。
 * 入口：总览页「角色贡献」表行点击。
 */
import { ref, watch } from 'vue'
import Modal from '@/components/Modal.vue'
import StatusBadge from '@/components/StatusBadge.vue'
import { api } from '@/api/client'
import { useAuthStore } from '@/stores/auth'
import type { RoleProfile, RoleProfileTask } from '@/api/types'

const props = defineProps<{ role: string | null }>()
const emit = defineEmits<{ (e: 'close'): void }>()

const auth = useAuthStore()
const profile = ref<RoleProfile | null>(null)
const loading = ref(false)
const error = ref('')

async function load(role: string): Promise<void> {
  loading.value = true
  error.value = ''
  profile.value = null
  try {
    const result = await api.roleProfile(role, auth.project || undefined)
    profile.value = result.profile ?? null
    if (!result.profile) error.value = '角色档案不存在'
  } catch (caught) {
    error.value = caught instanceof Error ? caught.message : '角色档案加载失败'
  } finally {
    loading.value = false
  }
}

watch(
  () => props.role,
  (role) => {
    if (role) void load(role)
  },
)

function durationText(ms: number): string {
  const value = Number(ms ?? 0)
  if (!value) return '—'
  const total = Math.round(value / 1000)
  if (total < 60) return `${total}秒`
  const m = Math.floor(total / 60)
  const s = total % 60
  if (m < 60) return `${m}分${s}秒`
  return `${Math.floor(m / 60)}时${m % 60}分`
}

function tokenText(n: number): string {
  return new Intl.NumberFormat('en-US').format(Math.round(n || 0))
}

function rowsOf(list: RoleProfileTask[] | undefined): RoleProfileTask[] {
  return list ?? []
}
</script>

<template>
  <Modal
    :model-value="Boolean(props.role)"
    :title="`角色档案 · ${props.role ?? ''}`"
    :width="680"
    @update:model-value="emit('close')"
  >
    <div v-if="loading" class="hint">加载中…</div>
    <div v-else-if="error" class="err-text">{{ error }}</div>
    <template v-else-if="profile">
      <!-- 汇总：做了多少、多久、多少资源 -->
      <div class="stats" data-testid="role-profile-stats">
        <div class="stat">
          <span class="k">执行任务</span>
          <b class="v mono">{{ profile.executed_count }}</b>
          <span class="sub">完成 {{ profile.done_count }}</span>
        </div>
        <div class="stat">
          <span class="k">审查任务</span>
          <b class="v mono">{{ profile.reviewed_count }}</b>
        </div>
        <div class="stat">
          <span class="k">总耗时</span>
          <b class="v mono">{{ durationText(profile.duration_ms) }}</b>
        </div>
        <div class="stat">
          <span class="k">Token</span>
          <b class="v mono">{{ tokenText(profile.total_tokens) }}</b>
          <span class="sub">{{ profile.call_count }} 次调用</span>
        </div>
      </div>

      <!-- 三段列表：做过 / 审过 / 未来 -->
      <section v-for="block in [
        { key: 'executed', title: '做过的工作', list: rowsOf(profile.executed), empty: '尚未执行过任务' },
        { key: 'reviewed', title: '审查过的工作', list: rowsOf(profile.reviewed), empty: '尚未审查过任务' },
        { key: 'future', title: '未来任务分配', list: rowsOf(profile.future), empty: '没有待执行的任务分配' },
      ]" :key="block.key" class="block" :data-testid="`role-profile-${block.key}`">
        <div class="block-title">
          <span>{{ block.title }}</span>
          <span class="count mono">{{ block.list.length }}</span>
        </div>
        <ul v-if="block.list.length" class="task-list">
          <li v-for="item in block.list" :key="item.task_id" class="task">
            <span class="tid mono">{{ item.task_id }}</span>
            <span class="ttitle">{{ item.title || item.task_id }}</span>
            <StatusBadge :state="item.state" />
            <span v-if="item.rework_count" class="rework tiny">返工 {{ item.rework_count }}</span>
            <span class="meta mono tiny">{{ durationText(item.duration_ms) }} · {{ tokenText(item.token) }} tok</span>
          </li>
        </ul>
        <p v-else class="hint">{{ block.empty }}</p>
      </section>
      <p class="hint foot">· 耗时 = 执行任务 duration_ms 合计；Token/调用按模型事件的角色归属统计（含审查调用）。</p>
    </template>
  </Modal>
</template>

<style scoped>
.stats {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 10px;
  margin-bottom: 14px;
}

.stat {
  display: flex;
  flex-direction: column;
  gap: 2px;
  padding: 10px 12px;
  border: 1px solid var(--line);
  border-radius: var(--radius-sm);
  background: var(--bg-panel-2);
}

.stat .k {
  font-size: 11px;
  color: var(--text-mute);
}

.stat .v {
  font-size: 15px;
  color: var(--text);
}

.stat .sub {
  font-size: 11px;
  color: var(--text-mute);
}

.block {
  margin-bottom: 14px;
}

.block-title {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 12.5px;
  color: var(--text-dim);
  font-weight: 600;
  margin-bottom: 6px;
}

.count {
  padding: 0 8px;
  border-radius: 999px;
  border: 1px solid var(--line);
  color: var(--text-mute);
  font-size: 11px;
}

.task-list {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 2px;
  max-height: 180px;
  overflow-y: auto;
}

.task {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 5px 7px;
  border-radius: var(--radius-sm);
  background: var(--bg-panel-2);
}

.task .tid {
  font-size: 11px;
  color: var(--text-mute);
  flex: 0 0 auto;
}

.task .ttitle {
  font-size: 12.5px;
  color: var(--text);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  min-width: 0;
  flex: 1;
}

.task .rework {
  color: var(--danger);
}

.task .meta {
  flex: 0 0 auto;
  color: var(--text-mute);
}

.foot {
  margin-top: 4px;
}
</style>
