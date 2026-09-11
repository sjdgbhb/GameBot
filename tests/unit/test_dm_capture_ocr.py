"""大漠后台截图 OCR 单元测试。

覆盖 ocr_kk_lines、Base.ocr_lines/ocr_text、capture_to_temp、
TextMonitor 大漠截图路径、bind_multi 切换等。
"""

import os
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


# ── capture_to_temp 测试 ──────────────────────────────


class TestCaptureToTemp:
    """测试 VisualMixin.capture_to_temp 方法。"""

    def test_capture_success(self):
        from GameBot.runner.driver.visual import VisualMixin

        class FakeClient(VisualMixin):
            def _com_call(self, name, *args):
                if name == "Capture":
                    return 1
                return 0

        client = FakeClient()
        path = client.capture_to_temp(10, 20, 100, 200, prefix="test")
        assert path != ""
        assert "gamebot_test_" in path
        assert path.endswith(".bmp")
        # 清理临时文件
        if os.path.exists(path):
            os.remove(path)

    def test_same_millisecond_captures_use_different_paths(self):
        from GameBot.runner.driver.visual import VisualMixin

        class FakeClient(VisualMixin):
            def _com_call(self, name, *args):
                return 1 if name == "Capture" else 0

        client = FakeClient()
        with patch("time.time", return_value=1234.567):
            first = client.capture_to_temp(10, 20, 100, 200)
            second = client.capture_to_temp(10, 20, 100, 200)

        assert first != second

    def test_capture_failure(self):
        from GameBot.runner.driver.visual import VisualMixin

        class FakeClient(VisualMixin):
            def _com_call(self, name, *args):
                if name == "Capture":
                    return 0
                return 0

        client = FakeClient()
        path = client.capture_to_temp(10, 20, 100, 200, prefix="fail")
        assert path == ""


# ── KKBusiness.ocr_kk_lines 测试 ──────────────────────


class TestOcrKkLines:
    """测试 KKBusiness.ocr_kk_lines 大漠后台截图行为。"""

    def test_ocr_kk_lines_binds_window(self):
        """ocr_kk_lines 总是走 bind_window（幂等由 bind_window 自身处理）。"""
        from GameBot.runner.business.kk import KKBusiness

        dm = MagicMock()
        dm.capture_to_temp.return_value = "/tmp/test_ocr.bmp"
        dm.bind_window.return_value.__enter__ = MagicMock(return_value=None)
        dm.bind_window.return_value.__exit__ = MagicMock(return_value=False)
        kk = KKBusiness(dm, {"bind": {}})

        mock_client = MagicMock()
        mock_client.ocr_lines_from_file.return_value = [{"text": "room123", "x_center": 30, "y_center": 30}]
        with patch("GameBot.runner.business.base.get_inference_client", return_value=mock_client):
            with patch("os.remove") as mock_remove:
                lines = kk.ocr_kk_lines(dm, 999, {"area_coords": [10, 20, 100, 50]})

        assert len(lines) == 1
        assert lines[0]["text"] == "room123"
        dm.bind_window.assert_called_once()
        dm.capture_to_temp.assert_called_once()
        mock_client.ocr_lines_from_file.assert_called_once_with("/tmp/test_ocr.bmp", merge_lines=True)
        mock_remove.assert_called_once()

    def test_ocr_kk_lines_binds_with_cfg(self):
        """ocr_kk_lines 传入 bind_cfg 时应使用该配置绑定。"""
        from GameBot.runner.business.kk import KKBusiness

        dm = MagicMock()
        dm.capture_to_temp.return_value = "/tmp/test_ocr2.bmp"
        dm.bind_window.return_value.__enter__ = MagicMock(return_value=None)
        dm.bind_window.return_value.__exit__ = MagicMock(return_value=False)

        kk = KKBusiness(dm, {"bind": {"display": "gdi2"}})

        mock_client = MagicMock()
        mock_client.ocr_lines_from_file.return_value = []
        with patch("GameBot.runner.business.base.get_inference_client", return_value=mock_client):
            with patch("os.remove"):
                lines = kk.ocr_kk_lines(dm, 888, {"area_coords": [0, 0, 100, 50]})

        dm.bind_window.assert_called_once()
        dm.capture_to_temp.assert_called_once()

    def test_capture_failure(self):
        """截图失败返回空列表。"""
        from GameBot.runner.business.kk import KKBusiness

        dm = MagicMock()
        dm.capture_to_temp.return_value = ""
        dm.bind_window.return_value.__enter__ = MagicMock(return_value=None)
        dm.bind_window.return_value.__exit__ = MagicMock(return_value=False)

        kk = KKBusiness(dm, {"bind": {}})

        mock_client = MagicMock()
        with patch("GameBot.runner.business.base.get_inference_client", return_value=mock_client):
            lines = kk.ocr_kk_lines(dm, 777, {"area_coords": [0, 0, 50, 50]})

        assert lines == []
        mock_client.ocr_lines_from_file.assert_not_called()


