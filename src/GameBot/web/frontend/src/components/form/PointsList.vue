<script setup lang="ts">
import { ref, computed, onMounted, onBeforeUnmount, watch, nextTick } from 'vue'
import { CircleCloseFilled, CirclePlus, Operation, QuestionFilled } from '@element-plus/icons-vue'

import type { SkillDef, InventorySlot, ItemDef, CommandDef } from '@/types'
import { useToast } from '@/composables/useToast'
import { sortByPinyin } from '@/utils/pinyin'

const { showToast } = useToast()

const props = defineProps<{
  modelValue: any[]
  taskOptions?: { value: string; label: string }[]
  heroSkills?: SkillDef[]
  inventory?: InventorySlot[]
  items?: ItemDef[]
  commands?: CommandDef[]
}>()

const emit = defineEmits<{
  'update:modelValue': [value: any[]]
}>()

const scroll = ref<HTMLElement | null>(null)
const containerWidth = ref(720)
const dragIdx = ref<number | null>(null)
const dropIdx = ref<number | null>(null)
const coordErrors = ref<Record<string, boolean>>({})
const coordTexts = ref<Record<string, string>>({})
const skillCoordErrors = ref<Record<string, boolean>>({})
const skillCoordTexts = ref<Record<string, string>>({})
const cardHeights = ref<Record<number, number>>({})
const rowHeights = ref<Record<number, number>>({})

// 描述必填校验：空值视为错误
const descErrors = computed<Record<number, boolean>>(() => {
  const map: Record<number, boolean> = {}
  for (let i = 0; i < points.value.length; i++) {
    map[i] = !points.value[i]?.desc?.trim()
  }
  return map
})

// 必填校验：窗口坐标、路线耗时、移动方式
const requiredErrors = computed<Record<number, { coords: boolean; time: boolean; walk_mode: boolean }>>(() => {
  const map: Record<number, { coords: boolean; time: boolean; walk_mode: boolean }> = {}
  for (let i = 0; i < points.value.length; i++) {
    const pt = points.value[i]
    const c = pt?.coords
    const emptyCoords = !Array.isArray(c) || (Number(c[0] ?? 0) === 0 && Number(c[1] ?? 0) === 0)
    map[i] = {
      coords: emptyCoords,
      time: pt?.time == null || Number(pt.time) <= 0,
      walk_mode: pt?.walk_mode == null,
    }
  }
  return map
})

// 页面内已配置的技能快捷键默认值：同 id 技能在最近一次配置中提取的快捷键
const defaultSkillKeys = computed<Record<number, string>>(() => {
  const map: Record<number, string> = {}
  for (const pt of points.value) {
    for (const act of (pt.actions || [])) {
      if (act.type === 'skill' && act.key) {
        map[act.id] = act.key
      }
    }
  }
  return map
})

function getCoordText(idx: number, field: 'mini_coords' | 'coords'): string {
  const key = `${idx}-${field}`
  if (coordTexts.value[key] !== undefined) return coordTexts.value[key]
  const pt = points.value[idx]
  return formatCoord(pt ? pt[field] : undefined)
}

function onCoordInput(idx: number, field: 'mini_coords' | 'coords', val: string) {
  coordTexts.value[`${idx}-${field}`] = val
}

function onCoordBlur(idx: number, field: 'mini_coords' | 'coords', val: string) {
  const key = `${idx}-${field}`
  const raw = val.trim()
  if (raw === '') {
    delete coordErrors.value[key]
    delete coordTexts.value[key]
    const list = (props.modelValue || []).map((p, i) => (i === idx ? { ...p } : p))
    if (list[idx]) {
      list[idx][field] = undefined
      emit('update:modelValue', list)
    }
    return
  }
  const normalized = normalizeCoord(val)
  if (!isValidCoord(normalized)) {
    coordErrors.value[key] = true
    return
  }
  delete coordErrors.value[key]
  delete coordTexts.value[key]
  const list = (props.modelValue || []).map((p, i) => (i === idx ? { ...p } : p))
  if (!list[idx]) return
  list[idx][field] = parseCoordPair(normalized)
  emit('update:modelValue', list)
}

watch(() => props.modelValue, () => {
  coordTexts.value = {}
  coordErrors.value = {}
  skillCoordTexts.value = {}
  skillCoordErrors.value = {}
}, { deep: true })

const points = computed(() => props.modelValue || [])

const pinyinCollator = new Intl.Collator('zh-Hans-CN')
const sortedHeroSkills = computed<SkillDef[]>(() => {
  if (!props.heroSkills) return []
  return [...props.heroSkills].sort((a, b) => pinyinCollator.compare(a.desc || '', b.desc || ''))
})

