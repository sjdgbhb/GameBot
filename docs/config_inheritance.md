# 配置继承规则文档

## 概述

本项目使用 TOML 配置文件系统，通过 **依赖声明 + 命名空间隔离** 实现树形继承，最终产出一份类 JSON 的全局配置对象。

核心代码位于 `src/GameBot/config/system/`，采用 mixin 架构：

| 模块 | 职责 |
|------|------|
| `base.py` | `ConfigurationError` 异常 + 常量（`EXCLUSIVE_NAMESPACES`、`CONTROL_KEYS`） |
| `loader.py` | `ConfigLoaderMixin` — TOML 文件加载缓存、配置名到文件路径映射、命名空间根集合发现、可继承/命名空间节点拆分 |
| `resolver.py` | `ConfigResolverMixin` — DFS 后序依赖解析、循环依赖检测 |
| `builder.py` | `ConfigBuilderMixin` — 按加载顺序合并配置、深度合并、英雄互斥处理 |
| `user.py` | `ConfigUserMixin` — `user_configs.json` 加载与用户覆盖应用 |
| `core.py` | `Config` 单例类，组合所有 mixin，提供 `load_task` / `get` / `get_section` / `__getitem__` 接口 |

---

## 五条继承规则

### 规则 1：依赖继承

配置文件通过顶层 `dependencies` 数组声明依赖：

```toml
dependencies = ["heroes.hxd", "scenes.forest_city"]
```

- 按**深度优先后序**（DFS post-order）递归展开依赖链，生成线性加载顺序。
- 每个文件只加载一次（类似 Python import），首次到达的位置生效。
- **后加载覆盖先加载**：同名可继承节点**深度合并**（未覆盖的字段从父配置继承，已覆盖的字段递归覆盖）。
- dependencies负责把依赖的TOML加载到cfg树中，代码负责从各命名空间分别取值

示例依赖链：

```
tasks.daily_reputation
  → tasks.blackstone_reputation
      → tasks.atomic.blackstone_gate_harassment
          → scenes.blackstone_city
              → heroes.hxd
                  → jiubing2
                      → war3
  → tasks.forest_reputation
      → tasks.atomic.swift_beast
          → scenes.forest_city
              → heroes.hxd (已加载，跳过)
  → scenes.menethil
  → scenes.palace
  → heroes.paladin (互斥替换 hxd，见规则 3)
```

线性加载顺序（后加载覆盖先加载）：

```
war3 → jiubing2 → heroes.hxd → scenes.blackstone_city → tasks.atomic.blackstone_gate_harassment → tasks.blackstone_reputation → scenes.forest_city → tasks.atomic.swift_beast → tasks.forest_reputation → scenes.menethil → scenes.palace → heroes.paladin → tasks.daily_reputation
```

### 规则 2：命名空间约定

`config/` 目录下所有**文件名、文件夹名**（含子级路径）构成命名空间根集合。

判定方式：TOML 顶层键是否命中命名空间根。

| 节点名示例 | 是否命中命名空间根 | 可继承？ |
|---|---|---|
| `[command]` | 否 | ✅ 可继承，提升到顶层 |
| `[skill.test]` | 否（`skill` 不是目录/文件名） | ✅ 可继承，提升到顶层 |
| `[hero]` | 否 | ✅ 可继承，提升到顶层 |
| `[tasks.fishing]` | 是（`tasks` 是目录） | ❌ 不可继承，保留在 `result["tasks"]["fishing"]` |
| `[scenes.forest_city.npcs.diana]` | 是（`scenes` 是目录） | ❌ 不可继承，保留在命名空间路径下 |
| `[war3]` | 是（`war3.toml` 是文件） | ❌ 不可继承，保留在 `result["war3"]` |

### 规则 3：英雄互斥

一场游戏只能玩一个英雄。`heroes.*` 命名空间为**互斥命名空间**。

- 加载顺序中出现多个英雄配置时，**最后一个英雄整体替换**之前英雄贡献的所有可继承节点。
- 前一英雄的可继承节点被完全清除，不残留任何字段。

示例：

```
heroes.hxd 贡献: hero = { floor_key = "O", skills = [...] }
heroes.paladin 贡献: hero = { floor_key = "P" }
→ 最终结果: hero = { floor_key = "P" }  (hxd 的 skills 不残留)
```

### 规则 4：[hero] 浅合并

`[hero]` 是可继承节点但做**浅合并**处理——合并顶层子键（`skills`/`inventory`/`stigma`/`cards` 等），每个子键**完全覆盖**（不递归）。

这样任务配置只写 `[[hero.inventory]]` 不会丢失英雄的 `skills` 等属性。英雄属性是 list/dict，不适合递归合并。

### 规则 5：结果结构

`load_task()` 返回的类 JSON 字典结构：

```
{
  # 可继承节点 → 深度合并到顶层（未覆盖的字段从父配置继承）
  "command": { ... },
  "chest": { ... },
  "pickup": { ... },
  "hero": { ... },
  "game": { ... },
  "prompt_text": { ... },

  # 不可继承节点 → 保留在命名空间路径下（深度合并，不同子路径可共存）
  "war3": { ... },
  "tasks": {
    "patrol_loot": { ... },
    "endless": { ... },
    "daily_reputation": { ... },
    "atomic": {
      "swift_beast": { ... },
      "blackstone_gate_harassment": { ... }
    }
  },
  "scenes": {
    "forest_city": { "npcs": { "diana": { ... } } },
    "blackstone_city": { "npcs": { "guard_captain": { ... } } },
    "menethil": { ... },
    "palace": { ... }
  },
  "heroes": {
    "hxd": { ... },
    "paladin": { ... }
  }
}
```

**合并语义总结**：

