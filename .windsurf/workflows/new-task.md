---
description: 新增任务模块 — 创建 Python 任务文件和对应 TOML 配置
---

# 新增任务模块工作流

当用户需要创建一个新的自动化任务时，按以下步骤操作：

## 1. 确认任务信息

向用户询问以下信息（如果用户未提供）：
- **任务名称**：英文蛇形命名（如 `boss_rush`、`material_farm`）
- **任务描述**：这个任务做什么
- **是否需要子目录**：如 `atomic/` 下的原子任务

## 2. 创建 TOML 配置文件

在 `src/GameBot/config/tasks/` 下创建 `{task_name}.toml`，基本结构：

```toml
# =============================================================================
# {任务描述}
# =============================================================================
dependencies = ["heroes.mk"]   # 指定依赖的英雄，通常继承 jiubing2

[tasks.{task_name}]
name = "{中文名称}"

# 任务特有配置...
```

注意事项：
- `dependencies` 必须声明，通常包含 `heroes.{英雄名}` 来继承英雄配置和 `jiubing2`
- 带命名空间前缀的节点（如 `[tasks.{task_name}]`）不可继承
- 不带前缀的节点（如 `[chest]`、`[pickup]`）可继承自 jiubing2.toml，按需覆盖

## 3. 创建 Python 任务文件

在 `src/GameBot/runner/tasks/` 下创建 `{task_name}.py`，基本结构：

```python
"""
{任务描述}
"""
import time

from GameBot.utils import logger
from GameBot.config import config
from GameBot.utils.exception_handler import setup_global_exception_hook
from GameBot.runner import DmClient
from GameBot.runner.business.war3 import War3Business
from GameBot.runner.business.jiubing2 import GameUI, CombatHelper


class {TaskName}Task:
    """{任务描述}"""

    def __init__(self, cfg: dict):
        self.task_cfg = cfg
        self.cfg = cfg["tasks"]["{task_name}"]
        self.dm = DmClient()

        war3_cfg = self.task_cfg.get("war3", {})
        hero_cfg = self.task_cfg.get("hero", {})

        self.war3 = War3Business(self.dm, war3_cfg)
        self.ui = GameUI(self.dm, war3_cfg, hero_cfg, self.task_cfg, self.war3)
        self.combat = CombatHelper(self.dm, war3_cfg, hero_cfg, self.task_cfg, self.war3)
        self.war3_cfg = war3_cfg
        self.hero_cfg = hero_cfg

    def run(self):
        # 任务主逻辑
        pass


def main():
    setup_global_exception_hook()
    logger.info("############################# {任务名称} #############################")
    time.sleep(5)
    cfg = config.load_task("tasks.{task_name}")
    task = {TaskName}Task(cfg)
    task.run()


if __name__ == "__main__":
    main()
```

注意事项：
- 物品快捷键通过 `get_inventory_hotkey(self.hero_cfg, item_id)` 获取，不要硬编码
- 配置值从 TOML 读取，不要硬编码在代码中
- 参考现有任务文件（如 `patrol_loot.py`、`endless_single.py`）的写法

## 4. 验证

- 检查 TOML 配置的 `dependencies` 是否正确
- 检查 Python 文件的 import 是否完整
- 确认运行命令：`.venv-dm/Scripts/python.exe -m GameBot.runner.tasks.{task_name}`
