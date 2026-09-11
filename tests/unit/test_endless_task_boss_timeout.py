"""EndlessTask do_war3 BossDeathTimeoutError 测试 + EndlessSingleTask 测试。

覆盖：
- U-20: do_war3 捕获 BossDeathTimeoutError 后 quit_game 并返回 False
- U-19: do_kk 无房间时调用 create_room（已在 test_war3_bot_improvements.py 中覆盖）
- U-21: endless_single 捕获 BossDeathTimeoutError 后 quit_game
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


class TestDoWar3BossTimeout(unittest.TestCase):
    """EndlessTask.do_war3 BossDeathTimeoutError 处理测试。"""

    def setUp(self):
        self._orig = _mock_dm_modules()

    def tearDown(self):
        _restore_dm_modules(self._orig)

    def _make_task(self):
        from GameBot.runner.tasks.war3.jiubing2.endless.endless import EndlessTask

        task = EndlessTask.__new__(EndlessTask)
        task.dm = MagicMock()
        task.war3 = MagicMock()
        task.runner = MagicMock()
        task.ui = MagicMock()
        task.nav = MagicMock()
        task.kk = MagicMock()
        task.endless_cfg = {"loop_interval_time": 0}
        task.war3_cfg = {"window_class": "War3Class", "window_title": "War3Title"}
        task._stop_event = None
        return task

    # U-20: BossDeathTimeoutError 触发 quit_game 并返回 False
    @patch("GameBot.runner.tasks.war3.jiubing2.endless.endless.time")
    def test_do_war3_catches_boss_timeout_quits_game(self, mock_time):
        """BossDeathTimeoutError 应触发 quit_game 并返回 False。"""
        from GameBot.runner.business.war3.jiubing2.endless_runner import BossDeathTimeoutError

        task = self._make_task()
        task.war3.wait_for_game_window.return_value = 123
        # bind_window 上下文管理器
        ctx = MagicMock()
        task.dm.bind_window.return_value = ctx
        # start_endless 抛出 BossDeathTimeoutError
        task.runner.start_endless.side_effect = BossDeathTimeoutError("超时")

        result = task.do_war3(1)

        self.assertFalse(result)
        task.war3.quit_game.assert_called_once()

    # 正常完成时也应调用 quit_game
    @patch("GameBot.runner.tasks.war3.jiubing2.endless.endless.time")
    def test_do_war3_normal_complete_quits_game(self, mock_time):
        """正常完成时也应调用 quit_game。"""
        task = self._make_task()
        task.war3.wait_for_game_window.return_value = 123
        ctx = MagicMock()
        task.dm.bind_window.return_value = ctx
        task.runner.start_endless.return_value = None  # 正常完成

        result = task.do_war3(1)

        self.assertTrue(result)
        task.war3.quit_game.assert_called_once()

    # WindowLostError 时不调用 quit_game（窗口已消失）
    def test_do_war3_window_lost_no_quit(self):
        """WindowLostError 时不调用 quit_game（窗口已消失）。"""
        from GameBot.utils import WindowLostError

        task = self._make_task()
        task.kk_cfg = {"create_room_window_class": "CreateClass", "window_title": "KKTitle"}
        task.war3.wait_for_game_window.return_value = 123
        ctx = MagicMock()
        task.dm.bind_window.return_value = ctx
        task.runner.start_endless.side_effect = WindowLostError("窗口消失")

        result = task.do_war3(1)

        self.assertFalse(result)
        task.war3.quit_game.assert_not_called()

    # 多开：target_player 匹配时正常继续
    @patch("GameBot.runner.tasks.war3.jiubing2.endless.endless.time")
    def test_do_war3_multi_instance_owner_matches(self, mock_time):
        """target_player 匹配时应正常继续，不调用 _find_target_war3_hwnd。"""
        task = self._make_task()
        task.endless_cfg = {"loop_interval_time": 0, "target_player": "Player1"}
        task.war3.wait_for_game_window.return_value = 123
        task.war3.identify_war3_owner.return_value = "Player1"
        task._find_target_war3_hwnd = MagicMock()
        ctx = MagicMock()
        task.dm.bind_window.return_value = ctx

        result = task.do_war3(1)

        self.assertTrue(result)
        task._find_target_war3_hwnd.assert_not_called()

    # 多开：target_player 不匹配但找到目标窗口
    @patch("GameBot.runner.tasks.war3.jiubing2.endless.endless.time")
    def test_do_war3_multi_instance_owner_mismatch_finds_target(self, mock_time):
        """target_player 不匹配但 _find_target_war3_hwnd 找到目标时应使用目标窗口。"""
        task = self._make_task()
        task.endless_cfg = {"loop_interval_time": 0, "target_player": "Player2"}
        task.war3.wait_for_game_window.return_value = 123
        task.war3.identify_war3_owner.return_value = "Player1"
        task._find_target_war3_hwnd = MagicMock(return_value=456)
        ctx = MagicMock()
        task.dm.bind_window.return_value = ctx

        result = task.do_war3(1)

        self.assertTrue(result)
        task.war3.set_client_size.assert_called_once_with(456)

    # 多开：target_player 不匹配且未找到目标窗口
    def test_do_war3_multi_instance_owner_mismatch_no_target(self):
        """target_player 不匹配且 _find_target_war3_hwnd 未找到时应 quit_game 并返回 False。"""
        task = self._make_task()
        task.endless_cfg = {"loop_interval_time": 0, "target_player": "Player2"}
        task.war3.wait_for_game_window.return_value = 123
        task.war3.identify_war3_owner.return_value = "Player1"
        task._find_target_war3_hwnd = MagicMock(return_value=0)

        result = task.do_war3(1)

        self.assertFalse(result)
        task.war3.quit_game.assert_called_once()


class TestEndlessSingleBossTimeout(unittest.TestCase):
    """EndlessSingleTask BossDeathTimeoutError 处理测试。"""

    def setUp(self):
        self._orig = _mock_dm_modules()

    def tearDown(self):
        _restore_dm_modules(self._orig)

    # U-21: 单局任务超时停止但不退出 War3
    @patch("GameBot.runner.tasks.war3.jiubing2.endless.endless_single.time")
    def test_run_catches_boss_timeout_no_quit(self, mock_time):
        """单局任务捕获 BossDeathTimeoutError 后应停止任务，但不退出 War3。"""
        from GameBot.runner.business.war3.jiubing2.endless_runner import BossDeathTimeoutError
        from GameBot.runner.tasks.war3.jiubing2.endless.endless_single import EndlessSingleTask

        task = EndlessSingleTask.__new__(EndlessSingleTask)
        task.dm = MagicMock()
        task.war3 = MagicMock()
        task.runner = MagicMock()
        task.ui = MagicMock()
        task.endless_cfg = {}
        task.war3_cfg = {"window_class": "War3Class", "window_title": "War3Title"}
        task._stop_event = None
        task._progress_callback = MagicMock()

        task.dm.get_active_window.return_value = 123
        ctx = MagicMock()
        task.dm.bind_window.return_value = ctx
        task.runner.clear_endless_monster_loop.side_effect = BossDeathTimeoutError("超时")

        # 不应重新抛出异常
        task.run()

        task.war3.quit_game.assert_not_called()

    # 单局无尽正常完成时不退出 War3
    @patch("GameBot.runner.tasks.war3.jiubing2.endless.endless_single.time")
    def test_run_normal_complete_no_quit(self, mock_time):
        """单局无尽正常完成时不应调用 quit_game。"""
        from GameBot.runner.tasks.war3.jiubing2.endless.endless_single import EndlessSingleTask

        task = EndlessSingleTask.__new__(EndlessSingleTask)
        task.dm = MagicMock()
        task.war3 = MagicMock()
        task.runner = MagicMock()
        task.ui = MagicMock()
        task.endless_cfg = {}
        task.war3_cfg = {"window_class": "War3Class", "window_title": "War3Title"}
        task._stop_event = None
        task._progress_callback = MagicMock()

        task.dm.get_active_window.return_value = 123
        ctx = MagicMock()
        task.dm.bind_window.return_value = ctx
        task.runner.clear_endless_monster_loop.return_value = None

        task.run()

        task.war3.quit_game.assert_not_called()

    # StopTaskError 时不调用 quit_game
    @patch("GameBot.runner.tasks.war3.jiubing2.endless.endless_single.time")
    def test_run_stop_task_error_no_quit(self, mock_time):
        """StopTaskError 时不应调用 quit_game，正常结束任务。"""
        from GameBot.runner.tasks.war3.jiubing2.endless.endless_single import EndlessSingleTask
        from GameBot.utils import StopTaskError

        task = EndlessSingleTask.__new__(EndlessSingleTask)
        task.dm = MagicMock()
        task.war3 = MagicMock()
        task.runner = MagicMock()
        task.ui = MagicMock()
        task.endless_cfg = {}
        task.war3_cfg = {"window_class": "War3Class", "window_title": "War3Title"}
        task._stop_event = None
        task._progress_callback = MagicMock()

        task.dm.get_active_window.return_value = 123
        ctx = MagicMock()
        task.dm.bind_window.return_value = ctx
        task.runner.clear_endless_monster_loop.side_effect = StopTaskError("停止")

        task.run()

        task.war3.quit_game.assert_not_called()


class TestDoWar3TimeoutError(unittest.TestCase):
    """EndlessTask.do_war3 TimeoutError 处理测试。"""

    def setUp(self):
        self._orig = _mock_dm_modules()

    def tearDown(self):
        _restore_dm_modules(self._orig)

    def _make_task(self):
        from GameBot.runner.tasks.war3.jiubing2.endless.endless import EndlessTask

        task = EndlessTask.__new__(EndlessTask)
        task.dm = MagicMock()
        task.war3 = MagicMock()
        task.runner = MagicMock()
        task.ui = MagicMock()
        task.nav = MagicMock()
        task.kk = MagicMock()
        task.endless_cfg = {"loop_interval_time": 0}
        task.war3_cfg = {"window_class": "War3Class", "window_title": "War3Title"}
        task._stop_event = None
        return task

    @patch("GameBot.runner.tasks.war3.jiubing2.endless.endless.time")
    def test_do_war3_timeout_error_quits_game(self, mock_time):
        """TimeoutError 应触发 quit_game 并返回 False。"""
        task = self._make_task()
        task.war3.wait_for_game_window.return_value = 123
        ctx = MagicMock()
        task.dm.bind_window.return_value = ctx
        task.runner.start_endless.side_effect = TimeoutError("加载超时")

        result = task.do_war3(1)

        self.assertFalse(result)
        task.war3.quit_game.assert_called_once()


class TestFindTargetWar3Hwnd(unittest.TestCase):
    """War3Business.find_target_war3_hwnd 边界场景测试。

    _find_target_war3_hwnd 已从 EndlessTask 提取到 War3Business，
    本类测试公共方法行为。
    """

    def setUp(self):
        self._orig = _mock_dm_modules()

    def tearDown(self):
        _restore_dm_modules(self._orig)

    def _make_war3(self):
        from GameBot.runner.business.war3 import War3Business

        war3 = War3Business.__new__(War3Business)
        war3.dm = MagicMock()
        war3.war3_cfg = {"window_class": "War3Class", "window_title": "War3Title"}
        return war3

    def test_find_target_war3_hwnd_single_window(self):
        """仅一个 War3 窗口时应直接返回该窗口句柄。"""
        war3 = self._make_war3()
        war3.dm.find_windows.return_value = [{"hwnd": 123, "title": "War3Title", "class": "War3Class", "rect": (0, 0, 1920, 1080)}]
        war3.identify_war3_owner = MagicMock()

        result = war3.find_target_war3_hwnd("")

        self.assertEqual(result, 123)
        war3.identify_war3_owner.assert_not_called()

    def test_find_target_war3_hwnd_no_windows(self):
        """无 War3 窗口时应返回 0。"""
        war3 = self._make_war3()
        war3.dm.find_windows.return_value = []

        result = war3.find_target_war3_hwnd("")

        self.assertEqual(result, 0)

    def test_find_target_war3_hwnd_multi_no_target_player(self):
        """多窗口但未配置 target_player 时应返回 0。"""
        war3 = self._make_war3()
        war3.dm.find_windows.return_value = [
            {"hwnd": 123, "title": "War3Title", "class": "War3Class", "rect": (0, 0, 1920, 1080)},
            {"hwnd": 456, "title": "War3Title", "class": "War3Class", "rect": (0, 0, 1920, 1080)},
        ]

        result = war3.find_target_war3_hwnd("")

        self.assertEqual(result, 0)

    def test_find_target_war3_hwnd_multi_with_target_match(self):
        """多窗口且 target_player 匹配时应返回匹配的窗口句柄。"""
        war3 = self._make_war3()
        war3.dm.find_windows.return_value = [
            {"hwnd": 123, "title": "War3Title", "class": "War3Class", "rect": (0, 0, 1920, 1080)},
            {"hwnd": 456, "title": "War3Title", "class": "War3Class", "rect": (0, 0, 1920, 1080)},
        ]
        war3.identify_war3_owner = MagicMock(side_effect=["Player1", "Player2"])

        result = war3.find_target_war3_hwnd("Player2")

        self.assertEqual(result, 456)

    def test_find_target_war3_hwnd_multi_no_match(self):
        """多窗口且 target_player 不匹配任何窗口时应返回 0。"""
        war3 = self._make_war3()
        war3.dm.find_windows.return_value = [
            {"hwnd": 123, "title": "War3Title", "class": "War3Class", "rect": (0, 0, 1920, 1080)},
            {"hwnd": 456, "title": "War3Title", "class": "War3Class", "rect": (0, 0, 1920, 1080)},
        ]
        war3.identify_war3_owner = MagicMock(side_effect=["Player1", "Player2"])

        result = war3.find_target_war3_hwnd("Player3")

        self.assertEqual(result, 0)
