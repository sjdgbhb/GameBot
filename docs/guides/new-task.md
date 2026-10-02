# 新增任务模块

> 当需要创建一个新的自动化任务时，按以下步骤操作。

## 1. 确认任务信息

向用户询问以下信息（如果用户未提供）：
- **任务名称**：英文蛇形命名（如 `boss_rush`、`material_farm`）
- **任务描述**：这个任务做什么
- **是否需要子目录**：如 `atomic/` 下的原子任务

## 2. 创建 TOML 配置文件

在 `src/GameBot/config/data/war3/jiubing2/tasks/` 对应类别目录下创建 `{task_name}.toml`。

基本结构：
```toml
extends = ["war3.jiubing2", "war3.jiubing2.heroes.{hero_name}"]   # 指定继承的英雄和基础配置

[this]
name = "{中文名称}"

# 任务特有配置...
```

注意事项：
- **不要写顶层 `name`**——`[this]` 展开的命名空间由文件路径自动推导（文件名即配置名）
- `extends` 必须声明，通常包含 `war3.jiubing2.heroes.{hero_name}` 来继承英雄配置和 `war3.jiubing2`
- `[this]` 直接展开为 `war3.jiubing2.tasks.{类别}.{task_name}`，是当前任务的数据节点
- 不带前缀的节点（如 `[chest]`、`[pickup]`）可继承自 jiubing2.toml，按需覆盖
- 配置继承机制详见 [配置系统](../modules/config.md)

## 3. 创建 Python 任务文件

在 `src/GameBot/runner/tasks/war3/jiubing2/` 对应类别目录下创建 `{task_name}.py`。

基本结构：
```python
"""{任务描述}"""
import time

from GameBot.config import config, get_task_view
from GameBot.runner.business.war3 import War3Business
from GameBot.runner.business.war3.jiubing2 import GameUI, CombatHelper
from GameBot.runner import create_dm_client
from GameBot.runner.ui import run_with_float_window
from GameBot.utils import logger, setup_log_file
from GameBot.utils.exception_handler import setup_global_exception_hook

# 任务名（完整命名空间路径，与 TOML 文件路径对应）
TASK_NAME = "war3.jiubing2.tasks.{类别}.{task_name}"


class {TaskName}Task:
    """{任务描述}"""

    def __init__(self, cfg: dict):
        self.task_cfg = cfg
        self.dm = create_dm_client()

        war3_cfg = self.task_cfg.get("war3", {})
        hero_cfg = self.task_cfg.get("hero", {})

        self.war3 = War3Business(self.dm, war3_cfg)
        self.ui = GameUI(self.dm, war3_cfg, hero_cfg, self.task_cfg, self.war3)
        self.combat = CombatHelper(self.dm, war3_cfg, hero_cfg, self.task_cfg, self.war3)
        # 任务视图：沿 extends 链深合并（基任务 → 变体），变体不写的参数自动从基任务继承
        self.cfg = get_task_view(cfg, TASK_NAME)

    def run(self, stop_event=None, progress_callback=None):
        # 任务主逻辑
        pass


def main():
    setup_global_exception_hook()
    setup_log_file("{任务名称}")
    logger.info("############################# {任务名称} #############################")
    cfg = config.load_task(TASK_NAME)

    def task_wrapper(stop_event, progress_callback=None):
        {TaskName}Task(cfg).run(stop_event=stop_event, progress_callback=progress_callback)

    run_with_float_window(
        "{任务名称}",
        task_wrapper,
        countdown_seconds=5,
        float_cfg=cfg.get("base", {}).get("float_window", {}),
    )


if __name__ == "__main__":
    main()
```

## 4. 关键注意事项

- **配置注入**：`main()` 中调用 `load_task` 一次，注入到任务类构造函数
- **物品快捷键**：通过 `get_inventory_hotkey(hero_cfg, item_id)` 获取，不要硬编码
- **配置值**：从 TOML 读取，不要硬编码在代码中
- **浮窗包装**：用 `run_with_float_window` 包装任务入口，支持停止
- **参考现有任务**：如 `patrol_loot.py`、`endless_single.py` 的写法

## 5. 选择任务基类

根据任务类型选择合适的基类：

| 任务类型 | 基类 | 说明 |
|----------|------|------|
| 循环执行原子任务 | `AtomicLoopTask` | 自动绑定窗口、预热OCR、循环调用原子任务 |
| 声望类任务 | `ReputationTask` | 在原子循环基础上，按声望上限反推次数 |
| 多原子任务 | `MultiAtomicLoopTask` | 一次接取多个，走共享路线，依次提交 |
| 独立流程 | 无基类 | 自己实现 run()，参考 EndlessTask/FishingTask |

## 6. 多开变体（可选）

同一台机器多个账号各跑各的同一任务时，为任务加变体支持：

1. `main()` 解析 `sys.argv[1]` 为变体名（叶子名拼上任务命名空间前缀，
   或直接用完整配置名），`load_task(task_name)` 后把 `task_name` 传给任务类
2. 任务类用 `get_task_view(cfg, task_name)` 取自身配置（变体节点不在固定
   路径上），并把 `target_player` 注入 `war3.target_player` 供窗口认领链路读取
3. 创建变体文件 `tasks/<组>/<任务>_<玩家名>.toml`：`extends` 基任务，
   `[this]` 写 `target_player`，`[war3]`/`[kk]` 段写 `bind_mode="background"`
   （多开必须后台绑定），按需加 `[hero.xxx]` 账号差异覆盖、`[base.float_window]`
   错开浮窗位置

参考实现：`endless.py`（多局，KK 房间认领 + war3 PPID 认领）、
`endless_single.py` / `fishing.py` / `patrol_loot.py` / `upgrade_stigmata.py`
（局内，war3 PPID 认领，kk_pid 未知时聊天 token 自举）。

## 7. 验证

- 检查 TOML 配置的 `extends` 是否正确（不要写顶层 `name`，文件名即配置名）
- 检查 Python 文件的 import 是否完整，`TASK_NAME` 与 TOML 文件路径对应
- 可用 `python -m GameBot.config lint` 校验全部 TOML 结构
- 可用 `python -m GameBot.config order war3.jiubing2.tasks.{类别}.{task_name}` 查看依赖加载顺序
- 确认运行命令：`uv run python -m GameBot.runner.tasks.war3.jiubing2.{类别}.{task_name}`

## 相关文档

- [任务编排层](../modules/tasks.md) —— 任务基类和继承体系
- [配置系统](../modules/config.md) —— 配置继承机制
- [业务逻辑层](../modules/business.md) —— 可用的业务原语
