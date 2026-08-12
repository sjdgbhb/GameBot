/** 深拷贝/深比较工具函数 */
export function deepClone<T>(obj: T): T {
  return JSON.parse(JSON.stringify(obj))
}

export function deepEqual(a: any, b: any): boolean {
  if (a === b) return true
  if (a == null || b == null) return a === b
  if (typeof a !== typeof b) return false
  if (typeof a !== 'object') return a === b
  const aKeys = Object.keys(a).sort()
  const bKeys = Object.keys(b).sort()
  if (aKeys.length !== bKeys.length) return false
  for (let i = 0; i < aKeys.length; i++) {
    if (aKeys[i] !== bKeys[i]) return false
    if (!deepEqual(a[aKeys[i]], b[aKeys[i]])) return false
  }
  return true
}

/**
 * 把任务数据规范化后再比较，避免 UI 运行期产生的临时/默认值导致
 * “改了又改回来” 仍被判定为未保存。
 */
function normalizeForCompare(value: any): any {
  if (value == null || typeof value !== 'object') return value
  if (Array.isArray(value)) return value.map(normalizeForCompare)

  const n: Record<string, any> = {}
  for (const key of Object.keys(value)) {
    if (value[key] === undefined) continue
    n[key] = normalizeForCompare(value[key])
  }

  // hero_configs 是当前英雄的 points/inventory 的镜像，比较时直接看 points/inventory 即可
  delete n.hero_configs

  // hero 为空字符串时表示未选择英雄，与 undefined/未设置视为相同
  if (n.hero === '' || n.hero == null) {
    delete n.hero
  }

  // 声望目标未选中时，对应路线点和物品栏不应影响判断
  if (n.enable_blackstone === false) {
    delete n.blackstone_points
  }
  if (n.enable_forest === false) {
    delete n.forest_points
    delete n.inventory
  }

  // 路线点：没有真正配置技能时，去掉 skills 临时键
  for (const pk of ['points', 'blackstone_points', 'forest_points']) {
    if (Array.isArray(n[pk])) {
      n[pk] = n[pk].map(cleanPointForCompare)
    }
  }

  // inventory：slot 键与数组下标等价，UI 交互（InventoryGrid）会补写 slot，比较时忽略
  if (Array.isArray(n.inventory)) {
    n.inventory = n.inventory.map(cleanInventorySlotForCompare)
  }

  // desired_items：过滤无效项（未命名/数量为0）后按 name 排序，避免 toggle 顺序变化影响判断
  if (Array.isArray(n.desired_items)) {
    n.desired_items = n.desired_items
      .filter((it: any) => it && it.name && (it.count ?? 0) > 0)
      .sort((a: any, b: any) => {
        const na = a?.name || ''
        const nb = b?.name || ''
        return na.localeCompare(nb, 'zh-CN')
      })
  }

  return n
}

function cleanInventorySlotForCompare(slot: any): any {
  if (!slot || typeof slot !== 'object') return slot
  const s: Record<string, any> = {}
  for (const key of Object.keys(slot)) {
    if (key === 'slot' || slot[key] === undefined) continue
    s[key] = slot[key]
  }
  return s
}

function cleanPointForCompare(point: any): any {
  if (!point || typeof point !== 'object') return point
  const p: Record<string, any> = {}
  for (const key of Object.keys(point)) {
    if (point[key] === undefined) continue
    p[key] = point[key]
  }
  // 小地图坐标未配置或为空数组时不参与比较
  if (p.mini_coords === null || (Array.isArray(p.mini_coords) && p.mini_coords.length === 0)) {
    delete p.mini_coords
  }
  // 无动作时不参与比较
  if (Array.isArray(p.actions) && p.actions.length === 0) {
    delete p.actions
  }
  // 移除已废弃的旧字段
  delete p.use_items
  delete p.send_msgs
  delete p.skills
  delete p.is_cast_skill
  delete p.blink_dagger_coords
  // 任务归属：统一为排序后的数组，避免 string/单元素数组 及多选顺序差异导致误判
  if (p.task !== undefined) {
    const t = Array.isArray(p.task) ? [...p.task] : [p.task]
    if (t.length === 0) delete p.task
    else p.task = t.map(String).sort()
  }
  return p
}

/** 判断当前任务数据相对于原始快照是否发生有效修改。 */
export function isTaskDataChanged(current: any, original: any): boolean {
  return !deepEqual(normalizeForCompare(current), normalizeForCompare(original))
}
