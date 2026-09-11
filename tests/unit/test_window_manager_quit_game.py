"""WindowManagerMixin quit_game 与 identify_war3_owner 测试。

覆盖：
- U-06: quit_game 在已绑定上下文内发送 F10/E/Q
- U-07: quit_game 检测结算页面，出现时按回车，未出现时不按回车
- identify_war3_owner: OCR 识别玩家用户名
"""

import sys
import unittest
from unittest.mock import MagicMock, patch

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


def _make_war3():
    """构造 War3Business 实例（通过 mixin 组合），跳过 __init__。"""
    from GameBot.runner.business.base import Base
    from GameBot.runner.business.war3.window_manager import WindowManagerMixin

    class FakeWar3(Base, WindowManagerMixin):
        pass

    war3 = FakeWar3.__new__(FakeWar3)
    war3.dm = MagicMock()
    war3.war3_cfg = {
        "window_class": "War3Class",
        "window_title": "War3Title",
        "small_window_response_time": 0.1,
        "quit_war3_time": 0.5,
        "end_statistics_area_coords": [0, 0, 100, 100],
        "end_statistics_img": "end.bmp",
        "end_statistics_sim": 0.8,
        "end_statistics_delta_color": "202020",
        "mini_map_signal_area_coords": [0, 0, 50, 50],
        "mini_map_signal_img": "signal.bmp",
        "mini_map_signal_sim": 0.7,
        "mini_map_signal_delta_color": "202020",
    }
    return war3


class TestQuitGame(unittest.TestCase):
    """quit_game 按键发送与结算页面测试。"""

    def setUp(self):
        self._orig = _mock_dm_modules()

    def tearDown(self):
        _restore_dm_modules(self._orig)

    # U-06: quit_game 发送 F10/E/Q
    def test_quit_game_sends_keys(self):
        """quit_game() 应发送 F10/E/Q 按键。"""
        war3 = _make_war3()
        war3.dm.find_pic.return_value = (-1, 0, 0)  # 无结算页面

        war3.quit_game()

        expected_calls = [
            unittest.mock.call("F10"),
            unittest.mock.call("E"),
            unittest.mock.call("Q"),
        ]
        self.assertEqual(war3.dm.key_press_char.call_args_list, expected_calls)
        # 无结算页面时不按回车
        self.assertNotIn(unittest.mock.call("enter"), war3.dm.key_press_char.call_args_list)

    # 结尾统计画面出现时按回车
    def test_quit_game_end_statistics_presses_enter(self):
        """出现结尾统计画面时应按回车确认。"""
        war3 = _make_war3()
        war3.dm.find_pic.return_value = (0, 50, 50)  # 找到结算图片

        war3.quit_game()

        # 最后应调用 key_press_char("enter")
        self.assertIn(unittest.mock.call("enter"), war3.dm.key_press_char.call_args_list)

    # 无结算页面时不按回车
    def test_quit_game_no_end_statistics_no_enter(self):
        """未出现结算页面时不应按回车。"""
        war3 = _make_war3()
        war3.dm.find_pic.return_value = (-1, 0, 0)  # 未找到结算图片

        war3.quit_game()

        self.assertNotIn(unittest.mock.call("enter"), war3.dm.key_press_char.call_args_list)


class TestIdentifyWar3Owner(unittest.TestCase):
    """identify_war3_owner OCR 识别测试。"""

    def setUp(self):
        self._orig = _mock_dm_modules()

    def tearDown(self):
        _restore_dm_modules(self._orig)

    def _make_war3(self):
        war3 = _make_war3()
        war3.war3_cfg["multi_instance"] = {
            "loading_page": {
                "area_coords": [400, 200, 1200, 600],
            }
        }
        return war3

    @patch("os.remove")
    @patch("GameBot.runner.business.base.get_inference_client")
    def test_identify_war3_owner_returns_first_player(self, mock_ocr_client, _):
        """应返回 OCR 识别的第一个非空行文本。"""
        war3 = self._make_war3()
        war3.dm.capture_to_temp.return_value = "/tmp/test_ocr.bmp"
        war3.dm.bind_window.return_value.__enter__ = MagicMock(return_value=None)
        war3.dm.bind_window.return_value.__exit__ = MagicMock(return_value=False)
        mock_ocr_client.return_value.ocr_lines_from_file.return_value = [
            {"text": "Player1", "y_center": 100, "x_center": 500},
            {"text": "Player2", "y_center": 200, "x_center": 500},
        ]

        result = war3.identify_war3_owner(123)

        self.assertEqual(result, "Player1")

    @patch("os.remove")
    @patch("GameBot.runner.business.base.get_inference_client")
    def test_identify_war3_owner_empty_lines_returns_empty(self, mock_ocr_client, _):
        """OCR 结果全为空时应返回空字符串。"""
        war3 = self._make_war3()
        war3.dm.capture_to_temp.return_value = "/tmp/test_ocr.bmp"
        war3.dm.bind_window.return_value.__enter__ = MagicMock(return_value=None)
        war3.dm.bind_window.return_value.__exit__ = MagicMock(return_value=False)
        mock_ocr_client.return_value.ocr_lines_from_file.return_value = [
            {"text": "", "y_center": 100},
            {"text": "   ", "y_center": 200},
        ]

        result = war3.identify_war3_owner(123)

        self.assertEqual(result, "")

    @patch("os.remove")
    @patch("GameBot.runner.business.base.get_inference_client")
    def test_identify_war3_owner_no_lines_returns_empty(self, mock_ocr_client, _):
        """OCR 无结果时应返回空字符串。"""
        war3 = self._make_war3()
        war3.dm.capture_to_temp.return_value = "/tmp/test_ocr.bmp"
        war3.dm.bind_window.return_value.__enter__ = MagicMock(return_value=None)
        war3.dm.bind_window.return_value.__exit__ = MagicMock(return_value=False)
        mock_ocr_client.return_value.ocr_lines_from_file.return_value = []

        result = war3.identify_war3_owner(123)

        self.assertEqual(result, "")
