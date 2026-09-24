<script setup lang="ts">
/**
 * App · 应用根（缺陷 #1 的布局保证）
 *
 * 结构：锁屏门（未解锁时整屏显示）→ 外壳（TopBar + [SideNav | 路由视图 | ProgressRail]）。
 * 硬规范：
 *  - 右侧顺序固定「锁定 → 设置」，由 TopBar 保证；本组件只负责事件接线；
 *  - **没有底部信息栏**（旧版底栏的位置不再渲染任何元素），信息全部上移到 TopBar；
 *  - 解锁后启动 WS（重连/轮询/增量补拉由 useWebSocket 统一负责）。
 */
import { onMounted, ref, watch } from 'vue'
import LockScreen from '@/layout/LockScreen.vue'
import TopBar from '@/layout/TopBar.vue'
import SideNav from '@/layout/SideNav.vue'
import ProgressRail from '@/layout/ProgressRail.vue'
import SettingsPanel from '@/layout/SettingsPanel.vue'
import Toast from '@/components/Toast.vue'
import { useAuthStore } from '@/stores/auth'
import { useExecutionStore } from '@/stores/execution'
import { useWebSocket } from '@/composables/useWebSocket'

const auth = useAuthStore()
const execution = useExecutionStore()
const ws = useWebSocket()

const booting = ref(true)
const navCollapsed = ref(false)
const railCollapsed = ref(false)
const settingsOpen = ref(false)

/**
 * 解锁后：起 WS + **把服务端调度模式拉回来**。
 *
 * 为什么必须在解锁时拉：调度模式是**服务端状态**（POST /api/mode / WS set_mode 落库），
 * 但客户端之前只在切换时乐观更新本地值，从不回读。
 * 结果刷新页面后 UI 会谎报默认的「自动执行」，与服务端真实值脱节（主题 9.3 实测捕获）。
 * execution.loadMode() 早已实现却无人调用，这里补上这一环。
 */
function afterUnlock(): void {
  ws.start()
  ws.connect()
  void execution.loadMode()
}

watch(
  () => auth.unlocked,
  (unlocked) => {
    if (unlocked) afterUnlock()
    else {
      ws.disconnect()
      settingsOpen.value = false
    }
  },
)

onMounted(async () => {
  const restored = await auth.restore()
  booting.value = false
  if (restored) afterUnlock()
})

async function onLock(): Promise<void> {
  await auth.lock()
}
</script>

<template>
  <div v-if="booting" class="boot">
    <span class="spinner" />
    <p>正在连接控制台…</p>
  </div>

  <LockScreen v-else-if="!auth.unlocked" />

  <div v-else class="shell">
    <TopBar @open-settings="settingsOpen = true" @lock="onLock" />

    <div class="body">
      <SideNav v-model:collapsed="navCollapsed" />
      <main class="main">
        <router-view v-slot="{ Component }">
          <component :is="Component" />
        </router-view>
      </main>
      <ProgressRail v-model:collapsed="railCollapsed" />
    </div>
  </div>

  <SettingsPanel v-model:open="settingsOpen" />
  <Toast />
</template>

<style scoped>
.boot {
  height: 100%;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 14px;
  color: var(--text-dim);
}

.spinner {
  width: 26px;
  height: 26px;
  border-radius: 50%;
  border: 2px solid var(--line-strong);
  border-top-color: var(--accent-cyan);
  animation: spin 0.8s linear infinite;
}

@keyframes spin {
  to {
    transform: rotate(360deg);
  }
}

.shell {
  height: 100%;
  display: flex;
  flex-direction: column;
  min-height: 0;
}

.body {
  flex: 1;
  display: flex;
  min-height: 0;
  overflow: hidden;
}

.main {
  flex: 1;
  min-width: 0;
  min-height: 0;
  overflow: auto;
  background: var(--bg-base);
}
</style>
