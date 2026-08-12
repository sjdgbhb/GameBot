<script setup lang="ts">
import { ref, computed } from 'vue'
import type { SchemaField, HeroInfo, ItemDef, SkillDef, InventorySlot, CommandDef } from '@/types'
import HeroSelect from './HeroSelect.vue'
import InventoryGrid from './InventoryGrid.vue'
import DesiredItems from './DesiredItems.vue'
import PointsList from './PointsList.vue'
import StigmaMatrix from './StigmaMatrix.vue'
import { QuestionFilled } from '@element-plus/icons-vue'
import { sortByPinyin } from '@/utils/pinyin'

const props = defineProps<{
  field: SchemaField
  modelValue: any
  heroes?: HeroInfo[]
  items?: ItemDef[]
  farmableItems?: string[]
  commands?: CommandDef[]
  routePresets?: { name: string; points: any[] }[]
  heroSkills?: SkillDef[]
  inventory?: InventorySlot[]
}>()

const emit = defineEmits<{
  'update:modelValue': [value: any]
  'routeSchemeChange': [scheme: string]
  'addInventory': []
  'addHero': []
}>()

function parseValue(value: string, field: SchemaField): any {
  if (field.valueType === 'number') return Number(value)
  if (field.valueType === 'boolean') return value === 'true'
  return value
}

// 带单位数字输入的文本缓冲，避免每次按键时 parseFloat 吃掉小数点
const numberText = ref<string | null>(null)

// 下拉选项按拼音排序
const sortedOptions = computed(() => sortByPinyin(props.field.options || [], opt => opt.label || ''))

function onNumberInput(value: string) {
  // 中文输入法下主键盘小数点可能输出全角句号（U+3002）或全角点（U+FF0E），先归一化为半角小数点
  let filtered = value.replace(/[\u3002\uFF0E\uFF61]/g, '.')
  // 过滤非法字符，仅保留数字、小数点、负号
  filtered = filtered.replace(/[^\d.\-]/g, '')
  // 只允许一个负号，且必须位于开头
  if (filtered.includes('-')) {
    const leading = filtered.startsWith('-') ? '-' : ''
    filtered = leading + filtered.replace(/-/g, '')
  }
  // 只允许一个小数点
  const dotIndex = filtered.indexOf('.')
  if (dotIndex !== -1) {
    filtered = filtered.slice(0, dotIndex + 1) + filtered.slice(dotIndex + 1).replace(/\./g, '')
  }
  numberText.value = filtered
}

function onNumberBlur() {
  if (numberText.value !== null) {
    const n = parseFloat(numberText.value)
    emit('update:modelValue', isNaN(n) ? 0 : n)
    numberText.value = null
  }
}

function updateCoord(idx: number, value: string) {
  const arr = Array.isArray(props.modelValue) ? [...props.modelValue] : [0, 0]
  arr[idx] = Number(value) || 0
  emit('update:modelValue', arr)
}

function formatCoordPair(value: any): string {
  if (!Array.isArray(value)) return '0, 0'
  return value.map(v => Number(v ?? 0)).join(', ')
}

function updateCoordPair(value: string) {
  const normalized = value.replace(/，/g, ',').trim()
  const nums = normalized.split(',').map(s => parseFloat(s.trim())).filter(n => !isNaN(n))
  emit('update:modelValue', nums.length ? nums : [0, 0])
}
</script>