| 节点类型 | 合并方式 |
|---|---|
| 可继承节点（顶层） | **深度合并**：未覆盖的字段从父配置继承，已覆盖的字段递归覆盖 |
| `[hero]`（特殊可继承节点） | **浅合并**：合并顶层子键，每个子键完全覆盖（不递归） |
| 命名空间节点 | **深度合并**：不同子路径可共存，同路径后加载覆盖先加载 |
| 互斥命名空间（heroes） | **整体替换**：后加载的英雄清除前一英雄的全部可继承节点 |

---

## 代码调用规范

### 任务脚本入口模式

所有任务脚本遵循统一模式：**`main()` 中调用 `load_task` 一次，注入到任务类构造函数**。

```python
class MyTask:
    def __init__(self, cfg: dict):
        self.task_cfg = cfg                    # 完整依赖闭包
        self.cfg = cfg["tasks"]["my_task"]     # 本任务命名空间段
        # 从闭包中提取所需配置段，注入到业务对象
        war3_cfg = cfg.get("war3", {})
        hero_cfg = cfg.get("hero", {})
        self.war3 = War3Business(self.dm, war3_cfg)
        self.ui = GameUI(self.dm, war3_cfg, hero_cfg, cfg, self.war3)
        ...


def main():
    setup_global_exception_hook()
    cfg = config.load_task("tasks.my_task")    # 唯一一次 load_task
    task = MyTask(cfg)                         # 注入到构造函数
    task.run()
```

### 禁止事项

- ❌ **禁止**在任务类 `__init__` 中调用 `config.load_task()`
- ❌ **禁止**在业务代码中调用 `config.load_task("jiubing2")` 或直接索引原始配置字典
- ❌ **禁止**在业务代码中调用 `config.get()` 或 `config["key"]`（仅 `main()` 入口和工具模块 `paddle_ocr.py` 例外）
- ❌ **禁止**顶层调度器直接导入或索引原始配置字典，必须通过依赖注入传递

### 允许事项

- ✅ `main()` 函数中调用 `config.load_task("tasks.xxx")` 一次
- ✅ 任务类构造函数接受 `cfg: dict` 参数，从中提取配置段
- ✅ 任务类将 `cfg` 传递给子任务和业务对象（依赖注入）
- ✅ `paddle_ocr.py` 等工具模块可使用 `config.get()`（子进程无法 import 主包配置）

### 原子任务模式

原子任务（`tasks/atomic/*`）由上层任务通过 `_run_one_atomic()` 实例化，不接受 `cfg` 参数，而是接受已拆分的业务对象和配置段：

```python
class SwiftBeastTask:
    def __init__(self, dm, war3, ui, combat, task_cfg, at_npc=False, walk_time=None, monitor=None):
        self.dm = dm
        self.war3 = war3
        self.ui = ui
        self.combat = combat       # combat.cfg 即完整依赖闭包
        self.cfg = task_cfg        # 原子任务配置段
        ...
```

原子任务通过 `self.combat.cfg` 访问完整依赖闭包（如 `scenes` 命名空间下的 NPC 配置、`prompt_text` 等）。

---

## 配置目录结构

```
src/GameBot/config/
├── system/                     # 配置加载引擎（mixin 架构）
│   ├── base.py                 #   ConfigurationError 异常 + 常量
│   ├── loader.py               #   ConfigLoaderMixin — 文件加载 & 命名空间拆分
│   ├── resolver.py             #   ConfigResolverMixin — DFS 后序依赖解析
│   ├── builder.py              #   ConfigBuilderMixin — 合并构建 & 深度合并
│   ├── user.py                 #   ConfigUserMixin — 用户配置覆盖
│   └── core.py                 #   Config 单例类 — 组合所有 mixin
└── data/                       # 配置文件（TOML）
    ├── base.toml               # 基础配置（路径、大漠脚本环境、大漠插件、推理子进程）
    ├── war3.toml               # War3 窗口设置（命名空间根：war3）
    ├── jiubing2.toml           # 游戏机制通用配置（依赖 war3）
    ├── kk.toml                 # KK 平台配置
    ├── web.toml                # Web 相关配置
    ├── heroes/                 # 英雄配置（互斥命名空间）
    │   ├── hxd.toml            #   玄武大帝（依赖 jiubing2）
    │   ├── paladin.toml        #   圣骑士（依赖 jiubing2）
    │   ├── moon_rider.toml     #   月之骑士（依赖 jiubing2）
    │   └── ...                 #   其他英雄（共 22 个）
    ├── scenes/                 # 场景配置
    │   ├── forest_city.toml    #   森之城（依赖 jiubing2）
    │   ├── blackstone_city.toml#   黑石城（依赖 jiubing2）
    │   ├── menethil.toml       #   米奈希尔
    │   └── palace.toml         #   皇宫
    └── tasks/                  # 任务配置
        ├── others/             #   独立任务
        │   ├── fishing.toml    #     钓鱼
        │   ├── patrol_loot.toml#     巡逻拾取
        │   └── upgrade_stigmata.toml # 升级圣痕
        ├── endless/            #   无尽任务
        │   ├── endless.toml    #     多局无尽
        │   └── endless_single.toml #  单局无尽
        ├── reputation/         #   声望任务
        │   ├── daily_reputation.toml     # 每日声望
        │   ├── blackstone_reputation.toml# 黑石城声望
        │   └── forest_reputation.toml    # 森之城声望
        ├── atomic/             #   原子任务
        │   ├── swift_beast.toml        # 迅猛野兽
        │   └── blackstone_gate_harassment.toml # 城门骚扰
        └── achievements/       #   成就任务
            └── personal.toml   #     个人成就
```

---

## 测试

```bash
uv run python tests/test_config.py
```

测试覆盖五条继承规则，包括临时配置树和真实配置冒烟测试。
