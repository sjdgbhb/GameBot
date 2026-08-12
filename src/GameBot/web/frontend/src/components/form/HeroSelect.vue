<script setup lang="ts">
import { computed } from 'vue'
import type { HeroInfo } from '@/types'
import { useHeroStore } from '@/stores/hero'

const props = withDefaults(defineProps<{
  modelValue?: string
  heroes: HeroInfo[]
}>(), {
  modelValue: '',
})

const emit = defineEmits<{
  'update:modelValue': [value: string]
}>()

const heroStore = useHeroStore()

const groups = computed(() => {
  const order: Record<string, number> = { P: 1, O: 2 }
  const keys = [...new Set(props.heroes.map(h => h.floor_key || 'P'))]
  keys.sort((a, b) => (order[a] || 99) - (order[b] || 99))
  return keys.map(k => ({
    key: k,
    title: k === 'P' ? '一楼英雄' : k === 'O' ? '二楼英雄' : `${k}楼英雄`,
    heroes: heroStore.sortHeroes(props.heroes.filter(h => (h.floor_key || 'P') === k)),
  }))
})

function toggleHero(h: HeroInfo) {
  emit('update:modelValue', props.modelValue === h.id ? '' : h.id)
}
</script>

<template>
  <div class="space-y-3">
    <div v-for="group in groups" :key="group.key">
      <div class="text-xs text-text-dim mb-2 tracking-wide">{{ group.title }}</div>
      <div class="flex flex-wrap gap-2">
        <div
          v-for="h in group.heroes"
          :key="h.id"
          class="hero-card"
          :class="{ selected: modelValue === h.id }"
          @click="toggleHero(h)"
        >
          <span class="hero-name truncate">{{ h.name }}</span>
        </div>
      </div>
    </div>
  </div>
</template>
