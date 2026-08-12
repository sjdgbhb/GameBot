<script setup lang="ts">
import { ref, onMounted, onUnmounted, computed, watch, nextTick } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { VideoPlay, Loading } from '@element-plus/icons-vue'
import { useTaskStore } from '@/stores/task'
import { useHeroStore } from '@/stores/hero'
import { useConfigStore } from '@/stores/config'
import { api } from '@/api/client'
import { useToast } from '@/composables/useToast'
import Sidebar from '@/components/layout/Sidebar.vue'
import TopNav from '@/components/layout/TopNav.vue'

const router = useRouter()
const route = useRoute()
const taskStore = useTaskStore()
const heroStore = useHeroStore()
const configStore = useConfigStore()
const { showToast } = useToast()

const loading = ref(true)
const sidebarCollapsed = ref(false)

// 任务标签页（__heroes__ 为全部英雄的虚拟标签ID）
const openTabs = ref<string[]>([])

function toggleSidebar() {
  sidebarCollapsed.value = !sidebarCollapsed.value
}

// 当前模块和任务（从路由推导）
const currentModule = computed(() => {
  if (route.name === 'home') return 'home'
  if (route.name === 'heroes') return 'heroes'
  return 'tasks'
})
const currentTaskId = computed(() => {
  if (route.name !== 'task') return ''
  return (route.params.taskId as string) || ''
})

const currentTask = computed(() => {
  return taskStore.tasks.find(t => t.id === currentTaskId.value)
})

const pageTitle = computed(() => {
  if (currentModule.value === 'home') return '首页'
  if (currentModule.value === 'heroes') return '英雄列表'
  return currentTask.value?.name || ''
})

const pageDesc = computed(() => {
  if (currentModule.value === 'home') return '脚本使用说明'
  if (currentModule.value === 'heroes') return '英雄物品栏默认装备配置'
  return ''
})

const isTaskRunning = computed(() => taskStore.isRunning(currentTaskId.value))

// 当前任务数据
const currentData = ref<Record<string, any>>({})
const originalTaskData = ref<Record<string, any>>({})
let isLoadingTask = false
// 抑制 hero watcher：handleModeSwitch 已处理 points/inventory 恢复时无需 watcher 重复加载
let suppressHeroWatch = false

// 各标签页的未保存数据缓存（切换标签时保留修改）
const taskDataCache = ref<Record<string, { data: Record<string, any>, original: Record<string, any> }>>({})

// 会话级暂存：路线方案来回切换时恢复用户数据，避免被默认值覆盖导致“改回去仍提示未保存”
const schemeStash = ref<Record<string, Record<string, any[]>>>({})

// 用户从路线点卡片点击“添加物品栏章节”后动态追加的表单章节
const extraSections = ref<any[]>([])

const currentSchema = computed(() => taskStore.schemas[currentTaskId.value])

function hasInventoryFieldInSections(sections?: any[]): boolean {
  if (!sections) return false
  return sections.some(s => s.fields?.some((f: any) => f.type === 'inventory'))
}

function hasHeroFieldInSections(sections?: any[]): boolean {
  if (!sections) return false
  return sections.some(s => s.fields?.some((f: any) => f.type === 'hero'))
}

function onAddInventory() {
  const schemaHasInv = hasInventoryFieldInSections(currentSchema.value?.sections)
  const extraHasInv = hasInventoryFieldInSections(extraSections.value)
  if (schemaHasInv || extraHasInv) {
    showToast('已存在物品栏配置', 'info')
    return
  }
  // 初始化 inventory 为 6 个空格子，确保 InventoryGrid 能直接渲染
  if (!Array.isArray(currentData.value.inventory) || currentData.value.inventory.length === 0) {
    const empty: any[] = []
    for (let i = 0; i < 6; i++) {
      empty.push({ slot: i, id: -1, hotkey: String(i + 1) })
    }
    empty[5] = { slot: 5, id: 0, hotkey: '6' }
    currentData.value.inventory = empty
  }
  extraSections.value.push({
    key: 'inventory',
    title: '物品栏',
    help: '由路线点卡片动态添加的物品栏配置',
    fields: [{ key: 'inventory', label: '', type: 'inventory' }],
  })
}

