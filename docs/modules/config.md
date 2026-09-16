# 配置系统

> 源码位置：`src/GameBot/config/`

## 职责

配置系统是项目的「配置加载与合并引擎」。它把 `config/data/` 下的 TOML 文件按依赖关系
解析、合并成一份统一的配置字典，并应用用户覆盖。整个项目通过一次 `load_task` 调用
拿到一份可运行的完整配置闭包，注入到任务类和业务对象。

## 对外能力

- **加载任务配置**：`config.load_task(task_name) → dict`，返回该任务的完整配置闭包
  （包含所有依赖的配置段：英雄、场景、游戏机制、任务参数等）
- **按路径读取**：`config.get("hero.inventory")` / `config.get_section("chest")`
  （仅任务入口和工具模块使用，业务代码不直接调用）
- **自动处理**：物品名→ID 解析、快捷键格子注入、前台/后台绑定模式切换

## 依赖关系

- **共享工具**：文件IO（读取 user_configs.json）、日志、异常
- **资源管理器**：延迟初始化（core.py 中）

## 引擎架构

核心代码位于 `src/GameBot/config/system/`，采用 mixin 架构：

| 模块 | 职责 |
|------|------|
| `base.py` | `ConfigurationError` 异常 + 常量（`EXCLUSIVE_NAMESPACES`、`CONTROL_KEYS`） |
| `loader.py` | `ConfigLoaderMixin` — TOML 文件加载缓存、配置名到文件路径映射、命名空间根集合发现（仅一级目录）、可继承/命名空间节点拆分 |
| `resolver.py` | `ConfigResolverMixin` — DFS 后序依赖解析、循环依赖检测 |
| `builder.py` | `ConfigBuilderMixin` — 按加载顺序合并配置、深度合并、英雄互斥处理 |
| `derive.py` | 派生值解析 — `get_task_view`（任务视图）、`resolve_item_names`（物品名→item_id）、`derive_bind_mode`/`select_bind_cfg`/`apply_bind_mode`（bind 选择），供 `load_task` 与组队等非标准路径共用 |
| `user.py` | `ConfigUserMixin` — `user_configs.json` 加载与用户覆盖应用（`_USER_KEY_ROUTES` 路由表：用户键 → 目标路径，新增可调键加一行即可） |
| `core.py` | `Config` 单例类，组合所有 mixin，提供 `load_task` / `get` / `get_section` / `__getitem__` 接口 |

## 关键机制：五条继承规则

配置系统通过「依赖声明 + 命名空间隔离（仅一级目录）」实现树形继承，最终产出一份类 JSON 的全局配置对象。

### 1. 依赖继承

TOML 文件通过 `extends` 数组声明继承。`extends` 中每项是点分路径，对应 `config/data/` 下的目录结构：

```toml
extends = ["war3.jiubing2", "war3.jiubing2.heroes.mk"]

[this]
name = "钓鱼"
```

- 配置命名空间由**文件路径自动推导**（`config/data/` 下的点分路径，如 `war3/jiubing2/tasks/others/fishing.toml` → `war3.jiubing2.tasks.others.fishing`），**配置文件中不要写顶层 `name`**（该字段已废弃，会被忽略）。
- `[this]` 是文件级简写，展开后等价于文件路径推导名所指的完整命名空间段。
- 按**深度优先后序**（DFS post-order）递归展开继承链，生成线性加载顺序。
- 每个文件只加载一次（类似 Python import），首次到达的位置生效。
- **后加载覆盖先加载**：同名可继承节点**深度合并**（未覆盖的字段从父配置继承，已覆盖的字段递归覆盖）。
- `extends` 负责把依赖的 TOML 加载到 cfg 树中，代码负责从各命名空间分别取值。
- 旧 `dependencies` 控制键已废弃，解析器会明确报错。

示例依赖链（`war3.jiubing2.tasks.reputation.daily_reputation`）：

```
war3.jiubing2.tasks.reputation.daily_reputation
  → war3.jiubing2.tasks.atomic.blackstone_gate_harassment
      → war3.jiubing2.scenes.blackstone_city
          → war3.jiubing2
              → war3
                  → base
  → war3.jiubing2.tasks.atomic.swift_beast
      → war3.jiubing2.scenes.forest_city
          → war3.jiubing2 (已加载，跳过)
  → kk
      → base (已加载，跳过)
```

线性加载顺序（后加载覆盖先加载）：

