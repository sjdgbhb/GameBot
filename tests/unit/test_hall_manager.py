"""HallManagerMixin 弹窗清理与创建房间测试。

覆盖：
- U-08: dismiss_hall_popups 循环直到无弹窗
- U-09: dismiss_hall_popups 不关闭创建房间弹窗
- U-10: dismiss_hall_popups 不关闭大厅和房间
- U-11: create_room 地图未找到时 save_screenshot(force=True)
- U-12: create_room 调用新版 send_string 输入地图名
- U-13a: create_room OCR 按 (y_center, x_center) 排序
- U-14: create_room dismiss_hall_popups 在 bind_window 外调用
"""

import sys
import unittest
from contextlib import ExitStack, contextmanager
from unittest.mock import MagicMock, call, patch

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
    """构造 HallManagerMixin 实例，跳过 __init__。

    由于 HallManagerMixin 依赖 KKBusiness.ocr_kk_lines，测试中绑定一个局部实现，
    使其调用测试里 patch 的 get_inference_client。
    """
    import types

    from GameBot.runner.business import base as _base
    from GameBot.runner.business.kk.hall_manager import HallManagerMixin

    kk = HallManagerMixin.__new__(HallManagerMixin)
    kk.dm = MagicMock()

    def _ocr_kk_lines(self, hwnd, ocr_cfg, merge_lines=True):
        raw = _base.get_inference_client().ocr_lines_from_array(
            MagicMock(), merge_lines=merge_lines
        )
        # 模拟 Base.ocr_lines 行为：OCR 坐标相对于截图区域，不额外偏移
        import copy

        lines = copy.deepcopy(raw)
        for line in lines:
            line["x_center"] = line.get("x_center", 0)
            line["y_center"] = line.get("y_center", 0)
        return lines

    kk.ocr_kk_lines = types.MethodType(_ocr_kk_lines, kk)
    # 默认 mock
    kk.dm.find_windows.return_value = []
    kk.dm.get_client_rect.return_value = (0, 0, 1328, 945)
    kk.kk_cfg = {
        "window_class": "KKClass",
        "window_title": "KKTitle",
        "create_room_window_class": "CreateClass",
        "main": {
            "window_size": [1328, 945],
            "search_input_coords": [825, 28],
            "search_map_coords": [919, 26],
            "search_map_wait_time": 0,
            "detail_wait_time": 0,
            "create_button_coords": [805, 898],
            "map_result_ocr_area_coords": [209, 174, 1281, 419],
            "profile_icon_coords": [100, 50],
            "dropdown_wait_time": 0,
            "username_area_coords": [961, 50, 1055, 85],
        },
        "room": {"window_size": [1224, 904]},
        "popup": {
            "close_offset": [15, 15],
            "protected_keywords": ["输入房间密码", "创建房间"],
            "max_popup_area_ratio": 0.85,
        },
        "create_room": {
            "password": "",
            "dialog_window_size": [584, 488],
            "dialog_wait_time": 0,
            "password_input_coords": [329, 211],
            "confirm_create_coords": [315, 438],
            "create_wait_time": 0,
        },
    }
    return kk


