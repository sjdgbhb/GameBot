"""
毒蛇原子任务（卡米村）
流程：走到村民杰菲特 → 点技能格接任务 → 沿路线过去 → OCR 检测完成 → 回 NPC 交任务。
后台 OCR 线程实时监测任务进度，检测到完成立即中断移动。
"""
from GameBot.config import config
from GameBot.inference import get_ocr_client
from GameBot.runner import DmClient
from GameBot.runner.business.war3 import War3Business
from GameBot.runner.business.war3.jiubing2 import CombatHelper, GameUI
from GameBot.runner.tasks.war3.jiubing2.atomic.base import AtomicTaskBase
from GameBot.runner.ui import run_with_float_window
from GameBot.utils import logger, setup_log_file
from GameBot.utils.exception_handler import setup_global_exception_hook


class VenomousSnakeTask(AtomicTaskBase):
    """毒蛇原子任务。"""

    _task_label = "毒蛇"
    _walk_offset = [0, 0]
    _task_grid_key = "venomous_snake_grid"
    _npc_key = "kami_village.jephite"

    @property
    def _npc(self) -> dict:
        """任务 NPC（村民杰菲特，卡米村场景）。"""
        scenes = self.combat.cfg.get("scenes", {})
        return scenes.get("kami_village", {}).get("npcs", {}).get("jephite", {})


# ── 独立运行入口 ──────────────────────────────────────────

def main():
    setup_global_exception_hook()
    setup_log_file("毒蛇任务")
    logger.info("############################# 毒蛇任务 #############################")

    cfg = config.load_task("war3.jiubing2.tasks.atomic.venomous_snake")
    task_cfg = cfg["war3"]["jiubing2"]["tasks"]["atomic"]["venomous_snake"]

    def task_wrapper(stop_event, progress_callback=None):
        dm = DmClient()
        war3_cfg = cfg.get("war3", {})
        hero_cfg = cfg.get("hero", {})
        war3 = War3Business(dm, war3_cfg)

        ui = GameUI(dm, war3_cfg, hero_cfg, cfg, war3)
        combat = CombatHelper(dm, war3_cfg, hero_cfg, cfg, war3)

        hwnd = dm.get_active_window(war3_cfg["window_class"], war3_cfg["window_title"])
        if not hwnd:
            logger.error("未找到 war3 窗口")
            return
        with dm.bind_window(hwnd):
            war3.set_client_size(hwnd)
            get_ocr_client()
            task = VenomousSnakeTask(dm, war3, ui, combat, task_cfg)
            task.run(stop_event=stop_event)

    run_with_float_window("毒蛇任务", task_wrapper, countdown_seconds=5, float_cfg=cfg.get("float_window", {}))


if __name__ == "__main__":
    main()
