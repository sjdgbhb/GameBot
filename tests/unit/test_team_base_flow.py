"""TeamMemberBase 步骤执行单元测试。

覆盖 _execute_steps 阶段列表执行、_invoke_step 阶段调用、
exit_signal 监控、_sync_exit 同步退出等纯逻辑。
"""

import sys
import threading
from unittest.mock import MagicMock, patch

import pytest

pytestmark = [pytest.mark.unit]

# Mock Windows COM 依赖，使主环境 3.12 可导入 runner 模块
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
    """在 sys.modules 中注入 mock 的 Windows COM 模块。"""
    originals = {name: sys.modules.get(name) for name in _DM_MODULES}
    for name in _DM_MODULES:
        sys.modules[name] = MagicMock()
    return originals


def _restore_dm_modules(originals):
    """恢复原始 sys.modules 状态。"""
    for name, mod in originals.items():
        if mod is None:
            sys.modules.pop(name, None)
        else:
            sys.modules[name] = mod


class _MockFactory:
    """可接受任意参数的 mock 类，其实例是 MagicMock。"""

    def __new__(cls, *args, **kwargs):
        return MagicMock()


@pytest.fixture
def team_base_setup(tmp_path, monkeypatch):
    """创建 TeamMemberBase 实例并打补丁，避免真实大漠调用。"""
    originals = _mock_dm_modules()

    # 拦截 TeamMemberBase 依赖的大漠对象
    monkeypatch.setattr("GameBot.runner.team.base.create_dm_client", _MockFactory)
    monkeypatch.setattr("GameBot.runner.team.base.KKBusiness", _MockFactory)
    monkeypatch.setattr("GameBot.runner.team.base.War3Business", _MockFactory)

    from GameBot.runner.team.base import TeamMemberBase

    # 子类化以 bypass 抽象方法
    class TestMember(TeamMemberBase):
        def get_role(self):
            return "leader"

        def kk_phase(self, round_num):
            return True

    cfg = {
        "war3": {
            "client_size": [1902, 1033],
            "key_time": 0.05,
            "general_time": 0.3,
        },
        "hero": {"inventory": []},
        "kk": {},
        "team": {
            "team_task": {
                "rounds": 0,
                "tasks": {"test_mod": "team_test_mod.test_task"},
                "sync": {"progress_report_interval": 0.1},
            }
        },
    }
    member_cfg = {
        "role": "leader",
        "target_player": "player1",
        "task": "test_mod",
        "steps": ["step_a", "step_b"],
    }

    # 使用临时 IPC 目录
    from GameBot.runner.team.ipc import TeamIPC

    ipc = TeamIPC("test_flow", str(tmp_path / "ipc"))

    stop_event = threading.Event()
    member = TestMember(
        cfg=cfg,
        member_cfg=member_cfg,
        ipc=ipc,
        sync_source="player1",
        stop_event=stop_event,
    )

    # 将 war3 替换为 mock
    member.war3 = MagicMock()
    member.dm = MagicMock()

    yield member

    _restore_dm_modules(originals)


class TestInvokeStep:
    """测试 _invoke_step 阶段调用。"""

    def test_simple_step(self, team_base_setup):
        """阶段名应正确解析并调用对应模块方法。"""
        member = team_base_setup
        member._flow_failed = False
        member._game = "test_game"

        mock_module = MagicMock()
        with patch("importlib.import_module", return_value=mock_module) as mock_import:
            member._invoke_step("test_mod", "run_task")
            mock_import.assert_called_once_with("GameBot.runner.tasks.test_game.test_mod")
            mock_module.run_task.assert_called_once_with(member, member.stop_event)
            assert member._flow_failed is False

    def test_unknown_task(self, team_base_setup):
        """未知任务模块应标记失败。"""
        member = team_base_setup
        member._flow_failed = False
        member._game = "test_game"

        with patch("importlib.import_module", side_effect=ModuleNotFoundError("No module")):
            member._invoke_step("nonexistent", "run_task")
            assert member._flow_failed is True

    def test_missing_method(self, team_base_setup):
        """模块存在但阶段方法不存在应标记失败。"""
        member = team_base_setup
        member._flow_failed = False
        member._game = "test_game"

        class FakeModule:
            pass

        with patch("importlib.import_module", return_value=FakeModule()):
            member._invoke_step("test_mod", "run_task")
            assert member._flow_failed is True

    def test_step_exception_marks_flow_failed(self, team_base_setup):
        """方法抛出异常时标记 _flow_failed=True。"""
        member = team_base_setup
        member._flow_failed = False
        member._game = "test_game"

        class FakeModule:
            @staticmethod
            def run_task(member, stop_event, **kwargs):
                raise ValueError("test error")

        with patch("importlib.import_module", return_value=FakeModule()):
            member._invoke_step("test_mod", "run_task")
            assert member._flow_failed is True


