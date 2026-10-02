"""WindowManagerMixin quit_game 测试。

覆盖：
- U-06: quit_game 在已绑定上下文内发送 F10/E/Q
- U-07: quit_game 检测结算页面，出现时按回车，未出现时不按回车
"""

import sys
import unittest
from contextlib import ExitStack, contextmanager
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


_WM = "GameBot.runner.business.war3.window_manager"


class TestClaimWar3Window(unittest.TestCase):
    """claim_war3_window 新认领协议测试（注册表 + 直接父进程 PPID 比对 + token 自举）。

    claim_window 原语、window_pid/parent_pid、注册表均 mock，只测 mixin 侧接线：
    resolve/identify 回调行为、kk_pid 推出与 kk_owner 写回。
    """

    def setUp(self):
        self._orig = _mock_dm_modules()

    def tearDown(self):
        _restore_dm_modules(self._orig)

    def _make_war3(self):
        war3 = _make_war3()
        war3.war3_cfg["multi_instance"] = {"claim_timeout": 5, "claim_retry_interval": 0.01}
        war3._claimed_hwnd = 0
        war3._claimed_mutex = None
        war3.claimed_owner = ""
        war3._kk_pid = 0
        war3.task_name = ""
        war3.target_player = ""
        return war3

    @contextmanager
    def _patched(self, kk_pid=0, claim_return=None, claim_side_effect=None):
        reg = MagicMock()
        reg.kk_pid_of.return_value = kk_pid
        with ExitStack() as stack:
            stack.enter_context(patch(f"{_WM}.ensure_registered", return_value=reg))
            stack.enter_context(patch(f"{_WM}.self_kk_pid", return_value=kk_pid))
            m_wpid = stack.enter_context(patch(f"{_WM}.window_pid"))
            m_ppid = stack.enter_context(patch(f"{_WM}.parent_pid"))
            m_claim = stack.enter_context(patch(f"{_WM}.claim_window"))
            if claim_side_effect is not None:
                m_claim.side_effect = claim_side_effect
            else:
                m_claim.return_value = claim_return if claim_return is not None else (700, MagicMock())
            yield reg, m_wpid, m_ppid, m_claim

    def test_claim_returns_hwnd_and_caches(self):
        """认领成功返回 hwnd 并缓存窗口锁。"""
        war3 = self._make_war3()
        mutex = MagicMock()
        with self._patched(claim_return=(700, mutex)):
            hwnd = war3.claim_war3_window("善木木")
        self.assertEqual(hwnd, 700)
        self.assertEqual(war3._claimed_hwnd, 700)
        self.assertEqual(war3._claimed_mutex, mutex)
        self.assertEqual(war3.claimed_owner, "善木木")

    def test_resolve_matches_parent_kk_pid(self):
        """kk_pid 已知：ppid(war3_pid) == kk_pid 判 True，否则 False。"""
        war3 = self._make_war3()
        with self._patched(kk_pid=4567) as (reg, m_wpid, m_ppid, m_claim):
            war3.claim_war3_window("善木木")
            resolve = m_claim.call_args.kwargs["resolve_owner"]
            m_wpid.return_value = 9000
            m_ppid.return_value = 4567
            self.assertTrue(resolve(100))
            m_ppid.return_value = 8888
            self.assertFalse(resolve(100))
            reg.player_of_kk_pid.assert_not_called()

    def test_resolve_unknown_kk_pid_uses_registry(self):
        """kk_pid 未知：按 ppid 反查注册表 kk_owner 玩家名比对。"""
        war3 = self._make_war3()
        with self._patched(kk_pid=0) as (reg, m_wpid, m_ppid, m_claim):
            war3.claim_war3_window("善木木")
            resolve = m_claim.call_args.kwargs["resolve_owner"]
            m_wpid.return_value = 9000
            m_ppid.return_value = 4567
            reg.player_of_kk_pid.return_value = "善木木"
            self.assertTrue(resolve(100))
            reg.player_of_kk_pid.return_value = "其他玩家"
            self.assertFalse(resolve(100))
            reg.player_of_kk_pid.return_value = ""
            self.assertIsNone(resolve(100))
            # ppid 查询失败 → 未知 → 转 identify
            m_ppid.return_value = 0
            self.assertIsNone(resolve(100))

    def test_identify_token_match_writes_kk_owner(self):
        """聊天 token 自举命中：写 kk_owner 并由 ppid 推出本账号 kk_pid。"""
        war3 = self._make_war3()
        war3._identify_owner_by_chat = MagicMock(return_value="善木木")
        with self._patched(kk_pid=0) as (reg, m_wpid, m_ppid, m_claim):
            war3.claim_war3_window("善木木")
            identify = m_claim.call_args.kwargs["identify"]
            m_wpid.return_value = 9000
            m_ppid.return_value = 4567
            self.assertTrue(identify(700))
            reg.set_kk_owner.assert_called_once_with(4567, "善木木")
            self.assertEqual(war3._kk_pid, 4567)

    def test_identify_token_mismatch_returns_false(self):
        """聊天 token 归属他人：写 kk_owner 记录归属，返回 False。"""
        war3 = self._make_war3()
        war3._identify_owner_by_chat = MagicMock(return_value="其他玩家")
        with self._patched(kk_pid=0) as (reg, m_wpid, m_ppid, m_claim):
            war3.claim_war3_window("善木木")
            identify = m_claim.call_args.kwargs["identify"]
            m_wpid.return_value = 9000
            m_ppid.return_value = 4567
            self.assertFalse(identify(700))
            reg.set_kk_owner.assert_called_once_with(4567, "其他玩家")
            self.assertEqual(war3._kk_pid, 0)

    def test_claim_timeout_raises_claim_error(self):
        """认领超时抛 ClaimError。"""
        from GameBot.utils import ClaimError

        war3 = self._make_war3()
        with self._patched(claim_side_effect=ClaimError("认领超时")):
            with self.assertRaises(ClaimError):
                war3.claim_war3_window("善木木", claim_timeout=1)

    def test_empty_target_resolves_true(self):
        """target_player 为空时 resolve 恒 True。"""
        war3 = self._make_war3()
        with self._patched() as (reg, m_wpid, m_ppid, m_claim):
            war3.claim_war3_window("")
            resolve = m_claim.call_args.kwargs["resolve_owner"]
            self.assertTrue(resolve(100))

    def test_release_and_reacquire(self):
        """release_war3_claim 释放锁、清缓存句柄、清注册表记录，随后可重新认领。"""
        war3 = self._make_war3()
        mutex = MagicMock()
        reg = MagicMock()
        with self._patched(claim_return=(700, mutex)):
            hwnd = war3.claim_war3_window("善木木")
        self.assertEqual(hwnd, 700)
        war3._claim_registry_obj = reg
        war3.release_war3_claim()
        mutex.release.assert_called_once()
        self.assertEqual(war3._claimed_hwnd, 0)
        self.assertEqual(war3.claimed_owner, "")
        reg.release_window.assert_called_once_with("war3", 700)
