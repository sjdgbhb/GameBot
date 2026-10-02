"""bind_window / bind_background 相关单元测试。

覆盖 BindWindowEx、resolve_bind_cfg / force_bind_mode、bind_window 重入等。
"""

import sys
from unittest.mock import MagicMock, patch

import pytest

from GameBot.config import force_bind_mode, resolve_bind_cfg

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


# ── 配置层 resolve_bind_cfg / force_bind_mode 测试 ──────────────────────


class TestResolveBindCfg:
    """测试 resolve_bind_cfg 按命名空间 bind_mode 选择 bind_foreground/bind_background。

    bind_mode 只有命名空间层（war3.bind_mode / kk.bind_mode）一个来源；任务/变体
    通过 [war3]/[kk] 绝对寻址段覆盖（合并后即命名空间值），任务 [this] 不参与。
    解析在调用时进行，不向配置字典写入派生 bind 字段。
    """

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
        """未指定 bind_mode 时默认 foreground，解析取 bind_foreground。"""
        config = self._config()
        war3_bind = resolve_bind_cfg(config["war3"])
        assert war3_bind["display"] == "normal"
        assert war3_bind["bind_mode"] == "foreground"
        assert resolve_bind_cfg(config["kk"])["display"] == "normal"
        # 调用时解析，不写入配置字典
        assert "bind" not in config["war3"]

    def test_background_mode_resolves_background_params(self):
        """平台 bind_mode=background 时解析取 bind_background 并记录模式。"""
        config = self._config(war3_mode="background", kk_mode="background")
        war3_bind = resolve_bind_cfg(config["war3"])
        assert war3_bind["display"] == "dx2"
        assert war3_bind["bind_delay"] == 1.5
        assert war3_bind["bind_mode"] == "background"
        kk_bind = resolve_bind_cfg(config["kk"])
        assert kk_bind["display"] == "gdi2"
        assert kk_bind["bind_delay"] == 1.0

    def test_platforms_resolve_independently(self):
        """war3/kk 各自按自身 bind_mode 解析。"""
        config = self._config(war3_mode="background", kk_mode="foreground")
        assert resolve_bind_cfg(config["war3"])["display"] == "dx2"
        assert resolve_bind_cfg(config["kk"])["display"] == "normal"

    def test_task_node_bind_mode_ignored(self):
        """任务 [this].bind_mode 已废弃：任务节点里的 bind_mode 不影响解析。"""
        config = self._config(war3_mode="foreground", kk_mode="foreground")
        config["war3"]["jiubing2"] = {"tasks": {"wind_dragon": {"paladin_wind_dragon": {"bind_mode": "background"}}}}
        assert resolve_bind_cfg(config["war3"])["display"] == "normal"
        assert resolve_bind_cfg(config["kk"])["display"] == "normal"

    def test_missing_bind_background_no_crash(self):
        """没有 bind_background 时 background 模式不崩溃，只回 bind_mode。"""
        assert resolve_bind_cfg({"bind_mode": "background"}) == {"bind_mode": "background"}

    def test_force_bind_mode_overrides(self):
        """force_bind_mode 覆写 war3/kk 命名空间 bind_mode。"""
        config = self._config(war3_mode="foreground", kk_mode="foreground")
        force_bind_mode(config, "background")
        assert config["war3"]["bind_mode"] == "background"
        assert config["kk"]["bind_mode"] == "background"
        assert resolve_bind_cfg(config["war3"])["display"] == "dx2"
        assert resolve_bind_cfg(config["kk"])["display"] == "gdi2"


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
