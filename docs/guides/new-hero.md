# 新增英雄配置

> 当需要添加新英雄时，按以下步骤操作。

## 1. 确认英雄信息

向用户询问以下信息（如果用户未提供）：
- **英雄名称**：英文蛇形命名（如 `paladin`、`spellblade`）
- **英雄中文名**：如"圣骑士"、"魔剑士"
- **英雄技能**：每个技能的描述、快捷键、目标类型、施法目标坐标
- **物品栏配置**：每个格子的物品 id 和快捷键

## 2. 创建英雄 TOML 配置文件

在 `src/GameBot/config/data/war3/jiubing2/heroes/` 下创建 `{hero_name}.toml`。

### 最小配置（仅需物品栏）
```toml
############## {英雄中文名} ##############
name = "war3.jiubing2.heroes.{hero_name}"
extends = ["war3.jiubing2"]

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
name = "{英雄中文名}"
floor_key = "O"
mini_coords = [186,900]  # 通过点击小地图来切换到目标英雄所在区域视角
coords = [1232,446]  # 英雄在选择界面的坐标
is_load = true             # 是否读取存档
load_save = "-load3"       # 存档读取指令（不同英雄存档命令可能不同）

# 技能
[[hero.skills]]
desc = '技能描述'
key = "Q"
target_type = "ground"     # self(自身/无指向) | ground(地面目标) | enemy(锁头敌方) | ally(锁头友军)
position = 'target_area'   # target_area(目标区域) 、target（目标），具体坐标需自行抓取后在路线点设置

# 连招技能序列
[[hero.combo_skills]]
desc = '技能描述'
key = "Q"
target_type = "ground"
position = 'target_area'

# 清小怪技能
[hero.clear_minion_skills]
desc = '技能描述'
key = "T"
target_type = "ground"
position = "target_area"

# 学习技能列表（按学习顺序）
[[hero.learn_skills]]
index_x = 1
index_y = 1

# 物品栏配置（背包1-6格）
[[hero.inventory]]
id = 1  # 血瓶
hotkey = "1"

[[hero.inventory]]
id = 8  # 魔法水晶
hotkey = "2"

[[hero.inventory]]
id = 4  # 传送至米奈希尔
hotkey = "3"

[[hero.inventory]]
id = 3  # 无敌
hotkey = "4"

[[hero.inventory]]
id = 9  # 宠物食物
hotkey = "5"

[[hero.inventory]]
id = 0  # 拾取
hotkey = "6"

# 圣痕
[hero.stigmata]
is_open = true
use_index = 1

# 卡牌
[hero.card]
is_open = true
use_index = [[1, 1]]

# 神碎
[hero.shard]
is_open = true
is_resonance = true
is_absorb = true
max_pages = 3
use_index = [[1, 2]]
absorb_index = [1, 4]
```

## 3. 物品 ID 参考表

物品 id 定义在 `jiubing2.toml` 的 `items` 中：

| id | 名称 |
|----|------|
| 0 | 拾取 |
| 1 | 血瓶 |
| 2 | 蓝瓶 |
| 3 | 无敌 |
| 4 | 米奈希尔传送卷轴 |
| 5 | 远古森林外围入口传送卷轴 |
| 6 | 跳刀 |
| 7 | 鱼竿 |
| 8 | 魔法水晶 |
| 9 | 宠物食物 |

## 4. 验证

- 检查 `name = "war3.jiubing2.heroes.{hero_name}"` 和 `extends = ["war3.jiubing2"]` 是否存在
- 检查物品栏是否包含 `item_id = 0`（拾取）项
- 确认在任务配置中通过 `extends = ["war3.jiubing2.heroes.{hero_name}"]` 引用此英雄
- **英雄配置互斥**：`heroes.*` 中最后加载的英雄独占生效

## 相关文档

- [配置系统](../modules/config.md) —— 英雄互斥和继承机制
- [游戏机制](../domain/game-mechanics.md) —— 物品/技能/圣痕/卡牌/神碎系统
- [业务逻辑层](../modules/business.md) —— 英雄配置如何被业务代码使用
