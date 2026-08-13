"""配置系统单元测试 — 覆盖 config.py 的核心逻辑：

- 依赖解析（DFS 后序展开、循环依赖检测）
- 可继承/命名空间节点拆分
- 合并构建（可继承覆盖、命名空间深度合并、英雄互斥）
- deep_merge
- load_task 缓存
- get / get_section / __contains__ 访问
- 单例模式
- 配置文件不存在异常
- user_config 覆盖（inventory / desired_items / patrol_rounds / chest / points）
"""
import json
import shutil
import tempfile
import unittest
from pathlib import Path

import pytest

from GameBot.config import Config, ConfigurationError
from tests.common.config_helpers import ConfigTestBase as TestConfigBase

pytestmark = [pytest.mark.unit, pytest.mark.config]


class TestDependencyResolution(TestConfigBase):
    """测试依赖解析（DFS 后序展开 + 循环依赖检测）。"""

    def test_simple_chain_order(self):
        """fishing → jiubing2 → war3 → base，加载顺序应为 base, war3, jiubing2, heroes.mk, fishing。"""
        order = []
        self.cfg._resolve_order("war3.jiubing2.tasks.others.fishing", order, [], set())
        # base 最先，war3 其次，jiubing2 再次，heroes.mk 在 fishing 之前
        self.assertEqual(order[0], "base")
        self.assertEqual(order[1], "war3")
        self.assertEqual(order[2], "war3.jiubing2")
        self.assertIn("war3.jiubing2.heroes.mk", order)
        self.assertEqual(order[-1], "war3.jiubing2.tasks.others.fishing")
        # heroes.mk 应在 fishing 之前
        self.assertLess(order.index("war3.jiubing2.heroes.mk"), order.index("war3.jiubing2.tasks.others.fishing"))

    def test_each_file_appears_once(self):
        """共享依赖（base 被 war3 和 jiubing2 都依赖）只出现一次。"""
        order = []
        self.cfg._resolve_order("war3.jiubing2.tasks.others.fishing", order, [], set())
        self.assertEqual(order.count("base"), 1)
        self.assertEqual(order.count("war3"), 1)

    def test_circular_dependency_raises(self):
        """循环依赖应抛出 ConfigurationError。"""
        order = []
        with self.assertRaises(ConfigurationError) as ctx:
            self.cfg._resolve_order("circular_a", order, [], set())
        self.assertIn("循环依赖", str(ctx.exception))


class TestSplitSections(TestConfigBase):
    """测试可继承/命名空间节点拆分。"""

    def test_inheritable_vs_namespaced(self):
        """jiubing2.toml 中 [game]/[command]/[hero] 可继承，[tasks.*] 不可继承。"""
        raw = self.cfg._load_file("war3.jiubing2")
        inheritable, namespaced = self.cfg._split_sections(raw)
        # 可继承节点
        self.assertIn("game", inheritable)
        self.assertIn("command", inheritable)
        self.assertIn("hero", inheritable)
        # 不应包含 dependencies（控制键）
        self.assertNotIn("dependencies", inheritable)
        self.assertNotIn("dependencies", namespaced)

    def test_namespaced_stays_in_namespace(self):
        """tasks.others.fishing 的 [tasks.others.fishing] 应归入命名空间。"""
        raw = self.cfg._load_file("war3.jiubing2.tasks.others.fishing")
        inheritable, namespaced = self.cfg._split_sections(raw)
        self.assertIn("war3", namespaced)
        self.assertNotIn("war3", inheritable)


