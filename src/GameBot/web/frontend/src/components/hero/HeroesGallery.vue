<script setup lang="ts">
import { ref, computed, watch, onUnmounted } from 'vue'
import { ElMessageBox } from 'element-plus'
import type { HeroInfo, ItemDef } from '@/types'
import { useHeroStore } from '@/stores/hero'
import { useToast } from '@/composables/useToast'
import InventoryGrid from '@/components/form/InventoryGrid.vue'
import ExportModal from './ExportModal.vue'

const props = defineProps<{
  heroes: HeroInfo[]
  items: ItemDef[]
}>()

const emit = defineEmits<{
  refresh: []
}>()

const heroStore = useHeroStore()
const { showToast } = useToast()

const filter = ref<'all' | 'P' | 'O'>('all')
const heroInventory = ref<Record<string, any[]>>({})
const exportModalShow = ref(false)
const fileInput = ref<HTMLInputElement | null>(null)

// 逐步加载：每隔一小段时间多渲染一张卡片
const renderCount = ref(0)
let loadTimer: ReturnType<typeof setTimeout> | null = null

function startProgressiveLoad(total: number) {
  if (loadTimer) { clearTimeout(loadTimer); loadTimer = null }
  renderCount.value = 0
  if (total === 0) return
  const step = () => {
    if (renderCount.value >= total) { loadTimer = null; return }
    renderCount.value++
    loadTimer = setTimeout(step, 50)
  }
  step()
}

onUnmounted(() => {
  if (loadTimer) { clearTimeout(loadTimer); loadTimer = null }
})

const filteredHeroes = computed(() => {
  const list = filter.value === 'all' ? props.heroes : props.heroes.filter(h => (h.floor_key || 'P') === filter.value)
  return heroStore.sortHeroes(list)
})

watch(filteredHeroes, (list) => {
  startProgressiveLoad(list.length)
}, { immediate: true })

watch(() => props.heroes, (newHeroes) => {
  const map: Record<string, any[]> = {}
  for (const h of newHeroes) {
    map[h.id] = heroStore.buildInventorySlots(h.inventory)
  }
  heroInventory.value = map
}, { immediate: true })

function updateInventory(heroId: string, value: any[]) {
  heroInventory.value = { ...heroInventory.value, [heroId]: value }
}

async function resetInventory(heroId: string) {
  const hero = props.heroes.find(h => h.id === heroId)
  if (!hero) return
  try {
    await ElMessageBox.confirm(
      `确认恢复 ${hero.name || hero.id} 的默认物品栏？`,
      '提示',
      { confirmButtonText: '确认', cancelButtonText: '取消', type: 'warning' }
    )
  } catch {
    return
  }
  heroInventory.value = { ...heroInventory.value, [heroId]: heroStore.buildInventorySlots(hero.inventory) }
  showToast('已恢复默认物品栏', 'success')
}

async function saveHeroInventory(heroId: string) {
  const result = await heroStore.saveHeroInventory(heroId, heroInventory.value[heroId] || [])
  if (result.ok) {
    showToast('英雄默认物品栏已保存', 'success')
  } else {
    showToast('保存失败：' + result.error, 'error')
  }
}

async function handleFileImport(event: Event) {
  const input = event.target as HTMLInputElement
  const files = Array.from(input.files || [])
  input.value = ''
  if (files.length === 0) return
  const result = await heroStore.importHeroes(files)
  if (result.ok) {
    showToast('已导入 ' + (result.saved?.length || 0) + ' 个英雄配置', 'success')
    emit('refresh')
  } else {
    const msg = result.errors && result.errors.length ? result.errors.join('; ') : result.error
    showToast('部分导入失败：' + msg, 'error')
    if (result.saved && result.saved.length > 0) emit('refresh')
  }
}
</script>

<template>
  <div>
    <div class="flex gap-3 mb-4 items-center">
      <el-button
        v-for="f in ['all', 'P', 'O']"
        :key="f"
        :class="['btn-header', { active: filter === f }]"
        @click="filter = f as 'all' | 'P' | 'O'"
      >
        {{ f === 'all' ? '全部' : f === 'P' ? '一楼' : '二楼' }}
      </el-button>
      <span class="flex-1"></span>
      <el-button class="btn-header" @click="fileInput?.click()">导入配置</el-button>
      <el-button class="btn-header" @click="exportModalShow = true">导出配置</el-button>
    </div>

    <div class="hero-gallery-grid">
      <div v-for="(h, idx) in filteredHeroes" :key="h.id" class="hero-gallery-card">
        <div class="text-center font-bold text-text mb-2">{{ h.name }}</div>
        <div v-if="idx < renderCount" class="hero-card-body">
          <InventoryGrid
            :model-value="heroInventory[h.id]"
            @update:model-value="updateInventory(h.id, $event)"
            :items="items"
          />
          <div class="flex justify-center gap-3 mt-3">
            <el-button class="btn-header" @click="resetInventory(h.id)">恢复默认</el-button>
            <el-button class="btn-header" @click="saveHeroInventory(h.id)">保存配置</el-button>
          </div>
        </div>
        <div v-else class="hero-card-placeholder"></div>
      </div>
    </div>

    <input ref="fileInput" type="file" accept=".toml,text/plain" class="hidden" multiple @change="handleFileImport">
    <ExportModal
      :show="exportModalShow"
      :heroes="heroes"
      @close="exportModalShow = false"
      @exported="(ok: number, fail: number) => {
        if (fail === 0) showToast('已导出 ' + ok + ' 个英雄配置', 'success')
        else showToast('导出完成：成功 ' + ok + ' 个，失败 ' + fail + ' 个', 'error')
      }"
    />
  </div>
</template>
