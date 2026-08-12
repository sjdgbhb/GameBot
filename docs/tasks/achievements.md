# 成就任务

## 个人任务成就

- **类名**：`PersonalAchievementTask`
- **源码**：`src/GameBot/runner/tasks/achievements/personal.py`
- **配置**：`config/data/tasks/achievements/personal.toml`
- **运行命令**：`.venv-dm/Scripts/python.exe -m GameBot.runner.tasks.achievements.personal`
- **依赖**：`tasks.atomic.venomous_snake` + `tasks.atomic.snake_egg` + `tasks.atomic.little_flame_snake` + `heroes.hxd`
- **继承**：`MultiAtomicLoopTask`

## 功能

完成一定次数的任务以达成个人成就。当前配置为卡米村村民杰菲特的 3 个任务（毒蛇、蛇蛋、小炎蛇（LV4）），一次性接取多个原子任务 → 走共享路线同时完成 → 依次提交，每次提交算 1 次。

## 流程

1. 绑定窗口，预热 OCR，启动 `TextMonitor` 常驻监测
2. 每轮循环：
   - **接取阶段**：依次走到 NPC 接取所有任务（跳过前置未完成 / 冷却中的任务）
   - **共享路线阶段**：沿 `points` 推进，屏幕提示完成时 `-rw` 查询弹窗确认是否全部完成
   - **提交阶段**：依次走到 NPC 自动提交，记录提交时间戳用于冷却判断
3. 总轮数 = `ceil(task_times / N)`，N = `atomic_tasks` 数量

## 前置任务机制

小炎蛇（LV4）有前置要求：本局必须完成至少一次毒蛇才能接取。
- `LittleFlameSnakeTask.prerequisite_done` 类属性默认 `False`
- 第一轮：跳过小炎蛇，只接取毒蛇 + 蛇蛋 → 提交毒蛇后设置 `prerequisite_done = True`
- 第二轮起：小炎蛇前置已解锁，3 个任务全部接取

## 刷新冷却机制

- 毒蛇 / 蛇蛋：60 秒刷新（`respawn_time = 60`）
- 小炎蛇（LV4）：300 秒刷新（`respawn_time = 300`）
- 提交后记录时间戳，下一轮接取前检查冷却，未冷却则跳过
- 轮间等待 `max(最短冷却时间, loop_interval_time)`

## 关键配置

| 配置项 | 说明 |
|--------|------|
| `task_times` | 需要完成的任务总次数 |
| `loop_interval_time` | 两轮之间的间隔（秒） |
| `monitor_interval` | OCR 监测线程的轮询间隔（秒） |
| `clear_nearby_interval` | 定时清理英雄附近物品间隔（秒） |
| `route_complete_timeout` | 路线走完仍未全部完成的兜底超时（秒） |
| `atomic_tasks` | 原子任务列表（key + walk_time），仅用于接取/提交阶段 |
| `points` | 共享路线点列表，控制路线阶段的行走路径 |