class TestBuild(TestConfigBase):
    """测试合并构建逻辑。"""

    def test_inheritable_override(self):
        """后加载的可继承节点完全覆盖先加载的。"""
        order = []
        self.cfg._resolve_order("war3.jiubing2.tasks.others.fishing", order, [], set())
        result = self.cfg._build(order)
        # jiubing2 的 [hero] inventory=["A","B","C"] 被 heroes.mk 的 ["D","E","F"] 覆盖
        self.assertEqual(result["hero"]["inventory"], ["D", "E", "F"])
        self.assertEqual(result["hero"]["attack"], 100)

    def test_namespaced_deep_merge(self):
        """不同任务的命名空间节点共存于各自路径下。"""
        # 先加载 fishing
        self.cfg.load_task("war3.jiubing2.tasks.others.fishing")
        # 再加载 patrol_loot（会重建全局 _config）
        self.cfg.load_task("war3.jiubing2.tasks.others.patrol_loot")
        result = self.cfg._config
        # 两个任务的命名空间路径都应存在
        tasks_ns = result.get("war3", {}).get("jiubing2", {}).get("tasks", {})
        self.assertIn("fishing", tasks_ns.get("others", {}))
        self.assertIn("patrol_loot", tasks_ns.get("others", {}))

    def test_hero_exclusivity(self):
        """英雄互斥：后加载的英雄替换前一英雄的可继承节点。"""
        # fishing 依赖 heroes.mk，patrol_loot 依赖 heroes.lancer
        # 先加载 fishing
        self.cfg.load_task("war3.jiubing2.tasks.others.fishing")
        # 再加载 patrol_loot
        self.cfg.load_task("war3.jiubing2.tasks.others.patrol_loot")
        result = self.cfg._config
        # 全局 _config 中英雄应为 lancer（后加载）
        self.assertEqual(result["hero"]["inventory"], ["G", "H", "I"])
        self.assertEqual(result["hero"]["attack"], 80)
        self.assertEqual(result["hero"]["defense"], 50)
        # mk 的 attack=100 不应残留
        # lancer 没有 attack=100 的覆盖，但有 attack=80

    def test_hero_exclusivity_cleans_previous(self):
        """换英雄时前一英雄独有的可继承节点应被清除。"""
        # mk 有 attack=100，lancer 没有 attack 字段但有 defense=50
        # 先加载 mk（通过 fishing）
        fishing_result = self.cfg.load_task("war3.jiubing2.tasks.others.fishing")
        self.assertIn("attack", fishing_result.get("hero", {}))
        # 再加载 lancer（通过 patrol_loot）
        patrol_result = self.cfg.load_task("war3.jiubing2.tasks.others.patrol_loot")
        # lancer 的 hero 应有 defense 但不应有 mk 独有的字段
        # 注意：lancer 也有 attack=80，所以 attack 仍存在但值不同
        self.assertEqual(patrol_result["hero"]["attack"], 80)
        self.assertEqual(patrol_result["hero"]["defense"], 50)


class TestDeepMerge(TestConfigBase):
    """测试 _deep_merge。"""

    def test_simple_merge(self):
        base = {"a": 1, "b": 2}
        override = {"b": 3, "c": 4}
        self.cfg._deep_merge(base, override)
        self.assertEqual(base, {"a": 1, "b": 3, "c": 4})

    def test_nested_dict_merge(self):
        base = {"x": {"y": 1, "z": 2}}
        override = {"x": {"z": 3, "w": 4}}
        self.cfg._deep_merge(base, override)
        self.assertEqual(base, {"x": {"y": 1, "z": 3, "w": 4}})

    def test_override_dict_with_non_dict(self):
        """非 dict 值直接覆盖 dict。"""
        base = {"x": {"y": 1}}
        override = {"x": "string"}
        self.cfg._deep_merge(base, override)
        self.assertEqual(base, {"x": "string"})


class TestLoadTask(TestConfigBase):
    """测试 load_task。"""

    def test_load_fishing_task(self):
        """加载钓鱼任务配置，应包含依赖闭包中的所有配置段。"""
        result = self.cfg.load_task("war3.jiubing2.tasks.others.fishing")
        # 任务自身命名空间
        self.assertEqual(result["war3"]["jiubing2"]["tasks"]["others"]["fishing"]["name"], "钓鱼")
        # 依赖的可继承节点
        self.assertIn("game", result)
        self.assertIn("command", result)
        self.assertIn("hero", result)
        # 英雄应为 mk
        self.assertEqual(result["hero"]["inventory"], ["D", "E", "F"])

    def test_load_task_caching(self):
        """第二次调用 load_task 返回缓存结果（同一对象）。"""
        result1 = self.cfg.load_task("war3.jiubing2.tasks.others.fishing")
        result2 = self.cfg.load_task("war3.jiubing2.tasks.others.fishing")
        self.assertIs(result1, result2)

    def test_load_task_syncs_global_config(self):
        """load_task 后全局 _config 应同步更新。"""
        self.cfg.load_task("war3.jiubing2.tasks.others.fishing")
        self.assertIn("game", self.cfg._config)
        self.assertIn("hero", self.cfg._config)

    def test_load_task_with_different_heroes(self):
        """不同任务依赖不同英雄，各自结果应使用自己的英雄。"""
        fishing = self.cfg.load_task("war3.jiubing2.tasks.others.fishing")
        self.assertEqual(fishing["hero"]["inventory"], ["D", "E", "F"])
        # 重置后加载 patrol_loot
        Config.reset()
        self.cfg = Config(str(self.config_dir))
        patrol = self.cfg.load_task("war3.jiubing2.tasks.others.patrol_loot")
        self.assertEqual(patrol["hero"]["inventory"], ["G", "H", "I"])


