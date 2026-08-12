<script setup lang="ts">
import { PanelLeftClose, PanelLeftOpen } from '@lucide/vue'

defineProps<{
  collapsed: boolean
}>()

const emit = defineEmits<{
  toggleCollapse: []
}>()
</script>

<template>
  <header class="top-nav">
    <div class="top-nav-collapse" @click="emit('toggleCollapse')">
      <el-icon :size="20">
        <component :is="collapsed ? PanelLeftOpen : PanelLeftClose" />
      </el-icon>
    </div>
  </header>
</template>
