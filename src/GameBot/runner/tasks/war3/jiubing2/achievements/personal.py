"""
个人任务成就 — 完成一定次数的个人任务。
流程：一次性接取多个同场景原子任务 → 走共享路线同时完成 → 依次提交，每次提交算 1 次。
任务状态通过 -rw 弹窗确认（屏幕提示完成时触发查询）。
"""

from GameBot.config import config
from GameBot.runner.tasks.war3.jiubing2.base import MultiAtomicLoopTask
from GameBot.runner.ui import run_with_float_window
from GameBot.utils import logger, setup_log_file
from GameBot.utils.exception_handler import setup_global_exception_hook


class PersonalAchievementTask(MultiAtomicLoopTask):
    """个人任务成就 — 接取多个原子任务 → 共享路线完成 → 依次提交。"""

    atomic_name = "个人任务"
    task_config_path = ("war3", "jiubing2", "tasks", "achievements", "personal")
    atomic_config_path = ("war3", "jiubing2", "tasks", "atomic", "venomous_snake")

    def __init__(self, cfg: dict):
        super().__init__(cfg)


def main():
    setup_global_exception_hook()
    setup_log_file("个人任务成就")
    logger.info("############################# 个人任务成就 #############################")
    cfg = config.load_task("war3.jiubing2.tasks.achievements.personal")

    def task_wrapper(stop_event, progress_callback=None):
        PersonalAchievementTask(cfg).run(stop_event=stop_event, progress_callback=progress_callback)

    run_with_float_window("个人任务成就", task_wrapper, countdown_seconds=5, float_cfg=cfg.get("base", {}).get("float_window", {}))


if __name__ == "__main__":
    main()