function onAddHero() {
  const schemaHasHero = hasHeroFieldInSections(currentSchema.value?.sections)
  const extraHasHero = hasHeroFieldInSections(extraSections.value)
  if (schemaHasHero || extraHasHero) {
    showToast('已存在英雄选择配置，请直接选择英雄', 'info')
    return
  }
  extraSections.value.push({
    key: 'hero',
    title: '英雄选择',
    help: '由路线点卡片动态添加的英雄选择器',
    fields: [{ key: 'hero', label: '', type: 'hero' }],
  })
}

function switchTask(taskId: string) {
  router.push(`/task/${taskId}`)
}

function switchTab(tabId: string) {
  if (tabId === '__heroes__') { switchModule('heroes'); return }
  switchTask(tabId)
}

function closeTab(tabId: string) {
  const idx = openTabs.value.indexOf(tabId)
  if (idx === -1) return
  const isCurrent = tabId === '__heroes__' ? currentModule.value === 'heroes' : currentTaskId.value === tabId
  doCloseTab(tabId, idx, isCurrent)
}

// 关闭标签并清理缓存；如关闭的是当前标签则跳转到相邻标签
function doCloseTab(tabId: string, idx: number, navigate: boolean) {
  delete taskDataCache.value[tabId]
  const curIdx = openTabs.value.indexOf(tabId)
  if (curIdx !== -1) openTabs.value.splice(curIdx, 1)
  if (!navigate) return
  if (openTabs.value.length === 0) {
    router.push('/home')
    return
  }
  const nextIdx = Math.min(idx, openTabs.value.length - 1)
  const nextTabId = openTabs.value[nextIdx]
  if (nextTabId === '__heroes__') router.push('/heroes')
  else router.push(`/task/${nextTabId}`)
}

function switchModule(module: string) {
  if (module === 'home') { router.push('/home'); return }
  if (module === 'heroes') router.push('/heroes')
}

function shouldFillInventory(inv: any[]): boolean {
  if (!Array.isArray(inv) || inv.length === 0) return true
  return !inv.some(s => s.id > 0)
}

function buildInventorySlots(...sources: any[][]): any[] {
  const arr: any[] = []
  for (let i = 0; i < 6; i++) arr.push({ id: -1, hotkey: String(i + 1) })
  // 按优先级从低到高依次填充，高优先级覆盖相同格子
  for (const source of sources) {
    for (const hi of source) {
      let slotIdx = -1
      if (hi.slot != null) slotIdx = Number(hi.slot)
      else if (hi.hotkey != null) slotIdx = parseInt(hi.hotkey, 10) - 1
      if (slotIdx >= 0 && slotIdx <= 5) arr[slotIdx] = { id: hi.id, hotkey: hi.hotkey }
    }
  }
  arr[5] = { id: 0, hotkey: arr[5].hotkey || '6' }
  return arr
}

function applyHeroDefaults(heroId: string, force = false, clearOnNoHero = false) {
  if (!heroId) {
    if (clearOnNoHero) {
      // 未选英雄时仅用任务配置填充
      const taskDefaults = currentSchema.value?.defaults?.inventory || []
      currentData.value.inventory = buildInventorySlots(taskDefaults)
    }
    return
  }
  const inv = currentData.value.inventory || []
  if (!force && !shouldFillInventory(inv)) return
  const hero = heroStore.heroes.find(h => h.id === heroId)
  if (!hero) return
  // 优先级：任务配置(defaults.inventory) > 英雄配置(hero.inventory)
  // 高优先级覆盖相同格子，低优先级填充缺省
  const taskDefaults = currentSchema.value?.defaults?.inventory || []
  currentData.value.inventory = buildInventorySlots(hero.inventory || [], taskDefaults)
}

// 根据路线方案名称取对应默认路线点
function getDefaultPointsForScheme(scheme: string, defaults: any): any[] {
  if (scheme) {
    const preset = (defaults?.route_presets || []).find((p: any) => p.name === scheme)
    if (preset?.points) return JSON.parse(JSON.stringify(preset.points))
  }
  if (defaults?.points) return JSON.parse(JSON.stringify(defaults.points))
  return []
}

// 每日声望任务使用 blackstone_points / forest_points 而非 points
const isDailyReputation = computed(() => currentTaskId.value === 'reputation.daily_reputation')
const pointsKeys = computed(() => {
  if (isDailyReputation.value) return ['blackstone_points', 'forest_points']
  return ['points']
})

// 从 currentData 提取所有路线点到一个对象
function getAllPoints(data: Record<string, any>): Record<string, any[]> {
  const result: Record<string, any[]> = {}
  for (const key of pointsKeys.value) {
    result[key] = JSON.parse(JSON.stringify(data[key] || []))
  }
  return result
}

