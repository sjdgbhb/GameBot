"""Web API services 层单元测试（pytest 风格）。

覆盖 load_tasks、load_heroes、load_items、load_commands、load_user_configs、
save_user_configs、start_task、get_running_tasks 等函数，
通过 fixtures 提供临时目录和 monkeypatch，验证分支行为。
"""
import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from GameBot.web.api import services

pytestmark = [pytest.mark.unit, pytest.mark.web]


def _write_task(config_dir: Path, rel_path: str, content: str) -> None:
    """在临时 config 目录下写入任务 TOML。"""
    p = config_dir / "war3" / "jiubing2" / "tasks" / rel_path
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")


def _write_hero(config_dir: Path, filename: str, content: str) -> None:
    """在临时 config 目录下写入英雄 TOML。"""
    heroes_dir = config_dir / "war3" / "jiubing2" / "heroes"
    heroes_dir.mkdir(parents=True, exist_ok=True)
    (heroes_dir / filename).write_text(content, encoding="utf-8")


def _write_base(config_dir: Path, content: str) -> None:
    """在临时 config 目录下写入 base.toml。"""
    jiubing2_dir = config_dir / "war3" / "jiubing2"
    jiubing2_dir.mkdir(parents=True, exist_ok=True)
    (jiubing2_dir / "base.toml").write_text(content, encoding="utf-8")


class TestLoadTasks:
    """测试 load_tasks — 扫描 tasks/ 目录提取任务列表。"""

    def test_load_tasks_scans_directory(self, services_config_dir):
        """应扫描 tasks/ 下所有 .toml 文件并提取 id/name/icon。"""
        _write_task(services_config_dir, "others/fishing.toml",
                    'dependencies = ["war3.jiubing2"]\n\n'
                    '[war3.jiubing2.tasks.others.fishing]\nname = "钓鱼"\n')
        _write_task(services_config_dir, "others/patrol_loot.toml",
                    'dependencies = ["war3.jiubing2"]\n\n'
                    '[war3.jiubing2.tasks.others.patrol_loot]\nname = "巡逻拾取"\n')

        result = services.load_tasks()
        ids = [t["id"] for t in result]

        assert "others.fishing" in ids
        assert "others.patrol_loot" in ids
        fishing = next(t for t in result if t["id"] == "others.fishing")
        assert fishing["name"] == "钓鱼"
        assert fishing["short_id"] == "fishing"
        assert fishing["category"] == "others"
        assert fishing["icon"] == "🎣"

    def test_load_tasks_empty_directory(self, services_config_dir):
        """空 tasks 目录应返回空列表。"""
        (services_config_dir / "war3" / "jiubing2" / "tasks").mkdir(parents=True)
        assert services.load_tasks() == []

    def test_load_tasks_missing_directory(self, services_config_dir):
        """不存在的 tasks 目录应返回空列表。"""
        assert services.load_tasks() == []

    def test_load_tasks_skips_invalid_toml(self, services_config_dir):
        """损坏的 TOML 文件应被跳过。"""
        _write_task(services_config_dir, "bad.toml", "not valid toml [[[")
        _write_task(services_config_dir, "good.toml",
                    '[war3.jiubing2.tasks.good]\nname = "好任务"\n')

        result = services.load_tasks()
        ids = [t["id"] for t in result]

        assert "good" in ids
        assert "bad" not in ids


