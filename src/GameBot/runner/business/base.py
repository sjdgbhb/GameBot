from __future__ import annotations

from abc import ABC, abstractmethod
import time
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from GameBot.runner.dm_client import DmClient


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
    def set_english_input():
        """将当前活动窗口的输入法切换为美式键盘"""
        import win32api
        import win32con
        import win32gui
        hwnd = win32gui.GetForegroundWindow()
        # '00000409' 是美式键盘的语言代码
        hkl = win32api.LoadKeyboardLayout('00000409', win32con.KLF_ACTIVATE)
        win32api.SendMessage(hwnd, win32con.WM_INPUTLANGCHANGEREQUEST, 0, hkl)
        return hwnd


class BasePlatform(Base):
    pass


class BaseGame(Base):
    pass