<script setup lang="ts">
import { computed, onMounted } from 'vue'
import type { ItemDef } from '@/types'
import { ElMessage } from 'element-plus'
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
  return arr[idx] || { id: -1, hotkey: String(idx + 1) }
}

function slotTitle(idx: number): string {
  const slot = slotValue(idx)
  if (slot.id === -1) return '空'
  if (slot.id === 0) return '拾取'
  const item = carryableItems.value.find(it => it.id === slot.id)
  return item ? item.name : String(slot.id)
}

function ensureSlots(arr: any[]): any[] {
  while (arr.length < 6) arr.push({ slot: arr.length, id: -1, hotkey: String(arr.length + 1) })
  return arr
}

function updateSlot(idx: number, key: string, value: any) {
  if (props.readonly) return
  const arr = Array.isArray(props.modelValue) ? JSON.parse(JSON.stringify(props.modelValue)) : []
  ensureSlots(arr)
  if (arr[5].id !== 0) {
    arr[5] = { slot: 5, id: 0, hotkey: arr[5].hotkey || '6' }
  }
  // 快捷键不能重复：如果新快捷键已被其他格子使用，提示用户并阻止写入
  if (key === 'hotkey' && value) {
    for (let i = 0; i < 6; i++) {
      if (i !== idx && arr[i].hotkey === value) {
        ElMessage.warning(`快捷键 "${value}" 已被第 ${i + 1} 格使用，请更换其他快捷键`)
        return
      }
    }
  }
  arr[idx] = { ...arr[idx], slot: idx, [key]: value }
  emit('update:modelValue', arr)
}

onMounted(() => {
  if (props.readonly) return
  const arr = Array.isArray(props.modelValue) ? JSON.parse(JSON.stringify(props.modelValue)) : []
  ensureSlots(arr)
  if (arr[5].id !== 0) {
    arr[5] = { slot: 5, id: 0, hotkey: arr[5].hotkey || '6' }
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
        :class="{ locked: i === 6, empty: i !== 6 && slotValue(i - 1).id === -1 }"
      >
        <div class="inv-war3-item">
          <el-select v-if="i === 6" :model-value="0" disabled style="width: 100%; height: 100%" title="拾取">
            <el-option :value="0" label="拾取">
              <span title="拾取">拾取</span>
            </el-option>
          </el-select>
          <el-select
            v-else
            :model-value="slotValue(i - 1).id"
            @update:model-value="updateSlot(i - 1, 'id', Number($event))"
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
            :model-value="slotValue(i - 1).hotkey"
            @update:model-value="updateSlot(i - 1, 'hotkey', $event as string)"
            :maxlength="2"
            :disabled="readonly"
            title="此位置快捷键"
          />
        </div>
      </div>
    </div>
  </div>
</template>
