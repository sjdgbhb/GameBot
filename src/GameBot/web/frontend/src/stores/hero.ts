/** 英雄状态管理 */
import { defineStore } from 'pinia'
import { ref } from 'vue'
import { api } from '@/api/client'
import type { HeroInfo, ItemDef, CommandDef } from '@/types'
import { pinyinCompare } from '@/utils/pinyin'

export const useHeroStore = defineStore('hero', () => {
  const heroes = ref<HeroInfo[]>([])
  const items = ref<ItemDef[]>([])
  const farmableItems = ref<string[]>([])
  const commands = ref<CommandDef[]>([])
  const petFoodId = ref(9)

  function setHeroes(list: HeroInfo[]) {
    heroes.value = list
  }

  function setItems(list: ItemDef[]) {
    items.value = list
    const petFood = list.find(it => it.name === '宠物食物')
    petFoodId.value = petFood ? petFood.id : 9
  }

  function setFarmableItems(list: string[]) {
    farmableItems.value = list
  }

  function setCommands(list: CommandDef[]) {
    commands.value = list
  }

  /** 排序英雄（按楼层和名称） */
  function sortHeroes(list: HeroInfo[]): HeroInfo[] {
    const floorOrder: Record<string, number> = { P: 1, O: 2 }
    return [...list].sort((a, b) => {
      const fa = floorOrder[a.floor_key || 'P'] || 99
      const fb = floorOrder[b.floor_key || 'P'] || 99
      if (fa !== fb) return fa - fb
      return pinyinCompare(a.name || String(a.id), b.name || String(b.id))
    })
  }

  /** 构建物品栏 6 格数组 */
  function buildInventorySlots(inv?: any[]): any[] {
    const arr: any[] = []
    for (let i = 0; i < 6; i++) arr.push({ slot: i, item_id: -1, hotkey: String(i + 1) })
    ;(inv || []).forEach((it: any) => {
      let slotIdx = -1
      if (it.slot != null) slotIdx = Number(it.slot)
      else if (it.hotkey != null) slotIdx = parseInt(it.hotkey, 10) - 1
      if (slotIdx >= 0 && slotIdx < 6) {
        const itemId = it.item_id != null ? it.item_id : it.id
        arr[slotIdx] = { slot: slotIdx, item_id: itemId, hotkey: it.hotkey || String(slotIdx + 1) }
      }
    })
    arr[5] = { slot: 5, item_id: 0, hotkey: arr[5].hotkey || '6' }
    return arr
  }

  async function saveHeroInventory(heroId: string, inventory: any[]): Promise<{ ok: boolean; error?: string }> {
    try {
      const result = await api.saveHeroInventory(heroId, inventory)
      return result
    } catch (e: any) {
      return { ok: false, error: e.message }
    }
  }

  async function exportHeroes(heroIds: string[]): Promise<{ ok: number; fail: number }> {
    let ok = 0, fail = 0
    for (const heroId of heroIds) {
      try {
        const content = await api.exportHero(heroId)
        const blob = new Blob([content], { type: 'text/plain;charset=utf-8' })
        const url = URL.createObjectURL(blob)
        const a = document.createElement('a')
        a.href = url
        a.download = heroId + '.toml'
        a.click()
        URL.revokeObjectURL(url)
        ok++
        await new Promise(r => setTimeout(r, 200))
      } catch {
        fail++
      }
    }
    return { ok, fail }
  }

  async function importHeroes(files: File[]): Promise<{ ok: boolean; saved?: string[]; errors?: string[]; error?: string }> {
    const heroes: { hero_id: string; content: string }[] = []
    for (const file of files) {
      const hid = file.name.replace(/\.toml$/i, '')
      try {
        const content = await file.text()
        heroes.push({ hero_id: hid, content })
      } catch (e: any) {
        return { ok: false, error: '读取文件 ' + file.name + ' 失败：' + e.message }
      }
    }
    if (heroes.length === 0) return { ok: false, error: '无有效文件' }
    try {
      const result = await api.importHeroBatch(heroes)
      return result
    } catch (e: any) {
      return { ok: false, error: e.message }
    }
  }

  return {
    heroes,
    items,
    farmableItems,
    commands,
    petFoodId,
    setHeroes,
    setItems,
    setFarmableItems,
    setCommands,
    sortHeroes,
    buildInventorySlots,
    saveHeroInventory,
    exportHeroes,
    importHeroes,
  }
})
