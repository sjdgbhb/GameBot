"""每日声望任务单元测试 — 覆盖配置加载、嵌套子表路径、次数反推、
父级 fallback、enable 开关路由等逻辑（mock 所有外部依赖）。

覆盖：
- 配置加载：daily_reputation 依赖链正确展开，嵌套子表 blackstone/forest 可访问
- task_config_path：BlackstoneReputationTask / ForestReputationTask 指向嵌套子表
- _effective_times：按 target_reputation / reputation_per_run 反推次数
- _parent_cfg fallback：子表未配置 clear_nearby_interval 时从父级读取
- DailyReputationTask.run：enable_blackstone / enable_forest 开关控制子任务执行
"""

import math
import unittest
from unittest.mock import MagicMock, patch

import pytest

from GameBot.config import Config

pytestmark = [pytest.mark.unit]

# ── 测试用 TOML 文件内容 ──

BASE_TOML = """
name = "base"
extends = []
[paths]
log_path = "logs"

[dm]
version = "3.1233"
"""

WAR3_TOML = """
name = "war3"
extends = ["base"]

[this]
window_class = "War3Class"
window_title = "Warcraft III"
client_size = [1902, 1033]
key_time = 0.05
general_time = 0.3
small_window_response_time = 0.5
"""

JIUBING2_TOML = """
name = "war3.jiubing2"
extends = ["war3"]

[game]
load_war3_time = 33

[command]
clear_nearby = "-delh"

[hero]
inventory = ["A", "B", "C"]

[atomic_task]
accept_text = "已领取"
complete_text = "前往任务发布者处完成任务"
monitor_interval = 0.2

[prompt_text]
area_coords = [100, 100, 800, 600]
"""

PALADIN_TOML = """
name = "war3.jiubing2.heroes.paladin"
extends = ["war3.jiubing2"]
[[hero.inventory]]
id = 6
hotkey = "4"
[[hero.inventory]]
id = 9
hotkey = "5"
[[hero.inventory]]
id = 0
hotkey = "6"

[hero]
attack = 120
"""

BLACKSTONE_CITY_TOML = """
name = "scenes.blackstone_city"
extends = ["war3.jiubing2"]

[this.npcs.guard_captain]
desc = "黑石城守卫队长"
mini_coords = [254, 867]
coords = [1018, 369]
walk_mode = 2
time = 0.5
"""

KAMI_VILLAGE_TOML = """
name = "scenes.kami_village"
extends = ["war3.jiubing2"]
[this.npcs.jephite]
desc = "村民杰菲特"
mini_coords = [332, 845]
coords = [1146, 245]
walk_offset = [-100, 0]
walk_mode = 0
time = 0.5
"""

FOREST_CITY_TOML = """
name = "scenes.forest_city"
extends = ["war3.jiubing2"]
[this.npcs.diana]
desc = "月之女祭司狄安娜"
mini_coords = [230, 986]
coords = [936, 432]
walk_mode = 2
time = 0.5
"""

MENETHIL_TOML = """
name = "scenes.menethil"
extends = ["war3.jiubing2"]
[this.teleport.forest_waygate]
desc = "远古森林入口传送圈"
mini_coords = [100, 900]
coords = [500, 400]
time = 3
"""

GATE_HARASSMENT_TOML = """
name = "tasks.atomic.blackstone_gate_harassment"
extends = ["war3.jiubing2.scenes.blackstone_city"]

[this]
name = "城门骚扰"
accept_timeout = 8
route_complete_timeout = 120
combat_mode = "auto_attack"
"""

SWIFT_BEAST_TOML = """
name = "tasks.atomic.swift_beast"
extends = ["war3.jiubing2.scenes.forest_city", "war3.jiubing2.heroes.hxd"]

[this]
name = "迅猛野兽"
accept_timeout = 8
route_complete_timeout = 120
combat_mode = "auto_attack"
"""