const cols = computed(() => {
  const minCard = 260
  const gap = 56
  const w = containerWidth.value || 720
  return Math.max(2, Math.floor(w / (minCard + gap)))
})

const pointsStyle = computed(() => ({
  gridTemplateColumns: `repeat(${cols.value}, 1fr)`,
  columnGap: '56px',
  rowGap: '56px',
}))

function pointStyle(idx: number): Record<string, string> {
  const c = cols.value
  const row = Math.floor(idx / c)
  const col = (row % 2 === 0) ? (idx % c) : (c - 1 - (idx % c))
  return { gridRow: String(row + 1), gridColumn: String(col + 1) }
}

function trailingDir(): string {
  const n = points.value.length
  if (n === 0) return 'right'
  const c = cols.value
  const lastPos = pointPos(n - 1)
  const nextIdx = n
  const nextRow = Math.floor(nextIdx / c)
  const nextCol = (nextRow % 2 === 0) ? (nextIdx % c) : (c - 1 - (nextIdx % c))
  if (nextRow > lastPos.row) return 'down'
  if (nextCol > lastPos.col) return 'right'
  if (nextCol < lastPos.col) return 'left'
  return 'right'
}

function relDir(from: number, to: number): string {
  const a = pointPos(from)
  const b = pointPos(to)
  if (b.row === a.row && b.col > a.col) return 'right'
  if (b.row === a.row && b.col < a.col) return 'left'
  if (b.row > a.row) return 'down'
  if (b.row < a.row) return 'up'
  return ''
}

function pointPos(i: number): { row: number; col: number } {
  const c = cols.value
  const row = Math.floor(i / c)
  const col = (row % 2 === 0) ? (i % c) : (c - 1 - (i % c))
  return { row, col }
}

function newPoint(): any {
  const pt: any = { desc: '', mini_coords: undefined, coords: [0, 0], time: 3, walk_mode: 1, actions: [] }
  if (props.taskOptions && props.taskOptions.length > 0) {
    pt.task = props.taskOptions.map(o => o.value)
  }
  return pt
}

function formatCoord(arr: any): string {
  if (arr == null) return ''
  if (!Array.isArray(arr)) return '0, 0'
  return `${Number(arr[0] ?? 0)}, ${Number(arr[1] ?? 0)}`
}

function normalizeCoord(val: string): string {
  return val.replace(/，/g, ',').trim()
}

function parseCoordPair(val: string): [number, number] {
  const nums = normalizeCoord(val).split(',').map(s => parseFloat(s.trim())).filter(n => !isNaN(n))
  return [nums[0] ?? 0, nums[1] ?? 0]
}

function isValidCoord(val: string): boolean {
  return /^-?\d+(\.\d+)?\s*,\s*-?\d+(\.\d+)?$/.test(normalizeCoord(val))
}

function addPoint() {
  const list = [...(props.modelValue || []), newPoint()]
  emit('update:modelValue', list)
}

function addPointAt(idx: number) {
  const list = [...(props.modelValue || [])]
  list.splice(idx, 0, newPoint())
  emit('update:modelValue', list)
}

function insertAfter(idx: number) {
  if (idx >= points.value.length - 1) addPoint()
  else addPointAt(idx + 1)
}

function removePoint(idx: number) {
  const list = [...(props.modelValue || [])]
  list.splice(idx, 1)
  emit('update:modelValue', list)
}

function emitUpdate() {
  emit('update:modelValue', (props.modelValue || []).slice())
}

function pointTask(idx: number): string[] {
  const pt = points.value[idx]
  if (!pt) return []
  const t = pt.task
  if (!t) return []
  return Array.isArray(t) ? t : [t]
}

function updateTask(idx: number, val: string[]) {
  const list = (props.modelValue || []).map((p, i) => (i === idx ? { ...p } : p))
  if (!list[idx]) return
  if (val.length === 0) {
    delete list[idx].task
  } else {
    list[idx].task = val.length === 1 ? val[0] : val
  }
  emit('update:modelValue', list)
}

const canConfigSkills = computed<boolean>(() => Array.isArray(props.heroSkills) && props.heroSkills.length > 0)

// 是否已配置物品栏（含空格子）
const hasInventory = computed<boolean>(() => Array.isArray(props.inventory) && props.inventory.length > 0)

// 物品栏中可使用的物品选项（按物品 id 去重，按拼音排序）
const useItemOptions = computed<{ value: number; label: string }[]>(() => {
  if (!hasInventory.value) return []
  const seen = new Set<number>()
  const arr: { value: number; label: string }[] = []
  for (const slot of props.inventory!) {
    const itemId = slot.item_id != null ? slot.item_id : slot.id
    if ((itemId ?? -1) <= 0) continue
    if (seen.has(itemId)) continue
    seen.add(itemId)
    const item = props.items?.find(it => it.id === itemId)
    const name = item ? item.name : `物品 ${itemId}`
    arr.push({ value: itemId, label: name })
  }
  return sortByPinyin(arr, o => o.label)
})