// 将路线点对象写回 currentData
function setAllPoints(data: Record<string, any>, points: Record<string, any[]>) {
  for (const key of pointsKeys.value) {
    data[key] = JSON.parse(JSON.stringify(points[key] || []))
  }
}

// 从 defaults 提取所有默认路线点
function getAllDefaultPoints(defaults: any): Record<string, any[]> {
  const result: Record<string, any[]> = {}
  for (const key of pointsKeys.value) {
    result[key] = JSON.parse(JSON.stringify(defaults[key] || []))
  }
  return result
}

function loadTaskData(taskId: string) {
  isLoadingTask = true
  // 暂存是会话级且针对单个任务，切换/重置任务时清空
  schemeStash.value = {}
  extraSections.value = []
  // 优先使用缓存的未保存数据（切换标签时保留修改）
  if (taskDataCache.value[taskId]) {
    const cached = taskDataCache.value[taskId]
    currentData.value = JSON.parse(JSON.stringify(cached.data))
    originalTaskData.value = JSON.parse(JSON.stringify(cached.original))
    isLoadingTask = false
    return
  }
  currentData.value = JSON.parse(JSON.stringify(configStore.configs[taskId] || {}))
  const defaults = currentSchema.value ? currentSchema.value.defaults || {} : {}

  // 初始化 enable_blackstone / enable_forest 默认值，避免 checkbox toggle 后 key 被显式写入导致误判未保存
  if (currentData.value.enable_blackstone === undefined && defaults.enable_blackstone !== undefined) {
    currentData.value.enable_blackstone = defaults.enable_blackstone
  }
  if (currentData.value.enable_forest === undefined && defaults.enable_forest !== undefined) {
    currentData.value.enable_forest = defaults.enable_forest
  }

  // 判断 schema 是否包含英雄选择字段
  const hasHeroField = currentSchema.value?.sections.some(s => s.fields?.some(f => f.type === 'hero'))
  // 英雄为可选项；仅在显式未指定英雄（undefined）且默认值存在时才预填充
  if (hasHeroField && currentData.value.hero === undefined && defaults.hero) {
    currentData.value.hero = defaults.hero
  }

  // 初始化 route_scheme 默认值，并加载对应预设路线点
  if (!currentData.value.route_scheme && defaults.route_scheme) {
    currentData.value.route_scheme = defaults.route_scheme
  }

  // 从 hero_configs 展开当前英雄的 points/inventory（若已按英雄隔离保存）
  // 当前英雄无保存配置时重置为对应路线方案的默认值，避免串用其他英雄的路线/物品栏
  if (currentData.value.hero) {
    const hc = currentData.value.hero_configs?.[currentData.value.hero]
    if (hc) {
      if (hc.points) setAllPoints(currentData.value, hc.points)
      if (hc.inventory) currentData.value.inventory = JSON.parse(JSON.stringify(hc.inventory))
    } else {
      const allDefaults = getAllDefaultPoints(defaults)
      setAllPoints(currentData.value, allDefaults)
      // 使用当前英雄的默认物品栏
      applyHeroDefaults(currentData.value.hero, true, hasHeroField)
    }
  }

  // 非英雄选择时也需初始化路线点默认值
  for (const key of pointsKeys.value) {
    if ((!currentData.value[key] || currentData.value[key].length === 0) && defaults[key]) {
      currentData.value[key] = JSON.parse(JSON.stringify(defaults[key]))
    }
  }

  if ((!currentData.value.desired_items || currentData.value.desired_items.length === 0) && defaults.desired_items) {
    currentData.value.desired_items = JSON.parse(JSON.stringify(defaults.desired_items)).filter((it: any) => it.count > 0)
  }

  const hasInventoryField = currentSchema.value?.sections.some(s => s.fields?.some(f => f.type === 'inventory')) ||
    hasInventoryFieldInSections(extraSections.value)
  if (hasInventoryField) {
    applyHeroDefaults(currentData.value.hero, false, hasHeroField)
  }

  // 若旧配置中存在 hero / inventory 但当前 schema 未展示对应章节，自动追加动态章节
  if (currentData.value.hero &&
      !hasHeroFieldInSections(currentSchema.value?.sections) &&
      !hasHeroFieldInSections(extraSections.value)) {
    extraSections.value.push({
      key: 'hero',
      title: '英雄选择',
      help: '根据已有配置自动恢复的英雄选择器',
      fields: [{ key: 'hero', label: '', type: 'hero' }],
    })
  }
  if (currentData.value.inventory &&
      !hasInventoryFieldInSections(currentSchema.value?.sections) &&
      !hasInventoryFieldInSections(extraSections.value)) {
    extraSections.value.push({
      key: 'inventory',
      title: '物品栏',
      help: '根据已有配置自动恢复的物品栏配置',
      fields: [{ key: 'inventory', label: '', type: 'inventory' }],
    })
  }

  // 遍历 schema 所有字段，用默认值填充缺失的 key（含 a.b 嵌套键）
  // 确保用户与表单交互后（update 会显式写入 key）即使改回默认值，key 集仍与 originalTaskData 一致
  if (currentSchema.value?.sections) {
    for (const sec of currentSchema.value.sections) {
      if (!sec.fields) continue
      for (const f of sec.fields) {
        if (!f.key) continue
        const path = f.key.split('.')
        // 与 FormRenderer.getSchemaDefault 一致：TOML defaults 优先，字段 default 兜底
        let def: any = defaults
        for (const k of path) {
          def = def && typeof def === 'object' ? def[k] : undefined
        }
        if (def === undefined) def = f.default
        if (def === undefined) continue
        let cur: any = currentData.value
        for (let i = 0; i < path.length - 1; i++) {
          const k = path[i]
          if (cur[k] === undefined || cur[k] === null || typeof cur[k] !== 'object') {
            cur[k] = {}
          }
          cur = cur[k]
        }
        const leaf = path[path.length - 1]
        if (cur[leaf] === undefined) {
          cur[leaf] = JSON.parse(JSON.stringify(def))
        }
      }
    }
  }

  originalTaskData.value = JSON.parse(JSON.stringify(currentData.value))
  isLoadingTask = false
}