```
base → war3 → war3.jiubing2 → war3.jiubing2.scenes.blackstone_city → war3.jiubing2.tasks.atomic.blackstone_gate_harassment → war3.jiubing2.scenes.forest_city → war3.jiubing2.tasks.atomic.swift_beast → war3.jiubing2.scenes.menethil → kk → war3.jiubing2.tasks.reputation.daily_reputation
```

### 2. 命名空间约定

命名空间根由**显式注册表**管理（`config/system/base.py` 的 `NAMESPACE_ROOTS`）：

```python
NAMESPACE_ROOTS = frozenset({"base", "kk", "team", "war3", "web"})
```

- 新增任务/英雄/场景/变体文件**不需要登记**（都在 `war3` 根内扩展）
- 只有新增一级命名空间（如 `data/yy/`）才需要向注册表加一行——这本该是显式决策
- `config/data/` 下出现未登记的一级目录或顶层 `.toml` 会告警：其顶层键会被当作
  可继承共享键提升（多半不是预期）
- 旧实现是扫描 `data/` 一级目录，新建目录会静默改变同名裸键的合并语义，已废弃

判定方式：TOML 顶层键是否命中命名空间根。

| 节点名示例 | 是否命中命名空间根 | 可继承？ |
|---|---|---|
| `[command]` | 否 | ✅ 可继承，提升到顶层 |
| `[hero]` | 否（`hero` 不是一级目录/文件名） | ✅ 可继承，提升到顶层 |
| `[war3]` | 是（`war3` 是一级目录名） | ❌ 不可继承，保留在 `result["war3"]` |
| `[kk]` | 是（`kk.toml` 是顶层文件） | ❌ 不可继承，保留在 `result["kk"]` |
| `[this]` | 否（简写，展开后为当前文件的完整命名空间） | ❌ 不可继承，保留在文件路径对应的命名空间路径下 |
| `[this.patrol]` | 否（简写，展开为 `文件路径名 + ".patrol"`） | ❌ 不可继承，保留在命名空间路径下 |

> **注意**：新格式使用 `[this]` 与 `[this.*]` 简写代替长命名空间前缀。
> 例如 `war3/jiubing2/tasks/others/fishing.toml` 中，`[this]` 等价于 `[war3.jiubing2.tasks.others.fishing]`。
> 旧 `dependencies` 与顶层 `name` 已不再支持。
>
> **绝对寻址**：完整命名空间段允许用于**给其他节点打补丁**（不能写自身路径——
> 自身路径命中即报错，提示改用 `[this]`）。典型场景是编排任务调子任务参数：
> ```toml
> # 在 ingame_special.toml 中直接覆盖 fishing 任务节点的参数
> [war3.jiubing2.tasks.others.fishing]
> max_times = 40
> ```
> 合并时该段深合并到目标命名空间，替代旧的在业务代码里手动搬运的模式。

### 3. 英雄互斥

一场游戏只能玩一个英雄。`war3.jiubing2.heroes.*` 是**互斥命名空间**
（`EXCLUSIVE_NAMESPACES = {"war3.jiubing2.heroes"}`）。

- 加载顺序中出现多个英雄配置时，**最后一个英雄整体替换**之前英雄贡献的所有可继承节点。
- 前一英雄的可继承节点被完全清除，不残留任何字段。

示例：

```
war3.jiubing2.heroes.hxd 贡献: hero = { floor_key = "O", skills = [...] }
war3.jiubing2.heroes.paladin 贡献: hero = { floor_key = "P" }
→ 最终结果: hero = { floor_key = "P" }  (hxd 的 skills 不残留)
```

### 4. [hero] 浅合并

`[hero]` 是可继承节点但做**浅合并**处理——合并顶层子键（`skills`/`inventory`/`stigma`/`cards` 等），每个子键**完全覆盖**（不递归）。

这样任务配置只写 `[[hero.inventory]]` 不会丢失英雄的 `skills` 等属性。英雄属性是 list/dict，不适合递归合并。

### 5. 结果结构

`load_task()` 返回的类 JSON 字典结构：

