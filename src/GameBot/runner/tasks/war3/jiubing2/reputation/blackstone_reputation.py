"""
每日黑石城声望任务 — 每日声望上限 150，每次城门骚扰 +5 声望。
通过反复完成黑石城城门骚扰任务来达成，循环逻辑复用 ReputationTask
（窗口绑定、OCR 预热、原子任务调度、次数反推等全部继承）。
配置通过 config.load_task("war3.jiubing2.tasks.reputation.daily_reputation") 加载，
其依赖 tasks.atomic.blackstone_gate_harassment（进而依赖黑石城场景）。
"""
from GameBot.config import config
from GameBot.runner.tasks.war3.jiubing2.atomic.blackstone_gate_harassment import GateHarassmentTask
from GameBot.runner.tasks.war3.jiubing2.base import ReputationTask
from GameBot.utils import logger, setup_log_file
from GameBot.utils.exception_handler import setup_global_exception_hook


class BlackstoneReputationTask(ReputationTask):
    """每日黑石城声望 — 按声望上限/每次收益反推需要完成的城门骚扰次数。"""

    atomic_task_cls = GateHarassmentTask
    atomic_name = "城门骚扰"
    task_config_path = ("war3", "jiubing2", "tasks", "reputation", "daily_reputation", "blackstone")
    atomic_config_path = ("war3", "jiubing2", "tasks", "atomic", "blackstone_gate_harassment")

    @property
    def task_name(self) -> str:
        return self.cfg.get("name", "每日黑石城声望")


def main():
    setup_global_exception_hook()
    setup_log_file("每日黑石城声望")
    logger.info("############################# 每日黑石城声望 #############################")
    cfg = config.load_task("war3.jiubing2.tasks.reputation.daily_reputation")
    task = BlackstoneReputationTask(cfg)
    task.run()


if __name__ == "__main__":
    main()