/**
 * useProjectsStore · 项目 id → 名称映射（需求1 共用数据源）
 *
 * 背景：会话记录的是规范化 project_id（P-xxx），TopBar 下拉与进度栏标题都需要
 * 把 id 还原为可读的项目名。免会话端点 /api/projects/names 一次拉取、全局共享。
 */
import { computed, ref } from 'vue'
import { defineStore } from 'pinia'
import { api } from '@/api/client'

export interface ProjectNameItem {
  id: string
  name: string
}

export const useProjectsStore = defineStore('projects', () => {
  const list = ref<ProjectNameItem[]>([])
  const loading = ref(false)
  const loaded = ref(false)

  const nameById = computed(() => new Map(list.value.map((item) => [item.id, item.name])))

  function nameOf(id: string): string {
    return nameById.value.get(id) || ''
  }

  async function load(force = false): Promise<void> {
    if (loaded.value && !force) return
    loading.value = true
    try {
      const result = await api.listProjectNames()
      list.value = result.projects ?? []
      loaded.value = true
    } catch {
      /* 拉不到就维持旧列表，不影响当前项目展示 */
    } finally {
      loading.value = false
    }
  }

  return { list, loading, loaded, nameOf, load }
})
