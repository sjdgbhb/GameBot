"""MultiInstanceMixin 多开识别测试。

覆盖：
- U-16: identify_hall_owner 返回第一个 OCR 行
- U-18: _compute_kk_ocr_bbox 客户区坐标转屏幕 bbox
"""

import sys
import threading
import unittest
from contextlib import nullcontext
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


def _make_kk():
    """构造 MultiInstanceMixin 实例，跳过 __init__。"""
    from GameBot.runner.business.kk.multi_instance import MultiInstanceMixin

    kk = MultiInstanceMixin.__new__(MultiInstanceMixin)
    kk.dm = MagicMock()
    kk.kk_cfg = {
        "window_class": "KKClass",
        "window_title": "KKTitle",
        "dropdown_window_class": "Qt5152QWindowPopupSaveBits",
        "main": {
            "window_size": [1328, 945],
            "profile_icon_coords": [100, 50],
            "dropdown_wait_time": 0,
            "username_area_coords": [50, 80, 300, 200],
        },
        "room": {
            "window_size": [1224, 904],
        },
    }
    ctx = MagicMock()
    kk.dm.bind_window.return_value = ctx
    kk.dm.get_client_rect.return_value = (0, 0, 1328, 945)
    kk.dm.get_window_process_id.return_value = 1234
    # 点击头像后，同 PID 下有大厅窗口和下拉框窗口
    # identify_hall_owner 按 PID + 完整类名 + 标题筛选下拉框
    kk.dm.find_windows.return_value = [
        {"hwnd": 500, "title": "KKTitle", "class": "KKClass", "rect": (0, 0, 1328, 945)},
        {"hwnd": 999, "title": "KKTitle", "class": "Qt5152QWindowPopupSaveBits", "rect": (100, 100, 256, 352)},
    ]
    kk.dm.get_window_parent.return_value = 0
    kk._pid_identify_lock = MagicMock(return_value=nullcontext(True))
    # MultiInstanceMixin 依赖 Base.ocr_lines，测试中直接 mock
    kk.ocr_lines = MagicMock(return_value=[])
    return kk


