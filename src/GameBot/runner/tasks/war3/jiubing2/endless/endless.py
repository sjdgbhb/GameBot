"""
多局无尽刷分 — 完整流程：KK → War3 → 准备 → 进皇宫 → 进无尽 → 循环 → 退出
"""

import time

from GameBot.utils import logger, StopTaskError, WindowLostError, setup_log_file
from GameBot.config import config
from GameBot.utils.exception_handler import setup_global_exception_hook
from GameBot.runner import DmClient
from GameBot.runner.business.war3 import War3Business
from GameBot.runner.business.kk import KKBusiness
from GameBot.runner.business.war3.jiubing2 import (
    GameUI, SceneNavigator, CombatHelper, EndlessRunner,
)
from GameBot.inference import get_ocr_client
from GameBot.runner.ui import run_with_float_window


class EndlessTask:
    """无尽刷怪任务"""

    def __init__(self, cfg: dict):
        self.task_cfg = cfg
        self.dm = DmClient()
        # 自动无尽继承局内无尽配置，再用 [tasks.endless.endless] 中独有的字段覆盖
        endless_cfg = {**cfg["war3"]["jiubing2"]["tasks"]["endless"]["endless_single"], **cfg["war3"]["jiubing2"]["tasks"]["endless"]["endless"]}

        war3_cfg = self.task_cfg.get("war3", {})
        hero_cfg = self.task_cfg.get("hero", {})
        kk_cfg = self.task_cfg.get("kk", {})

        self.war3 = War3Business(self.dm, war3_cfg)
        self.kk = KKBusiness(self.dm, kk_cfg)
        self.ui = GameUI(self.dm, war3_cfg, hero_cfg, self.task_cfg, self.war3)
        self.nav = SceneNavigator(
            self.dm, war3_cfg, hero_cfg, self.task_cfg, self.war3, self.ui,
        )
        self.combat = CombatHelper(self.dm, war3_cfg, hero_cfg, self.task_cfg, self.war3)
        self.runner = EndlessRunner(self.dm, self.war3, self.ui, self.combat,
                                    war3_cfg, hero_cfg, self.task_cfg)
        self.endless_cfg = endless_cfg
        self.war3_cfg = war3_cfg
        self.kk_cfg = kk_cfg

        self.game_start_time = 0
        self.boss_death_time = 0
        self.pet_feed_time = 0

    def do_kk(self) -> None:
        hwnd = self.dm.find_window(self.kk_cfg["window_class"], self.kk_cfg["window_title"])
        with self.dm.bind_window(hwnd):
            self.kk.start_game(self.dm)

    def _interruptible_wait(self, seconds: float):
        """可被停止信号中断的等待，检测到停止时抛出 StopTaskError。"""
        if self._stop_event is not None:
            if self._stop_event.wait(seconds):
                raise StopTaskError("用户请求停止任务")
        else:
            time.sleep(seconds)

    def do_war3(self, game_idx) -> bool:
        """执行单局 War3 流程。

        :return: True=本局正常完成, False=本局异常已跳过
        """
        logger.debug("已进入war3，等待地图加载")
        hwnd = self.war3.wait_for_game_window(self._stop_event, timeout=60)
        if not hwnd:
            logger.error("未找到 War3 窗口，跳过本局")
            self._handle_kk_disconnect()
            return False
        self.war3.set_client_size(hwnd)
        try:
            with self.dm.bind_window(hwnd):
                self.runner.wait_enter_game(self, self._stop_event)
                self.runner.do_preparation_phase(self.endless_cfg, self._stop_event)
                self.ui.switch_attribute_panel(is_fold=True)
                self.nav.enter_palace(self._stop_event)
                self.nav.enter_endless(self, self.endless_cfg, self._stop_event)
                self.runner.start_endless(self, game_idx, self.endless_cfg)
                self.war3.quit_game()
        except WindowLostError:
            logger.error("掉线，War3 窗口消失")
            self._handle_kk_disconnect()
            return False
        except TimeoutError as e:
            logger.error(f"卡在加载界面，关闭 War3：{e}")
            self.war3.quit_game()
            return False

        self._interruptible_wait(self.endless_cfg.get('loop_interval_time', 5))
        return True

    def _handle_kk_disconnect(self) -> None:
        """检测并处理 KK 掉线重连弹窗。"""
        hwnd = self.dm.find_window(
            self.kk_cfg.get("create_room_window_class", ""),
            self.kk_cfg.get("window_title", ""),
        )
        if hwnd:
            self.kk.handle_disconnect_dialog(self.dm)

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
        try:
            for game_idx in range(1, games + 1):
                self._progress_callback(f"第 {game_idx}/{games} 局 - 准备中")
                self.do_kk()
                self.do_war3(game_idx)
        except StopTaskError:
            logger.info("收到停止信号，停止无尽刷怪")
        logger.info("无尽刷怪任务结束")


def main():
    setup_global_exception_hook()
    setup_log_file("多局无尽")
    logger.info("############################# 无尽刷怪任务 #############################")
    cfg = config.load_task("war3.jiubing2.tasks.endless.endless")

    # 预加载推理子进程（OCR + 宝箱检测 + 战斗检测），避免首次使用时才启动
    get_ocr_client()

    def task_wrapper(stop_event, progress_callback=None):
        EndlessTask(cfg).run(stop_event=stop_event, progress_callback=progress_callback)

    run_with_float_window("无尽刷怪", task_wrapper, countdown_seconds=5,
                          float_cfg=cfg.get("float_window", {}))


if __name__ == "__main__":
    main()