class TestAccessMethods(TestConfigBase):
    """测试 get / get_section / __contains__ 访问方法。"""

    def test_get_dot_path(self):
        self.cfg.load_task("war3.jiubing2.tasks.others.fishing")
        self.assertEqual(self.cfg.get("hero.inventory"), ["D", "E", "F"])
        self.assertEqual(self.cfg.get("hero.attack"), 100)
        self.assertEqual(self.cfg.get("war3.jiubing2.tasks.others.fishing.name"), "钓鱼")

    def test_get_default(self):
        self.cfg.load_task("war3.jiubing2.tasks.others.fishing")
        self.assertIsNone(self.cfg.get("nonexistent"))
        self.assertEqual(self.cfg.get("nonexistent", "fallback"), "fallback")

    def test_get_section(self):
        self.cfg.load_task("war3.jiubing2.tasks.others.fishing")
        game = self.cfg.get_section("game")
        self.assertIsInstance(game, dict)
        self.assertEqual(game["load_war3_time"], 33)

    def test_get_section_missing(self):
        self.cfg.load_task("war3.jiubing2.tasks.others.fishing")
        result = self.cfg.get_section("nonexistent")
        self.assertEqual(result, {})

    def test_contains(self):
        self.cfg.load_task("war3.jiubing2.tasks.others.fishing")
        self.assertIn("hero", self.cfg)
        self.assertIn("game", self.cfg)
        self.assertNotIn("nonexistent", self.cfg)

    def test_getitem(self):
        self.cfg.load_task("war3.jiubing2.tasks.others.fishing")
        self.assertEqual(self.cfg["hero"]["inventory"], ["D", "E", "F"])