// 是否有可配置的指令
const hasCommands = computed<boolean>(() => Array.isArray(props.commands) && props.commands.length > 0)

// 指令预设选项（只显示指令文本，不显示内部键名）
const commandSuggestions = computed<{ value: string; label: string }[]>(() => {
  if (!hasCommands.value) return []
  return props.commands!.map(c => ({ value: c.cmd, label: c.cmd }))
})

// ── actions 统一配置 ──

// 动作类型选项
const actionTypeOptions = [
  { value: 'skill', label: '使用技能' },
  { value: 'item', label: '使用物品' },
  { value: 'msg', label: '发送指令' },
]

// 判断动作类型是否可用
function isActionTypeDisabled(type: string): boolean {
  if (type === 'skill') return !canConfigSkills.value
  if (type === 'item') return !hasInventory.value || useItemOptions.value.length === 0
  return false
}

function pointActions(idx: number): any[] {
  const pt = points.value[idx]
  if (!pt) return []
  return pt.actions || []
}

function addEmptyAction(idx: number) {
  const list = (props.modelValue || []).map((p, i) => (i === idx ? { ...p } : p))
  if (!list[idx]) return
  if (!list[idx].actions) list[idx].actions = []
  list[idx].actions.push({ type: '' })
  emit('update:modelValue', list)
}

function onActionTypeChange(idx: number, aIdx: number, type: string) {
  if (!type) {
    updateActionField(idx, aIdx, 'type', type)
    return
  }
  if (isActionTypeDisabled(type)) {
    const opt = actionTypeOptions.find(o => o.value === type)
    showToast(`${opt?.label || type}不可用`, 'warning')
    return
  }
  const list = (props.modelValue || []).map((p, i) => (i === idx ? { ...p } : p))
  if (!list[idx] || !list[idx].actions) return
  const act: any = { type }
  if (type === 'skill') {
    if (props.heroSkills && props.heroSkills.length > 0) {
      const usedIds = new Set((list[idx].actions as any[])
        .filter((a: any) => a.type === 'skill' && a !== list[idx].actions[aIdx])
        .map((a: any) => a.id))
      const available = props.heroSkills.find(h => !usedIds.has(h.id))
      if (available) {
        act.id = available.id
        act.key = available.key
        act.target_type = available.target_type
      } else {
        act.id = props.heroSkills[0].id
        act.key = props.heroSkills[0].key
        act.target_type = props.heroSkills[0].target_type
      }
    } else {
      act.id = 1
      act.key = ''
      act.target_type = 'self'
    }
  } else if (type === 'item') {
    act.id = useItemOptions.value.length > 0 ? useItemOptions.value[0].value : 0
  } else if (type === 'msg') {
    act.content = ''
  }
  list[idx].actions[aIdx] = act
  emit('update:modelValue', list)
}

function removeAction(idx: number, aIdx: number) {
  const list = (props.modelValue || []).map((p, i) => (i === idx ? { ...p } : p))
  if (!list[idx] || !list[idx].actions) return
  list[idx].actions.splice(aIdx, 1)
  if (list[idx].actions.length === 0) {
    delete list[idx].actions
  }
  emit('update:modelValue', list)
}

function moveAction(idx: number, aIdx: number, dir: -1 | 1) {
  const list = (props.modelValue || []).map((p, i) => (i === idx ? { ...p } : p))
  if (!list[idx] || !list[idx].actions) return
  const arr = list[idx].actions
  const target = aIdx + dir
  if (target < 0 || target >= arr.length) return
  ;[arr[aIdx], arr[target]] = [arr[target], arr[aIdx]]
  emit('update:modelValue', list)
}

function updateActionField(idx: number, aIdx: number, field: string, val: any) {
  const list = (props.modelValue || []).map((p, i) => (i === idx ? { ...p } : p))
  if (!list[idx] || !list[idx].actions) return
  list[idx].actions[aIdx][field] = val
  emit('update:modelValue', list)
}

// ── 技能 action 辅助函数 ──

function actionSkillTargetType(act: any): string {
  const hero = props.heroSkills?.find(h => h.id === act.id)
  return hero ? hero.target_type : (act.target_type || '')
}

function actionSkillKeyEditable(act: any): boolean {
  const hero = props.heroSkills?.find(h => h.id === act.id)
  if (!hero) return true
  return !!hero.fixed_key
}

function actionSkillDefaultKey(act: any): string {
  const hero = props.heroSkills?.find(h => h.id === act.id)
  return hero ? hero.key : (act.key || '')
}

