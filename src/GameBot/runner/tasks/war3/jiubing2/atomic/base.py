"""
原子任务基类 — 接取任务 → 沿路线清怪 → 检测完成 → 回 NPC 交任务。

子类需指定类属性：
- _task_label：任务显示名（用于日志）
- _walk_offset：走到 NPC 附近的坐标偏移 [dx, dy]
- _task_grid_key：NPC 配置中任务技能格的键名

子类需实现：
- _npc：返回任务 NPC 配置（含 coords / mini_coords / walk_mode / time 等）
"""
from __future__ import annotations

import time
from typing import TYPE_CHECKING, Optional

from GameBot.utils import StopTaskError, logger

if TYPE_CHECKING:
    from GameBot.runner import DmClient
    from GameBot.runner.business.war3 import TextMonitor, War3Business
    from GameBot.runner.business.war3.jiubing2 import CombatHelper, GameUI, NearbyCleaner


class AtomicTaskBase:
    """原子任务基类。

    封装"接取 → 路线清怪 → 检测完成 → 回 NPC 提交"的通用流程。
    子类通过类属性差异化 NPC 定位、行走偏移和技能格选择。
    """

    _task_label = "原子任务"       # 任务显示名（子类覆写）
    _walk_offset = [0, 0]          # 走到 NPC 附近的坐标偏移（子类覆写）
    _task_grid_key = "grid"        # NPC 配置中任务技能格的键名（子类覆写）
    _npc_key = ""                  # NPC 唯一标识（场景名+NPC名，子类覆写或自动推断）

    def __init__(self, dm: "DmClient", war3: "War3Business",
                 ui: "GameUI", combat: "CombatHelper", task_cfg: dict,
                 at_npc: bool = False, walk_time: Optional[float] = None,
                 monitor: "TextMonitor" = None,
                 nearby_cleaner: "NearbyCleaner" = None):
        self.dm = dm
        self.war3 = war3
        self.ui = ui
        self.combat = combat
        self.cfg = task_cfg
        # 英雄是否已在任务 NPC 附近（如上一轮提交后停在 NPC 旁），为真则跳过接取前的行走
        self.at_npc = at_npc
        # 走到任务 NPC 的等待时间覆盖（None 则用 npc 配置的 time）
        self.walk_time = walk_time
        # 持续文字监测器（TextMonitor）；为 None 时回退到 war3 的起停式 watcher/wait_for_text
        self.monitor = monitor
        # 定时清理英雄附近物品（由上层 AtomicLoopTask 传入，在路线点之间调用 tick）
        self.nearby_cleaner = nearby_cleaner
        # 用户停止事件（由 run 参数传入，None 时不支持中断）
        self._stop_event = None

    def _interruptible_wait(self, seconds: float):
        """可被停止信号中断的等待，检测到停止时抛出 StopTaskError。"""
        if self._stop_event is not None:
            if self._stop_event.wait(seconds):
                raise StopTaskError("用户请求停止任务")
        else:
            time.sleep(seconds)

    def run(self, stop_event=None) -> bool:
        self._stop_event = stop_event
        logger.info(f"开始{self._task_label}任务")
        try:
            if not self._accept():
                logger.error("接取任务失败")
                return False
            if not self._clear_route():
                logger.error("杀怪阶段失败")
                return False
        except StopTaskError:
            logger.info(f"用户请求停止，终止{self._task_label}任务")
            raise
        logger.info(f"{self._task_label}任务完成")
        return True

    @property
    def _npc(self) -> dict:
        """任务 NPC 配置（子类必须实现）。"""
        raise NotImplementedError

    def _on_point_arrival(self, pt: dict, complete_event) -> None:
        """到达路线点后的钩子（子类可覆写，例如施放技能）。"""
        pass
    # ── 接取任务 ──────────────────────────────────────────

    def _accept(self) -> bool:
        gt = self.combat.war3_cfg['general_time']
        npc = self._npc
        self.dm.key_press_char('F1')
        self._interruptible_wait(gt)
        coords = npc['coords']
        offset = npc.get("walk_offset", [0, 0])
        if not self.at_npc:
            wait_time = self.walk_time if self.walk_time is not None else npc.get("time", 5)
            self.war3.move_to_minimap_point(
                npc["mini_coords"],
                [coords[0] + offset[0], coords[1] + offset[1]],
                mode=npc.get("walk_mode", 1),
                wait_time=wait_time,
                stop_event=self._stop_event,
            )
        # 点击任务 NPC
        self.dm.move_to(*coords)
        self._interruptible_wait(gt)
        self.dm.left_click()
        self._interruptible_wait(self.combat.war3_cfg['small_window_response_time'])
        # 点击任务技能格
        grid = npc.get(self._task_grid_key, [1, 1])
        sx, sy = self.ui.get_skill_coords(grid[0], grid[1])
        self.dm.move_to(sx, sy)
        self._interruptible_wait(gt)
        self.dm.left_click()
        self._interruptible_wait(gt)

        accept_text = self.combat.cfg.get("atomic_task", {}).get("accept_text", "")
        accept_timeout = self.cfg.get("accept_timeout", 8)
        prompt_text = self.combat.cfg.get("prompt_text")
        if self.monitor is not None:
            return self.monitor.wait_for(accept_text, timeout=accept_timeout)
        return self.war3.wait_for_text(
            prompt_text, accept_text,
            timeout=accept_timeout,
            stop_event=self._stop_event,
        )

    # ── 路线清怪 ──────────────────────────────────────────

    def _clear_route(self) -> bool:
        """沿路线点推进，后台 OCR 实时检测"已完成"。

        中途检测到完成时，不再按路线依次走，立刻执行最后一个路线点（回 NPC 附近，
        不中断、走完整等待时间）以自动提交；路线正常走完则最后一点已执行，无需再走。
        """
        complete_text = self.combat.cfg.get("atomic_task", {}).get("complete_text", "")
        complete_event = self.monitor.watch(complete_text)
        # 组合事件：complete_event 或用户 stop_event 任一触发即中断行走
        combined_event = _CombinedEvent(complete_event, self._stop_event)
        points = self.cfg.get("points", [])
        gt = self.combat.war3_cfg['general_time']

        try:
            # 沿路线推进，检测到完成即中断后续路线点
            for pt in points:
                if complete_event.is_set():
                    break
                # 定时清理英雄附近物品（在路线点之间执行）
                if self.nearby_cleaner is not None:
                    self.nearby_cleaner.tick()
                logger.info(f'走到：{pt.get("desc")}，预计 {pt.get("time", 5)}s')
                self.dm.key_press_char('F1')
                self._interruptible_wait(gt)
                try:
                    self.war3.move_to_minimap_point(
                        pt.get("mini_coords"), pt.get("coords"),
                        mode=pt.get("walk_mode", 1),
                        wait_time=pt.get("time", 5),
                        stop_event=combined_event,
                    )
                    self._on_point_arrival(pt, complete_event)
                except StopTaskError:
                    if self._stop_event is not None and self._stop_event.is_set():
                        raise  # 用户停止，向上传播
                    break  # complete_event 触发，正常中断去提交任务

            # 若路线走完仍未检测到完成，兜底等待（也响应停止）
            if not complete_event.is_set():
                timeout = self.cfg.get("route_complete_timeout", 120)
                if not combined_event.wait(timeout=timeout):
                    logger.error("路线走完仍未检测到完成提示")
                    return False

            # 检测到完成后，确保回到最后一个路线点（NPC 附近）以自动提交任务
            # （移动可能被 complete_event 中断，英雄未必已到达末点）
            if points:
                last_pt = points[-1]
                logger.info(f'任务完成，返回NPC附近提交：{last_pt.get("desc")}')
                self.dm.key_press_char('F1')
                self._interruptible_wait(gt)
                self.war3.move_to_minimap_point(
                    last_pt.get("mini_coords"), last_pt.get("coords"),
                    mode=last_pt.get("walk_mode", 1),
                    wait_time=last_pt.get("time", 5),
                    stop_event=self._stop_event,
                )
            return True
        finally:
            if self.monitor is not None:
                self.monitor.unwatch(complete_event)
            else:
                self.war3.stop_text_watcher(complete_event)


class _CombinedEvent:
    """组合两个 threading.Event：任一被 set 即视为触发。

    用于让 move_to_minimap_point 的 stop_event 同时响应任务完成事件和用户停止事件。
    """

    def __init__(self, *events):
        self._events = [e for e in events if e is not None]

    def is_set(self) -> bool:
        return any(e.is_set() for e in self._events)

    def wait(self, timeout: float = None) -> bool:
        """轮询等待，任一事件被 set 即返回 True。

        用短轮询周期（0.1s）模拟多事件 wait，避免依赖底层实现。
        """
        if not self._events:
            if timeout is not None:
                time.sleep(timeout)
            return False
        deadline = None
        if timeout is not None:
            deadline = time.monotonic() + timeout
        while True:
            if self.is_set():
                return True
            if deadline is not None:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return False
                time.sleep(min(0.1, remaining))
            else:
                time.sleep(0.1)