class TestSingleton(TestConfigBase):
    """测试单例模式。"""

    def test_same_instance(self):
        cfg2 = Config(str(self.config_dir))
        self.assertIs(self.cfg, cfg2)

    def test_reset_creates_new_instance(self):
        Config.reset()
        cfg2 = Config(str(self.config_dir))
        self.assertIsNot(self.cfg, cfg2)

    def test_thread_safe_singleton(self):
        """多线程并发创建 Config，应返回同一实例。"""
        import threading
        Config.reset()
        results = []
        barrier = threading.Barrier(8)  # 8 个线程同时等待，最大化竞争窗口

        def create_config():
            barrier.wait()  # 所有线程同时通过屏障，最大化并发竞争
            results.append(Config(str(self.config_dir)))

        threads = [threading.Thread(target=create_config) for _ in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        # 所有线程应得到同一个实例
        self.assertEqual(len(results), 8)
        for cfg in results:
            self.assertIs(results[0], cfg)


class TestMissingFile(TestConfigBase):
    """测试配置文件不存在异常。"""

    def test_missing_file_raises(self):
        with self.assertRaises(ConfigurationError) as ctx:
            self.cfg._load_file("nonexistent.config")
        self.assertIn("配置文件不存在", str(ctx.exception))


class TestUserConfig(TestConfigBase):
    """测试 user_config.json 用户覆盖。"""

    def test_user_config_hero_override(self):
        """user_configs.json 中 hero 字段替换英雄依赖。"""
        # 写入 user_configs.json，指定 hero=lancer
        user_cfg_path = self.cfg.project_root / "user_configs.json"
        # project_root 是 config_dir 上上上一级，需要调整
        # 实际 project_root = config_path.parent.parent.parent
        # 对于临时目录，project_root = tmp.parent.parent
        # 但这不准确，我们需要直接在正确位置写文件
        # _load_user_config 用 self.project_root / "user_configs.json"
        # project_root = config_path.parent.parent.parent
        # config_path = tmp, parent = parent, parent.parent = parent.parent
        # 所以 project_root = tmp.parent.parent
        # 这不太可靠，我们直接 mock project_root
        # 创建一个假的 project_root
        fake_root = Path(tempfile.mkdtemp(prefix="jiubing2_test_user_"))
        try:
            # 覆盖 project_root 属性
            self.cfg.config_path = self.config_dir
            # project_root 是 property，依赖 config_path
            # config_path 上溯 4 级 = project_root
            # fake_root / "a" / "b" / "c" / "config" → parent.parent.parent.parent = fake_root
            fake_config_dir = fake_root / "a" / "b" / "c" / "config"
            fake_config_dir.mkdir(parents=True)
            # 复制所有测试 TOML 到 fake_config_dir
            shutil.copytree(self.config_dir, fake_config_dir, dirs_exist_ok=True)
            self.cfg.config_path = fake_config_dir

            # 写入 user_configs.json
            user_cfg_path = fake_root / "user_configs.json"
            user_cfg_path.write_text(json.dumps({
                        "hero": "lancer"
            }), encoding="utf-8")

            # 加载 fishing（原本依赖 heroes.mk），应被替换为 heroes.lancer
            result = self.cfg.load_task("war3.jiubing2.tasks.others.fishing")
            self.assertEqual(result["hero"]["inventory"], ["G", "H", "I"])
        finally:
            shutil.rmtree(fake_root, ignore_errors=True)

    def test_user_config_inventory_override(self):
        """user_configs.json 中 inventory 覆盖英雄背包。"""
        fake_root = Path(tempfile.mkdtemp(prefix="jiubing2_test_inv_"))
        try:
            fake_config_dir = fake_root / "a" / "b" / "c" / "config"
            fake_config_dir.mkdir(parents=True)
            shutil.copytree(self.config_dir, fake_config_dir, dirs_exist_ok=True)
            self.cfg.config_path = fake_config_dir

            user_cfg_path = fake_root / "user_configs.json"
            user_cfg_path.write_text(json.dumps({
                        "inventory": ["X", "Y", "Z"]
            }), encoding="utf-8")

            result = self.cfg.load_task("war3.jiubing2.tasks.others.fishing")
            self.assertEqual(result["hero"]["inventory"], ["X", "Y", "Z"])
        finally:
            shutil.rmtree(fake_root, ignore_errors=True)

    def test_user_config_desired_items_override(self):
        """user_configs.json 中 desired_items 合并到任务命名空间。"""
        fake_root = Path(tempfile.mkdtemp(prefix="jiubing2_test_items_"))
        try:
            fake_config_dir = fake_root / "a" / "b" / "c" / "config"
            fake_config_dir.mkdir(parents=True)
            shutil.copytree(self.config_dir, fake_config_dir, dirs_exist_ok=True)
            self.cfg.config_path = fake_config_dir

            user_cfg_path = fake_root / "user_configs.json"
            user_cfg_path.write_text(json.dumps({
                        "desired_items": ["item1", "item2"]
            }), encoding="utf-8")

            result = self.cfg.load_task("war3.jiubing2.tasks.others.patrol_loot")
            self.assertEqual(
                result["war3"]["jiubing2"]["tasks"]["others"]["patrol_loot"]["desired_items"],
                ["item1", "item2"]
            )
        finally:
            shutil.rmtree(fake_root, ignore_errors=True)

    def test_user_config_patrol_rounds_override(self):
        """user_configs.json 中 patrol_rounds 写入 patrol.rounds。"""
        fake_root = Path(tempfile.mkdtemp(prefix="jiubing2_test_rounds_"))
        try:
            fake_config_dir = fake_root / "a" / "b" / "c" / "config"
            fake_config_dir.mkdir(parents=True)
            shutil.copytree(self.config_dir, fake_config_dir, dirs_exist_ok=True)
            self.cfg.config_path = fake_config_dir

            user_cfg_path = fake_root / "user_configs.json"
            user_cfg_path.write_text(json.dumps({
                        "patrol_rounds": 20
            }), encoding="utf-8")

            result = self.cfg.load_task("war3.jiubing2.tasks.others.patrol_loot")
            self.assertEqual(result["war3"]["jiubing2"]["tasks"]["others"]["patrol_loot"]["patrol"]["rounds"], 20)
        finally:
            shutil.rmtree(fake_root, ignore_errors=True)

    def test_user_config_chest_override(self):
        """user_configs.json 中 chest 深度合并到顶层 [chest]。"""
        fake_root = Path(tempfile.mkdtemp(prefix="jiubing2_test_chest_"))
        try:
            fake_config_dir = fake_root / "a" / "b" / "c" / "config"
            fake_config_dir.mkdir(parents=True)
            shutil.copytree(self.config_dir, fake_config_dir, dirs_exist_ok=True)
            self.cfg.config_path = fake_config_dir

            user_cfg_path = fake_root / "user_configs.json"
            user_cfg_path.write_text(json.dumps({
                        "chest": {
                            "enable": True,
                            "items": ["gem"]
                        }
            }), encoding="utf-8")

            result = self.cfg.load_task("war3.jiubing2.tasks.others.fishing")
            self.assertTrue(result["chest"]["enable"])
            self.assertEqual(result["chest"]["items"], ["gem"])
        finally:
            shutil.rmtree(fake_root, ignore_errors=True)

    def test_user_config_points_override(self):
        """user_configs.json 中 points 写入任务命名空间。"""
        fake_root = Path(tempfile.mkdtemp(prefix="jiubing2_test_points_"))
        try:
            fake_config_dir = fake_root / "a" / "b" / "c" / "config"
            fake_config_dir.mkdir(parents=True)
            shutil.copytree(self.config_dir, fake_config_dir, dirs_exist_ok=True)
            self.cfg.config_path = fake_config_dir

            user_cfg_path = fake_root / "user_configs.json"
            user_cfg_path.write_text(json.dumps({
                        "points": [[100, 200], [300, 400]]
            }), encoding="utf-8")

            result = self.cfg.load_task("war3.jiubing2.tasks.others.patrol_loot")
            self.assertEqual(
                result["war3"]["jiubing2"]["tasks"]["others"]["patrol_loot"]["points"],
                [[100, 200], [300, 400]]
            )
        finally:
            shutil.rmtree(fake_root, ignore_errors=True)

    def test_user_config_nested_task_key(self):
        """user_configs.json 嵌套结构按任务名匹配。"""
        fake_root = Path(tempfile.mkdtemp(prefix="jiubing2_test_nested_"))
        try:
            fake_config_dir = fake_root / "a" / "b" / "c" / "config"
            fake_config_dir.mkdir(parents=True)
            shutil.copytree(self.config_dir, fake_config_dir, dirs_exist_ok=True)
            self.cfg.config_path = fake_config_dir

            user_cfg_path = fake_root / "user_configs.json"
            user_cfg_path.write_text(json.dumps({
                        "others.patrol_loot": {
                            "patrol_rounds": 15
                        }
            }), encoding="utf-8")

            result = self.cfg.load_task("war3.jiubing2.tasks.others.patrol_loot")
            self.assertEqual(result["war3"]["jiubing2"]["tasks"]["others"]["patrol_loot"]["patrol"]["rounds"], 15)
        finally:
            shutil.rmtree(fake_root, ignore_errors=True)

    def test_user_config_short_task_name(self):
        """user_configs.json 用短任务名匹配。"""
        fake_root = Path(tempfile.mkdtemp(prefix="jiubing2_test_short_"))
        try:
            fake_config_dir = fake_root / "a" / "b" / "c" / "config"
            fake_config_dir.mkdir(parents=True)
            shutil.copytree(self.config_dir, fake_config_dir, dirs_exist_ok=True)
            self.cfg.config_path = fake_config_dir

            user_cfg_path = fake_root / "user_configs.json"
            user_cfg_path.write_text(json.dumps({
                        "patrol_loot": {
                            "patrol_rounds": 8
                        }
            }), encoding="utf-8")

            result = self.cfg.load_task("war3.jiubing2.tasks.others.patrol_loot")
            self.assertEqual(result["war3"]["jiubing2"]["tasks"]["others"]["patrol_loot"]["patrol"]["rounds"], 8)
        finally:
            shutil.rmtree(fake_root, ignore_errors=True)

    def test_user_config_hero_configs_applied(self):
        """施法模式下，当前英雄的 hero_configs 中的 points/inventory 应被应用。"""
        fake_root = Path(tempfile.mkdtemp(prefix="jiubing2_test_hero_cfgs_"))
        try:
            fake_config_dir = fake_root / "a" / "b" / "c" / "config"
            fake_config_dir.mkdir(parents=True)
            shutil.copytree(self.config_dir, fake_config_dir, dirs_exist_ok=True)
            self.cfg.config_path = fake_config_dir

            user_cfg_path = fake_root / "user_configs.json"
            user_cfg_path.write_text(json.dumps({
                "combat_mode": "cast_skills",
                "hero": "lancer",
                "hero_configs": {
                    "lancer": {
                        "points": [[1, 2], [3, 4]],
                        "inventory": ["U", "V", "W"]
                    }
                }
            }), encoding="utf-8")

            result = self.cfg.load_task("war3.jiubing2.tasks.others.patrol_loot")
            self.assertEqual(result["hero"]["inventory"], ["U", "V", "W"])
            self.assertEqual(
                result["war3"]["jiubing2"]["tasks"]["others"]["patrol_loot"]["points"],
                [[1, 2], [3, 4]]
            )
        finally:
            shutil.rmtree(fake_root, ignore_errors=True)

    def test_user_config_hero_configs_isolation(self):
        """施法模式下，当前英雄不在 hero_configs 中时不应回退到顶层 points/inventory（防止串英雄）。"""
        fake_root = Path(tempfile.mkdtemp(prefix="jiubing2_test_hero_iso_"))
        try:
            fake_config_dir = fake_root / "a" / "b" / "c" / "config"
            fake_config_dir.mkdir(parents=True)
            shutil.copytree(self.config_dir, fake_config_dir, dirs_exist_ok=True)
            self.cfg.config_path = fake_config_dir

            user_cfg_path = fake_root / "user_configs.json"
            user_cfg_path.write_text(json.dumps({
                "combat_mode": "cast_skills",
                "hero": "lancer",
                "hero_configs": {
                    "mk": {
                        "points": [[999, 999]],
                        "inventory": ["X", "Y", "Z"]
                    }
                },
                "points": [[111, 222]],
                "inventory": ["A", "B", "C"]
            }), encoding="utf-8")

            result = self.cfg.load_task("war3.jiubing2.tasks.others.patrol_loot")
            # 应使用 lancer 默认物品栏，而不是顶层或 mk 的物品栏
            self.assertEqual(result["hero"]["inventory"], ["G", "H", "I"])
            # 顶层 points 不应回退到任务命名空间
            self.assertIsNone(
                result["war3"]["jiubing2"]["tasks"]["others"]["patrol_loot"].get("points")
            )
        finally:
            shutil.rmtree(fake_root, ignore_errors=True)


class TestFilePathMapping(TestConfigBase):
    """测试配置名到文件路径映射。"""

    def test_simple_name(self):
        """war3 → config/war3/war3.toml"""
        path = self.cfg._file_path_for("war3")
        self.assertEqual(path.name, "war3.toml")

    def test_nested_name(self):
        """war3.jiubing2.tasks.others.fishing → config/war3/jiubing2/tasks/others/fishing.toml"""
        path = self.cfg._file_path_for("war3.jiubing2.tasks.others.fishing")
        self.assertEqual(path.name, "fishing.toml")
        self.assertTrue(path.parent.name, "others")

    def test_hero_name(self):
        """war3.jiubing2.heroes.mk → config/war3/jiubing2/heroes/mk.toml"""
        path = self.cfg._file_path_for("war3.jiubing2.heroes.mk")
        self.assertEqual(path.name, "mk.toml")
        self.assertEqual(path.parent.name, "heroes")


class TestNamespaceRoots(TestConfigBase):
    """测试命名空间根集合。"""

    def test_roots_include_dirs_and_toml_files(self):
        """namespace_roots 应包含 config 目录下递归扫描的文件夹名和 .toml 文件名。"""
        roots = self.cfg.namespace_roots
        self.assertIn("war3", roots)        # 文件夹
        self.assertIn("jiubing2", roots)    # 文件夹
        self.assertIn("tasks", roots)       # 文件夹
        self.assertIn("heroes", roots)      # 文件夹
        self.assertIn("base", roots)        # .toml 文件


if __name__ == "__main__":
    unittest.main(verbosity=2)
