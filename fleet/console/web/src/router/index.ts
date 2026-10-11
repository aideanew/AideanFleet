import { createRouter, createWebHistory } from 'vue-router'

/**
 * 一级大纲。前 7 项为 UI-02 冻结顺序，**永不重排**；
 * UI-03R 新增的治理页一律**追加**在末尾（§9.5 审批中心 / 成本面板）。
 */
export const MENU = [
  { path: '/overview', name: 'overview', title: '总览', icon: '◧', hint: '当前执行步骤与阶段进度' },
  { path: '/chat', name: 'chat', title: '对话', icon: '◌', hint: '与 Manager 实时交流' },
  { path: '/models', name: 'models', title: '模型', icon: '◇', hint: '模型池与优先级' },
  { path: '/roles', name: 'roles', title: '角色', icon: '◈', hint: '角色提示词与模型绑定' },
  { path: '/executors', name: 'executors', title: '执行体', icon: '▣', hint: '执行体与启动命令' },
  { path: '/extensions', name: 'extensions', title: '拓展', icon: '⊞', hint: '技能与工具（MCP）' },
  { path: '/notifications', name: 'notifications', title: '消息', icon: '✉', hint: '邮件提醒与触发条件' },
  { path: '/approvals', name: 'approvals', title: '审批中心', icon: '⚖', hint: '红线操作与首次发信审批' },
  { path: '/cost', name: 'cost', title: '成本面板', icon: '◎', hint: 'Token 用量与三级预算' },
  { path: '/history', name: 'history', title: '历史', icon: '≡', hint: '历史任务：谁执行、谁审查、多久' },
] as const

/** 冻结的七项一级大纲（UI-02 契约，供回归断言使用） */
export const CORE_MENU = MENU.slice(0, 7)

const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/', redirect: '/overview' },
    { path: '/overview', component: () => import('@/pages/OverviewPage.vue') },
    { path: '/chat', component: () => import('@/pages/ChatPage.vue') },
    { path: '/models', component: () => import('@/pages/ModelsPage.vue') },
    { path: '/roles', component: () => import('@/pages/RolesPage.vue') },
    { path: '/executors', component: () => import('@/pages/ExecutorsPage.vue') },
    { path: '/extensions', component: () => import('@/pages/ExtensionsPage.vue') },
    { path: '/notifications', component: () => import('@/pages/NotificationsPage.vue') },
    { path: '/approvals', component: () => import('@/pages/ApprovalCenterPage.vue') },
    { path: '/cost', component: () => import('@/pages/CostPanelPage.vue') },
    { path: '/history', component: () => import('@/pages/HistoryPage.vue') },
    // Kernel 任务页（TASK-104，S1）：追加在治理页之后，不替换首页（U-06 默认不动）
    { path: '/tasks/new', component: () => import('@/pages/TasksNewPage.vue') },
    { path: '/tasks', component: () => import('@/pages/TasksBoardPage.vue') },
    { path: '/tasks/:todo_id/diff', component: () => import('@/pages/PlanDiffPage.vue') },
    // 首次运行向导（TASK-205/S2 + TASK-303/S3）：后端对 /api/setup/* 免会话仅回环
    { path: '/setup', component: () => import('@/pages/SetupPage.vue') },
    { path: '/:pathMatch(.*)*', redirect: '/overview' },
  ],
})

export default router
