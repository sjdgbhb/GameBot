# 无尽刷分任务

## 多局无尽

- **类名**：`EndlessTask`
- **源码**：`src/GameBot/runner/tasks/war3/jiubing2/endless/endless.py`
- **配置**：`config/data/war3/jiubing2/tasks/endless/endless.toml`（继承 `endless_single.toml`）
- **运行命令**：`uv run python -m GameBot.runner.tasks.war3.jiubing2.endless.endless`
- **依赖**：`war3.jiubing2.tasks.endless.endless_single`（传递带入 `heroes.hxd`）+
  `kk` + `war3.jiubing2.scenes.menethil` + `war3.jiubing2.scenes.palace`
- **多开变体**：`endless_<玩家名>.toml`（`target_player` + `bind_mode="background"`），
  启动 `... endless endless_善木木`

### 功能

完整的多局无尽刷分流程，自动循环：KK 启动游戏 → War3 → 准备阶段 → 进皇宫 → 进无尽 → 刷怪循环 → 退出 → 下一局。

### 流程

1. **KK 阶段**：认领本账号房间窗口（多开按 `target_player` 聊天 token 判归属）→ 启动游戏
2. **War3 阶段**（每局）：
   - **加载页只读认领**（`claim_war3_window`）：读图期对窗口零操作（不占窗口、
     不改尺寸、不绑定）——分阶段归属验证：加载页 OCR 玩家列表 /
     已进游戏且无难度界面时聊天 token / 难度界面在场则跳过本轮
   - 无绑定 WGC 轮询等待进入游戏（`wait_enter_game(hwnd)`）
   - 统一客户端尺寸 → 绑定窗口
   - 等待并按本账号配置选择难度（`wait_and_select_difficulty`）
   - 准备阶段（`do_preparation_phase`）：选英雄、读存、装备物品、学技能
     （init 等待扣除难度选定后已流逝时间）
   - 折叠属性面板 → 进皇宫 → 进无尽
   - 刷怪循环（`start_endless`）：按楼层循环清理怪物
   - 退出游戏（`quit_game`）
3. 循环 `games` 局后结束

### 异常处理

- **认领失败（多开）**：直接终止任务，避免误操作另一账号窗口；绝不对未认领
  窗口发退出键清场（未进游戏的窗口可能属于其他玩家）
- **未找到窗口（单开）**：对所有未认领 war3 窗口发退出键清场
  （`_quit_stuck_war3_windows`，单开时本机窗口必属本玩家），跳过本局
- **卡在加载页**：`wait_enter_game` 超时后绑定已认领窗口发退出键，跳过本局
- **War3 窗口消失**：按掉线处理，走 KK 掉线重连弹窗清理（多开按 `owner_pid` 过滤）

## 单局无尽

- **类名**：`EndlessSingleTask`
- **源码**：`src/GameBot/runner/tasks/war3/jiubing2/endless/endless_single.py`
- **配置**：`config/data/war3/jiubing2/tasks/endless/endless_single.toml`
- **运行命令**：`uv run python -m GameBot.runner.tasks.war3.jiubing2.endless.endless_single`
- **依赖**：`heroes.hxd`（间接依赖 `jiubing2` → `war3` → `base`）
- **多开变体**：`endless_single_<玩家名>.toml`（`[this] target_player` +
  `[war3]`/`[kk]` `bind_mode="background"`），启动
  `... endless_single endless_single_善木木`；局内任务认领——启动时已在
  游戏内，发聊天 token 按"玩家名：token"回显定归属，认领失败任务停止

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
