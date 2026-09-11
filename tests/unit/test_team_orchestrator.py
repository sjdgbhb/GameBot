"""TeamOrchestrator 单元测试。

覆盖 target_player 唯一性校验、Python 路径解析、
子进程监控（同步源重启 / 非同步源告警 / 重启次数超限）、
停止所有子进程等纯逻辑。
"""

import sys
import threading
from unittest.mock import MagicMock, patch

import pytest

pytestmark = [pytest.mark.unit]

from GameBot.runner.team.orchestrator import TeamOrchestrator


@pytest.fixture
def team_cfg(tmp_path):
    """返回一个基础 team_cfg，用于 Orchestrator 测试。"""
    return {
        "members": [
            {"role": "leader", "target_player": "p1"},
            {"role": "follower", "target_player": "p2"},
        ],
        "sync": {"sync_source": "p1", "max_restart": 2, "progress_report_interval": 0.1},
        "ipc": {"ipc_dir": str(tmp_path / "ipc"), "ready_timeout": 1},
        "_config_path": "team.team_task",
    }


class FakeConfig:
    """模拟 orchestrator 中使用的 config 单例。"""

    def __init__(self, project_root):
        self.project_root = project_root


@pytest.fixture
def orchestrator(team_cfg, monkeypatch, tmp_path):
    """创建并配置 TeamOrchestrator 测试实例。"""
    from GameBot.runner.team import orchestrator as orch_module

    fake_cfg = FakeConfig(tmp_path)
    monkeypatch.setattr(orch_module, "config", fake_cfg)
    (tmp_path / "src").mkdir(exist_ok=True)

    cfg = {"dm": {"python_path": ""}}
    stop_event = threading.Event()
    orch = TeamOrchestrator(cfg, team_cfg, stop_event)

    # 替换 _processes 为 mock 进程字典
    orch._processes = {}
    yield orch

    # 关闭测试期间打开的子进程日志文件，避免 Windows 删除 tmp_path 失败
    for f in orch._process_log_files.values():
        if f:
            try:
                f.close()
            except Exception:
                pass

    # 清理 IPC
    orch.ipc.cleanup()


class TestInit:
    """测试 __init__ 相关逻辑。"""

    def test_duplicate_target_player_raises(self, tmp_path, monkeypatch):
        """target_player 重复应抛出 ValueError。"""
        from GameBot.runner.team import orchestrator as orch_module

        monkeypatch.setattr(orch_module, "config", FakeConfig(tmp_path))

        bad_cfg = {
            "members": [
                {"role": "leader", "target_player": "same"},
                {"role": "follower", "target_player": "same"},
            ],
            "sync": {},
            "ipc": {"ipc_dir": str(tmp_path / "ipc")},
        }
        with pytest.raises(ValueError, match="target_player 重复"):
            TeamOrchestrator({}, bad_cfg)

    def test_duplicate_hero_raises(self, tmp_path, monkeypatch):
        """英雄重复应抛出 ValueError。"""
        from GameBot.runner.team import orchestrator as orch_module

        monkeypatch.setattr(orch_module, "config", FakeConfig(tmp_path))

        bad_cfg = {
            "members": [
                {"role": "leader", "target_player": "p1", "hero": "hxd"},
                {"role": "follower", "target_player": "p2", "hero": "hxd"},
            ],
            "sync": {},
            "ipc": {"ipc_dir": str(tmp_path / "ipc")},
        }
        with pytest.raises(ValueError, match="英雄重复"):
            TeamOrchestrator({}, bad_cfg)

    def test_different_heroes_allowed(self, tmp_path, monkeypatch):
        """不同英雄应正常通过初始化校验。"""
        from GameBot.runner.team import orchestrator as orch_module

        monkeypatch.setattr(orch_module, "config", FakeConfig(tmp_path))

        good_cfg = {
            "members": [
                {"role": "leader", "target_player": "p1", "hero": "hxd"},
                {"role": "follower", "target_player": "p2", "hero": "paladin"},
            ],
            "sync": {},
            "ipc": {"ipc_dir": str(tmp_path / "ipc")},
        }
        orch = TeamOrchestrator({}, good_cfg)
        assert orch is not None

    def test_session_id_unique(self, orchestrator, monkeypatch):
        """不同时间创建的 Orchestrator 应有不同的 session_id。"""
        import time

        cfg = {"dm": {"python_path": ""}}
        team_cfg = {
            "members": [],
            "sync": {},
            "ipc": {"ipc_dir": "logs/team_ipc"},
        }

        # 模拟不同时间戳
        original_time = time.time
        monkeypatch.setattr("GameBot.runner.team.orchestrator.time.time", lambda: original_time() + 1.5)

        orch2 = TeamOrchestrator(cfg, team_cfg)
        assert orch2.session_id != orchestrator.session_id


