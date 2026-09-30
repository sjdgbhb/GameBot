# 钓鱼任务

## 基本信息

- **类名**：`FishingTask`
- **源码**：`src/GameBot/runner/tasks/war3/jiubing2/others/fishing.py`
- **配置**：`config/data/war3/jiubing2/tasks/others/fishing.toml`
- **运行命令**：`uv run python -m GameBot.runner.tasks.war3.jiubing2.others.fishing`
  （或 `uv run python main.py fishing`）
- **依赖**：`war3.jiubing2` + `kk`（鱼竿在任务 `[hero]` 段的 inventory 里配置）
- **多开变体**：`fishing_<玩家名>.toml`（`[this] target_player` + `[war3]`/`[kk]`
  `bind_mode="background"`），启动 `... others.fishing fishing_善木木`；
  认领失败任务直接停止

## 功能

自动抛竿钓鱼：填充条循环稳定（实测 ~3.1s），用红色三角形出现时刻加周期
推算下次中钩时刻，提前 `retract_lead_time` 秒预判收竿，补偿按键到游戏执行
的固有延迟（约 100~200ms）。周期跨竿缓存：首竿等 2 次红色出现实测周期，
后续竿只等 1 次即可出手。

## 流程

1. 绑定窗口（`bind_mode` 默认后台），设置客户端尺寸
2. 循环抛竿：
   - F1×2 居中视角 → 移动到 `hook_coords` → 按物品栏快捷键（鱼竿）→ 左键点击
   - 轮询检测中钩：`mode=0` 找色（红色 `ff0000`），`mode=1` 先找图再找色兜底
   - 预判收竿（按实测填充周期提前按键）
   - OCR `prompt_text.last_area_coords` 区域检测成功文本（去重计数）
   - 每次收竿后按 `clear_nearby_probability` 概率发送清屏指令
3. 达到 `max_times` 抛竿次数后停止

## 关键配置

| 配置项 | 说明 |
|--------|------|
| `mode` | 中钩检测方式：0 = 找色，1 = 找图（未命中找色兜底） |
| `max_times` | 最大抛竿次数 |
| `fishing_interval_time` | 每次钓鱼间隔（秒） |
| `hook_coords` | 抛竿点击坐标 |
| `is_test_check` | 测试模式：抛竿后框选检测区域，用于校准 `status_area_coords` |
| `clear_nearby_probability` | 每次收竿后清理附近物品的概率（0~1） |
| `check.status_area_coords` | 中钩检测区域 |
| `check.hook_color` / `check.hook_delta_color` | 找色颜色与每通道容差 |
| `check.hook_status_image` / `check.hook_sim` | 找图模板与相似度 |
| `check.retract_lead_time` | 预判收竿提前量（秒），偏晚调大、过早调小 |
| `check.hook_timeout` / `check.hook_check_interval` | 中钩等待超时 / 轮询间隔 |

> 钓鱼快捷键不写配置：由 `hero.inventory` 中鱼竿所在格子经 `inventory_slots`
> 映射得到。

## 停止条件

- 达到 `max_times` 抛竿次数
- 收到停止信号（小键盘减号 / 浮窗 ✕ 按钮）
