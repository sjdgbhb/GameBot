"""任务脚本纯逻辑单元测试 — 覆盖 patrol_loot 路线解析/物品目标/拾取匹配、
daily_reputation 编排开关、personal 类属性继承等。

覆盖：
- PatrolLootTask._resolve_points: 用户自定义 points → preset 匹配 → 空兜底
- PatrolLootTask._parse_item_targets: 新格式(dict) / 旧格式(str) / 边界
- PatrolLootTask._all_items_satisfied: 全满足 / 未满足 / 空目标
- PatrolLootTask._match_desired: char_fixes 纠错 / 子串匹配 / 已达目标不匹配
- PatrolLootTask._report_progress: 有/无回调 / target=0 跳过
- PersonalAchievementTask: 类属性继承正确性
"""

import sys
import unittest
from unittest.mock import MagicMock

import pytest

pytestmark = [pytest.mark.unit]

# Mock Windows COM 依赖
_DM_MODULES = (
    "win32com",
    "win32com.client",
    "pythoncom",
    "pywintypes",
    "winreg",
    "win32gui",
    "win32con",
    "win32api",
)


def _mock_dm_modules():
    originals = {name: sys.modules.get(name) for name in _DM_MODULES}
    for name in _DM_MODULES:
        sys.modules[name] = MagicMock()
    return originals


def _restore_dm_modules(originals):
    for name, mod in originals.items():
        if mod is None:
            sys.modules.pop(name, None)
        else:
            sys.modules[name] = mod


class TestResolvePoints(unittest.TestCase):
    """测试 PatrolLootTask._resolve_points 路线解析三分支。"""

    def setUp(self):
        self._orig = _mock_dm_modules()

    def tearDown(self):
        _restore_dm_modules(self._orig)

    def _make_task(self, cfg=None, route_scheme="", route_presets=None):
        """用 __new__ 构造 PatrolLootTask 实例，跳过 __init__ 中的 DmClient 等。"""
        from GameBot.runner.tasks.war3.jiubing2.others.patrol_loot import PatrolLootTask

        task = PatrolLootTask.__new__(PatrolLootTask)
        task.cfg = cfg or {}
        task.route_scheme = route_scheme
        task.route_presets = route_presets or []
        return task

    def test_user_points_priority(self):
        """用户自定义 points 应优先于 route_presets。"""
        user_points = [{"desc": "用户点1", "coords": [100, 100]}]
        task = self._make_task(
            cfg={"points": user_points},
            route_scheme="preset_a",
            route_presets=[{"name": "preset_a", "points": [{"desc": "preset点"}]}],
        )
        result = task._resolve_points()
        self.assertEqual(result, user_points)

    def test_preset_match_by_scheme(self):
        """无用户 points 时，按 route_scheme 从 route_presets 中选取。"""
        preset_points = [{"desc": "preset点1"}, {"desc": "preset点2"}]
        task = self._make_task(
            cfg={},
            route_scheme="荒漠废墟",
            route_presets=[
                {"name": "奇异之地", "points": [{"desc": "奇异"}]},
                {"name": "荒漠废墟", "points": preset_points},
            ],
        )
        result = task._resolve_points()
        self.assertEqual(result, preset_points)

    def test_preset_no_match_returns_empty(self):
        """route_scheme 在 route_presets 中无匹配时应返回空列表。"""
        task = self._make_task(
            cfg={},
            route_scheme="不存在的方案",
            route_presets=[{"name": "其他", "points": [{"desc": "x"}]}],
        )
        result = task._resolve_points()
        self.assertEqual(result, [])

    def test_no_scheme_no_presets_returns_empty(self):
        """无 scheme 且无 presets 时应返回空列表。"""
        task = self._make_task(cfg={}, route_scheme="", route_presets=[])
        result = task._resolve_points()
        self.assertEqual(result, [])

    def test_preset_match_empty_points(self):
        """匹配的 preset 中 points 为空列表时应返回空列表。"""
        task = self._make_task(
            cfg={},
            route_scheme="空路线",
            route_presets=[{"name": "空路线", "points": []}],
        )
        result = task._resolve_points()
        self.assertEqual(result, [])

    def test_user_points_empty_list_falls_to_preset(self):
        """用户 points 为空列表（非 None）时应 fallback 到 preset。"""
        preset_points = [{"desc": "preset"}]
        task = self._make_task(
            cfg={"points": []},
            route_scheme="preset_a",
            route_presets=[{"name": "preset_a", "points": preset_points}],
        )
        result = task._resolve_points()
        self.assertEqual(result, preset_points)