class TestLoadHeroes:
    """测试 load_heroes — 扫描 heroes/ 目录提取英雄列表。"""

    def test_load_heroes_extracts_fields(self, services_config_dir):
        """应提取英雄 id/name/floor_key/inventory/skills。"""
        _write_hero(services_config_dir, "mk.toml",
                    '[hero]\nname = "山丘之王"\nfloor_key = "P"\n'
                    'inventory = ["A", "B"]\n'
                    '[[hero.skills]]\nname = "风暴之锤"\n')
        _write_hero(services_config_dir, "lancer.toml",
                    '[hero]\nname = "长枪兵"\nfloor_key = "O"\n'
                    'inventory = ["C"]\n')

        result = services.load_heroes()
        ids = [h["id"] for h in result]

        assert "mk" in ids
        assert "lancer" in ids
        mk = next(h for h in result if h["id"] == "mk")
        assert mk["name"] == "山丘之王"
        assert mk["floor_key"] == "P"
        assert mk["inventory"] == ["A", "B"]

    def test_load_heroes_sorted_by_floor(self, services_config_dir):
        """英雄应按楼层排序（P 在 O 之前）。"""
        _write_hero(services_config_dir, "z_hero.toml",
                    '[hero]\nname = "Z英雄"\nfloor_key = "O"\n')
        _write_hero(services_config_dir, "a_hero.toml",
                    '[hero]\nname = "A英雄"\nfloor_key = "P"\n')

        result = services.load_heroes()
        assert result[0]["floor_key"] == "P"
        assert result[1]["floor_key"] == "O"

    def test_load_heroes_missing_dir(self, services_config_dir):
        """不存在的 heroes 目录应返回空列表。"""
        assert services.load_heroes() == []

    def test_load_heroes_name_from_comment(self, services_config_dir):
        """无 name 字段时应从注释中提取英雄名。"""
        _write_hero(services_config_dir, "test_hero.toml",
                    '### 山丘之王 ###\n[hero]\nfloor_key = "P"\n'
                    'inventory = []\n')

        result = services.load_heroes()
        hero = next(h for h in result if h["id"] == "test_hero")
        assert hero["name"] == "山丘之王"


class TestLoadItemsAndCommands:
    """测试 load_items 和 load_commands。"""

    def test_load_items(self, services_config_dir):
        """应从 base.toml 读取物品定义表。"""
        _write_base(services_config_dir,
                    '[[items]]\nid = 1\nname = "铁剑"\n'
                    '[[items]]\nid = 2\nname = "木盾"\n')
        result = services.load_items()
        assert len(result) == 2
        assert result[0] == {"id": 1, "name": "铁剑"}
        assert result[1] == {"id": 2, "name": "木盾"}

    def test_load_items_missing_file(self, services_config_dir):
        """base.toml 不存在时应返回空列表。"""
        assert services.load_items() == []

    def test_load_commands(self, services_config_dir):
        """应从 base.toml [command] 段读取指令。"""
        _write_base(services_config_dir,
                    '[command]\nclear_nearby = "-delh"\nsuicide = "-kill"\n')
        result = services.load_commands()
        keys = {c["key"] for c in result}

        assert "clear_nearby" in keys
        assert "suicide" in keys

    def test_load_commands_missing_file(self, services_config_dir):
        """base.toml 不存在时应返回空列表。"""
        assert services.load_commands() == []


class TestUserConfigs:
    """测试 load_user_configs 和 save_user_configs。"""

    def test_load_user_configs_flat_format(self, services_user_config_path):
        """普通格式 user_configs.json 应直接返回字典。"""
        services_user_config_path.write_text(
            '{"hero": "mk", "inventory": ["A"]}',
            encoding="utf-8",
        )
        result = services.load_user_configs()

        assert result["hero"] == "mk"
        assert result["inventory"] == ["A"]

    def test_load_user_configs_old_multi_format(self, services_user_config_path):
        """旧多配置格式（含 active/configs）应提取 active 配置。"""
        services_user_config_path.write_text(
            '{"active": "profile1", "configs": '
            '{"profile1": {"hero": "lancer"}, "profile2": {"hero": "mk"}}}',
            encoding="utf-8",
        )
        result = services.load_user_configs()
        assert result.get("hero") == "lancer"

    def test_load_user_configs_missing_file(self, services_user_config_path):
        """文件不存在时应返回空字典。"""
        assert services.load_user_configs() == {}

    def test_load_user_configs_invalid_json(self, services_user_config_path):
        """损坏的 JSON 应返回空字典。"""
        services_user_config_path.write_text(
            "not json {{{",
            encoding="utf-8",
        )
        assert services.load_user_configs() == {}

    def test_save_user_configs_writes_json(self, services_user_config_path):
        """save_user_configs 应写入 JSON 文件。"""
        services.save_user_configs({"hero": "mk", "patrol_rounds": 5})
        data = json.loads(services_user_config_path.read_text(encoding="utf-8"))

        assert data["hero"] == "mk"
        assert data["patrol_rounds"] == 5