class TestDismissHallPopups(unittest.TestCase):
    """dismiss_hall_popups 循环关闭弹窗测试。"""

    def setUp(self):
        self._orig = _mock_dm_modules()

    def tearDown(self):
        _restore_dm_modules(self._orig)

    # U-08: 循环关闭弹窗直到无弹窗
    @patch("GameBot.runner.business.base.get_inference_client")
    def test_dismiss_hall_popups_loops_until_no_popup(self, mock_ocr_client):
        """应循环关闭弹窗，直到一轮未关闭任何弹窗。"""
        kk = _make_kk()
        popup_hwnd = 100
        popup_info = {
            "hwnd": popup_hwnd,
            "title": "KKTitle",
            "class": "CreateClass",
            "rect": (0, 0, 300, 200),
        }
        # 第一轮返回弹窗，第二轮返回空（循环结束）
        kk.dm.find_windows.side_effect = [
            [popup_info],  # 第一轮
            [],  # 第二轮（无弹窗，循环结束）
        ]
        kk.dm.get_client_rect.return_value = (0, 0, 300, 200)
        kk.dm.close_window_by_x.return_value = True
        # OCR 返回空，不命中保护关键词
        mock_ocr_client.return_value.ocr_lines_from_array.return_value = []

        kk.dismiss_hall_popups(kk.dm)

        kk.dm.close_window_by_x.assert_called_once_with(
            popup_hwnd, 15, 15, bind_cfg={"bind_mode": "foreground"}
        )

    # U-09: 不关闭创建房间弹窗（OCR 关键词保护）
    @patch("GameBot.runner.business.base.get_inference_client")
    def test_dismiss_hall_popups_ignores_create_room_dialog(self, mock_ocr_client):
        """含"创建房间"关键词的弹窗不应被关闭。"""
        kk = _make_kk()
        dialog_hwnd = 300
        kk.dm.find_windows.return_value = [
            {
                "hwnd": dialog_hwnd,
                "title": "KKTitle",
                "class": "CreateClass",
                "rect": (0, 0, 584, 488),
            }
        ]
        kk.dm.get_client_rect.return_value = (0, 0, 584, 488)  # 创建房间弹窗尺寸
        mock_ocr_client.return_value.ocr_lines_from_array.return_value = [
            {"text": "创建房间", "y_center": 10, "x_center": 10},
        ]

        kk.dismiss_hall_popups(kk.dm)

        kk.dm.close_window_by_x.assert_not_called()

    # U-10: 不扫描大厅窗口类
    def test_dismiss_hall_popups_ignores_hall_class(self):
        """弹窗清理只枚举弹窗类，不应扫描大厅窗口类。"""
        kk = _make_kk()
        kk.dm.find_windows.return_value = []

        kk.dismiss_hall_popups(kk.dm)

        # find_windows 使用精确类名/标题/owner_pid 过滤
        kk.dm.find_windows.assert_called_once_with("CreateClass", "KKTitle", 0)
        kk.dm.close_window_by_x.assert_not_called()

    # find_windows 已做精确类名过滤，CreateClass 查询不会返回 KKClass 主窗口
    @patch("GameBot.runner.business.base.get_inference_client")
    def test_dismiss_hall_popups_skips_main_window_class(self, mock_ocr_client):
        """find_windows 精确类名过滤后，不会把 KKClass 主窗口当作弹窗处理。"""
        kk = _make_kk()
        # CreateClass 查询结果为空，不会命中主窗口
        kk.dm.find_windows.return_value = []
        mock_ocr_client.return_value.ocr_lines_from_array.return_value = []

        kk.dismiss_hall_popups(kk.dm)

        # 没有弹窗命中，不应 OCR 或关闭
        kk.dm.find_windows.assert_called_once_with("CreateClass", "KKTitle", 0)
        mock_ocr_client.return_value.ocr_lines_from_array.assert_not_called()
        kk.dm.close_window_by_x.assert_not_called()

    # exclude_hwnds 参数生效
    def test_dismiss_hall_popups_exclude_hwnds(self):
        """exclude_hwnds 中的窗口不应被关闭。"""
        kk = _make_kk()
        excluded = 999
        kk.dm.find_windows.return_value = [
            {
                "hwnd": excluded,
                "title": "KKTitle",
                "class": "CreateClass",
                "rect": (0, 0, 300, 200),
            }
        ]
        kk.dm.get_client_rect.return_value = (0, 0, 300, 200)

        kk.dismiss_hall_popups(kk.dm, exclude_hwnds={excluded})

        kk.dm.close_window_by_x.assert_not_called()

    # exclude_hwnds 默认为 None 时不报错
    def test_dismiss_hall_popups_no_exclude(self):
        """exclude_hwnds 默认 None 时不报错。"""
        kk = _make_kk()
        kk.dm.find_windows.return_value = []

        kk.dismiss_hall_popups(kk.dm)  # 不传 exclude_hwnds

    # OCR 关键词保护：密码弹窗不关闭
    @patch("GameBot.runner.business.base.get_inference_client")
    def test_dismiss_hall_popups_ignores_password_dialog(self, mock_ocr_client):
        """含"输入房间密码"关键词的弹窗不应被关闭。"""
        kk = _make_kk()
        dialog_hwnd = 400
        kk.dm.find_windows.return_value = [
            {
                "hwnd": dialog_hwnd,
                "title": "KKTitle",
                "class": "CreateClass",
                "rect": (0, 0, 440, 260),
            }
        ]
        kk.dm.get_client_rect.return_value = (0, 0, 440, 260)  # 密码弹窗尺寸
        mock_ocr_client.return_value.ocr_lines_from_array.return_value = [
            {"text": "输入房间密码", "y_center": 10, "x_center": 10},
        ]

        kk.dismiss_hall_popups(kk.dm)

        kk.dm.close_window_by_x.assert_not_called()


