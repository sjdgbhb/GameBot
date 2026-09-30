# 刷装备

## 基本信息

- **类名**：`PatrolLootTask`
- **源码**：`src/GameBot/runner/tasks/war3/jiubing2/others/patrol_loot.py`
- **配置**：`config/data/war3/jiubing2/tasks/others/patrol_loot.toml`
- **运行命令**：`uv run python -m GameBot.runner.tasks.war3.jiubing2.others.patrol_loot`
- **依赖**：`war3.jiubing2` + `kk`（`chest`/`item_text`/`pickup`/`combat_status`
  等通用识别配置在 jiubing2.toml）
- **多开变体**：`patrol_loot_<玩家名>.toml`（`[this] target_player` +
  `[war3]`/`[kk]` `bind_mode="background"`），启动
  `... others.patrol_loot patrol_loot_善木木`；认领失败任务直接停止

## 功能

在指定路线点循环巡逻杀怪，AI 检测地面宝箱，OCR 识别物品名称，自动拾取目标物品。支持浮窗控制（小键盘减号停止）。

## 流程

1. 绑定窗口，预热推理（OCR + 宝箱检测 + 战斗检测模型）
2. 启动 `TextMonitor` 常驻文字监测线程
3. 按轮次循环：
   - 遍历路线点：小地图导航到点 → 执行动作（技能/物品/消息）→ 等待脱离战斗 → 喂宠物
   - 拾取循环：
     - WGC 全屏取帧 → YOLOv8 检测宝箱位置
     - 逐个悬停宝箱 → OCR 读取物品名称 → 匹配目标物品 → 使用快速拾取功能拾取 → 监测"不可点击"/"储物箱已满"提示
     - 不可点击时 ESC 取消并重试（最多 `max_retries` 次）
     - 非目标物品加入跳过列表
   - 储物箱满或所有目标物品拾取完毕 → 进入仅喂宠物模式
4. 清理地面物品

## 关键配置

| 配置项 | 说明 |
|--------|------|
| `patrol.rounds` | 巡逻轮数（0 = 无限） |
| `route_scheme` | 路线方案名，从 `route_presets` 中按名选取 |
| `route_presets` | 预置路线方案列表，各含 `points`（mini_coords / coords / time / walk_mode / actions） |
| `points` | 用户自定义路线点，配置后优先于 `route_scheme` |
| `desired_items` | 目标物品列表，支持 `[{name, count}, ...]` 或 `["name", ...]` |
| `mouse_avoid_pos` | 巡逻时鼠标避让位置 |
| `feed_only_interval` | 仅喂宠物模式下的喂食间隔 |
| `clear_nearby_interval` | 定时清理附近物品间隔（0 = 禁用） |
| `chest` | 宝箱检测配置（jiubing2.toml：YOLOv8 模型路径、置信度阈值） |
| `item_text` | 物品名称 OCR 区域配置（jiubing2.toml） |
| `pickup` | 拾取配置（jiubing2.toml：max_retries / retry_interval / result_timeout） |
| `combat_status` | 战斗状态检测配置（jiubing2.toml：AI 模型、截图帧数、间隔） |

## 停止条件

- 所有目标物品已拾取到目标数量
- 储物箱已满
- 收到停止信号（小键盘减号 / 浮窗 ✕ 按钮）