function actionSkillEffectiveKey(act: any): string {
  const hero = props.heroSkills?.find(h => h.id === act.id)
  if (hero) {
    if (hero.fixed_key) return (act.key || '').toUpperCase()
    return (hero.key || '').toUpperCase()
  }
  return (act.key || '').toUpperCase()
}

function hasDuplicateSkillKey(idx: number, aIdx: number, key: string, list?: any[]): boolean {
  if (!key) return false
  const actions = list ? list[idx]?.actions : points.value[idx]?.actions
  return (actions || []).some((a: any, i: number) =>
    i !== aIdx && a.type === 'skill' && actionSkillEffectiveKey(a) === key)
}

function isSkillAlreadyAdded(idx: number, skillId: number, excludeAIdx?: number): boolean {
  const actions = points.value[idx]?.actions || []
  return actions.some((a: any, i: number) =>
    i !== excludeAIdx && a.type === 'skill' && a.id === skillId)
}

function updateActionSkillId(idx: number, aIdx: number, val: number) {
  if (isSkillAlreadyAdded(idx, val, aIdx)) {
    showToast('该技能已在当前路线点中添加', 'warning')
    return
  }
  const list = (props.modelValue || []).map((p, i) => (i === idx ? { ...p } : p))
  if (!list[idx] || !list[idx].actions) return
  const act = list[idx].actions[aIdx]
  const oldHero = props.heroSkills?.find(h => h.id === act.id)
  const newHero = props.heroSkills?.find(h => h.id === val)
  act.id = val
  if (newHero) {
    act.target_type = newHero.target_type
    if (!newHero.fixed_key) {
      act.key = newHero.key
    } else if (!act.key || act.key === oldHero?.key) {
      act.key = newHero.key
    }
  } else {
    if (!act.key) {
      act.key = defaultSkillKeys.value[val] || ''
    }
  }
  const effKey = actionSkillEffectiveKey(act)
  if (effKey && hasDuplicateSkillKey(idx, aIdx, effKey, list)) {
    if (actionSkillKeyEditable(act)) {
      act.key = ''
    } else {
      showToast('该技能默认快捷键与当前路线点其他技能重复，无法选择', 'warning')
      return
    }
  }
  emit('update:modelValue', list)
}

function updateActionSkillCustomId(idx: number, aIdx: number, val: string) {
  const n = Number(val)
  if (Number.isNaN(n)) return
  updateActionSkillId(idx, aIdx, n)
}

function updateActionSkillTargetType(idx: number, aIdx: number, val: string) {
  updateActionField(idx, aIdx, 'target_type', val)
}

function updateActionSkillKey(idx: number, aIdx: number, val: string) {
  const list = (props.modelValue || []).map((p, i) => (i === idx ? { ...p } : p))
  if (!list[idx] || !list[idx].actions) return
  const act = list[idx].actions[aIdx]
  if (!actionSkillKeyEditable(act)) return
  const key = val.trim().toUpperCase()
  if (key && hasDuplicateSkillKey(idx, aIdx, key, list)) {
    showToast('同一路线点中不能存在相同快捷键', 'warning')
    return
  }
  act.key = key
  emit('update:modelValue', list)
}

function getActionSkillCoordText(idx: number, aIdx: number, act: any): string {
  const key = `${idx}-${aIdx}`
  if (skillCoordTexts.value[key] !== undefined) return skillCoordTexts.value[key]
  return formatSkillCoords(act.target_coords)
}

function onActionSkillCoordInput(idx: number, aIdx: number, val: string) {
  const key = `${idx}-${aIdx}`
  skillCoordTexts.value[key] = val
  delete skillCoordErrors.value[key]
}

function onActionSkillCoordBlur(idx: number, aIdx: number, val: string) {
  const key = `${idx}-${aIdx}`
  delete skillCoordTexts.value[key]
  const normalized = val.replace(/，/g, ',').trim()
  if (!normalized) {
    const list = (props.modelValue || []).map((p, i) => (i === idx ? { ...p } : p))
    if (!list[idx] || !list[idx].actions) return
    list[idx].actions[aIdx].target_coords = undefined
    emit('update:modelValue', list)
    return
  }
  const nums = normalized.split(',').map(s => parseFloat(s.trim())).filter(n => !isNaN(n))
  if (nums.length === 2) {
    delete skillCoordErrors.value[key]
    const list = (props.modelValue || []).map((p, i) => (i === idx ? { ...p } : p))
    if (!list[idx] || !list[idx].actions) return
    list[idx].actions[aIdx].target_coords = nums
    emit('update:modelValue', list)
  } else {
    skillCoordErrors.value[key] = true
  }
}

function formatSkillCoords(arr: any): string {
  if (!Array.isArray(arr)) return ''
  return arr.map(v => Number(v ?? 0)).join(', ')
}