<template>
  <div class="form-group" :style="field.width ? { flex: '0 0 ' + field.width } : field.type === 'inventory' ? { flex: '1 0 100%' } : {}">
    <label v-if="field.label && field.type !== 'checkbox'" class="form-label">
      {{ field.label }}
      <el-tooltip v-if="field.help" :content="field.help" placement="top-start" effect="dark" :show-after="200" popper-class="help-tooltip">
        <el-icon class="help-icon"><QuestionFilled /></el-icon>
      </el-tooltip>
    </label>

    <!-- 文本 / 热键 -->
    <el-input
      v-if="field.type === 'text' || field.type === 'hotkey'"
      :model-value="modelValue"
      @update:model-value="emit('update:modelValue', $event as string)"
      :placeholder="field.placeholder || ''"
      :maxlength="field.maxlength || 255"
      :class="{ short: field.short }"
      clearable
    />

    <!-- 数字 -->
    <el-input-number
      v-else-if="field.type === 'number' && !field.unit"
      :model-value="Number(modelValue) || 0"
      @update:model-value="emit('update:modelValue', $event as number)"
      :min="field.min"
      :max="field.max"
      :step="field.step || 1"
      :precision="field.step && String(field.step).includes('.') ? 1 : 0"
      :controls="field.controls === true"
      :size="field.size || 'default'"
      :style="{ width: field.width || '100%' }"
    />

    <!-- 带单位的数字 -->
    <el-input
      v-else-if="field.type === 'number' && field.unit"
      :model-value="numberText !== null ? numberText : String(modelValue ?? '')"
      @update:model-value="onNumberInput"
      @blur="onNumberBlur"
      inputmode="decimal"
      :size="field.size || 'default'"
      :style="{ width: field.width || '100%' }"
    >
      <template #suffix><span class="input-unit">{{ field.unit }}</span></template>
    </el-input>

    <!-- 下拉选择 -->
    <el-select
      v-else-if="field.type === 'select'"
      :model-value="modelValue"
      @update:model-value="emit('update:modelValue', parseValue(String($event), field))"
      class="form-select"
      style="width: 100%"
    >
      <el-option
        v-for="opt in sortedOptions"
        :key="String(opt.value)"
        :label="opt.label"
        :value="opt.value"
      />
    </el-select>

    <!-- 单选框 -->
    <el-radio-group
      v-else-if="field.type === 'radio'"
      :model-value="modelValue"
      @update:model-value="emit('update:modelValue', $event as any)"
    >
      <el-radio
        v-for="opt in field.options"
        :key="String(opt.value)"
        :value="opt.value"
      >{{ opt.label }}</el-radio>
    </el-radio-group>

    <!-- 开关 -->
    <el-switch
      v-else-if="field.type === 'switch'"
      :model-value="!!modelValue"
      @update:model-value="emit('update:modelValue', $event)"
      active-text="开启"
      inactive-text="关闭"
    />

    <!-- 复选框 -->
    <el-checkbox
      v-else-if="field.type === 'checkbox'"
      :model-value="!!modelValue"
      @update:model-value="emit('update:modelValue', $event)"
    >
      {{ field.label }}
      <el-tooltip v-if="field.help" :content="field.help" placement="top-start" effect="dark" :show-after="200" popper-class="help-tooltip">
        <el-icon class="help-icon"><QuestionFilled /></el-icon>
      </el-tooltip>
    </el-checkbox>

    <!-- 坐标 [x, y] -->
    <div v-else-if="field.type === 'coords'" class="flex gap-2">
      <el-input
        :model-value="formatCoordPair(modelValue)"
        @update:model-value="updateCoordPair($event as string)"
        placeholder="x, y"
        style="width: 100%"
      />
    </div>

    <!-- 英雄选择 -->
    <HeroSelect
      v-else-if="field.type === 'hero'"
      :model-value="modelValue"
      @update:model-value="emit('update:modelValue', $event)"
      :heroes="heroes || []"
    />

    <!-- 物品栏 -->
    <InventoryGrid
      v-else-if="field.type === 'inventory'"
      :model-value="modelValue"
      @update:model-value="emit('update:modelValue', $event)"
      :items="items || []"
    />

    <!-- 目标装备 -->
    <DesiredItems
      v-else-if="field.type === 'desired_items'"
      :model-value="modelValue"
      @update:model-value="emit('update:modelValue', $event)"
      :farmable-items="farmableItems || []"
    />

    <!-- 路线方案选择（单选框） -->
    <el-radio-group
      v-else-if="field.type === 'route_scheme'"
      :model-value="modelValue"
      @update:model-value="emit('routeSchemeChange', $event as string)"
    >
      <el-radio
        v-for="opt in (routePresets || [])"
        :key="opt.name"
        :value="opt.name"
      >{{ opt.name }}</el-radio>
    </el-radio-group>

    <!-- 路线点列表 -->
    <PointsList
      v-else-if="field.type === 'points'"
      :model-value="modelValue"
      @update:model-value="emit('update:modelValue', $event)"
      :task-options="field.taskOptions"
      :hero-skills="heroSkills"
      :inventory="inventory"
      :items="items"
      :commands="commands || []"
      @add-inventory="emit('addInventory')"
      @add-hero="emit('addHero')"
    />

    <!-- 圣痕待升级配置 -->
    <StigmaMatrix
      v-else-if="field.type === 'stigmata_matrix'"
      :model-value="modelValue || {}"
      @update:model-value="emit('update:modelValue', $event)"
    />

  </div>
</template>
