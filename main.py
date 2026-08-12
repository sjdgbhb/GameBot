import argparse
import platform
import sys

from GameBot.config import config
from GameBot.utils.exception_handler import setup_global_exception_hook
from GameBot.runner import tasks as tasks_mod


def _check_environment():
    """校验运行环境：大漠插件 COM 仅支持 32 位 Python 3.8。"""
    if sys.maxsize > 2**32:
        print(f"错误：当前 Python 为 64 位（{platform.python_version()}），大漠插件 COM 仅支持 32 位 Python 3.8。")
        print("请使用 32 位 Python 3.8 环境运行本脚本：uv run python main.py")
        sys.exit(1)
    if sys.version_info[:2] != (3, 8):
        print(f"错误：当前 Python 版本为 {platform.python_version()}，大漠插件 COM 仅支持 Python 3.8。")
        print("请使用 32 位 Python 3.8 环境运行本脚本：uv run python main.py")
        sys.exit(1)

# 任务名 → (配置路径, 任务类) 映射
TASK_REGISTRY = {
    "fishing":           ("war3.jiubing2.tasks.others.fishing",           "FishingTask"),
    "endless":           ("war3.jiubing2.tasks.endless.endless",          "EndlessTask"),
    "endless_single":    ("war3.jiubing2.tasks.endless.endless_single",   "EndlessSingleTask"),
    "patrol_loot":       ("war3.jiubing2.tasks.others.patrol_loot",       "PatrolLootTask"),
    "upgrade_stigmata":  ("war3.jiubing2.tasks.others.upgrade_stigmata",  "UpgradeStigmataTask"),
    "daily_reputation":  ("war3.jiubing2.tasks.reputation.daily_reputation",   "DailyReputationTask"),
    "blackstone":        ("war3.jiubing2.tasks.reputation.blackstone_reputation", "BlackstoneReputationTask"),
    "forest":            ("war3.jiubing2.tasks.reputation.forest_reputation",   "ForestReputationTask"),
}


def main():
    _check_environment()
    parser = argparse.ArgumentParser(description="九种兵器2 自动化脚本")
    parser.add_argument(
        "task",
        nargs="?",
        default="fishing",
        choices=list(TASK_REGISTRY.keys()),
        help="要运行的任务（默认: fishing）",
    )
    args = parser.parse_args()

    setup_global_exception_hook()

    cfg_path, class_name = TASK_REGISTRY[args.task]
    cfg = config.load_task(cfg_path)

    task_cls = getattr(tasks_mod, class_name)
    task_cls(cfg).run()


if __name__ == "__main__":
    main()