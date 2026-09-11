"""War3 Bot 弹窗与异常截图改进 — 边界测试。

覆盖 2026-08-13 开发变更日志中的关键新增行为：
- DmClientBase 截图、活动窗口截图、右上角 X 关闭
- KKBusiness 弹窗清理、开始游戏
- WindowManagerMixin 等待窗口超时/掉线截图
- AtomicLoopTask 弹窗关闭（右上角 X 模式）
- EndlessTask do_kk
"""

import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

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


# 测试用 DmClientBase 子类：_com_call 委托给 self._com（MagicMock），不启动子进程。
from GameBot.runner.driver.base import DmClientBase


class _TestDmClient(DmClientBase):
    """测试用驱动实例，跳过 __init__，_com_call 委托给 self._com。"""

    def _com_call(self, name, *args):
        return getattr(self._com, name)(*args)


def _make_dm_client():
    """通过 __new__ 构造 _TestDmClient 实例，跳过 __init__ 并手动设置 _com。"""
    dm = _TestDmClient.__new__(_TestDmClient)
    dm._com = MagicMock()
    return dm


class TestDmClientScreenshot(unittest.TestCase):
    """DmClientBase 截图相关方法边界测试。"""

    def setUp(self):
        self._orig = _mock_dm_modules()
        _TestDmClient._last_screenshot_time = 0

    def tearDown(self):
        _restore_dm_modules(self._orig)
        _TestDmClient._last_screenshot_time = 0

    @patch.object(_TestDmClient, "_screenshot_dir")
    def test_save_screenshot_success(self, mock_dir):
        """正常截图应返回文件路径。"""
        tmp = Path(__file__).parent
        mock_dir.return_value = tmp
        dm = _make_dm_client()
        dm._com.Capture.return_value = 1

        with patch("GameBot.runner.driver.screenshot.time") as mock_time:
            mock_time.time.return_value = 1000
            result = dm.save_screenshot((0, 0, 100, 100), label="test")

        self.assertIsNotNone(result)
        self.assertIn("test_", result.name)
        self.assertTrue(str(result).endswith(".bmp"))

    @patch.object(_TestDmClient, "_screenshot_dir")
    def test_save_screenshot_min_interval(self, mock_dir):
        """两次截图间隔小于最小间隔时，第二次应返回 None。"""
        tmp = Path(__file__).parent
        mock_dir.return_value = tmp
        dm = _make_dm_client()
        dm._com.Capture.return_value = 1

        with patch("GameBot.runner.driver.screenshot.time") as mock_time:
            mock_time.time.side_effect = [1000, 1000.5]
            result1 = dm.save_screenshot(label="test")
            result2 = dm.save_screenshot(label="test2")

        self.assertIsNotNone(result1)
        self.assertIsNone(result2)

    @patch.object(_TestDmClient, "_screenshot_dir")
    def test_save_screenshot_invalid_bbox(self, mock_dir):
        """无效截图区域应返回 None。"""
        tmp = Path(__file__).parent
        mock_dir.return_value = tmp
        dm = _make_dm_client()

        result = dm.save_screenshot((100, 100, 50, 50), label="test")

        self.assertIsNone(result)
        dm._com.Capture.assert_not_called()

    @patch.object(_TestDmClient, "_screenshot_dir")
    def test_save_screenshot_capture_failed(self, mock_dir):
        """大漠 Capture 返回非 1 时应返回 None。"""
        tmp = Path(__file__).parent
        mock_dir.return_value = tmp
        dm = _make_dm_client()
        dm._com.Capture.return_value = 0

        with patch("GameBot.runner.driver.screenshot.time") as mock_time:
            mock_time.time.return_value = 1000
            result = dm.save_screenshot((0, 0, 100, 100), label="test")

        self.assertIsNone(result)

    @patch.object(_TestDmClient, "get_foreground_window")
    @patch.object(_TestDmClient, "get_window_rect")
    @patch.object(_TestDmClient, "save_screenshot")
    def test_save_active_window_screenshot(self, mock_save, mock_rect, mock_fg):
        """有前台窗口时应按窗口矩形截图。"""
        dm = _make_dm_client()
        mock_fg.return_value = 123
        mock_rect.return_value = (10, 10, 110, 110)
        mock_save.return_value = Path("/tmp/active.bmp")

        result = dm.save_active_window_screenshot(label="active")

        self.assertEqual(result, Path("/tmp/active.bmp"))
        mock_rect.assert_called_once_with(123)
        mock_save.assert_called_once_with((10, 10, 110, 110), "active")

    @patch.object(_TestDmClient, "get_foreground_window")
    @patch.object(_TestDmClient, "save_screenshot")
    def test_save_active_window_screenshot_no_hwnd(self, mock_save, mock_fg):
        """无前台窗口时应回退到全屏截图。"""
        dm = _make_dm_client()
        mock_fg.return_value = 0
        mock_save.return_value = Path("/tmp/fullscreen.bmp")

        result = dm.save_active_window_screenshot(label="no_window")

        self.assertEqual(result, Path("/tmp/fullscreen.bmp"))
        mock_save.assert_called_once_with(label="no_window")


