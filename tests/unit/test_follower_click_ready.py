"""TeamFollower _click_ready 单元测试。

覆盖：
- 按钮文本含"取消准备" → 跳过点击
- 按钮文本含"准备" → 点击准备
- 其他文本 → 默认点击
- OCR 为空 → 默认点击
"""

import os
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


class _MockFactory:
    def __new__(cls, *args, **kwargs):
        return MagicMock()


def _make_follower(tmp_path):
    """创建 TeamFollower 实例用于测试。"""
    originals = _mock_dm_modules()

    import GameBot.runner.team.base as base_mod

    old_dm = base_mod.create_dm_client
    old_kk = base_mod.KKBusiness
    old_war3 = base_mod.War3Business
    base_mod.create_dm_client = _MockFactory
    base_mod.KKBusiness = _MockFactory
    base_mod.War3Business = _MockFactory

    from GameBot.runner.team.follower import TeamFollower
    from GameBot.runner.team.ipc import TeamIPC

    cfg = {
        "war3": {"client_size": [1902, 1033], "key_time": 0.05, "general_time": 0.3},
        "hero": {"inventory": []},
        "kk": {
            "room": {
                "window_size": [1224, 904],
                "ready_button_coords": [800, 850],
                "ready_keyword": "已准备",
                "not_ready_keyword": "未准备",
                "start_button_ocr_area_coords": [50, 100, 800, 600],
            },
            "bind": {},
        },
        "team": {
            "team_task": {
                "rounds": 0,
                "tasks": {"test_mod": "team_test_mod.test_task"},
                "sync": {"progress_report_interval": 2},
                "members": [
                    {"role": "leader", "target_player": "leader_player"},
                    {"role": "follower", "target_player": "my_player", "task": "test_mod", "steps": []},
                ],
            }
        },
    }
    member_cfg = {
        "role": "follower",
        "target_player": "my_player",
    }

    ipc = TeamIPC("test_click_ready", os.path.join(tmp_path, "ipc"))
    stop_event = __import__("threading").Event()
    follower = TeamFollower(
        cfg=cfg,
        member_cfg=member_cfg,
        ipc=ipc,
        sync_source="leader_player",
        follower_index=0,
        stop_event=stop_event,
    )
    follower.dm = MagicMock()
    follower.dm.get_client_rect.return_value = (0, 0, 1224, 904)
    follower.war3 = MagicMock()
    follower.kk = MagicMock()
    follower.kk._compute_kk_ocr_bbox = MagicMock(return_value=(50, 100, 800, 600))
    # 默认返回空 OCR 行，各测试方法覆盖具体场景
    follower.kk.ocr_kk_lines.return_value = []

    # bind_window 返回上下文管理器
    ctx = MagicMock()
    follower.dm.bind_window.return_value = ctx

    follower._originals = originals
    follower._old_modules = (base_mod, old_dm, old_kk, old_war3)
    return follower


def _cleanup_follower(follower):
    base_mod, old_dm, old_kk, old_war3 = follower._old_modules
    base_mod.create_dm_client = old_dm
    base_mod.KKBusiness = old_kk
    base_mod.War3Business = old_war3
    _restore_dm_modules(follower._originals)


class TestFollowerKKOwnership(unittest.TestCase):
    def setUp(self):
        import tempfile

        self._tmp = tempfile.mkdtemp()
        self.follower = _make_follower(self._tmp)

    def tearDown(self):
        _cleanup_follower(self.follower)

    def test_claim_failure_stops_before_room_lookup(self):
        self.follower._claim_hall_window = MagicMock(return_value=False)

        result = self.follower.kk_phase(round_num=1)

        self.assertFalse(result)
        # 认领失败仅做一次房间残留探测（诊断），不进入等待房间信息/加入房间流程
        self.follower.kk.dismiss_room_popups.assert_called_once_with(self.follower.dm, owner_pid=0)
        self.follower.kk.join_room_by_id.assert_not_called()

    def test_joined_room_reports_recovered_round(self):
        def claim():
            self.follower.owner_pid = 123
            self.follower.hall_hwnd = 500
            return True

        def wait_room_info(round_num):
            self.follower._current_round = 4
            return {"round": 4, "room_id": "888", "password": "", "map_name": "test"}

        self.follower._claim_hall_window = MagicMock(side_effect=claim)
        self.follower.kk.dismiss_room_popups.side_effect = [0, 0]
        self.follower._wait_for_room_info = MagicMock(side_effect=wait_room_info)
        self.follower.kk.join_room_by_id.return_value = 700
        self.follower._click_ready = MagicMock(return_value=True)
        self.follower._report_progress = MagicMock()

        result = self.follower.kk_phase(round_num=1)

        self.assertTrue(result)
        self.follower._report_progress.assert_called_once_with(state="ready", round_num=4)

    def test_existing_room_recovers_round_before_ready(self):
        def claim():
            self.follower.owner_pid = 123
            return True

        self.follower._claim_hall_window = MagicMock(side_effect=claim)
        self.follower.kk.dismiss_room_popups.return_value = 700
        self.follower._wait_for_room_info = MagicMock(return_value={"round": 4})
        self.follower._click_ready = MagicMock(return_value=True)

        result = self.follower.kk_phase(round_num=1)

        self.assertTrue(result)
        self.follower.kk.dismiss_room_popups.assert_called_once_with(self.follower.dm, owner_pid=123)
        self.follower._wait_for_room_info.assert_called_once_with(1)


class TestClickReadyReadyState(unittest.TestCase):
    """_click_ready 准备状态测试。"""

    def setUp(self):
        import tempfile

        self._tmp = tempfile.mkdtemp()
        self.follower = _make_follower(self._tmp)

    def tearDown(self):
        _cleanup_follower(self.follower)

    def test_already_ready_skips_click(self):
        """按钮文本含 ready_keyword 时跳过点击。"""
        self.follower.kk.ocr_kk_lines.return_value = [
            {"text": "已准备"},
        ]

        self.follower._click_ready(room_hwnd=700)

        self.follower.dm.left_down.assert_not_called()
        self.follower.dm.left_up.assert_not_called()

    def test_not_ready_clicks_once(self):
        """按钮文本含 not_ready_keyword 时点击一次准备，不依赖 OCR 后验。"""
        self.follower.kk.ocr_kk_lines.return_value = [
            {"text": "未准备"},
        ]

        self.follower._click_ready(room_hwnd=700)

        self.follower.dm.left_down.assert_called_once()
        self.follower.dm.left_up.assert_called_once()

    def test_unknown_state_defaults_to_click(self):
        """按钮文本无法识别时默认点击准备。"""
        self.follower.kk.ocr_kk_lines.return_value = [
            {"text": "some other text"},
        ]

        self.follower._click_ready(room_hwnd=700)

        self.follower.dm.left_down.assert_called_once()
        self.follower.dm.left_up.assert_called_once()

    def test_empty_ocr_defaults_to_click(self):
        """OCR 完全无结果时默认点击准备。"""
        self.follower.kk.ocr_kk_lines.return_value = []

        self.follower._click_ready(room_hwnd=700)

        self.follower.dm.left_down.assert_called_once()
        self.follower.dm.left_up.assert_called_once()
