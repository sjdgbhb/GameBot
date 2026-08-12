<script setup lang="ts">
import { computed } from 'vue'
import type { TaskGroup } from '@/types'
import {
  List,
  Users,
  Trophy,
  Zap,
  Award,
  Infinity as InfinityIcon,
  Package,
  Crosshair,
  Fish,
  FileText,
  Home as HomeIcon,
  Settings as SettingsIcon,
} from '@lucide/vue'

const props = defineProps<{
  taskGroups: TaskGroup[]
  currentModule: string
  currentTaskId: string
  collapsed: boolean
}>()

const emit = defineEmits<{
  switchTask: [taskId: string]
  switchModule: [module: string]
}>()

const activeIndex = computed(() => {
  if (props.currentModule === 'home') return 'home'
  if (props.currentModule === 'heroes') return 'heroes'
  return props.currentTaskId
})

const defaultOpeneds = computed(() => {
  if (props.collapsed) return []
  const open: string[] = ['jiubing2', 'tasks', 'heroes']
  for (const g of props.taskGroups) {
    if (g.tasks.some(t => t.id === props.currentTaskId)) {
      open.push(g.key)
    }
  }
  return open
})

function handleSelect(index: string) {
  if (index === 'home') {
    emit('switchModule', 'home')
    return
  }
  if (index === 'heroes') {
    emit('switchModule', 'heroes')
    return
  }
  emit('switchTask', index)
}

const groupIcons: Record<string, any> = {
  achievements: Trophy,
  atomic: Zap,
  reputation: Award,
  endless: InfinityIcon,
  others: Package,
}

const taskIcons: Record<string, any> = {
  patrol_loot: Crosshair,
  fishing: Fish,
  endless: InfinityIcon,
  endless_single: InfinityIcon,
}

function getGroupIcon(group: TaskGroup) {
  return groupIcons[group.key] || FileText
}

function getTaskIcon(taskId: string) {
  const short = taskId.split('.').pop() || taskId
  return taskIcons[short] || FileText
}

function isGroupAllDisabled(group: TaskGroup): boolean {
  return group.tasks.length > 0 && group.tasks.every(t => !t.configurable)
}

function isTasksAllDisabled(): boolean {
  return props.taskGroups.length > 0 && props.taskGroups.every(g => isGroupAllDisabled(g))
}

function trunc4(s: string): string {
  return s.length > 4 ? s.slice(0, 4) + '…' : s
}
</script>

<template>
  <aside class="sidebar" :class="{ collapsed }">
    <div v-if="!collapsed" class="sidebar-logo">
      <span class="sidebar-logo-text">脚本系统</span>
    </div>
    <div class="sidebar-menu">
      <el-menu
        :default-active="activeIndex"
        :default-openeds="defaultOpeneds"
        :collapse="collapsed"
        @select="handleSelect"
        class="border-none"
        background-color="transparent"
        text-color="#f0f0f5"
        active-text-color="#f0c040"
      >
        <el-menu-item index="home">
          <el-icon><HomeIcon /></el-icon>
          <span :title="'首页'">{{ trunc4('首页') }}</span>
        </el-menu-item>

        <el-sub-menu index="jiubing2">
          <template #title>
            <el-icon><InfinityIcon /></el-icon>
            <span :title="'九种兵器'">{{ trunc4('九种兵器') }}</span>
          </template>

          <el-sub-menu index="tasks" :disabled="isTasksAllDisabled()">
            <template #title>
              <el-icon><List /></el-icon>
              <span :title="'任务'">{{ trunc4('任务') }}</span>
            </template>
            <el-sub-menu
              v-for="group in taskGroups"
              :key="group.key"
              :index="group.key"
              :disabled="isGroupAllDisabled(group)"
            >
              <template #title>
                <el-icon><component :is="getGroupIcon(group)" /></el-icon>
                <span :title="group.label">{{ trunc4(group.label) }}</span>
              </template>
              <el-menu-item
                v-for="task in group.tasks"
                :key="task.id"
                :index="task.id"
                :disabled="!task.configurable"
                :title="task.configurable ? task.name : (task.name + '（暂未开放配置）')"
              >
                <el-icon><component :is="getTaskIcon(task.id)" /></el-icon>
                <span :title="task.name">{{ trunc4(task.name) }}</span>
              </el-menu-item>
            </el-sub-menu>
          </el-sub-menu>

          <el-sub-menu index="heroes">
            <template #title>
              <el-icon><Users /></el-icon>
              <span :title="'英雄'">{{ trunc4('英雄') }}</span>
            </template>
            <el-menu-item index="heroes">
              <el-icon><Users /></el-icon>
              <span :title="'全部英雄'">{{ trunc4('全部英雄') }}</span>
            </el-menu-item>
          </el-sub-menu>

          <el-menu-item index="jiubing2_settings" disabled>
            <el-icon><SettingsIcon /></el-icon>
            <span :title="'设置（开发中）'">{{ trunc4('设置') }}</span>
          </el-menu-item>
        </el-sub-menu>

        <el-menu-item index="global_settings" disabled>
          <el-icon><SettingsIcon /></el-icon>
          <span :title="'设置（开发中）'">{{ trunc4('设置') }}</span>
        </el-menu-item>
      </el-menu>
    </div>

    <div v-if="!collapsed" class="sidebar-footer">v3.0</div>
  </aside>
</template>