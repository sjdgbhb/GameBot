# 无尽刷分任务

## 多局无尽

- **类名**：`EndlessTask`
- **源码**：`src/GameBot/tasks/endless/endless.py`
- **配置**：`config/data/tasks/endless/endless.toml`（继承 `endless_single.toml`）
- **运行命令**：`uv run python -m GameBot.tasks.endless.endless`
- **依赖**：`tasks.endless.endless_single` + `kk` + `heroes.hxd` + `scenes.menethil` + `scenes.palace`

### 功能

完整的多局无尽刷分流程，自动循环：KK 启动游戏 → War3 → 准备阶段 → 进皇宫 → 进无尽 → 刷怪循环 → 退出 → 下一局。

### 流程

1. **KK 阶段**：绑定 KK 窗口 → 启动游戏
2. **War3 阶段**（每局）：
   - 等待 War3 窗口出现（最多 30 秒）
   - 绑定窗口 → 设置客户端尺寸
   - 等待进入游戏（`wait_enter_game`）
   - 准备阶段（`do_preparation_phase`）：选难度、选英雄、读存、装备物品、学技能
   - 折叠属性面板 → 进皇宫 → 进无尽
   - 刷怪循环（`start_endless`）：按楼层循环清理怪物
   - 退出游戏（`quit_game`）
3. 循环 `games` 局后结束

## 单局无尽

- **类名**：`EndlessSingleTask`
- **源码**：`src/GameBot/tasks/endless/endless_single.py`
- **配置**：`config/data/tasks/endless/endless_single.toml`
- **运行命令**：`uv run python -m GameBot.tasks.endless.endless_single`
- **依赖**：`heroes.hxd`（间接依赖 `jiubing2` → `war3` → `base`）

### 功能

英雄已在无尽地图内（准备阶段已完成），直接循环刷怪。适用于手动完成准备阶段后挂机。

### 流程

1. 绑定窗口 → 设置客户端尺寸
2. 直接调用 `clear_endless_monster_loop` 按楼层循环刷怪

## 关键配置

| 配置项 | 说明 |
|--------|------|
| `games` | 游戏总局数（多局无尽） |
| `min_level` | 起始楼层 |
| `max_level` | 结束楼层 |
| `points` | 无尽地图路径点列表（coords / skills / time / walk_mode） |
| `refresh_timer` | 当层打完后至下一层开始的刷新时间 |
| `use_shard_floor` | 从该层开始使用魔法水晶 |
| `drink_floor` | 从该层开始喝药 |
| `pet_feed_interval` | 喂宠物间隔（秒） |
| `loop_interval_time` | 局间间隔时间 |