```
{
  # 可继承节点 → 深度合并到顶层（未覆盖的字段从父配置继承）
  "command": { ... },
  "hero": { ... },
  "game": { ... },
  "prompt_text": { ... },
  ...

  # 不可继承节点 → 保留在命名空间路径下（深度合并，不同子路径可共存）
  "war3": {
    "jiubing2": {
      "tasks": {
        "others": { "fishing": { ... }, "patrol_loot": { ... } },
        "atomic": { "swift_beast": { ... }, ... },
        "reputation": { "daily_reputation": { ... } },
        ...
      },
      "scenes": {
        "forest_city": { "npcs": { "diana": { ... } } },
        "blackstone_city": { "npcs": { "guard_captain": { ... } } },
        ...
      }
    }
  },
  "kk": { ... },

  # 各配置文件的 extends 依赖映射，供 get_task_view 沿链合并任务视图
  "_extends": { ... }
}
```

**`get_task_view(cfg, task_name)` — 有效任务视图**：

`[this]` 按文件路径展开为兄弟节点，彼此不会自动覆盖。`load_task` 不再预合并
`cfg["task"]`；业务代码调 `config.get_task_view(cfg, task_name)`，沿该任务的
extends 链 DFS 后序深合并 `war3.jiubing2.tasks.*` 节点——变体不写的参数
自动从基任务继承，要覆盖则用绝对寻址写全路径打到基任务节点。

注意边界：只合并 `war3.jiubing2.tasks.*` 节点；编排任务的子任务参数仍在各自
命名空间节点读取（编排任务调子任务参数用绝对寻址段），不在编排任务的任务视图中。
非任务入口（`load_task("kk")` 等）返回空 dict。

**合并语义总结**：

| 节点类型 | 合并方式 |
|---|---|
| 可继承节点（顶层） | **深度合并**：未覆盖的字段从父配置继承，已覆盖的字段递归覆盖 |
| `[hero]`（特殊可继承节点） | **浅合并**：合并顶层子键，每个子键完全覆盖（不递归） |
| 命名空间节点 | **深度合并**：不同子路径可共存，同路径后加载覆盖先加载 |
| 互斥命名空间（`war3.jiubing2.heroes`） | **整体替换**：后加载的英雄清除前一英雄的全部可继承节点 |

## 配置文件组织

```
config/data/
├── base.toml              # 基础配置（路径、大漠、推理、浮窗）
├── war3/
│   ├── war3.toml          # War3 窗口设置（命名空间节点：[war3]）
│   └── jiubing2/
│       ├── jiubing2.toml  # 游戏机制通用配置（物品定义、各系统参数）
│       ├── heroes/        # 英雄配置（互斥命名空间，22个英雄）
│       ├── scenes/        # 场景配置（森之城/黑石城/米奈希尔/皇宫/卡米村）
│       └── tasks/         # 任务配置（atomic/endless/others/reputation/achievements）
├── kk.toml                # KK 平台配置
├── web.toml               # Web 相关配置
└── team/                  # 组队任务配置
```

## 配置调用规范

### 任务入口模式（必须遵守）
所有任务脚本遵循统一模式：**`main()` 中调用 `load_task` 一次，注入到任务类构造函数**。

```
main() → load_task("tasks.xxx") → 得到配置dict → 注入到任务类 → 任务类提取配置段 → 注入到业务对象
```

```python
class MyTask:
    def __init__(self, cfg: dict):
        self.task_cfg = cfg                    # 完整依赖闭包
        self.cfg = get_task_view(cfg, task_name)  # 有效任务视图（本任务 extends 链深合并）
        # 从闭包中提取所需配置段，注入到业务对象
        war3_cfg = cfg.get("war3", {})
        hero_cfg = cfg.get("hero", {})
        self.war3 = War3Business(self.dm, war3_cfg)
        self.ui = GameUI(self.dm, war3_cfg, hero_cfg, cfg, self.war3)
        ...


def main():
    setup_global_exception_hook()
    cfg = config.load_task("war3.jiubing2.tasks.others.my_task")    # 唯一一次 load_task
    task = MyTask(cfg)                         # 注入到构造函数
    task.run()
```

### 原子任务模式

原子任务（`tasks/atomic/*`）由上层任务通过 `_run_one_atomic()` 实例化，不接受 `cfg` 参数，而是接受已拆分的业务对象和配置段：

```python
class SwiftBeastTask:
    def __init__(self, dm, war3, ui, combat, task_cfg, walk_time=None, monitor=None):
        self.dm = dm
        self.war3 = war3
        self.ui = ui
        self.combat = combat       # combat.cfg 即完整依赖闭包
        self.cfg = task_cfg        # 原子任务配置段
        ...
```

原子任务通过 `self.combat.cfg` 访问完整依赖闭包（如 `war3.jiubing2.scenes` 命名空间下的 NPC 配置、`prompt_text` 等）。

