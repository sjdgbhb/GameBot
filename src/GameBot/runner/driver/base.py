"""大漠驱动基类 — 组合 Visual / Input / Window / Screenshot Mixin 的抽象基类。

架构说明：
- DmClientBase 继承四个 Mixin，承载全部业务可见 API（找图找色、键鼠、窗口、截图等），
  仅依赖抽象原语 _com_call(name, *args)（透传大漠 COM 方法调用）。
- Mixin 拆分：
  - visual.py    — VisualMixin：找图找色、截图、OCR
  - input.py     — InputMixin：键盘/鼠标/字符串输入
  - window.py    — WindowMixin：窗口绑定/查找/枚举/Win32 静态方法
  - screenshot.py — ScreenshotMixin：调试截图保存与频率控制
- 传输实现：
  - bridge.DmBridgeClient — 64 位主环境经 dm_bridge 子进程 RPC 调用大漠 COM
- 纯 Win32 操作（GetWindowRect 等）在本进程用 ctypes 直接调用。
"""

import abc
import ctypes

from GameBot.runner.driver.input import InputMixin
from GameBot.runner.driver.screenshot import ScreenshotMixin
from GameBot.runner.driver.visual import VisualMixin
from GameBot.runner.driver.window import WindowMixin

# 声明进程 DPI 感知，避免 Windows DPI 缩放导致大漠坐标与实际像素不一致
# （bridge 模式下 dm_bridge 子进程也会各自声明，保证两进程坐标体系一致）
try:
    ctypes.windll.shcore.SetProcessDpiAwareness(2)  # PER_MONITOR_AWARE
except OSError:
    try:
        ctypes.windll.user32.SetProcessDPIAware()
    except OSError:
        pass


class DmClientBase(abc.ABC, VisualMixin, InputMixin, WindowMixin, ScreenshotMixin):
    """大漠操作抽象基类（不捕获 COMError，让上层处理重试）。

    子类需实现抽象原语 _com_call(name, *args)：调用大漠 COM 同名方法并返回结果。
    """

    # ---------- 抽象原语 ----------

    @abc.abstractmethod
    def _com_call(self, name, *args):
        """调用大漠 COM 方法（子类实现：进程内 COM 或跨进程 RPC）。"""
        raise NotImplementedError

    def close(self):
        """释放底层资源（终止 dm_bridge 子进程）。"""

    @property
    def version(self):
        return self._com_call("Ver")
