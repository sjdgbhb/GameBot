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
    from GameBot.runner.business.war3 import TextMonitor, War3Business
    from GameBot.runner.business.war3.jiubing2 import CombatHelper, GameUI, NearbyCleaner
    from GameBot.runner.driver.base import DmClientBase as DmClient


class AtomicTaskBase:
    """原子任务基类。

    封装"接取 → 路线清怪 → 检测完成 → 回 NPC 提交"的通用流程。
    子类通过类属性差异化 NPC 定位、行走偏移和技能格选择。
    """

    _task_label = "原子任务"  # 任务显示名（子类覆写）
    _walk_offset = [0, 0]  # 走到 NPC 附近的坐标偏移（子类覆写）
    _task_grid_key = "grid"  # NPC 配置中任务技能格的键名（子类覆写）
    _npc_key = ""  # NPC 唯一标识（场景名+NPC名，子类覆写或自动推断）

    def __init__(
        self,
        dm: "DmClient",
        war3: "War3Business",
        ui: "GameUI",
        combat: "CombatHelper",
        task_cfg: dict,
        walk_time: Optional[float] = None,
        monitor: "TextMonitor" = None,
        nearby_cleaner: "NearbyCleaner" = None,
    ):
        self.dm = dm
        self.war3 = war3
        self.ui = ui
        self.combat = combat
        self.cfg = task_cfg
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
        if self._try_accept():
            return True
        # 接取被拒：若提示"任务已接取需完成后才能再接"（上次遗留未完成），
        # 放弃遗留任务并等待冷却后重接一次
        if self._handle_already_accepted():
            return self._try_accept()
        return False

    def _try_accept(self) -> bool:
        gt = self.combat.war3_cfg["general_time"]
        npc = self._npc
        self.dm.key_press_char("F1")
        self._interruptible_wait(gt)
        coords = npc["coords"]
        offset = npc.get("walk_offset", [0, 0])
        # 先走到 NPC 附近，再点击接任务
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
        self._interruptible_wait(self.combat.war3_cfg["small_window_response_time"])
        # 点击任务技能格
        grid = npc.get(self._task_grid_key, [1, 1])
        sx, sy = self.ui.get_skill_coords(grid[0], grid[1])
        self.dm.move_to(sx, sy)
        self._interruptible_wait(gt)
        self.dm.left_click()
        self._interruptible_wait(gt)

        accept_text = self.combat.cfg.get("war3", {}).get("jiubing2", {}).get("atomic_task", {}).get("accept_text", "")
        accept_timeout = self.cfg.get("accept_timeout", 8)
        prompt_text = self.combat.cfg.get("war3", {}).get("jiubing2", {}).get("prompt_text")
        if self.monitor is not None:
            return self.monitor.wait_for(accept_text, timeout=accept_timeout)
        return self.war3.wait_for_text(
            prompt_text,
            accept_text,
            timeout=accept_timeout,
            stop_event=self._stop_event,
        )

    # ── 放弃遗留任务 ──────────────────────────────────────

    def _handle_already_accepted(self) -> bool:
        """接取失败后检测"任务已接取"提示，命中则放弃遗留任务并等待重接冷却。

        :return: True=已执行放弃流程可重试接取；False=非"已接取"原因，直接判失败
        """
        atomic_cfg = self.combat.cfg.get("war3", {}).get("jiubing2", {}).get("atomic_task", {})
        accepted_kw = self.war3._normalize_ocr(atomic_cfg.get("already_accepted_text", ""))
        if not accepted_kw:
            return False
        # 读最近一次提示区 OCR 文本：有监测线程取 latest，否则现场读一次
        if self.monitor is not None:
            seen = self.monitor.latest
        else:
            prompt_text = self.combat.cfg.get("war3", {}).get("jiubing2", {}).get("prompt_text")
            if not prompt_text:
                return False
            try:
                seen = self.war3._normalize_ocr(self.war3._ocr_region_text(prompt_text))
            except Exception as e:
                logger.debug(f"接取失败后读提示区文本失败: {e}")
                return False
        if accepted_kw not in seen:
            return False

        logger.info(f"{self._task_label}已接取未完成，放弃遗留任务后重接")
        if not self._abandon_task():
            return False
        wait_time = atomic_cfg.get("abandon_wait_time", 60)
        logger.info(f"等待 {wait_time}s 后重新接取")
        self._interruptible_wait(wait_time)
        return True

    def _abandon_task(self) -> bool:
        """-rw 打开任务弹窗 → 点击任务名 → 点击确认弹窗"放弃"按钮。

        :return: 放弃操作是否完成（弹窗未开/未找到任务名/未找到放弃按钮均 False）
        """
        jiubing2 = self.combat.cfg.get("war3", {}).get("jiubing2", {})
        popup_cfg = jiubing2.get("task_popup", {})
        command_cfg = jiubing2.get("command", {})
        gt = self.combat.war3_cfg["general_time"]
        swt = self.combat.war3_cfg["small_window_response_time"]
        area = popup_cfg.get("area_coords", [])
        hwnd = self.war3._find_war3_hwnd()
        if not hwnd or not area:
            logger.error("放弃任务失败：未找到 war3 窗口或未配置 task_popup.area_coords")
            return False

        def _click_text(ocr_area, keyword, desc) -> bool:
            """OCR 区域内找含 keyword 的行并点击其中心，返回是否点到。"""
            lines = self.war3.ocr_lines(hwnd, {"area_coords": ocr_area})
            for line in lines:
                if keyword in line.get("text", ""):
                    x = ocr_area[0] + int(line.get("x_center", 0))
                    y = ocr_area[1] + int(line.get("y_center", 0))
                    logger.info(f"点击{desc}「{line.get('text')}」: ({x},{y})")
                    self.dm.move_to(x, y)
                    self._interruptible_wait(gt)
                    self.dm.left_click()
                    self._interruptible_wait(swt)
                    return True
            logger.warning(
                f"未找到{desc}「{keyword}」，OCR: {[l.get('text') for l in lines]}"
            )
            return False

        # 1) -rw 打开任务弹窗，点击本任务名行
        self.war3.send_msg(command_cfg.get("task_query", "-rw"), stop_event=self._stop_event)
        self._interruptible_wait(popup_cfg.get("open_wait_time", 0.5))
        if not _click_text(area, self._task_label, "任务名"):
            self._close_task_popup(gt)
            return False
        # 2) 弹出的确认窗口与任务弹窗同区域，点击"放弃"按钮
        if not _click_text(area, popup_cfg.get("abandon_keyword", "放弃"), "放弃按钮"):
            self._close_task_popup(gt)
            return False
        # 3) 关闭残留的任务弹窗
        self._close_task_popup(gt)
        return True

    def _close_task_popup(self, gt: float):
        """关闭任务弹窗：按 Escape（弹窗无 X 按钮）。"""
        self.dm.key_press_char("Escape")
        self._interruptible_wait(gt)

    # ── 路线清怪 ──────────────────────────────────────────

    def _clear_route(self) -> bool:
        """沿路线点推进，后台 OCR 实时检测"已完成"。

        中途检测到完成时，不再按路线依次走，立刻执行最后一个路线点（回 NPC 附近，
        不中断、走完整等待时间）以自动提交；路线正常走完则最后一点已执行，无需再走。
        """
        complete_text = self.combat.cfg.get("war3", {}).get("jiubing2", {}).get("atomic_task", {}).get("complete_text", "")
        if self.monitor is not None:
            complete_event = self.monitor.watch(complete_text)
        else:
            # 无持续监测器时回退到起停式后台监测线程
            interval = self.combat.cfg.get("war3", {}).get("jiubing2", {}).get("atomic_task", {}).get("monitor_interval", 0.2)
            complete_event = self.war3.start_text_watcher(
                self.combat.cfg.get("war3", {}).get("jiubing2", {}).get("prompt_text"), complete_text, interval=interval
            )
        # 组合事件：complete_event 或用户 stop_event 任一触发即中断行走
        combined_event = _CombinedEvent(complete_event, self._stop_event)
        points = self.cfg.get("points", [])
        gt = self.combat.war3_cfg["general_time"]

        try:
            # 沿路线推进，检测到完成即中断后续路线点
            for pt in points:
                if complete_event.is_set():
                    break
                # 定时清理英雄附近物品（在路线点之间执行）
                if self.nearby_cleaner is not None:
                    self.nearby_cleaner.tick()
                logger.info(f"走到：{pt.get('desc')}，预计 {pt.get('time', 5)}s")
                self.dm.key_press_char("F1")
                self._interruptible_wait(gt)
                try:
                    self.war3.move_to_minimap_point(
                        pt.get("mini_coords"),
                        pt.get("coords"),
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
                logger.info(f"任务完成，返回NPC附近提交：{last_pt.get('desc')}")
                self.dm.key_press_char("F1")
                self._interruptible_wait(gt)
                self.war3.move_to_minimap_point(
                    last_pt.get("mini_coords"),
                    last_pt.get("coords"),
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
