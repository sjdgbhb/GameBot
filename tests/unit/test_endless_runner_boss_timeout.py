"""EndlessRunner BOSS 死亡超时测试。

覆盖：
- U-04: _wait_boss_dead 超时后 save_screenshot(force=True) + 抛出 BossDeathTimeoutError
- U-05: _wait_boss_dead 后台已检测到时设置 boss_death_time
- U-05b: _wait_boss_dead 后台未检测到但等待期间检测到时设置 boss_death_time
- U-06: 无 _prompt_text_cfg 时直接设置 boss_death_time（兜底）
"""

import sys
import threading
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


class TestWaitBossDead(unittest.TestCase):
    """EndlessRunner._wait_boss_dead 后台监测与超时测试。"""

    def setUp(self):
        self._orig = _mock_dm_modules()

    def tearDown(self):
        _restore_dm_modules(self._orig)

    def _make_runner(self):
        """构造 EndlessRunner 实例，跳过 __init__。"""
        from GameBot.runner.business.war3.jiubing2.endless_runner import EndlessRunner

        runner = EndlessRunner.__new__(EndlessRunner)
        runner.dm = MagicMock()
        runner._war3 = MagicMock()
        runner._prompt_text_cfg = {"area_coords": [0, 0, 100, 100]}
        return runner

    # U-04: 超时后截图并抛出异常
    @patch("GameBot.runner.business.war3.jiubing2.endless_runner.time")
    def test_wait_boss_dead_timeout_saves_screenshot_and_raises(self, mock_time):
        """后台未检测到且超时后应 save_screenshot(force=True) 并抛出 BossDeathTimeoutError。"""
        from GameBot.runner.business.war3.jiubing2.endless_runner import BossDeathTimeoutError

        runner = self._make_runner()
        # 模拟 time.time：首次返回 0（deadline=0+60），之后持续递增超过 timeout
        mock_time.time.side_effect = [0.0] + [100.0] * 10

        event = threading.Event()  # 不会被 set
        task = MagicMock()
        endless_cfg = {"boss_death_text": "开始挑战", "boss_death_timeout": 60}

        with self.assertRaises(BossDeathTimeoutError):
            runner._wait_boss_dead(task, endless_cfg, boss_death_event=event)

        runner.dm.save_screenshot.assert_called_once_with(label="boss_death_timeout", force=True)

    # U-05: 后台已检测到时设置 boss_death_time
    @patch("GameBot.runner.business.war3.jiubing2.endless_runner.time")
    def test_wait_boss_dead_already_detected_sets_boss_death_time(self, mock_time):
        """后台监测已检测到（event.is_set()）时应直接设置 task.boss_death_time。"""
        runner = self._make_runner()
        mock_time.time.return_value = 12345.0

        event = threading.Event()
        event.set()  # 模拟后台已检测到
        task = MagicMock()
        task.boss_death_time = 0
        endless_cfg = {"boss_death_text": "开始挑战", "boss_death_timeout": 60}

        runner._wait_boss_dead(task, endless_cfg, boss_death_event=event)

        self.assertEqual(task.boss_death_time, 12345.0)
        runner.dm.save_screenshot.assert_not_called()

    # U-05b: 后台在等待期间检测到时设置 boss_death_time
    @patch("GameBot.runner.business.war3.jiubing2.endless_runner.time")
    def test_wait_boss_dead_detected_during_wait_sets_boss_death_time(self, mock_time):
        """后台在等待期间检测到（event.wait 返回 True）时应设置 task.boss_death_time。"""
        runner = self._make_runner()
        mock_time.time.return_value = 12345.0

        event = threading.Event()
        # 模拟等待期间检测到：wait 返回 True，is_set 也返回 True
        event.wait = MagicMock(return_value=True)
        event.is_set = MagicMock(return_value=True)
        task = MagicMock()
        task.boss_death_time = 0
        endless_cfg = {"boss_death_text": "开始挑战", "boss_death_timeout": 60}

        runner._wait_boss_dead(task, endless_cfg, boss_death_event=event)

        self.assertEqual(task.boss_death_time, 12345.0)
        runner.dm.save_screenshot.assert_not_called()

    # U-06: 无 _prompt_text_cfg 时直接设置 boss_death_time
    @patch("GameBot.runner.business.war3.jiubing2.endless_runner.time")
    def test_wait_boss_dead_no_prompt_cfg_sets_time(self, mock_time):
        """无 _prompt_text_cfg 时应直接设置 boss_death_time（兜底）。"""
        runner = self._make_runner()
        runner._prompt_text_cfg = None
        mock_time.time.return_value = 99999.0

        task = MagicMock()
        task.boss_death_time = 0
        endless_cfg = {"boss_death_text": "开始挑战", "boss_death_timeout": 60}

        runner._wait_boss_dead(task, endless_cfg)

        self.assertEqual(task.boss_death_time, 99999.0)
