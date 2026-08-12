"""
单局无尽刷分 — 已在无尽地图内，直接开刷
"""
import time
from GameBot.utils import logger, StopTaskError, setup_log_file
from GameBot.config import config
from GameBot.utils.exception_handler import setup_global_exception_hook
from GameBot.runner import DmClient
from GameBot.runner.business.war3 import War3Business
from GameBot.runner.business.war3.jiubing2 import (
    GameUI, CombatHelper, EndlessRunner,
)
from GameBot.runner.ui import run_with_float_window
from GameBot.inference import get_ocr_client


class EndlessSingleTask:
    """无尽刷怪任务（已在无尽地图内）"""

    def __init__(self, cfg: dict):
        self.task_cfg = cfg
        self.dm = DmClient()
        endless_cfg = cfg["war3"]["jiubing2"]["tasks"]["endless"]["endless_single"]

        war3_cfg = self.task_cfg.get("war3", {})
        hero_cfg = self.task_cfg.get("hero", {})

        self.war3 = War3Business(self.dm, war3_cfg)
        self.ui = GameUI(self.dm, war3_cfg, hero_cfg, self.task_cfg, self.war3)
        self.combat = CombatHelper(self.dm, war3_cfg, hero_cfg, self.task_cfg, self.war3)
        self.runner = EndlessRunner(self.dm, self.war3, self.ui, self.combat,
                                    war3_cfg, hero_cfg, self.task_cfg)
        self.endless_cfg = endless_cfg
        self.war3_cfg = war3_cfg

        self.game_start_time = 0
        self.boss_death_time = 0
        self.pet_feed_time = time.time()

    def run(self, stop_event=None, progress_callback=None):
        self._stop_event = stop_event
        self._progress_callback = progress_callback or (lambda text: None)
        games = self.endless_cfg.get("games", 10)
        min_level = self.endless_cfg.get("min_level", 15)
        max_level = self.endless_cfg.get("max_level", 100)
        logger.info(
            f'游戏总局数：{games}，'
            f'每局刷怪楼层：{min_level} -> {max_level}'
        )
        self._progress_callback(f"楼层 {min_level}/{max_level}")
        hwnd = self.dm.get_active_window(self.war3_cfg["window_class"], self.war3_cfg["window_title"])
        if not hwnd:
            logger.error("未找到 war3 窗口")
            return
        with self.dm.bind_window(hwnd):
            self.war3.set_client_size(hwnd)
            try:
                self.runner.clear_endless_monster_loop(self, 1, self.endless_cfg)
            except StopTaskError:
                logger.info("收到停止信号，停止无尽刷怪")
        logger.info("无尽刷怪任务结束")


def main():
    setup_global_exception_hook()
    setup_log_file("单局无尽")
    logger.info("############################# 无尽刷怪任务 #############################")
    cfg = config.load_task("war3.jiubing2.tasks.endless.endless_single")

    # 预加载推理子进程（OCR + 宝箱检测 + 战斗检测），避免首次使用时才启动
    get_ocr_client()

    def task_wrapper(stop_event, progress_callback=None):
        EndlessSingleTask(cfg).run(stop_event=stop_event, progress_callback=progress_callback)

    run_with_float_window("无尽刷怪", task_wrapper, countdown_seconds=5,
                          float_cfg=cfg.get("float_window", {}))


if __name__ == "__main__":
    main()