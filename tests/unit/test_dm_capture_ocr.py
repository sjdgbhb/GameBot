"""bind_window / bind_background 相关单元测试。

覆盖 TeamMemberBase bind_background 切换、BindWindowEx、_apply_bind_mode、
bind_window 重入等。
"""

import sys
from unittest.mock import MagicMock, patch

import pytest

pytestmark = [pytest.mark.unit]

# Mock Windows COM 依赖
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


@pytest.fixture(autouse=True)
def mock_windows():
    originals = _mock_dm_modules()
    yield
    _restore_dm_modules(originals)


# ── TeamMemberBase bind_background 切换测试 ────────────────


class TestTeamMemberBindMulti:
    """测试 TeamMemberBase 根据成员数/bind_mode 切换 bind_background。"""

    def test_single_member_keeps_bind(self, tmp_path, monkeypatch):
        """单成员时保持 bind 配置不变。"""
        monkeypatch.setattr("GameBot.runner.team.base.create_dm_client", lambda: MagicMock())
        monkeypatch.setattr("GameBot.runner.team.base.KKBusiness", lambda dm, cfg: MagicMock())
        monkeypatch.setattr("GameBot.runner.team.base.War3Business", lambda dm, cfg: MagicMock())

        from GameBot.runner.team.base import TeamMemberBase
        from GameBot.runner.team.ipc import TeamIPC

        class TestMember(TeamMemberBase):
            def get_role(self):
                return "leader"

            def kk_phase(self, round_num):
                return True

        cfg = {
            "war3": {
                "bind": {"display": "normal", "mouse": "normal", "keypad": "normal", "mode": 0},
                "bind_background": {"display": "dx2", "mouse": "windows3", "keypad": "windows", "mode": 0},
            },
            "hero": {"inventory": []},
            "kk": {
                "bind": {"display": "normal", "mouse": "normal", "keypad": "normal", "mode": 0},
                "bind_background": {"display": "gdi2", "mouse": "windows3", "keypad": "windows", "mode": 0},
            },
            "team": {
                "team_task": {
                    "rounds": 0,
                    "members": [{"role": "leader", "target_player": "p1"}],
                }
            },
        }
        ipc = TeamIPC("test", str(tmp_path / "ipc"))
        member = TestMember(cfg, cfg["team"]["team_task"]["members"][0], ipc, "p1")

        assert member.kk_cfg["bind"]["display"] == "normal"
        assert member.war3_cfg["bind"]["display"] == "normal"

    def test_multi_members_switch_bind_background(self, tmp_path, monkeypatch):
        """多成员时 bind_background 配置覆盖 bind 配置。"""
        monkeypatch.setattr("GameBot.runner.team.base.create_dm_client", lambda: MagicMock())
        monkeypatch.setattr("GameBot.runner.team.base.KKBusiness", lambda dm, cfg: MagicMock())
        monkeypatch.setattr("GameBot.runner.team.base.War3Business", lambda dm, cfg: MagicMock())

        from GameBot.runner.team.base import TeamMemberBase
        from GameBot.runner.team.ipc import TeamIPC

        class TestMember(TeamMemberBase):
            def get_role(self):
                return "leader"

            def kk_phase(self, round_num):
                return True

        cfg = {
            "war3": {
                "bind": {"display": "normal", "mouse": "normal", "keypad": "normal", "mode": 0},
                "bind_background": {
                    "display": "dx2",
                    "mouse": "windows3",
                    "keypad": "windows",
                    "mode": 0,
                    "bind_delay": 1.5,
                },
            },
            "hero": {"inventory": []},
            "kk": {
                "bind": {"display": "normal", "mouse": "normal", "keypad": "normal", "mode": 0},
                "bind_background": {
                    "display": "gdi2",
                    "mouse": "windows3",
                    "keypad": "windows",
                    "mode": 0,
                    "bind_delay": 1.0,
                },
            },
            "team": {
                "team_task": {
                    "rounds": 0,
                    "members": [
                        {"role": "leader", "target_player": "p1"},
                        {"role": "follower", "target_player": "p2"},
                    ],
                }
            },
        }
        ipc = TeamIPC("test", str(tmp_path / "ipc"))
        member = TestMember(cfg, cfg["team"]["team_task"]["members"][0], ipc, "p1")

        assert member.kk_cfg["bind"]["display"] == "gdi2"
        assert member.kk_cfg["bind"]["mouse"] == "windows3"
        assert member.kk_cfg["bind"]["bind_delay"] == 1.0
        assert member.war3_cfg["bind"]["display"] == "dx2"
        assert member.war3_cfg["bind"]["mouse"] == "windows3"
        assert member.war3_cfg["bind"]["bind_delay"] == 1.5

    def test_bind_mode_foreground_multi_member_forces_back(self, tmp_path, monkeypatch):
        """bind_mode=foreground 但多成员时，强制用后台 bind_background。"""
        monkeypatch.setattr("GameBot.runner.team.base.create_dm_client", lambda: MagicMock())
        monkeypatch.setattr("GameBot.runner.team.base.KKBusiness", lambda dm, cfg: MagicMock())
        monkeypatch.setattr("GameBot.runner.team.base.War3Business", lambda dm, cfg: MagicMock())

        from GameBot.runner.team.base import TeamMemberBase
        from GameBot.runner.team.ipc import TeamIPC

        class TestMember(TeamMemberBase):
            def get_role(self):
                return "leader"

            def kk_phase(self, round_num):
                return True

        cfg = {
            "war3": {
                "bind": {"display": "normal"},
                "bind_background": {"display": "dx2"},
            },
            "hero": {"inventory": []},
            "kk": {
                "bind": {"display": "normal"},
                "bind_background": {"display": "gdi2"},
            },
            "team": {
                "team_task": {
                    "rounds": 0,
                    "bind_mode": "foreground",
                    "members": [
                        {"role": "leader", "target_player": "p1"},
                        {"role": "follower", "target_player": "p2"},
                    ],
                }
            },
        }
        ipc = TeamIPC("test", str(tmp_path / "ipc"))
        member = TestMember(cfg, cfg["team"]["team_task"]["members"][0], ipc, "p1")

        # 多成员强制后台，即使 bind_mode=foreground
        assert member.kk_cfg["bind"]["display"] == "gdi2"
        assert member.war3_cfg["bind"]["display"] == "dx2"

    def test_bind_mode_background_forces_back(self, tmp_path, monkeypatch):
        """bind_mode=background 时即使单成员也用 bind_background。"""
        monkeypatch.setattr("GameBot.runner.team.base.create_dm_client", lambda: MagicMock())
        monkeypatch.setattr("GameBot.runner.team.base.KKBusiness", lambda dm, cfg: MagicMock())
        monkeypatch.setattr("GameBot.runner.team.base.War3Business", lambda dm, cfg: MagicMock())

        from GameBot.runner.team.base import TeamMemberBase
        from GameBot.runner.team.ipc import TeamIPC

        class TestMember(TeamMemberBase):
            def get_role(self):
                return "leader"

            def kk_phase(self, round_num):
                return True

        cfg = {
            "war3": {
                "bind": {"display": "normal"},
                "bind_background": {"display": "dx2", "bind_delay": 1.5},
            },
            "hero": {"inventory": []},
            "kk": {
                "bind": {"display": "normal"},
                "bind_background": {"display": "gdi2", "bind_delay": 1.0},
            },
            "team": {
                "team_task": {
                    "rounds": 0,
                    "bind_mode": "background",
                    "members": [{"role": "leader", "target_player": "p1"}],
                }
            },
        }
        ipc = TeamIPC("test", str(tmp_path / "ipc"))
        member = TestMember(cfg, cfg["team"]["team_task"]["members"][0], ipc, "p1")

        assert member.kk_cfg["bind"]["display"] == "gdi2"
        assert member.war3_cfg["bind"]["display"] == "dx2"