class TestStartTask:
    """测试 start_task — 启动任务子进程。"""

    def test_start_task_success(self, services_config_dir, services_project_root,
                                services_web_config, monkeypatch):
        """正常启动任务应返回 ok=True 和 pid。"""
        mock_proc = MagicMock()
        mock_proc.pid = 12345
        mock_proc.poll.return_value = None

        popen_mock = MagicMock(return_value=mock_proc)
        monkeypatch.setattr(services.subprocess, "Popen", popen_mock)
        monkeypatch.setattr(services, "is_runnable_task", lambda _: True)

        result = services.start_task("others.fishing")

        assert result["ok"] is True
        assert result["pid"] == 12345
        assert "others.fishing" in services._running_processes

    def test_start_task_not_found(self, monkeypatch):
        """不存在的任务应抛出 FileNotFoundError。"""
        monkeypatch.setattr(services, "is_runnable_task", lambda _: False)

        with pytest.raises(FileNotFoundError):
            services.start_task("nonexistent.task")

    def test_start_task_already_running(self, services_config_dir, services_project_root,
                                        services_web_config, monkeypatch):
        """已在运行的任务应返回 ok=False。"""
        existing_proc = MagicMock()
        existing_proc.pid = 999
        existing_proc.poll.return_value = None
        services._running_processes["others.fishing"] = existing_proc

        monkeypatch.setattr(services, "is_runnable_task", lambda _: True)
        popen_mock = MagicMock()
        monkeypatch.setattr(services.subprocess, "Popen", popen_mock)

        result = services.start_task("others.fishing")

        assert result["ok"] is False
        assert result["running"] is True
        assert result["pid"] == 999
        popen_mock.assert_not_called()


class TestGetRunningTasks:
    """测试 get_running_tasks。"""

    def test_get_running_empty(self):
        """无运行中任务应返回空列表。"""
        assert services.get_running_tasks() == []

    def test_get_running_with_tasks(self):
        """有运行中任务应返回 id/pid 列表。"""
        proc1 = MagicMock()
        proc1.pid = 111
        proc1.poll.return_value = None
        proc2 = MagicMock()
        proc2.pid = 222
        proc2.poll.return_value = None

        services._running_processes["task_a"] = proc1
        services._running_processes["task_b"] = proc2

        result = services.get_running_tasks()
        ids = {t["id"] for t in result}
        pids = {t["pid"] for t in result}

        assert ids == {"task_a", "task_b"}
        assert pids == {111, 222}

    def test_get_running_prunes_finished(self):
        """已结束的进程应被清理，不在结果中。"""
        running = MagicMock()
        running.pid = 333
        running.poll.return_value = None
        finished = MagicMock()
        finished.pid = 444
        finished.poll.return_value = 0

        services._running_processes["alive"] = running
        services._running_processes["dead"] = finished

        result = services.get_running_tasks()
        ids = {t["id"] for t in result}

        assert "alive" in ids
        assert "dead" not in ids


class TestTaskIcon:
    """测试 _task_icon 任务图标映射。"""

    def test_short_id_special_mapping(self):
        """短 ID 在特殊映射中应返回对应 emoji。"""
        assert services._task_icon("others.fishing") == "🎣"
        assert services._task_icon("others.patrol_loot") == "⚔"
        assert services._task_icon("endless.endless") == "∞"

    def test_category_fallback(self):
        """短 ID 无特殊映射时应按分类返回图标。"""
        assert services._task_icon("atomic.some_task") == "⚡"
        assert services._task_icon("reputation.some_task") == "🏅"
        assert services._task_icon("achievements.some_task") == "🏆"

    def test_unknown_category_default(self):
        """未知分类应返回默认图标。"""
        assert services._task_icon("unknown.task") == "📜"

    def test_no_dot_in_id(self):
        """无点号的 ID 应回退到默认图标。"""
        assert services._task_icon("fishing") == "🎣"


