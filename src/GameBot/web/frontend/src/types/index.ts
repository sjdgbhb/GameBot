/** 全局类型定义 */

export interface TaskInfo {
  id: string
  short_id: string
  category: string
  name: string
  icon: string
  description: string
  configurable?: boolean
}

export interface SkillDef {
  id: number
  desc: string
  key: string
  target_type: string
  fixed_key?: boolean
}

export interface HeroInfo {
  id: string
  name: string
  floor_key: string
  inventory: InventorySlot[]
  skills?: SkillDef[]
}

export interface ItemDef {
  id: number
  name: string
}

export interface CommandDef {
  key: string
  cmd: string
}

export interface InventorySlot {
  id: number
  hotkey: string
}

export interface DesiredItem {
  name: string
  count: number
}

export interface RoutePoint {
  desc: string
  mini_coords?: [number, number]
  coords?: [number, number]
  time: number
  walk_mode: number
  use_items?: string[]
}

export interface RunningTask {
  id: string
  pid: number
}

// ---- Schema 类型 ----

export type FieldType = 'text' | 'hotkey' | 'number' | 'select' | 'radio' | 'switch' | 'checkbox' | 'coords' | 'hero' | 'inventory' | 'desired_items' | 'points' | 'route_scheme' | 'stigmata_matrix'

export interface SchemaField {
  key: string
  label: string
  type: FieldType
  default?: any
  min?: number
  max?: number
  step?: number
  help?: string
  placeholder?: string
  maxlength?: number
  short?: boolean
  width?: string
  controls?: boolean
  size?: 'small' | 'default' | 'large' | string
  options?: { value: any; label: string }[]
  valueType?: 'number' | 'boolean'
  unit?: string
  showIf?: { field: string; value: any }
  taskOptions?: { value: string; label: string }[]
}

export interface SchemaSection {
  key: string
  title: string
  help?: string
  comment?: string
  content?: string
  fields?: SchemaField[]
}

export interface TaskSchema {
  id: string
  name: string
  description?: string
  sections: SchemaSection[]
  defaults: Record<string, any>
}

// ---- API 响应 ----

export interface InitResponse {
  tasks: TaskInfo[]
  heroes: HeroInfo[]
  items: ItemDef[]
  farmable_items: string[]
  commands: CommandDef[]
  configs: Record<string, any>
}

export interface OkResponse {
  ok: boolean
  error?: string
}

export interface StartTaskResponse {
  ok: boolean
  pid?: number
  log?: string
  error?: string
  running?: boolean
}

export interface RunningTasksResponse {
  tasks: RunningTask[]
}

export interface HeroImportBatchResponse {
  ok: boolean
  saved: string[]
  errors: string[]
}

// ---- 任务分组 ----

export interface TaskGroup {
  key: string
  label: string
  icon?: string
  tasks: TaskInfo[]
}
