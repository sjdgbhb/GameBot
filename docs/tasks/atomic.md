# 原子任务

原子任务是可被其他任务复用的最底层任务单元。每个原子任务完成一次完整的"接取 → 执行 → 提交"流程。

## 迅猛野兽

- **类名**：`SwiftBeastTask`
- **源码**：`src/GameBot/runner/tasks/atomic/swift_beast.py`
- **配置**：`config/data/tasks/atomic/swift_beast.toml`
- **场景**：森之城
- **NPC**：月之女祭司狄安娜

### 流程

1. 走到狄安娜附近（小地图导航）
2. 点击 NPC → 点击迅猛野兽任务格 → OCR 检测“已领取”
3. 沿路线点推进，后台 OCR 实时监测"前往任务发布者处完成任务"提示
4. 检测到完成后立即中断移动，返回最后一个路线点（NPC 附近）自动提交任务

### 关键特性

- **事件中断移动**：`move_to_minimap_point` 接受 `stop_event` 参数，OCR 检测到完成立即中断
- **at_npc 优化**：首轮后英雄停在 NPC 旁，跳过行走

## 城门骚扰

- **类名**：`GateHarassmentTask`
- **源码**：`src/GameBot/runner/tasks/atomic/blackstone_gate_harassment.py`
- **配置**：`config/data/tasks/atomic/blackstone_gate_harassment.toml`
- **场景**：黑石城
- **NPC**：守卫队长

### 流程

1. 走到守卫队长附近（小地图导航）
2. 点击 NPC → 点击城门骚扰任务格 → OCR 检测“已领取”
3. 沿路线点推进，后台 OCR 实时监测"前往任务发布者处完成任务"提示
4. 检测到完成后立即中断移动，返回最后一个路线点（NPC 附近）自动提交任务

### 关键特性

与迅猛野兽任务结构完全一致，仅 NPC、场景、路线点不同。

## 毒蛇

- **类名**：`VenomousSnakeTask`
- **源码**：`src/GameBot/runner/tasks/atomic/venomous_snake.py`
- **配置**：`config/data/tasks/atomic/venomous_snake.toml`
- **场景**：卡米村
- **NPC**：村民杰菲特
- **技能格**：`[1, 1]`
- **刷新**：60 秒（`respawn_time = 60`）

### 流程

走到村民杰菲特 → 点技能格接取 → 沿农场路线清毒蛇 → OCR 检测完成 → 回 NPC 提交。

## 蛇蛋

- **类名**：`SnakeEggTask`
- **源码**：`src/GameBot/runner/tasks/atomic/snake_egg.py`
- **配置**：`config/data/tasks/atomic/snake_egg.toml`
- **场景**：卡米村
- **NPC**：村民杰菲特
- **技能格**：`[1, 2]`
- **刷新**：60 秒（`respawn_time = 60`，共享毒蛇刷新）

### 流程

走到村民杰菲特 → 点技能格接取 → 沿农场路线杀毒蛇掉落蛇蛋 → OCR 检测完成 → 回 NPC 提交。

### 注意

蛇蛋通过杀毒蛇掉落完成，农场共 6 只毒蛇，大概率完成，小概率差一两个（超时后未完成的不会自动提交）。

## 小炎蛇（LV4）

- **类名**：`LittleFlameSnakeTask`
- **源码**：`src/GameBot/runner/tasks/atomic/little_flame_snake.py`
- **配置**：`config/data/tasks/atomic/little_flame_snake.toml`
- **场景**：卡米村
- **NPC**：村民杰菲特
- **技能格**：`[1, 3]`
- **刷新**：300 秒（`respawn_time = 300`）
- **前置要求**：本局必须完成至少一次毒蛇才能接取

### 前置机制

- `LittleFlameSnakeTask.prerequisite_done` 类属性默认 `False`
- `MultiAtomicLoopTask` 提交毒蛇后设置为 `True`
- 接取前检查该标志，未完成则跳过

## 关键配置

| 配置项 | 说明 |
|--------|------|
| `points` | 路线点列表（mini_coords / coords / desc / time / walk_mode） |
| `accept_timeout` | 接取任务检测超时（秒） |
| `route_complete_timeout` | 路线走完后等待完成的兜底超时（秒） |
| `complete_check_interval` | 完成检测轮询间隔（秒） |
| `respawn_time` | 杀怪后刷新间隔（秒），用于冷却判断 |

## 被谁复用

| 上游任务 | 原子任务 |
|----------|----------|
| `ForestReputationTask` | `SwiftBeastTask` |
| `BlackstoneReputationTask` | `GateHarassmentTask` |
| `UpgradeStigmataTask` | `GateHarassmentTask` |
| `PersonalAchievementTask` | `VenomousSnakeTask` + `SnakeEggTask` + `LittleFlameSnakeTask` |
