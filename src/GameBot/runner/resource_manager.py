"""
统一管理图片、字体等资源路径，支持临时安装字体
"""

import ctypes
from pathlib import Path

from GameBot.config import config
from GameBot.utils.exception_handler import ResourceNotFoundError
from GameBot.utils.logger import logger


class ResourceManager:
    """资源文件（图片、字体）路径管理"""

    def __init__(self):
        self._resources_dir = None
        self._images_dir = None
        self._fonts_dir = None
        self._image_cache = {}

    def _ensure_initialized(self):
        if self._resources_dir is not None:
            return
        self._resources_dir = config.get_path("paths.resources_path")
        self._images_dir = self._resources_dir / "images"
        self._fonts_dir = self._resources_dir / "fonts"
        self._images_dir.mkdir(parents=True, exist_ok=True)
        self._fonts_dir.mkdir(parents=True, exist_ok=True)

    @property
    def resources_dir(self) -> Path:
        self._ensure_initialized()
        return self._resources_dir

    @property
    def images_dir(self) -> Path:
        self._ensure_initialized()
        return self._images_dir

    @property
    def fonts_dir(self) -> Path:
        self._ensure_initialized()
        return self._fonts_dir

    def get_image_path(self, filename: str) -> str:
        """获取图片文件的绝对路径（带缓存）"""
        cached = self._image_cache.get(filename)
        if cached is not None:
            return cached
        path = self.images_dir / filename
        if not path.exists():
            raise ResourceNotFoundError(f"图片文件不存在: {path}")
        result = str(path)
        self._image_cache[filename] = result
        return result

    def get_font_path(self, filename: str) -> str:
        """获取字体文件的绝对路径"""
        path = self.fonts_dir / filename
        if not path.exists():
            raise ResourceNotFoundError(f"字体文件不存在: {path}")
        return str(path)

    def install_font(self, filename: str, permanent: bool = False) -> str:
        """
        安装字体（临时或永久）
        :param filename: 字体文件名（如 'myfont.ttf'）
        :param permanent: True=永久安装（写入注册表），False=临时安装（仅当前会话）
        :return: 字体文件路径
        """
        font_path = self.get_font_path(filename)
        # 调用 Windows API 添加字体资源
        if permanent:
            # 永久安装需要管理员权限，此处不实现，仅临时安装
            logger.warning("永久安装字体需要管理员权限，当前仅临时安装")

        res = ctypes.windll.gdi32.AddFontResourceW(font_path)
        if res == 0:
            logger.error(f"安装字体失败: {filename}")
            raise RuntimeError(f"安装字体失败: {filename}")

        # 通知所有窗口字体已更改
        HWND_BROADCAST = 0xFFFF
        WM_FONTCHANGE = 0x001D
        ctypes.windll.user32.SendMessageW(HWND_BROADCAST, WM_FONTCHANGE, 0, 0)
        logger.info(f"临时安装字体成功: {filename}")
        return font_path

    def remove_temp_font(self, filename: str):
        """移除临时安装的字体（程序退出时调用）"""
        font_path = self.get_font_path(filename)
        ctypes.windll.gdi32.RemoveFontResourceW(font_path)
        ctypes.windll.user32.SendMessageW(0xFFFF, 0x001D, 0, 0)
        logger.info(f"移除临时字体: {filename}")


# 全局单例
res_mgr = ResourceManager()
