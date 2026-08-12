# 钓鱼任务

## 基本信息

- **类名**：`FishingTask`
- **源码**：`src/GameBot/tasks/others/fishing.py`
- **配置**：`config/data/tasks/others/fishing.toml`
- **运行命令**：`uv run python -m GameBot.tasks.others.fishing`
- **依赖**：`heroes.hxd`（间接依赖 `jiubing2` → `war3` → `base`）

## 功能

自动完成钓鱼日常任务。支持两种模式：

- **慢速模式**（`fishing_mode = 0`）：OCR 检测钓鱼成功文本，达到目标成功次数后停止
- **快速模式**（`fishing_mode != 0`）：不检测成功，固定抛竿 N 次后停止

## 流程

1. 绑定窗口，设置客户端尺寸
2. 提高 Windows 定时器精度到 1ms（`timeBeginPeriod(1)`）
3. 慢速模式：预热 OCR 子进程（不加载 AI 模型），预计算 OCR 屏幕区域
4. 居中英雄视角
5. 循环抛竿：
   - 移动到钓鱼坐标 → 按钓鱼快捷键 → 左键点击
   - 轮询找色/找图检测中钩（红色三角形填充）
   - 检测到中钩立即按 S 收竿
   - 慢速模式：OCR 检测屏幕文本是否包含"钓"字（去重避免重复判定）
   - 每隔 `clear_interval` 次抛竿发送清屏消息
   - 慢速模式达到 `success_times` 次成功则停止
6. 恢复定时器精度（`timeEndPeriod(1)`）

## 关键配置

| 配置项 | 说明 |
|--------|------|
| `fishing_mode` | 0 = 慢速（OCR 检测成功），非 0 = 快速（固定次数） |
| `max_times` | 最大抛竿次数 |
| `success_times` | 慢速模式目标成功次数 |
| `fishing_hotkey` | 钓鱼快捷键 |
| `hook_coords` | 抛竿点击坐标 |
| `clear_interval` | 每隔多少次抛竿清屏一次 |
| `check.hook_color` | 中钩检测颜色（红色 `ff0000`） |
| `check.hook_sim` | 找色相似度 |
| `check.status_area_coords` | 中钩检测区域 |
| `check.hook_timeout` | 中钩等待超时（秒） |
| `check.hook_check_interval` | 中钩检测轮询间隔（秒） |

## 停止条件

- 达到任务次数停止（max_times / success_times）
- 收到停止信号（F6 / 浮窗停止按钮）