watch(currentTaskId, async (newTaskId, oldTaskId) => {
  // 切走前，缓存当前标签的未保存数据（仅限仍处于打开状态的标签，避免已关闭标签被重新缓存）
  if (oldTaskId && openTabs.value.includes(oldTaskId)) {
    taskDataCache.value[oldTaskId] = {
      data: JSON.parse(JSON.stringify(currentData.value)),
      original: JSON.parse(JSON.stringify(originalTaskData.value)),
    }
  }
  if (!newTaskId || currentModule.value !== 'tasks') return
  // 添加到标签页
  if (!openTabs.value.includes(newTaskId)) {
    openTabs.value.push(newTaskId)
  }
  const task = taskStore.tasks.find(t => t.id === newTaskId)
  await taskStore.loadSchema(newTaskId)
  loadTaskData(newTaskId)
}, { immediate: true })

// 全部英雄模块访问时添加到标签页
watch(currentModule, (mod) => {
  if (mod === 'heroes' && !openTabs.value.includes('__heroes__')) {
    openTabs.value.push('__heroes__')
  }
}, { immediate: true })

watch(() => currentData.value.hero, (newHero, oldHero) => {
  if (isLoadingTask || suppressHeroWatch) return
  if (newHero === oldHero) return

  const hasHeroField = currentSchema.value?.sections.some(s => s.fields?.some(f => f.type === 'hero'))
  const hasInventoryField = currentSchema.value?.sections.some(s => s.fields?.some(f => f.type === 'inventory')) ||
    hasInventoryFieldInSections(extraSections.value)

  if (!newHero) {
    // 取消选择：保留旧英雄隔离配置，并清空物品栏
    if (oldHero) {
      if (!currentData.value.hero_configs) currentData.value.hero_configs = {}
      currentData.value.hero_configs[oldHero] = {
        points: getAllPoints(currentData.value),
        inventory: JSON.parse(JSON.stringify(currentData.value.inventory || [])),
      }
    }
    if (hasInventoryField) {
      applyHeroDefaults('', true, hasHeroField)
    }
    return
  }

  // 按英雄隔离 points/inventory（英雄切换时暂存/恢复）
  if (oldHero) {
    if (!currentData.value.hero_configs) currentData.value.hero_configs = {}
    currentData.value.hero_configs[oldHero] = {
      points: getAllPoints(currentData.value),
      inventory: JSON.parse(JSON.stringify(currentData.value.inventory || [])),
    }
  }
  // 加载新英雄配置
  const hc = currentData.value.hero_configs?.[newHero]
  if (hc) {
    setAllPoints(currentData.value, hc.points)
    currentData.value.inventory = JSON.parse(JSON.stringify(hc.inventory || []))
  } else {
    // 新英雄无保存配置：加载默认路线点/物品栏
    const defaults = currentSchema.value ? currentSchema.value.defaults || {} : {}
    const allDefaults = getAllDefaultPoints(defaults)
    setAllPoints(currentData.value, allDefaults)
    if (hasInventoryField) {
      applyHeroDefaults(newHero, true, hasHeroField)
    }
  }
}, { flush: 'sync' })

