"""测试共用工具 — TOML 构造器、Config 测试基类、临时目录管理。

供 tests/unit/ 下所有配置相关测试复用，减少重复代码。
"""

import json
import shutil
import tempfile
import unittest
from pathlib import Path

from GameBot.config import Config


def write_toml(directory: Path, relative_path: str, content: str):
    """在 directory 下按 relative_path 写入 TOML 文件。

    :param directory: 根目录
    :param relative_path: 相对路径（如 "war3/jiubing2/heroes/mk.toml"）
    :param content: TOML 文本内容
    """
    filepath = directory / relative_path
    filepath.parent.mkdir(parents=True, exist_ok=True)
    filepath.write_text(content, encoding="utf-8")


def make_test_config_dir() -> Path:
    """创建标准测试用临时 config 目录。

    包含：base.toml、war3/war3.toml、war3/jiubing2/base.toml、
    两个英雄配置、两个任务配置、循环依赖文件。
    """
    tmp = Path(tempfile.mkdtemp(prefix="jiubing2_test_cfg_"))

    # base.toml — 基础配置，无依赖
    write_toml(
        tmp,
        "base.toml",
        """
[paths]
log_path = "logs"

[dm]
version = "3.1233"
""",
    )

    # war3/war3.toml — 依赖 base
    write_toml(
        tmp,
        "war3/war3.toml",
        """
dependencies = ["base"]

[war3]
window_class = "War3Class"
window_title = "Warcraft III"
client_size = [1902, 1033]
key_time = 0.05
general_time = 0.3
""",
    )

    # war3/jiubing2/base.toml — 依赖 war3
    write_toml(
        tmp,
        "war3/jiubing2/base.toml",
        """
dependencies = ["war3"]

[game]
load_war3_time = 33

[command]
clear_nearby = "-delh"

[hero]
inventory = ["A", "B", "C"]
""",
    )

    # war3/jiubing2/heroes/mk.toml — 英雄配置
    write_toml(
        tmp,
        "war3/jiubing2/heroes/mk.toml",
        """
[hero]
inventory = ["D", "E", "F"]
attack = 100
""",
    )

    # war3/jiubing2/heroes/lancer.toml — 另一个英雄
    write_toml(
        tmp,
        "war3/jiubing2/heroes/lancer.toml",
        """
[hero]
inventory = ["G", "H", "I"]
attack = 80
defense = 50
""",
    )

    # war3/jiubing2/tasks/others/fishing.toml
    write_toml(
        tmp,
        "war3/jiubing2/tasks/others/fishing.toml",
        """
dependencies = ["war3.jiubing2", "war3.jiubing2.heroes.mk"]

[war3.jiubing2.tasks.others.fishing]
name = "钓鱼"
task_times = 5
loop_interval_time = 2.0
""",
    )

    # war3/jiubing2/tasks/others/patrol_loot.toml
    write_toml(
        tmp,
        "war3/jiubing2/tasks/others/patrol_loot.toml",
        """
dependencies = ["war3.jiubing2", "war3.jiubing2.heroes.lancer"]

[war3.jiubing2.tasks.others.patrol_loot]
name = "巡逻拾取"
task_times = 3
patrol_rounds = 10
""",
    )

    # war3/jiubing2/tasks/endless/endless_single.toml
    write_toml(
        tmp,
        "war3/jiubing2/tasks/endless/endless_single.toml",
        """
dependencies = ["war3.jiubing2", "war3.jiubing2.heroes.mk"]

[war3.jiubing2.tasks.endless.endless_single]
name = "单局无尽"
task_times = 1
""",
    )

    # 循环依赖测试文件
    write_toml(
        tmp,
        "circular_a.toml",
        """
dependencies = ["circular_b"]
[x]
val = 1
""",
    )
    write_toml(
        tmp,
        "circular_b.toml",
        """
dependencies = ["circular_a"]
[y]
val = 2
""",
    )

    return tmp


def make_user_config_dir(config_dir: Path, user_config: dict) -> Path:
    """创建包含 user_configs.json 的临时 project_root，并复制 config 目录。

    :param config_dir: 原始 config 目录
    :param user_config: user_configs.json 内容字典
    :return: fake project_root 路径
    """
    fake_root = Path(tempfile.mkdtemp(prefix="jiubing2_user_"))
    fake_config_dir = fake_root / "a" / "b" / "c" / "config"
    fake_config_dir.mkdir(parents=True)
    shutil.copytree(config_dir, fake_config_dir, dirs_exist_ok=True)

    user_cfg_path = fake_root / "user_configs.json"
    user_cfg_path.write_text(json.dumps(user_config), encoding="utf-8")
    return fake_root


class ConfigTestBase(unittest.TestCase):
    """Config 测试基类 — 每个测试方法创建独立的 Config 实例和临时目录。

    子类可直接使用 self.cfg 和 self.config_dir。
    如需自定义 config 目录，覆盖 make_config_dir() 方法。
    """

    def make_config_dir(self) -> Path:
        """创建测试用 config 目录，子类可覆盖。"""
        return make_test_config_dir()

    def setUp(self):
        Config.reset()
        self.config_dir = self.make_config_dir()
        self.cfg = Config(str(self.config_dir))

    def tearDown(self):
        Config.reset()
        shutil.rmtree(self.config_dir, ignore_errors=True)
