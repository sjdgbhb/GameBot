"""
局内特殊任务 — 节日活动局内编排脚本。
英雄起始位置：黑石城城门骚扰任务 NPC 附近（可直接接取任务的位置）。
流程：每日声望（黑石城 + 森之城）→ 森之城内步行至鱼点 → 钓鱼 N 次抛竿。
配置仅通过一次 config.load_task("war3.jiubing2.tasks.festival.ingame_special") 加载，
依赖闭包含 tasks.reputation.daily_reputation 与 tasks.others.fishing（及其传递依赖）。
[this.reputation] / [this.fishing] 段在构造子任务前深度合并到对应命名空间节点，
实现仅对本任务生效的参数覆盖（声望开关、抛竿次数、抛竿坐标等）。
"""

import copy

from GameBot.config import config
from GameBot.runner.tasks.war3.jiubing2.others.fishing import FishingTask
from GameBot.runner.tasks.war3.jiubing2.reputation.daily_reputation import DailyReputationTask
from GameBot.runner.ui import run_with_float_window
from GameBot.utils import logger, setup_log_file
from GameBot.utils.exception_handler import setup_global_exception_hook


class IngameSpecialTask:
    """局内特殊任务 — 顺序编排：每日声望 → 步行至鱼点 → 钓鱼。"""

    def __init__(self, cfg: dict):
        self.cfg = cfg["war3"]["jiubing2"]["tasks"]["festival"]["ingame_special"]
        # 先应用本任务的子配置覆盖，再以生效配置构造子任务
        self.full_cfg = self._apply_overrides(cfg)
        self.daily = DailyReputationTask(self.full_cfg)
        # 复用黑石城声望的大漠客户端和业务对象，避免多占一个 dm_bridge 子进程
        self.dm = self.daily.blackstone.dm
        self.war3 = self.daily.blackstone.war3
        self.war3_cfg = self.full_cfg.get("war3", {})

    @property
    def task_name(self) -> str:
        return self.cfg.get("name", "局内特殊任务")

    def _apply_overrides(self, cfg: dict) -> dict:
        """将 [this.reputation] / [this.fishing] 深度合并到对应任务命名空间，返回深拷贝配置。"""
        effective = copy.deepcopy(cfg)
        tasks = effective["war3"]["jiubing2"]["tasks"]
        for section, node in (
            ("reputation", tasks["reputation"]["daily_reputation"]),
            ("fishing", tasks["others"]["fishing"]),
        ):
            overrides = self.cfg.get(section)
            if isinstance(overrides, dict):
                config._deep_merge(node, overrides)
        return effective

    def run(self, stop_event=None, progress_callback=None, progress_lines_callback=None):
        enable_reputation = self.cfg.get("enable_reputation", True)
        enable_fishing = self.cfg.get("enable_fishing", True)
        logger.info(
            f"{self.task_name}开始（每日声望={'开' if enable_reputation else '关'}，"
            f"钓鱼={'开' if enable_fishing else '关'}）"
        )

        # 多行进度：声望两行由 DailyReputationTask 维护，钓鱼行由本层维护
        rep_lines: list = []
        fishing_line: list = []

        def _emit_lines():
            if progress_lines_callback is not None:
                progress_lines_callback(rep_lines + fishing_line)

        def _rep_lines_cb(lines):
            rep_lines[:] = lines
            _emit_lines()

        def _fishing_cb(text):
            fishing_line[:] = [f"钓鱼：{text}"]
            _emit_lines()
            if progress_callback is not None:
                progress_callback(text)

        if enable_fishing:
            # 预置钓鱼行占位，让三行从一开始就显示
            fishing_cfg = self.full_cfg["war3"]["jiubing2"]["tasks"]["others"]["fishing"]
            fishing_line.append(f"钓鱼：抛竿 0/{fishing_cfg.get('max_times', 350)}")
            _emit_lines()

        # 1) 每日声望：黑石城（城门骚扰 ×N）→ 转场 → 森之城（迅猛野兽 ×N）
        if enable_reputation:
            self.daily.run(stop_event=stop_event, progress_lines_callback=_rep_lines_cb)

        # 2) 森之城内步行至鱼点 → 钓鱼循环
        if enable_fishing and (stop_event is None or not stop_event.is_set()):
            fishing_line[:] = ["钓鱼：前往钓鱼点"]
            _emit_lines()
            self._walk_to_fishing_spot(stop_event)
            FishingTask(
                self.full_cfg,
                stop_event=stop_event,
                progress_callback=_fishing_cb,
                dm=self.dm,
            ).run()

        logger.info(f"{self.task_name}结束")

    def _walk_to_fishing_spot(self, stop_event):
        """森之城内步行至钓鱼点：小地图切视角 → 点击目标点移动。"""
        spot = self.cfg.get("fishing_spot")
        if not spot:
            logger.info("未配置鱼点，原地钓鱼")
            return
        logger.info(f"前往钓鱼点：{spot.get('desc', '')}（等待 {spot.get('time', 10)}s）")
        hwnd = self.dm.get_active_window(self.war3_cfg["window_class"], self.war3_cfg["window_title"])
        if not hwnd:
            logger.error("未找到 war3 窗口，无法前往鱼点")
            return
        with self.dm.bind_window(hwnd, bind_cfg=self.war3_cfg.get("bind", {})):
            self.war3.set_client_size(hwnd)
            self.war3.move_to_minimap_point(
                spot.get("mini_coords"),
                spot.get("coords"),
                spot.get("walk_mode", 2),
                spot.get("time", 10),
                stop_event,
            )


def main():
    setup_global_exception_hook()
    setup_log_file("局内特殊任务")
    logger.info("############################# 局内特殊任务 #############################")
    cfg = config.load_task("war3.jiubing2.tasks.festival.ingame_special")

    def task_wrapper(stop_event, progress_callback=None, progress_lines_callback=None):
        IngameSpecialTask(cfg).run(
            stop_event=stop_event,
            progress_callback=progress_callback,
            progress_lines_callback=progress_lines_callback,
        )

    run_with_float_window("局内特殊任务", task_wrapper, countdown_seconds=5, float_cfg=cfg.get("float_window", {}))


if __name__ == "__main__":
    main()
