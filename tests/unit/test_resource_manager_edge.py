"""ResourceManager 边界测试 — 覆盖字体安装/移除的 Windows API 分支。"""

import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from GameBot.utils.exception_handler import ResourceNotFoundError

pytestmark = [pytest.mark.unit]


# Mock Windows COM 依赖
_DM_MODULES = (
    "win32com",
    "win32com.client",
    "pythoncom",
    "pywintypes",
    "winreg",
    "win32gui",
    "win32con",
    "win32api",
)


def _mock_dm_modules():
    originals = {name: sys.modules.get(name) for name in _DM_MODULES}
    for name in _DM_MODULES:
        sys.modules[name] = MagicMock()
    return originals


def _restore_dm_modules(originals):
    for name, mod in originals.items():
        if mod is None:
            sys.modules.pop(name, None)
        else:
            sys.modules[name] = mod


class TestResourceManagerFontEdge(unittest.TestCase):
    """ResourceManager 字体安装/移除边界测试。"""

    def setUp(self):
        self._orig = _mock_dm_modules()

    def tearDown(self):
        _restore_dm_modules(self._orig)

    def _make_mgr(self, tmp_path):
        """创建一个 ResourceManager 实例，mock config.get_path 返回 tmp_path。"""
        from GameBot.runner.resource_manager import ResourceManager

        mgr = ResourceManager()
        with patch("GameBot.runner.resource_manager.config") as mock_config:
            mock_config.get_path.return_value = tmp_path
            mgr._ensure_initialized()
        return mgr

    @patch("GameBot.runner.resource_manager.ctypes")
    def test_install_temp_font_success(self, mock_ctypes):
        """临时安装字体成功时应发送字体变更广播并返回路径。"""
        import shutil

        tmp = Path(tempfile.mkdtemp())
        try:
            mgr = self._make_mgr(tmp)
            font_file = tmp / "fonts" / "test.ttf"
            font_file.write_text("fake")

            mock_ctypes.windll.gdi32.AddFontResourceW.return_value = 1

            result = mgr.install_font("test.ttf", permanent=False)

            self.assertEqual(result, str(font_file))
            mock_ctypes.windll.gdi32.AddFontResourceW.assert_called_once_with(str(font_file))
            mock_ctypes.windll.user32.SendMessageW.assert_called_once()
            call_args = mock_ctypes.windll.user32.SendMessageW.call_args[0]
            self.assertEqual(call_args[0], 0xFFFF)
            self.assertEqual(call_args[1], 0x001D)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    @patch("GameBot.runner.resource_manager.ctypes")
    def test_install_font_permanent_warns_and_falls_back(self, mock_ctypes):
        """permanent=True 时应记录警告并仍然执行临时安装。"""
        import shutil

        tmp = Path(tempfile.mkdtemp())
        try:
            mgr = self._make_mgr(tmp)
            font_file = tmp / "fonts" / "test.ttf"
            font_file.write_text("fake")

            mock_ctypes.windll.gdi32.AddFontResourceW.return_value = 1

            with patch("GameBot.runner.resource_manager.logger") as mock_logger:
                result = mgr.install_font("test.ttf", permanent=True)

            self.assertEqual(result, str(font_file))
            mock_logger.warning.assert_called_once()
            self.assertIn("管理员权限", mock_logger.warning.call_args[0][0])
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    @patch("GameBot.runner.resource_manager.ctypes")
    def test_install_font_failure_raises(self, mock_ctypes):
        """AddFontResourceW 返回 0 时应抛出 RuntimeError。"""
        import shutil

        tmp = Path(tempfile.mkdtemp())
        try:
            mgr = self._make_mgr(tmp)
            font_file = tmp / "fonts" / "test.ttf"
            font_file.write_text("fake")

            mock_ctypes.windll.gdi32.AddFontResourceW.return_value = 0

            with self.assertRaises(RuntimeError) as ctx:
                mgr.install_font("test.ttf")

            self.assertIn("安装字体失败", str(ctx.exception))
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_install_font_not_found(self):
        """字体文件不存在时应抛出 ResourceNotFoundError。"""
        import shutil

        tmp = Path(tempfile.mkdtemp())
        try:
            mgr = self._make_mgr(tmp)
            with self.assertRaises(ResourceNotFoundError):
                mgr.install_font("nonexistent.ttf")
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    @patch("GameBot.runner.resource_manager.ctypes")
    def test_remove_temp_font_calls_windows_api(self, mock_ctypes):
        """移除临时字体时应调用 RemoveFontResourceW 并广播。"""
        import shutil

        tmp = Path(tempfile.mkdtemp())
        try:
            mgr = self._make_mgr(tmp)
            font_file = tmp / "fonts" / "test.ttf"
            font_file.write_text("fake")

            mgr.remove_temp_font("test.ttf")

            mock_ctypes.windll.gdi32.RemoveFontResourceW.assert_called_once_with(str(font_file))
            mock_ctypes.windll.user32.SendMessageW.assert_called_once()
            call_args = mock_ctypes.windll.user32.SendMessageW.call_args[0]
            self.assertEqual(call_args[0], 0xFFFF)
            self.assertEqual(call_args[1], 0x001D)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