# ── TextMonitorMixin 大漠截图测试 ─────────────────────


class TestTextMonitorDmCapture:
    """测试 TextMonitorMixin 大漠后台截图行为。"""

    def test_ocr_region_text(self):
        """_ocr_region_text 走大漠截图路径。"""
        from GameBot.runner.business.base import Base
        from GameBot.runner.business.war3.text_monitor import TextMonitorMixin

        class FakeWar3(Base, TextMonitorMixin):
            def _find_war3_hwnd(self):
                return 12345

            def __init__(self):
                self.dm = MagicMock()
                self.dm.capture_to_temp.return_value = "/tmp/war3_ocr.bmp"
                self.war3_cfg = {"bind": {"display": "gdi2"}}

        war3 = FakeWar3()
        mock_client = MagicMock()
        mock_client.ocr_from_file.return_value = "测试文字"
        with patch("GameBot.runner.business.base.get_inference_client", return_value=mock_client):
            with patch("os.remove"):
                result = war3._ocr_region_text({"area_coords": [10, 20, 100, 50]})

        assert result == "测试文字"
        war3.dm.capture_to_temp.assert_called_once()
        mock_client.ocr_from_file.assert_called_once_with("/tmp/war3_ocr.bmp")


# ── TeamMemberBase bind_multi 切换测试 ────────────────