### 禁止事项
- ❌ 禁止在任务类 `__init__` 中调用 `load_task`
- ❌ 禁止在业务代码中调用 `load_task` 或直接索引原始配置字典
- ❌ 禁止在业务代码中调用 `config.get()` 或 `config["key"]`（仅 main() 入口和工具模块例外）
- ❌ 禁止顶层调度器直接导入或索引原始配置字典，必须通过依赖注入传递

### 允许事项
- ✅ `main()` 中调用 `load_task("war3.jiubing2.tasks.xxx")` 一次
- ✅ 任务类构造函数接受 `cfg: dict`，从中提取配置段
- ✅ 任务类将 `cfg` 传递给子任务和业务对象（依赖注入）
- ✅ 工具模块（如推理子进程）可使用 `config.get()`（子进程无法 import 主包配置）

## 关键约束

- 配置合并是**深度合并**（未覆盖的字段从父配置继承，已覆盖的字段递归覆盖）
- `[hero]` 是唯一的浅合并例外
- `user_configs.json` 用于覆盖英雄背包、目标物品、巡逻轮数等用户可调参数
- 配置加载引擎采用 mixin 架构（加载器/解析器/构建器/派生/用户覆盖组合到核心类）
- `name` 和 `extends` 是文件级控制键，不参与合并结果
- extends 分层约束（告警阶段）：低层文件（base/平台/领域/英雄/场景）不得 extends `tasks.*`；
  task→task 任意引用允许（编排任务、变体继承是既有用法）
- 派生逻辑统一走 `config/system/derive.py`；组队等非 `load_task` 路径调
  `apply_bind_mode(cfg, force_mode="background")`，不要手写派生拷贝

## 禁忌

- ❌ 不要硬编码配置值在代码中（应从 TOML 读取）
- ❌ 不要在业务代码中直接读配置单例（应通过依赖注入）
- ❌ 不要假设英雄配置会叠加（英雄互斥，最后加载的独占生效）
- ❌ 不要创建不声明 `name` 和 `extends` 的配置文件
- ❌ 不要使用已废弃的 `dependencies` 控制键
- ❌ 不要用完整命名空间段写**自身**路径（会被拦截）；自身命名空间一律用 `[this]`，给其他节点打补丁才写完整路径（绝对寻址）

## 排障工具（CLI）

`load_task` 合并时同步记录 **provenance**（每个键的写入来源链），通过 CLI 查询：

```bash
# 依赖闭包的线性加载顺序（先 → 后，后者覆盖前者）
python -m GameBot.config order war3.jiubing2.tasks.endless.endless_善木木

# 查某个键的值与来源链（谁写的、被谁覆盖）
python -m GameBot.config explain war3.jiubing2.tasks.endless.endless_善木木 hero.shard.use_index

# 导出合并后的有效配置；--annotate 展平为 dot 路径并逐行标注来源
python -m GameBot.config dump <任务名> --out merged_cfg.json
python -m GameBot.config dump <任务名> --annotate

# 结构校验全部 TOML（不执行任务）：extends 声明/循环依赖/旧格式写法/
# 低层 extends tasks.*/未登记一级条目为错误；变体约定、绝对寻址段笔误为警告
python -m GameBot.config lint

# 生成新任务/变体模板（变体名带 _后缀且同目录有基任务时自动 extends 基任务）
python -m GameBot.config new war3.jiubing2.tasks.others.my_task
python -m GameBot.config new war3.jiubing2.tasks.endless.endless_玩家名
```

来源名含义：TOML 文件名（配置名取最后一段）、`user_configs.json`（用户覆盖）、
`<派生:xxx>`（引擎派生步骤：bind 选择 / inventory_slots 注入 / 物品名→item_id 解析）。

代码侧对应接口：`config.get_provenance(task_name=None)` → `{dot_path: [来源链]}`。

## 测试

```bash
uv run python tests/unit/test_config.py
```

测试覆盖五条继承规则，包括临时配置树和真实配置冒烟测试。

## 关联文档

- [新增英雄配置](../guides/new-hero.md) —— 如何添加英雄 TOML
- [新增任务模块](../guides/new-task.md) —— 如何添加任务 TOML
- [架构总览](../architecture/overview.md) —— 配置依赖注入的设计理由
- [常见问题排查](../guides/troubleshooting.md) —— 配置字段丢失、英雄覆盖等问题