class TestParseItemTargets(unittest.TestCase):
    """测试 PatrolLootTask._parse_item_targets 静态方法。"""

    def setUp(self):
        self._orig = _mock_dm_modules()
        from GameBot.runner.tasks.war3.jiubing2.others.patrol_loot import PatrolLootTask

        self.PatrolLootTask = PatrolLootTask

    def tearDown(self):
        _restore_dm_modules(self._orig)

    def test_new_format_with_count(self):
        """新格式 dict 含 name 和 count。"""
        result = self.PatrolLootTask._parse_item_targets(
            [
                {"name": "铁剑", "count": 3},
                {"name": "木盾", "count": 1},
            ]
        )
        self.assertEqual(result["铁剑"]["target"], 3)
        self.assertEqual(result["铁剑"]["picked"], 0)
        self.assertEqual(result["木盾"]["target"], 1)
        self.assertEqual(result["木盾"]["picked"], 0)

    def test_new_format_default_count(self):
        """新格式 dict 缺省 count 时默认 1。"""
        result = self.PatrolLootTask._parse_item_targets(
            [
                {"name": "铁剑"},
            ]
        )
        self.assertEqual(result["铁剑"]["target"], 1)

    def test_old_format_string(self):
        """旧格式字符串列表，默认 count=1。"""
        result = self.PatrolLootTask._parse_item_targets(["铁剑", "木盾"])
        self.assertEqual(result["铁剑"]["target"], 1)
        self.assertEqual(result["木盾"]["target"], 1)

    def test_mixed_format(self):
        """新旧格式混合。"""
        result = self.PatrolLootTask._parse_item_targets(
            [
                "铁剑",
                {"name": "木盾", "count": 5},
            ]
        )
        self.assertEqual(result["铁剑"]["target"], 1)
        self.assertEqual(result["木盾"]["target"], 5)

    def test_empty_list(self):
        """空列表应返回空字典。"""
        self.assertEqual(self.PatrolLootTask._parse_item_targets([]), {})

    def test_dict_without_name_skipped(self):
        """dict 无 name 字段时应跳过。"""
        result = self.PatrolLootTask._parse_item_targets(
            [
                {"count": 3},
                {"name": "铁剑", "count": 1},
            ]
        )
        self.assertEqual(len(result), 1)
        self.assertIn("铁剑", result)

    def test_empty_name_skipped(self):
        """name 为空字符串时应跳过。"""
        result = self.PatrolLootTask._parse_item_targets(
            [
                {"name": "", "count": 3},
                {"name": "铁剑", "count": 1},
            ]
        )
        self.assertEqual(len(result), 1)
        self.assertIn("铁剑", result)

    def test_duplicate_name_overwrites(self):
        """同名物品后一个覆盖前一个。"""
        result = self.PatrolLootTask._parse_item_targets(
            [
                {"name": "铁剑", "count": 1},
                {"name": "铁剑", "count": 5},
            ]
        )
        self.assertEqual(result["铁剑"]["target"], 5)

    def test_count_zero(self):
        """count=0 时仍应记录（target=0）。"""
        result = self.PatrolLootTask._parse_item_targets(
            [
                {"name": "铁剑", "count": 0},
            ]
        )
        self.assertEqual(result["铁剑"]["target"], 0)


class TestAllItemsSatisfied(unittest.TestCase):
    """测试 PatrolLootTask._all_items_satisfied。"""

    def setUp(self):
        self._orig = _mock_dm_modules()

    def tearDown(self):
        _restore_dm_modules(self._orig)

    def _make_task(self, item_targets=None):
        from GameBot.runner.tasks.war3.jiubing2.others.patrol_loot import PatrolLootTask

        task = PatrolLootTask.__new__(PatrolLootTask)
        task.item_targets = item_targets or {}
        return task

    def test_all_satisfied(self):
        """所有物品 picked >= target 时返回 True。"""
        task = self._make_task(
            {
                "铁剑": {"target": 2, "picked": 2},
                "木盾": {"target": 1, "picked": 3},
            }
        )
        self.assertTrue(task._all_items_satisfied())

    def test_not_all_satisfied(self):
        """任一物品 picked < target 时返回 False。"""
        task = self._make_task(
            {
                "铁剑": {"target": 2, "picked": 1},
                "木盾": {"target": 1, "picked": 1},
            }
        )
        self.assertFalse(task._all_items_satisfied())

    def test_empty_targets_returns_false(self):
        """无目标物品时返回 False（不拾取不结束）。"""
        task = self._make_task({})
        self.assertFalse(task._all_items_satisfied())

    def test_target_zero_satisfied(self):
        """target=0 时 picked=0 即满足。"""
        task = self._make_task(
            {
                "铁剑": {"target": 0, "picked": 0},
            }
        )
        self.assertTrue(task._all_items_satisfied())