class TestTeamMemberBindMulti:
    """测试 TeamMemberBase 根据成员数/bind_mode 切换 bind_multi。"""

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
                "bind_multi": {"display": "dx2", "mouse": "windows3", "keypad": "windows", "mode": 0},
            },
            "hero": {"inventory": []},
            "kk": {
                "bind": {"display": "normal", "mouse": "normal", "keypad": "normal", "mode": 0},
                "bind_multi": {"display": "gdi2", "mouse": "windows3", "keypad": "windows", "mode": 0},
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

    def test_multi_members_switch_bind_multi(self, tmp_path, monkeypatch):
        """多成员时 bind_multi 配置覆盖 bind 配置。"""
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
                "bind_multi": {"display": "dx2", "mouse": "windows3", "keypad": "windows", "mode": 0, "bind_delay": 1.5},
            },
            "hero": {"inventory": []},
            "kk": {
                "bind": {"display": "normal", "mouse": "normal", "keypad": "normal", "mode": 0},
                "bind_multi": {"display": "gdi2", "mouse": "windows3", "keypad": "windows", "mode": 0, "bind_delay": 1.0},
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
        """bind_mode=foreground 但多成员时，强制用后台 bind_multi。"""
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
                "bind_multi": {"display": "dx2"},
            },
            "hero": {"inventory": []},
            "kk": {
                "bind": {"display": "normal"},
                "bind_multi": {"display": "gdi2"},
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
        """bind_mode=background 时即使单成员也用 bind_multi。"""
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
                "bind_multi": {"display": "dx2", "bind_delay": 1.5},
            },
            "hero": {"inventory": []},
            "kk": {
                "bind": {"display": "normal"},
                "bind_multi": {"display": "gdi2", "bind_delay": 1.0},
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
        with client.bind_window(12345, bind_cfg={"display": "gdi2", "mouse": "windows3", "keypad": "windows", "mode": 0}):
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
    """测试 Config._apply_bind_mode 在配置加载后自动切换 bind/bind_multi。"""

    def _make_config(self):
        """构造一个最小 Config 实例用于测试 _apply_bind_mode。"""
        from GameBot.config.system.core import Config

        cfg = Config.__new__(Config)
        return cfg

    def test_default_mode_no_swap(self):
        """未指定 bind_mode 时默认 foreground，不切换 bind。"""
        cfg = self._make_config()
        config = {
            "war3": {
                "bind": {"display": "normal"},
                "bind_multi": {"display": "dx2"},
            },
            "kk": {
                "bind": {"display": "normal"},
                "bind_multi": {"display": "gdi2"},
            },
        }
        cfg._apply_bind_mode(config)
        assert config["war3"]["bind"]["display"] == "normal"
        assert config["kk"]["bind"]["display"] == "normal"

    def test_background_mode_swaps(self):
        """background 模式用 bind_multi 覆盖 bind。"""
        cfg = self._make_config()
        config = {
            "war3": {
                "bind": {"display": "normal", "bind_mode": "background"},
                "bind_multi": {"display": "dx2", "bind_delay": 1.5},
            },
            "kk": {
                "bind": {"display": "normal", "bind_mode": "background"},
                "bind_multi": {"display": "gdi2", "bind_delay": 1.0},
            },
        }
        cfg._apply_bind_mode(config)
        assert config["war3"]["bind"]["display"] == "dx2"
        assert config["war3"]["bind"]["bind_delay"] == 1.5
        assert config["kk"]["bind"]["display"] == "gdi2"
        assert config["kk"]["bind"]["bind_delay"] == 1.0

    def test_foreground_mode_no_swap(self):
        """foreground 模式保持 bind 不变。"""
        cfg = self._make_config()
        config = {
            "war3": {
                "bind": {"display": "normal", "bind_mode": "foreground"},
                "bind_multi": {"display": "dx2"},
            },
            "kk": {
                "bind": {"display": "normal", "bind_mode": "foreground"},
                "bind_multi": {"display": "gdi2"},
            },
        }
        cfg._apply_bind_mode(config)
        assert config["war3"]["bind"]["display"] == "normal"
        assert config["kk"]["bind"]["display"] == "normal"

    def test_team_bind_mode_background_overrides(self):
        """team.team_task.bind_mode=background 优先级高于 war3/kk 自身的 bind_mode。"""
        cfg = self._make_config()
        config = {
            "war3": {
                "bind": {"display": "normal", "bind_mode": "foreground"},
                "bind_multi": {"display": "dx2"},
            },
            "kk": {
                "bind": {"display": "normal", "bind_mode": "foreground"},
                "bind_multi": {"display": "gdi2"},
            },
            "team": {
                "team_task": {
                    "bind_mode": "background",
                }
            },
        }
        cfg._apply_bind_mode(config)
        # team 的 background 覆盖 war3/kk 的 foreground
        assert config["war3"]["bind"]["display"] == "dx2"
        assert config["kk"]["bind"]["display"] == "gdi2"

    def test_team_bind_mode_foreground_overrides(self):
        """team.team_task.bind_mode=foreground 优先级高于 war3/kk 自身的 bind_mode。"""
        cfg = self._make_config()
        config = {
            "war3": {
                "bind": {"display": "normal", "bind_mode": "background"},
                "bind_multi": {"display": "dx2"},
            },
            "kk": {
                "bind": {"display": "normal", "bind_mode": "background"},
                "bind_multi": {"display": "gdi2"},
            },
            "team": {
                "team_task": {
                    "bind_mode": "foreground",
                }
            },
        }
        cfg._apply_bind_mode(config)
        # team 的 foreground 覆盖 war3/kk 的 background，保持 bind 不变
        assert config["war3"]["bind"]["display"] == "normal"
        assert config["kk"]["bind"]["display"] == "normal"

    def test_no_bind_multi_no_crash(self):
        """没有 bind_multi 时 background 模式不崩溃。"""
        cfg = self._make_config()
        config = {
            "war3": {"bind": {"display": "normal", "bind_mode": "background"}},
            "kk": {"bind": {"display": "normal", "bind_mode": "background"}},
        }
        cfg._apply_bind_mode(config)
        # 没有 bind_multi，bind 保持不变
        assert config["war3"]["bind"]["display"] == "normal"
        assert config["kk"]["bind"]["display"] == "normal"


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