DAILY_REPUTATION_TOML = """
name = "tasks.reputation.daily_reputation"
extends = ["war3.jiubing2.tasks.atomic.blackstone_gate_harassment", "war3.jiubing2.tasks.atomic.swift_beast", "war3.jiubing2.scenes.menethil", "war3.jiubing2.heroes.paladin"]

[this]
name = "每日声望"
enable_blackstone = true
enable_forest = true
clear_nearby_interval = 120

[this.blackstone]
name = "每日黑石城声望"
target_reputation = 150
reputation_per_run = 5
loop_interval_time = 1.5

[this.forest]
name = "每日森之城声望"
target_reputation = 150
reputation_per_run = 10
loop_interval_time = 60
"""

# heroes.hxd — swift_beast 依赖（被 paladin 互斥）
HXD_TOML = """
name = "war3.jiubing2.heroes.hxd"
extends = ["war3.jiubing2"]
[[hero.inventory]]
id = 0
hotkey = "6"

[hero]
attack = 90
"""


def _write_toml(directory, relative_path, content):
    """在 directory 下按 relative_path 写入 TOML 文件。"""
    from pathlib import Path

    filepath = Path(directory) / relative_path
    filepath.parent.mkdir(parents=True, exist_ok=True)
    filepath.write_text(content, encoding="utf-8")


def _make_test_config_dir():
    """创建一个独立的临时 config 目录，包含每日声望任务所需的所有 TOML 文件。"""
    import tempfile
    from pathlib import Path

    tmp = Path(tempfile.mkdtemp(prefix="jiubing2_test_rep_"))

    _write_toml(tmp, "base.toml", BASE_TOML)
    _write_toml(tmp, "war3/war3.toml", WAR3_TOML)
    _write_toml(tmp, "war3/jiubing2/base.toml", JIUBING2_TOML)
    _write_toml(tmp, "war3/jiubing2/heroes/paladin.toml", PALADIN_TOML)
    _write_toml(tmp, "war3/jiubing2/heroes/hxd.toml", HXD_TOML)
    _write_toml(tmp, "war3/jiubing2/scenes/blackstone_city.toml", BLACKSTONE_CITY_TOML)
    _write_toml(tmp, "war3/jiubing2/scenes/kami_village.toml", KAMI_VILLAGE_TOML)
    _write_toml(tmp, "war3/jiubing2/scenes/forest_city.toml", FOREST_CITY_TOML)
    _write_toml(tmp, "war3/jiubing2/scenes/menethil.toml", MENETHIL_TOML)
    _write_toml(tmp, "war3/jiubing2/tasks/atomic/blackstone_gate_harassment.toml", GATE_HARASSMENT_TOML)
    _write_toml(tmp, "war3/jiubing2/tasks/atomic/swift_beast.toml", SWIFT_BEAST_TOML)
    _write_toml(tmp, "war3/jiubing2/tasks/reputation/daily_reputation.toml", DAILY_REPUTATION_TOML)

    return tmp


class TestDailyReputationBase(unittest.TestCase):
    """测试基类 — 每个测试方法创建独立的 Config 实例和临时目录。"""

    def setUp(self):
        Config.reset()
        self.config_dir = _make_test_config_dir()
        self.cfg = Config(str(self.config_dir))
        self._cleanup_dirs = [self.config_dir]

    def tearDown(self):
        import shutil

        Config.reset()
        for d in self._cleanup_dirs:
            shutil.rmtree(d, ignore_errors=True)


