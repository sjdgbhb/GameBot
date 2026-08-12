/** Vue Router 路由定义 */
import { createRouter, createWebHashHistory } from 'vue-router'
import HeroManage from '@/views/HeroManage.vue'

const router = createRouter({
  history: createWebHashHistory(),
  routes: [
    {
      path: '/',
      redirect: '/home',
    },
    {
      path: '/home',
      name: 'home',
      component: () => import('@/views/Home.vue'),
    },
    {
      path: '/task/:taskId',
      name: 'task',
      component: () => import('@/views/TaskConfig.vue'),
      props: true,
    },
    {
      path: '/heroes',
      name: 'heroes',
      component: HeroManage,
    },
  ],
})

export default router
