/** 用户配置状态管理 */
import { defineStore } from 'pinia'
import { ref } from 'vue'
import { api } from '@/api/client'

export const useConfigStore = defineStore('config', () => {
  const configs = ref<Record<string, any>>({})
  const loading = ref(true)

  function setConfigs(data: Record<string, any>) {
    configs.value = data
  }

  async function saveAll(): Promise<{ ok: boolean; error?: string }> {
    try {
      const result = await api.saveConfig(configs.value)
      return result
    } catch (e: any) {
      return { ok: false, error: e.message }
    }
  }

  return {
    configs,
    loading,
    setConfigs,
    saveAll,
  }
})