class TestIdentifyHallOwner(unittest.TestCase):
    """identify_hall_owner 大厅玩家 ID 识别测试。"""

    def setUp(self):
        self._orig = _mock_dm_modules()

    def tearDown(self):
        _restore_dm_modules(self._orig)

    @patch("GameBot.runner.business.kk.multi_instance.ctypes.windll.kernel32")
    def test_pid_identify_lock_skips_busy_pid(self, kernel32):
        from GameBot.runner.business.kk.multi_instance import MultiInstanceMixin

        kk = MultiInstanceMixin.__new__(MultiInstanceMixin)
        kernel32.CreateMutexW.return_value = 123
        kernel32.WaitForSingleObject.return_value = 0x102

        with kk._pid_identify_lock(4567) as acquired:
            self.assertFalse(acquired)

        kernel32.CreateMutexW.assert_called_once_with(
            None, False, "Local\\GameBot_KK_Hall_Identify_PID_4567"
        )
        kernel32.WaitForSingleObject.assert_called_once_with(123, 0)
        kernel32.ReleaseMutex.assert_not_called()
        kernel32.CloseHandle.assert_called_once_with(123)

    # U-16: 返回第一个 OCR 行
    def test_identify_hall_owner_returns_first_ocr_line(self):
        """应返回 OCR 识别的第一个非空文本。"""
        kk = _make_kk()
        kk.ocr_lines.return_value = [
            {"text": "PlayerABC", "y_center": 100},
        ]

        result = kk.identify_hall_owner(kk.dm, 500)

        self.assertEqual(result, "PlayerABC")

    def test_non_matching_ocr_owner_is_written_to_shared_cache(self):
        kk = _make_kk()
        kk.ocr_lines.return_value = [{"text": "其他玩家#1234"}]
        shared_cache = MagicMock()
        shared_cache.read_hall_owner.return_value = None

        result = kk.identify_hall_owner(kk.dm, 500, hall_owner_cache=shared_cache)

        self.assertEqual(result, "其他玩家#1234")
        shared_cache.write_hall_owner.assert_called_once_with(500, 1234, "其他玩家#1234")

    def test_shared_cache_hit_skips_click_and_ocr(self):
        kk = _make_kk()
        shared_cache = MagicMock()
        shared_cache.read_hall_owner.return_value = "岁月神偷#8146"

        result = kk.identify_hall_owner(kk.dm, 500, hall_owner_cache=shared_cache)

        self.assertEqual(result, "岁月神偷#8146")
        kk.dm.left_click.assert_not_called()
        kk.ocr_lines.assert_not_called()
        shared_cache.write_hall_owner.assert_not_called()

    def test_identify_hall_owner_resizes_before_ocr(self):
        kk = _make_kk()
        kk.ocr_lines.return_value = [{"text": "PlayerABC#1234"}]
        # 点击前没有下拉框，点击后出现新下拉框 999
        kk.dm.find_windows.side_effect = [
            [],
            [{"hwnd": 999, "title": "KKTitle", "class": "Qt5152QWindowPopupSaveBits", "rect": (100, 100, 256, 352)}],
        ]

        result = kk.identify_hall_owner(kk.dm, 500)

        self.assertEqual(result, "PlayerABC#1234")
        kk._pid_identify_lock.assert_called_once_with(1234, stop_event=None)
        kk.dm.set_client_size.assert_called_once_with(500, 1328, 945)
        kk.dm.move_to.assert_called_once_with(100, 50)
        # OCR 应在下拉框绑定上下文内调用（bind_window 幂等，已绑定时自动复用）
        kk.ocr_lines.assert_called_once_with(
            kk.dm,
            999,
            {"area_coords": [0, 0, 156, 252]},
        )

    def test_busy_window_is_skipped_without_click(self):
        kk = _make_kk()
        kk._pid_identify_lock.return_value = nullcontext(False)

        result = kk.identify_hall_owner(kk.dm, 500)

        self.assertIsNone(result)
        kk.dm.left_click.assert_not_called()

    def test_identify_hall_owner_stops_before_click(self):
        from GameBot.utils import StopTaskError

        kk = _make_kk()
        stop_event = threading.Event()
        stop_event.set()

        with self.assertRaises(StopTaskError):
            kk.identify_hall_owner(kk.dm, 500, stop_event=stop_event)

        kk.dm.left_click.assert_not_called()

    def test_identify_hall_owner_empty_returns_empty(self):
        """OCR 无结果时应返回空字符串。"""
        kk = _make_kk()
        kk.ocr_lines.return_value = []

        result = kk.identify_hall_owner(kk.dm, 500)

        self.assertEqual(result, "")
        kk.ocr_lines.assert_called_once()

    def test_identify_hall_owner_prefers_new_dropdown_owned_by_hall(self):
        """点击后若出现多个新下拉框，优先父/属主为当前大厅的窗口。"""
        kk = _make_kk()
        # 点击前没有下拉框；点击后出现两个新下拉框
        before = []
        after = [
            {"hwnd": 997, "title": "KKTitle", "class": "Qt5152QWindowPopupSaveBits", "rect": (100, 100, 256, 352)},
            {"hwnd": 998, "title": "KKTitle", "class": "Qt5152QWindowPopupSaveBits", "rect": (200, 200, 356, 452)},
        ]
        kk.dm.find_windows.side_effect = [before, after]

        def _parent_side_effect(hwnd):
            # 998 属于当前大厅，997 属于其他大厅
            if hwnd == 998:
                return 500
            return 0

        kk.dm.get_window_parent.side_effect = _parent_side_effect

        kk.ocr_lines.return_value = [{"text": "善木木#3686"}]

        result = kk.identify_hall_owner(kk.dm, 500)

        self.assertEqual(result, "善木木#3686")
        # 应绑定 998，而不是 Z 序更靠前的 997
        kk.ocr_lines.assert_called_once_with(
            kk.dm,
            998,
            {"area_coords": [0, 0, 156, 252]},
        )

    def test_identify_hall_owner_skips_pre_existing_other_dropdown(self):
        """点击前已存在其他大厅的下拉框时，应选择本次点击新弹出的、属于当前大厅的下拉框。"""
        kk = _make_kk()
        # 点击前已有其他大厅的下拉框；点击后既有旧的也有新的
        before = [
            {"hwnd": 111, "title": "KKTitle", "class": "Qt5152QWindowPopupSaveBits", "rect": (10, 10, 256, 352)},
        ]
        after = [
            {"hwnd": 111, "title": "KKTitle", "class": "Qt5152QWindowPopupSaveBits", "rect": (10, 10, 166, 162)},
            {"hwnd": 222, "title": "KKTitle", "class": "Qt5152QWindowPopupSaveBits", "rect": (100, 100, 256, 352)},
            {"hwnd": 333, "title": "KKTitle", "class": "Qt5152QWindowPopupSaveBits", "rect": (200, 200, 356, 452)},
        ]
        kk.dm.find_windows.side_effect = [before, after]

        def _parent_side_effect(hwnd):
            if hwnd == 222:
                return 500
            return 0

        kk.dm.get_window_parent.side_effect = _parent_side_effect

        kk.ocr_lines.return_value = [{"text": "岁月神偷#1234"}]

        result = kk.identify_hall_owner(kk.dm, 500)

        self.assertEqual(result, "岁月神偷#1234")
        # 应绑定 222（父窗口是当前大厅），跳过 111（旧的）和 333（Z 序更前但非本大厅）
        kk.ocr_lines.assert_called_once_with(
            kk.dm,
            222,
            {"area_coords": [0, 0, 156, 252]},
        )

    def test_identify_hall_owner_fallback_to_new_without_parent(self):
        """新弹出的下拉框无法确认父窗口时，应兜底选择第一个新出现的。"""
        kk = _make_kk()
        before = [
            {"hwnd": 111, "title": "KKTitle", "class": "Qt5152QWindowPopupSaveBits", "rect": (10, 10, 256, 352)},
        ]
        after = [
            {"hwnd": 111, "title": "KKTitle", "class": "Qt5152QWindowPopupSaveBits", "rect": (10, 10, 166, 162)},
            {"hwnd": 222, "title": "KKTitle", "class": "Qt5152QWindowPopupSaveBits", "rect": (100, 100, 256, 352)},
        ]
        kk.dm.find_windows.side_effect = [before, after]
        kk.dm.get_window_parent.return_value = 0

        kk.ocr_lines.return_value = [{"text": "PlayerXYZ"}]

        result = kk.identify_hall_owner(kk.dm, 500)

        self.assertEqual(result, "PlayerXYZ")
        kk.ocr_lines.assert_called_once_with(
            kk.dm,
            222,
            {"area_coords": [0, 0, 156, 252]},
        )


class TestCheckParentChildRelation(unittest.TestCase):
    """check_parent_child_relation 父子窗口验证测试。"""

    def setUp(self):
        self._orig = _mock_dm_modules()

    def tearDown(self):
        _restore_dm_modules(self._orig)

    def test_check_parent_child_relation_has_parent(self):
        """有父窗口时应返回父窗口句柄。"""
        kk = _make_kk()
        kk.dm.get_window_parent.return_value = 789

        result = kk.check_parent_child_relation(kk.dm, 123)

        self.assertEqual(result, 789)

    def test_check_parent_child_relation_no_parent(self):
        """无父窗口时应返回 0。"""
        kk = _make_kk()
        kk.dm.get_window_parent.return_value = 0

        result = kk.check_parent_child_relation(kk.dm, 123)

        self.assertEqual(result, 0)
