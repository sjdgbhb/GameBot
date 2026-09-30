# 新增英雄配置

> 当需要添加新英雄时，按以下步骤操作。

## 1. 确认英雄信息

向用户询问以下信息（如果用户未提供）：
- **英雄名称**：英文蛇形命名（如 `paladin`、`spellblade`）
- **英雄中文名**：如"圣骑士"、"魔剑士"
- **英雄技能**：每个技能的描述、快捷键、目标类型、施法目标坐标
- **物品栏配置**：每个格子的物品名（快捷键由 `kk.toml` 的 `inventory_slots`
  统一映射，英雄文件不写 hotkey）

## 2. 创建英雄 TOML 配置文件

在 `src/GameBot/config/data/war3/jiubing2/heroes/` 下创建 `{hero_name}.toml`。

### 最小配置（仅需物品栏）
```toml
############## {英雄中文名} ##############
extends = ["war3.jiubing2"]

[hero]
name = "{英雄中文名}"

inventory = [
  {slot = 0, item = "血瓶"},
  {slot = 5, item = "拾取"},
]
```

### 完整配置（含技能、学习顺序等）
```toml
############## {英雄中文名} ##############
extends = ["war3.jiubing2"]

[hero]
name = "{英雄中文名}"
floor_key = "O"
mini_coords = [186,900]  # 通过点击小地图来切换到目标英雄所在区域视角
coords = [1232,446]  # 英雄在选择界面的坐标
load_save = "-load3"       # 存档读取指令（不配置则跳过读档；不同英雄存档命令可能不同）

# 技能
# id: 技能池内序号（仅兼容旧引用）；desc 为技能名，路线点/任务用 skill = "desc" 引用
# key: 游戏内快捷键
# target_type: self(自身/无指向) | ground(地面目标) | enemy(锁头敌方) | ally(锁头友军)
# position: target_area(目标区域) 、target（目标），具体坐标需自行抓取后在路线点设置
skills = [
  {id = 0, desc = '技能描述', key = "Q", target_type = "ground", position = 'target_area'},
]

# 学习技能列表（按学习顺序）
learn_skills = [
  {index_x = 1, index_y = 1},
]

# 物品栏配置（背包1-6格）
# slot: 格子编号 0~5 对应第 1~6 格
# item: 物品名（映射表在 jiubing2.toml 的 items 中，load_task 时解析为 item_id）
# 快捷键从 kk.toml 的 inventory_slots 默认配置中查找，无需在此重复配置
inventory = [
  {slot = 0, item = "血瓶"},
  {slot = 1, item = "水晶"},
  {slot = 2, item = "米奈希尔传送卷轴"},
  {slot = 3, item = "跳刀"},
  {slot = 4, item = "宠物食物"},
  {slot = 5, item = "拾取"},
]

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

## 3. 物品名 ↔ ID 参考表

配置里写 `item = "名称"`，`load_task` 时按 `jiubing2.toml` 的 `items`
解析为 `item_id`（业务侧只读 `item_id`）：

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

- 检查 `extends = ["war3.jiubing2"]` 是否存在（配置名由文件路径自动推导，无需顶层 `name`）
- 检查物品栏是否包含 `item = "拾取"`（拾取）项
- 确认在任务配置中通过 `extends = ["war3.jiubing2.heroes.{hero_name}"]` 引用此英雄
- **英雄配置互斥**：`heroes.*` 中最后加载的英雄独占生效

## 相关文档

- [配置系统](../modules/config.md) —— 英雄互斥和继承机制
- [游戏机制](../domain/game-mechanics.md) —— 物品/技能/圣痕/卡牌/神碎系统
- [业务逻辑层](../modules/business.md) —— 英雄配置如何被业务代码使用
