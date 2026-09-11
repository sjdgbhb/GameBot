"""KK 多开识别 mixin — 大厅玩家 ID 识别、父子窗口辅助验证。

多开下只需在主界面（大厅）OCR 一次玩家名建立归属；
房间、弹窗等其它窗口通过 PID + 尺寸/类名区分，不再 OCR 玩家名。
"""

from __future__ import annotations

import ctypes
import time
from contextlib import contextmanager
from ctypes import wintypes
from typing import TYPE_CHECKING, Optional

from GameBot.utils import StopTaskError, logger

if TYPE_CHECKING:
    from GameBot.runner.driver.base import DmClientBase as DmClient


class MultiInstanceMixin:
    """KK 多开识别 mixin。依赖 self.kk_cfg（dict）。"""

    @contextmanager
    def _pid_identify_lock(self, pid: int, stop_event=None):
        """按 KK 进程 PID 串行化玩家 ID 下拉框操作。"""
        kernel32 = ctypes.windll.kernel32
        kernel32.CreateMutexW.restype = wintypes.HANDLE
        kernel32.CreateMutexW.argtypes = [
            ctypes.c_void_p,
            wintypes.BOOL,
            wintypes.LPCWSTR,
        ]
        kernel32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
        kernel32.ReleaseMutex.argtypes = [wintypes.HANDLE]
        kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
        mutex_name = f"Local\\GameBot_KK_Hall_Identify_PID_{int(pid)}"
        handle = kernel32.CreateMutexW(None, False, mutex_name)
        if not handle:
            raise OSError("创建 KK 大厅 PID 识别互斥锁失败")
        if stop_event and stop_event.is_set():
            kernel32.CloseHandle(handle)
            raise StopTaskError("停止 KK 大厅玩家 ID 识别")
        result = kernel32.WaitForSingleObject(handle, 0)
        if result == 0x102:
            kernel32.CloseHandle(handle)
            yield False
            return
        if result not in (0, 0x80):
            kernel32.CloseHandle(handle)
            raise OSError(f"获取 KK 大厅 PID 识别互斥锁失败: {result}")
        try:
            yield True
        finally:
            kernel32.ReleaseMutex(handle)
            kernel32.CloseHandle(handle)

    def identify_hall_owner(
        self,
        dm: DmClient,
        hall_hwnd: int,
        stop_event=None,
        hall_owner_cache=None,
    ) -> Optional[str]:
        """通过点击头像弹出下拉框，对下拉框窗口 OCR 识别 KK 主界面窗口的玩家 ID。

        流程：记录点击前下拉框快照 → 绑定大厅 → 点击头像 → 解绑大厅 →
              找点击后新出现的下拉框（优先父/属主窗口为当前大厅的）→
              绑定下拉框 OCR → ESC 关闭。

        多开下若多个 KK 大厅属于同一 PID，旧实现直接取 Z 序最上层的下拉框，
        会误读其他大厅弹出的下拉框。此处通过"before/after 差分"配合
        父窗口校验，确保只读取本次点击所属于 hall_hwnd 的下拉框。

        同一 KK PID 使用互斥锁串行操作，不同 PID 可并行识别。

        :param hall_hwnd: 主界面窗口句柄
        :return: 玩家 ID；OCR 为空返回空字符串，窗口正忙（互斥锁冲突）返回 None
        """
        main_cfg = self.kk_cfg.get("main", {})
        main_size = tuple(main_cfg.get("window_size", [1328, 945]))
        dropdown_wait = main_cfg.get("dropdown_wait_time", 1)
        # 下拉框完整类名从 [kk] 配置读取
        dropdown_class = self.kk_cfg.get("dropdown_window_class", "")
        window_title = self.kk_cfg.get("window_title", "")
        pid = dm.get_window_process_id(hall_hwnd)

        with self._pid_identify_lock(pid, stop_event=stop_event) as acquired:
            if not acquired:
                return None
            if stop_event and stop_event.is_set():
                raise StopTaskError("停止 KK 大厅玩家 ID 识别")
            if hall_owner_cache:
                cached_owner = hall_owner_cache.read_hall_owner(hall_hwnd, pid)
                if cached_owner:
                    logger.info(f"大厅归属共享缓存命中: hwnd={hall_hwnd}, pid={pid}, owner={cached_owner}")
                    return cached_owner

            # 点击前先记录已有下拉框，避免把其他大厅残留/其他进程刚弹出的框当成本次结果
            before_candidates = dm.find_windows(dropdown_class, window_title, pid)
            before_hwnds = {w["hwnd"] for w in before_candidates}

            # 绑定大厅窗口，点击头像展开下拉框
            dm.set_client_size(hall_hwnd, *main_size)
            with dm.bind_window(hall_hwnd, bind_cfg=self.kk_cfg.get("bind", {})):
                dm.move_to(*main_cfg["profile_icon_coords"])
                if stop_event:
                    if stop_event.wait(0.3):
                        raise StopTaskError("停止 KK 大厅玩家 ID 识别")
                else:
                    time.sleep(0.3)
                dm.left_click()
                if stop_event and stop_event.wait(dropdown_wait):
                    dm.key_press_char("esc")
                    raise StopTaskError("停止 KK 大厅玩家 ID 识别")
                if not stop_event:
                    time.sleep(dropdown_wait)

            # 大厅已解绑，按 PID + 完整类名 + 标题 + 父/属主窗口找本次点击产生的下拉框
            dropdown = None
            after_candidates = dm.find_windows(dropdown_class, window_title, pid)
            new_candidates = [w for w in after_candidates if w["hwnd"] not in before_hwnds]

            if new_candidates:
                # 在新弹出的下拉框中，优先父/属主窗口是当前大厅的
                for w in new_candidates:
                    if dm.get_window_parent(w["hwnd"]) == hall_hwnd:
                        dropdown = w
                        break
                if dropdown is None:
                    # 没有命中父/属主窗口，按 Z 序取第一个新弹出的下拉框兜底
                    dropdown = new_candidates[0]
            else:
                # 未观察到新下拉框（可能与点击前已有），兜底：优先父/属主是当前大厅的
                for w in after_candidates:
                    if dm.get_window_parent(w["hwnd"]) == hall_hwnd:
                        dropdown = w
                        break
                if dropdown is None and after_candidates:
                    dropdown = after_candidates[0]

            if not dropdown:
                logger.warning(f"KK 主界面窗口 {hall_hwnd} 点击头像后未检测到下拉框窗口")
                with dm.bind_window(hall_hwnd, bind_cfg=self.kk_cfg.get("bind", {})):
                    dm.key_press_char("esc")
                return ""

            dd_hwnd = dropdown["hwnd"]
            # 优先用 get_client_rect 获取尺寸（find_windows 的 rect 来自 get_window_rect，
            # 在 bridge 模式下可能返回 0）
            try:
                dd_cr = dm.get_client_rect(dd_hwnd)
                dd_w = dd_cr[2] - dd_cr[0]
                dd_h = dd_cr[3] - dd_cr[1]
            except Exception:
                dd_rect = dropdown["rect"]
                dd_w = dd_rect[2] - dd_rect[0]
                dd_h = dd_rect[3] - dd_rect[1]

            # 若配置了基准尺寸，先统一下拉框客户区尺寸
            dropdown_cfg = self.kk_cfg.get("dropdown", {})
            dropdown_size = dropdown_cfg.get("window_size")
            if dropdown_size and len(dropdown_size) >= 2 and dropdown_size[0] > 0 and dropdown_size[1] > 0:
                try:
                    dm.set_client_size(dd_hwnd, *dropdown_size)
                    logger.info(f"下拉框已统一尺寸: {dropdown_size}")
                    x1, y1, x2, y2 = dm.get_client_rect(dd_hwnd)
                    dd_w, dd_h = x2 - x1, y2 - y1
                except Exception as e:
                    logger.warning(f"设置下拉框尺寸失败: {e}")

            logger.debug(f"大厅下拉框定位: hall_hwnd={hall_hwnd}, dropdown_hwnd={dd_hwnd}, size=({dd_w}x{dd_h})")

            # 绑定下拉框窗口做 OCR，OCR 完成后在同一上下文内 ESC 关闭
            owner = ""
            with dm.bind_window(dd_hwnd, bind_cfg=self.kk_cfg.get("bind", {})):
                lines = self.ocr_lines(
                    dm,
                    dd_hwnd,
                    {"area_coords": [0, 0, dd_w, dd_h]},
                )
                for line in lines:
                    text = line.get("text", "").strip()
                    if text:
                        owner = text
                        break
                if not owner:
                    all_texts = [ln.get("text", "").strip() for ln in lines if ln.get("text", "").strip()]
                    logger.warning(f"下拉框窗口 {dd_hwnd} OCR 为空，所有文本: {all_texts}")
                dm.key_press_char("esc")

            if owner:
                if hall_owner_cache:
                    hall_owner_cache.write_hall_owner(hall_hwnd, pid, owner)
                logger.info(f"大厅归属 OCR: hwnd={hall_hwnd}, pid={pid}, owner={owner}")
            return owner

    def check_parent_child_relation(self, dm: DmClient, hwnd: int) -> int:
        """检查窗口的父窗口句柄（辅助多开识别）。

        :return: 父窗口句柄，无父窗口返回 0
        """
        parent = dm.get_window_parent(hwnd)
        if parent:
            logger.debug(f"窗口 {hwnd} 的父窗口为 {parent}")
        else:
            logger.debug(f"窗口 {hwnd} 无父窗口（顶层窗口）")
        return parent