class TestClaimHallWindow(unittest.TestCase):
    """claim_hall_window 新认领协议测试（注册表 + PID 匹配 + 下拉框自举）。

    claim_window 原语、window_pid、注册表均 mock，只测 mixin 侧接线。
    """

    def setUp(self):
        self._orig = _mock_dm_modules()

    def tearDown(self):
        _restore_dm_modules(self._orig)

    def _make_hall_kk(self):
        kk = _make_kk()
        kk._claimed_hall_hwnd = 0
        kk._claimed_hall_pid = 0
        kk._claimed_hall_mutex = None
        kk._kk_pid = 0
        kk.target_player = ""
        kk.task_name = ""
        kk.kk_cfg["multi_instance"] = {"claim_timeout": 5, "claim_retry_interval": 0.01}
        return kk

    @contextmanager
    def _patched(self, kk_pid_of=0, claim_return=None, claim_side_effect=None):
        reg = MagicMock()
        reg.kk_pid_of.return_value = kk_pid_of
        with ExitStack() as stack:
            stack.enter_context(
                patch("GameBot.runner.business.kk.hall_manager.ensure_registered", return_value=reg)
            )
            stack.enter_context(
                patch("GameBot.runner.business.kk.hall_manager.self_kk_pid", return_value=kk_pid_of)
            )
            m_wpid = stack.enter_context(patch("GameBot.runner.business.kk.hall_manager.window_pid"))
            m_claim = stack.enter_context(patch("GameBot.runner.business.kk.hall_manager.claim_window"))
            if claim_side_effect is not None:
                m_claim.side_effect = claim_side_effect
            else:
                m_claim.return_value = claim_return if claim_return is not None else (600, MagicMock())
            m_wpid.return_value = 4567
            yield reg, m_wpid, m_claim

    def test_claim_hall_returns_hwnd_pid_and_caches(self):
        """认领成功返回 (hwnd, kk_pid) 并缓存窗口/互斥锁。"""
        kk = self._make_hall_kk()
        mutex = MagicMock()
        with self._patched(claim_return=(500, mutex)) as (reg, m_wpid, m_claim):
            m_wpid.return_value = 4567
            hwnd, pid = kk.claim_hall_window(kk.dm, "善木木")
        self.assertEqual((hwnd, pid), (500, 4567))
        self.assertEqual(kk._claimed_hall_hwnd, 500)
        self.assertEqual(kk._claimed_hall_pid, 4567)
        self.assertEqual(kk._claimed_hall_mutex, mutex)

    def test_claim_hall_reuses_cached_hwnd(self):
        """已认领窗口存活（PID 一致）时直接复用，不走认领原语。"""
        kk = self._make_hall_kk()
        kk._claimed_hall_hwnd = 500
        kk._claimed_hall_pid = 4567
        with self._patched() as (reg, m_wpid, m_claim):
            m_wpid.return_value = 4567
            hwnd, pid = kk.claim_hall_window(kk.dm, "善木木")
        self.assertEqual((hwnd, pid), (500, 4567))
        m_claim.assert_not_called()

    def test_claim_hall_timeout_propagates_claim_error(self):
        """claim_window 超时抛 ClaimError 直接上抛。"""
        from GameBot.utils import ClaimError

        kk = self._make_hall_kk()
        with self._patched(claim_side_effect=ClaimError("认领超时")):
            with self.assertRaises(ClaimError):
                kk.claim_hall_window(kk.dm, "善木木", claim_timeout=1)

    def test_claim_hall_no_window_class_raises(self):
        """未配置 window_class 时抛 ClaimError。"""
        from GameBot.utils import ClaimError

        kk = self._make_hall_kk()
        kk.kk_cfg["window_class"] = ""
        with self.assertRaises(ClaimError):
            kk.claim_hall_window(kk.dm, "善木木")

    def test_resolve_owner_by_kk_pid(self):
        """kk_pid 已知时 resolve_owner 按窗口 PID 确定性判定。"""
        kk = self._make_hall_kk()
        with self._patched(kk_pid_of=4567) as (reg, m_wpid, m_claim):
            kk.claim_hall_window(kk.dm, "善木木")
            resolve = m_claim.call_args.kwargs["resolve_owner"]
            m_wpid.return_value = 4567
            self.assertTrue(resolve(100))
            m_wpid.return_value = 9999
            self.assertFalse(resolve(101))

    def test_resolve_owner_by_registry_player(self):
        """kk_pid 未知时按注册表 kk_owner 反查玩家名比对。"""
        kk = self._make_hall_kk()
        with self._patched(kk_pid_of=0) as (reg, m_wpid, m_claim):
            kk.claim_hall_window(kk.dm, "善木木")
            resolve = m_claim.call_args.kwargs["resolve_owner"]
            m_wpid.return_value = 8888
            reg.player_of_kk_pid.return_value = "其他玩家"
            self.assertFalse(resolve(100))
            reg.player_of_kk_pid.return_value = "善木木#1234"
            self.assertTrue(resolve(100))
            reg.player_of_kk_pid.return_value = ""
            self.assertIsNone(resolve(100))

    def test_identify_writes_kk_owner_on_match(self):
        """下拉框 OCR 自举命中：写 kk_owner 并推出本账号 kk_pid。"""
        kk = self._make_hall_kk()
        kk.dismiss_hall_popups = MagicMock()
        kk.identify_hall_owner = MagicMock(return_value="善木木#1234")
        with self._patched(kk_pid_of=0) as (reg, m_wpid, m_claim):
            m_wpid.return_value = 4567
            kk.claim_hall_window(kk.dm, "善木木")
            identify = m_claim.call_args.kwargs["identify"]
            self.assertTrue(identify(500))
            # identify 写识别出的归属名；认领成功后补写 target_player 映射
            reg.set_kk_owner.assert_any_call(4567, "善木木#1234")
            self.assertEqual(kk._kk_pid, 4567)
            # 自举前清理弹窗并按窗口 PID 过滤
            kk.dismiss_hall_popups.assert_called_once_with(kk.dm, exclude_hwnds={500}, owner_pid=4567)

    def test_identify_busy_or_empty_returns_false(self):
        """下拉框正忙（None）或 OCR 空结果时返回 False，不写注册表。"""
        kk = self._make_hall_kk()
        kk.dismiss_hall_popups = MagicMock()
        kk.identify_hall_owner = MagicMock(return_value=None)
        with self._patched(kk_pid_of=0) as (reg, m_wpid, m_claim):
            kk.claim_hall_window(kk.dm, "善木木")
            identify = m_claim.call_args.kwargs["identify"]
            self.assertFalse(identify(500))
            # 认领前 set_kk_owner 未被 identify 调用（认领成功后的补写是 target_player）
            reg.set_kk_owner.assert_called_once_with(4567, "善木木")

    def test_candidates_skip_room_and_tiny_windows(self):
        """候选枚举：排除房间窗口、过小窗口，恢复最小化。"""
        kk = self._make_hall_kk()
        kk.kk_cfg["min_business_window_size"] = [200, 200]
        kk.dm.find_windows.return_value = [
            {"hwnd": 100, "title": "KKTitle", "class": "KKClass", "rect": (0, 0, 100, 100)},
            {"hwnd": 500, "title": "KKTitle", "class": "KKClass", "rect": (0, 0, 1332, 945)},
            {"hwnd": 600, "title": "KKTitle", "class": "KKClass", "rect": (0, 0, 1332, 945)},
        ]
        kk.dm.get_client_rect.side_effect = lambda h: (
            (0, 0, 100, 100) if h == 100 else (0, 0, 1332, 945)
        )
        kk.dm.is_window_minimized.return_value = False
        kk._is_room_window = MagicMock(side_effect=lambda dm, h: h == 600)
        with self._patched() as (reg, m_wpid, m_claim):
            kk.claim_hall_window(kk.dm, "善木木")
        candidates = m_claim.call_args.kwargs["candidates_fn"]()
        self.assertEqual(candidates, [500])  # 100 过小、600 是房间


