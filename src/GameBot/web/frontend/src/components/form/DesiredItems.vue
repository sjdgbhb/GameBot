<script setup lang="ts">
import { computed } from 'vue'
import { sortByPinyin } from '@/utils/pinyin'

const props = defineProps<{
  modelValue: any[]
  farmableItems: string[]
}>()

const emit = defineEmits<{
  'update:modelValue': [value: any[]]
}>()

const map = computed<Record<string, number>>(() => {
  const m: Record<string, number> = {}
  ;(props.modelValue || []).forEach(it => { m[it.name] = it.count })
  return m
})

const filteredItems = computed(() => sortByPinyin(props.farmableItems, name => name))

const customItems = computed(() => {
  const set = new Set(props.farmableItems)
  return (props.modelValue || []).filter(it => !set.has(it.name))
})

function isChecked(name: string): boolean {
  return (map.value[name] || 0) > 0
}

function count(name: string): number {
  return map.value[name] || 0
}

function shortName(name: string): string {
  return name.length > 4 ? name.slice(0, 4) : name
}

function toggle(name: string, checked: boolean) {
  const list = [...(props.modelValue || [])]
  if (checked) {
    const it = list.find(x => x.name === name)
    if (it) {
      it.count = Math.max(1, it.count || 1)
    } else {
      list.push({ name, count: 1 })
    }
  } else {
    const idx = list.findIndex(it => it.name === name)
    if (idx >= 0) list.splice(idx, 1)
  }
  emit('update:modelValue', list)
}

function setCount(name: string, val: string) {
  const list = [...(props.modelValue || [])]
  const c = Math.max(0, parseInt(val) || 0)
  const it = list.find(x => x.name === name)
  if (!it) {
    if (c > 0) list.push({ name, count: c })
  } else {
    if (c <= 0) {
      const idx = list.findIndex(x => x.name === name)
      if (idx >= 0) list.splice(idx, 1)
    } else {
      it.count = c
    }
  }
  emit('update:modelValue', list)
}

function addCustom() {
  const list = [...(props.modelValue || []), { name: '', count: 1 }]
  emit('update:modelValue', list)
}

function removeCustom(it: any) {
  const list = (props.modelValue || []).filter(x => x !== it)
  emit('update:modelValue', list)
}

function emitUpdate() {
  emit('update:modelValue', [...(props.modelValue || [])])
}
</script>

<template>
  <div>
    <div class="desired-items-list">
      <div
        v-for="name in filteredItems"
        :key="name"
        class="item-row"
        :class="{ checked: isChecked(name) }"
      >
        <el-checkbox
          :model-value="isChecked(name)"
          @update:model-value="toggle(name, $event as boolean)"
          class="item-check"
        >
          <span class="item-name" :title="name">{{ name }}</span>
        </el-checkbox>
        <el-input-number
          :model-value="count(name)"
          @update:model-value="setCount(name, String($event))"
          :min="0"
          :max="99"
          :controls="false"
          size="small"
          style="width: 44px"
        />
      </div>
    </div>
    <div class="space-y-2 mb-3">
      <div v-for="(it, idx) in customItems" :key="idx" class="desired-custom-item">
        <div class="desired-input-group">
          <el-input v-model="it.name" placeholder="装备名称" @input="emitUpdate" />
          <el-input-number v-model="it.count" :min="1" :max="99" :controls="false" @input="emitUpdate" style="width: 44px" />
        </div>
        <el-button class="btn-remove" size="small" @click="removeCustom(it)">删除</el-button>
      </div>
    </div>
    <el-button class="btn-header" @click="addCustom">添加其他</el-button>
  </div>
</template>