class TestExecuteSteps:
    """测试 _execute_steps 步骤列表执行。"""

    def test_steps_in_order(self, team_base_setup):
        """步骤应按配置顺序执行。"""
        member = team_base_setup
        member._game = "test_game"
        call_order = []

        def _fake_import(path):
            mod = MagicMock()
            mod.run_task = MagicMock(side_effect=lambda m, e, **kw: call_order.append(path))
            return mod

        with patch("importlib.import_module", side_effect=_fake_import):
            member._steps = ["mod_a", "mod_b"]
            flow_failed = member._execute_steps(round_num=1)
            assert flow_failed is False
            assert call_order == [
                "GameBot.runner.tasks.test_game.mod_a",
                "GameBot.runner.tasks.test_game.mod_b",
            ]

    def test_stop_event_interrupts_steps(self, team_base_setup):
        """stop_event 设置时应中断步骤执行。"""
        member = team_base_setup
        member._steps = ["step_a", "step_b"]
        member.stop_event.set()

        with patch.object(member, "_invoke_step") as mock_invoke:
            member._execute_steps(round_num=1)
            mock_invoke.assert_not_called()

    def test_flow_failed_skips_remaining(self, team_base_setup):
        """任一步骤失败后跳过剩余步骤。"""
        member = team_base_setup
        member._game = "test_game"
        called_paths = []

        def _fake_import(path):
            mod = MagicMock()

            def _run_task(m, e, **kw):
                if path.endswith("mod_fail"):
                    m._flow_failed = True
                called_paths.append(path)

            mod.run_task = MagicMock(side_effect=_run_task)
            return mod

        with patch("importlib.import_module", side_effect=_fake_import):
            member._steps = ["mod_fail", "mod_never"]
            flow_failed = member._execute_steps(round_num=1)
            assert flow_failed is True
            assert called_paths == ["GameBot.runner.tasks.test_game.mod_fail"]

    def test_empty_steps_marks_failed(self, team_base_setup):
        """空步骤列表应标记失败。"""
        member = team_base_setup
        member._steps = []
        flow_failed = member._execute_steps(round_num=1)
        assert flow_failed is True


class TestGamePhaseResult:
    def test_non_sync_member_waits_before_quitting(self, team_base_setup):
        member = team_base_setup
        member.is_sync_source = False
        member.get_role = MagicMock(return_value="follower_0")
        member.war3.bind_war3_window.return_value = 100
        member._is_window_alive = MagicMock(return_value=True)
        member._wait_enter_game = MagicMock()
        member._execute_steps = MagicMock(return_value=False)

        game_failed = member._game_phase(round_num=1)

        assert game_failed is False
        member.war3.quit_game.assert_not_called()
        assert member._current_war3_hwnd == 100

    def test_flow_failure_returns_true(self, team_base_setup):
        member = team_base_setup
        member.is_sync_source = False
        member.get_role = MagicMock(return_value="follower_0")
        member.war3.bind_war3_window.return_value = 100
        member._is_window_alive = MagicMock(return_value=True)
        member._wait_enter_game = MagicMock()
        member._execute_steps = MagicMock(return_value=True)

        game_failed = member._game_phase(round_num=1)

        assert game_failed is True


