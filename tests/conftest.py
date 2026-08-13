"""pytest 全局公共固件与钩子。

- 注册自定义 mark
- 在缺失大漠环境时忽略 tests/manual 目录，避免 3.12 主环境收集失败
- 提供 Config 测试通用固件（委托给 tests/common/config_helpers.py）
"""
import shutil
from pathlib import Path

import pytest

from GameBot.config import Config
from tests.common.config_helpers import make_test_config_dir as _make_test_config_dir
from tests.common.config_helpers import write_toml as _write_toml_helper


# 自定义标记说明（与 pyproject.toml 保持一致，防止 --strict-markers 报错）
_MARKERS = {
    "unit": "单元测试",
    "integration": "集成测试（真实文件 I/O，多模块协作）",
    "manual": "需人工介入的手动测试",
    "dm": "依赖大漠插件 COM（仅 .venv-dm 32 位 Python 3.8）",
    "slow": "耗时较长的测试",
    "inference": "依赖 ONNX / AI 模型的推理测试",
    "web": "Web API / FastAPI 测试",
    "config": "配置系统测试",
}


def pytest_configure(config):
    """注册所有自定义标记，避免 --strict-markers 时报 unknown marker 警告。"""
    for mark, desc in _MARKERS.items():
        config.addinivalue_line("markers", f"{mark}: {desc}")


# 检测大漠环境：在 .venv-dm 中 pythoncom 可导入，在主环境 3.12 中会失败
_DM_AVAILABLE = False
try:
    import pythoncom  # type: ignore
    _DM_AVAILABLE = True
except Exception:  # noqa: S110
    pass


def pytest_ignore_collect(collection_path, config):
    """非大漠环境下不收集 tests/manual，避免 pythoncom 等 32 位依赖报错。"""
    rel = str(collection_path).replace("\\", "/")
    if "tests/manual" in rel and not _DM_AVAILABLE:
        return True
    return None


@pytest.fixture
def reset_config():
    """手动控制 Config 单例重置，适用于非 unittest 类的新测试。"""
    Config.reset()
    yield
    Config.reset()


@pytest.fixture
def write_toml():
    """提供 TOML 文件写入工具（来自 config_helpers）。"""
    return _write_toml_helper


@pytest.fixture
def test_config_dir(tmp_path):
    """创建标准 TOML 测试配置目录并返回。

    委托给 tests/common/config_helpers.py 的 write_toml，
    在 tmp_path 下生成与 make_test_config_dir 相同结构的配置目录。
    """
    config_dir = tmp_path / "config"
    _populate_standard_config(config_dir)
    yield config_dir
    shutil.rmtree(config_dir, ignore_errors=True)


@pytest.fixture
def config_instance(test_config_dir, reset_config):
    """创建独立的 Config 实例。

    test_config_dir 提供临时配置目录，reset_config 保证单例清理。
    """
    cfg = Config(str(test_config_dir))
    yield cfg


@pytest.fixture
def project_root_with_config(tmp_path, test_config_dir):
    """构造一个带 config 目录和用户配置文件的临时 project_root。

    Config.project_root 依赖 config_path 上溯四级，因此生成的 fake_root 满足
    fake_root / a / b / c / config 结构。
    """
    fake_root = tmp_path / "project_root"
    fake_config_dir = fake_root / "a" / "b" / "c" / "config"
    fake_config_dir.mkdir(parents=True)

    _copy_tree(test_config_dir, fake_config_dir)

    yield fake_root


# ------------------- 辅助函数 -------------------


def _copy_tree(src: Path, dst: Path) -> None:
    """复制 src 下所有文件到 dst（忽略 __pycache__）。"""
    for p in src.rglob("*"):
        if "__pycache__" in p.parts:
            continue
        if p.is_file():
            rel = p.relative_to(src)
            target = dst / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(p, target)


def _populate_standard_config(config_dir: Path) -> Path:
    """生成标准测试配置目录，委托给 config_helpers.write_toml 写入文件。

    内容与 config_helpers.make_test_config_dir 完全一致，
    但写入指定目录而非临时随机目录。
    """
    _write_toml_helper(config_dir, "base.toml", """
[paths]
log_path = "logs"

[dm]
version = "3.1233"
""")

    _write_toml_helper(config_dir, "war3/war3.toml", """
dependencies = ["base"]

[war3]
window_class = "War3Class"
window_title = "Warcraft III"
client_size = [1902, 1033]
key_time = 0.05
general_time = 0.3
""")

    _write_toml_helper(config_dir, "war3/jiubing2/base.toml", """
dependencies = ["war3"]

[game]
load_war3_time = 33

[command]
clear_nearby = "-delh"

[hero]
inventory = ["A", "B", "C"]
""")

    _write_toml_helper(config_dir, "war3/jiubing2/heroes/mk.toml", """
[hero]
inventory = ["D", "E", "F"]
attack = 100
""")

    _write_toml_helper(config_dir, "war3/jiubing2/heroes/lancer.toml", """
[hero]
inventory = ["G", "H", "I"]
attack = 80
defense = 50
""")

    _write_toml_helper(config_dir, "war3/jiubing2/tasks/others/fishing.toml", """
dependencies = ["war3.jiubing2", "war3.jiubing2.heroes.mk"]

[war3.jiubing2.tasks.others.fishing]
name = "钓鱼"
task_times = 5
loop_interval_time = 2.0
""")

    _write_toml_helper(config_dir, "war3/jiubing2/tasks/others/patrol_loot.toml", """
dependencies = ["war3.jiubing2", "war3.jiubing2.heroes.lancer"]

[war3.jiubing2.tasks.others.patrol_loot]
name = "巡逻拾取"
task_times = 3
patrol_rounds = 10
""")

    _write_toml_helper(config_dir, "war3/jiubing2/tasks/endless/endless_single.toml", """
dependencies = ["war3.jiubing2", "war3.jiubing2.heroes.mk"]

[war3.jiubing2.tasks.endless.endless_single]
name = "单局无尽"
task_times = 1
""")

    # 循环依赖测试文件
    _write_toml_helper(config_dir, "circular_a.toml", """
dependencies = ["circular_b"]
[x]
val = 1
""")

    _write_toml_helper(config_dir, "circular_b.toml", """
dependencies = ["circular_a"]
[y]
val = 2
""")

    return config_dir
