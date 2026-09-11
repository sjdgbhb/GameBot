"""TeamMemberBase 第 3 轮复审新增逻辑单元测试。

覆盖：
- _claim_hall_window 缓存复用 + PID 校验 + 多开 error 日志
- _wait_all_members_in_game round 校验 + 死亡成员跳过 + stale 时钟
- _recover_round 一次性标志（_round_recovered）
- _report_progress 状态转换绕过节流
"""

import sys
import threading
import time
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


class _MockFactory:
    def __new__(cls, *args, **kwargs):
        return MagicMock()


def _make_member(tmp_path, members=None, target_player="player1", role="leader"):
    """创建 TeamMemberBase 子类实例用于测试。"""
    originals = _mock_dm_modules()

    import GameBot.runner.team.base as base_mod

    old_dm = base_mod.create_dm_client
    old_kk = base_mod.KKBusiness
    old_war3 = base_mod.War3Business
    base_mod.create_dm_client = _MockFactory
    base_mod.KKBusiness = _MockFactory
    base_mod.War3Business = _MockFactory

    from GameBot.runner.team.base import TeamMemberBase

    class TestMember(TeamMemberBase):
        def get_role(self):
            return role

        def kk_phase(self, round_num):
            return True

    if members is None:
        members = [{"role": "leader", "target_player": target_player}]

    cfg = {
        "war3": {"client_size": [1902, 1033], "key_time": 0.05, "general_time": 0.3},
        "hero": {"inventory": []},
        "kk": {},
        "team": {
            "team_task": {
                "rounds": 0,
                "tasks": {"test_mod": "team_test_mod.test_task"},
                "sync": {"progress_report_interval": 2},
                "members": members,
            }
        },
    }
    member_cfg = {
        "role": role,
        "target_player": target_player,
        "task": "test_mod",
        "steps": [],
    }

    from GameBot.runner.team.ipc import TeamIPC

    ipc = TeamIPC("test_review3", str(tmp_path / "ipc"))
    stop_event = threading.Event()
    member = TestMember(
        cfg=cfg,
        member_cfg=member_cfg,
        ipc=ipc,
        sync_source=target_player,
        stop_event=stop_event,
    )
    member.dm = MagicMock()
    member.war3 = MagicMock()
    member.kk = MagicMock()
    member._originals = originals
    member._old_modules = (base_mod, old_dm, old_kk, old_war3)
    return member


@pytest.fixture
def member(tmp_path):
    m = _make_member(tmp_path)
    yield m
    base_mod, old_dm, old_kk, old_war3 = m._old_modules
    base_mod.create_dm_client = old_dm
    base_mod.KKBusiness = old_kk
    base_mod.War3Business = old_war3
    _restore_dm_modules(m._originals)


@pytest.fixture
def member_multi(tmp_path):
    """多开场景（2 members）。"""
    members = [
        {"role": "leader", "target_player": "player1"},
        {"role": "follower", "target_player": "player2"},
    ]
    m = _make_member(tmp_path, members=members, target_player="player2", role="follower_0")
    yield m
    base_mod, old_dm, old_kk, old_war3 = m._old_modules
    base_mod.create_dm_client = old_dm
    base_mod.KKBusiness = old_kk
    base_mod.War3Business = old_war3
    _restore_dm_modules(m._originals)