class TestIsRunnableTask:
    """测试 is_runnable_task。"""

    def test_valid_task_id(self, services_config_dir, services_project_root):
        """存在的任务脚本应返回 True。"""
        task_dir = services_project_root / "src" / "GameBot" / "runner" / "tasks" / "war3" / "jiubing2" / "others"
        task_dir.mkdir(parents=True)
        (task_dir / "fishing.py").write_text("# test", encoding="utf-8")

        assert services.is_runnable_task("others.fishing") is True

    def test_nonexistent_task(self, services_config_dir, services_project_root):
        """不存在的任务脚本应返回 False。"""
        assert services.is_runnable_task("others.nonexistent") is False

    def test_invalid_task_id_format(self):
        """非法格式的任务 ID 应返回 False。"""
        assert services.is_runnable_task("..invalid") is False
        assert services.is_runnable_task("task with spaces") is False
        assert services.is_runnable_task("") is False


class TestFindTaskSection:
    """测试 _find_task_section。"""

    def test_find_section_with_name(self):
        """含 name 的节点应被找到。"""
        data = {"war3": {"jiubing2": {"tasks": {"others": {"fishing": {"name": "钓鱼"}}}}}}
        result = services._find_task_section(data)
        assert result["name"] == "钓鱼"

    def test_find_section_nested(self):
        """多层嵌套时应递归找到含 name 的叶子节点。"""
        data = {"war3": {"jiubing2": {"tasks": {"atomic": {"sub": {"name": "子任务"}}}}}}
        result = services._find_task_section(data)
        assert result["name"] == "子任务"

    def test_find_section_no_name(self):
        """无 name 节点时应返回空字典。"""
        data = {"war3": {"jiubing2": {"tasks": {"others": {"key": "val"}}}}}
        result = services._find_task_section(data)
        assert result == {}

    def test_find_section_empty(self):
        """空字典应返回空字典。"""
        assert services._find_task_section({}) == {}


class TestLoadTaskDefaults:
    """测试 load_task_defaults — 从任务 TOML 读取表单默认值。"""

    def test_load_defaults_hero_from_dependencies(self, services_config_dir):
        """应从 dependencies 中提取英雄 ID。"""
        _write_task(services_config_dir, "others/test_task.toml",
                    'dependencies = ["war3.jiubing2", "war3.jiubing2.heroes.lancer"]\n\n'
                    '[war3.jiubing2.tasks.others.test_task]\nname = "测试"\n')
        _write_hero(services_config_dir, "lancer.toml",
                    '[hero]\nname = "长枪兵"\nfloor_key = "P"\ninventory = []\n'
                    '[[hero.skills]]\nname = "穿刺"\n')
        _write_hero(services_config_dir, "mk.toml",
                    '[hero]\nname = "山丘"\nfloor_key = "P"\ninventory = []\n'
                    '[[hero.skills]]\nname = "风暴之锤"\n')

        result = services.load_task_defaults("others.test_task")
        assert result.get("hero") == "lancer"

    def test_load_defaults_inventory_from_task(self, services_config_dir):
        """任务级 inventory 应优先于英雄默认。"""
        _write_task(services_config_dir, "others/test_task.toml",
                    'dependencies = ["war3.jiubing2"]\n\n'
                    '[war3.jiubing2.tasks.others.test_task]\nname = "测试"\n'
                    'inventory = [{id = 1, hotkey = "1"}]\n')
        _write_hero(services_config_dir, "mk.toml",
                    '[hero]\nname = "山丘"\nfloor_key = "P"\ninventory = []\n'
                    '[[hero.skills]]\nname = "风暴之锤"\n')

        result = services.load_task_defaults("others.test_task")
        assert "inventory" in result

    def test_load_defaults_nonexistent_task(self, services_config_dir):
        """不存在的任务应返回空字典。"""
        assert services.load_task_defaults("nonexistent.task") == {}

    def test_load_defaults_patrol_rounds(self, services_config_dir):
        """patrol.rounds 应被提取为 patrol_rounds。"""
        _write_task(services_config_dir, "others/test_task.toml",
                    'dependencies = ["war3.jiubing2"]\n\n'
                    '[war3.jiubing2.tasks.others.test_task]\nname = "测试"\n'
                    '[war3.jiubing2.tasks.others.test_task.patrol]\nrounds = 10\n')
        _write_hero(services_config_dir, "mk.toml",
                    '[hero]\nname = "山丘"\nfloor_key = "P"\ninventory = []\nskills = []\n')

        result = services.load_task_defaults("others.test_task")
        assert result.get("patrol_rounds") == 10

    def test_load_defaults_chest_override(self, services_config_dir):
        """顶层 [chest] 应被提取。"""
        _write_task(services_config_dir, "others/test_task.toml",
                    'dependencies = ["war3.jiubing2"]\n\n'
                    '[war3.jiubing2.tasks.others.test_task]\nname = "测试"\n\n'
                    '[chest]\nai_conf = 0.8\n')
        _write_hero(services_config_dir, "mk.toml",
                    '[hero]\nname = "山丘"\nfloor_key = "P"\ninventory = []\nskills = []\n')

        result = services.load_task_defaults("others.test_task")
        assert "chest" in result
        assert result["chest"]["ai_conf"] == 0.8

    def test_load_defaults_hero_fallback_to_first_with_skills(self, services_config_dir):
        """默认英雄无技能时应回退到第一个有技能的英雄。"""
        _write_task(services_config_dir, "others/test_task.toml",
                    'dependencies = ["war3.jiubing2", "war3.jiubing2.heroes.mk"]\n\n'
                    '[war3.jiubing2.tasks.others.test_task]\nname = "测试"\n')
        _write_hero(services_config_dir, "mk.toml",
                    '[hero]\nname = "山丘"\nfloor_key = "P"\ninventory = []\nskills = []\n')
        _write_hero(services_config_dir, "lancer.toml",
                    '[hero]\nname = "长枪"\nfloor_key = "P"\ninventory = []\n'
                    '[[hero.skills]]\nname = "穿刺"\n')

        result = services.load_task_defaults("others.test_task")
        assert result["hero"] == "lancer"


