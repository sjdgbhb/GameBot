"""单元测试公共固件（Web、services、大漠 mock）。"""

import sys
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient


@pytest.fixture(autouse=True)
def reset_services_state():
    """每个单元测试前后清空 services 层的全局运行进程表。"""
    from GameBot.web.api import services

    services._running_processes.clear()
    yield
    services._running_processes.clear()


@pytest.fixture
def dm_env_mocks():
    """模拟 Windows COM 依赖，使主环境 3.12 可导入 runner 模块。

    适用于需要临时导入 runner/tasks 下模块的测试。
    """
    to_mock = (
        "win32com",
        "win32com.client",
        "pythoncom",
        "pywintypes",
        "winreg",
        "win32gui",
        "win32con",
        "win32api",
    )
    originals = {name: sys.modules.get(name) for name in to_mock}
    for name in to_mock:
        sys.modules[name] = MagicMock()
    yield
    for name, mod in originals.items():
        if mod is None:
            sys.modules.pop(name, None)
        else:
            sys.modules[name] = mod


@pytest.fixture
def web_client(reset_services_state):
    """创建 FastAPI TestClient，测试结束后自动清理。"""
    from GameBot.web.server import create_app

    app = create_app()
    with TestClient(app) as client:
        yield client


@pytest.fixture
def services_config_dir(tmp_path, monkeypatch):
    """为 services 层测试创建临时 config 目录并 patch _CONFIG_DIR。"""
    from GameBot.web.api import services

    config_dir = tmp_path / "src" / "GameBot" / "config" / "data"
    config_dir.mkdir(parents=True)
    monkeypatch.setattr(services, "_CONFIG_DIR", config_dir)
    return config_dir


@pytest.fixture
def services_project_root(tmp_path, monkeypatch):
    """为 services 层测试 patch _PROJECT_ROOT。"""
    from GameBot.web.api import services

    monkeypatch.setattr(services, "_PROJECT_ROOT", tmp_path)
    return tmp_path


@pytest.fixture
def services_user_config_path(tmp_path, monkeypatch):
    """为 load/save_user_configs 提供临时 user_configs.json 路径。"""
    from GameBot.web.api import services

    path = tmp_path / "user_configs.json"
    monkeypatch.setattr(services, "USER_CONFIGS_PATH", path)
    return path


@pytest.fixture
def services_web_config(monkeypatch):
    """为启动任务子进程测试清空 _WEB_CONFIG，避免读取真实 web.toml。"""
    from GameBot.web.api import services

    monkeypatch.setattr(services, "_WEB_CONFIG", {})
    return {}
