"""配置系统边界测试 — 补充 test_config.py 未覆盖的边界和异常场景。

覆盖范围：
- _deep_merge 边界：list 覆盖 dict、None 覆盖、空 dict 合并
- _split_sections 边界：空文件、仅含控制键、全部命名空间节点
- _file_path_for 回退路径：同名目录文件、base.toml 回退
- _resolve_order 边界：自依赖、菱形依赖、空依赖
- load_task 缓存失效：user_configs.json 修改后缓存失效
- _apply_user_overrides 边界：combat_mode 写入、route_scheme 写入、blackstone/forest_points
- get_path 方法：相对路径解析、绝对路径、空值回退
"""

import json
import shutil
import tempfile
import unittest
from pathlib import Path

import pytest

from GameBot.config import ConfigurationError
from tests.common.config_helpers import ConfigTestBase
from tests.common.config_helpers import write_toml as _write_toml

pytestmark = [pytest.mark.unit, pytest.mark.config]


def _make_edge_config_dir() -> Path:
    """创建边界测试用的临时 config 目录。"""
    tmp = Path(tempfile.mkdtemp(prefix="jiubing2_edge_"))

    _write_toml(
        tmp,
        "base.toml",
        """
extends = []
[paths]
log_path = "logs"
""",
    )

    _write_toml(
        tmp,
        "war3/war3.toml",
        """
extends = ["base"]

[this]
window_class = "War3Class"
""",
    )

    _write_toml(
        tmp,
        "war3/jiubing2/jiubing2.toml",
        """
extends = ["war3"]

[game]
load_war3_time = 33

[hero]
inventory = ["A", "B", "C"]
""",
    )

    _write_toml(
        tmp,
        "war3/jiubing2/heroes/mk.toml",
        """
extends = []
[hero]
inventory = ["D", "E", "F"]
attack = 100
""",
    )

    _write_toml(
        tmp,
        "war3/jiubing2/heroes/lancer.toml",
        """
extends = []
[hero]
inventory = ["G", "H", "I"]
attack = 80
defense = 50
""",
    )

    _write_toml(
        tmp,
        "war3/jiubing2/tasks/others/fishing.toml",
        """
extends = ["war3.jiubing2", "war3.jiubing2.heroes.mk"]

[this]
name = "钓鱼"
task_times = 5
""",
    )

    _write_toml(
        tmp,
        "war3/jiubing2/tasks/others/patrol_loot.toml",
        """
extends = ["war3.jiubing2", "war3.jiubing2.heroes.lancer"]

[this]
name = "巡逻拾取"
task_times = 3
""",
    )

    # 自依赖测试文件
    _write_toml(
        tmp,
        "self_circular.toml",
        """
extends = ["self_circular"]
[x]
val = 1
""",
    )

    # 菱形依赖：diamond_d → diamond_a, diamond_b → diamond_c → diamond_a, diamond_b
    _write_toml(
        tmp,
        "diamond_a.toml",
        """
extends = []
[a]
val = 1
""",
    )
    _write_toml(
        tmp,
        "diamond_b.toml",
        """
extends = ["diamond_a"]
[b]
val = 2
""",
    )
    _write_toml(
        tmp,
        "diamond_c.toml",
        """
extends = ["diamond_a", "diamond_b"]
[c]
val = 3
""",
    )
    _write_toml(
        tmp,
        "diamond_d.toml",
        """
extends = ["diamond_c"]
[d]
val = 4
""",
    )

    # 空依赖文件
    _write_toml(
        tmp,
        "empty_deps.toml",
        """
extends = []
[e]
val = 5
""",
    )

    # 仅含控制键的文件
    _write_toml(
        tmp,
        "control_only.toml",
        """
extends = ["base"]
""",
    )

    # 全部命名空间节点（无可继承节点）
    _write_toml(
        tmp,
        "war3/jiubing2/tasks/atomic/test_atomic.toml",
        """
extends = ["war3.jiubing2"]

[this]
name = "测试原子任务"
""",
    )

    # 同名目录文件布局：dir_same/dir_same.toml
    _write_toml(
        tmp,
        "dir_same/dir_same.toml",
        """
extends = []
[same]
val = 10
""",
    )

    # base.toml 回退布局：dir_base/base.toml
    _write_toml(
        tmp,
        "dir_base/base.toml",
        """
extends = []
[base_fallback]
val = 20
""",
    )

    return tmp