class TestGameStateSync:
    def test_wait_game_state_ignores_previous_round(self):
        from GameBot.runner.business.war3.jiubing2.team_steps_base import _wait_game_state

        member = MagicMock()
        member._current_round = 2
        member.ipc.read_game_state.side_effect = [
            {"phase": "in_game", "round": 1},
            {"phase": "in_game", "round": 2},
        ]

        _wait_game_state(member, "in_game", threading.Event(), timeout=0.1)

        assert member.ipc.read_game_state.call_count == 2


class TestSyncExit:
    """测试 _sync_exit 同步退出逻辑。"""

    def test_sync_source_writes_exit_signal(self, team_base_setup):
        """同步源成员广播退出信号。"""
        member = team_base_setup
        member.is_sync_source = True
        member._sync_exit(round_num=3)
        signal = member.ipc.read_exit_signal()
        assert signal is not None
        assert signal["round"] == 3

    def test_non_sync_source_waits_for_exit_signal(self, team_base_setup):
        """非同步源成员等待退出信号。"""
        member = team_base_setup
        member.is_sync_source = False

        # 在另一个线程延迟写入退出信号
        def delayed_write():
            import time
            time.sleep(0.1)
            member.ipc.write_exit_signal(round_num=2)

        threading.Thread(target=delayed_write).start()

        member._sync_exit(round_num=2)
        # 等待成功返回 None（方法内无返回值，只阻塞等待）
        signal = member.ipc.read_exit_signal()
        assert signal["round"] == 2

    def test_non_sync_source_stops_on_stop_event(self, team_base_setup):
        """非同步源在 stop_event 设置时应立即退出等待。"""
        member = team_base_setup
        member.is_sync_source = False

        # 在另一个线程延迟设置 stop_event
        def delayed_stop():
            import time
            time.sleep(0.1)
            member.stop_event.set()

        threading.Thread(target=delayed_stop).start()

        member._sync_exit(round_num=1)
        # 应因 stop_event 退出，不广播任何信号
        assert member.ipc.read_stop_signal() is False


class TestLoadMemberHero:
    """测试 _load_member_hero 成员英雄加载。"""

    def test_loads_member_hero(self, team_base_setup, monkeypatch):
        """成员配置 hero 时，应替换当前 hero 配置。"""
        member = team_base_setup
        member._game = "war3.jiubing2"
        cfg = member.task_cfg

        fake_raw = {"hero": {"name": "构造师", "floor_key": "P"}}
        fake_inheritable = {"hero": {"name": "构造师", "floor_key": "P"}}

        fake_config = MagicMock()
        fake_config._load_file = MagicMock(return_value=fake_raw)
        fake_config._split_sections = MagicMock(return_value=(fake_inheritable, {}))
        monkeypatch.setattr("GameBot.runner.team.base.config", fake_config)

        member._load_member_hero(cfg, {"hero": "engineer"})

        fake_config._load_file.assert_called_once_with("war3.jiubing2.heroes.engineer")
        assert cfg["hero"]["name"] == "构造师"
        assert cfg["hero"]["floor_key"] == "P"

    def test_missing_hero_config_keeps_default(self, team_base_setup, monkeypatch):
        """英雄配置不存在时，保留默认 hero。"""
        from GameBot.config import ConfigurationError

        member = team_base_setup
        member._game = "war3.jiubing2"
        cfg = member.task_cfg
        cfg["hero"] = {"name": "异界之人"}

        fake_config = MagicMock()
        fake_config._load_file = MagicMock(side_effect=ConfigurationError("not found"))
        monkeypatch.setattr("GameBot.runner.team.base.config", fake_config)

        member._load_member_hero(cfg, {"hero": "unknown"})

        assert cfg["hero"]["name"] == "异界之人"

    def test_no_game_skips_loading(self, team_base_setup):
        """未配置 _game 时不尝试加载英雄。"""
        member = team_base_setup
        member._game = ""
        cfg = member.task_cfg
        cfg["hero"] = {"name": "异界之人"}

        member._load_member_hero(cfg, {"hero": "engineer"})

        assert cfg["hero"]["name"] == "异界之人"