class TestDmClientNewMethods(unittest.TestCase):
    """DmClientBase 新增方法测试：send_string2 / get_bind_window / get_window_parent / save_screenshot force。"""

    def setUp(self):
        self._orig = _mock_dm_modules()
        _TestDmClient._last_screenshot_time = 0

    def tearDown(self):
        _restore_dm_modules(self._orig)
        _TestDmClient._last_screenshot_time = 0

    def test_send_string_with_hwnd_calls_com_send_string(self):
        dm = _make_dm_client()
        dm.get_foreground_window = MagicMock(return_value=999)

        dm.send_string("九种兵器2", hwnd=123)

        dm._com.SendString.assert_called_once_with(123, "九种兵器2")
        dm.get_foreground_window.assert_not_called()

    # U-02: send_string2 默认使用前台窗口
    def test_send_string2_calls_com_send_string2(self):
        """send_string2(text) 应调用 _com.SendString2(前台窗口, text)。"""
        dm = _make_dm_client()
        dm.get_foreground_window = MagicMock(return_value=999)

        dm.send_string2("九种兵器2")

        dm._com.SendString2.assert_called_once_with(999, "九种兵器2")

    # U-02a: send_string2 显式传入 hwnd
    def test_send_string2_with_hwnd(self):
        """send_string2(text, hwnd=123) 应调用 _com.SendString2(123, text)，不使用 get_foreground_window。"""
        dm = _make_dm_client()
        dm.get_foreground_window = MagicMock(return_value=999)

        dm.send_string2("九种兵器2", hwnd=123)

        dm._com.SendString2.assert_called_once_with(123, "九种兵器2")
        dm.get_foreground_window.assert_not_called()

    # U-22: get_bind_window 返回内部跟踪的绑定句柄
    def test_get_bind_window_returns_com_value(self):
        """get_bind_window 应返回 bind_window 上下文内跟踪的 _current_bind_hwnd。"""
        dm = _make_dm_client()
        dm._current_bind_hwnd = 456

        result = dm.get_bind_window()

        self.assertEqual(result, 456)

    # U-22: get_bind_window 未绑定时返回 0
    def test_get_bind_window_returns_zero_when_unbound(self):
        """未绑定窗口时 get_bind_window 应返回 0。"""
        dm = _make_dm_client()

        result = dm.get_bind_window()

        self.assertEqual(result, 0)

    # U-03: get_window_parent 调用大漠 GetWindow
    def test_get_window_parent(self):
        """get_window_parent 应调用大漠 GetWindow(flag=0) 并返回结果。"""
        dm = _make_dm_client()
        dm._com.GetWindow.return_value = 789

        result = dm.get_window_parent(123)

        self.assertEqual(result, 789)
        dm._com.GetWindow.assert_called_once_with(123, 0)

    # U-03: get_window_parent 无父窗口返回 0
    def test_get_window_parent_no_parent(self):
        """无父窗口时 get_window_parent 应返回 0。"""
        dm = _make_dm_client()
        dm._com.GetWindow.return_value = 0

        result = dm.get_window_parent(456)

        self.assertEqual(result, 0)

    # U-01: save_screenshot force=True 绕过频率限制
    @patch.object(_TestDmClient, "_screenshot_dir")
    def test_save_screenshot_force_bypasses_min_interval(self, mock_dir):
        """force=True 时间隔小于 1 秒仍应截图。"""
        tmp = Path(__file__).parent
        mock_dir.return_value = tmp
        dm = _make_dm_client()
        dm._com.Capture.return_value = 1

        with patch("GameBot.runner.driver.screenshot.time") as mock_time:
            mock_time.time.side_effect = [1000, 1000.5]
            result1 = dm.save_screenshot(label="first")
            result2 = dm.save_screenshot(label="second", force=True)

        self.assertIsNotNone(result1)
        self.assertIsNotNone(result2)