class TestEdgeBase(ConfigTestBase):
    """边界测试基类。"""

    def make_config_dir(self) -> Path:
        return _make_edge_config_dir()


class TestDeepMergeEdge(TestEdgeBase):
    """_deep_merge 边界测试。"""

    def test_list_overrides_dict(self):
        """list 值应完全覆盖 dict 值。"""
        base = {"x": {"y": 1}}
        override = {"x": [1, 2, 3]}
        self.cfg._deep_merge(base, override)
        self.assertEqual(base["x"], [1, 2, 3])

    def test_dict_overrides_list(self):
        """dict 值应完全覆盖 list 值。"""
        base = {"x": [1, 2, 3]}
        override = {"x": {"y": 1}}
        self.cfg._deep_merge(base, override)
        self.assertEqual(base["x"], {"y": 1})

    def test_none_overrides_value(self):
        """None 应覆盖已有值。"""
        base = {"x": 1}
        override = {"x": None}
        self.cfg._deep_merge(base, override)
        self.assertIsNone(base["x"])

    def test_empty_override_dict(self):
        """空 override 不改变 base。"""
        base = {"x": 1, "y": 2}
        self.cfg._deep_merge(base, {})
        self.assertEqual(base, {"x": 1, "y": 2})

    def test_empty_base_dict(self):
        """空 base 接受 override 全部内容。"""
        base = {}
        override = {"x": 1, "y": {"z": 2}}
        self.cfg._deep_merge(base, override)
        self.assertEqual(base, {"x": 1, "y": {"z": 2}})

    def test_deeply_nested_merge(self):
        """三层嵌套 dict 应递归合并。"""
        base = {"a": {"b": {"c": 1, "d": 2}}}
        override = {"a": {"b": {"c": 3, "e": 4}}}
        self.cfg._deep_merge(base, override)
        self.assertEqual(base, {"a": {"b": {"c": 3, "d": 2, "e": 4}}})

    def test_scalar_overrides_dict(self):
        """标量值应覆盖 dict。"""
        base = {"x": {"y": 1}}
        override = {"x": "string"}
        self.cfg._deep_merge(base, override)
        self.assertEqual(base["x"], "string")


class TestSplitSectionsEdge(TestEdgeBase):
    """_split_sections 边界测试。"""

    def test_empty_file(self):
        """空文件应返回两个空字典。"""
        _write_toml(self.config_dir, "empty.toml", "")
        raw = self.cfg._load_file("empty")
        inheritable, namespaced = self.cfg._split_sections(raw)
        self.assertEqual(inheritable, {})
        self.assertEqual(namespaced, {})

    def test_control_only_file(self):
        """仅含 name/extends 控制键的文件应返回两个空字典。"""
        raw = self.cfg._load_file("control_only")
        inheritable, namespaced = self.cfg._split_sections(raw)
        self.assertEqual(inheritable, {})
        self.assertEqual(namespaced, {})

    def test_all_namespaced(self):
        """全部为命名空间节点时应全部归入 namespaced。"""
        raw = self.cfg._load_file("war3.jiubing2.tasks.atomic.test_atomic")
        inheritable, namespaced = self.cfg._split_sections(raw)
        self.assertEqual(inheritable, {})
        self.assertIn("war3", namespaced)

    def test_mixed_sections(self):
        """混合节点应正确拆分。"""
        raw = self.cfg._load_file("war3.jiubing2")
        inheritable, namespaced = self.cfg._split_sections(raw)
        # game 和 hero 是可继承的
        self.assertIn("game", inheritable)
        self.assertIn("hero", inheritable)
        # war3 是命名空间
        self.assertNotIn("war3", inheritable)


