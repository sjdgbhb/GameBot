---
description: 新增英雄配置 — 在 config/heroes/ 下创建英雄 TOML 配置文件
---

# 新增英雄配置工作流

当用户需要添加新英雄时，按以下步骤操作：

## 1. 确认英雄信息

向用户询问以下信息（如果用户未提供）：
- **英雄名称**：英文蛇形命名（如 `paladin`、`spellblade`）
- **英雄中文名**：如"圣骑士"、"法刃"
- **英雄技能**：每个技能的描述、快捷键、目标类型、定位
- **物品栏配置**：每个格子的物品 id 和快捷键

## 2. 创建英雄 TOML 配置文件

在 `src/GameBot/config/data/war3/jiubing2/heroes/` 下创建 `{hero_name}.toml`。

### 最小配置（仅需物品栏）

```toml
############## {英雄中文名} ##############
name = "war3.jiubing2.heroes.{hero_name}"
extends = ["war3.jiubing2"]

# ------------------------------ 物品栏配置（背包1-6格） ------------------------------
[hero]
name = "{英雄中文名}"

inventory = [
  {slot = 0, item_id = 1},  # 血瓶
  {slot = 5, item_id = 0},  # 拾取
]
```

### 完整配置（含技能、连招、学习顺序等）

```toml
############## {英雄中文名} ##############
name = "war3.jiubing2.heroes.{hero_name}"
extends = ["war3.jiubing2"]

[hero]
floor_key = "X"           # 无尽楼层快捷键
coords = [1185, 333]       # 英雄在选择界面的坐标
is_load = true             # 是否读取存档
load_save = "-load3"       # 存档读取指令

# ------------------------------ 技能 ------------------------------
[[hero.skills]]
desc = '技能描述'
key = "Q"
target_type = "ground"     # ground=地面目标, self=自身, point=点
position = 'target_area'   # target_area 或其他定位方式

# ------------------------------ 连招技能序列 ------------------------------
[[hero.combo_skills]]
desc = '技能描述'
key = "Q"
target_type = "ground"
position = 'target_area'

# ------------------------------ 清小怪技能 ------------------------------
[hero.clear_minion_skills]
desc = '技能描述'
key = "T"
target_type = "ground"
position = "target_area"

# ------------------------------ 学习技能列表（按学习顺序） ------------------------------
[[hero.learn_skills]]
index_x = 1
index_y = 1

# ------------------------------ 物品栏配置（背包1-6格） ------------------------------
[[hero.inventory]]
id = 1  # 物品id，详见 jiubing2.toml [[items]] 定义
hotkey = "1"

[[hero.inventory]]
id = 8  # 魔法水晶
hotkey = "2"

[[hero.inventory]]
id = 4  # 传送至米奈希尔
hotkey = "3"

[[hero.inventory]]
id = 3  # 跳刀/无敌
hotkey = "4"

[[hero.inventory]]
id = 9  # 宠物食物
hotkey = "5"

[[hero.inventory]]
id = 0  # 拾取
hotkey = "6"

# ------------------------------ 圣痕 ------------------------------
[hero.stigmata]
is_open = true
use_index = 1

# ------------------------------ 卡牌 ------------------------------
[hero.card]
is_open = true
use_index = [
    [1, 1],
]

# ------------------------------ 神碎 ------------------------------
[hero.shard]
is_open = true
is_resonance = true
is_absorb = true
max_pages = 3
use_index = [
    [1, 2],
]
absorb_index = [1, 4]
```

## 3. 物品 id 参考表

物品 id 定义在 `jiubing2.toml` 的 `[[items]]` 中：

| id | 名称 |
|----|------|
| 0  | 拾取 |
| 1  | 血瓶 |
| 2  | 蓝瓶 |
| 3  | 无敌 |
| 4  | 传送至米奈希尔的卷轴 |
| 5  | 传送至远古森林外围入口的卷轴 |
| 6  | 跳刀 |
| 7  | 鱼竿 |
| 8  | 魔法水晶 |
| 9  | 宠物食物 |

## 4. 验证

- 检查 `name = "war3.jiubing2.heroes.{hero_name}"` 和 `extends = ["war3.jiubing2"]` 是否存在
- 检查物品栏是否包含 `item_id = 0`（拾取）项
- 确认在任务配置中通过 `extends = ["war3.jiubing2.heroes.{hero_name}"]` 引用此英雄
- 英雄配置互斥：heroes.* 中最后加载的英雄独占生效