class TestDailyReputationConfig(TestDailyReputationBase):
    """测试每日声望配置加载和嵌套子表结构。"""

    def test_load_daily_reputation(self):
        """加载 daily_reputation 任务，应包含依赖闭包中的所有配置段。"""
        result = self.cfg.load_task("war3.jiubing2.tasks.reputation.daily_reputation")
        # 任务自身命名空间
        self.assertEqual(result["tasks"]["reputation"]["daily_reputation"]["name"], "每日声望")
        # 嵌套子表
        blackstone = result["tasks"]["reputation"]["daily_reputation"]["blackstone"]
        self.assertEqual(blackstone["name"], "每日黑石城声望")
        self.assertEqual(blackstone["target_reputation"], 150)
        self.assertEqual(blackstone["reputation_per_run"], 5)

        forest = result["tasks"]["reputation"]["daily_reputation"]["forest"]
        self.assertEqual(forest["name"], "每日森之城声望")
        self.assertEqual(forest["target_reputation"], 150)
        self.assertEqual(forest["reputation_per_run"], 10)

    def test_dependencies_resolved(self):
        """daily_reputation 的依赖链应包含原子任务和场景配置。"""
        result = self.cfg.load_task("war3.jiubing2.tasks.reputation.daily_reputation")
        # 原子任务配置
        self.assertIn("blackstone_gate_harassment", result.get("tasks", {}).get("atomic", {}))
        self.assertIn("swift_beast", result.get("tasks", {}).get("atomic", {}))
        # 场景配置
        self.assertIn("blackstone_city", result.get("scenes", {}))
        self.assertIn("forest_city", result.get("scenes", {}))
        self.assertIn("menethil", result.get("scenes", {}))

    def test_hero_exclusivity_paladin(self):
        """heroes.paladin 置于最后加载，应覆盖 heroes.hxd。"""
        result = self.cfg.load_task("war3.jiubing2.tasks.reputation.daily_reputation")
        # paladin 的 attack=120 应生效，hxd 的 attack=90 不应残留
        self.assertEqual(result["hero"]["attack"], 120)

    def test_atomic_task_monitor_interval(self):
        """atomic_task 段的 monitor_interval 应在加载结果中可用。"""
        result = self.cfg.load_task("war3.jiubing2.tasks.reputation.daily_reputation")
        self.assertEqual(result.get("atomic_task", {}).get("monitor_interval"), 0.2)

    def test_clear_nearby_interval_in_parent(self):
        """clear_nearby_interval 应在父级 daily_reputation 段中。"""
        result = self.cfg.load_task("war3.jiubing2.tasks.reputation.daily_reputation")
        daily = result["tasks"]["reputation"]["daily_reputation"]
        self.assertEqual(daily.get("clear_nearby_interval"), 120)
        # 子表不应有 clear_nearby_interval
        self.assertNotIn("clear_nearby_interval", daily.get("blackstone", {}))
        self.assertNotIn("clear_nearby_interval", daily.get("forest", {}))


class TestReputationTaskConfigPath(TestDailyReputationBase):
    """测试 BlackstoneReputationTask / ForestReputationTask 的 task_config_path
    指向嵌套子表。"""

    def test_blackstone_config_path(self):
        """BlackstoneReputationTask.task_config_path 应指向 daily_reputation.blackstone。"""
        with patch.dict(
            "sys.modules",
            {
                "win32com": MagicMock(),
                "win32com.client": MagicMock(),
                "pythoncom": MagicMock(),
                "pywintypes": MagicMock(),
            },
        ):
            from GameBot.runner.tasks.war3.jiubing2.reputation.blackstone_reputation import BlackstoneReputationTask

            self.assertEqual(
                BlackstoneReputationTask.task_config_path,
                ("war3", "jiubing2", "tasks", "reputation", "daily_reputation", "blackstone"),
            )

    def test_forest_config_path(self):
        """ForestReputationTask.task_config_path 应指向 daily_reputation.forest。"""
        with patch.dict(
            "sys.modules",
            {
                "win32com": MagicMock(),
                "win32com.client": MagicMock(),
                "pythoncom": MagicMock(),
                "pywintypes": MagicMock(),
            },
        ):
            from GameBot.runner.tasks.war3.jiubing2.reputation.forest_reputation import ForestReputationTask

            self.assertEqual(
                ForestReputationTask.task_config_path,
                ("war3", "jiubing2", "tasks", "reputation", "daily_reputation", "forest"),
            )

    def test_blackstone_cfg_extracted(self):
        """通过 task_config_path 从合并配置中提取黑石城子表。"""
        result = self.cfg.load_task("war3.jiubing2.tasks.reputation.daily_reputation")
        path = ("tasks", "reputation", "daily_reputation", "blackstone")
        cfg = result
        for key in path:
            cfg = cfg.get(key, {})
        self.assertEqual(cfg["name"], "每日黑石城声望")
        self.assertEqual(cfg["target_reputation"], 150)
        self.assertEqual(cfg["reputation_per_run"], 5)

    def test_forest_cfg_extracted(self):
        """通过 task_config_path 从合并配置中提取森之城子表。"""
        result = self.cfg.load_task("war3.jiubing2.tasks.reputation.daily_reputation")
        path = ("tasks", "reputation", "daily_reputation", "forest")
        cfg = result
        for key in path:
            cfg = cfg.get(key, {})
        self.assertEqual(cfg["name"], "每日森之城声望")
        self.assertEqual(cfg["target_reputation"], 150)
        self.assertEqual(cfg["reputation_per_run"], 10)

    def test_parent_cfg_extracted(self):
        """_parent_cfg 应为 daily_reputation 段（子表的父级）。"""
        result = self.cfg.load_task("war3.jiubing2.tasks.reputation.daily_reputation")
        parent_path = ("tasks", "reputation", "daily_reputation")
        parent = result
        for key in parent_path:
            parent = parent.get(key, {})
        self.assertEqual(parent.get("clear_nearby_interval"), 120)
        self.assertEqual(parent.get("name"), "每日声望")