class TestFilePathForEdge(TestEdgeBase):
    """_file_path_for 回退路径测试。"""

    def test_standard_path(self):
        """标准路径：config_dir / a / b / c.toml。"""
        path = self.cfg._file_path_for("war3.jiubing2.tasks.others.fishing")
        self.assertTrue(path.exists())
        self.assertEqual(path.name, "fishing.toml")

    def test_same_name_dir_fallback(self):
        """回退1：config_dir / dir_same / dir_same.toml。"""
        path = self.cfg._file_path_for("dir_same")
        self.assertTrue(path.exists())
        self.assertEqual(path.name, "dir_same.toml")

    def test_base_toml_fallback(self):
        """回退2：config_dir / dir_base / base.toml。"""
        path = self.cfg._file_path_for("dir_base")
        self.assertTrue(path.exists())
        self.assertEqual(path.name, "base.toml")

    def test_nonexistent_returns_standard_path(self):
        """不存在的配置名应返回标准路径（让调用方报错）。"""
        path = self.cfg._file_path_for("nonexistent.config.name")
        self.assertFalse(path.exists())
        self.assertEqual(path.name, "name.toml")


class TestResolveOrderEdge(TestEdgeBase):
    """_resolve_order 边界测试。"""

    def test_self_circular_dependency(self):
        """自依赖应抛出 ConfigurationError。"""
        order = []
        with self.assertRaises(ConfigurationError) as ctx:
            self.cfg._resolve_order("self_circular", order, [], set())
        self.assertIn("循环依赖", str(ctx.exception))

    def test_diamond_dependency(self):
        """菱形依赖：diamond_d → c → a, b → a，a 只出现一次。"""
        order = []
        self.cfg._resolve_order("diamond_d", order, [], set())
        # a 应在 b 和 c 之前
        self.assertLess(order.index("diamond_a"), order.index("diamond_b"))
        self.assertLess(order.index("diamond_a"), order.index("diamond_c"))
        self.assertLess(order.index("diamond_b"), order.index("diamond_c"))
        self.assertLess(order.index("diamond_c"), order.index("diamond_d"))
        # a 只出现一次
        self.assertEqual(order.count("diamond_a"), 1)

    def test_empty_extends(self):
        """空 extends 列表应正常加载，只包含自身。"""
        order = []
        self.cfg._resolve_order("empty_deps", order, [], set())
        self.assertEqual(order, ["empty_deps"])

    def test_already_visited_skips(self):
        """已 visited 的配置不应重复解析。"""
        order = []
        visited = set()
        self.cfg._resolve_order("diamond_d", order, [], visited)
        order_len_after_first = len(order)
        # 用同一个 visited 集合再次解析
        self.cfg._resolve_order("diamond_d", order, [], visited)
        self.assertEqual(len(order), order_len_after_first)


class TestLoadTaskCacheEdge(TestEdgeBase):
    """load_task 缓存失效测试。"""

    def test_cache_invalidated_on_user_config_change(self):
        """user_configs.json 修改后缓存应失效。"""
        fake_root = Path(tempfile.mkdtemp(prefix="jiubing2_cache_"))
        try:
            fake_config_dir = fake_root / "a" / "b" / "c" / "config"
            fake_config_dir.mkdir(parents=True)
            shutil.copytree(self.config_dir, fake_config_dir, dirs_exist_ok=True)
            self.cfg.config_path = fake_config_dir

            # 第一次加载
            result1 = self.cfg.load_task("war3.jiubing2.tasks.others.fishing")
            self.assertEqual(result1["hero"]["inventory"], ["D", "E", "F"])

            # 写入 user_configs.json 覆盖 inventory
            user_cfg_path = fake_root / "user_configs.json"
            user_cfg_path.write_text(json.dumps({"inventory": ["X", "Y", "Z"]}), encoding="utf-8")

            # 第二次加载应检测到 mtime 变化，缓存失效
            result2 = self.cfg.load_task("war3.jiubing2.tasks.others.fishing")
            self.assertEqual(result2["hero"]["inventory"], ["X", "Y", "Z"])
        finally:
            shutil.rmtree(fake_root, ignore_errors=True)

    def test_cache_valid_when_user_config_unchanged(self):
        """user_configs.json 未修改时缓存应有效（同一对象）。"""
        fake_root = Path(tempfile.mkdtemp(prefix="jiubing2_cache2_"))
        try:
            fake_config_dir = fake_root / "a" / "b" / "c" / "config"
            fake_config_dir.mkdir(parents=True)
            shutil.copytree(self.config_dir, fake_config_dir, dirs_exist_ok=True)
            self.cfg.config_path = fake_config_dir

            result1 = self.cfg.load_task("war3.jiubing2.tasks.others.fishing")
            result2 = self.cfg.load_task("war3.jiubing2.tasks.others.fishing")
            self.assertIs(result1, result2)
        finally:
            shutil.rmtree(fake_root, ignore_errors=True)


