---
name: new-variant
description: 生成多开单任务变体配置（tasks/<组>/<任务>_<玩家名>.toml）
argument-hint: "<组>/<任务> <玩家名>"
---

# 生成多开变体配置文件

为某个支持多开认领的任务生成玩家变体 TOML。约定见 AGENTS.md「多开单任务（非组队）用法」。

**参数**：`<组>/<任务>` + `<玩家名>`，如 `endless/endless 火焰头槌`、`others/fishing 善木木`。
若用户未给出玩家名或任务名，先询问补齐。

## 步骤

### 1. 确认任务支持变体

任务代码须支持 `target_player` 认领（找 `self.war3.target_player =` / `claim_war3_window` 等）。
已确认支持：endless/endless、endless/endless_single、others/fishing、others/game_count、
others/patrol_loot、others/upgrade_stigmata、festival/ingame_special、achievements/personal、
wind_dragon/paladin_wind_dragon。若任务不在列，先读任务源码确认是否走认领链路再生成。

### 2. 生成模板

```bash
uv run python -m GameBot.config new war3.jiubing2.tasks.<组>.<任务>_<玩家名>
```

该命令检测到同目录基任务存在时自动输出变体骨架（extends 基任务 + [this] target_player）。

### 3. 填写差异字段

- `[this] target_player = "<玩家名>"` —— 必填，认领归属判据
- **取消注释** `[war3]` 与 `[kk]` 的 `bind_mode = "background"` —— 多开必须后台绑定
  （注意：`[this]` 段不支持 bind_mode，必须写到命名空间段）
- 可选 `[base.float_window] y = <值>` —— 多实例并存时错开浮窗；先看同组已有变体用了哪些 y 再取未占用的值
- 可选 `[war3.jiubing2.tasks.<组>.<任务>]` 绝对寻址段 —— 覆盖基任务参数（如 games、max_times）
- 可选 `[hero.*]` 覆盖账号差异配置 —— hero 为浅合并，子键（如 shard/card/stigmata）整表覆盖，
  须把该子表字段写全，不能只写差异键

头部注释补全：变体说明 + 启动命令 + 启动要求（账号停留在自己的 KK 密码房内）。

### 4. 校验

```bash
uv run python -m GameBot.config lint                                          # 结构校验（变体应只 extends 基任务）
uv run python -m GameBot.config order war3.jiubing2.tasks.<组>.<任务>_<玩家名>  # 确认 extends 闭包正确
uv run python -m GameBot.config explain war3.jiubing2.tasks.<组>.<任务>_<玩家名> this.target_player
```

lint 警告「变体应只 extends 基任务」必须修正；extends 只允许 `[基任务配置名]`。

### 5. 输出使用说明

告知用户：
- 启动：`uv run python -m GameBot.runner.tasks.war3.jiubing2.<组>.<任务> <任务>_<玩家名>`
- 前置条件：该账号已创建/进入自己的 KK 密码房
- 认领失败会终止任务（防止误操作他人窗口）；浮窗 NumPad- 停止键是全局热键，多实例会一起停，单独停用各浮窗 ✕
- exe 用户：`config/data/` 全量打进包内，变体 TOML 运行时按名加载，无需重新打包

## 参考样例

`src/GameBot/config/data/war3/jiubing2/tasks/endless/endless_善木木.toml`（含 hero 覆盖）、
`.../festival/ingame_special_善木木.toml`（含绝对寻址参数覆盖）。
