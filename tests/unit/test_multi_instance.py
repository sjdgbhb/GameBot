"""MultiInstanceMixin 多开识别测试。

覆盖：
- U-16: identify_hall_owner 返回第一个 OCR 行
- U-18: _compute_kk_ocr_bbox 客户区坐标转屏幕 bbox
"""

import sys
import threading
import unittest
from contextlib import ExitStack, contextmanager, nullcontext
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
    # get_client_rect 按 hwnd 返回尺寸：大厅 1328x945，下拉框取其 find_windows rect 的宽高
    # （实现优先用 get_client_rect 而非 find_windows 的 rect，bridge 模式下 rect 可能为 0）
    _client_sizes = {
        500: (1328, 945),
        111: (246, 342),
        222: (156, 252),
        333: (156, 252),
        997: (156, 252),
        998: (156, 252),
        999: (156, 252),
    }

    def _get_client_rect(hwnd):
        w, h = _client_sizes.get(hwnd, (0, 0))
        return (0, 0, w, h)

    kk.dm.get_client_rect.side_effect = _get_client_rect
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

        kernel32.CreateMutexW.assert_called_once_with(None, False, "Local\\GameBot_KK_Hall_Identify_PID_4567")
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
            222,
            {"area_coords": [0, 0, 156, 252]},
        )


