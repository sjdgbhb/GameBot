<script setup lang="ts">
import { ref, computed, watch } from 'vue'
import type { HeroInfo } from '@/types'
import { useHeroStore } from '@/stores/hero'

const props = defineProps<{
  show: boolean
  heroes: HeroInfo[]
}>()

const emit = defineEmits<{
  close: []
  exported: [ok: number, fail: number]
}>()

const heroStore = useHeroStore()
const selected = ref<Record<string, boolean>>({})
const allSelected = ref(true)

const groupedHeroes = computed(() => {
  const sorted = heroStore.sortHeroes(props.heroes)
  const floorOrder = ['P', 'O']
  const floorLabels: Record<string, string> = { P: '一楼', O: '二楼' }
  const groups: Record<string, HeroInfo[]> = {}
  for (const h of sorted) {
    const floor = h.floor_key || 'P'
    if (!groups[floor]) groups[floor] = []
    groups[floor].push(h)
  }
  return floorOrder
    .filter(floor => groups[floor])
    .map(floor => ({ floor, label: floorLabels[floor] || floor, heroes: groups[floor] }))
})

const selectedCount = computed(() => Object.values(selected.value).filter(v => v).length)

const selectedIds = computed({
  get: () => props.heroes.filter(h => selected.value[h.id]).map(h => h.id),
  set: (ids: string[]) => {
    const s: Record<string, boolean> = {}
    for (const h of props.heroes) s[h.id] = ids.includes(h.id)
    selected.value = s
    allSelected.value = ids.length === props.heroes.length
  },
})

watch(() => props.show, (show) => {
  if (show) {
    const s: Record<string, boolean> = {}
    for (const h of props.heroes) s[h.id] = true
    selected.value = s
    allSelected.value = true
  }
})

function toggleExportAll() {
  const val = !allSelected.value
  const s: Record<string, boolean> = {}
  for (const h of props.heroes) s[h.id] = val
  selected.value = s
  allSelected.value = val
}

function toggleExportHero(heroId: string) {
  selected.value = { ...selected.value, [heroId]: !selected.value[heroId] }
  allSelected.value = props.heroes.every(h => selected.value[h.id])
}

function updateSelectedFromGroup(ids: string[]) {
  const s: Record<string, boolean> = {}
  for (const h of props.heroes) s[h.id] = ids.includes(h.id)
  selected.value = s
  allSelected.value = ids.length === props.heroes.length
}

async function confirmExport() {
  const ids = props.heroes.filter(h => selected.value[h.id]).map(h => h.id)
  if (ids.length === 0) return
  emit('close')
  const result = await heroStore.exportHeroes(ids)
  emit('exported', result.ok, result.fail)
}
</script>

<template>
  <el-dialog
    :model-value="show"
    @update:model-value="(val: boolean) => { if (!val) emit('close') }"
    title="导出英雄配置"
    width="640px"
    :close-on-click-modal="true"
  >
    <div class="mb-4 flex items-center gap-4">
      <el-checkbox :model-value="allSelected" @change="toggleExportAll" size="small">全选</el-checkbox>
      <span class="text-sm text-text-dim">已选 {{ selectedCount }} / {{ heroes.length }}</span>
    </div>
    <div class="max-h-[400px] overflow-y-auto space-y-4 mb-4">
      <div v-for="grp in groupedHeroes" :key="grp.floor">
        <div class="mb-2">
          <el-tag type="warning" size="small">{{ grp.label }}</el-tag>
        </div>
        <el-checkbox-group v-model="selectedIds" size="small" class="flex flex-wrap gap-2">
          <el-checkbox-button
            v-for="h in grp.heroes"
            :key="h.id"
            :label="h.id"
            :value="h.id"
          >
            {{ h.name }}
          </el-checkbox-button>
        </el-checkbox-group>
      </div>
    </div>
    <template #footer>
      <div class="flex justify-end gap-3">
        <el-button @click="emit('close')">取消</el-button>
        <el-button type="primary" @click="confirmExport" :disabled="selectedCount === 0">
          导出 ({{ selectedCount }})
        </el-button>
      </div>
    </template>
  </el-dialog>
</template>