class TestEffectiveTimes(TestDailyReputationBase):
    """测试 ReputationTask._effective_times 次数反推逻辑。"""

    def _make_reputation_task(self, sub_cfg):
        """构造一个最小可用的 ReputationTask 实例（不触发 DmClient 初始化）。"""
        with patch.dict(
            "sys.modules",
            {
                "win32com": MagicMock(),
                "win32com.client": MagicMock(),
                "pythoncom": MagicMock(),
                "pywintypes": MagicMock(),
            },
        ):
            from GameBot.runner.tasks.war3.jiubing2.base import ReputationTask
        task = ReputationTask.__new__(ReputationTask)
        task.cfg = sub_cfg
        task.atomic_name = "测试"
        return task

    def test_blackstone_times(self):
        """黑石城：150 / 5 = 30 次。"""
        result = self.cfg.load_task("war3.jiubing2.tasks.reputation.daily_reputation")
        sub = result["tasks"]["reputation"]["daily_reputation"]["blackstone"]
        task = self._make_reputation_task(sub)
        self.assertEqual(task._effective_times(), 30)

    def test_forest_times(self):
        """森之城：150 / 10 = 15 次。"""
        result = self.cfg.load_task("war3.jiubing2.tasks.reputation.daily_reputation")
        sub = result["tasks"]["reputation"]["daily_reputation"]["forest"]
        task = self._make_reputation_task(sub)
        self.assertEqual(task._effective_times(), 15)

    def test_uneven_division(self):
        """不整除时向上取整：150 / 7 = ceil(21.43) = 22。"""
        sub = {"target_reputation": 150, "reputation_per_run": 7}
        task = self._make_reputation_task(sub)
        self.assertEqual(task._effective_times(), math.ceil(150 / 7))

    def test_default_values(self):
        """未配置时使用默认值 150 / 5 = 30。"""
        task = self._make_reputation_task({})
        self.assertEqual(task._effective_times(), 30)


