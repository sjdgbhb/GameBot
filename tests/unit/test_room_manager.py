"""RoomManagerMixin start_game 测试。

覆盖：
- U-15: start_game 传入 room_hwnd 时跳过 dismiss_room_popups
"""

import sys
import unittest
from unittest.mock import MagicMock

import pytest

pytestmark = [pytest.mark.unit]

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


def _make_kk():
    """构造 RoomManagerMixin 实例，跳过 __init__。"""
    from GameBot.runner.business.kk.room_manager import RoomManagerMixin

    kk = RoomManagerMixin.__new__(RoomManagerMixin)
    kk.dm = MagicMock()
    kk.kk_cfg = {
        "window_class": "KKClass",
        "window_title": "KKTitle",
        "create_room_window_class": "CreateClass",
        "room": {
            "window_size": [1328, 945],
            "start_button_coords": [1100, 900],
            "start_button_ocr_area_coords": [800, 850, 1200, 930],
            "start_game_keyword": "开始游戏",
            "ready_keyword": "取消准备",
            "not_ready_keyword": "准备",
            "wait_ready_keyword": "等待准备",
            "start_wait_time": 0.1,
        },
        "popup": {
            "close_offset": [15, 15],
            "protected_keywords": ["输入房间密码", "创建房间"],
            "max_popup_area_ratio": 0.85,
        },
    }
    # bind_window 上下文管理器
    ctx = MagicMock()
    kk.dm.bind_window.return_value = ctx
    kk.dm.get_client_rect.return_value = (0, 0, 1328, 945)
    kk.dm.find_windows.return_value = []
    kk.ocr_kk_lines = MagicMock(return_value=[{"text": "开始游戏"}])
    return kk


class TestStartGame(unittest.TestCase):
    """start_game room_hwnd 参数测试。"""

    def setUp(self):
        self._orig = _mock_dm_modules()

    def tearDown(self):
        _restore_dm_modules(self._orig)

    # U-15: 传入 room_hwnd 时跳过 dismiss_room_popups
    def test_start_game_with_room_hwnd_skips_dismiss(self):
        """传入 room_hwnd 时不应调用 dismiss_room_popups。"""
        kk = _make_kk()
        kk.dismiss_room_popups = MagicMock()

        kk.start_game(kk.dm, room_hwnd=123)

        kk.dismiss_room_popups.assert_not_called()
        kk.dm.set_client_size.assert_called_once_with(123, 1328, 945)
        kk.dm.move_to.assert_called_once_with(1100, 900)
        kk.dm.left_click.assert_called_once()

    def test_start_game_uses_fixed_coordinates_with_client_size(self):
        kk = _make_kk()
        kk.dm.get_client_rect.return_value = (0, 0, 1200, 900)

        kk.start_game(kk.dm, room_hwnd=123)

        kk.dm.set_client_size.assert_called_once_with(123, 1328, 945)
        kk.dm.move_to.assert_called_once_with(1100, 900)
        kk.ocr_kk_lines.assert_called_once_with(
            kk.dm,
            123,
            {"area_coords": [800, 850, 1200, 930]},
        )

    # 未传入 room_hwnd 时调用 dismiss_room_popups
    def test_start_game_without_room_hwnd_calls_dismiss(self):
        """未传入 room_hwnd 时应调用 dismiss_room_popups 检测房间。"""
        kk = _make_kk()
        kk.dismiss_room_popups = MagicMock(return_value=123)

        kk.start_game(kk.dm)

        kk.dismiss_room_popups.assert_called_once()
        kk.dm.set_client_size.assert_called_once_with(123, 1328, 945)

    # dismiss_room_popups 返回 0 时截图并返回
    def test_start_game_no_room_captures(self):
        """dismiss_room_popups 返回 0 时应 save_screenshot(force=True) 并返回。"""
        kk = _make_kk()
        kk.dismiss_room_popups = MagicMock(return_value=0)

        kk.start_game(kk.dm)

        kk.dm.save_screenshot.assert_called_once_with(label="kk_room_not_found", force=True)
        kk.dm.set_client_size.assert_not_called()


class TestFindRoomWindow(unittest.TestCase):
    """_find_room_window PID 与状态 OCR 测试。"""

    def setUp(self):
        self._orig = _mock_dm_modules()

    def tearDown(self):
        _restore_dm_modules(self._orig)

    def test_owner_pid_and_ready_text_return_hwnd(self):
        kk = _make_kk()
        target_hwnd = 800
        kk.dm.find_windows.return_value = [
            {"hwnd": target_hwnd, "title": "KKTitle", "class": "KKClass", "rect": (0, 0, 1328, 945)}
        ]
        kk.ocr_kk_lines = MagicMock(return_value=[{"text": "取消准备"}])

        result = kk._find_room_window(kk.dm, owner_pid=5678)

        self.assertEqual(result, target_hwnd)
        kk.dm.set_client_size.assert_not_called()
        kk.ocr_kk_lines.assert_not_called()

    def test_owner_pid_mismatch_skips_window(self):
        """PID 不匹配时 find_windows 返回空列表，_find_room_window 返回 0。"""
        kk = _make_kk()
        # PID 不匹配时 find_windows 按 PID 过滤后返回空列表
        kk.dm.find_windows.return_value = []
        kk.ocr_kk_lines = MagicMock(return_value=[{"text": "取消准备"}])

        result = kk._find_room_window(kk.dm, owner_pid=5678)

        self.assertEqual(result, 0)
        kk.ocr_kk_lines.assert_not_called()
        # 验证 find_windows 被调用时传入了正确的 PID
        kk.dm.find_windows.assert_called_once_with("KKClass", "KKTitle", 5678)

    def test_tiny_candidates_are_skipped(self):
        kk = _make_kk()
        kk.dm.find_windows.return_value = [
            {"hwnd": 100, "title": "KKTitle", "class": "KKClass", "rect": (0, 0, 100, 100)},
            {"hwnd": 200, "title": "KKTitle", "class": "KKClass", "rect": (0, 0, 100, 100)},
        ]
        kk.dm.get_client_rect.return_value = (0, 0, 100, 100)
        kk.ocr_kk_lines = MagicMock(return_value=[{"text": "开始游戏"}])

        result = kk._find_room_window(kk.dm, owner_pid=0)

        self.assertEqual(result, 0)
        kk.ocr_kk_lines.assert_not_called()

    def test_non_room_size_is_rejected(self):
        kk = _make_kk()
        kk.dm.find_windows.return_value = [
            {"hwnd": 800, "title": "KKTitle", "class": "KKClass", "rect": (0, 0, 1000, 700)}
        ]
        kk.dm.get_client_rect.return_value = (0, 0, 1000, 700)

        result = kk._find_room_window(kk.dm, owner_pid=5678)

        self.assertEqual(result, 0)
        kk.ocr_kk_lines.assert_not_called()
