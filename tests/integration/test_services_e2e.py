"""Web services 端到端集成测试。

使用真实 src/GameBot/config/data/ 下的配置文件调用 services 函数，
不 mock 文件系统，验证 load_tasks / load_heroes / load_items / load_commands
等函数返回非空且结构合法。
"""
import sys
from pathlib import Path

import pytest

pytestmark = [pytest.mark.integration]

# services.py 导入时读取真实配置文件，无需 mock
from GameBot.web.api.services import (
    TASK_SCHEMAS,
    _find_task_section,
    is_runnable_task,
    load_commands,
    load_farmable_items,
    load_heroes,
    load_items,
    load_task_defaults,
    load_tasks,
)


class TestLoadTasks:
    """load_tasks() 使用真实配置文件。"""

    def test_returns_non_empty_list(self):
        """load_tasks 应返回非空任务列表。"""
        tasks = load_tasks()
        assert isinstance(tasks, list)
        assert len(tasks) > 0, "load_tasks 应返回非空列表"

    def test_each_task_has_required_fields(self):
        """每个任务应含 id, name, short_id, category, icon, configurable 字段。"""
        tasks = load_tasks()
        required = {"id", "name", "short_id", "category", "icon", "description", "configurable"}
        for task in tasks:
            missing = required - set(task.keys())
            assert not missing, f"任务 {task.get('id', '?')} 缺少字段: {missing}"

    def test_task_ids_unique(self):
        """所有任务 id 应唯一。"""
        tasks = load_tasks()
        ids = [t["id"] for t in tasks]
        assert len(ids) == len(set(ids)), f"任务 id 重复: {[x for x in ids if ids.count(x) > 1]}"

    def test_known_tasks_present(self):
        """应包含已知的关键任务。"""
        tasks = load_tasks()
        ids = {t["id"] for t in tasks}
        expected = {"others.fishing", "others.patrol_loot", "endless.endless_single"}
        missing = expected - ids
        assert not missing, f"缺少预期任务: {missing}"


class TestLoadHeroes:
    """load_heroes() 使用真实配置文件。"""

    def test_returns_non_empty_list(self):
        """load_heroes 应返回非空英雄列表。"""
        heroes = load_heroes()
        assert isinstance(heroes, list)
        assert len(heroes) > 0, "load_heroes 应返回非空列表"

    def test_each_hero_has_required_fields(self):
        """每个英雄应含 id, name, floor_key, inventory, skills 字段。"""
        heroes = load_heroes()
        required = {"id", "name", "floor_key", "inventory", "skills"}
        for hero in heroes:
            missing = required - set(hero.keys())
            assert not missing, f"英雄 {hero.get('id', '?')} 缺少字段: {missing}"

    def test_hero_ids_unique(self):
        """所有英雄 id 应唯一。"""
        heroes = load_heroes()
        ids = [h["id"] for h in heroes]
        assert len(ids) == len(set(ids)), f"英雄 id 重复: {[x for x in ids if ids.count(x) > 1]}"

    def test_known_heroes_present(self):
        """应包含已知英雄 mk（山丘之王）。"""
        heroes = load_heroes()
        ids = {h["id"] for h in heroes}
        assert "mk" in ids, f"应包含英雄 mk，实际: {ids}"

    def test_hero_names_non_empty(self):
        """每个英雄 name 应非空。"""
        heroes = load_heroes()
        empty = [h["id"] for h in heroes if not h.get("name")]
        assert not empty, f"以下英雄 name 为空: {empty}"


class TestLoadItems:
    """load_items() 使用真实配置文件。"""

    def test_returns_non_empty_list(self):
        """load_items 应返回非空物品列表。"""
        items = load_items()
        assert isinstance(items, list)
        assert len(items) > 0, "load_items 应返回非空列表"

    def test_each_item_has_id_and_name(self):
        """每个物品应含 id 和 name。"""
        items = load_items()
        for item in items:
            assert "id" in item, f"物品缺少 id: {item}"
            assert "name" in item, f"物品缺少 name: {item}"


class TestLoadCommands:
    """load_commands() 使用真实配置文件。"""

    def test_returns_non_empty_list(self):
        """load_commands 应返回非空指令列表。"""
        cmds = load_commands()
        assert isinstance(cmds, list)
        assert len(cmds) > 0, "load_commands 应返回非空列表"

    def test_each_command_has_key_and_cmd(self):
        """每个指令应含 key 和 cmd。"""
        cmds = load_commands()
        for cmd in cmds:
            assert "key" in cmd, f"指令缺少 key: {cmd}"
            assert "cmd" in cmd, f"指令缺少 cmd: {cmd}"


class TestLoadTaskDefaults:
    """load_task_defaults() 使用真实配置文件。"""

    def test_patrol_loot_defaults(self):
        """patrol_loot 应返回含 desired_items 的默认值。"""
        defaults = load_task_defaults("others.patrol_loot")
        assert isinstance(defaults, dict)
        assert "desired_items" in defaults, "patrol_loot defaults 应含 desired_items"
        assert isinstance(defaults["desired_items"], list)
        assert len(defaults["desired_items"]) > 0

    def test_fishing_defaults(self):
        """fishing 应返回含钓鱼相关配置的默认值。"""
        defaults = load_task_defaults("others.fishing")
        assert isinstance(defaults, dict)

    def test_daily_reputation_defaults(self):
        """daily_reputation 应返回含黑石城/森之城路线点的默认值。"""
        defaults = load_task_defaults("reputation.daily_reputation")
        assert isinstance(defaults, dict)
        # 应含 inventory（默认物品栏）
        assert "inventory" in defaults, "daily_reputation defaults 应含 inventory"

    def test_nonexistent_task_returns_empty(self):
        """不存在的 task_id 应返回空字典。"""
        defaults = load_task_defaults("nonexistent.task")
        assert defaults == {}


class TestLoadFarmableItems:
    """load_farmable_items() 使用真实配置文件。"""

    def test_returns_non_empty_list(self):
        """load_farmable_items 应返回非空列表。"""
        items = load_farmable_items()
        assert isinstance(items, list)
        assert len(items) > 0, "load_farmable_items 应返回非空列表"

    def test_items_are_strings(self):
        """每个物品名应为字符串。"""
        items = load_farmable_items()
        for item in items:
            assert isinstance(item, str), f"物品名应为字符串: {item}"