// 表单更新入口：处理路线方案切换的暂存与恢复，再写入 currentData
function onModelUpdate(next: Record<string, any>) {
  const prev = currentData.value
  if (!isLoadingTask) {
    handleSchemeSwitch(prev, next)
  }
  currentData.value = next
}

// 路线方案来回切换：优先恢复本次会话/已保存的路线点，而非预设默认值
function handleSchemeSwitch(prev: Record<string, any>, next: Record<string, any>) {
  if (!next.route_scheme || !prev.route_scheme || next.route_scheme === prev.route_scheme) return
  schemeStash.value[prev.route_scheme] = getAllPoints(prev)
  const stashed = schemeStash.value[next.route_scheme]
  if (stashed) {
    setAllPoints(next, stashed)
  } else if (next.route_scheme === originalTaskData.value.route_scheme) {
    setAllPoints(next, getAllPoints(originalTaskData.value))
  }
  // 其余情况保留 FormRenderer 已填入的预设路线点
}


async function saveConfig() {
  if (currentTaskId.value.endsWith('.patrol_loot')) {
    const hasInventory = hasInventoryFieldInSections(currentSchema.value?.sections) ||
      hasInventoryFieldInSections(extraSections.value)
    if (hasInventory) {
      const inv = currentData.value.inventory || []
      if (!inv.some((s: any) => s.id === heroStore.petFoodId)) { showToast('物品栏必须携带宠物食物', 'error'); return }
    }
    const desired = currentData.value.desired_items || []
    if (!desired.some((it: any) => it.count > 0)) { showToast('请至少选择一件待刷装备', 'error'); return }
  }
  // 选择了英雄时将当前英雄的 points/inventory 写入 hero_configs（同步到 currentData 和 dataToSave）
  if (currentData.value.hero) {
    if (!currentData.value.hero_configs) currentData.value.hero_configs = {}
    currentData.value.hero_configs[currentData.value.hero] = {
      points: getAllPoints(currentData.value),
      inventory: JSON.parse(JSON.stringify(currentData.value.inventory || [])),
    }
  }
  const dataToSave = JSON.parse(JSON.stringify(currentData.value))
  configStore.configs[currentTaskId.value] = dataToSave
  const result = await configStore.saveAll()
  if (result.ok) {
    showToast('配置已保存', 'success')
    originalTaskData.value = JSON.parse(JSON.stringify(currentData.value))
    // 保存成功后清除该标签的缓存
    delete taskDataCache.value[currentTaskId.value]
  } else {
    showToast('保存失败：' + result.error, 'error')
  }
}

async function resetTaskConfig() {
  if (!currentSchema.value) return
  const defaults = JSON.parse(JSON.stringify(currentSchema.value.defaults || {}))
  // 清除英雄隔离配置
  delete defaults.hero_configs
  configStore.configs[currentTaskId.value] = defaults
  delete taskDataCache.value[currentTaskId.value]
  loadTaskData(currentTaskId.value)
  showToast('已恢复默认配置', 'success')
}

async function startTask() {
  if (isTaskRunning.value) { showToast('任务正在运行', 'info'); return }
  if (!currentTaskId.value) return

  const result = await taskStore.startTask(currentTaskId.value)
  if (result.ok) {
    showToast('任务已启动（PID ' + result.pid + '）', 'success')
  } else if (result.error) {
    showToast('启动失败：' + result.error, 'error')
  }
}

async function refreshHeroes() {
  try {
    const data = await api.getInit()
    heroStore.setHeroes(data.heroes || [])
    if (currentModule.value === 'tasks' && currentTaskId.value) {
      loadTaskData(currentTaskId.value)
      const hasHeroField = currentSchema.value?.sections.some(s => s.fields?.some(f => f.type === 'hero'))
      const hasInventoryField = currentSchema.value?.sections.some(s => s.fields?.some(f => f.type === 'inventory')) ||
        hasInventoryFieldInSections(extraSections.value)
      if (hasInventoryField) {
        applyHeroDefaults(currentData.value.hero, true, hasHeroField)
      }
    }
  } catch (e: any) {
    showToast('刷新英雄列表失败：' + e.message, 'error')
  }
}

