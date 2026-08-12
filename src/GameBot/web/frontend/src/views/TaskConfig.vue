<script setup lang="ts">
import { computed } from 'vue'
import { useRoute } from 'vue-router'
import { useTaskStore } from '@/stores/task'
import { useHeroStore } from '@/stores/hero'
import FormRenderer from '@/components/form/FormRenderer.vue'

const route = useRoute()
const taskStore = useTaskStore()
const heroStore = useHeroStore()

const taskId = computed(() => route.params.taskId as string)
const schema = computed(() => taskStore.schemas[taskId.value])

// 接收 App.vue 传入的 model 数据
const props = defineProps<{
  model?: Record<string, any>
  heroes?: any[]
  items?: any[]
  farmableItems?: string[]
  commands?: any[]
  extraSections?: any[]
}>()

const emit = defineEmits<{
  'update:model': [value: Record<string, any>]
  'addInventory': []
  'addHero': []
}>()
</script>

<template>
  <div>
    <template v-if="schema">
      <FormRenderer
        :schema="schema"
        :model="props.model || {}"
        :heroes="props.heroes || heroStore.heroes"
        :items="props.items || heroStore.items"
        :farmable-items="props.farmableItems || heroStore.farmableItems"
        :commands="props.commands || heroStore.commands"
        :extra-sections="props.extraSections || []"
        @update:model="emit('update:model', $event)"
        @add-inventory="emit('addInventory')"
        @add-hero="emit('addHero')"
      />
    </template>
    <el-card v-else class="card text-center py-12 text-text-dim">
      <div class="text-4xl mb-2">🚧</div>
      <p>该任务暂未开放配置</p>
    </el-card>
  </div>
</template>
