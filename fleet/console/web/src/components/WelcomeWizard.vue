<script setup lang="ts">
/**
 * WelcomeWizard · 零基础欢迎向导
 *
 * 三步流程（用户只需点击 + 输入产品想法）：
 * 1. 环境自检——自动检测 Python/Node/CLI/API Key，缺什么显示安装按钮
 * 2. 输入想法——"你想做什么产品？"（唯一需要打字的地方）
 * 3. 确认启动——显示生成的计划摘要，点"开始开发"即解锁进入控制台
 */
import { onMounted, ref, computed } from 'vue'
import CodeBackground from '@/components/CodeBackground.vue'
import { api, setAuthToken } from '@/api/client'
import { useAuthStore } from '@/stores/auth'
import { toast } from '@/composables/useToast'

const auth = useAuthStore()

type QuickstartStatus = {
  has_python: boolean
  has_node: boolean
  has_npm: boolean
  has_git: boolean
  has_cli: boolean
  installed_clis: string[]
  has_api_key: boolean
  has_project: boolean
  projects_count: number
  frontend_built: boolean
  ready: boolean
}

const step = ref(1) // 1=环境检查, 2=输入想法, 3=确认启动
const status = ref<QuickstartStatus | null>(null)
const checking = ref(true)
const description = ref('')
const creating = ref(false)
const createdProject = ref<{ name: string; stages: number; tasks: number } | null>(null)

const envItems = computed(() => {
  if (!status.value) return []
  const s = status.value
  return [
    { label: 'Python 运行时', ok: s.has_python, hint: '核心依赖' },
    { label: 'Node.js', ok: s.has_node, hint: '前端构建 + CLI 安装' },
    { label: 'npm 包管理', ok: s.has_npm, hint: '安装 AI 编程助手' },
    { label: 'Git', ok: s.has_git, hint: '代码版本管理' },
    { label: 'AI 编程助手', ok: s.has_cli, hint: s.installed_clis.length ? `已装: ${s.installed_clis.join(', ')}` : '可选：控制台也能直接用' },
    { label: '模型 API Key', ok: s.has_api_key, hint: '让 AI 执行任务' },
  ]
})

const envAllReady = computed(() => {
  if (!status.value) return false
  return status.value.has_python && status.value.frontend_built
})

async function checkEnv() {
  checking.value = true
  try {
    const res = await api.quickstartStatus()
    status.value = res
  } catch {
    status.value = null
  } finally {
    checking.value = false
  }
}

function goToStep2() {
  step.value = 2
}

async function generatePlan() {
  if (!description.value.trim() || description.value.trim().length < 3) {
    toast.warn('请描述你想做的产品（至少 3 个字）')
    return
  }
  creating.value = true
  try {
    const res = await api.quickstartCreate(description.value.trim())
    // 写入 auth store
    auth.apply(res.token, res.project, res.expires_in)
    createdProject.value = {
      name: res.project_name,
      stages: res.plan?.stages ?? 0,
      tasks: res.plan?.tasks ?? 0,
    }
    step.value = 3
  } catch (error) {
    toast.fail('创建失败', error instanceof Error ? error.message : '请重试')
  } finally {
    creating.value = false
  }
}

function enterConsole() {
  // 触发解锁后的初始化（App.vue 的 watch 会接管）
  // 刷新页面让 App.vue 重新走 afterUnlock 流程
  window.location.href = '/'
}

const examples = [
  '开发一个待办事项网页应用，能添加、删除、标记完成',
  '帮我做一个在线聊天室，支持多人群聊',
  '我想做一个个人博客网站，能写文章和标签管理',
  '搭建一个数据看板，展示销售数据的图表',
]

function useExample(text: string) {
  description.value = text
}

onMounted(checkEnv)
</script>