class TestClaimHallWindowCacheReuse:
    """_claim_hall_window 缓存复用 + PID 校验测试。"""

    def test_cache_reuse_skips_ocr(self, member):
        """已缓存且窗口 PID 一致时应复用缓存，不调用 claim_hall_window。"""
        member.hall_hwnd = 500
        member.owner_pid = 1234
        member.dm.get_window_process_id.return_value = 1234

        result = member._claim_hall_window()

        assert result is True
        member.kk.claim_hall_window.assert_not_called()

    def test_cache_invalid_pid_triggers_reclaim(self, member):
        """缓存窗口 PID 不匹配时应重新认领。"""
        member.hall_hwnd = 500
        member.owner_pid = 1234
        member.dm.get_window_process_id.return_value = 9999  # PID 不匹配
        member.kk.claim_hall_window.return_value = (600, 5678)

        result = member._claim_hall_window()

        assert result is True
        assert member.hall_hwnd == 600
        assert member.owner_pid == 5678
        member.kk.claim_hall_window.assert_called_once()

    def test_no_target_player_returns_false(self, member):
        """未配置 target_player 时应返回 False。"""
        member.target_player = ""

        result = member._claim_hall_window()

        assert result is False

    def test_claim_failure_multi_instance_logs_error(self, member_multi):
        """多开场景下认领失败应记录 error 日志。"""
        member_multi.target_player = "player2"
        member_multi.kk.claim_hall_window.return_value = (0, 0)

        with patch("GameBot.runner.team.base.logger") as mock_logger:
            result = member_multi._claim_hall_window()

        assert result is False
        mock_logger.error.assert_called_once()
        call_args = mock_logger.error.call_args[0][0]
        assert "PID 过滤将失效" in call_args

    def test_claim_failure_single_instance_no_error(self, member):
        """单开场景下认领失败不应记录 error 日志。"""
        member.kk.claim_hall_window.return_value = (0, 0)

        with patch("GameBot.runner.team.base.logger") as mock_logger:
            result = member._claim_hall_window()

        assert result is False
        mock_logger.error.assert_not_called()


class TestWaitAllMembersInGame:
    """_wait_all_members_in_game round 校验 + 死亡成员跳过测试。"""

    def test_round_mismatch_not_counted(self, member):
        """成员 state=in_game 但 round 不匹配时不应放行。"""
        # 写入陈旧 round 的 progress
        member.ipc.write_progress(
            role="leader",
            member_name="p1",
            task_name="t",
            task_progress="",
            state="in_game",
            round_num=1,
        )
        member._current_round = 2

        result = member._wait_all_members_in_game(timeout=0.5)

        assert result is False  # 超时，因为 round 不匹配

    def test_round_match_passes(self, member):
        """成员 state=in_game 且 round 匹配时应放行。"""
        member.ipc.write_progress(
            role="leader",
            member_name="p1",
            task_name="t",
            task_progress="",
            state="in_game",
            round_num=2,
        )
        member._current_round = 2

        result = member._wait_all_members_in_game(timeout=1)

        assert result is True

    def test_stopped_member_skipped(self, tmp_path):
        """state=stopped 的成员应被跳过，不阻塞屏障。"""
        members = [
            {"role": "leader", "target_player": "p1"},
            {"role": "follower", "target_player": "p2"},
        ]
        member = _make_member(tmp_path, members=members, target_player="p1", role="leader")
        try:
            # leader 在游戏中，follower 已停止
            member.ipc.write_progress(
                role="leader",
                member_name="p1",
                task_name="t",
                task_progress="",
                state="in_game",
                round_num=1,
            )
            member.ipc.write_progress(
                role="follower_0",
                member_name="p2",
                task_name="t",
                task_progress="",
                state="stopped",
                round_num=1,
            )
            member._current_round = 1

            result = member._wait_all_members_in_game(timeout=1)

            assert result is True  # follower_0 被跳过，不阻塞
        finally:
            base_mod, old_dm, old_kk, old_war3 = member._old_modules
            base_mod.create_dm_client = old_dm
            base_mod.KKBusiness = old_kk
            base_mod.War3Business = old_war3
            _restore_dm_modules(member._originals)

    def test_stale_timestamp_member_skipped(self, tmp_path):
        """timestamp 过期的成员应被跳过。"""
        members = [
            {"role": "leader", "target_player": "p1"},
            {"role": "follower", "target_player": "p2"},
        ]
        member = _make_member(tmp_path, members=members, target_player="p1", role="leader")
        try:
            # leader 在游戏中
            member.ipc.write_progress(
                role="leader",
                member_name="p1",
                task_name="t",
                task_progress="",
                state="in_game",
                round_num=1,
            )
            # follower 进度过期（timestamp 远在过去）
            old_ts = time.time() - 10000
            member.ipc.write_progress(
                role="follower_0",
                member_name="p2",
                task_name="t",
                task_progress="",
                state="game_phase",
                round_num=1,
            )
            # 手动修改 timestamp
            import json
            import os

            prog_path = os.path.join(member.ipc.progress_dir, "follower_0.json")
            with open(prog_path, "r") as f:
                data = json.load(f)
            data["timestamp"] = old_ts
            with open(prog_path, "w") as f:
                json.dump(data, f)

            member._current_round = 1

            result = member._wait_all_members_in_game(timeout=1)

            assert result is True  # follower_0 过期被跳过
        finally:
            base_mod, old_dm, old_kk, old_war3 = member._old_modules
            base_mod.create_dm_client = old_dm
            base_mod.KKBusiness = old_kk
            base_mod.War3Business = old_war3
            _restore_dm_modules(member._originals)


