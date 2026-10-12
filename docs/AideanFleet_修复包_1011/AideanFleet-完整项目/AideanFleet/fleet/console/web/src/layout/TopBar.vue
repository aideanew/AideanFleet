<script setup lang="ts">
/**
 * TopBar · 顶部栏（缺陷 #1）
 * 硬规范：右侧顺序固定为【🔒 锁定】在前（靠左）、【⚙ 设置】在后（靠右）；
 * 左侧 = Logo + 项目名 + 连接状态。无底部信息栏（该条由 App.vue 的布局保证）。
 * 项目徽标为下拉：列出全部项目（免会话 names 端点），选择即切换会话项目并刷新计划。
 */
import { computed, onMounted, ref } from 'vue'
import { useAuthStore } from '@/stores/auth'
import { useConnectionStore } from '@/stores/connection'
import { usePlanStore } from '@/stores/plan'
import { useExecutionStore } from '@/stores/execution'
import { useTaskStore } from '@/stores/task'
import { useChatStore } from '@/stores/chat'
import { api } from '@/api/client'
import { toast } from '@/composables/useToast'
import { useWebSocket } from '@/composables/useWebSocket'

const emit = defineEmits<{ (e: 'open-settings'): void; (e: 'lock'): void }>()

const auth = useAuthStore()
const connection = useConnectionStore()
const plan = usePlanStore()
const execution = useExecutionStore()
const ws = useWebSocket()

const allProjects = ref<{ id: string; name: string }[]>([])
const switching = ref(false)

onMounted(async () => {
  try {
    const result = await api.listProjectNames()
    allProjects.value = result.projects ?? []
  } catch {
    /* 拉不到就不显示候选，不影响当前项目展示 */
  }
})

/** 切换项目：服务端换绑会话 → 本地清空旧项目态 → 重新拉计划 */
async function switchProject(name: string): Promise<void> {
  if (switching.value || name === auth.project) return
  switching.value = true
  const ok = await auth.switchTo(name)
  switching.value = false
  if (!ok) {
    toast.fail('切换失败', auth.lastError)
    return
  }
  // 项目隔离：重置连接游标并重建 WS，避免跨项目消息串台
  connection.reset()
  ws.disconnect()
  execution.clear()
  useTaskStore().clear()
  useChatStore().clear()
  await plan.load(auth.project || undefined)
  // 重新建立实时通道：start() 重挂心跳/监听，connect() 真正发起新 WebSocket
  // （与 App.vue afterUnlock 同构；仅 start() 会因幂等守卫不发连接）
  ws.start()
  ws.connect()
  toast.ok(`已切换到项目 ${auth.project}`)
}

const runState = computed(() => {
  if (!plan.started) return '待启动'
  if (plan.percent >= 100) return '已收口'
  return `执行中 ${plan.percent}%`
})

const connClass = computed(() => `tone-${connection.tone}`)
</script>

<template>
  <header class="topbar">
    <!-- 左侧：Logo + 项目下拉 + 连接状态 -->
    <div class="left">
      <span class="logo">◈ AideanFleet</span>
      <select
        class="project-select"
        :value="auth.project"
        :disabled="switching"
        title="切换项目"
        @change="switchProject(($event.target as HTMLSelectElement).value)"
      >
        <!-- 候选未加载/当前项目不在候选（列表竞态）时的兜底回显：
             value 仍绑 auth.project，避免列表到达前下拉整块空白 -->
        <option v-if="!allProjects.some((item) => item.id === auth.project)" :value="auth.project">
          {{ auth.project || '未解锁' }}
        </option>
        <!-- value 必须用 project_id（与 :value="auth.project" 同语义）；用 name 会因 id/name 分裂导致当前项目无法回显（缺陷⑤） -->
        <option v-for="item in allProjects" :key="item.id" :value="item.id">
          {{ item.name }}（{{ item.id }}）
        </option>
      </select>
      <span class="chip" :class="connClass" data-testid="conn-state">
        <i class="dot" />
        {{ connection.label }}
      </span>
      <span class="chip tone-mute">{{ runState }}</span>
      <span class="chip tone-mute" title="调度模式">{{ execution.modeLabel }}</span>
    </div>

    <!-- 右侧：先锁定，后设置（顺序不得颠倒） -->
    <div class="right">
      <span class="ttl mono" :title="`会话剩余有效时间（${auth.expiresIn} 秒总时长）`">
        会话 {{ auth.remainText }}
      </span>
      <button id="lock-now" class="btn btn-ghost" type="button" title="立即锁定（回锁屏）" @click="emit('lock')">
        🔒 锁定
      </button>
      <button id="settings-btn" class="btn btn-ghost" type="button" title="设置" @click="emit('open-settings')">
        ⚙ 设置
      </button>
    </div>
  </header>
</template>

<style scoped>
.topbar {
  flex: 0 0 auto;
  height: var(--topbar-h);
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  padding: 0 16px;
  border-bottom: 1px solid var(--line);
  background: var(--bg-panel);
}

.left,
.right {
  display: flex;
  align-items: center;
  gap: 10px;
  min-width: 0;
}

.logo {
  font-size: 14px;
  font-weight: 700;
  letter-spacing: 0.4px;
  color: var(--text);
  white-space: nowrap;
}

.project-select {
  max-width: 220px;
  padding: 4px 8px;
  border-radius: var(--radius-sm);
  border: 1px solid var(--line);
  background: var(--bg-panel-2);
  color: var(--accent-cyan);
  font-size: 12px;
  font-weight: 600;
  cursor: pointer;
}

.project-select:focus {
  outline: none;
  border-color: var(--accent-cyan);
}

.chip {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 3px 9px;
  border-radius: 999px;
  border: 1px solid transparent;
  font-size: 12px;
  white-space: nowrap;
}

.chip .dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: currentColor;
}

.tone-ok {
  color: var(--ok);
  background: var(--ok-dim);
  border-color: rgba(34, 197, 94, 0.3);
}
.tone-warn {
  color: var(--warn);
  background: var(--warn-dim);
  border-color: rgba(245, 158, 11, 0.3);
}
.tone-danger {
  color: var(--danger);
  background: var(--danger-dim);
  border-color: rgba(239, 68, 68, 0.3);
}
.tone-info {
  color: var(--info);
  background: var(--info-dim);
  border-color: rgba(96, 165, 250, 0.3);
}
.tone-mute {
  color: var(--text-dim);
  background: var(--mute-dim);
  border-color: var(--line);
}

.ttl {
  font-size: 12px;
  color: var(--text-mute);
}
</style>
