"""
多局无尽刷分 — 完整流程：KK → War3 → 准备 → 进皇宫 → 进无尽 → 循环 → 退出
"""

import time

from GameBot.config import config
from GameBot.inference import get_inference_client
from GameBot.runner import create_dm_client
from GameBot.runner.business.kk import KKBusiness
from GameBot.runner.business.war3 import War3Business
from GameBot.runner.business.war3.jiubing2 import (
    CombatHelper,
    EndlessRunner,
    GameUI,
    SceneNavigator,
)
from GameBot.runner.business.war3.jiubing2.endless_runner import BossDeathTimeoutError
from GameBot.runner.ui import run_with_float_window
from GameBot.utils import StopTaskError, WindowLostError, logger, setup_log_file
from GameBot.utils.exception_handler import setup_global_exception_hook


class EndlessTask:
    """无尽刷怪任务"""

    def __init__(self, cfg: dict):
        self.task_cfg = cfg
        self.dm = create_dm_client()
        # 自动无尽继承局内无尽配置，再用 [tasks.endless.endless] 中独有的字段覆盖
        endless_cfg = {
            **cfg["war3"]["jiubing2"]["tasks"]["endless"]["endless_single"],
            **cfg["war3"]["jiubing2"]["tasks"]["endless"]["endless"],
        }

        war3_cfg = self.task_cfg.get("war3", {})
        hero_cfg = self.task_cfg.get("hero", {})
        kk_cfg = self.task_cfg.get("kk", {})

        self.war3 = War3Business(self.dm, war3_cfg)
        self.kk = KKBusiness(self.dm, kk_cfg)
        self.ui = GameUI(self.dm, war3_cfg, hero_cfg, self.task_cfg, self.war3)
        self.nav = SceneNavigator(
            self.dm,
            war3_cfg,
            hero_cfg,
            self.task_cfg,
            self.war3,
            self.ui,
        )
        self.combat = CombatHelper(self.dm, war3_cfg, hero_cfg, self.task_cfg, self.war3)
        self.runner = EndlessRunner(self.dm, self.war3, self.ui, self.combat, war3_cfg, hero_cfg, self.task_cfg)
        self.endless_cfg = endless_cfg
        self.war3_cfg = war3_cfg
        self.kk_cfg = kk_cfg

        self.game_start_time = 0
        self.boss_death_time = 0
        self.pet_feed_time = 0

    def do_kk(self) -> None:
        # 先尝试找到已有房间
        room_hwnd = self.kk.dismiss_room_popups(self.dm)
        if room_hwnd:
            # 找到房间，直接开始游戏（传入 room_hwnd 避免重复检测）
            self.kk.start_game(self.dm, room_hwnd=room_hwnd)
            return
        # 未找到房间，清理主界面弹窗后创建
        logger.info("未找到 KK 房间，开始自动创建房间")
        self.kk.dismiss_hall_popups(self.dm)
        map_name = self.task_cfg.get("game", {}).get("map_name", "九种兵器2诸神战场")
        room_hwnd = self.kk.create_room(self.dm, map_name=map_name)
        if not room_hwnd:
            logger.error(
                "创建房间失败，跳过本局。建议检查：1) KK 主界面是否正常显示 2) 搜索结果是否包含目标地图 3) 创建房间弹窗是否出现 4) 网络是否正常"
            )
            return
        self.kk.start_game(self.dm, room_hwnd=room_hwnd)

    def _interruptible_wait(self, seconds: float):
        """可被停止信号中断的等待，检测到停止时抛出 StopTaskError。"""
        if self._stop_event is not None:
            if self._stop_event.wait(seconds):
                raise StopTaskError("用户请求停止任务")
        else:
            time.sleep(seconds)

    def _find_target_war3_hwnd(self) -> int:
        """查找目标 War3 窗口（支持多开识别）。"""
        target_player = self.endless_cfg.get("target_player", "")
        return self.war3.find_target_war3_hwnd(target_player)

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
        # 多开时验证窗口归属
        target_player = self.endless_cfg.get("target_player", "")
        if target_player:
            owner = self.war3.identify_war3_owner(hwnd)
            if owner != target_player:
                logger.warning(f"War3 窗口归属 {owner} 与目标 {target_player} 不匹配，尝试查找目标窗口")
                target_hwnd = self._find_target_war3_hwnd()
                if target_hwnd:
                    hwnd = target_hwnd
                else:
                    logger.error(f"未找到归属 {target_player} 的 War3 窗口，跳过本局")
                    with self.dm.bind_window(hwnd, bind_cfg=self.war3_cfg.get("bind", {})):
                        self.war3.quit_game()
                    return False
        self.war3.set_client_size(hwnd)
        try:
            with self.dm.bind_window(hwnd, bind_cfg=self.war3_cfg.get("bind", {})):
                try:
                    self.runner.wait_enter_game(self, self._stop_event)
                    self.runner.do_preparation_phase(self.endless_cfg, self._stop_event)
                    self.ui.switch_attribute_panel(is_fold=True)
                    self.nav.enter_palace(self._stop_event)
                    self.nav.enter_endless(self, self.endless_cfg, self._stop_event)
                    self.runner.start_endless(self, game_idx, self.endless_cfg)
                except TimeoutError as e:
                    logger.error(f"卡在加载界面，关闭 War3：{e}")
                    self.war3.quit_game()
                    return False
                except BossDeathTimeoutError:
                    logger.warning("BOSS 死亡超时，退出本局 War3")
                    self.war3.quit_game()
                    return False
                # 正常退出
                self.war3.quit_game()
        except WindowLostError:
            logger.error("掉线，War3 窗口消失")
            self._handle_kk_disconnect()
            return False

        self._interruptible_wait(self.endless_cfg.get("loop_interval_time", 5))
        return True

    def _handle_kk_disconnect(self) -> None:
        """检测并处理 KK 掉线重连弹窗。"""
        self.kk.handle_disconnect_dialog(self.dm)

    def run(self, stop_event=None, progress_callback=None):
        self._stop_event = stop_event
        self._progress_callback = progress_callback or (lambda text: None)
        games = self.endless_cfg.get("games", 10)
        min_level = self.endless_cfg.get("min_level", 15)
        max_level = self.endless_cfg.get("max_level", 100)
        logger.info(f"游戏总局数：{games}，每局刷怪楼层：{min_level} -> {max_level}")
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

    # 预加载 OCR（无尽任务不需要宝箱和战斗模型）
    get_inference_client(load_chest=False, load_combat=False)

    def task_wrapper(stop_event, progress_callback=None):
        EndlessTask(cfg).run(stop_event=stop_event, progress_callback=progress_callback)

    run_with_float_window("无尽刷怪", task_wrapper, countdown_seconds=5, float_cfg=cfg.get("float_window", {}))


if __name__ == "__main__":
    main()