class TestLoadFarmableItems:
    """测试 load_farmable_items。"""

    def test_load_farmable_items(self, services_config_dir):
        """应从 patrol_loot.toml 的 desired_items 提取物品名列表。"""
        _write_task(services_config_dir, "others/patrol_loot.toml",
                    'dependencies = ["war3.jiubing2"]\n\n'
                    '[war3.jiubing2.tasks.others.patrol_loot]\nname = "巡逻"\n'
                    'desired_items = [\n'
                    '  {id = 1, name = "铁剑"},\n'
                    '  {id = 2, name = "木盾"},\n'
                    ']\n')
        _write_hero(services_config_dir, "mk.toml",
                    '[hero]\nname = "山丘"\nfloor_key = "P"\ninventory = []\nskills = []\n')

        result = services.load_farmable_items()
        assert "铁剑" in result
        assert "木盾" in result

    def test_load_farmable_items_empty(self, services_config_dir):
        """无 desired_items 时应返回空列表。"""
        _write_task(services_config_dir, "others/patrol_loot.toml",
                    'dependencies = ["war3.jiubing2"]\n\n'
                    '[war3.jiubing2.tasks.others.patrol_loot]\nname = "巡逻"\n')
        _write_hero(services_config_dir, "mk.toml",
                    '[hero]\nname = "山丘"\nfloor_key = "P"\ninventory = []\nskills = []\n')

        assert services.load_farmable_items() == []


class TestExportHeroConfig:
    """测试 export_hero_config。"""

    def test_export_existing_hero(self, services_config_dir):
        """应返回英雄 TOML 文件内容。"""
        content = '[hero]\nname = "山丘之王"\nfloor_key = "P"\n'
        _write_hero(services_config_dir, "mk.toml", content)

        result = services.export_hero_config("mk")
        assert result == content

    def test_export_nonexistent_hero(self, services_config_dir):
        """不存在的英雄应抛出 FileNotFoundError。"""
        with pytest.raises(FileNotFoundError):
            services.export_hero_config("nonexistent")

    def test_export_invalid_hero_id(self, services_config_dir):
        """非法英雄 ID 应抛出 ValueError。"""
        with pytest.raises(ValueError):
            services.export_hero_config("../../../etc/passwd")