class TestParentCfgFallback(TestDailyReputationBase):
    """测试子表未配置 clear_nearby_interval 时从父级 fallback。"""

    def test_clear_nearby_fallback_to_parent(self):
        """子表无 clear_nearby_interval 时，_parent_cfg 应提供该值。"""
        result = self.cfg.load_task("war3.jiubing2.tasks.reputation.daily_reputation")

        # 模拟 __init__ 中的 _parent_cfg 计算
        path = ("tasks", "reputation", "daily_reputation", "blackstone")
        sub_cfg = result
        for key in path:
            sub_cfg = sub_cfg.get(key, {})
        parent_cfg = result
        for key in path[:-1]:
            parent_cfg = parent_cfg.get(key, {})

        # 子表无 clear_nearby_interval
        self.assertNotIn("clear_nearby_interval", sub_cfg)
        # 父级有
        self.assertEqual(parent_cfg.get("clear_nearby_interval"), 120)
        # fallback 逻辑：子表无则用父级
        val = sub_cfg.get("clear_nearby_interval", parent_cfg.get("clear_nearby_interval", 0))
        self.assertEqual(val, 120)

    def test_no_parent_clear_nearby_defaults_zero(self):
        """父级也无 clear_nearby_interval 时默认 0（禁用）。"""
        # 构造无 clear_nearby_interval 的父级
        parent_cfg = {}
        sub_cfg = {}
        val = sub_cfg.get("clear_nearby_interval", parent_cfg.get("clear_nearby_interval", 0))
        self.assertEqual(val, 0)


class TestDailyReputationRun(TestDailyReputationBase):
    """测试 DailyReputationTask.run 的 enable 开关路由逻辑。"""

    def _make_daily_task(self, cfg_override=None):
        """构造一个 mock 版 DailyReputationTask（不触发 DmClient 初始化）。"""
        result = self.cfg.load_task("war3.jiubing2.tasks.reputation.daily_reputation")
        daily_cfg = result["tasks"]["reputation"]["daily_reputation"]
        if cfg_override:
            daily_cfg.update(cfg_override)

        # 用 __new__ 跳过 __init__ 中的 BlackstoneReputationTask / ForestReputationTask 创建
        with patch.dict(
            "sys.modules",
            {
                "win32com": MagicMock(),
                "win32com.client": MagicMock(),
                "pythoncom": MagicMock(),
                "pywintypes": MagicMock(),
            },
        ):
            from GameBot.runner.tasks.war3.jiubing2.reputation.daily_reputation import DailyReputationTask
        task = DailyReputationTask.__new__(DailyReputationTask)
        task.cfg = daily_cfg
        task.blackstone = MagicMock()
        task.forest = MagicMock()
        return task

    def test_run_both_enabled(self):
        """enable_blackstone=true, enable_forest=true → 两个子任务都执行。"""
        task = self._make_daily_task({"enable_blackstone": True, "enable_forest": True})
        task.run()
        task.blackstone.run.assert_called_once()
        task.forest.run.assert_called_once()

    def test_run_only_blackstone(self):
        """enable_blackstone=true, enable_forest=false → 只执行黑石城。"""
        task = self._make_daily_task({"enable_blackstone": True, "enable_forest": False})
        task.run()
        task.blackstone.run.assert_called_once()
        task.forest.run.assert_not_called()

    def test_run_only_forest(self):
        """enable_blackstone=false, enable_forest=true → 只执行森之城。"""
        task = self._make_daily_task({"enable_blackstone": False, "enable_forest": True})
        task.run()
        task.blackstone.run.assert_not_called()
        task.forest.run.assert_called_once()

    def test_run_neither_enabled(self):
        """两个都 false → 都不执行。"""
        task = self._make_daily_task({"enable_blackstone": False, "enable_forest": False})
        task.run()
        task.blackstone.run.assert_not_called()
        task.forest.run.assert_not_called()

    def test_run_passes_stop_event(self):
        """run 应将 stop_event 传递给子任务。"""
        task = self._make_daily_task()
        stop_event = MagicMock()
        stop_event.is_set.return_value = False
        task.run(stop_event=stop_event)
        task.blackstone.run.assert_called_once_with(stop_event=stop_event, progress_lines_callback=None)
        task.forest.run.assert_called_once_with(stop_event=stop_event, progress_lines_callback=None)

    def test_task_name(self):
        """task_name 应从配置中读取。"""
        task = self._make_daily_task()
        self.assertEqual(task.task_name, "每日声望")

    def test_task_name_default(self):
        """未配置 name 时 task_name 应返回默认值。"""
        task = self._make_daily_task()
        task.cfg = {}
        self.assertEqual(task.task_name, "每日声望")


if __name__ == "__main__":
    unittest.main()
