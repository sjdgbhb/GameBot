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

1. **KK 阶段**：认领本账号房间窗口（`claim_own_room`：注册表命中 kk_pid 直接
   按 PID 判定，未知时房间聊天 token 自举并写 `kk_owner`）→ 启动游戏
2. **War3 阶段**（每局）：
   - **PPID 认领**（`claim_war3_window`）：`ppid(war3_pid) == kk_pid` 直接父进程
     比对（纯只读、读图期窗口零操作、任意游戏阶段可用）；认领失败抛
     `ClaimError` 终止任务
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

- **认领失败**：`claim_room_window`/`claim_war3_window` 超时抛 `ClaimError`
  终止任务，避免误操作另一账号窗口；绝不对未认领窗口发退出键清场
- **卡在加载页**：`wait_enter_game` 超时后绑定已认领窗口发退出键，跳过本局
- **War3 窗口消失**：按掉线处理，走 KK 掉线重连弹窗清理（多开按注册表
  `kk_pid` 过滤，任务层无需传 `owner_pid`）

## 单局无尽

- **类名**：`EndlessSingleTask`
- **源码**：`src/GameBot/runner/tasks/war3/jiubing2/endless/endless_single.py`
- **配置**：`config/data/war3/jiubing2/tasks/endless/endless_single.toml`
- **运行命令**：`uv run python -m GameBot.runner.tasks.war3.jiubing2.endless.endless_single`
- **依赖**：`heroes.hxd`（间接依赖 `jiubing2` → `war3` → `base`）
- **多开变体**：`endless_single_<玩家名>.toml`（`[this] target_player` +
  `[war3]`/`[kk]` `bind_mode="background"`），启动
  `... endless_single endless_single_善木木`；局内任务认领——启动时已在
  游戏内，war3 侧按 `ppid(war3_pid) == kk_pid` 判定（kk_pid 未知时聊天
  token 自举），认领失败抛 `ClaimError` 任务停止

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
