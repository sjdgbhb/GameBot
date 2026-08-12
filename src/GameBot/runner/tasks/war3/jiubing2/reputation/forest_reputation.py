"""
每日森之城声望任务 — 每日声望上限 150，每次迅猛野兽任务 +10 声望。
先通过传送卷转场至森之城（SceneNavigator.tp_enter_forest_city），
再反复完成迅猛野兽任务来达成，循环逻辑复用 ReputationTask
（窗口绑定、OCR 预热、原子任务调度、次数反推等全部继承）。
配置通过 config.load_task("war3.jiubing2.tasks.reputation.daily_reputation") 加载，
依赖 tasks.atomic.swift_beast + scenes.menethil/scenes.palace + heroes.paladin。
"""
import time

from GameBot.utils import logger, setup_log_file
from GameBot.config import config
from GameBot.utils.exception_handler import setup_global_exception_hook
from GameBot.runner.business.war3.jiubing2 import GameUI, SceneNavigator
from GameBot.runner.tasks.war3.jiubing2.base import ReputationTask
from GameBot.runner.tasks.war3.jiubing2.atomic.swift_beast import SwiftBeastTask


class ForestReputationTask(ReputationTask):
    """每日森之城声望 — 先转场至森之城，再按声望上限/每次收益反推需要完成的迅猛野兽次数。"""

    atomic_task_cls = SwiftBeastTask
    atomic_name = "迅猛野兽"
    task_config_path = ("war3", "jiubing2", "tasks", "reputation", "daily_reputation", "forest")
    atomic_config_path = ("war3", "jiubing2", "tasks", "atomic", "swift_beast")

    def __init__(self, cfg: dict):
        super().__init__(cfg)
        # 转场导航器：传送卷在英雄物品栏（由 heroes.paladin 依赖闭包提供）
        hero_cfg = cfg.get("hero", {})
        ui = GameUI(self.dm, self.war3_cfg, hero_cfg, cfg, self.war3)
        self.nav = SceneNavigator(self.dm, self.war3_cfg, hero_cfg, cfg, self.war3, ui)

    @property
    def task_name(self) -> str:
        return self.cfg.get("name", "每日森之城声望")

    def run(self, stop_event=None, progress_lines_callback=None):
        self._stop_event = stop_event
        # 先转场至森之城
        self._travel_to_forest_city()
        super().run(stop_event=stop_event, progress_lines_callback=progress_lines_callback)

    def _travel_to_forest_city(self):
        """使用传送卷传送至远古森林外围入口，再走进传送圈到达森之城。"""
        hwnd = self.dm.get_active_window(
            self.war3_cfg["window_class"], self.war3_cfg["window_title"]
        )
        if not hwnd:
            logger.error("未找到 war3 窗口，转场失败")
            return
        with self.dm.bind_window(hwnd):
            self.nav.tp_enter_forest_city(self._stop_event)


def main():
    setup_global_exception_hook()
    setup_log_file("每日森之城声望")
    logger.info("############################# 每日森之城声望 #############################")
    cfg = config.load_task("war3.jiubing2.tasks.reputation.daily_reputation")
    task = ForestReputationTask(cfg)
    task.run()


if __name__ == "__main__":
    main()
