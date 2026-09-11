from __future__ import annotations

import os
import time
from abc import ABC
from typing import TYPE_CHECKING

from GameBot.inference import get_inference_client
from GameBot.utils.logger import logger

if TYPE_CHECKING:
    from GameBot.runner.driver.base import DmClientBase as DmClient


class Base(ABC):
    def __init__(self, dm: DmClient):
        self.dm = dm

    def sleep(self, seconds: float):
        """统一休眠，可在此处加入全局暂停检查逻辑"""
        time.sleep(seconds)

    def is_dm_valid(self) -> bool:
        """检查大漠对象是否可用（如 Ver 方法）"""
        return self.dm.version != ""

    @staticmethod
    def set_english_input(hwnd: int = 0):
        """将目标窗口的输入法临时切换为美式键盘，返回原布局供恢复。

        前台键盘模拟会经过系统输入队列，中文输入法会拦截字母键。
        :param hwnd: 目标窗口句柄，0 表示当前前台窗口
        :return: 原键盘布局句柄（HKL），失败时返回 None
        """
        import win32api
        import win32con
        import win32gui
        import win32process

        hwnd = hwnd or win32gui.GetForegroundWindow()
        if not hwnd:
            return None
        tid, _ = win32process.GetWindowThreadProcessId(hwnd)
        old_hkl = win32api.GetKeyboardLayout(tid)
        # '00000409' 是美式键盘的语言代码
        hkl = win32api.LoadKeyboardLayout("00000409", win32con.KLF_ACTIVATE)
        win32api.SendMessage(hwnd, win32con.WM_INPUTLANGCHANGEREQUEST, 0, hkl)
        return old_hkl

    @staticmethod
    def restore_input(hwnd: int, old_hkl):
        """恢复目标窗口原来的键盘布局。"""
        if not hwnd or not old_hkl:
            return
        import win32api
        import win32con

        win32api.SendMessage(hwnd, win32con.WM_INPUTLANGCHANGEREQUEST, 0, old_hkl)

    def ocr_lines(
        self, dm: DmClient, hwnd: int, ocr_cfg: dict, bind_cfg: dict = None, merge_lines: bool = True
    ) -> list:
        """大漠后台截图 → OCR 逐行识别，返回行列表。

        :param dm: DmClient 实例
        :param hwnd: 目标窗口句柄
        :param ocr_cfg: 含 area_coords [x1,y1,x2,y2]（客户区坐标）
        :param bind_cfg: 绑定配置；bind_window 幂等，已绑定同一窗口时自动复用
        :param merge_lines: False 时保持每个 OCR 框独立（网格布局）
        """
        x1, y1, x2, y2 = ocr_cfg["area_coords"]
        with dm.bind_window(hwnd, bind_cfg=bind_cfg or {}):
            img_path = dm.capture_to_temp(x1, y1, x2, y2, prefix="ocr")
        if not img_path:
            logger.warning(f"大漠截图失败: hwnd={hwnd}, area=[{x1},{y1},{x2},{y2}]")
            return []
        try:
            return get_inference_client(load_chest=False, load_combat=False).ocr_lines_from_file(
                img_path, merge_lines=merge_lines
            )
        finally:
            try:
                os.remove(img_path)
            except OSError:
                pass

    def ocr_text(self, dm: DmClient, hwnd: int, ocr_cfg: dict, bind_cfg: dict = None) -> str:
        """大漠后台截图 → OCR 识别，返回文本。"""
        x1, y1, x2, y2 = ocr_cfg["area_coords"]
        with dm.bind_window(hwnd, bind_cfg=bind_cfg or {}):
            img_path = dm.capture_to_temp(x1, y1, x2, y2, prefix="ocr")
        if not img_path:
            logger.warning(f"大漠截图失败: hwnd={hwnd}, area=[{x1},{y1},{x2},{y2}]")
            return ""
        try:
            return get_inference_client(load_chest=False, load_combat=False).ocr_from_file(img_path)
        finally:
            try:
                os.remove(img_path)
            except OSError:
                pass


class BasePlatform(Base):
    pass


class BaseGame(Base):
    pass