class TestImportHeroBatch:
    """测试 import_hero_batch。"""

    def test_import_single_hero(self, services_config_dir):
        """应成功导入单个英雄配置。"""
        heroes_dir = services_config_dir / "war3" / "jiubing2" / "heroes"
        heroes_dir.mkdir(parents=True)
        content = '[hero]\nname = "新英雄"\nfloor_key = "P"\n'
        result = services.import_hero_batch([{"hero_id": "new_hero", "content": content}])

        assert "new_hero" in result["saved"]
        assert result["errors"] == []
        hero_path = heroes_dir / "new_hero.toml"
        assert hero_path.exists()
        assert hero_path.read_text(encoding="utf-8") == content

    def test_import_multiple_heroes(self, services_config_dir):
        """应支持批量导入。"""
        heroes_dir = services_config_dir / "war3" / "jiubing2" / "heroes"
        heroes_dir.mkdir(parents=True)
        result = services.import_hero_batch([
            {"hero_id": "hero_a", "content": '[hero]\nname = "A"\n'},
            {"hero_id": "hero_b", "content": '[hero]\nname = "B"\n'},
        ])

        assert len(result["saved"]) == 2
        assert result["errors"] == []

    def test_import_invalid_hero_id(self, services_config_dir):
        """非法英雄 ID 应记录错误。"""
        result = services.import_hero_batch([
            {"hero_id": "../bad", "content": '[hero]\nname = "bad"\n'},
        ])

        assert result["saved"] == []
        assert len(result["errors"]) == 1

    def test_import_empty_content(self, services_config_dir):
        """空内容应记录错误。"""
        result = services.import_hero_batch([
            {"hero_id": "empty_hero", "content": ""},
        ])

        assert result["saved"] == []
        assert len(result["errors"]) == 1

    def test_import_invalid_toml(self, services_config_dir):
        """非法 TOML 内容应记录错误。"""
        result = services.import_hero_batch([
            {"hero_id": "bad_hero", "content": "not valid toml [[["},
        ])

        assert result["saved"] == []
        assert len(result["errors"]) == 1

    def test_import_mixed_success_and_error(self, services_config_dir):
        """部分成功部分失败应分别记录。"""
        heroes_dir = services_config_dir / "war3" / "jiubing2" / "heroes"
        heroes_dir.mkdir(parents=True)
        result = services.import_hero_batch([
            {"hero_id": "good_hero", "content": '[hero]\nname = "好"\n'},
            {"hero_id": "bad_hero", "content": "invalid [[["},
        ])

        assert "good_hero" in result["saved"]
        assert len(result["errors"]) == 1