function skillNeedsCoords(targetType: string): boolean {
  return targetType === 'ground' || targetType === 'enemy' || targetType === 'ally'
}

// ── 物品 action 辅助函数 ──

function getActionItemCoordsText(idx: number, aIdx: number, act: any): string {
  const key = `${idx}-item-${aIdx}`
  if (skillCoordTexts.value[key] !== undefined) return skillCoordTexts.value[key]
  return formatSkillCoords(act.coords)
}

function onActionItemCoordsInput(idx: number, aIdx: number, val: string) {
  const key = `${idx}-item-${aIdx}`
  skillCoordTexts.value[key] = val
  delete skillCoordErrors.value[key]
}

function onActionItemCoordsBlur(idx: number, aIdx: number, val: string) {
  const key = `${idx}-item-${aIdx}`
  delete skillCoordTexts.value[key]
  const normalized = val.replace(/，/g, ',').trim()
  if (!normalized) {
    const list = (props.modelValue || []).map((p, i) => (i === idx ? { ...p } : p))
    if (!list[idx] || !list[idx].actions) return
    list[idx].actions[aIdx].coords = undefined
    emit('update:modelValue', list)
    return
  }
  const nums = normalized.split(',').map(s => parseFloat(s.trim())).filter(n => !isNaN(n))
  if (nums.length === 2) {
    delete skillCoordErrors.value[key]
    const list = (props.modelValue || []).map((p, i) => (i === idx ? { ...p } : p))
    if (!list[idx] || !list[idx].actions) return
    list[idx].actions[aIdx].coords = nums
    emit('update:modelValue', list)
  } else {
    skillCoordErrors.value[key] = true
  }
}

function updateWidth() {
  if (!scroll.value) {
    containerWidth.value = 720
    return
  }
  const style = getComputedStyle(scroll.value)
  const pl = parseFloat(style.paddingLeft) || 0
  const pr = parseFloat(style.paddingRight) || 0
  containerWidth.value = scroll.value.clientWidth - pl - pr
}

function measureCards() {
  if (!scroll.value) return
  const ptEls = scroll.value.querySelectorAll('.route-point')
  const cHeights: Record<number, number> = {}
  const rHeights: Record<number, number> = {}
  ptEls.forEach((pt, i) => {
    const card = pt.querySelector('.route-card') as HTMLElement | null
    cHeights[i] = card ? card.offsetHeight : 0
    rHeights[i] = (pt as HTMLElement).offsetHeight
  })
  cardHeights.value = cHeights
  rowHeights.value = rHeights
}

function connStyle(idx: number, dir: string, targetIdx?: number): Record<string, string> {
  const h = cardHeights.value[idx] || 0
  if (dir === 'down') {
    if (targetIdx === undefined) {
      // 首尾半线：仍从当前卡片底边开始
      return { top: `${h}px` }
    }
    // 中间下行线：从当前卡片底边连到下一行顶部，需要越过整行高度
    const rowH = rowHeights.value[idx] || h
    const up = Math.max(0, rowH - h)
    return {
      top: '100%',
      '--conn-up': `-${up}px`
    }
  }
  // 水平连接器：取当前卡片与相邻卡片的较小高度，确保两端都落在卡片范围内
  const targetH = (targetIdx !== undefined && cardHeights.value[targetIdx]) ? cardHeights.value[targetIdx] : h
  const y = Math.min(h, targetH)
  return { top: `${y / 2}px`, transform: 'translateY(-50%)' }
}

let ro: ResizeObserver | null = null
let cardRo: ResizeObserver | null = null

function observeCards() {
  if (!cardRo || !scroll.value) return
  cardRo.disconnect()
  const ptEls = scroll.value.querySelectorAll('.route-point')
  ptEls.forEach(pt => {
    cardRo!.observe(pt as HTMLElement)
    const card = pt.querySelector('.route-card')
    if (card) cardRo!.observe(card as HTMLElement)
  })
}

onMounted(() => {
  updateWidth()
  if (typeof ResizeObserver !== 'undefined') {
    cardRo = new ResizeObserver(() => measureCards())
  }
  nextTick(() => {
    measureCards()
    observeCards()
  })
  if (typeof ResizeObserver !== 'undefined' && scroll.value) {
    ro = new ResizeObserver(entries => {
      const rect = entries[0].contentRect
      containerWidth.value = rect.width
      nextTick(() => {
        measureCards()
        observeCards()
      })
    })
    ro.observe(scroll.value)
  } else {
    window.addEventListener('resize', updateWidth)
  }
})

watch([() => props.modelValue, cols], () => {
  nextTick(() => {
    measureCards()
    observeCards()
  })
}, { deep: true })