class TestApplyUserOverridesEdge(TestEdgeBase):
    """_apply_user_overrides 边界测试。"""

    def test_combat_mode_override(self):
        """combat_mode 应写入任务命名空间和每日声望子任务。"""
        fake_root = Path(tempfile.mkdtemp(prefix="jiubing2_combat_"))
        try:
            fake_config_dir = fake_root / "a" / "b" / "c" / "config"
            fake_config_dir.mkdir(parents=True)
            shutil.copytree(self.config_dir, fake_config_dir, dirs_exist_ok=True)
            self.cfg.config_path = fake_config_dir

            user_cfg_path = fake_root / "user_configs.json"
            user_cfg_path.write_text(json.dumps({"combat_mode": "cast_skills"}), encoding="utf-8")

            result = self.cfg.load_task("war3.jiubing2.tasks.others.patrol_loot")
            task_cfg = result["war3"]["jiubing2"]["tasks"]["others"]["patrol_loot"]
            self.assertEqual(task_cfg.get("combat_mode"), "cast_skills")
        finally:
            shutil.rmtree(fake_root, ignore_errors=True)

    def test_route_scheme_override(self):
        """route_scheme 应写入任务命名空间。"""
        fake_root = Path(tempfile.mkdtemp(prefix="jiubing2_route_"))
        try:
            fake_config_dir = fake_root / "a" / "b" / "c" / "config"
            fake_config_dir.mkdir(parents=True)
            shutil.copytree(self.config_dir, fake_config_dir, dirs_exist_ok=True)
            self.cfg.config_path = fake_config_dir

            user_cfg_path = fake_root / "user_configs.json"
            user_cfg_path.write_text(json.dumps({"route_scheme": "custom_route"}), encoding="utf-8")

            result = self.cfg.load_task("war3.jiubing2.tasks.others.patrol_loot")
            task_cfg = result["war3"]["jiubing2"]["tasks"]["others"]["patrol_loot"]
            self.assertEqual(task_cfg.get("route_scheme"), "custom_route")
        finally:
            shutil.rmtree(fake_root, ignore_errors=True)

    def test_blackstone_points_override(self):
        """blackstone_points 应写入城门骚扰原子任务命名空间。"""
        fake_root = Path(tempfile.mkdtemp(prefix="jiubing2_bs_pts_"))
        try:
            fake_config_dir = fake_root / "a" / "b" / "c" / "config"
            fake_config_dir.mkdir(parents=True)
            shutil.copytree(self.config_dir, fake_config_dir, dirs_exist_ok=True)
            self.cfg.config_path = fake_config_dir

            user_cfg_path = fake_root / "user_configs.json"
            user_cfg_path.write_text(
                json.dumps({"patrol_loot": {"blackstone_points": [[10, 20], [30, 40]]}}), encoding="utf-8"
            )

            result = self.cfg.load_task("war3.jiubing2.tasks.others.patrol_loot")
            bs_cfg = result["war3"]["jiubing2"]["tasks"]["atomic"]["blackstone_gate_harassment"]
            self.assertEqual(bs_cfg["points"], [[10, 20], [30, 40]])
        finally:
            shutil.rmtree(fake_root, ignore_errors=True)

    def test_forest_points_override(self):
        """forest_points 应写入迅猛野兽原子任务命名空间。"""
        fake_root = Path(tempfile.mkdtemp(prefix="jiubing2_fr_pts_"))
        try:
            fake_config_dir = fake_root / "a" / "b" / "c" / "config"
            fake_config_dir.mkdir(parents=True)
            shutil.copytree(self.config_dir, fake_config_dir, dirs_exist_ok=True)
            self.cfg.config_path = fake_config_dir

            user_cfg_path = fake_root / "user_configs.json"
            user_cfg_path.write_text(
                json.dumps({"patrol_loot": {"forest_points": [[50, 60], [70, 80]]}}), encoding="utf-8"
            )

            result = self.cfg.load_task("war3.jiubing2.tasks.others.patrol_loot")
            swift_cfg = result["war3"]["jiubing2"]["tasks"]["atomic"]["swift_beast"]
            self.assertEqual(swift_cfg["points"], [[50, 60], [70, 80]])
        finally:
            shutil.rmtree(fake_root, ignore_errors=True)

    def test_extra_fields_merged_to_task(self):
        """非特殊键应合并到任务命名空间。"""
        fake_root = Path(tempfile.mkdtemp(prefix="jiubing2_extra_"))
        try:
            fake_config_dir = fake_root / "a" / "b" / "c" / "config"
            fake_config_dir.mkdir(parents=True)
            shutil.copytree(self.config_dir, fake_config_dir, dirs_exist_ok=True)
            self.cfg.config_path = fake_config_dir

            user_cfg_path = fake_root / "user_configs.json"
            user_cfg_path.write_text(
                json.dumps({"patrol_loot": {"custom_field": 42, "custom_list": [1, 2, 3]}}), encoding="utf-8"
            )

            result = self.cfg.load_task("war3.jiubing2.tasks.others.patrol_loot")
            task_cfg = result["war3"]["jiubing2"]["tasks"]["others"]["patrol_loot"]
            self.assertEqual(task_cfg.get("custom_field"), 42)
            self.assertEqual(task_cfg.get("custom_list"), [1, 2, 3])
        finally:
            shutil.rmtree(fake_root, ignore_errors=True)

    def test_old_user_config_json_compat(self):
        """旧格式 user_config.json（无 active/configs）应兼容。"""
        fake_root = Path(tempfile.mkdtemp(prefix="jiubing2_old_cfg_"))
        try:
            fake_config_dir = fake_root / "a" / "b" / "c" / "config"
            fake_config_dir.mkdir(parents=True)
            shutil.copytree(self.config_dir, fake_config_dir, dirs_exist_ok=True)
            self.cfg.config_path = fake_config_dir

            # 写入旧格式 user_config.json（非 user_configs.json）
            old_path = fake_root / "user_config.json"
            old_path.write_text(json.dumps({"inventory": ["OLD", "FORMAT"]}), encoding="utf-8")

            result = self.cfg.load_task("war3.jiubing2.tasks.others.fishing")
            self.assertEqual(result["hero"]["inventory"], ["OLD", "FORMAT"])
        finally:
            shutil.rmtree(fake_root, ignore_errors=True)


