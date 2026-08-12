/** Axios HTTP 客户端封装 */
import axios from 'axios'
import type {
  InitResponse,
  TaskSchema,
  OkResponse,
  StartTaskResponse,
  RunningTasksResponse,
  HeroImportBatchResponse,
} from '@/types'

const client = axios.create({
  baseURL: '/api',
  timeout: 10000,
  headers: { 'Content-Type': 'application/json' },
})

export const api = {
  /** 初始化数据 */
  async getInit(): Promise<InitResponse> {
    const { data } = await client.get<InitResponse>('/init')
    return data
  },

  /** 获取任务 schema */
  async getSchema(taskId: string): Promise<TaskSchema> {
    const { data } = await client.get<TaskSchema>(`/schema/${taskId}`)
    return data
  },

  /** 保存用户配置 */
  async saveConfig(configs: Record<string, any>): Promise<OkResponse> {
    const { data } = await client.post<OkResponse>('/save', { configs })
    return data
  },

  /** 启动任务 */
  async startTask(taskId: string): Promise<StartTaskResponse> {
    const { data } = await client.post<StartTaskResponse>(`/start/${taskId}`)
    return data
  },

  /** 获取运行中任务 */
  async getRunning(): Promise<RunningTasksResponse> {
    const { data } = await client.get<RunningTasksResponse>('/running')
    return data
  },

  /** 导出英雄配置 */
  async exportHero(heroId: string): Promise<string> {
    const { data } = await client.get<string>(`/hero_export/${heroId}`, {
      responseType: 'text',
    })
    return data
  },

  /** 保存英雄物品栏 */
  async saveHeroInventory(heroId: string, inventory: any[]): Promise<OkResponse> {
    const { data } = await client.post<OkResponse>('/save_hero_inventory', {
      hero_id: heroId,
      inventory,
    })
    return data
  },

  /** 批量导入英雄配置 */
  async importHeroBatch(heroes: { hero_id: string; content: string }[]): Promise<HeroImportBatchResponse> {
    const { data } = await client.post<HeroImportBatchResponse>('/hero_import_batch', { heroes })
    return data
  },
}
