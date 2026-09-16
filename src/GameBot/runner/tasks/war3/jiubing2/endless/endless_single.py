"""
单局无尽刷分 — 已在无尽地图内，直接开刷
"""

import time

from GameBot.config import config, get_task_view
from GameBot.inference import get_inference_client
from GameBot.runner import create_dm_client
from GameBot.runner.business.war3 import War3Business
from GameBot.runner.business.war3.jiubing2 import (
    CombatHelper,
    EndlessRunner,
    GameUI,
)
from GameBot.runner.business.war3.jiubing2.endless_runner import BossDeathTimeoutError
from GameBot.runner.ui import run_with_float_window
from GameBot.utils import StopTaskError, logger, setup_log_file
from GameBot.utils.exception_handler import setup_global_exception_hook


class EndlessSingleTask:
    """无尽刷怪任务（已在无尽地图内）"""

    def __init__(self, cfg: dict):
        self.task_cfg = cfg
        self.dm = create_dm_client()
        # 任务视图：本任务无变体，即 endless_single 段自身
        endless_cfg = get_task_view(cfg, "war3.jiubing2.tasks.endless.endless_single")

        war3_cfg = self.task_cfg.get("war3", {})
        hero_cfg = self.task_cfg.get("hero", {})

        self.war3 = War3Business(self.dm, war3_cfg)
        self.ui = GameUI(self.dm, war3_cfg, hero_cfg, self.task_cfg, self.war3)
        self.combat = CombatHelper(self.dm, war3_cfg, hero_cfg, self.task_cfg, self.war3)
        self.runner = EndlessRunner(self.dm, self.war3, self.ui, self.combat, war3_cfg, hero_cfg, self.task_cfg)
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
        logger.info(f"游戏总局数：{games}，每局刷怪楼层：{min_level} -> {max_level}")
        self._progress_callback(f"楼层 {min_level}/{max_level}")
        hwnd = self.war3.find_game_window()
        if not hwnd:
            logger.error("未找到 war3 窗口")
            return
        self.war3.set_client_size(hwnd)
        try:
            with self.dm.bind_window(hwnd, bind_cfg=self.war3_cfg.get("bind", {})):
                try:
                    self.runner.clear_endless_monster_loop(self, 1, self.endless_cfg)
                except BossDeathTimeoutError:
                    logger.warning("BOSS 死亡超时，结束本局")
        except StopTaskError:
            logger.info("收到停止信号，停止无尽刷怪")
        logger.info("无尽刷怪任务结束")


def main():
    setup_global_exception_hook()
    setup_log_file("单局无尽")
    logger.info("############################# 无尽刷怪任务 #############################")
    cfg = config.load_task("war3.jiubing2.tasks.endless.endless_single")

    # 预加载 OCR（无尽单局不需要宝箱和战斗模型）
    get_inference_client(load_chest=False, load_combat=False)

    def task_wrapper(stop_event, progress_callback=None):
        EndlessSingleTask(cfg).run(stop_event=stop_event, progress_callback=progress_callback)

    run_with_float_window("无尽刷怪", task_wrapper, countdown_seconds=5, float_cfg=cfg.get("base", {}).get("float_window", {}))


if __name__ == "__main__":
    main()


# ── 组队任务步骤 ────────────────────────────────────────────


from GameBot.runner.business.war3.jiubing2.team_steps_base import Jiubing2TaskSteps


class _EndlessSingleSteps(Jiubing2TaskSteps):
    """无尽单局组队步骤 — position_init 进入无尽地图，run_task 无尽刷怪。"""

    def position_init(self, member, stop_event=None, **kwargs):
        """就位 — 折叠属性面板 → 进入皇宫 → 进入无尽地图。"""
        from GameBot.runner.business.war3.jiubing2.team_steps_base import _build_business_objects

        ui, nav, combat, runner = _build_business_objects(member)
        endless_cfg = (
            member.task_cfg.get("war3", {})
            .get("jiubing2", {})
            .get("tasks", {})
            .get("endless", {})
            .get("endless_single", {})
        )

        logger.info("组队无尽就位：进入皇宫 → 进入无尽")
        ui.switch_attribute_panel(is_fold=True)
        nav.enter_palace(stop_event)
        nav.enter_endless(member.task_ctx, endless_cfg, stop_event)
        logger.info("组队无尽就位完成")

    def run_task(self, member, stop_event=None, **kwargs):
        """无尽刷怪主循环。"""
        from GameBot.runner.business.war3.jiubing2.endless_runner import BossDeathTimeoutError
        from GameBot.runner.business.war3.jiubing2.team_steps_base import _build_business_objects

        ui, nav, combat, runner = _build_business_objects(member)
        endless_cfg = (
            member.task_cfg.get("war3", {})
            .get("jiubing2", {})
            .get("tasks", {})
            .get("endless", {})
            .get("endless_single", {})
        )

        if not endless_cfg:
            logger.error("run_task 缺少 endless_cfg")
            member._flow_failed = True
            return

        logger.info(f"开始无尽刷怪 (round={member._current_round})")
        try:
            runner.start_endless(member.task_ctx, member._current_round, endless_cfg)
        except BossDeathTimeoutError:
            logger.warning(f"BOSS 死亡超时（{'同步源' if member.is_sync_source else '非同步源'}），结束本局")
            member._flow_failed = True


_steps = _EndlessSingleSteps()
preparation = _steps.preparation
position_init = _steps.position_init
pre_exit = _steps.pre_exit
run_task = _steps.run_task