class TestResolvePythonPath:
    """测试 _resolve_python_path。"""

    def test_uses_sys_executable(self, tmp_path, monkeypatch, team_cfg):
        """队长/队员子进程固定使用主环境 Python (sys.executable)。"""
        from GameBot.runner.team import orchestrator as orch_module

        monkeypatch.setattr(orch_module, "config", FakeConfig(tmp_path))
        (tmp_path / "src").mkdir(exist_ok=True)

        orch = TeamOrchestrator({}, team_cfg)
        assert orch._python_path == sys.executable

    def test_ignores_dm_python_path(self, tmp_path, monkeypatch, team_cfg):
        """[dm].python_path 不应影响子进程解释器选择。"""
        from GameBot.runner.team import orchestrator as orch_module

        monkeypatch.setattr(orch_module, "config", FakeConfig(tmp_path))
        (tmp_path / "src").mkdir(exist_ok=True)
        fake_py = tmp_path / "my_python.exe"
        fake_py.write_text("")

        cfg = {"dm": {"python_path": str(fake_py)}}
        orch = TeamOrchestrator(cfg, team_cfg)
        assert orch._python_path == sys.executable


class TestRoleToIndex:
    """测试 _role_to_index。"""

    def test_leader_index(self, orchestrator):
        """leader 角色返回正确索引。"""
        assert orchestrator._role_to_index("leader") == 0

    def test_follower_index(self, orchestrator):
        """follower_0 返回正确索引。"""
        assert orchestrator._role_to_index("follower_0") == 1

    def test_unknown_role(self, orchestrator):
        """未知角色返回 None。"""
        assert orchestrator._role_to_index("follower_99") is None


class TestStartAndStop:
    """测试子进程启动和停止。"""

    @patch("GameBot.runner.team.orchestrator.subprocess.Popen")
    def test_start_all_members(self, mock_popen, orchestrator):
        """_start_all_members 应为每个成员启动子进程。"""
        mock_popen.return_value = MagicMock()

        orchestrator._start_all_members()

        assert len(orchestrator._processes) == 2
        assert "leader" in orchestrator._processes
        assert "follower_0" in orchestrator._processes

        # 第一个调用应是 leader
        first_call = mock_popen.call_args_list[0]
        cmd = first_call[1].get("args") or first_call[0][0]
        assert "GameBot.runner.team.leader" in cmd

    @patch("GameBot.runner.team.orchestrator.subprocess.Popen")
    def test_stop_all_members(self, mock_popen, orchestrator):
        """_stop_all_members 应写入 stop_signal 并等待子进程。"""
        proc1 = MagicMock()
        proc2 = MagicMock()
        orchestrator._processes = {"leader": proc1, "follower_0": proc2}

        orchestrator._stop_all_members()

        assert orchestrator.ipc.read_stop_signal() is True
        proc1.wait.assert_called_once()
        proc2.wait.assert_called_once()


