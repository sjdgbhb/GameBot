"""配置用户覆盖边界测试 — 补充 config/system/user.py 未覆盖的分支。

覆盖范围：
- _load_user_config 边界：无任务名返回、旧格式 active/configs、非法 JSON、旧文件异常
- _apply_user_overrides 边界：hero_configs 内 points 为 dict、combat_mode 同步到每日声望子任务
"""

import json
import shutil
import tempfile
import unittest
from pathlib import Path

import pytest

from GameBot.config import Config
from tests.common.config_helpers import write_toml as _write_toml

pytestmark = [pytest.mark.unit, pytest.mark.config]


class _UserEdgeConfigTestBase(unittest.TestCase):
    """用户覆盖边界测试基类。"""

    def setUp(self):
        Config.reset()
        self.tmp_root = Path(tempfile.mkdtemp(prefix="jiubing2_user_edge_"))
        self.config_dir = self.tmp_root / "a" / "b" / "c" / "config"
        self.config_dir.mkdir(parents=True)
        _write_toml(
            self.config_dir, "base.toml", '\nname = "base"\nextends = []\n[paths]\nresources_path = "resources"\n'
        )
        _write_toml(
            self.config_dir,
            "war3/war3.toml",
            '\nname = "war3.war3"\nextends = ["base"]\n[war3]\nwindow_title = "Warcraft III"\n',
        )
        _write_toml(
            self.config_dir,
            "war3/jiubing2/jiubing2.toml",
            '\nname = "war3.jiubing2.jiubing2"\nextends = ["war3"]\n[hero]\ninventory = ["A", "B", "C"]\n',
        )
        _write_toml(
            self.config_dir,
            "war3/jiubing2/heroes/mk.toml",
            '\nname = "war3.jiubing2.heroes.mk"\nextends = ["war3.jiubing2"]\n[hero]\ninventory = ["D", "E", "F"]\nattack = 100\n',
        )
        _write_toml(
            self.config_dir,
            "war3/jiubing2/tasks/reputation/daily_reputation.toml",
            '\nname = "war3.jiubing2.tasks.reputation.daily_reputation"\nextends = ["war3.jiubing2"]\n\n[this.blackstone]\nname = "黑石声望"\n\n[this.forest]\nname = "森林声望"\n',
        )
        self.cfg = Config(str(self.config_dir))

    def tearDown(self):
        Config.reset()
        shutil.rmtree(self.tmp_root, ignore_errors=True)


class TestLoadUserConfigEdge(_UserEdgeConfigTestBase):
    """_load_user_config 边界测试。"""

    def test_load_without_task_name_returns_deep_copy(self):
        """不传入 task_name 时应返回 user_configs.json 内容的深拷贝。"""
        user_cfg = {"inventory": ["X", "Y"], "points": [[1, 2]]}
        (self.cfg.project_root / "user_configs.json").write_text(json.dumps(user_cfg), encoding="utf-8")
        result = self.cfg._load_user_config()
        self.assertEqual(result, user_cfg)
        self.assertIsNot(result, user_cfg)
        result["inventory"].append("Z")
        result2 = self.cfg._load_user_config()
        self.assertEqual(result2["inventory"], ["X", "Y"])

    def test_old_multi_config_active_format(self):
        """旧多配置格式 {active, configs} 应按 active 键返回对应配置。"""
        (self.cfg.project_root / "user_configs.json").write_text(
            json.dumps(
                {"active": "custom", "configs": {"default": {"inventory": ["A"]}, "custom": {"inventory": ["B", "C"]}}}
            ),
            encoding="utf-8",
        )
        result = self.cfg._load_user_config("war3.jiubing2.tasks.others.fishing")
        self.assertEqual(result.get("inventory"), ["B", "C"])

    def test_invalid_json_in_user_configs_ignored(self):
        """user_configs.json 为非法 JSON 时应静默忽略并返回空 dict。"""
        (self.cfg.project_root / "user_configs.json").write_text("not a json {", encoding="utf-8")
        result = self.cfg._load_user_config("war3.jiubing2.tasks.others.fishing")
        self.assertEqual(result, {})

    def test_invalid_json_in_old_user_config_ignored(self):
        """旧 user_config.json 为非法 JSON 时应静默忽略并返回空 dict。"""
        (self.cfg.project_root / "user_config.json").write_text("not a json {", encoding="utf-8")
        result = self.cfg._load_user_config("war3.jiubing2.tasks.others.fishing")
        self.assertEqual(result, {})

    def test_non_dict_user_config_returns_empty(self):
        """user_configs.json 内容非 dict（如 list）时应返回空 dict。"""
        (self.cfg.project_root / "user_configs.json").write_text(json.dumps(["invalid"]), encoding="utf-8")
        result = self.cfg._load_user_config("war3.jiubing2.tasks.others.fishing")
        self.assertEqual(result, {})


class TestApplyUserOverridesEdge(_UserEdgeConfigTestBase):
    """_apply_user_overrides 边界测试。"""

    def test_hero_configs_points_dict_with_blackstone_and_forest(self):
        """hero_configs 中 points 为 dict 时，应分别写入黑石/森林原子任务。"""
        config = {"hero": {"inventory": ["A", "B", "C"]}}
        user_cfg = {
            "combat_mode": "cast_skills",
            "hero": "lancer",
            "hero_configs": {
                "lancer": {
                    "points": {"blackstone_points": [[10, 20], [30, 40]], "forest_points": [[50, 60], [70, 80]]},
                    "inventory": ["G", "H", "I"],
                }
            },
        }
        self.cfg._apply_user_overrides(config, user_cfg, "war3.jiubing2.tasks.others.patrol_loot")
        bs_cfg = config["war3"]["jiubing2"]["tasks"]["atomic"]["blackstone_gate_harassment"]
        forest_cfg = config["war3"]["jiubing2"]["tasks"]["atomic"]["swift_beast"]
        self.assertEqual(bs_cfg["points"], [[10, 20], [30, 40]])
        self.assertEqual(forest_cfg["points"], [[50, 60], [70, 80]])
        self.assertEqual(config["hero"]["inventory"], ["G", "H", "I"])

    def test_combat_mode_sync_to_daily_reputation_subtasks(self):
        """combat_mode 应同步写入每日声望的 blackstone/forest 子任务。"""
        config = {
            "war3": {
                "jiubing2": {
                    "tasks": {
                        "reputation": {"daily_reputation": {"blackstone": {"name": "黑石"}, "forest": {"name": "森林"}}}
                    }
                }
            }
        }
        user_cfg = {"combat_mode": "cast_skills"}
        self.cfg._apply_user_overrides(config, user_cfg, "war3.jiubing2.tasks.reputation.daily_reputation")
        daily_cfg = config["war3"]["jiubing2"]["tasks"]["reputation"]["daily_reputation"]
        self.assertEqual(daily_cfg["blackstone"]["combat_mode"], "cast_skills")
        self.assertEqual(daily_cfg["forest"]["combat_mode"], "cast_skills")


if __name__ == "__main__":
    unittest.main()
