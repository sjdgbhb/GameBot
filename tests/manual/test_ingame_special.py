"""局内特殊任务冒烟测试 — 黑石声望 1 次 + 森之城声望 1 次 + 抛竿 1 次。

通过覆盖 [this.reputation] / [this.fishing] 段实现少量次数（与任务自身的
覆盖机制同一条链路），不修改任务 TOML：
- 黑石城声望：target_reputation 5 ÷ 每次 +5 = 1 次城门骚扰
- 森之城声望：target_reputation 10 ÷ 每次 +10 = 1 次迅猛野兽
- 钓鱼：max_times = 1，抛 1 竿

前置条件：英雄位于黑石城守卫队长附近（可接城门骚扰的位置），
物品栏第 4 格鱼竿、第 5 格远古森林外围入口传送卷轴。

用法：
    uv run python tests/manual/test_ingame_special.py
"""

import sys

from GameBot.config import config
from GameBot.runner.tasks.war3.jiubing2.festival.ingame_special import IngameSpecialTask
from GameBot.runner.ui import run_with_float_window
from GameBot.utils import logger, setup_global_exception_hook, setup_log_file


def main():
    setup_global_exception_hook()
    setup_log_file("局内特殊冒烟测试")
    cfg = config.load_task("war3.jiubing2.tasks.festival.ingame_special")

    # 冒烟测试覆盖：写入本任务节点的 reputation/fishing 覆盖段，
    # 由 IngameSpecialTask._apply_overrides 合并到子任务命名空间
    this_cfg = cfg["war3"]["jiubing2"]["tasks"]["festival"]["ingame_special"]
    this_cfg.setdefault("reputation", {}).setdefault("blackstone", {})["target_reputation"] = 0
    this_cfg.setdefault("reputation", {}).setdefault("forest", {})["target_reputation"] = 0
    this_cfg.setdefault("fishing", {})["max_times"] = 1
    logger.info("冒烟测试：黑石声望 1 次 + 森之城声望 1 次 + 抛竿 1 次")

    def task_wrapper(stop_event, progress_callback=None, progress_lines_callback=None):
        IngameSpecialTask(cfg).run(
            stop_event=stop_event,
            progress_callback=progress_callback,
            progress_lines_callback=progress_lines_callback,
        )

    run_with_float_window(
        "局内特殊冒烟测试",
        task_wrapper,
        countdown_seconds=5,
        float_cfg=cfg.get("float_window", {}),
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