<template>
  <div class="wizard">
    <CodeBackground class="bg" />
    <div class="panel">
      <!-- 品牌头 -->
      <div class="brand">
        <span class="mark">◈</span>
        <h1>AideanFleet</h1>
        <span class="subtitle">AI 帮你开发产品</span>
      </div>

      <!-- 步骤指示器 -->
      <div class="steps-bar">
        <div class="step-dot" :class="{ active: step >= 1, done: step > 1 }">1</div>
        <div class="step-line" :class="{ done: step > 1 }" />
        <div class="step-dot" :class="{ active: step >= 2, done: step > 2 }">2</div>
        <div class="step-line" :class="{ done: step > 2 }" />
        <div class="step-dot" :class="{ active: step >= 3 }">3</div>
      </div>

      <!-- 步骤 1：环境自检 -->
      <div v-if="step === 1" class="step-content">
        <h2>检查运行环境</h2>
        <p class="step-hint">正在自动检测你的电脑环境…</p>

        <div v-if="checking" class="checking">
          <span class="spinner" />
          <span>检测中…</span>
        </div>

        <div v-else class="env-list">
          <div v-for="item in envItems" :key="item.label" class="env-item">
            <span class="env-icon" :class="item.ok ? 'ok' : 'warn'">
              {{ item.ok ? '✓' : '○' }}
            </span>
            <span class="env-label">{{ item.label }}</span>
            <span class="env-hint">{{ item.hint }}</span>
          </div>
        </div>

        <div v-if="!checking && status && !status.has_api_key" class="env-warning">
          <p>⚠ 未检测到模型 API Key。你仍可进入控制台，但 AI 执行任务需要配置密钥。</p>
          <p class="muted">进入控制台后，在「安装向导」页面配置。</p>
        </div>

        <button
          v-if="!checking"
          class="btn btn-primary btn-block"
          @click="goToStep2"
        >
          下一步 →
        </button>

        <button v-if="!checking" class="btn btn-text btn-block" @click="checkEnv">
          重新检测
        </button>
      </div>

      <!-- 步骤 2：输入产品想法 -->
      <div v-if="step === 2" class="step-content">
        <h2>你想做什么产品？</h2>
        <p class="step-hint">用一句话描述你的想法，AI 会自动规划开发任务</p>

        <textarea
          v-model="description"
          class="desc-input"
          placeholder="例如：开发一个待办事项网页应用，能添加、删除、标记完成"
          rows="3"
          autocomplete="off"
          spellcheck="false"
          @keydown.ctrl.enter="generatePlan"
        />

        <div class="examples">
          <p class="examples-title">没想法？试试这些：</p>
          <div class="example-chips">
            <button
              v-for="ex in examples"
              :key="ex"
              class="example-chip"
              type="button"
              @click="useExample(ex)"
            >
              {{ ex.slice(0, 20) }}…
            </button>
          </div>
        </div>

        <button
          class="btn btn-primary btn-block"
          :disabled="creating || !description.trim()"
          @click="generatePlan"
        >
          {{ creating ? '正在生成计划…' : '生成开发计划' }}
        </button>

        <button class="btn btn-text btn-block" @click="step = 1">
          ← 上一步
        </button>
      </div>

      <!-- 步骤 3：确认启动 -->
      <div v-if="step === 3" class="step-content">
        <h2>计划已就绪！</h2>

        <div v-if="createdProject" class="plan-summary">
          <div class="summary-item">
            <span class="summary-label">项目名称</span>
            <span class="summary-value">{{ createdProject.name }}</span>
          </div>
          <div class="summary-item">
            <span class="summary-label">开发阶段</span>
            <span class="summary-value">{{ createdProject.stages }} 个阶段</span>
          </div>
          <div class="summary-item">
            <span class="summary-label">任务总数</span>
            <span class="summary-value">{{ createdProject.tasks }} 个任务</span>
          </div>
        </div>

        <p class="step-hint">
          AI 将自动开始执行任务。你可以在控制台查看进度、确认关键步骤。
        </p>

        <button class="btn btn-primary btn-block" @click="enterConsole">
          🚀 开始开发
        </button>
      </div>
    </div>
  </div>
</template>

<style scoped>
.wizard {
  position: relative;
  height: 100%;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 24px;
  overflow: hidden;
}

.bg { opacity: 0.9; }