onBeforeUnmount(() => {
  if (cardRo) cardRo.disconnect()
  if (ro) ro.disconnect()
  else window.removeEventListener('resize', updateWidth)
})

function onDragStart(e: DragEvent, idx: number) {
  const target = e.target as HTMLElement
  if (!target || !target.closest) {
    e.preventDefault()
    return
  }
  if (!target.closest('.route-drag-handle')) {
    e.preventDefault()
    return
  }
  dragIdx.value = idx
  e.dataTransfer!.setData('text/plain', String(idx))
  try { e.dataTransfer!.setData('text', String(idx)) } catch {}
  e.dataTransfer!.effectAllowed = 'move'
  const card = (e.currentTarget as HTMLElement).querySelector('.route-card')
  if (card) {
    e.dataTransfer!.setDragImage(card as HTMLElement, (card as HTMLElement).offsetWidth / 2, (card as HTMLElement).offsetHeight / 2)
  }
}

function onDragOver(e: DragEvent, idx: number) {
  if (e.dataTransfer) e.dataTransfer.dropEffect = 'move'
  dropIdx.value = idx
}

function onDrop(e: DragEvent, idx: number) {
  e.preventDefault()
  const dragI = Number(e.dataTransfer!.getData('text/plain'))
  dropIdx.value = null
  dragIdx.value = null
  if (isNaN(dragI) || dragI === idx) return
  const list = [...points.value]
  const [moved] = list.splice(dragI, 1)
  const insertIdx = idx > dragI ? idx - 1 : idx
  list.splice(insertIdx, 0, moved)
  emit('update:modelValue', list)
}

function onDragEnd() {
  dragIdx.value = null
  dropIdx.value = null
}
</script>