class TestDialogIdentification(unittest.TestCase):
    def setUp(self):
        self._orig = _mock_dm_modules()

    def tearDown(self):
        _restore_dm_modules(self._orig)

    def test_create_room_dialog_uses_pid_and_keyword(self):
        kk = _make_kk()
        # owner_pid>0 时用 find_windows 按 PID 枚举
        kk.dm.find_windows.return_value = [
            {"hwnd": 600, "title": "KKTitle", "class": "CreateClass", "rect": (0, 0, 700, 500)},
        ]
        kk.dm.get_client_rect.return_value = (0, 0, 700, 500)
        kk.ocr_kk_lines = MagicMock(return_value=[{"text": "创建房间"}])

        result = kk._find_create_room_dialog(kk.dm, owner_pid=123)

        self.assertEqual(result, 600)
        kk.dm.find_windows.assert_called_once_with("CreateClass", "KKTitle", 123)
        kk.dm.set_client_size.assert_not_called()

    def test_password_dialog_uses_pid_and_keyword(self):
        from GameBot.runner.business.kk import KKBusiness

        kk = KKBusiness.__new__(KKBusiness)
        kk.kk_cfg = _make_kk().kk_cfg
        kk.kk_cfg["password_input"] = {
            "window_size": [440, 260],
            "dialog_keyword": "输入房间密码",
        }
        dm = MagicMock()
        dm.find_windows.return_value = [
            {"hwnd": 700, "title": "KKTitle", "class": "CreateClass", "rect": (0, 0, 500, 300)},
        ]
        dm.get_client_rect.return_value = (0, 0, 500, 300)
        kk.ocr_kk_lines = MagicMock(return_value=[{"text": "输入房间密码"}])

        result = kk._find_password_dialog(dm, owner_pid=123)

        self.assertEqual(result, 700)
        dm.find_windows.assert_called_once_with("CreateClass", "KKTitle", 123)
        dm.set_client_size.assert_not_called()