class TestRecoverRoundOneTimeFlag:
    """_recover_round 一次性标志测试。"""

    def test_recover_round_updates_current_round(self, member):
        """_recover_round 应从 IPC 读取最大 round 并 +1。"""
        member.ipc.write_progress(
            role="leader",
            member_name="p1",
            task_name="t",
            task_progress="",
            state="game_phase",
            round_num=3,
        )
        member._recover_round()

        assert member._current_round == 4

    def test_recover_round_no_progress_stays_default(self, member):
        """无 IPC 进度时 _current_round 应保持默认值 1。"""
        member._recover_round()

        assert member._current_round == 1

    def test_run_calls_recover_round_only_once(self, member):
        """run() 循环中 _recover_round 应仅被调用一次（一次性标志）。"""
        member._recover_round = MagicMock()
        # kk_phase 第一次失败，第二次也失败 → 循环多次
        member.kk_phase = MagicMock(side_effect=[False, False, False])
        member._safe_quit_game = MagicMock()
        # 设置 safe_stop_threshold=3 使循环能在 3 次失败后退出
        member.task_cfg["team"]["team_task"]["sync"]["safe_stop_threshold"] = 3

        member.run()

        member._recover_round.assert_called_once()


class TestReportProgressStateChange:
    """_report_progress 状态转换绕过节流测试。"""

    def test_state_change_bypasses_throttle(self, member):
        """状态转换时应绕过节流强制写入。"""
        member._progress_interval = 10  # 大节流间隔
        member.ipc.write_progress = MagicMock()

        # 第一次上报 kk_phase
        member._report_progress(state="kk_phase", round_num=1)
        assert member.ipc.write_progress.call_count == 1

        # 立即上报不同状态 in_game — 应绕过节流
        member._report_progress(state="in_game", round_num=1)
        assert member.ipc.write_progress.call_count == 2

    def test_same_state_throttled(self, member):
        """同状态重复上报应被节流。"""
        member._progress_interval = 10
        member.ipc.write_progress = MagicMock()

        member._report_progress(state="in_game", round_num=1)
        assert member.ipc.write_progress.call_count == 1

        # 同状态立即再次上报 — 应被节流
        member._report_progress(state="in_game", round_num=1)
        assert member.ipc.write_progress.call_count == 1  # 仍未写入

    def test_task_progress_bypasses_throttle(self, member):
        """有 task_progress 内容时应绕过节流（即使状态相同）。"""
        member._progress_interval = 10
        member.ipc.write_progress = MagicMock()

        member._report_progress(state="in_game", round_num=1)
        assert member.ipc.write_progress.call_count == 1

        # 同状态但有 task_progress — 应写入
        member._report_progress(state="in_game", round_num=1, task_progress="3/10")
        assert member.ipc.write_progress.call_count == 2

    def test_stopped_state_always_written(self, member):
        """stopped 状态转换应总是写入（不被节流吞掉）。"""
        member._progress_interval = 10
        member.ipc.write_progress = MagicMock()

        member._report_progress(state="in_game", round_num=1)
        member._report_progress(state="in_game", round_num=1)  # 被节流
        assert member.ipc.write_progress.call_count == 1

        # 状态转为 stopped — 应立即写入
        member._report_progress(state="stopped", round_num=1)
        assert member.ipc.write_progress.call_count == 2