<template>
  <div>
    <div ref="scroll" class="route-scroll-area">
      <div class="route-grid-inner">
        <div v-if="points.length === 0" class="py-4">
          <el-button class="btn btn-sm btn-outline" size="small" @click="addPoint">+ 添加第一个路线点</el-button>
        </div>
        <div v-else class="grid" :style="pointsStyle">
        <div
          v-for="(pt, idx) in points"
          :key="idx"
          class="route-point"
          :class="{ dragging: dragIdx === idx, 'drag-over': dropIdx === idx && dragIdx !== idx }"
          :style="pointStyle(idx)"
          @dragstart="onDragStart($event, idx)"
          @dragend="onDragEnd"
          @dragover.prevent="onDragOver($event, idx)"
          @drop="onDrop($event, idx)"
        >
          <div class="route-card">
            <div class="flex items-center gap-2 mb-3">
              <div class="route-drag-handle" title="拖拽排序" draggable="true">
                <el-icon><Operation /></el-icon>
              </div>
              <div class="route-num">{{ idx + 1 }}</div>
              <el-input
                v-model="pt.desc"
                @input="emitUpdate"
                class="route-desc flex-1"
                :class="{ 'desc-invalid': descErrors[idx] }"
                placeholder="路线点描述（必填）"
                :title="pt.desc"
              />
            </div>
            <div class="space-y-3">
              <div class="flex gap-3">
                <div class="flex-1">
                  <label class="form-label">小地图坐标</label>
                  <el-input
                    :model-value="getCoordText(idx, 'mini_coords')"
                    @update:model-value="onCoordInput(idx, 'mini_coords', $event as string)"
                    @blur="onCoordBlur(idx, 'mini_coords', ($event.target as HTMLInputElement).value)"
                    @clear="onCoordBlur(idx, 'mini_coords', '')"
                    clearable
                    placeholder="x, y（可选）"
                    title="留空则不点小地图"
                    :class="{ 'coord-invalid': coordErrors[`${idx}-mini_coords`] }"
                  />
                </div>
                <div class="flex-1">
                  <label class="form-label">
                    窗口坐标
                    <span class="text-danger ml-1">*</span>
                  </label>
                  <el-input
                    :model-value="getCoordText(idx, 'coords')"
                    @update:model-value="onCoordInput(idx, 'coords', $event as string)"
                    @blur="onCoordBlur(idx, 'coords', ($event.target as HTMLInputElement).value)"
                    @clear="onCoordBlur(idx, 'coords', '')"
                    clearable
                    placeholder="x, y"
                    :class="{ 'coord-invalid': coordErrors[`${idx}-coords`], 'required-invalid': requiredErrors[idx]?.coords }"
                  />
                </div>
              </div>
              <div class="flex gap-3">
                <div class="flex-1">
                  <label class="form-label">
                    路线耗时
                    <span class="text-danger ml-1">*</span>
                  </label>
                  <el-input-number
                    v-model="pt.time"
                    :step="0.5"
                    :precision="1"
                    :min="0"
                    :controls="false"
                    @input="emitUpdate"
                    style="width: 100%"
                    :class="{ 'required-invalid': requiredErrors[idx]?.time }"
                  >
                    <template #suffix><span class="input-unit">秒</span></template>
                  </el-input-number>
                </div>
                <div class="flex-1">
                  <label class="form-label">
                    移动方式
                    <span class="text-danger ml-1">*</span>
                  </label>
                  <el-select
                    v-model="pt.walk_mode"
                    @change="emitUpdate"
                    class="route-select"
                    style="width: 100%"
                    :class="{ 'required-invalid': requiredErrors[idx]?.walk_mode }"
                  >
                    <el-option :value="0" label="右键移动" />
                    <el-option :value="1" label="A地板" />
                    <el-option :value="2" label="M键" />
                  </el-select>
                </div>
              </div>
              <div v-if="taskOptions && taskOptions.length > 0" class="flex gap-3">
                <div class="flex-1">
                  <label class="form-label">
                    任务归属
                    <el-tooltip content="只有下列任务才走这个路线点，无标记则所有任务都走这个路线点" placement="top-start" effect="dark" :show-after="200" popper-class="help-tooltip">
                      <el-icon class="help-icon"><QuestionFilled /></el-icon>
                    </el-tooltip>
                  </label>
                  <el-select
                    :model-value="pointTask(idx)"
                    @update:model-value="updateTask(idx, $event as string[])"
                    multiple
                    collapse-tags
                    collapse-tags-tooltip
                    placeholder="无标记 = 始终走"
                    class="route-select"
                    style="width: 100%"
                  >
                    <el-option v-for="opt in taskOptions" :key="opt.value" :value="opt.value" :label="opt.label" />
                  </el-select>
                </div>
              </div>
              <!-- 到点动作配置（技能/物品/信息统一管理） -->
              <div class="skill-section">
                <label class="form-label">
                  到点动作
                  <el-tooltip content="按列表顺序依次执行，可自由排列使用技能、使用物品、发送指令的顺序" placement="top-start" effect="dark" :show-after="200" popper-class="help-tooltip">
                    <el-icon class="help-icon"><QuestionFilled /></el-icon>
                  </el-tooltip>
                </label>
                <div class="action-list">
                  <div v-for="(act, aIdx) in pointActions(idx)" :key="aIdx" class="action-item">
                    <div class="action-item-header">
                      <el-select
                        :model-value="act.type"
                        @update:model-value="onActionTypeChange(idx, aIdx, $event as string)"
                        placeholder="选择动作类型"
                        class="route-select"
                        style="width: 120px"
                      >
                        <el-option
                          v-for="opt in actionTypeOptions"
                          :key="opt.value"
                          :value="opt.value"
                          :label="opt.label"
                          :disabled="isActionTypeDisabled(opt.value)"
                        />
                      </el-select>
                      <div class="action-item-btns">
                        <el-button class="btn-remove" size="small" :disabled="aIdx === 0" @click="moveAction(idx, aIdx, -1)">↑</el-button>
                        <el-button class="btn-remove" size="small" :disabled="aIdx === pointActions(idx).length - 1" @click="moveAction(idx, aIdx, 1)">↓</el-button>
                        <el-button class="btn-remove" size="small" @click="removeAction(idx, aIdx)">删除</el-button>
                      </div>
                    </div>
                    <div v-if="act.type" class="action-item-body">
                      <!-- 技能配置 -->
                      <template v-if="act.type === 'skill'">
                        <div class="action-field-row">
                          <template v-if="heroSkills && heroSkills.length > 0">
                            <el-select
                              :model-value="act.id"
                              @update:model-value="updateActionSkillId(idx, aIdx, $event as number)"
                              placeholder="选择技能"
                              class="route-select"
                              style="width: 160px"
                            >
                              <el-option
                                v-for="hs in sortedHeroSkills"
                                :key="hs.id"
                                :value="hs.id"
                                :label="hs.desc"
                                :disabled="isSkillAlreadyAdded(idx, hs.id, aIdx)"
                              />
                            </el-select>
                          </template>
                          <template v-else>
                            <el-input
                              :model-value="act.id"
                              @update:model-value="updateActionSkillCustomId(idx, aIdx, $event as string)"
                              placeholder="技能id"
                              style="width: 80px"
                            />
                            <el-select
                              :model-value="act.target_type || ''"
                              @update:model-value="updateActionSkillTargetType(idx, aIdx, $event as string)"
                              placeholder="目标类型"
                              class="route-select"
                              style="width: 100px"
                            >
                              <el-option value="self" label="自身" />
                              <el-option value="ground" label="地面" />
                              <el-option value="enemy" label="敌方" />
                              <el-option value="ally" label="友军" />
                            </el-select>
                          </template>
                          <el-input
                            :model-value="actionSkillKeyEditable(act) ? (act.key || '') : actionSkillDefaultKey(act)"
                            @update:model-value="updateActionSkillKey(idx, aIdx, $event as string)"
                            placeholder="快捷键"
                            style="width: 60px"
                            :title="actionSkillKeyEditable(act) ? '覆盖默认快捷键' : '该技能快捷键固定'"
                            :disabled="!actionSkillKeyEditable(act)"
                          />
                        </div>
                        <el-input
                          v-if="skillNeedsCoords(actionSkillTargetType(act))"
                          :model-value="getActionSkillCoordText(idx, aIdx, act)"
                          @update:model-value="onActionSkillCoordInput(idx, aIdx, $event as string)"
                          @blur="onActionSkillCoordBlur(idx, aIdx, ($event.target as HTMLInputElement).value)"
                          placeholder="技能目标坐标 x, y"
                          style="width: 100%; margin-top: 4px"
                          :class="{ 'coord-invalid': skillCoordErrors[`${idx}-${aIdx}`] }"
                        />
                      </template>

                      <!-- 物品配置 -->
                      <template v-if="act.type === 'item'">
                        <div class="action-field-row">
                          <el-select
                            v-if="hasInventory && useItemOptions.length > 0"
                            :model-value="act.id"
                            @update:model-value="updateActionField(idx, aIdx, 'id', $event as number)"
                            placeholder="选择物品"
                            class="route-select"
                            style="width: 160px"
                          >
                            <el-option
                              v-for="opt in useItemOptions"
                              :key="opt.value"
                              :value="opt.value"
                              :label="opt.label"
                            />
                          </el-select>
                          <el-input
                            v-else
                            :model-value="act.id"
                            @update:model-value="updateActionField(idx, aIdx, 'id', Number($event) || 0)"
                            placeholder="物品id"
                            style="width: 80px"
                          />
                        </div>
                        <el-input
                          :model-value="getActionItemCoordsText(idx, aIdx, act)"
                          @update:model-value="onActionItemCoordsInput(idx, aIdx, $event as string)"
                          @blur="onActionItemCoordsBlur(idx, aIdx, ($event.target as HTMLInputElement).value)"
                          placeholder="目标坐标 x, y（可选，如跳刀）"
                          style="width: 100%; margin-top: 4px"
                          :class="{ 'coord-invalid': skillCoordErrors[`${idx}-item-${aIdx}`] }"
                        />
                      </template>

                      <!-- 发送指令配置 -->
                      <template v-if="act.type === 'msg'">
                        <el-select
                          v-if="hasCommands && commandSuggestions.length > 0"
                          :model-value="act.content"
                          @update:model-value="updateActionField(idx, aIdx, 'content', $event as string)"
                          filterable
                          allow-create
                          default-first-option
                          placeholder="输入或选择指令（如 -del）"
                          class="route-select"
                          style="width: 100%"
                        >
                          <el-option
                            v-for="opt in commandSuggestions"
                            :key="opt.value"
                            :value="opt.value"
                            :label="opt.label"
                          />
                        </el-select>
                        <el-input
                          v-else
                          :model-value="act.content"
                          @update:model-value="updateActionField(idx, aIdx, 'content', $event as string)"
                          placeholder="输入聊天指令（如 -del）"
                          style="width: 100%"
                        />
                      </template>
                    </div>
                  </div>
                  <!-- 添加动作 -->
                  <el-button class="btn-header btn-sm" size="small" @click="addEmptyAction(idx)">添加动作</el-button>
                </div>
              </div>
            </div>
            <el-icon class="route-close" @click.stop="removePoint(idx)" title="删除"><CircleCloseFilled /></el-icon>
          </div>
          <!-- 首卡片前置连接器 -->
          <div v-if="idx === 0" class="route-connector leading conn-left" :style="connStyle(idx, 'left')" @click.stop="addPointAt(0)">
            <el-icon class="route-add-icon"><CirclePlus /></el-icon>
          </div>
          <!-- 中间连接器 -->
          <div v-if="idx < points.length - 1" class="route-connector" :class="`conn-${relDir(idx, idx + 1)}`" :style="connStyle(idx, relDir(idx, idx + 1), idx + 1)" @click.stop="insertAfter(idx)">
            <el-icon class="route-add-icon"><CirclePlus /></el-icon>
          </div>
          <!-- 尾卡片后置连接器 -->
          <div v-else class="route-connector trailing" :class="`conn-${trailingDir()}`" :style="connStyle(idx, trailingDir())" @click.stop="addPoint()">
            <el-icon class="route-add-icon"><CirclePlus /></el-icon>
          </div>
        </div>
      </div>
      </div>
    </div>
  </div>
</template>
