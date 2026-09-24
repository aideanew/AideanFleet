<script setup lang="ts">
import { onMounted, ref } from 'vue'
import CodeBackground from '@/components/CodeBackground.vue'
import { useAuthStore } from '@/stores/auth'
import { api } from '@/api/client'
import { toast } from '@/composables/useToast'

const auth = useAuthStore()
const projectName = ref('')
const projects = ref<{ id: string; name: string }[]>([])
const submitting = ref(false)

async function loadProjects() {
  try {
    // 锁屏候选走免会话端点；拿不到也不影响手输项目名
    const result = await api.listProjectNames()
    projects.value = result.projects ?? []
    if (!projectName.value && projects.value.length) {
      projectName.value = projects.value[0].name
    }
  } catch {
    /* 未解锁时拿不到列表也不影响手输项目名 */
  }
}

async function submit() {
  if (submitting.value) return
  const name = projectName.value.trim()
  if (!name) {
    toast.warn('请输入项目名')
    return
  }
  submitting.value = true
  const ok = await auth.unlock(name)
  submitting.value = false
  if (ok) {
    toast.ok('已解锁')
  } else {
    toast.fail('解锁失败', auth.lastError)
  }
}

/** 点候选 chip 直接解锁（服务端按 id 或 name 解析项目身份） */
async function quickUnlock(name: string) {
  projectName.value = name
  await submit()
}

onMounted(loadProjects)
</script>

<template>
  <div class="lock">
    <CodeBackground class="bg" />
    <div class="panel">
      <div class="brand">
        <span class="mark">◈</span>
        <h1>AideanFleet</h1>
      </div>

      <input
        v-model="projectName"
        class="control"
        type="text"
        placeholder="项目名"
        autocomplete="off"
        spellcheck="false"
        @keydown.enter="submit"
      />

      <p v-if="auth.lastError" class="err-text">{{ auth.lastError }}</p>

      <button class="btn btn-primary btn-block" type="button" :disabled="submitting" @click="submit">
        {{ submitting ? '解锁中…' : '解锁控制台' }}
      </button>

      <div v-if="projects.length" class="candidates">
        <div class="chips">
          <button
            v-for="item in projects"
            :key="item.id"
            class="chip"
            type="button"
            @click="quickUnlock(item.name)"
          >
            {{ item.name }}
          </button>
        </div>
      </div>

    </div>
  </div>
</template>

<style scoped>
.lock {
  position: relative;
  height: 100%;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 24px;
  overflow: hidden;
}

.bg {
  opacity: 0.9;
}

.panel {
  position: relative;
  z-index: 1;
  width: 420px;
  max-width: 100%;
  padding: 28px;
  border-radius: var(--radius-lg);
  border: 1px solid var(--line-strong);
  background: var(--bg-panel);
  display: flex;
  flex-direction: column;
  gap: 14px;
}

.brand {
  display: flex;
  align-items: center;
  gap: 14px;
}

.mark {
  width: 42px;
  height: 42px;
  display: grid;
  place-items: center;
  border-radius: var(--radius);
  border: 1px solid var(--line-accent);
  background: var(--accent-cyan-dim);
  color: var(--accent-cyan);
  font-size: 20px;
}

.brand h1 {
  font-size: 17px;
}

.brand p {
  margin: 2px 0 0;
}

.control {
  width: 100%;
  padding: 10px 12px;
  border-radius: var(--radius-sm);
  border: 1px solid var(--line-strong);
  background: var(--bg-input);
  color: var(--text);
}

.control:focus {
  outline: none;
  border-color: var(--accent-cyan);
}

.candidates {
  border-top: 1px solid var(--line);
  padding-top: 12px;
}

.chips {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-top: 8px;
}

.chip {
  padding: 4px 10px;
  border-radius: 999px;
  border: 1px solid var(--line-strong);
  background: var(--bg-panel-2);
  color: var(--text-dim);
  font-size: 12px;
}

.chip:hover {
  border-color: var(--line-accent);
  color: var(--accent-cyan);
}

.foot {
  border-top: 1px solid var(--line);
  padding-top: 12px;
}
</style>
