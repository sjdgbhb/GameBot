<script setup lang="ts">
import { computed } from 'vue'
import type { SchemaSection, HeroInfo, ItemDef, SkillDef, CommandDef } from '@/types'
import FieldRenderer from './FieldRenderer.vue'

const props = defineProps<{
  schema: any
  model: Record<string, any>
  heroes?: HeroInfo[]
  items?: ItemDef[]
  farmableItems?: string[]
  commands?: CommandDef[]
  extraSections?: any[]
}>()

const emit = defineEmits<{
  'update:model': [value: Record<string, any>]
  'addInventory': []
  'addHero': []
}>()

const routePresets = computed(() => {
  const defaults = props.schema?.defaults || {}
  return defaults.route_presets || []
})

const heroSkills = computed<SkillDef[]>(() => {
  const heroId = props.model?.hero
  if (!heroId || !props.heroes) return []
  const hero = props.heroes.find(h => h.id === heroId)
  return hero?.skills || []
})

const inventory = computed(() => props.model?.inventory)

function resolve(obj: Record<string, any>, key: string): any {
  const keys = key.split('.')
  let v: any = obj
  for (const k of keys) {
    v = v && typeof v === 'object' ? v[k] : undefined
  }
  return v !== undefined ? v : getSchemaDefault(key)
}

function update(key: string, value: any) {
  const keys = key.split('.')
  let target: Record<string, any>
  if (keys.length === 1) {
    target = { ...props.model, [key]: value }
  } else {
    target = { ...props.model }
    let cur: any = target
    for (let i = 0; i < keys.length - 1; i++) {
      const k = keys[i]
      const next = cur[k] && typeof cur[k] === 'object' ? { ...cur[k] } : {}
      cur[k] = next
      cur = next
    }
    cur[keys[keys.length - 1]] = value
  }
  emit('update:model', target)
}

function onRouteSchemeChange(scheme: string) {
  const preset = (routePresets.value as any[]).find((p: any) => p.name === scheme)
  const target: Record<string, any> = { ...props.model, route_scheme: scheme }
  if (preset && preset.points) {
    target.points = JSON.parse(JSON.stringify(preset.points))
  }
  emit('update:model', target)
}

function getFieldDefault(key: string): any {
  for (const sec of props.schema.sections) {
    if (!sec.fields) continue
    for (const f of sec.fields) {
      if (f.key === key) return f.default
    }
  }
  return undefined
}

function getSchemaDefault(key: string): any {
  const defaults = props.schema && props.schema.defaults
  if (defaults) {
    const keys = key.split('.')
    let v: any = defaults
    for (const k of keys) {
      if (v && typeof v === 'object' && k in v) {
        v = v[k]
      } else {
        v = undefined
        break
      }
    }
    if (v !== undefined) return v
  }
  return getFieldDefault(key)
}

function visibleFields(fields: any[]): any[] {
  return fields.filter(f => {
    if (!f.showIf) return true
    return resolve(props.model, f.showIf.field) === f.showIf.value
  })
}

function isSectionVisible(section: any): boolean {
  if (!section.showIf) return true
  return resolve(props.model, section.showIf.field) === section.showIf.value
}
</script>

<template>
  <div>
    <el-card v-for="section in schema.sections" v-show="isSectionVisible(section)" :key="section.key" class="card" shadow="never">
      <template #header v-if="section.title || section.comment">
        <div class="card-title">
          {{ section.title }}
          <span v-if="section.comment" class="card-comment">{{ section.comment }}</span>
        </div>
      </template>
      <div v-if="section.content" class="guide-content" v-html="section.content"></div>
      <div v-if="section.help" class="form-help mb-3">{{ section.help }}</div>
      <div class="form-row" v-if="section.fields">
        <FieldRenderer
          v-for="field in visibleFields(section.fields)"
          :key="field.key"
          :field="field"
          :model-value="resolve(model, field.key)"
          @update:model-value="update(field.key, $event)"
          @route-scheme-change="onRouteSchemeChange"
          @add-inventory="emit('addInventory')"
          @add-hero="emit('addHero')"
          :heroes="heroes || []"
          :items="items || []"
          :farmable-items="farmableItems || []"
          :commands="commands || []"
          :route-presets="routePresets"
          :hero-skills="heroSkills"
          :inventory="inventory"
        />
      </div>
      <div v-if="section.footer" class="form-help mt-3">{{ section.footer }}</div>
    </el-card>
    <el-card v-for="section in (extraSections || [])" :key="section.key" class="card" shadow="never">
      <template #header v-if="section.title || section.comment">
        <div class="card-title">
          {{ section.title }}
          <span v-if="section.comment" class="card-comment">{{ section.comment }}</span>
        </div>
      </template>
      <div v-if="section.content" class="guide-content" v-html="section.content"></div>
      <div v-if="section.help" class="form-help mb-3">{{ section.help }}</div>
      <div class="form-row" v-if="section.fields">
        <FieldRenderer
          v-for="field in visibleFields(section.fields)"
          :key="field.key"
          :field="field"
          :model-value="resolve(model, field.key)"
          @update:model-value="update(field.key, $event)"
          @route-scheme-change="onRouteSchemeChange"
          @add-inventory="emit('addInventory')"
          @add-hero="emit('addHero')"
          :heroes="heroes || []"
          :items="items || []"
          :farmable-items="farmableItems || []"
          :commands="commands || []"
          :route-presets="routePresets"
          :hero-skills="heroSkills"
          :inventory="inventory"
        />
      </div>
      <div v-if="section.footer" class="form-help mt-3">{{ section.footer }}</div>
    </el-card>
  </div>
</template>
