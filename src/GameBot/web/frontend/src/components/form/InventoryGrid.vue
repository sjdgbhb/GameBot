<script setup lang="ts">
import { computed, onMounted } from 'vue'
import type { ItemDef } from '@/types'
import { sortByPinyin } from '@/utils/pinyin'

const props = defineProps<{
  modelValue: any[]
  items: ItemDef[]
  readonly?: boolean
}>()

const emit = defineEmits<{
  'update:modelValue': [value: any[]]
}>()

const carryableItems = computed(() => {
  return sortByPinyin(
    props.items.filter(it => it.id !== 0),
    it => it.name || ''
  )
})

function slotValue(idx: number): any {
  const arr = Array.isArray(props.modelValue) ? props.modelValue : []
  return arr[idx] || { slot: idx, item_id: -1, hotkey: String(idx + 1) }
}

function slotTitle(idx: number): string {
  const slot = slotValue(idx)
  const itemId = slot.item_id != null ? slot.item_id : slot.id
  if (itemId === -1) return '空'
  if (itemId === 0) return '拾取'
  const item = carryableItems.value.find(it => it.id === itemId)
  return item ? item.name : String(itemId)
}

function ensureSlots(arr: any[]): any[] {
  while (arr.length < 6) arr.push({ slot: arr.length, item_id: -1, hotkey: String(arr.length + 1) })
  return arr
}

function updateSlot(idx: number, value: any) {
  if (props.readonly) return
  const arr = Array.isArray(props.modelValue) ? JSON.parse(JSON.stringify(props.modelValue)) : []
  ensureSlots(arr)
  if (arr[5].item_id !== 0 && (arr[5].item_id != null ? arr[5].item_id : arr[5].id) !== 0) {
    arr[5] = { slot: 5, item_id: 0, hotkey: arr[5].hotkey || '6' }
  }
  arr[idx] = { ...arr[idx], slot: idx, item_id: Number(value) }
  emit('update:modelValue', arr)
}

onMounted(() => {
  if (props.readonly) return
  const arr = Array.isArray(props.modelValue) ? JSON.parse(JSON.stringify(props.modelValue)) : []
  ensureSlots(arr)
  if (arr[5].item_id !== 0 && (arr[5].item_id != null ? arr[5].item_id : arr[5].id) !== 0) {
    arr[5] = { slot: 5, item_id: 0, hotkey: arr[5].hotkey || '6' }
  }
  emit('update:modelValue', arr)
})
</script>

<template>
  <div style="width: 100%; display: flex; justify-content: flex-start">
    <div class="inv-war3">
      <div
        v-for="i in 6"
        :key="i"
        class="inv-war3-slot"
        :class="{ locked: i === 6, empty: i !== 6 && (slotValue(i - 1).item_id != null ? slotValue(i - 1).item_id : slotValue(i - 1).id) === -1 }"
      >
        <div class="inv-war3-item">
          <el-select v-if="i === 6" :model-value="0" disabled style="width: 100%; height: 100%" title="拾取">
            <el-option :value="0" label="拾取">
              <span title="拾取">拾取</span>
            </el-option>
          </el-select>
          <el-select
            v-else
            :model-value="slotValue(i - 1).item_id != null ? slotValue(i - 1).item_id : slotValue(i - 1).id"
            @update:model-value="updateSlot(i - 1, $event)"
            :disabled="readonly"
            filterable
            style="width: 100%; height: 100%"
            title="装备"
          >
            <el-option :value="-1" label="空">
              <span title="空">空</span>
            </el-option>
            <el-option v-for="it in carryableItems" :key="it.id" :value="it.id" :label="it.name">
              <span :title="it.name">{{ it.name }}</span>
            </el-option>
          </el-select>
        </div>
        <div class="inv-war3-key">
          <el-input
            :model-value="slotValue(i - 1).hotkey || String(i)"
            disabled
            :maxlength="2"
            title="格子快捷键（在 KK 平台设置）"
          />
        </div>
      </div>
    </div>
  </div>
</template>
