"""
每日声望任务 — 获取黑石城、森之城声望各 150 点。
流程：黑石城声望（城门骚扰 x N）→ 森之城声望（内部自动转场 + 迅猛野兽 x N）。
转场逻辑封装在 ForestReputationTask._travel_to_forest_city。
配置仅通过一次 config.load_task("war3.jiubing2.tasks.reputation.daily_reputation") 加载，
依赖闭包含 tasks.atomic.blackstone_gate_harassment / tasks.atomic.swift_beast /
scenes.menethil / heroes.paladin，并注入到子任务与业务对象。
"""
from GameBot.utils import logger, setup_log_file
from GameBot.config import config
from GameBot.utils.exception_handler import setup_global_exception_hook
from GameBot.runner.tasks.war3.jiubing2.reputation.blackstone_reputation import BlackstoneReputationTask
from GameBot.runner.tasks.war3.jiubing2.reputation.forest_reputation import ForestReputationTask
from GameBot.runner.ui import run_with_float_window


class DailyReputationTask:
    """每日声望 — 顺序编排：黑石城声望 → 森之城声望（内部自动转场）。"""

    def __init__(self, cfg: dict):
        self.cfg = cfg["war3"]["jiubing2"]["tasks"]["reputation"]["daily_reputation"]
        self.blackstone = BlackstoneReputationTask(cfg)
        self.forest = ForestReputationTask(cfg)

    @property
    def task_name(self) -> str:
        return self.cfg.get("name", "每日声望")

    def run(self, stop_event=None, progress_lines_callback=None):
        enable_blackstone = self.cfg.get("enable_blackstone", True)
        enable_forest = self.cfg.get("enable_forest", True)
        targets_desc = []
        if enable_blackstone:
            targets_desc.append("黑石城")
        if enable_forest:
            targets_desc.append("森之城")
        logger.info(f"{self.task_name}开始（目标: {' + '.join(targets_desc) or '无'}）")

        # 初始化浮窗显示和共享状态
        progress_state = {}
        if progress_lines_callback is not None:
            lines = []
            if enable_blackstone:
                bs_target = self.blackstone.cfg.get("target_reputation", 150)
                progress_state["黑石城"] = f"黑石城：0/{bs_target}"
                lines.append(progress_state["黑石城"])
            if enable_forest:
                fs_target = self.forest.cfg.get("target_reputation", 150)
                progress_state["森之城"] = f"森之城：0/{fs_target}"
                lines.append(progress_state["森之城"])
            progress_lines_callback(lines)

        # 将共享状态传给子任务，使各子任务只更新自己的行
        if enable_blackstone:
            self.blackstone._progress_state = progress_state
        if enable_forest:
            self.forest._progress_state = progress_state

        # 1) 黑石城声望
        if enable_blackstone:
            self.blackstone.run(stop_event=stop_event, progress_lines_callback=progress_lines_callback)

        # 2) 森之城声望（ForestReputationTask 内部会先转场再循环）
        if enable_forest and (stop_event is None or not stop_event.is_set()):
            self.forest.run(stop_event=stop_event, progress_lines_callback=progress_lines_callback)

        logger.info(f"{self.task_name}结束")


def main():
    setup_global_exception_hook()
    setup_log_file("每日声望")
    logger.info("############################# 每日声望 #############################")
    cfg = config.load_task("war3.jiubing2.tasks.reputation.daily_reputation")

    def task_wrapper(stop_event, progress_callback=None, progress_lines_callback=None):
        DailyReputationTask(cfg).run(stop_event=stop_event, progress_lines_callback=progress_lines_callback)

    run_with_float_window("每日声望", task_wrapper, countdown_seconds=5,
                          float_cfg=cfg.get("float_window", {}))


if __name__ == "__main__":
    main()
