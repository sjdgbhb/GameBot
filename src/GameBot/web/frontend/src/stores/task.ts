/** 任务状态管理 */
import { defineStore } from 'pinia'
import { ref, computed, reactive } from 'vue'
import { api } from '@/api/client'
import type { TaskInfo, TaskSchema, TaskGroup, RunningTask } from '@/types'

// 任务分组定义（按展示顺序）
const groupDefs: { key: string; label: string; icon?: string; taskOrder?: string[] }[] = [
  { key: 'achievements', label: '成就任务' },
  { key: 'atomic', label: '原子任务' },
  { key: 'reputation', label: '声望任务', taskOrder: ['daily_reputation'] },
  { key: 'endless', label: '无尽任务', icon: '∞', taskOrder: ['endless_single', 'endless'] },
  { key: 'others', label: '其他任务', icon: '📦' },
]

export const useTaskStore = defineStore('task', () => {
  const tasks = ref<TaskInfo[]>([])
  const schemas = reactive<Record<string, TaskSchema | null>>({})
  const runningTasks = reactive<Record<string, number>>({})

  const taskGroups = computed<TaskGroup[]>(() => {
    const groups: Record<string, TaskInfo[]> = {}
    for (const t of tasks.value) {
      const cat = t.category || 'others'
      if (!groups[cat]) groups[cat] = []
      groups[cat].push(t)
    }
    const result: TaskGroup[] = []
    for (const def of groupDefs) {
      const list = groups[def.key]
      if (!list) continue
      const order = def.taskOrder
      if (order) {
        const orderMap = new Map(order.map((id, i) => [id, i]))
        list.sort((a, b) => {
          const ai = orderMap.get(a.short_id)
          const bi = orderMap.get(b.short_id)
          if (ai !== undefined && bi !== undefined) return ai - bi
          if (ai !== undefined) return -1
          if (bi !== undefined) return 1
          return a.name.localeCompare(b.name, 'zh-CN')
        })
      } else {
        list.sort((a, b) => a.name.localeCompare(b.name, 'zh-CN'))
      }
      result.push({ key: def.key, label: def.label, icon: def.icon, tasks: list })
    }
    return result
  })

  async function loadSchema(taskId: string, force = false): Promise<void> {
    if (!taskId) return
    if (!force && schemas[taskId] !== undefined) return
    try {
      schemas[taskId] = await api.getSchema(taskId)
    } catch {
      schemas[taskId] = null
    }
  }

  async function startTask(taskId: string): Promise<{ ok: boolean; pid?: number; error?: string }> {
    try {
      const result = await api.startTask(taskId)
      if (result.ok) {
        runningTasks[taskId] = result.pid!
      } else if (result.running) {
        runningTasks[taskId] = result.pid!
      }
      return result
    } catch (e: any) {
      return { ok: false, error: e.message }
    }
  }

  async function fetchRunning(): Promise<void> {
    try {
      const data = await api.getRunning()
      for (const k of Object.keys(runningTasks)) delete runningTasks[k]
      for (const t of data.tasks) runningTasks[t.id] = t.pid
    } catch {
      // 状态获取失败不影响主界面
    }
  }

  function isRunning(taskId: string): boolean {
    return !!runningTasks[taskId]
  }

  return {
    tasks,
    schemas,
    runningTasks,
    taskGroups,
    loadSchema,
    startTask,
    fetchRunning,
    isRunning,
  }
})