class TestDmClientWindowRectAndClose(unittest.TestCase):
    """DmClientBase 窗口矩形与右上角 X 关闭测试。"""

    def setUp(self):
        self._orig = _mock_dm_modules()

    def tearDown(self):
        _restore_dm_modules(self._orig)

    @patch.object(_TestDmClient, "get_screen_rect")
    def test_get_window_rect_through_active_screenshot(self, mock_screen):
        """get_window_rect 通过与 save_active_window_screenshot 集成验证："""
        dm = _make_dm_client()
        dm.get_foreground_window = MagicMock(return_value=123)
        dm.get_window_rect = MagicMock(return_value=(10, 10, 110, 110))
        dm.save_screenshot = MagicMock(return_value=Path("/tmp/active.bmp"))

        result = dm.save_active_window_screenshot(label="active")

        self.assertEqual(result, Path("/tmp/active.bmp"))
        dm.get_window_rect.assert_called_once_with(123)
        dm.save_screenshot.assert_called_once_with((10, 10, 110, 110), "active")

    def test_get_screen_rect(self):
        """应通过大漠 GetScreenWidth/GetScreenHeight 返回主屏幕矩形。"""
        dm = _make_dm_client()
        dm._com.GetScreenWidth.return_value = 1920
        dm._com.GetScreenHeight.return_value = 1080

        result = dm.get_screen_rect()
        self.assertEqual(result, (0, 0, 1920, 1080))
        dm._com.GetScreenWidth.assert_called_once()
        dm._com.GetScreenHeight.assert_called_once()

    def test_close_window_by_x_success(self):
        """成功点击右上角 X。"""
        dm = _make_dm_client()
        dm.get_client_rect = MagicMock(return_value=(0, 0, 200, 100))
        dm.bind_window = MagicMock()
        dm.move_to = MagicMock()
        dm.left_click = MagicMock()

        result = dm.close_window_by_x(123, offset_x=15, offset_y=15)

        self.assertTrue(result)
        dm.move_to.assert_called_once_with(185, 15)
        dm.left_click.assert_called_once()

    def test_close_window_by_x_invalid_hwnd(self):
        """hwnd 为 0 时返回 False。"""
        dm = _make_dm_client()
        result = dm.close_window_by_x(0)
        self.assertFalse(result)

    def test_close_window_by_x_negative_coords(self):
        """计算坐标为负时应返回 False 且不点击。"""
        dm = _make_dm_client()
        dm.get_client_rect = MagicMock(return_value=(0, 0, 10, 20))

        result = dm.close_window_by_x(123, offset_x=15, offset_y=25)

        self.assertFalse(result)


