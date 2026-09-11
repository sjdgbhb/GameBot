"""截图操作 Mixin — 调试截图保存与频率控制（基于 _com_call 原语组合）。
"""

import datetime
import time
from pathlib import Path
from typing import Optional, Tuple

from GameBot.config import config
from GameBot.utils.logger import logger


class ScreenshotMixin:
    """调试截图相关操作：保存截图、活动窗口截图、频率控制。

    依赖子类提供 `capture_region`（VisualMixin 提供）。
    另依赖 `get_foreground_window`/`get_window_rect`/`get_screen_rect`（WindowMixin 提供）。
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

    def save_screenshot(self, bbox: Optional[Tuple[int, int, int, int]] = None, label: str = "debug", force: bool = False) -> Optional[Path]:
        """截取指定屏幕区域并保存到日志目录，返回文件路径或 None。

        带最小间隔限制，避免循环中重复截图。force=True 时绕过频率限制。

        :param bbox: 屏幕坐标 (left, top, right, bottom)，为 None 时截取整个屏幕
        :param label: 文件名前缀，便于识别截图场景
        :param force: True 时跳过频率限制，用于异常/超时等必须截图的场景
        """
        cls = type(self)
        now = time.time()
        if not force and now - cls._last_screenshot_time < cls._screenshot_min_interval:
            return None
        cls._last_screenshot_time = now

        if bbox is None:
            bbox = self.get_screen_rect()
        x1, y1, x2, y2 = bbox
        if x2 <= x1 or y2 <= y1:
            logger.warning(f"截图区域无效: {bbox}")
            return None

        screenshot_dir = self._screenshot_dir()
        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        filename = f"{label}_{timestamp}.bmp"
        filepath = screenshot_dir / filename
        try:
            if self.capture_region(x1, y1, x2, y2, str(filepath)):
                logger.info(f"已保存截图: {filepath}")
                return filepath
            logger.warning(f"截图失败，大漠 Capture 返回非 1: {filepath}")
        except Exception as e:
            logger.warning(f"截图异常: {e}")
        return None

    def save_active_window_screenshot(self, label: str = "active_window") -> Optional[Path]:
        """截取当前活动（前台）窗口并保存。"""
        hwnd = self.get_foreground_window()
        if hwnd:
            try:
                bbox = self.get_window_rect(hwnd)
                return self.save_screenshot(bbox, label)
            except Exception as e:
                logger.warning(f"截取活动窗口失败: {e}")
        # 无法获取句柄时截全屏
        return self.save_screenshot(label=label)