class TestSaveHeroInventory:
    """测试 save_hero_inventory。"""

    def test_save_inventory_replaces_existing(self, services_config_dir):
        """应替换已有的 inventory 块。"""
        original = (
            '### 山丘之王 ###\n\n'
            '# ------------------------------ 物品栏配置 ------------------------------\n'
            '[[hero.inventory]]\nslot = 0\nid = 1\nhotkey = "1"\n\n'
            '[[hero.inventory]]\nslot = 1\nid = 2\nhotkey = "2"\n\n'
            '# ============================== 分割线 ==============================\n'
            '[hero]\nname = "山丘"\nfloor_key = "P"\n'
        )
        _write_hero(services_config_dir, "mk.toml", original)

        services.save_hero_inventory("mk", [
            {"id": 3, "hotkey": "1"},
            {"id": 4, "hotkey": "2"},
        ])

        content = (services_config_dir / "war3" / "jiubing2" / "heroes" / "mk.toml").read_text(encoding="utf-8")
        assert "[[hero.inventory]]" in content
        assert "id = 3" in content
        assert "id = 4" in content
        assert "id = 1" not in content
        assert "id = 2" not in content

    def test_save_inventory_appends_new_block(self, services_config_dir):
        """无 inventory 块时应追加新块。"""
        original = '[hero]\nname = "无物品栏英雄"\nfloor_key = "P"\n'
        _write_hero(services_config_dir, "no_inv.toml", original)

        services.save_hero_inventory("no_inv", [
            {"id": 1, "hotkey": "1"},
        ])

        content = (services_config_dir / "war3" / "jiubing2" / "heroes" / "no_inv.toml").read_text(encoding="utf-8")
        assert "[[hero.inventory]]" in content
        assert "id = 1" in content

    def test_save_inventory_filters_empty_slots(self, services_config_dir):
        """空格子和无效 id 应被过滤。"""
        original = '[hero]\nname = "测试"\nfloor_key = "P"\n'
        _write_hero(services_config_dir, "test.toml", original)

        services.save_hero_inventory("test", [
            {"id": 1, "hotkey": "1"},
            {"id": -1, "hotkey": "2"},  # 空 id 应被过滤
            {"id": 2, "hotkey": ""},    # 空 hotkey 应被过滤
            {"id": None, "hotkey": "3"},  # None id 应被过滤
        ])

        content = (services_config_dir / "war3" / "jiubing2" / "heroes" / "test.toml").read_text(encoding="utf-8")
        assert "id = 1" in content
        assert "id = 2" not in content

    def test_save_inventory_empty_list(self, services_config_dir):
        """空物品栏列表应写入注释。"""
        original = '[hero]\nname = "空物品栏"\nfloor_key = "P"\n'
        _write_hero(services_config_dir, "empty.toml", original)

        services.save_hero_inventory("empty", [])

        content = (services_config_dir / "war3" / "jiubing2" / "heroes" / "empty.toml").read_text(encoding="utf-8")
        assert "未配置物品栏" in content

    def test_save_inventory_invalid_hero_id(self, services_config_dir):
        """非法英雄 ID 应抛出 ValueError。"""
        with pytest.raises(ValueError):
            services.save_hero_inventory("../../../etc/passwd", [{"id": 1, "hotkey": "1"}])

    def test_save_inventory_nonexistent_hero(self, services_config_dir):
        """不存在的英雄应抛出 FileNotFoundError。"""
        with pytest.raises(FileNotFoundError):
            services.save_hero_inventory("nonexistent", [{"id": 1, "hotkey": "1"}])


class TestGetTaskSchema:
    """测试 get_task_schema。"""

    def test_get_schema_by_full_id(self, services_config_dir):
        """应按完整 task_id 返回 schema。"""
        _write_task(services_config_dir, "others/fishing.toml",
                    'dependencies = ["war3.jiubing2"]\n\n'
                    '[war3.jiubing2.tasks.others.fishing]\nname = "钓鱼"\n')
        _write_hero(services_config_dir, "mk.toml",
                    '[hero]\nname = "山丘"\nfloor_key = "P"\ninventory = []\nskills = []\n')

        result = services.get_task_schema("others.fishing")
        assert result is not None
        assert result["id"] == "others.fishing"
        assert "defaults" in result

    def test_get_schema_by_short_id(self, services_config_dir):
        """应按短 ID 返回 schema。"""
        _write_task(services_config_dir, "others/patrol_loot.toml",
                    'dependencies = ["war3.jiubing2"]\n\n'
                    '[war3.jiubing2.tasks.others.patrol_loot]\nname = "巡逻"\n')
        _write_hero(services_config_dir, "mk.toml",
                    '[hero]\nname = "山丘"\nfloor_key = "P"\ninventory = []\nskills = []\n')

        result = services.get_task_schema("patrol_loot")
        assert result is not None
        assert result["id"] == "patrol_loot"

    def test_get_schema_nonexistent(self):
        """不存在的任务应返回 None。"""
        assert services.get_task_schema("nonexistent.task") is None

    def test_get_schema_deep_copy(self, services_config_dir):
        """返回的 schema 应为深拷贝，不修改原 schema。"""
        _write_task(services_config_dir, "others/patrol_loot.toml",
                    'dependencies = ["war3.jiubing2"]\n\n'
                    '[war3.jiubing2.tasks.others.patrol_loot]\nname = "巡逻"\n')
        _write_hero(services_config_dir, "mk.toml",
                    '[hero]\nname = "山丘"\nfloor_key = "P"\ninventory = []\nskills = []\n')

        result = services.get_task_schema("others.patrol_loot")
        original = services.TASK_SCHEMAS["patrol_loot"]
        # 修改返回值不应影响原 schema
        result["test_modification"] = True
        assert "test_modification" not in original