.panel {
  position: relative;
  z-index: 1;
  width: 480px;
  max-width: 100%;
  max-height: 90vh;
  overflow-y: auto;
  padding: 32px;
  border-radius: var(--radius-lg);
  border: 1px solid var(--line-strong);
  background: var(--bg-panel);
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.brand {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
}

.mark {
  width: 36px;
  height: 36px;
  display: grid;
  place-items: center;
  border-radius: var(--radius);
  border: 1px solid var(--line-accent);
  background: var(--accent-cyan-dim);
  color: var(--accent-cyan);
  font-size: 18px;
}

.brand h1 { font-size: 18px; margin: 0; }
.subtitle { font-size: 12px; color: var(--text-dim); }

/* 步骤指示器 */
.steps-bar {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 0;
  margin: 4px 0 8px;
}

.step-dot {
  width: 28px;
  height: 28px;
  border-radius: 50%;
  display: grid;
  place-items: center;
  font-size: 13px;
  font-weight: 600;
  border: 2px solid var(--line-strong);
  color: var(--text-dim);
  background: var(--bg-panel-2);
  transition: all 0.2s;
}

.step-dot.active {
  border-color: var(--accent-cyan);
  color: var(--accent-cyan);
}

.step-dot.done {
  background: var(--accent-cyan);
  border-color: var(--accent-cyan);
  color: var(--bg-base);
}

.step-line {
  width: 40px;
  height: 2px;
  background: var(--line-strong);
  transition: background 0.2s;
}

.step-line.done { background: var(--accent-cyan); }

/* 步骤内容 */
.step-content {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.step-content h2 {
  font-size: 16px;
  margin: 0;
}

.step-hint {
  font-size: 13px;
  color: var(--text-dim);
  margin: 0;
}

.checking {
  display: flex;
  align-items: center;
  gap: 8px;
  color: var(--text-dim);
  padding: 12px 0;
}

.spinner {
  width: 16px;
  height: 16px;
  border-radius: 50%;
  border: 2px solid var(--line-strong);
  border-top-color: var(--accent-cyan);
  animation: spin 0.8s linear infinite;
}

@keyframes spin { to { transform: rotate(360deg); } }

/* 环境列表 */
.env-list {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.env-item {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 6px 8px;
  border-radius: var(--radius-sm);
  background: var(--bg-panel-2);
}

.env-icon {
  width: 20px;
  height: 20px;
  display: grid;
  place-items: center;
  border-radius: 50%;
  font-size: 12px;
  font-weight: 600;
}

.env-icon.ok {
  background: rgba(34, 197, 94, 0.15);
  color: #22c55e;
}

.env-icon.warn {
  background: rgba(234, 179, 8, 0.15);
  color: #eab308;
}

.env-label { font-size: 13px; }
.env-hint { font-size: 11px; color: var(--text-dim); margin-left: auto; }

.env-warning {
  padding: 10px 12px;
  border-radius: var(--radius-sm);
  background: rgba(234, 179, 8, 0.08);
  border: 1px solid rgba(234, 179, 8, 0.2);
  font-size: 12px;
}

.env-warning .muted { color: var(--text-dim); margin-top: 4px; }

/* 输入框 */
.desc-input {
  width: 100%;
  padding: 12px;
  border-radius: var(--radius-sm);
  border: 1px solid var(--line-strong);
  background: var(--bg-input);
  color: var(--text);
  font-size: 14px;
  resize: vertical;
  min-height: 72px;
  font-family: inherit;
}

.desc-input:focus {
  outline: none;
  border-color: var(--accent-cyan);
}

/* 示例 */
.examples { margin-top: 4px; }

.examples-title {
  font-size: 12px;
  color: var(--text-dim);
  margin: 0 0 6px;
}

.example-chips {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

.example-chip {
  padding: 4px 10px;
  border-radius: 999px;
  border: 1px solid var(--line-strong);
  background: var(--bg-panel-2);
  color: var(--text-dim);
  font-size: 11px;
  cursor: pointer;
}

.example-chip:hover {
  border-color: var(--line-accent);
  color: var(--accent-cyan);
}

/* 计划摘要 */
.plan-summary {
  display: flex;
  flex-direction: column;
  gap: 8px;
  padding: 16px;
  border-radius: var(--radius);
  background: var(--bg-panel-2);
  border: 1px solid var(--line);
}

.summary-item {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.summary-label { font-size: 13px; color: var(--text-dim); }
.summary-value { font-size: 14px; font-weight: 600; }

/* 按钮 */
.btn {
  padding: 10px 16px;
  border-radius: var(--radius-sm);
  border: 1px solid var(--line-strong);
  background: var(--bg-panel-2);
  color: var(--text);
  font-size: 14px;
  cursor: pointer;
  transition: all 0.15s;
}

.btn:hover { border-color: var(--line-accent); }

.btn-primary {
  background: var(--accent-cyan);
  border-color: var(--accent-cyan);
  color: var(--bg-base);
  font-weight: 600;
}

.btn-primary:hover {
  opacity: 0.9;
}

.btn-primary:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.btn-text {
  border: none;
  background: transparent;
  color: var(--text-dim);
}

.btn-text:hover { color: var(--text); }

.btn-block { width: 100%; }
</style>