# ── BindWindowEx 路径测试 ────────────────────────────


class TestBindWindowEx:
    """测试 bind_window 在有/无 public 参数时的行为。"""

    def test_bind_window_without_public(self):
        """无 public 字段时仍统一走 BindWindowEx，public 传空串。"""
        from GameBot.runner.driver.window import WindowMixin

        class FakeClient(WindowMixin):
            def __init__(self):
                self.calls = []

            def _com_call(self, name, *args):
                self.calls.append((name, args))
                if name == "BindWindowEx":
                    return 1
                if name == "UnBindWindow":
                    return 1
                return 0

        client = FakeClient()
        with client.bind_window(
            12345, bind_cfg={"display": "gdi2", "mouse": "windows3", "keypad": "windows", "mode": 0}
        ):
            pass

        # 统一调用 BindWindowEx，无 public 时 public 为空串
        assert client.calls[0][0] == "BindWindowEx"
        assert client.calls[0][1] == (12345, "gdi2", "windows3", "windows", "", 0)

    def test_bind_window_with_public(self):
        """有 public 字段时走 BindWindowEx。"""
        from GameBot.runner.driver.window import WindowMixin

        class FakeClient(WindowMixin):
            def __init__(self):
                self.calls = []

            def _com_call(self, name, *args):
                self.calls.append((name, args))
                if name == "BindWindowEx":
                    return 1
                if name == "UnBindWindow":
                    return 1
                return 0

        client = FakeClient()
        bind_cfg = {
            "display": "dx2",
            "mouse": "windows3",
            "keypad": "windows",
            "mode": 0,
            "public": "dx.public.active.api",
        }
        with client.bind_window(99999, bind_cfg=bind_cfg):
            pass

        # 应调用 BindWindowEx
        assert client.calls[0][0] == "BindWindowEx"
        assert client.calls[0][1] == (99999, "dx2", "windows3", "windows", "dx.public.active.api", 0)

    def test_bind_window_with_delay(self):
        """有 bind_delay 时绑定后应延时。"""
        from GameBot.runner.driver.window import WindowMixin

        class FakeClient(WindowMixin):
            def __init__(self):
                self.calls = []

            def _com_call(self, name, *args):
                self.calls.append((name, args))
                if name == "BindWindowEx":
                    return 1
                if name == "UnBindWindow":
                    return 1
                return 0

        client = FakeClient()
        with patch("GameBot.runner.driver.window.time.sleep") as mock_sleep:
            with client.bind_window(111, bind_cfg={"display": "gdi2", "bind_delay": 1.5}):
                pass

        # bind_delay > 0 时应调用 time.sleep
        mock_sleep.assert_called_once_with(1.5)

    def test_bind_window_without_delay_no_sleep(self):
        """无 bind_delay 时不调用 sleep。"""
        from GameBot.runner.driver.window import WindowMixin

        class FakeClient(WindowMixin):
            def _com_call(self, name, *args):
                if name == "BindWindowEx":
                    return 1
                if name == "UnBindWindow":
                    return 1
                return 0

        client = FakeClient()
        with patch("GameBot.runner.driver.window.time.sleep") as mock_sleep:
            with client.bind_window(222, bind_cfg={"display": "normal"}):
                pass

        mock_sleep.assert_not_called()


