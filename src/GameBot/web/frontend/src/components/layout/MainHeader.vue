<script setup lang="ts">
defineProps<{
  title: string
  desc: string
  showActions: boolean
  isRunning: boolean
}>()

const emit = defineEmits<{
  save: []
  reset: []
  start: []
}>()
</script>

<template>
  <header class="px-7 py-5 bg-gradient-to-b from-bg to-card flex items-center justify-between shadow-sm">
    <div>
      <div class="text-[24px] font-bold text-gold-bright tracking-wide">{{ title }}</div>
      <div class="text-sm text-text-dim mt-1.5">{{ desc }}</div>
    </div>
    <div v-if="showActions" class="flex gap-3">
      <el-button class="btn-header" @click="emit('reset')">恢复默认</el-button>
      <el-button class="btn-header" @click="emit('save')">保存配置</el-button>
      <el-button
        class="btn-header"
        :class="{ running: isRunning }"
        :disabled="isRunning"
        @click="emit('start')"
      >
        <span v-if="isRunning">运行中</span>
        <span v-else>启动任务</span>
      </el-button>
    </div>
  </header>
</template>
