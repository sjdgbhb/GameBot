"""Web API services 层边界测试 — 补充 services.py 未覆盖的分支。"""

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from GameBot.web.api import services

pytestmark = [pytest.mark.unit, pytest.mark.web]


def _write_hero(config_dir: Path, filename: str, content: str) -> None:
    """在临时 config 目录下写入英雄 TOML。"""
    heroes_dir = config_dir / "war3" / "jiubing2" / "heroes"
    heroes_dir.mkdir(parents=True, exist_ok=True)
    (heroes_dir / filename).write_text(content, encoding="utf-8")


def _write_base(config_dir: Path, content: str) -> None:
    """在临时 config 目录下写入 jiubing2.toml。"""
    jiubing2_dir = config_dir / "war3" / "jiubing2"
    jiubing2_dir.mkdir(parents=True, exist_ok=True)
    (jiubing2_dir / "jiubing2.toml").write_text(content, encoding="utf-8")


class TestLoadHeroesEdge:
    """load_heroes 名称提取边界测试。"""

    def test_load_heroes_name_from_parentheses_pattern(self, services_config_dir):
        """无 name 字段时，应从 `# 英雄配置: xxx (中文名)` 注释中提取名称。"""
        _write_hero(
            services_config_dir,
            "test_hero.toml",
            '# 英雄配置: mk（山丘之王）\n[hero]\nfloor_key = "P"\ninventory = []\n',
        )

        result = services.load_heroes()
        hero = next(h for h in result if h["id"] == "test_hero")
        assert hero["name"] == "山丘之王"

    def test_load_heroes_name_from_plain_pattern(self, services_config_dir):
        """无 name 字段时，应从 `# 英雄配置: 中文名` 注释中提取名称。"""
        _write_hero(
            services_config_dir, "test_hero.toml", '# 英雄配置：  风暴之灵  \n[hero]\nfloor_key = "P"\ninventory = []\n'
        )

        result = services.load_heroes()
        hero = next(h for h in result if h["id"] == "test_hero")
        assert hero["name"] == "风暴之灵"

    def test_load_heroes_invalid_toml_returns_defaults(self, services_config_dir):
        """损坏的英雄 TOML 应返回 id 和空默认字段，不崩溃。"""
        _write_hero(services_config_dir, "bad.toml", "not valid toml [[[")

        result = services.load_heroes()
        hero = next(h for h in result if h["id"] == "bad")
        assert hero["name"] == "bad"
        assert hero["inventory"] == []


class TestSaveHeroInventoryEdge:
    """save_hero_inventory 边界测试。"""

    def test_save_inventory_appends_newline_when_missing(self, services_config_dir):
        """原文件末尾无换行时，追加物品栏块前应先补换行。"""
        _write_hero(services_config_dir, "no_newline.toml", '[hero]\nname = "测试"\nfloor_key = "P"')

        services.save_hero_inventory(
            "no_newline",
            [
                {"slot": 0, "item_id": 1},
            ],
        )

        content = (services_config_dir / "war3" / "jiubing2" / "heroes" / "no_newline.toml").read_text(encoding="utf-8")
        assert "inventory = [" in content
        assert "item_id = 1" in content

    def test_save_inventory_stops_at_section_header(self, services_config_dir):
        """替换 inventory 块时应在下一个普通 section 前停止。"""
        original = '[hero]\nname = "测试"\nfloor_key = "P"\ninventory = [\n  {slot = 0, item_id = 1},\n]\n\n[war3]\nclient_size = [1, 1]\n'
        _write_hero(services_config_dir, "section_stop.toml", original)

        services.save_hero_inventory(
            "section_stop",
            [
                {"slot": 0, "item_id": 5},
            ],
        )

        content = (services_config_dir / "war3" / "jiubing2" / "heroes" / "section_stop.toml").read_text(
            encoding="utf-8"
        )
        assert "item_id = 5" in content
        assert "item_id = 1" not in content
        assert '[war3]' in content

    def test_save_inventory_filters_non_dict_items(self, services_config_dir):
        """非 dict 类型的物品项应被过滤。"""
        _write_hero(services_config_dir, "filter_inv.toml", '[hero]\nname = "测试"\nfloor_key = "P"\n')

        services.save_hero_inventory(
            "filter_inv",
            [
                {"slot": 0, "item_id": 1},
                "invalid string item",
                123,
                None,
            ],
        )

        content = (services_config_dir / "war3" / "jiubing2" / "heroes" / "filter_inv.toml").read_text(encoding="utf-8")
        assert "item_id = 1" in content


class TestStartTaskEdge:
    """start_task 边界测试。"""

    def test_start_task_reads_python_path_from_base_toml(
        self, services_config_dir, services_project_root, services_web_config, monkeypatch
    ):
        """当 _WEB_CONFIG 未配置 dm_python_path 时，应从 jiubing2.toml [dm].python_path 读取。"""
        _write_base(services_config_dir, '[dm]\npython_path = "custom/python.exe"\n')

        expected_path = str(services_project_root / "custom" / "python.exe")

        captured = []

        def popen_mock(cmd, **kwargs):
            captured.append(cmd)
            proc = MagicMock()
            proc.pid = 54321
            return proc

        monkeypatch.setattr(services.subprocess, "Popen", popen_mock)
        monkeypatch.setattr(services, "is_runnable_task", lambda _: True)

        result = services.start_task("others.fishing")

        assert result["ok"] is True
        assert captured[0][0] == expected_path


if __name__ == "__main__":
    pytest.main()