class TestMonitorLoop:
    """测试 _monitor_loop 子进程监控逻辑。"""

    @patch("GameBot.runner.team.orchestrator.subprocess.Popen")
    def test_sync_source_crashed_in_game_writes_exit_signal(self, mock_popen, orchestrator):
        """同步源在游戏阶段异常退出应写 exit_signal 并重启，计入重启次数。"""
        # 写入 progress 模拟游戏阶段
        orchestrator.ipc.write_progress(
            role="leader", member_name="p1", task_name="test",
            task_progress="", state="in_game", round_num=1,
        )

        crashed_proc = MagicMock()
        crashed_proc.poll.return_value = -1
        healthy_proc = MagicMock()
        healthy_proc.poll.return_value = None

        orchestrator._processes = {
            "leader": crashed_proc,  # leader 是同步源
            "follower_0": healthy_proc,
        }

        new_proc = MagicMock()
        mock_popen.return_value = new_proc

        with patch.object(orchestrator.stop_event, "is_set", side_effect=[False, True]):
            orchestrator._monitor_loop()

        # 应写 exit_signal（让其他玩家退出游戏回到房间）
        exit_signal = orchestrator.ipc.read_exit_signal()
        assert exit_signal is not None
        assert exit_signal["round"] == 1
        # 计入重启次数
        assert orchestrator._sync_source_restart_count == 1

    @patch("GameBot.runner.team.orchestrator.subprocess.Popen")
    def test_sync_source_max_restart_stops_all(self, mock_popen, orchestrator):
        """同步源在游戏阶段异常退出超过 max_restart 应广播 stop_signal。"""
        orchestrator.ipc.write_progress(
            role="leader", member_name="p1", task_name="test",
            task_progress="", state="in_game", round_num=1,
        )

        crashed_proc = MagicMock()
        crashed_proc.poll.return_value = -1

        orchestrator._processes = {"leader": crashed_proc}
        orchestrator._sync_source_max_restart = 0

        with patch.object(orchestrator.stop_event, "is_set", side_effect=[False, True]):
            orchestrator._monitor_loop()

        assert orchestrator.ipc.read_stop_signal() is True
        assert orchestrator.stop_event.is_set()

    def test_non_sync_source_crashed_in_game_no_restart(self, orchestrator):
        """非同步源在游戏阶段异常退出仅告警，不重启，不影响其他玩家。"""
        orchestrator.ipc.write_progress(
            role="follower_0", member_name="p2", task_name="test",
            task_progress="", state="in_game", round_num=1,
        )

        crashed_proc = MagicMock()
        crashed_proc.poll.return_value = -1

        orchestrator._processes = {
            "leader": MagicMock(poll=MagicMock(return_value=None)),
            "follower_0": crashed_proc,
        }

        with patch.object(orchestrator.stop_event, "is_set", side_effect=[False, True]):
            orchestrator._monitor_loop()

        # 不写 exit_signal，不计入重启次数
        assert orchestrator.ipc.read_exit_signal() is None
        assert orchestrator._sync_source_restart_count == 0
        # follower_0 应已从 _processes 中移除（崩溃后不重启）

    @patch("GameBot.runner.team.orchestrator.subprocess.Popen")
    def test_any_member_crashed_in_kk_restarts(self, mock_popen, orchestrator):
        """KK 阶段任何成员崩溃都直接重启，不计入重启次数。"""
        orchestrator.ipc.write_progress(
            role="follower_0", member_name="p2", task_name="test",
            task_progress="", state="kk_phase", round_num=1,
        )

        crashed_proc = MagicMock()
        crashed_proc.poll.return_value = -1

        orchestrator._processes = {
            "leader": MagicMock(poll=MagicMock(return_value=None)),
            "follower_0": crashed_proc,
        }

        new_proc = MagicMock()
        mock_popen.return_value = new_proc

        with patch.object(orchestrator.stop_event, "is_set", side_effect=[False, True]):
            orchestrator._monitor_loop()

        # KK 阶段直接重启，不计入重启次数，不写 exit_signal
        assert orchestrator._sync_source_restart_count == 0
        assert orchestrator.ipc.read_exit_signal() is None
        mock_popen.assert_called_once()

    @patch("GameBot.runner.team.orchestrator.subprocess.Popen")
    def test_normal_exit_no_restart(self, mock_popen, orchestrator):
        """同步源正常退出（返回码 0）不应重启。"""
        exited_proc = MagicMock()
        exited_proc.poll.return_value = 0

        orchestrator._processes = {"leader": exited_proc}

        with patch.object(orchestrator.stop_event, "is_set", side_effect=[False, True]):
            orchestrator._monitor_loop()

        assert orchestrator.ipc.read_exit_signal() is None
        assert orchestrator._sync_source_restart_count == 0
        mock_popen.assert_not_called()
