# 刷装备

## 基本信息

- **类名**：`PatrolLootTask`
- **源码**：`src/GameBot/tasks/others/patrol_loot.py`
- **配置**：`config/data/tasks/others/patrol_loot.toml`
- **运行命令**：`uv run python -m GameBot.tasks.others.patrol_loot`
- **依赖**：`heroes.hxd`（间接依赖 `jiubing2` → `war3` → `base`）

## 功能

在指定路线点循环巡逻杀怪，AI 检测地面宝箱，OCR 识别物品名称，自动拾取目标物品。支持浮窗控制（F6 停止）。

## 流程

1. 绑定窗口，初始化推理子进程（OCR + 宝箱检测 + 战斗检测模型）
2. 启动 `TextMonitor` 常驻文字监测线程
3. 按轮次循环：
   - 遍历路线点：小地图导航到点 → 施放移动前/后技能 → 等待脱离战斗 → 喂宠物
   - 拾取循环：
     - 全屏截图 → YOLOv8 检测宝箱位置
     - 逐个悬停宝箱 → OCR 读取物品名称 → 匹配目标物品 → 使用快速拾取功能拾取 → 监测"不可点击"/"储物箱已满"提示
     - 不可点击时 ESC 取消并重试（最多 `max_retries` 次）
     - 非目标物品加入跳过列表
   - 储物箱满或所有目标物品拾取完毕 → 进入仅喂宠物模式
4. 清理地面物品

## 关键配置

| 配置项 | 说明 |_``
|--------|------|
| `patrol.rounds` | 巡逻轮数（0 = 无限） |
| `points` | 路线点列表（mini_coords / coords / skills / time / walk_mode） |
| `desired_items` | 目标物品列表，支持 `[{name, count}, ...]` 或 `["name", ...]` |
| `chest` | 宝箱检测配置（YOLOv8 模型路径、置信度阈值） |
| `item_text` | 物品名称 OCR 区域配置（offset_y / area_width / area_height） |
| `pickup` | 拾取配置（max_retries / retry_interval / result_timeout） |
| `combat_status` | 战斗状态检测配置（AI 模型、截图帧数、间隔） |

## 停止条件

- 所有目标物品已拾取到目标数量
- 储物箱已满
- 收到停止信号（F6 / 浮窗停止按钮）
