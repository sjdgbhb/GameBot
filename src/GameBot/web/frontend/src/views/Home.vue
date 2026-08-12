<script setup lang="ts">
import { computed } from 'vue'
import { useRouter } from 'vue-router'
import { useTaskStore } from '@/stores/task'
import {
  Monitor,
  Settings,
  Play,
  Fish,
  Infinity as InfinityIcon,
  Sparkles,
  Crosshair,
  Award,
  Trophy,
} from '@lucide/vue'

const router = useRouter()
const taskStore = useTaskStore()

const baseTaskEntries = [
  { icon: Fish, name: '钓鱼', desc: '自动抛竿，预判收竿，按抛竿次数停止', id: 'others.fishing' },
  { icon: InfinityIcon, name: '局内无尽', desc: '英雄已在无尽地图内，直接循环刷怪刷积分，可以自由设置层数', id: 'endless.endless_single' },
  { icon: InfinityIcon, name: '多局无尽', desc: '完整流程：KK房间内 启动游戏 → 英雄初始化 → 进皇宫 → 进无尽（可选重置层数1或15） → 局内无尽 → 退出，多局自动循环', id: 'endless.endless' },
  { icon: Sparkles, name: '升级圣痕', desc: '通过完成城门骚扰任务获取圣痕升级机会来圣痕升级，直到所有词条达标', id: 'others.upgrade_stigmata' },
  { icon: Crosshair, name: '刷装备', desc: '路线循环杀怪，检测地面宝箱，拾取目标装备，直到储物箱满或达到目标数量', id: 'others.patrol_loot' },
  { icon: Award, name: '每日声望', desc: '顺序编排：黑石城声望 → 转场至森之城 → 森之城声望，各 150 点', id: 'reputation.daily_reputation' },
  { icon: Trophy, name: '个人任务成就', desc: '反复完成卡米村村民杰菲特的多个任务，直到达成指定次数', id: 'achievements.personal' },
]

const taskEntries = computed(() => {
  const configurableMap: Record<string, boolean> = {}
  for (const t of taskStore.tasks) {
    configurableMap[t.id] = !!t.configurable
  }
  return baseTaskEntries.map(task => ({
    ...task,
    configurable: configurableMap[task.id] ?? false,
  }))
})

function goTask(task: { id: string; configurable?: boolean }) {
  if (!task.configurable) return
  router.push(`/task/${task.id}`)
}
</script>

<template>
  <div class="home-page">
    <!-- 运行环境 -->
    <el-card class="card" shadow="never">
      <template #header>
        <div class="card-title">
          <el-icon class="home-section-icon"><Monitor /></el-icon>
          运行环境
        </div>
      </template>
      <div class="home-content">
        <div class="home-item">
          <span class="home-item-label">操作系统</span>
          <span class="home-item-text">仅支持 Windows（依赖大漠插件 COM 自动化）</span>
        </div>
        <div class="home-item">
          <span class="home-item-label">KK 平台设置</span>
          <span class="home-item-text">非重置版war3，窗口模式，分辨率1920x1080，窗口大小1920x1080，启用视距调整，视距高度 3000</span>
        </div>
      </div>
    </el-card>

    <!-- 常用任务执行入口 -->
    <el-card class="card" shadow="never">
      <template #header>
        <div class="card-title">
          <el-icon class="home-section-icon"><Play /></el-icon>
          常用任务
        </div>
      </template>
      <div class="home-task-list">
        <div
          v-for="task in taskEntries"
          :key="task.id"
          class="home-task-card"
          :class="{ 'home-task-card-disabled': !task.configurable }"
          :title="task.configurable ? task.desc : (task.name + '（暂未开放配置）')"
          @click="goTask(task)"
        >
          <el-icon class="home-task-icon"><component :is="task.icon" /></el-icon>
          <div class="home-task-info">
            <div class="home-task-name">{{ task.name }}</div>
            <div class="home-task-desc">{{ task.desc }}</div>
          </div>
        </div>
      </div>
    </el-card>

    <!-- 配置原则 -->
    <el-card class="card" shadow="never">
      <template #header>
        <div class="card-title">
          <el-icon class="home-section-icon"><Settings /></el-icon>
          配置原则
        </div>
      </template>
      <div class="home-content">
        <div class="home-item">
          <span class="home-item-label">英雄配置</span>
          <span class="home-item-text">在「英雄」页面配置每个英雄的物品栏默认装备和快捷键。任务配置中选择英雄后会自动继承其默认物品栏，并且携带的物品以任务配置中为准</span>
        </div>
        <div class="home-item">
          <span class="home-item-label">物品栏配置</span>
          <span class="home-item-text">前 5 格可自由设置携带装备和快捷键（数字 1~5），第 6 格固定为拾取。</span>
        </div>
        <div class="home-item">
          <span class="home-item-label">技能配置</span>
          <span class="home-item-text">只有自动施法模式才需要配置技能，一般选择全程平a模式（携带一些物理属性就可以了），如果一定要自动施法，建议选择一些无指向技能（如异界之人的相位作战服），否则需要自行抓取坐标作为施法目标。</span>
        </div>
        <div class="home-item">
          <span class="home-item-label">任务配置</span>
          <span class="home-item-text">选择英雄 → 配置物品栏装备 → 设置任务参数 → 保存配置 → 启动任务。</span>
        </div>
      </div>
    </el-card>
  </div>
</template>