# ── 配置层 _apply_bind_mode 测试 ──────────────────────


class TestConfigApplyBindMode:
    """测试 Config._apply_bind_mode 按 bind_mode 把 bind_foreground/bind_background 解析进 bind。

    bind_mode 位于命名空间层（war3.bind_mode / kk.bind_mode），顶层任务可用自身
    [this].bind_mode 覆盖；解析结果写入 config[ns]["bind"] 并记录 bind_mode。
    """

    def _make_config(self):
        """构造一个最小 Config 实例用于测试 _apply_bind_mode。"""
        from GameBot.config.system.core import Config

        cfg = Config.__new__(Config)
        return cfg

    @staticmethod
    def _config(war3_mode=None, kk_mode=None):
        """构造测试配置：bind_mode 在命名空间层，bind_foreground/bind_background 为参数源。"""
        config = {
            "war3": {
                "bind_foreground": {"display": "normal"},
                "bind_background": {"display": "dx2", "bind_delay": 1.5},
            },
            "kk": {
                "bind_foreground": {"display": "normal"},
                "bind_background": {"display": "gdi2", "bind_delay": 1.0},
            },
        }
        if war3_mode is not None:
            config["war3"]["bind_mode"] = war3_mode
        if kk_mode is not None:
            config["kk"]["bind_mode"] = kk_mode
        return config

    def test_default_mode_uses_foreground(self):
        """未指定 bind_mode 时默认 foreground，bind 取 bind_foreground。"""
        cfg = self._make_config()
        config = self._config()
        cfg._apply_bind_mode(config)
        assert config["war3"]["bind"]["display"] == "normal"
        assert config["war3"]["bind"]["bind_mode"] == "foreground"
        assert config["kk"]["bind"]["display"] == "normal"

    def test_background_mode_resolves_background_params(self):
        """平台 bind_mode=background 时 bind 取 bind_background 并记录模式。"""
        cfg = self._make_config()
        config = self._config(war3_mode="background", kk_mode="background")
        cfg._apply_bind_mode(config)
        assert config["war3"]["bind"]["display"] == "dx2"
        assert config["war3"]["bind"]["bind_delay"] == 1.5
        assert config["war3"]["bind"]["bind_mode"] == "background"
        assert config["kk"]["bind"]["display"] == "gdi2"
        assert config["kk"]["bind"]["bind_delay"] == 1.0

    def test_platforms_resolve_independently(self):
        """war3/kk 各自按自身 bind_mode 解析。"""
        cfg = self._make_config()
        config = self._config(war3_mode="background", kk_mode="foreground")
        cfg._apply_bind_mode(config)
        assert config["war3"]["bind"]["display"] == "dx2"
        assert config["kk"]["bind"]["display"] == "normal"

    def test_task_bind_mode_background_overrides(self):
        """顶层任务 this.bind_mode=background 覆盖平台默认 foreground。"""
        cfg = self._make_config()
        config = self._config(war3_mode="foreground", kk_mode="foreground")
        config["war3"]["jiubing2"] = {"tasks": {"others": {"paladin_wind_dragon": {"bind_mode": "background"}}}}
        cfg._apply_bind_mode(config, "war3.jiubing2.tasks.others.paladin_wind_dragon")
        assert config["war3"]["bind"]["display"] == "dx2"
        assert config["kk"]["bind"]["display"] == "gdi2"

    def test_task_bind_mode_foreground_overrides(self):
        """顶层任务 this.bind_mode=foreground 覆盖平台默认 background。"""
        cfg = self._make_config()
        config = self._config(war3_mode="background", kk_mode="background")
        config["team"] = {"team_task": {"bind_mode": "foreground"}}
        cfg._apply_bind_mode(config, "team.team_task")
        assert config["war3"]["bind"]["display"] == "normal"
        assert config["kk"]["bind"]["display"] == "normal"

    def test_missing_bind_background_no_crash(self):
        """没有 bind_background 时 background 模式不崩溃，bind 不生成。"""
        cfg = self._make_config()
        config = {
            "war3": {"bind_mode": "background"},
            "kk": {"bind_mode": "background"},
        }
        cfg._apply_bind_mode(config)
        assert "bind" not in config["war3"]
        assert "bind" not in config["kk"]


