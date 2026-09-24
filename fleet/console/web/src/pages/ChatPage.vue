<script setup lang="ts">
/**
 * ChatPage · 对话
 * 与 Manager 实时交流。缺陷修复：对话历史**不截断**——全量保留，首屏只渲染最新一页，
 * 向上滚动按需续载更早一页；新消息自动滚到底部；Manager 回执带打字机流式效果。
 * 发送优先走 WS（chat），不可用时降级 REST（服务端同样写入事件流）。
 *
 * UI-03R §9.6：新增 `stream_chunk` 增量渲染。本页在事件气泡之外单独维护一个
 * **实时增量气泡**，逐帧追加 delta；收到完整 chat_reply 事件后自动清空（避免重复）。
 * P1-A-3 后服务端通过 dispatcher._run_with_chain 产出 stream_chunk 事件。
 *
 * P2-B-1：消息列表改用 vue-virtual-scroller（DynamicScroller，变高行自动测量），
 * 只渲染可视区 ± 缓冲区的气泡——500+ 条历史滚动时 DOM 节点数 < 50、FPS > 30。
 * older 按钮与 live 流气泡作为 stream 区固定栏保留在 scroller 之外，
 * data-testid（inject-stream / stream-live / stream-text / stream-meta）全部保留。
 */
import { computed, nextTick, onMounted, ref, watch } from 'vue'
import { DynamicScroller, DynamicScrollerItem } from 'vue-virtual-scroller'
import 'vue-virtual-scroller/dist/vue-virtual-scroller.css'
import ChatBubble from '@/components/ChatBubble.vue'
import StreamText from '@/components/StreamText.vue'
import { useAuthStore } from '@/stores/auth'
import { useChatStore } from '@/stores/chat'
import { useExecutionStore } from '@/stores/execution'
import { usePlanStore } from '@/stores/plan'
import { useConnectionStore } from '@/stores/connection'
import { useWebSocket } from '@/composables/useWebSocket'
import { toast } from '@/composables/useToast'

const auth = useAuthStore()
const plan = usePlanStore()
const execution = useExecutionStore()
const chat = useChatStore()
const connection = useConnectionStore()
const ws = useWebSocket()

const draft = ref('')
/** DynamicScroller 是函数式泛型组件，不能用 InstanceType；只声明用到的暴露方法 */
const scrollerRef = ref<{ scrollToItem: (index: number, align?: 'start' | 'center' | 'end' | 'auto') => void } | null>(null)
const streamingSeq = ref<number | null>(null)

const messages = computed(() => chat.messages)
const liveStream = computed(() => chat.stream)

function roleOf(action: string): 'user' | 'manager' {
  return action === 'chat' ? 'user' : 'manager'
}

async function scrollToBottom(): Promise<void> {
  await nextTick()
  const last = messages.value.length - 1
  if (last >= 0) scrollerRef.value?.scrollToItem(last, 'end')
}

function loadOlder(): void {
  const prevLen = messages.value.length
  chat.loadOlder()
  void nextTick(() => {
    // 在头部 prepend 了约 pageSize 条；原首条现位于 index=delta，钉在视口顶
    // 保持用户停留在先前阅读位置，新载入的历史可向上滚查看
    const delta = messages.value.length - prevLen
    if (delta > 0) scrollerRef.value?.scrollToItem(delta, 'start')
    else scrollerRef.value?.scrollToItem(0, 'start')
  })
}

async function send(): Promise<void> {
  const text = draft.value.trim()
  if (!text) {
    toast.warn('请输入内容')
    return
  }
  draft.value = ''
  const ok = await chat.send(auth.project || undefined, text, ws.send)
  if (!ok) {
    toast.fail('发送失败', chat.lastError)
    draft.value = text
    return
  }
  void scrollToBottom()
}

function onKeydown(event: KeyboardEvent): void {
  if (event.key === 'Enter' && !event.shiftKey) {
    event.preventDefault()
    void send()
  }
}

/** 供 e2e/调试：把一串文本按帧注入 stream_chunk（走与真实 WS 相同的处理路径） */
function injectProbe(): void {
  ws.injectStream(['【Manager', '·流式', '回执】', '增量帧', '已到达。'], true)
  void scrollToBottom()
}

// 新消息到达 → 滚到底；Manager 回执 → 触发流式动画
watch(
  () => chat.messages.length,
  (next, prev) => {
    const latest = chat.messages[chat.messages.length - 1]
    if (latest && latest.action === 'chat_reply' && next > (prev ?? 0)) {
      streamingSeq.value = latest.seq
      // 对话启动新项目 → 会话与看板切换到新项目（服务端已切 session）
      const nextProject = String(
        (latest as unknown as { extra?: { new_project?: string } })?.extra?.new_project ?? '',
      )
      if (nextProject && nextProject !== auth.project) {
        auth.apply(auth.token, nextProject, auth.expiresIn)
        execution.clear()
        void plan.load(nextProject)
        toast.ok(`已切换到项目 ${nextProject}`)
      }
    }
    void scrollToBottom()
  },
)

// 增量帧到达 → 保持贴底
watch(
  () => chat.stream.chunks,
  () => {
    void scrollToBottom()
  },
)