class TestMatchDesired(unittest.TestCase):
    """测试 PatrolLootTask._match_desired 物品名匹配。"""

    def setUp(self):
        self._orig = _mock_dm_modules()

    def tearDown(self):
        _restore_dm_modules(self._orig)

    def _make_task(self, item_targets=None, item_text_cfg=None):
        from GameBot.runner.tasks.war3.jiubing2.others.patrol_loot import PatrolLootTask

        task = PatrolLootTask.__new__(PatrolLootTask)
        task.item_targets = item_targets or {}
        task.item_text_cfg = item_text_cfg or {}
        return task

    def test_exact_match(self):
        """物品名完全匹配目标。"""
        task = self._make_task(
            item_targets={"铁剑": {"target": 1, "picked": 0}},
        )
        self.assertEqual(task._match_desired("铁剑"), "铁剑")

    def test_substring_match(self):
        """物品名包含目标名时匹配。"""
        task = self._make_task(
            item_targets={"铁剑": {"target": 1, "picked": 0}},
        )
        self.assertEqual(task._match_desired("精铁剑+3"), "铁剑")

    def test_no_match(self):
        """不匹配任何目标时返回 None。"""
        task = self._make_task(
            item_targets={"铁剑": {"target": 1, "picked": 0}},
        )
        self.assertIsNone(task._match_desired("木盾"))

    def test_empty_item_name(self):
        """空物品名应返回 None。"""
        task = self._make_task(
            item_targets={"铁剑": {"target": 1, "picked": 0}},
        )
        self.assertIsNone(task._match_desired(""))

    def test_already_at_target_skipped(self):
        """已达目标数量的物品不再匹配。"""
        task = self._make_task(
            item_targets={"铁剑": {"target": 2, "picked": 2}},
        )
        self.assertIsNone(task._match_desired("铁剑"))

    def test_char_fixes_applied(self):
        """char_fixes 应在匹配前纠正 OCR 形近字。"""
        task = self._make_task(
            item_targets={"魔龙爪": {"target": 1, "picked": 0}},
            item_text_cfg={"char_fixes": {"廣": "魔"}},
        )
        self.assertEqual(task._match_desired("廣龙爪"), "魔龙爪")

    def test_char_fixes_empty_dict(self):
        """char_fixes 为空字典时应正常匹配。"""
        task = self._make_task(
            item_targets={"铁剑": {"target": 1, "picked": 0}},
            item_text_cfg={"char_fixes": {}},
        )
        self.assertEqual(task._match_desired("铁剑"), "铁剑")

    def test_multiple_targets_first_match(self):
        """多个目标时返回第一个匹配的。"""
        task = self._make_task(
            {
                "铁剑": {"target": 1, "picked": 0},
                "铁甲": {"target": 1, "picked": 0},
            }
        )
        result = task._match_desired("铁剑")
        self.assertEqual(result, "铁剑")

    def test_partial_target_remaining(self):
        """部分物品已达目标，未达的仍可匹配。"""
        task = self._make_task(
            {
                "铁剑": {"target": 2, "picked": 2},
                "木盾": {"target": 1, "picked": 0},
            }
        )
        self.assertEqual(task._match_desired("木盾"), "木盾")
        self.assertIsNone(task._match_desired("铁剑"))


class TestReportProgress(unittest.TestCase):
    """测试 PatrolLootTask._report_progress。"""

    def setUp(self):
        self._orig = _mock_dm_modules()

    def tearDown(self):
        _restore_dm_modules(self._orig)

    def _make_task(self, item_targets=None, callback=None):
        from GameBot.runner.tasks.war3.jiubing2.others.patrol_loot import PatrolLootTask

        task = PatrolLootTask.__new__(PatrolLootTask)
        task.item_targets = item_targets or {}
        task._progress_lines_callback = callback
        return task

    def test_with_callback(self):
        """有回调时应调用并传递进度行。"""
        lines_received = []
        task = self._make_task(
            item_targets={
                "铁剑": {"target": 2, "picked": 1},
                "木盾": {"target": 1, "picked": 0},
            },
            callback=lambda lines: lines_received.extend(lines),
        )
        task._report_progress()
        self.assertEqual(len(lines_received), 2)
        self.assertIn("铁剑 1/2", lines_received)
        self.assertIn("木盾 0/1", lines_received)

    def test_no_callback(self):
        """无回调时应直接返回不报错。"""
        task = self._make_task(
            item_targets={"铁剑": {"target": 1, "picked": 0}},
            callback=None,
        )
        task._report_progress()

    def test_target_zero_skipped(self):
        """target=0 的物品不应出现在进度行中。"""
        lines_received = []
        task = self._make_task(
            item_targets={
                "铁剑": {"target": 0, "picked": 0},
                "木盾": {"target": 1, "picked": 0},
            },
            callback=lambda lines: lines_received.extend(lines),
        )
        task._report_progress()
        self.assertEqual(len(lines_received), 1)
        self.assertIn("木盾 0/1", lines_received)

    def test_empty_targets(self):
        """无目标物品时应传递空列表。"""
        lines_received = []
        task = self._make_task(
            item_targets={},
            callback=lambda lines: lines_received.extend(lines),
        )
        task._report_progress()
        self.assertEqual(lines_received, [])


