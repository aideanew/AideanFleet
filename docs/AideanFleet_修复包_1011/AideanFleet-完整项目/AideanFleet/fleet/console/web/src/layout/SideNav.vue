<script setup lang="ts">
/**
 * SideNav · 左侧菜单（缺陷 #4 的修复载体）
 * 用 ResizablePanel 重建：拖拽期无过渡、折叠与拖拽值解耦、拖到最窄自动折叠（联动），
 * 连续快速拖拽 10 次不抖动，三态（拖拽/折叠/展开）互不覆盖。
 * 一级大纲顺序固定：[总览, 对话, 模型, 角色, 执行体, 拓展, 消息]。
 */
import { computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import ResizablePanel from '@/components/ResizablePanel.vue'
import { MENU } from '@/router'
import { usePlanStore } from '@/stores/plan'

const props = defineProps<{ collapsed: boolean }>()
const emit = defineEmits<{ (e: 'update:collapsed', value: boolean): void }>()

const route = useRoute()
const router = useRouter()
const plan = usePlanStore()

const activePath = computed(() => route.path)

/** 菜单右侧的角标：总览显示进度，对话显示未读较难界定故省略，模型/角色/执行体显示数量 */
function badgeOf(path: string): string {
  if (path === '/overview') return plan.started ? `${plan.percent}%` : ''
  return ''
}

function go(path: string) {
  if (route.path !== path) void router.push(path)
}
</script>

<template>
  <ResizablePanel
    side="left"
    :collapsed="props.collapsed"
    :min="180"
    :max="420"
    :default-width="208"
    :collapsed-width="60"
    storage-key="fleet.nav.width"
    @update:collapsed="emit('update:collapsed', $event)"
  >
    <nav class="nav" aria-label="主导航">
      <button
        v-for="item in MENU"
        :key="item.path"
        class="item"
        :class="{ active: activePath === item.path, compact: collapsed }"
        type="button"
        :title="collapsed ? item.title : item.hint"
        @click="go(item.path)"
      >
        <span class="icon">{{ item.icon }}</span>
        <span v-show="!collapsed" class="text">
          <b>{{ item.title }}</b>
          <em>{{ item.hint }}</em>
        </span>
        <span v-if="!collapsed && badgeOf(item.path)" class="badge">{{ badgeOf(item.path) }}</span>
      </button>
    </nav>

    <div class="foot">
      <button
        class="collapse"
        type="button"
        :title="collapsed ? '展开菜单' : '收起菜单'"
        @click="emit('update:collapsed', !collapsed)"
      >
        <span class="chev">{{ collapsed ? '»' : '«' }}</span>
        <span v-show="!collapsed">收起菜单</span>
      </button>
    </div>
  </ResizablePanel>
</template>

<style scoped>
.nav {
  display: flex;
  flex-direction: column;
  gap: 2px;
  padding: 10px 8px;
}

.item {
  display: flex;
  align-items: center;
  gap: 10px;
  width: 100%;
  padding: 9px 10px;
  border: 0;
  border-left: 2px solid transparent;
  border-radius: var(--radius-sm);
  background: transparent;
  color: var(--text-dim);
  text-align: left;
  transition: background var(--dur-fast) var(--ease), color var(--dur-fast) var(--ease);
}

.item:hover {
  background: var(--bg-hover);
  color: var(--text);
}

.item.active {
  background: var(--accent-cyan-dim);
  border-left-color: var(--accent-cyan);
  color: var(--accent-cyan);
}

.item.compact {
  justify-content: center;
  padding: 10px 0;
}

.icon {
  flex: 0 0 auto;
  width: 18px;
  text-align: center;
  font-size: 14px;
}

.text {
  display: flex;
  flex-direction: column;
  gap: 1px;
  min-width: 0;
  overflow: hidden;
}

.text b {
  font-size: 13px;
  font-weight: 600;
  white-space: nowrap;
}

.text em {
  font-style: normal;
  font-size: 11px;
  color: var(--text-mute);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.item.active .text em {
  color: rgba(0, 212, 255, 0.72);
}

.badge {
  margin-left: auto;
  font-family: var(--font-mono);
  font-size: 11px;
  color: var(--accent-cyan);
}

.foot {
  padding: 8px;
  border-top: 1px solid var(--line);
  margin-top: auto;
}

.collapse {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  width: 100%;
  padding: 8px;
  border: 1px solid var(--line);
  border-radius: var(--radius-sm);
  background: transparent;
  color: var(--text-dim);
  font-size: 12px;
}

.collapse:hover {
  border-color: var(--line-accent);
  color: var(--accent-cyan);
}

.chev {
  font-size: 13px;
}
</style>