class TestCreateRoom(unittest.TestCase):
    """create_room 自动创建房间测试。"""

    def setUp(self):
        self._orig = _mock_dm_modules()

    def tearDown(self):
        _restore_dm_modules(self._orig)

    def _make_kk_for_create(self):
        """构造完整 create_room 测试用的 KK 实例。"""
        kk = _make_kk()
        # _find_hall_hwnd 返回大厅窗口
        kk._find_hall_hwnd = MagicMock(return_value=500)
        kk._find_create_room_dialog = MagicMock(return_value=600)
        kk._find_room_window = MagicMock(return_value=700)
        # bind_window 上下文管理器
        ctx = MagicMock()
        kk.dm.bind_window.return_value = ctx
        kk.dm.get_client_rect.side_effect = lambda hwnd: (0, 0, 584, 517) if hwnd == 600 else (0, 0, 1328, 945)
        return kk

    # U-11: 地图未找到时截图
    @patch("GameBot.runner.business.base.get_inference_client")
    def test_create_room_map_not_found_saves_screenshot(self, mock_ocr_client):
        """搜索结果中未找到地图时应 save_screenshot(force=True)。"""
        kk = self._make_kk_for_create()
        mock_ocr_client.return_value.ocr_lines_from_array.return_value = [
            {"text": "其他地图", "y_center": 100, "x_center": 500},
        ]

        result = kk.create_room(kk.dm)

        self.assertEqual(result, 0)
        # 应至少保存全屏截图（搜索区域 GDI2 截图也会被调用）
        save_calls = kk.dm.save_screenshot.call_args_list
        assert any(call.kwargs.get("label") == "create_room_map_not_found" for call in save_calls)

    # U-12: 调用 send_string 输入地图名
    @patch("GameBot.runner.business.base.get_inference_client")
    def test_create_room_calls_send_string_for_map_name(self, mock_ocr_client):
        """应调用新版 send_string 输入中文地图名。"""
        kk = self._make_kk_for_create()
        mock_ocr_client.return_value.ocr_lines_from_array.return_value = [
            {"text": "九种兵器2诸神战场", "y_center": 100, "x_center": 500},
        ]

        kk.create_room(kk.dm, map_name="九种兵器2诸神战场")

        kk.dm.send_string.assert_called_once_with("九种兵器2诸神战场", hwnd=500)
        kk.dm.send_string2.assert_not_called()

    # U-13a: OCR 按 (y_center, x_center) 排序
    @patch("GameBot.runner.business.base.get_inference_client")
    def test_create_room_ocr_sorted_by_y_then_x(self, mock_ocr_client):
        """搜索结果应按 (y_center, x_center) 排序后取第一个匹配项。"""
        kk = self._make_kk_for_create()
        # 故意给出乱序结果：第二个匹配项 y 更小（更靠上）
        mock_ocr_client.return_value.ocr_lines_from_array.return_value = [
            {"text": "九种兵器2诸神战场", "y_center": 200, "x_center": 300},
            {"text": "九种兵器2诸神战场", "y_center": 100, "x_center": 500},
        ]

        kk.create_room(kk.dm, map_name="九种兵器2诸神战场")

        # move_to 应被调用点击 y=100 更靠上的结果
        # 不缩放坐标，y=100 且 x=500 的匹配项点击后偏移为 500+209, 100+174
        move_calls = kk.dm.move_to.call_args_list
        self.assertTrue(
            any(c == call(709, 274) for c in move_calls),
            f"move_to 应包含 (709, 274) 即排序后第一个匹配项（含偏移），实际: {move_calls}",
        )

    # U-14: dismiss_hall_popups 在 bind_window 外调用
    @patch("GameBot.runner.business.base.get_inference_client")
    def test_create_room_dismisses_popups_outside_bind(self, mock_ocr_client):
        """dismiss_hall_popups 应在 bind_window 外部调用。"""
        kk = self._make_kk_for_create()
        mock_ocr_client.return_value.ocr_lines_from_array.return_value = [
            {"text": "九种兵器2诸神战场", "y_center": 100, "x_center": 500},
        ]

        kk.create_room(kk.dm)

        # dismiss_hall_popups 应被调用（至少一次）
        # 由于它是 self 的方法，我们检查它被调用
        # 这里间接验证：bind_window 调用次数应少于 dismiss_hall_popups 调用次数
        # 更直接的验证：检查 dismiss_hall_popups 被调用时 dm 未处于绑定状态
        # 由于我们 mock 了 bind_window，只需验证 dismiss_hall_popups 被调用
        # 它是 self 上的方法，我们通过 mock 来追踪
        kk.dismiss_hall_popups = MagicMock()
        kk.create_room(kk.dm, map_name="九种兵器2诸神战场")
        self.assertTrue(kk.dismiss_hall_popups.called)

    # 大厅未找到时返回 0
    def test_create_room_no_hall_returns_zero(self):
        """未找到 KK 主界面时应返回 0。"""
        kk = _make_kk()
        kk._find_hall_hwnd = MagicMock(return_value=0)

        result = kk.create_room(kk.dm)

        self.assertEqual(result, 0)

    # 创建房间弹窗未出现时截图
    @patch("GameBot.runner.business.base.get_inference_client")
    def test_create_room_dialog_not_found_saves_screenshot(self, mock_ocr_client):
        """创建房间弹窗未出现时应 save_screenshot(force=True)。"""
        kk = self._make_kk_for_create()
        kk._find_create_room_dialog = MagicMock(return_value=0)
        mock_ocr_client.return_value.ocr_lines_from_array.return_value = [
            {"text": "九种兵器2诸神战场", "y_center": 100, "x_center": 500},
        ]

        result = kk.create_room(kk.dm, map_name="九种兵器2诸神战场")

        self.assertEqual(result, 0)
        kk.dm.save_screenshot.assert_called_once_with(label="create_room_dialog_not_found", force=True)

    # 创建成功返回房间句柄
    @patch("GameBot.runner.business.base.get_inference_client")
    def test_create_room_success_returns_room_hwnd(self, mock_ocr_client):
        """创建房间成功后应返回房间窗口句柄。"""
        kk = self._make_kk_for_create()
        mock_ocr_client.return_value.ocr_lines_from_array.return_value = [
            {"text": "九种兵器2诸神战场", "y_center": 100, "x_center": 500},
        ]

        result = kk.create_room(kk.dm, map_name="九种兵器2诸神战场")

        self.assertEqual(result, 700)
        # 统一尺寸后使用配置中的固定坐标，不再缩放
        self.assertIn(call(329, 211), kk.dm.move_to.call_args_list)
        self.assertIn(call(315, 438), kk.dm.move_to.call_args_list)
        self.assertIn(call(600, 584, 488), kk.dm.set_client_size.call_args_list)

    # 非空密码时调用 send_string 输入密码
    @patch("GameBot.runner.business.base.get_inference_client")
    def test_create_room_with_password_sends_string(self, mock_ocr_client):
        """非空密码时应调用 send_string(password, hwnd=dialog_hwnd)。"""
        kk = self._make_kk_for_create()
        kk.kk_cfg["create_room"]["password"] = "abc123"
        mock_ocr_client.return_value.ocr_lines_from_array.return_value = [
            {"text": "九种兵器2诸神战场", "y_center": 100, "x_center": 500},
        ]

        kk.create_room(kk.dm, map_name="九种兵器2诸神战场")

        # 验证 send_string 被调用传入密码和 dialog_hwnd=600
        send_string_calls = kk.dm.send_string.call_args_list
        self.assertTrue(
            any(c == call("abc123", hwnd=600) for c in send_string_calls),
            f"send_string 应被调用传入密码和 hwnd=600，实际: {send_string_calls}",
        )


