"""
小炎蛇（LV4）原子任务（卡米村）
流程：走到村民杰菲特 → 点技能格接任务 → 沿路线过去 → OCR 检测完成 → 回 NPC 交任务。
前置要求：本局游戏内必须完成至少一次「毒蛇」任务才能接取。
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


class LittleFlameSnakeTask(AtomicTaskBase):
    """小炎蛇（LV4）原子任务。

    前置要求：本局完成至少一次「毒蛇」任务。
    通过类属性 prerequisite_done 标志判断，由 MultiAtomicLoopTask 在编排时设置。
    """

    # 统一的任务显示名（TOML 配置和日志均引用此常量，避免格式不一致）
    TASK_LABEL = "小炎蛇（LV4）"

    _task_label = TASK_LABEL
    _walk_offset = [0, 0]
    _task_grid_key = "little_flame_snake_grid"
    _npc_key = "kami_village.jephite"

    # 前置任务标志：本局是否已完成至少一次「毒蛇」
    # 由 MultiAtomicLoopTask 在编排时设置为 True
    prerequisite_done = False

    @property
    def _npc(self) -> dict:
        """任务 NPC（村民杰菲特，卡米村场景）。"""
        scenes = self.combat.cfg.get("scenes", {})
        return scenes.get("kami_village", {}).get("npcs", {}).get("jephite", {})


# ── 独立运行入口 ──────────────────────────────────────────

def main():
    setup_global_exception_hook()
    setup_log_file("小火焰蛇任务")
    logger.info(f"############################# {LittleFlameSnakeTask.TASK_LABEL}任务 #############################")

    cfg = config.load_task("war3.jiubing2.tasks.atomic.little_flame_snake")
    task_cfg = cfg["war3"]["jiubing2"]["tasks"]["atomic"]["little_flame_snake"]

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
            task = LittleFlameSnakeTask(dm, war3, ui, combat, task_cfg)
            task.run(stop_event=stop_event)

    run_with_float_window(f"{LittleFlameSnakeTask.TASK_LABEL}任务", task_wrapper, countdown_seconds=5, float_cfg=cfg.get("float_window", {}))


if __name__ == "__main__":
    main()
