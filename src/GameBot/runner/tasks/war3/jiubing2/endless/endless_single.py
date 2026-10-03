"""
单局无尽刷分 — 已在无尽地图内，直接开刷

多开用法（本机两个玩家各跑各的单局无尽，互不干扰）：
    uv run python -m GameBot.runner.tasks.war3.jiubing2.endless.endless_single endless_single_善木木
变体配置 tasks/endless/endless_single_<玩家名>.toml 需写 target_player、
[war3] bind_mode="background"（多开必须后台绑定）等差异字段。
局内任务认领：启动时已在游戏内，默认发聊天 token，OCR 聊天区"玩家名：token"
回显定归属；认领失败任务停止，避免误操作另一账号窗口。
"""

import sys
import time

from GameBot.config import config, get_task_view, resolve_bind_cfg
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

    def __init__(self, cfg: dict, task_name: str = "war3.jiubing2.tasks.endless.endless_single"):
        self.task_cfg = cfg
        self.dm = create_dm_client()
        # 任务视图：沿 extends 链深合并（endless_single → 变体）
        endless_cfg = get_task_view(cfg, task_name)

        war3_cfg = self.task_cfg.get("war3", {})
        hero_cfg = self.task_cfg.get("hero", {})

        self.war3 = War3Business(self.dm, war3_cfg)
        # 多开认领：target_player 在变体 [this] 里配置，注入 war3 供 find_game_window 认领链路读取
        self.war3.target_player = endless_cfg.get("target_player", "")
        self.war3.task_name = task_name
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
        min_level = self.endless_cfg.get("min_level", 15)
        max_level = self.endless_cfg.get("max_level", 100)
        logger.info(f"刷怪楼层：{min_level} -> {max_level}")
        self._progress_callback(f"楼层 {min_level}/{max_level}")
        hwnd = self.war3.find_game_window()
        if not hwnd:
            logger.error("未找到 war3 窗口")
            return
        self.war3.set_client_size(hwnd)
        try:
            with self.dm.bind_window(hwnd, bind_cfg=resolve_bind_cfg(self.war3_cfg)):
                try:
                    self.runner.clear_endless_monster_loop(self, 1, self.endless_cfg)
                except BossDeathTimeoutError:
                    logger.warning("BOSS 死亡超时，结束本局")
        except StopTaskError:
            logger.info("收到停止信号，停止无尽刷怪")
        logger.info("无尽刷怪任务结束")


def main():
    setup_global_exception_hook()
    # 命令行参数可指定变体配置名（如 endless_single_岁月神偷 认领指定玩家窗口）
    # 用法：python -m GameBot.runner.tasks.war3.jiubing2.endless.endless_single endless_single_岁月神偷
    task_name = "war3.jiubing2.tasks.endless.endless_single"
    if len(sys.argv) > 1:
        leaf_arg = sys.argv[1]
        task_name = leaf_arg if "." in leaf_arg else f"war3.jiubing2.tasks.endless.{leaf_arg}"
    cfg = config.load_task(task_name)

    # 显示名动态计算：变体配置带 target_player 时拼上玩家名
    target_player = get_task_view(cfg, task_name).get("target_player", "")
    title = f"单局无尽-{target_player}" if target_player else "单局无尽"

    setup_log_file(title)
    logger.info(f"############################# {title} #############################")
    if task_name != "war3.jiubing2.tasks.endless.endless_single":
        logger.info(f"使用指定配置: {task_name}")

    # 预加载 OCR（无尽单局不需要宝箱和战斗模型）
    get_inference_client(load_chest=False, load_combat=False)

    def task_wrapper(stop_event, progress_callback=None):
        EndlessSingleTask(cfg, task_name=task_name).run(stop_event=stop_event, progress_callback=progress_callback)

    run_with_float_window(title, task_wrapper, countdown_seconds=5, float_cfg=cfg.get("base", {}).get("float_window", {}))


if __name__ == "__main__":
    main()