class TestGetPath(TestEdgeBase):
    """get_path 方法测试。"""

    def test_get_path_relative(self):
        """相对路径应以 project_root 为基准解析。"""
        self.cfg.load_task("war3.jiubing2.tasks.others.fishing")
        path = self.cfg.get_path("paths.log_path")
        self.assertTrue(path.is_absolute())
        self.assertEqual(path.name, "logs")

    def test_get_path_empty_returns_project_root(self):
        """空值应返回 project_root。"""
        self.cfg.load_task("war3.jiubing2.tasks.others.fishing")
        path = self.cfg.get_path("nonexistent.key", "")
        self.assertEqual(path, self.cfg.project_root)

    def test_get_path_absolute(self):
        """绝对路径应直接返回。"""
        self.cfg.load_task("war3.jiubing2.tasks.others.fishing")
        abs_path = "C:/some/absolute/path"
        path = self.cfg.get_path("nonexistent.key", abs_path)
        self.assertEqual(str(path).replace("\\", "/"), abs_path)


class TestHeroShallowMerge(TestEdgeBase):
    """[hero] 浅合并测试。"""

    def test_hero_shallow_merge_preserves_other_keys(self):
        """任务配置只写 inventory 时不应丢失英雄的 skills 等属性。"""
        # 在 fishing 任务中添加 hero.inventory 覆盖
        _write_toml(
            self.config_dir,
            "war3/jiubing2/tasks/others/fishing.toml",
            """
extends = ["war3.jiubing2", "war3.jiubing2.heroes.mk"]

[this]
name = "钓鱼"
task_times = 5

[hero]
inventory = ["CUSTOM", "ITEM"]
""",
        )

        result = self.cfg.load_task("war3.jiubing2.tasks.others.fishing")
        # inventory 应被覆盖
        self.assertEqual(result["hero"]["inventory"], ["CUSTOM", "ITEM"])
        # attack 应保留（来自 mk.toml）
        self.assertEqual(result["hero"]["attack"], 100)


if __name__ == "__main__":
    unittest.main()