onMounted(scrollToBottom)
</script>

<template>
  <section class="page chat-page">
    <header class="page-head">
      <div class="page-title">
        <h2>对话</h2>
        <span class="page-sub">与 Manager 实时交流 · 历史全量保留（虚拟滚动，不截断）</span>
      </div>
      <div class="row">
        <button class="btn btn-ghost" type="button" data-testid="inject-stream" @click="injectProbe">
          注入 stream_chunk
        </button>
        <span class="chip" :class="`tone-${connection.tone}`">
          <i class="dot" />
          {{ connection.label }}
        </span>
      </div>
    </header>

    <div class="stream">
      <div v-if="chat.hasOlder" class="older">
        <button class="btn btn-ghost" type="button" @click="loadOlder">
          载入更早的 {{ Math.min(chat.pageSize, chat.total - chat.visibleCount) }} 条（共 {{ chat.total }} 条）
        </button>
      </div>

      <p v-if="!messages.length" class="empty">
        暂无对话。输入指令后 Manager 会在此回执；事件流中的 chat / chat_reply 都会实时同步到这里。
      </p>

      <DynamicScroller
        v-else
        ref="scrollerRef"
        class="messages"
        :items="messages"
        :min-item-size="72"
        key-field="seq"
      >
        <template #default="{ item, index, active }">
          <DynamicScrollerItem :item="item" :index="index" :active="active">
            <ChatBubble
              :role="roleOf(String(item.action))"
              :time="item.timestamp"
              :streaming="item.seq === streamingSeq"
            >
              <StreamText
                v-if="item.seq === streamingSeq"
                :text="String(item.summary)"
                :speed="16"
                @done="streamingSeq = null"
              />
              <template v-else>{{ item.summary }}</template>
            </ChatBubble>
          </DynamicScrollerItem>
        </template>
      </DynamicScroller>

      <!-- 增量流气泡（stream_chunk）——固定在列表下方，不参与回收 -->
      <div v-if="chat.streaming" class="live" data-testid="stream-live">
        <ChatBubble role="manager" :time="liveStream.lastAt" :streaming="liveStream.active">
          <span class="live-text" data-testid="stream-text">{{ liveStream.text }}</span>
        </ChatBubble>
        <div class="live-meta tiny muted" data-testid="stream-meta">
          stream_chunk 来源：
          <b>{{ liveStream.source === 'server' ? '服务端推送' : '注入（后端尚未产出，INT-04 REWORK）' }}</b>
          · 已收 {{ liveStream.chunks }} 帧
          <template v-if="liveStream.messageId"> · 消息 {{ liveStream.messageId }}</template>
        </div>
      </div>
    </div>

    <div class="composer">
      <textarea
        v-model="draft"
        class="control"
        rows="2"
        placeholder="输入给 Manager 的指令…（Enter 发送 / Shift+Enter 换行）"
        @keydown="onKeydown"
      />
      <div class="composer-side">
        <span class="hint">共 {{ chat.total }} 条 · 已渲染 {{ messages.length }}</span>
        <button class="btn btn-primary" type="button" :disabled="chat.sending" @click="send">
          {{ chat.sending ? '发送中…' : '发送' }}
        </button>
      </div>
    </div>

    <p v-if="chat.lastError" class="err-text">{{ chat.lastError }}</p>
  </section>
</template>

<style scoped>
.chat-page {
  height: 100%;
  min-height: 0;
  padding-bottom: 18px;
}

/* stream 不再自滚动：DynamicScroller 消息区独占滚动，older/live 为固定栏 */
.stream {
  flex: 1;
  min-height: 0;
  display: flex;
  flex-direction: column;
  gap: 12px;
  padding: 14px;
  border: 1px solid var(--line);
  border-radius: var(--radius);
  background: var(--bg-panel);
}

.messages {
  flex: 1;
  min-height: 0;
  /* DynamicScroller 自带滚动容器；此处只保证撑满剩余高度 */
}

.messages :deep(.bubble) {
  /* 回收视图复用时气泡上下留出原 stream 的 gap 观感 */
  margin-bottom: 12px;
}

.older {
  display: flex;
  justify-content: center;
  padding-bottom: 4px;
}

.live {
  display: flex;
  flex-direction: column;
  gap: 4px;
  flex-shrink: 0;
}

.live-text {
  white-space: pre-wrap;
  word-break: break-word;
}

.live-meta {
  padding-left: 2px;
}

.live-meta b {
  color: var(--warn);
  font-weight: 600;
}

.composer {
  display: flex;
  flex-direction: column;
  gap: 8px;
  border: 1px solid var(--line-strong);
  border-radius: var(--radius);
  background: var(--bg-panel-2);
  padding: 10px 12px;
}

.composer .control {
  width: 100%;
  border: 0;
  background: transparent;
  color: var(--text);
  resize: none;
  outline: none;
  font-size: 13px;
  line-height: 1.6;
}

.composer-side {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}

.chip {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 3px 9px;
  border-radius: 999px;
  border: 1px solid transparent;
  font-size: 12px;
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
</style>