class TestClaimRoomWindow(unittest.TestCase):
    """claim_room_window 新认领协议测试（注册表 + PID 匹配 + token 自举）。

    claim_window 原语、window_pid、注册表均 mock，只测 mixin 侧接线：
    resolve/identify 回调行为、kk_pid 缓存与 kk_owner 写回。
    """

    def setUp(self):
        self._orig = _mock_dm_modules()

    def tearDown(self):
        _restore_dm_modules(self._orig)

    def _make_kk(self):
        from GameBot.runner.business.kk.multi_instance import MultiInstanceMixin

        kk = MultiInstanceMixin.__new__(MultiInstanceMixin)
        kk.dm = MagicMock()
        kk.kk_cfg = {
            "window_class": "KKClass",
            "window_title": "KKTitle",
            "room": {"window_size": [1224, 904]},
            "multi_instance": {"claim_timeout": 5, "claim_retry_interval": 0.01},
            "bind": {},
        }
        kk._claimed_room_hwnd = 0
        kk._claimed_room_pid = 0
        kk._claimed_room_mutex = None
        kk._kk_pid = 0
        kk.target_player = ""
        kk.task_name = ""
        return kk

    @contextmanager
    def _patched(self, kk_pid_of=0, claim_return=None, claim_side_effect=None):
        """patch 认领链路依赖：claim_window / window_pid / ensure_registered / self_kk_pid。"""
        reg = MagicMock()
        reg.kk_pid_of.return_value = kk_pid_of
        with ExitStack() as stack:
            stack.enter_context(
                patch("GameBot.runner.business.kk.multi_instance.ensure_registered", return_value=reg)
            )
            m_pid = stack.enter_context(
                patch("GameBot.runner.business.kk.multi_instance.self_kk_pid", return_value=kk_pid_of)
            )
            m_wpid = stack.enter_context(patch("GameBot.runner.business.kk.multi_instance.window_pid"))
            m_claim = stack.enter_context(patch("GameBot.runner.business.kk.multi_instance.claim_window"))
            if claim_side_effect is not None:
                m_claim.side_effect = claim_side_effect
            else:
                m_claim.return_value = claim_return if claim_return is not None else (600, MagicMock())
            m_wpid.return_value = 4567
            yield reg, m_pid, m_wpid, m_claim

    def test_claim_room_returns_claimed_hwnd_pid(self):
        """认领成功返回 (hwnd, kk_pid) 并缓存窗口。"""
        kk = self._make_kk()
        mutex = MagicMock()
        with self._patched(claim_return=(600, mutex)):
            hwnd, pid = kk.claim_room_window(kk.dm, "善木木")
        self.assertEqual((hwnd, pid), (600, 4567))
        self.assertEqual(kk._claimed_room_hwnd, 600)
        self.assertEqual(kk._claimed_room_pid, 4567)
        self.assertEqual(kk._claimed_room_mutex, mutex)
        kk.release_room_claim()

    def test_claim_room_registry_hit_passes_kk_pid(self):
        """注册表命中 kk_pid 时 self_kk_pid 返回该值供 resolve 判定。"""
        kk = self._make_kk()
        with self._patched(kk_pid_of=4567) as (reg, m_pid, m_wpid, m_claim):
            kk.claim_room_window(kk.dm, "善木木")
        m_pid.assert_called()
        m_claim.assert_called_once()

    def test_claim_room_timeout_propagates_claim_error(self):
        """claim_window 超时抛 ClaimError 直接上抛（不再返回 (0,0)）。"""
        from GameBot.utils import ClaimError

        kk = self._make_kk()
        with self._patched(claim_side_effect=ClaimError("认领超时")):
            with self.assertRaises(ClaimError):
                kk.claim_room_window(kk.dm, "善木木", claim_timeout=1)

    def test_claim_room_reuses_cached_hwnd(self):
        """已认领且窗口存活（PID 一致）时直接复用，不走认领原语。"""
        kk = self._make_kk()
        kk._claimed_room_hwnd = 500
        kk._claimed_room_pid = 4567
        with self._patched() as (reg, m_pid, m_wpid, m_claim):
            m_wpid.return_value = 4567
            hwnd, pid = kk.claim_room_window(kk.dm, "善木木")
        self.assertEqual((hwnd, pid), (500, 4567))
        m_claim.assert_not_called()
        kk.release_room_claim()

    def test_claim_room_reclaims_after_window_dead(self):
        """认领窗口销毁（PID 查询为 0）后释放锁并走认领原语。"""
        kk = self._make_kk()
        kk._claimed_room_hwnd = 500
        kk._claimed_room_pid = 4567
        kk.release_room_claim = MagicMock()
        with self._patched() as (reg, m_pid, m_wpid, m_claim):
            m_wpid.return_value = 0  # 窗口已销毁
            kk.claim_room_window(kk.dm, "善木木")
        kk.release_room_claim.assert_called_once()
        m_claim.assert_called_once()

    def test_resolve_owner_by_kk_pid(self):
        """kk_pid 已知时 resolve_owner 按窗口 PID 确定性判定，不落 identify。"""
        kk = self._make_kk()
        with self._patched(kk_pid_of=4567) as (reg, m_pid, m_wpid, m_claim):
            kk.claim_room_window(kk.dm, "善木木")
            resolve = m_claim.call_args.kwargs["resolve_owner"]
            m_wpid.return_value = 4567
            self.assertTrue(resolve(100))
            m_wpid.return_value = 9999
            self.assertFalse(resolve(101))

    def test_resolve_owner_by_registry_player(self):
        """kk_pid 未知时按注册表 kk_owner 反查玩家名比对。"""
        kk = self._make_kk()
        with self._patched(kk_pid_of=0) as (reg, m_pid, m_wpid, m_claim):
            kk.claim_room_window(kk.dm, "善木木")
            resolve = m_claim.call_args.kwargs["resolve_owner"]
            m_wpid.return_value = 8888
            reg.player_of_kk_pid.return_value = "其他玩家"
            self.assertFalse(resolve(100))
            reg.player_of_kk_pid.return_value = "善木木"
            self.assertTrue(resolve(100))
            reg.player_of_kk_pid.return_value = ""
            self.assertIsNone(resolve(100))

    def test_identify_writes_kk_owner_on_match(self):
        """token 自举命中：写 kk_owner 并推出本账号 kk_pid。"""
        kk = self._make_kk()
        kk._identify_room_owner_by_chat = MagicMock(return_value="善木木#1234")
        with self._patched(kk_pid_of=0) as (reg, m_pid, m_wpid, m_claim):
            m_wpid.return_value = 4567
            kk.claim_room_window(kk.dm, "善木木")
            identify = m_claim.call_args.kwargs["identify"]
            self.assertTrue(identify(600))
            # identify 写识别出的归属名；认领成功后补写 target_player 映射
            reg.set_kk_owner.assert_any_call(4567, "善木木#1234")
            self.assertEqual(kk._kk_pid, 4567)

    def test_identify_mismatch_still_writes_kk_owner(self):
        """token 自举识别出他人归属：仍写 kk_owner（其他实例可复用），返回 False。"""
        kk = self._make_kk()
        kk._identify_room_owner_by_chat = MagicMock(return_value="其他玩家")
        with self._patched(kk_pid_of=0) as (reg, m_pid, m_wpid, m_claim):
            kk.claim_room_window(kk.dm, "善木木")
            identify = m_claim.call_args.kwargs["identify"]
            self.assertFalse(identify(600))
            reg.set_kk_owner.assert_any_call(4567, "其他玩家")

    def test_identify_empty_owner_returns_false(self):
        """token 未上屏/归属名未解析出时返回 False。"""
        kk = self._make_kk()
        kk._identify_room_owner_by_chat = MagicMock(return_value="")
        with self._patched(kk_pid_of=0) as (reg, m_pid, m_wpid, m_claim):
            kk.claim_room_window(kk.dm, "善木木")
            identify = m_claim.call_args.kwargs["identify"]
            self.assertFalse(identify(600))
            # 认领前 set_kk_owner 未被 identify 调用（认领成功后的补写是 target_player）
            reg.set_kk_owner.assert_called_once_with(4567, "善木木")

    def test_empty_target_player_resolves_true(self):
        """target_player 为空时 resolve 恒 True（认领第一个空闲窗口）。"""
        kk = self._make_kk()
        with self._patched() as (reg, m_pid, m_wpid, m_claim):
            kk.claim_room_window(kk.dm, "")
            resolve = m_claim.call_args.kwargs["resolve_owner"]
            self.assertTrue(resolve(100))  # 空归属 resolve 不查 PID

    def test_candidates_filter_non_room_windows(self):
        """候选枚举过滤非房间窗口。"""
        kk = self._make_kk()
        kk.dm.find_windows.return_value = [{"hwnd": 500}, {"hwnd": 600}]
        kk._check_room_window = MagicMock(side_effect=lambda dm, h: h == 600)
        kk.dm.get_window_state.return_value = True
        with self._patched() as (reg, m_pid, m_wpid, m_claim):
            kk.claim_room_window(kk.dm, "善木木")
        candidates = m_claim.call_args.kwargs["candidates_fn"]()
        self.assertEqual(candidates, [600])
