"""组队任务入口 — TeamTaskRunner，由 main.py / Web 端启动。

仅此进程有浮窗，显示所有成员的任务进度汇总。
子进程（leader/follower）通过 subprocess 启动，无浮窗。
"""

from __future__ import annotations

import threading
from typing import Optional

from GameBot.config import config
from GameBot.runner.team.orchestrator import TeamOrchestrator
from GameBot.runner.ui import run_with_float_window
from GameBot.utils import logger, setup_log_file
from GameBot.utils.exception_handler import setup_global_exception_hook


class TeamTaskRunner:
    """组队任务入口 — 读取配置，拉起队长/队员子进程，仅此进程有浮窗。"""

    def __init__(self, cfg: dict):
        """
        :param cfg: 完整配置闭包（load_task 结果）
        """
        self.cfg = cfg
        # 提取 team_task 配置段（通用命名空间，不绑定 war3/jiubing2）
        self.team_cfg = cfg.get("team", {}).get("team_task", {})

    def run(self, stop_event: Optional[threading.Event] = None, progress_callback=None) -> None:
        """启动组队任务。

        :param stop_event: 停止事件
        :param progress_callback: 进度回调（用于浮窗显示）
        """
        if not self.team_cfg:
            logger.error("未找到 team_task 配置段")
            return

        # 传递配置路径给编排器（用于子进程加载配置）
        self.team_cfg["_config_path"] = "team.team_task"

        orchestrator = TeamOrchestrator(self.cfg, self.team_cfg, stop_event)
        if progress_callback:
            orchestrator.set_progress_callback(progress_callback)
        orchestrator.run()


def main():
    """入口函数 — 由 main.py 或 -m 方式启动。"""
    setup_global_exception_hook()
    setup_log_file("组队任务")
    logger.info("############################# 组队任务 #############################")
    cfg = config.load_task("team.team_task")

    def task_wrapper(stop_event, progress_callback=None):
        TeamTaskRunner(cfg).run(stop_event=stop_event, progress_callback=progress_callback)

    run_with_float_window(
        "组队任务",
        task_wrapper,
        countdown_seconds=5,
        float_cfg=cfg.get("float_window", {}),
    )


if __name__ == "__main__":
    main()
