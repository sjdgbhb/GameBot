<script setup lang="ts">
import { ref, watch } from 'vue'

const props = defineProps<{
  modelValue: Record<string, number[]>
}>()

const emit = defineEmits<{
  'update:modelValue': [value: Record<string, number[]>]
}>()

const POSITIONS = ['upper', 'core', 'middle', 'lower'] as const
const LABELS: Record<string, string> = {
  upper: '上位',
  core: '核心',
  middle: '中位',
  lower: '下位',
}

/** 将词条数组格式化为逗号分隔字符串 */
function formatRow(vals: any): string {
  if (!Array.isArray(vals)) return '0,0,0'
  const nums = vals.map(v => Number(v ?? 0))
  while (nums.length < 3) nums.push(0)
  return nums.slice(0, 3).join(',')
}

/** 当前输入框显示文本 */
const texts = ref<Record<string, string>>({})

function syncTexts() {
  const next: Record<string, string> = {}
  for (const pos of POSITIONS) {
    next[pos] = formatRow(props.modelValue?.[pos])
  }
  texts.value = next
}

syncTexts()
watch(() => props.modelValue, syncTexts, { deep: true })

/** 解析用户输入为 3 个非负数 */
function parseRow(text: string): number[] {
  const normalized = text.replace(/，/g, ',').trim()
  if (!normalized) return [0, 0, 0]
  const nums = normalized.split(',').map(s => {
    const n = parseFloat(s.trim())
    return isNaN(n) ? 0 : Math.max(0, n)
  })
  while (nums.length < 3) nums.push(0)
  return nums.slice(0, 3)
}

function onInput(pos: string, text: string) {
  texts.value[pos] = text
}

function onBlur(pos: string) {
  const parsed = parseRow(texts.value[pos] || '')
  texts.value[pos] = formatRow(parsed)
  const next: Record<string, number[]> = { ...props.modelValue }
  next[pos] = parsed
  emit('update:modelValue', next)
}
</script>

<template>
  <div class="stigma-matrix">
    <div v-for="pos in POSITIONS" :key="pos" class="stigma-row">
      <span class="stigma-label">{{ LABELS[pos] }}</span>
      <el-input
        :model-value="texts[pos]"
        @update:model-value="onInput(pos, $event as string)"
        @blur="onBlur(pos)"
        :maxlength="20"
        placeholder="0,0,0"
        size="default"
        style="width: 160px"
      />
    </div>
  </div>
</template>

<style scoped>
.stigma-matrix {
  display: flex;
  flex-direction: column;
  gap: 12px;
}
.stigma-row {
  display: flex;
  align-items: center;
  gap: 16px;
}
.stigma-label {
  width: 56px;
  text-align: right;
  color: var(--el-text-color-regular);
  font-size: 14px;
}
</style>