class TestDmClientGetActiveWindow(unittest.TestCase):
    """DmClientBase.get_active_window 截图分支测试。"""

    def setUp(self):
        self._orig = _mock_dm_modules()

    def tearDown(self):
        _restore_dm_modules(self._orig)

    def test_get_active_window_expected(self):
        """前台窗口为预期窗口时直接返回句柄。"""
        dm = _make_dm_client()
        dm.get_foreground_window = MagicMock(return_value=123)
        dm.enum_windows = MagicMock(return_value=[123, 456])

        result = dm.get_active_window("War3Class", "War3Title", capture=True)

        self.assertEqual(result, 123)

    def test_get_active_window_no_foreground_captures(self):
        """无前台窗口时保存全屏截图并返回 0。"""
        dm = _make_dm_client()
        dm.get_foreground_window = MagicMock(return_value=0)
        dm.save_screenshot = MagicMock(return_value=Path("/tmp/no_active.bmp"))

        result = dm.get_active_window("War3Class", "War3Title")

        self.assertEqual(result, 0)
        dm.save_screenshot.assert_called_once_with(label="no_active_window")

    def test_get_active_window_unexpected_captures(self):
        """前台窗口非预期窗口时保存该窗口截图并返回 0。"""
        dm = _make_dm_client()
        dm.get_foreground_window = MagicMock(return_value=789)
        dm.enum_windows = MagicMock(return_value=[123, 456])
        dm.save_active_window_screenshot = MagicMock(return_value=Path("/tmp/unexpected.bmp"))

        result = dm.get_active_window("War3Class", "War3Title")

        self.assertEqual(result, 0)
        dm.save_active_window_screenshot.assert_called_once()


