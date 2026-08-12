"""
城门骚扰原子任务
流程：走到 NPC → 点技能格接任务 → 沿路线 A 过去 → OCR 检测完成 → 回 NPC 交任务。
后台 OCR 线程实时监测任务进度，检测到完成立即中断移动。
"""
from GameBot.utils import logger, setup_log_file
from GameBot.config import config
from GameBot.utils.exception_handler import setup_global_exception_hook
from GameBot.inference import get_ocr_client
from GameBot.runner import DmClient
from GameBot.runner.business.war3 import War3Business
from GameBot.runner.business.war3.jiubing2 import GameUI, CombatHelper
from GameBot.runner.tasks.war3.jiubing2.atomic.base import AtomicTaskBase
from GameBot.runner.ui import run_with_float_window


class GateHarassmentTask(AtomicTaskBase):
    """城门骚扰原子任务。"""

    _task_label = "城门骚扰"
    _walk_offset = [-100, 0]
    _task_grid_key = "harassment_grid"

    @property
    def _npc(self) -> dict:
        """任务 NPC（黑石城守卫队长）。"""
        scenes = self.combat.cfg.get("scenes", {})
        return scenes.get("blackstone_city", {}).get("npcs", {}).get("guard_captain", {})

    def _on_point_arrival(self, pt: dict, complete_event) -> None:
        """到达路线点后执行 actions。"""
        if complete_event.is_set():
            return
        self.combat.execute_actions(pt, pt.get('coords'), stop_event=self._stop_event)


# ── 独立运行入口 ──────────────────────────────────────────

def main():
    setup_global_exception_hook()
    setup_log_file("城门骚扰任务")
    logger.info("############################# 城门骚扰任务 #############################")

    cfg = config.load_task("war3.jiubing2.tasks.atomic.blackstone_gate_harassment")
    task_cfg = cfg["war3"]["jiubing2"]["tasks"]["atomic"]["blackstone_gate_harassment"]

    def task_wrapper(stop_event, progress_callback=None):
        # 创建任务所需对象（所有配置来自单一 load_task 结果）
        dm = DmClient()
        war3_cfg = cfg.get("war3", {})
        hero_cfg = cfg.get("hero", {})
        war3 = War3Business(dm, war3_cfg)

        ui = GameUI(dm, war3_cfg, hero_cfg, cfg, war3)
        combat = CombatHelper(dm, war3_cfg, hero_cfg, cfg, war3)

        # 获取活动的war3窗口为操作窗口
        hwnd = dm.get_active_window(war3_cfg["window_class"], war3_cfg["window_title"])
        if not hwnd:
            logger.error("未找到 war3 窗口")
            return
        with dm.bind_window(hwnd):
            war3.set_client_size(hwnd)
            # 预热 OCR 子进程（启动 + 加载 OCR 模型，约数秒），避免占用 wait_for_text 超时
            get_ocr_client()
            task = GateHarassmentTask(dm, war3, ui, combat, task_cfg)
            task.run(stop_event=stop_event)

    run_with_float_window("城门骚扰任务", task_wrapper, countdown_seconds=5, float_cfg=cfg.get("float_window", {}))


if __name__ == "__main__":
    main()