class TestPersonalAchievementTask(unittest.TestCase):
    """测试 PersonalAchievementTask 类属性继承正确性。"""

    def setUp(self):
        self._orig = _mock_dm_modules()

    def tearDown(self):
        _restore_dm_modules(self._orig)

    def test_inherits_multi_atomic_loop_task(self):
        """应继承 MultiAtomicLoopTask。"""
        from GameBot.runner.tasks.war3.jiubing2.achievements.personal import PersonalAchievementTask
        from GameBot.runner.tasks.war3.jiubing2.base import MultiAtomicLoopTask

        self.assertTrue(issubclass(PersonalAchievementTask, MultiAtomicLoopTask))

    def test_atomic_name(self):
        """atomic_name 应为 '个人任务'。"""
        from GameBot.runner.tasks.war3.jiubing2.achievements.personal import PersonalAchievementTask

        self.assertEqual(PersonalAchievementTask.atomic_name, "个人任务")

    def test_task_config_path(self):
        """task_config_path 应指向 achievements.personal。"""
        from GameBot.runner.tasks.war3.jiubing2.achievements.personal import PersonalAchievementTask

        self.assertEqual(
            PersonalAchievementTask.task_config_path,
            ("war3", "jiubing2", "tasks", "achievements", "personal"),
        )

    def test_atomic_config_path(self):
        """atomic_config_path 应指向 atomic.venomous_snake。"""
        from GameBot.runner.tasks.war3.jiubing2.achievements.personal import PersonalAchievementTask

        self.assertEqual(
            PersonalAchievementTask.atomic_config_path,
            ("war3", "jiubing2", "tasks", "atomic", "venomous_snake"),
        )


class TestBlackstoneReputationTask(unittest.TestCase):
    """测试 BlackstoneReputationTask 类属性。"""

    def setUp(self):
        self._orig = _mock_dm_modules()

    def tearDown(self):
        _restore_dm_modules(self._orig)

    def test_inherits_reputation_task(self):
        """应继承 ReputationTask。"""
        from GameBot.runner.tasks.war3.jiubing2.base import ReputationTask
        from GameBot.runner.tasks.war3.jiubing2.reputation.blackstone_reputation import BlackstoneReputationTask

        self.assertTrue(issubclass(BlackstoneReputationTask, ReputationTask))

    def test_atomic_name(self):
        """atomic_name 应为 '城门骚扰'。"""
        from GameBot.runner.tasks.war3.jiubing2.reputation.blackstone_reputation import BlackstoneReputationTask

        self.assertEqual(BlackstoneReputationTask.atomic_name, "城门骚扰")

    def test_task_config_path(self):
        """task_config_path 应指向 daily_reputation.blackstone。"""
        from GameBot.runner.tasks.war3.jiubing2.reputation.blackstone_reputation import BlackstoneReputationTask

        self.assertEqual(
            BlackstoneReputationTask.task_config_path,
            ("war3", "jiubing2", "tasks", "reputation", "daily_reputation", "blackstone"),
        )


class TestForestReputationTask(unittest.TestCase):
    """测试 ForestReputationTask 类属性。"""

    def setUp(self):
        self._orig = _mock_dm_modules()

    def tearDown(self):
        _restore_dm_modules(self._orig)

    def test_inherits_reputation_task(self):
        """应继承 ReputationTask。"""
        from GameBot.runner.tasks.war3.jiubing2.base import ReputationTask
        from GameBot.runner.tasks.war3.jiubing2.reputation.forest_reputation import ForestReputationTask

        self.assertTrue(issubclass(ForestReputationTask, ReputationTask))

    def test_atomic_name(self):
        """atomic_name 应为 '迅猛野兽'。"""
        from GameBot.runner.tasks.war3.jiubing2.reputation.forest_reputation import ForestReputationTask

        self.assertEqual(ForestReputationTask.atomic_name, "迅猛野兽")

    def test_task_config_path(self):
        """task_config_path 应指向 daily_reputation.forest。"""
        from GameBot.runner.tasks.war3.jiubing2.reputation.forest_reputation import ForestReputationTask

        self.assertEqual(
            ForestReputationTask.task_config_path,
            ("war3", "jiubing2", "tasks", "reputation", "daily_reputation", "forest"),
        )


if __name__ == "__main__":
    unittest.main()