let runningPollTimer: ReturnType<typeof setInterval> | null = null

onMounted(async () => {
  try {
    const data = await api.getInit()
    heroStore.setHeroes(data.heroes || [])
    heroStore.setItems(data.items || [])
    heroStore.setFarmableItems(data.farmable_items || [])
    heroStore.setCommands(data.commands || [])
    configStore.setConfigs(data.configs || {})
    taskStore.tasks = data.tasks || []

    await taskStore.fetchRunning()
    loading.value = false
  } catch (e: any) {
    loading.value = false
    showToast('初始化失败：' + e.message, 'error')
  }

  // 定时轮询运行状态，关闭控制台窗口后能自动检测到进程退出
  runningPollTimer = setInterval(() => {
    taskStore.fetchRunning()
  }, 5000)
})

onUnmounted(() => {
  if (runningPollTimer) {
    clearInterval(runningPollTimer)
    runningPollTimer = null
  }
})
</script>

<template>
  <div class="flex h-screen w-full">
    <!-- 侧边栏（全高） -->
    <Sidebar
      :task-groups="taskStore.taskGroups"
      :current-module="currentModule"
      :current-task-id="currentTaskId"
      :collapsed="sidebarCollapsed"
      @switch-task="switchTask"
      @switch-module="switchModule"
    />

    <!-- 主区域 -->
    <main class="flex-1 min-w-0 flex flex-col overflow-hidden">
      <template v-if="loading">
        <div class="flex-1 flex items-center justify-center text-text-dim">正在加载配置...</div>
      </template>
      <template v-else>
        <!-- 水平导航栏 -->
        <TopNav :collapsed="sidebarCollapsed" @toggle-collapse="toggleSidebar" />

        <!-- 标签页 -->
        <div v-if="currentModule === 'tasks' || currentModule === 'home' || currentModule === 'heroes'" class="task-tabs">
          <div
            class="task-tab"
            :class="{ active: currentModule === 'home' }"
            @click="switchModule('home')"
          >
            <span class="task-tab-label">首页</span>
          </div>
          <div
            v-for="tabId in openTabs"
            :key="tabId"
            class="task-tab"
            :class="{ active: tabId === '__heroes__' ? currentModule === 'heroes' : tabId === currentTaskId }"
            @click="switchTab(tabId)"
          >
            <span class="task-tab-label">{{ tabId === '__heroes__' ? '全部英雄' : (taskStore.tasks.find(t => t.id === tabId)?.name || tabId) }}</span>
            <span class="task-tab-close" @click.stop="closeTab(tabId)">×</span>
          </div>
        </div>

        <div id="scroll-container" class="flex-1 overflow-y-auto p-7">
          <!-- 操作按钮 -->
          <div v-if="currentModule === 'tasks'" class="action-bar-actions">
            <el-button class="btn-header" @click="resetTaskConfig">恢复默认</el-button>
            <el-button class="btn-header" @click="saveConfig">保存配置</el-button>
            <span class="flex-1"></span>
            <el-button
              class="btn-header"
              :class="{ running: isTaskRunning }"
              :disabled="isTaskRunning"
              @click="startTask"
            >
              <el-icon v-if="!isTaskRunning" class="mr-1" :size="18"><VideoPlay /></el-icon>
              <el-icon v-else class="mr-1 is-loading" :size="18"><Loading /></el-icon>
              <span v-if="isTaskRunning">运行中</span>
              <span v-else>启动任务</span>
            </el-button>
          </div>

          <template v-if="currentModule === 'home'">
            <router-view />
          </template>
          <template v-else-if="currentModule === 'heroes'">
            <router-view @refresh="refreshHeroes" />
          </template>
          <template v-else>
            <router-view
              :model="currentData"
              :heroes="heroStore.heroes"
              :items="heroStore.items"
              :farmable-items="heroStore.farmableItems"
              :commands="heroStore.commands"
              :extra-sections="extraSections"
              @update:model="onModelUpdate"
              @add-inventory="onAddInventory"
              @add-hero="onAddHero"
            />
          </template>
        </div>
        <el-backtop target="#scroll-container" :right="40" :bottom="40" class="backtop-custom" />
      </template>
    </main>
  </div>
</template>