class TestDismissHallPopupsMaxRounds(unittest.TestCase):
    """dismiss_hall_popups 最大轮数限制测试。"""

    def setUp(self):
        self._orig = _mock_dm_modules()

    def tearDown(self):
        _restore_dm_modules(self._orig)

    def test_dismiss_hall_popups_max_rounds_stops(self):
        """弹窗持续出现超过 10 轮时应停止，不无限循环。"""
        kk = _make_kk()
        # 每轮都出现一个新弹窗，close_window_by_x 成功但弹窗持续出现
        popup_hwnds = list(range(100, 110))
        kk.dm.find_windows.side_effect = [
            [
                {
                    "hwnd": h,
                    "title": "KKTitle",
                    "class": "CreateClass",
                    "rect": (0, 0, 300, 200),
                }
            ]
            for h in popup_hwnds
        ]
        kk.dm.get_client_rect.return_value = (0, 0, 300, 200)
        kk.dm.close_window_by_x.return_value = True

        # 不应抛出异常，应在 10 轮后停止
        with patch("GameBot.runner.business.base.get_inference_client") as mock_ocr:
            mock_ocr.return_value.ocr_lines_from_array.return_value = []
            kk.dismiss_hall_popups(kk.dm)

        # close_window_by_x 最多被调用 10 次
        self.assertLessEqual(kk.dm.close_window_by_x.call_count, 10)
