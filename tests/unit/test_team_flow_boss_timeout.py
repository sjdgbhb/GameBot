"""endless_single.run_task BossDeathTimeoutError 处理测试。

覆盖：
- 同步源捕获 BossDeathTimeoutError 后标记 _flow_failed=True
- 非同步源捕获 BossDeathTimeoutError 后也标记 _flow_failed=True
- 正常完成时不标记 _flow_failed
"""

import sys
import threading
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


def _make_member(is_sync_source=True):
    """构造 mock member 对象，模拟 TeamMemberBase 的必要属性。"""
    member = MagicMock()
    member.is_sync_source = is_sync_source
    member._current_round = 1
    member._flow_failed = False
    member.task_ctx = MagicMock()
    member.task_cfg = {
        "war3": {"jiubing2": {"tasks": {"endless": {"endless_single": {"min_level": 1, "max_level": 1}}}}}
    }
    return member


class TestRunTaskBossTimeout:
    """endless_single.run_task BossDeathTimeoutError 处理测试。"""

    def setUp(self):
        self._orig = _mock_dm_modules()

    def tearDown(self):
        _restore_dm_modules(self._orig)

    @patch("GameBot.runner.business.war3.jiubing2.team_steps_base._build_business_objects")
    def test_sync_source_boss_timeout_marks_flow_failed(self, mock_build):
        """同步源捕获 BossDeathTimeoutError 后应标记 _flow_failed=True。"""
        from GameBot.runner.business.war3.jiubing2.endless_runner import BossDeathTimeoutError
        from GameBot.runner.tasks.war3.jiubing2.endless import endless_single

        ui, nav, combat, runner = MagicMock(), MagicMock(), MagicMock(), MagicMock()
        runner.start_endless.side_effect = BossDeathTimeoutError("超时")
        mock_build.return_value = (ui, nav, combat, runner)

        member = _make_member(is_sync_source=True)

        endless_single.run_task(member, stop_event=threading.Event())

        assert member._flow_failed is True
        runner.start_endless.assert_called_once()
        member.war3.quit_game.assert_not_called()

    @patch("GameBot.runner.business.war3.jiubing2.team_steps_base._build_business_objects")
    def test_non_sync_source_boss_timeout_marks_flow_failed(self, mock_build):
        """非同步源捕获 BossDeathTimeoutError 后也应标记 _flow_failed=True。"""
        from GameBot.runner.business.war3.jiubing2.endless_runner import BossDeathTimeoutError
        from GameBot.runner.tasks.war3.jiubing2.endless import endless_single

        ui, nav, combat, runner = MagicMock(), MagicMock(), MagicMock(), MagicMock()
        runner.start_endless.side_effect = BossDeathTimeoutError("超时")
        mock_build.return_value = (ui, nav, combat, runner)

        member = _make_member(is_sync_source=False)

        endless_single.run_task(member, stop_event=threading.Event())

        assert member._flow_failed is True
        runner.start_endless.assert_called_once()

    @patch("GameBot.runner.business.war3.jiubing2.team_steps_base._build_business_objects")
    def test_normal_completion_no_flow_failed(self, mock_build):
        """正常完成时不应标记 _flow_failed。"""
        from GameBot.runner.tasks.war3.jiubing2.endless import endless_single

        ui, nav, combat, runner = MagicMock(), MagicMock(), MagicMock(), MagicMock()
        runner.start_endless.return_value = None
        mock_build.return_value = (ui, nav, combat, runner)

        member = _make_member(is_sync_source=True)

        endless_single.run_task(member, stop_event=threading.Event())

        assert member._flow_failed is False