# ── bind_window 幂等测试 ──────────────────────────────


class TestBindWindowReentrant:
    """bind_window 幂等：已绑定同一 hwnd 时内层不重复调用 COM。"""

    def test_nested_same_hwnd_skips_com(self):
        """嵌套 bind 同一窗口时，内层不重复 BindWindowEx/UnBindWindow。"""
        from GameBot.runner.driver.window import WindowMixin

        calls = []

        class FakeClient(WindowMixin):
            def _com_call(self, name, *args):
                calls.append(name)
                if name == "BindWindowEx":
                    return 1
                if name == "GetBindWindow":
                    return getattr(self, "_current_bind_hwnd", 0)
                return 1

        client = FakeClient()
        with client.bind_window(123, bind_cfg={}):
            assert calls.count("BindWindowEx") == 1
            with client.bind_window(123, bind_cfg={}):
                # 内层不重复绑定
                assert calls.count("BindWindowEx") == 1
        # 外层退出时解绑一次
        assert calls.count("UnBindWindow") == 1

    def test_nested_different_hwnd_binds(self):
        """嵌套 bind 不同窗口时，内层仍正常绑定（大漠同一时刻只能绑一个）。"""
        from GameBot.runner.driver.window import WindowMixin

        calls = []

        class FakeClient(WindowMixin):
            def _com_call(self, name, *args):
                calls.append(name)
                if name == "BindWindowEx":
                    return 1
                if name == "GetBindWindow":
                    return getattr(self, "_current_bind_hwnd", 0)
                return 1

        client = FakeClient()
        with client.bind_window(123, bind_cfg={}):
            with client.bind_window(456, bind_cfg={}):
                assert calls.count("BindWindowEx") == 2
        assert calls.count("UnBindWindow") == 2