class TestKKBusinessPopupDismiss(unittest.TestCase):
    """KKBusiness 弹窗清理与开始游戏测试。"""

    def setUp(self):
        self._orig = _mock_dm_modules()
        # 避免 OCR 客户端真实加载模型，测试中统一 mock
        self._ocr_patch = patch("GameBot.runner.business.base.get_inference_client")
        self._ocr_mock = self._ocr_patch.start()
        self._ocr_mock.return_value.ocr_lines_from_file.return_value = []
        self._remove_patch = patch("os.remove")
        self._remove_patch.start()

    def tearDown(self):
        self._remove_patch.stop()
        self._ocr_patch.stop()
        _restore_dm_modules(self._orig)

    def _make_kk(self, kk_cfg=None):
        from GameBot.runner.business.kk import KKBusiness

        dm = MagicMock()
        dm.get_client_rect.return_value = (0, 0, 1328, 945)
        dm.find_windows.return_value = []
        dm.capture_to_temp.return_value = "/tmp/test_ocr.bmp"
        if kk_cfg is None:
            kk_cfg = {
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
        return KKBusiness(dm, kk_cfg)

    def test_dismiss_room_popups_room_on_top(self):
        """房间尺寸匹配时直接返回句柄。"""
        kk = self._make_kk()
        kk.dm.find_windows.return_value = [
            {"hwnd": 123, "title": "KKTitle", "class": "KKClass", "rect": (0, 0, 1328, 945)}
        ]

        result = kk.dismiss_room_popups(kk.dm)

        self.assertEqual(result, 123)
        kk.dm.close_window_by_x.assert_not_called()

    def test_dismiss_room_popups_large_main_window_breaks(self):
        """顶层窗口大于房间面积比例时视为大厅，不关闭。"""
        kk = self._make_kk()
        # 1600x945 面积大于 1328*945*0.85
        kk.dm.get_client_rect.return_value = (0, 0, 1600, 945)
        kk.dm.find_windows.side_effect = lambda window_class, *args: [
            {"hwnd": 123, "title": "KKTitle", "class": "KKClass", "rect": (0, 0, 1600, 945)}
        ] if window_class == "KKClass" else []

        result = kk.dismiss_room_popups(kk.dm)

        self.assertEqual(result, 0)
        kk.dm.close_window_by_x.assert_not_called()

    def test_dismiss_room_popups_closes_popup(self):
        """目标 PID 的弹窗关闭后应继续识别房间。"""
        kk = self._make_kk()
        popup_hwnd = 100
        room_hwnd = 200
        kk.dm.find_windows.side_effect = [
            [],
            [{"hwnd": popup_hwnd, "title": "KKTitle", "class": "CreateClass", "rect": (0, 0, 400, 300)}],
            [{"hwnd": room_hwnd, "title": "KKTitle", "class": "KKClass", "rect": (0, 0, 1328, 945)}],
        ]
        kk.dm.get_client_rect.side_effect = lambda hwnd: (
            (0, 0, 400, 300) if hwnd == popup_hwnd else (0, 0, 1328, 945)
        )
        kk.dm.close_window_by_x.return_value = True
        self._ocr_mock.return_value.ocr_lines_from_file.side_effect = [[], [{"text": "开始游戏"}]]

        result = kk.dismiss_room_popups(kk.dm)

        self.assertEqual(result, room_hwnd)
        kk.dm.close_window_by_x.assert_called_once()

    def test_dismiss_room_popups_finds_room_by_size(self):
        """同类同标题窗口应按客户区尺寸区分房间。"""
        kk = self._make_kk()
        kk.dm.find_windows.return_value = [
            {"hwnd": 111, "title": "KKTitle", "class": "KKClass", "rect": (0, 0, 1000, 700)},
            {"hwnd": 222, "title": "KKTitle", "class": "KKClass", "rect": (0, 0, 1328, 945)},
        ]
        kk.dm.get_client_rect.side_effect = lambda hwnd: (
            (0, 0, 1000, 700) if hwnd == 111 else (0, 0, 1328, 945)
        )

        result = kk.dismiss_room_popups(kk.dm)

        self.assertEqual(result, 222)

    def test_start_game_no_room_captures(self):
        """找不到房间时截图并返回。"""
        kk = self._make_kk()
        kk.dismiss_room_popups = MagicMock(return_value=0)

        kk.start_game(kk.dm)

        kk.dm.save_screenshot.assert_called_once_with(label="kk_room_not_found", force=True)
        kk.dm.set_client_size.assert_not_called()

    def test_start_game_success(self):
        """找到房间后设置尺寸、绑定并点击开始。"""
        kk = self._make_kk()
        kk.dismiss_room_popups = MagicMock(return_value=123)
        self._ocr_mock.return_value.ocr_lines_from_file.return_value = [{"text": "开始游戏"}]

        kk.start_game(kk.dm)

        kk.dm.set_client_size.assert_called_once_with(123, 1328, 945)
        kk.dm.move_to.assert_called_once_with(1100, 900)
        kk.dm.left_click.assert_called_once()


class TestWindowManagerMixin(unittest.TestCase):
    """WindowManagerMixin 等待窗口与掉线截图测试。"""

    def setUp(self):
        self._orig = _mock_dm_modules()

    def tearDown(self):
        _restore_dm_modules(self._orig)

    def _make_war3(self, war3_cfg=None, dm=None):
        from GameBot.runner.business.war3.core import War3Business

        if dm is None:
            dm = MagicMock()
        if war3_cfg is None:
            war3_cfg = {
                "window_class": "War3Class",
                "window_title": "War3Title",
                "in_game_detect": {"timeout": 5, "method": "image"},
                "check_interval_time": 0.1,
            }
        return War3Business(dm, war3_cfg)

    def test_wait_for_game_window_timeout_screenshot(self):
        """等待 War3 窗口超时后保存截图。"""
        war3 = self._make_war3()
        war3.dm.get_active_window.return_value = 0

        with patch("GameBot.runner.business.war3.window_manager.time") as mock_time:
            start = [0]

            def fake_time():
                start[0] += 0.5
                return start[0]

            mock_time.time.side_effect = fake_time

            result = war3.wait_for_game_window(timeout=1)

        self.assertIsNone(result)
        war3.dm.save_screenshot.assert_called_once_with(label="wait_for_game_window_timeout")

    def test_wait_for_game_window_success(self):
        """成功找到 War3 窗口时返回句柄。"""
        war3 = self._make_war3()
        war3.dm.get_active_window.return_value = 123

        result = war3.wait_for_game_window(timeout=1)

        self.assertEqual(result, 123)
        war3.dm.save_screenshot.assert_not_called()

    def test_wait_enter_game_window_lost(self):
        """等待进入游戏时窗口消失应抛 WindowLostError 并截图。"""
        war3 = self._make_war3()
        war3.is_in_game = MagicMock(return_value=False)
        war3.dm.get_active_window.return_value = 0
        war3.interruptible_wait = MagicMock()

        task = MagicMock()

        with self.assertRaises(Exception):
            war3.wait_enter_game(task)

        war3.dm.save_active_window_screenshot.assert_called_once_with(label="war3_window_lost")


class TestAtomicLoopTaskClosePopup(unittest.TestCase):
    """AtomicLoopTask._close_popup 右上角 X 模式测试。"""

    def setUp(self):
        self._orig = _mock_dm_modules()

    def tearDown(self):
        _restore_dm_modules(self._orig)

    def _make_task(self, full_cfg):
        from GameBot.runner.tasks.war3.jiubing2.base import MultiAtomicLoopTask

        task = MultiAtomicLoopTask.__new__(MultiAtomicLoopTask)
        task.war3_cfg = {"general_time": 0.1}
        task.full_cfg = full_cfg
        task.dm = MagicMock()
        return task

    def test_close_popup_by_x(self):
        """task_popup.close_by_x=true 时点击 area_coords 右上角偏移。"""
        task = self._make_task(
            {
                "task_popup": {
                    "close_by_x": True,
                    "area_coords": [600, 200, 1300, 600],
                    "close_offset": [15, 15],
                },
            }
        )

        task._close_popup(None)

        task.dm.move_to.assert_called_once_with(1285, 215)
        task.dm.left_click.assert_called_once()
        task.dm.key_press_char.assert_not_called()

    def test_close_popup_by_coords(self):
        """close_by_x=false 时点击 close_coords。"""
        task = self._make_task(
            {
                "task_popup": {"close_by_x": False},
            }
        )

        task._close_popup((100, 200))

        task.dm.move_to.assert_called_once_with(100, 200)
        task.dm.left_click.assert_called_once()
        task.dm.key_press_char.assert_not_called()

    def test_close_popup_escape_fallback(self):
        """close_by_x=false 且 close_coords 无效时按 Escape。"""
        task = self._make_task(
            {
                "task_popup": {"close_by_x": False},
            }
        )

        task._close_popup((0, 0))

        task.dm.key_press_char.assert_called_once_with("Escape")


class TestEndlessTaskDoKK(unittest.TestCase):
    """EndlessTask.do_kk 弹窗清理测试。"""

    def setUp(self):
        self._orig = _mock_dm_modules()

    def tearDown(self):
        _restore_dm_modules(self._orig)

    def _make_task(self):
        from GameBot.runner.tasks.war3.jiubing2.endless.endless import EndlessTask

        task = EndlessTask.__new__(EndlessTask)
        task.dm = MagicMock()
        task.kk = MagicMock()
        task.task_cfg = {"game": {"map_name": "九种兵器2诸神战场"}}
        return task

    def test_do_kk_calls_start_game(self):
        """do_kk 找到房间后应调用 kk.start_game(dm, room_hwnd=...)。"""
        task = self._make_task()
        task.kk.dismiss_room_popups.return_value = 123
        task.do_kk()
        task.kk.dismiss_room_popups.assert_called_once_with(task.dm)
        task.kk.start_game.assert_called_once_with(task.dm, room_hwnd=123)
        task.kk.dismiss_hall_popups.assert_not_called()
        task.kk.create_room.assert_not_called()

    def test_do_kk_creates_room_when_missing(self):
        """do_kk 未找到房间时应清理主界面弹窗并创建房间。"""
        task = self._make_task()
        task.kk.dismiss_room_popups.return_value = 0
        task.kk.create_room.return_value = 456
        task.do_kk()
        task.kk.dismiss_hall_popups.assert_called_once_with(task.dm)
        task.kk.create_room.assert_called_once_with(task.dm, map_name="九种兵器2诸神战场")
        task.kk.start_game.assert_called_once_with(task.dm, room_hwnd=456)

    def test_do_kk_create_room_fails_skips(self):
        """do_kk 创建房间失败时跳过本局，不调用 start_game。"""
        task = self._make_task()
        task.kk.dismiss_room_popups.return_value = 0
        task.kk.create_room.return_value = 0
        task.do_kk()
        task.kk.dismiss_hall_popups.assert_called_once_with(task.dm)
        task.kk.create_room.assert_called_once_with(task.dm, map_name="九种兵器2诸神战场")
        task.kk.start_game.assert_not_called()


if __name__ == "__main__":
    unittest.main()
