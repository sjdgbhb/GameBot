/** 全局 Toast 提示 composable — 使用 Element Plus ElMessage */
import { ElMessage } from 'element-plus'

export type ToastType = 'success' | 'error' | 'info' | 'warning'

export function showToast(message: string, type: ToastType = 'info') {
  ElMessage({
    message,
    type,
    duration: 2500,
  })
}

export function useToast() {
  return { showToast }
}
