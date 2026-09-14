"""截图操作 Mixin — 调试截图保存与频率控制（统一走 WGC）。

截图目标：已绑定窗口（`_current_bind_hwnd`）优先；未绑定时退到当前前台窗口。
所有截图均为 WGC 取帧，不再走大漠 Capture 或 PrintWindow。
"""

import datetime
import time
from pathlib import Path
from typing import Optional, Tuple

from GameBot.config import config
from GameBot.runner.driver.wgc_capture import WgcCapture
from GameBot.utils.exception_handler import CaptureError
from GameBot.utils.logger import logger


class ScreenshotMixin:
    """调试截图相关操作：保存截图、活动窗口截图、频率控制。

    依赖子类提供 `_current_bind_hwnd`（WindowMixin 提供）、
    `get_foreground_window`（WindowMixin 提供）。
    """

    # 调试截图默认配置
    _screenshot_min_interval: float = 1.0  # 秒，避免循环中重复截图
    _last_screenshot_time: float = 0.0

    def _screenshot_dir(self) -> Path:
        """调试截图输出目录，从配置读取，默认 logs/screenshots。"""
        path = config.get_path("paths.screenshot_path", "logs/screenshots")
        if not path or path == config.project_root:
            path = config.project_root / "logs" / "screenshots"
        path.mkdir(parents=True, exist_ok=True)
        return path

    def save_screenshot(
        self, bbox: Optional[Tuple[int, int, int, int]] = None, label: str = "debug", force: bool = False
    ) -> Optional[Path]:
        """截取目标窗口客户区并保存到日志目录，返回文件路径或 None。

        带最小间隔限制，避免循环中重复截图。force=True 时绕过频率限制。

        :param bbox: 客户区坐标 (left, top, right, bottom)；为 None 时截取整个客户区
        :param label: 文件名前缀，便于识别截图场景
        :param force: True 时跳过频率限制，用于异常/超时等必须截图的场景
        """
        cls = type(self)
        now = time.time()
        if not force and now - cls._last_screenshot_time < cls._screenshot_min_interval:
            return None
        cls._last_screenshot_time = now

        hwnd = (
            getattr(self, "_current_bind_hwnd", 0)
            or getattr(self, "_last_bind_hwnd", 0)
            or self.get_foreground_window()
        )
        if not hwnd:
            logger.warning("无可截图窗口（未绑定、无历史绑定且无前台窗口）")
            return None
        try:
            cap = WgcCapture.for_hwnd(hwnd)
            if bbox is None:
                cw, ch = cap.client_size()
                bbox = (0, 0, cw, ch)
            path = self._screenshot_dir() / f"{label}_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S_%f')}.png"
            cap.save(str(path), bbox)
            logger.info(f"已保存截图: {path}")
            return path
        except (CaptureError, OSError) as e:
            logger.warning(f"截图失败: {e}")
            return None

    def save_active_window_screenshot(self, label: str = "active_window") -> Optional[Path]:
        """截取当前活动（前台）窗口并保存。"""
        hwnd = self.get_foreground_window()
        if not hwnd:
            logger.warning("无前台窗口，无法截取活动窗口")
            return None
        try:
            cap = WgcCapture.for_hwnd(hwnd)
            path = self._screenshot_dir() / f"{label}_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S_%f')}.png"
            cap.save(str(path))
            logger.info(f"已保存活动窗口截图: {path}")
            return path
        except (CaptureError, OSError) as e:
            logger.warning(f"截取活动窗口失败: {e}")
            return None
