"""刷装备任务物品拾取 — 单元测试（mock 所有外部依赖）。

覆盖：
- get_inventory_hotkey / get_inventory_hotkeys（纯函数）
- CombatHelper.feed_pet（含多快捷键随机选择）
- PatrolLootTask._parse_item_targets / _match_desired / _all_items_satisfied
- PatrolLootTask._pickup_loop / _pickup_one / _handle_unclickable（mock 依赖）
"""
import random
import sys
import time
import unittest
from unittest.mock import MagicMock, patch, call

# Mock win32com 等大漠依赖，使 3.12 环境能导入 patrol_loot 模块
for _mod in ("win32com", "win32com.client", "pythoncom", "winreg",
             "win32gui", "win32con", "win32api"):
    if _mod not in sys.modules:
        sys.modules[_mod] = MagicMock()

from GameBot.runner.business.war3.jiubing2.combat_helper import (
    CombatHelper, get_inventory_hotkey, get_inventory_hotkeys,
)
import GameBot.runner.tasks.war3.jiubing2.others.patrol_loot  # noqa: F401 — 注册模块供 @patch 解析路径


HERO_CFG = {
    "skills": [
        {"key": "Q", "desc": "轨道炮", "target_type": "ground", "position": "target_area"},
        {"key": "T", "desc": "舰队信标", "target_type": "ground", "position": "target_area"},
        {"key": "R", "desc": "相位作战服", "target_type": "self"},
    ],
    "inventory": [
        {"id": 1, "hotkey": "1"},
        {"id": 8, "hotkey": "2"},
        {"id": 9, "hotkey": "5"},
        {"id": 0, "hotkey": "6"},
    ],
}

class TestGetInventoryHotkey(unittest.TestCase):

    def test_found(self):
        self.assertEqual(get_inventory_hotkey(HERO_CFG, 1), "1")
        self.assertEqual(get_inventory_hotkey(HERO_CFG, 9), "5")
        self.assertEqual(get_inventory_hotkey(HERO_CFG, 0), "6")

    def test_not_found(self):
        self.assertEqual(get_inventory_hotkey(HERO_CFG, 99), "")

    def test_empty_inventory(self):
        self.assertEqual(get_inventory_hotkey({}, 1), "")
        self.assertEqual(get_inventory_hotkey({"inventory": []}, 1), "")


class TestGetInventoryHotkeys(unittest.TestCase):
    """get_inventory_hotkeys（复数版）返回所有匹配快捷键。"""

    MULTI_HERO_CFG = {
        "inventory": [
            {"id": 9, "hotkey": "4"},
            {"id": 9, "hotkey": "5"},
            {"id": 0, "hotkey": "6"},
        ],
    }

    def test_single_match(self):
        self.assertEqual(get_inventory_hotkeys(HERO_CFG, 1), ["1"])

    def test_multi_match(self):
        result = get_inventory_hotkeys(self.MULTI_HERO_CFG, 9)
        self.assertEqual(result, ["4", "5"])

    def test_no_match(self):
        self.assertEqual(get_inventory_hotkeys(self.MULTI_HERO_CFG, 99), [])

    def test_empty_inventory(self):
        self.assertEqual(get_inventory_hotkeys({}, 9), [])

    def test_skip_items_without_hotkey(self):
        cfg = {"inventory": [{"id": 9, "hotkey": ""}, {"id": 9, "hotkey": "5"}]}
        self.assertEqual(get_inventory_hotkeys(cfg, 9), ["5"])


class TestCombatHelperFeedPet(unittest.TestCase):

    def setUp(self):
        self.mock_war3 = MagicMock()
        self.combat = CombatHelper(
            dm=MagicMock(), war3_cfg={}, hero_cfg=HERO_CFG,
            cfg={"pet": {"feeding_interval": 8.5}}, war3=self.mock_war3,
        )

    def test_feed_when_interval_passed(self):
        task = MagicMock()
        task.pet_feed_time = time.time() - 600
        self.combat.feed_pet(task)
        self.mock_war3.use_inventory_item.assert_called_once_with("5", None)

    def test_skip_when_interval_not_reached(self):
        task = MagicMock()
        task.pet_feed_time = time.time() - 60
        self.combat.feed_pet(task)
        self.mock_war3.use_inventory_item.assert_not_called()

    def test_skip_when_no_pet_food_hotkey(self):
        combat = CombatHelper(
            dm=MagicMock(), war3_cfg={}, hero_cfg={"inventory": []},
            cfg={"pet": {"feeding_interval": 1}}, war3=self.mock_war3,
        )
        task = MagicMock()
        task.pet_feed_time = time.time() - 999
        combat.feed_pet(task)
        self.mock_war3.use_inventory_item.assert_not_called()

    def test_feed_with_multiple_hotkeys_random_choice(self):
        """多格子宠物食物时，随机选一个快捷键。"""
        multi_hero_cfg = {
            "inventory": [
                {"id": 9, "hotkey": "4"},
                {"id": 9, "hotkey": "5"},
            ],
        }
        combat = CombatHelper(
            dm=MagicMock(), war3_cfg={}, hero_cfg=multi_hero_cfg,
            cfg={"pet": {"feeding_interval": 1}}, war3=self.mock_war3,
        )
        task = MagicMock()
        task.pet_feed_time = time.time() - 999
        with patch("GameBot.runner.business.war3.jiubing2.combat_helper.random.choice") as mock_choice:
            mock_choice.return_value = "4"
            combat.feed_pet(task)
        mock_choice.assert_called_once_with(["4", "5"])
        self.mock_war3.use_inventory_item.assert_called_once_with("4", None)


class TestPatrolLootItemLogic(unittest.TestCase):

    def test_parse_new_format(self):
        from GameBot.runner.tasks.war3.jiubing2.others.patrol_loot import PatrolLootTask
        items = [{"name": "屠戮者", "count": 3}, {"name": "魔龙之角", "count": 1}]
        targets = PatrolLootTask._parse_item_targets(items)
        self.assertEqual(targets["屠戮者"]["target"], 3)
        self.assertEqual(targets["魔龙之角"]["target"], 1)

    def test_parse_old_format(self):
        from GameBot.runner.tasks.war3.jiubing2.others.patrol_loot import PatrolLootTask
        targets = PatrolLootTask._parse_item_targets(["屠戮者", "魔龙之角"])
        self.assertEqual(targets["屠戮者"]["target"], 1)

    def test_match_desired_hit(self):
        from GameBot.runner.tasks.war3.jiubing2.others.patrol_loot import PatrolLootTask
        targets = PatrolLootTask._parse_item_targets(["屠戮者"])
        # _match_desired 是实例方法，用 unbound 方式调用
        result = PatrolLootTask._match_desired(
            type('Obj', (), {'item_targets': targets, 'item_text_cfg': {}})(), "【屠戮者】Lv.5")
        self.assertEqual(result, "屠戮者")

    def test_match_desired_miss(self):
        from GameBot.runner.tasks.war3.jiubing2.others.patrol_loot import PatrolLootTask
        targets = PatrolLootTask._parse_item_targets(["屠戮者"])
        result = PatrolLootTask._match_desired(
            type('Obj', (), {'item_targets': targets, 'item_text_cfg': {}})(), "魔龙之角")
        self.assertIsNone(result)

    def test_match_desired_already_satisfied(self):
        from GameBot.runner.tasks.war3.jiubing2.others.patrol_loot import PatrolLootTask
        targets = PatrolLootTask._parse_item_targets([{"name": "屠戮者", "count": 2}])
        targets["屠戮者"]["picked"] = 2
        result = PatrolLootTask._match_desired(
            type('Obj', (), {'item_targets': targets, 'item_text_cfg': {}})(), "屠戮者")
        self.assertIsNone(result)

    def test_all_items_satisfied_true(self):
        from GameBot.runner.tasks.war3.jiubing2.others.patrol_loot import PatrolLootTask
        targets = PatrolLootTask._parse_item_targets([{"name": "A", "count": 2}, {"name": "B", "count": 1}])
        targets["A"]["picked"] = 2
        targets["B"]["picked"] = 1
        obj = type('Obj', (), {'item_targets': targets})()
        self.assertTrue(PatrolLootTask._all_items_satisfied(obj))

    def test_all_items_satisfied_false(self):
        from GameBot.runner.tasks.war3.jiubing2.others.patrol_loot import PatrolLootTask
        targets = PatrolLootTask._parse_item_targets([{"name": "A", "count": 2}])
        targets["A"]["picked"] = 1
        obj = type('Obj', (), {'item_targets': targets})()
        self.assertFalse(PatrolLootTask._all_items_satisfied(obj))

    def test_all_items_satisfied_empty(self):
        from GameBot.runner.tasks.war3.jiubing2.others.patrol_loot import PatrolLootTask
        obj = type('Obj', (), {'item_targets': {}})()
        self.assertFalse(PatrolLootTask._all_items_satisfied(obj))

    def test_match_desired_with_char_fixes(self):
        """char_fixes 纠错后再匹配目标物品。"""
        from GameBot.runner.tasks.war3.jiubing2.others.patrol_loot import PatrolLootTask
        targets = PatrolLootTask._parse_item_targets(["白眼魔盔"])
        obj = type('Obj', (), {
            'item_targets': targets,
            'item_text_cfg': {'char_fixes': {'廣': '魔', '磨': '魔'}},
        })()
        # OCR 误识别 "魔" 为 "廣"，纠错后应匹配
        self.assertEqual(PatrolLootTask._match_desired(obj, "白眼廣盔"), "白眼魔盔")
        # 正确识别也应匹配
        self.assertEqual(PatrolLootTask._match_desired(obj, "白眼魔盔"), "白眼魔盔")
        # 无 char_fixes 时不纠错
        obj_no_fix = type('Obj', (), {
            'item_targets': targets,
            'item_text_cfg': {},
        })()
        self.assertIsNone(PatrolLootTask._match_desired(obj_no_fix, "白眼廣盔"))


class TestPatrolLootConfigDefaults(unittest.TestCase):
    """测试 PatrolLootTask 新增配置项的默认值和自定义值。"""

    def _make_task(self, cfg_override=None, chest_override=None):
        """构造一个最小可用的 PatrolLootTask 实例（不触发 DmClient 初始化）。"""
        from GameBot.runner.tasks.war3.jiubing2.others.patrol_loot import PatrolLootTask
        cfg = {
            "war3": {"jiubing2": {"tasks": {"others": {"patrol_loot": {}}}}},
            "hero": {}, "chest": {}, "item_text": {},
            "pickup": {}, "combat_status": {},
        }
        if cfg_override:
            cfg["war3"]["jiubing2"]["tasks"]["others"]["patrol_loot"].update(cfg_override)
        if chest_override:
            cfg["chest"].update(chest_override)
        # 用 __new__ 跳过 __init__ 中的 DmClient() 调用
        task = PatrolLootTask.__new__(PatrolLootTask)
        task.task_cfg = cfg
        task.cfg = cfg["war3"]["jiubing2"]["tasks"]["others"]["patrol_loot"]
        task.war3_cfg = cfg["war3"]
        task.hero_cfg = cfg["hero"]
        task.chest_cfg = cfg["chest"]
        task.item_text_cfg = cfg["item_text"]
        task.pickup_cfg = cfg["pickup"]
        task.patrol_cfg = task.cfg.get("patrol", {})
        task.combat_cfg = cfg["combat_status"]
        task.hwnd = None
        task.pet_feed_time = time.time()
        task.item_targets = PatrolLootTask._parse_item_targets(
            task.cfg.get('desired_items', []))
        task.storage_full = False
        task.hover_wait_time = task.chest_cfg.get('hover_wait_time', 1.5)
        task.mouse_avoid_pos = task.cfg.get('mouse_avoid_pos', [200, 200])
        task.feed_only_interval = task.cfg.get('feed_only_interval', 10)
        task.combat_timeout = task.cfg.get('combat_timeout', 120)
        return task

    def test_defaults(self):
        task = self._make_task()
        self.assertEqual(task.hover_wait_time, 1.5)
        self.assertEqual(task.mouse_avoid_pos, [200, 200])
        self.assertEqual(task.feed_only_interval, 10)
        self.assertEqual(task.combat_timeout, 120)

    def test_custom_values(self):
        task = self._make_task({
            "mouse_avoid_pos": [100, 100],
            "feed_only_interval": 30,
            "combat_timeout": 60,
        }, chest_override={"hover_wait_time": 2.0})
        self.assertEqual(task.hover_wait_time, 2.0)
        self.assertEqual(task.mouse_avoid_pos, [100, 100])
        self.assertEqual(task.feed_only_interval, 30)
        self.assertEqual(task.combat_timeout, 60)

    def test_read_item_name_defaults_match_config(self):
        """_read_item_name 的默认 offset_y/area_height 应与 jiubing2.toml 一致。"""
        task = self._make_task()
        # item_text_cfg 为空时，应使用与 jiubing2.toml [item_text] 一致的默认值
        self.assertEqual(task.item_text_cfg.get('offset_y', 50), 50)
        self.assertEqual(task.item_text_cfg.get('area_height', 60), 60)


class TestPatrolLootPickupLoop(unittest.TestCase):
    """_pickup_loop 拾取循环测试 — mock 宝箱检测/OCR/拾取，验证流程编排逻辑。"""

    def _make_task(self, desired_items=None):
        from GameBot.runner.tasks.war3.jiubing2.others.patrol_loot import PatrolLootTask
        cfg = {
            "war3": {"jiubing2": {"tasks": {"others": {"patrol_loot": {}}}}, "key_time": 0.1},
            "hero": {"inventory": [{"id": 0, "hotkey": "6"}]},
            "chest": {}, "item_text": {}, "pickup": {}, "combat_status": {},
            "command": {"clear_nearby": "-clear"},
        }
        if desired_items:
            cfg["war3"]["jiubing2"]["tasks"]["others"]["patrol_loot"]["desired_items"] = desired_items
        task = PatrolLootTask.__new__(PatrolLootTask)
        task.task_cfg = cfg
        task.cfg = cfg["war3"]["jiubing2"]["tasks"]["others"]["patrol_loot"]
        task.war3_cfg = cfg["war3"]
        task.hero_cfg = cfg["hero"]
        task.chest_cfg = cfg["chest"]
        task.item_text_cfg = cfg["item_text"]
        task.pickup_cfg = cfg["pickup"]
        task.patrol_cfg = task.cfg.get("patrol", {})
        task.combat_cfg = cfg["combat_status"]
        task.hwnd = None
        task.pet_feed_time = time.time()
        task.item_targets = PatrolLootTask._parse_item_targets(
            task.cfg.get('desired_items', []))
        task.storage_full = False
        task.hover_wait_time = 0
        task.mouse_avoid_pos = [200, 200]
        task.feed_only_interval = 10
        task.combat_timeout = 120
        task.dm = MagicMock()
        task.war3 = MagicMock()
        task.combat = MagicMock()
        task._stats = {
            'start_time': 0, 'rounds_completed': 0, 'chests_detected': 0,
            'items_picked': {}, 'items_skipped': 0, 'non_target_names': [],
            'combat_wait_total': 0, 'feed_count': 0,
        }
        task._progress_lines_callback = None
        return task

    def test_no_chests_breaks_immediately(self):
        """无宝箱时立即退出循环。"""
        task = self._make_task([{"name": "屠戮者", "count": 1}])
        task._find_all_chests = MagicMock(return_value=[])
        task._wait_non_combat = MagicMock()
        task._pickup_loop(MagicMock())
        self.assertEqual(task._stats['chests_detected'], 0)

    def test_all_items_satisfied_skips_loop(self):
        """所有物品已满足时跳过拾取。"""
        task = self._make_task([{"name": "屠戮者", "count": 1}])
        task.item_targets["屠戮者"]["picked"] = 1
        task._find_all_chests = MagicMock(return_value=[(0, 100, 200, 0.9)])
        task._pickup_loop(MagicMock())
        task._find_all_chests.assert_not_called()

    def test_target_item_picked(self):
        """检测到目标物品 → 拾取成功 → picked 计数+1。"""
        task = self._make_task([{"name": "屠戮者", "count": 2}])
        chests = [(0, 100, 200, 0.95)]
        task._find_all_chests = MagicMock(side_effect=[chests, []])
        task._read_item_name = MagicMock(return_value="屠戮者")
        task._pickup_one = MagicMock(return_value="picked")
        task._wait_non_combat = MagicMock()
        task._pickup_loop(MagicMock())
        self.assertEqual(task.item_targets["屠戮者"]["picked"], 1)
        self.assertEqual(task._stats['items_picked']["屠戮者"], 1)

    def test_non_target_item_skipped(self):
        """非目标物品加入 checked 列表，items_skipped+1。"""
        task = self._make_task([{"name": "屠戮者", "count": 1}])
        task._find_all_chests = MagicMock(side_effect=[[(0, 100, 200, 0.9)], []])
        task._read_item_name = MagicMock(return_value="魔龙之角")
        task._pickup_one = MagicMock()
        task._wait_non_combat = MagicMock()
        task._pickup_loop(MagicMock())
        task._pickup_one.assert_not_called()
        self.assertEqual(task._stats['items_skipped'], 1)

    def test_storage_full_stops_loop(self):
        """储物箱满时设置 storage_full 并退出。"""
        task = self._make_task([{"name": "屠戮者", "count": 1}])
        task._find_all_chests = MagicMock(return_value=[(0, 100, 200, 0.9)])
        task._read_item_name = MagicMock(return_value="屠戮者")
        task._pickup_one = MagicMock(return_value="storage_full")
        task._wait_non_combat = MagicMock()
        task._pickup_loop(MagicMock())
        self.assertTrue(task.storage_full)
        # 储物箱满不应触发清理地面
        task.war3.send_msg.assert_not_called()

    def test_unclickable_triggers_retry(self):
        """拾取不可点击时触发 _handle_unclickable 重试。"""
        task = self._make_task([{"name": "屠戮者", "count": 1}])
        task._find_all_chests = MagicMock(side_effect=[[(0, 100, 200, 0.9)], []])
        task._read_item_name = MagicMock(return_value="屠戮者")
        task._pickup_one = MagicMock(return_value="unclickable")
        task._handle_unclickable = MagicMock(return_value=True)
        task._wait_non_combat = MagicMock()
        task._pickup_loop(MagicMock())
        task._handle_unclickable.assert_called_once()
        self.assertEqual(task.item_targets["屠戮者"]["picked"], 1)

    def test_unclickable_retry_fails_added_to_checked(self):
        """重试失败后加入 checked，不再尝试该宝箱。"""
        task = self._make_task([{"name": "屠戮者", "count": 1}])
        task._find_all_chests = MagicMock(side_effect=[[(0, 100, 200, 0.9)], []])
        task._read_item_name = MagicMock(return_value="屠戮者")
        task._pickup_one = MagicMock(return_value="unclickable")
        task._handle_unclickable = MagicMock(return_value=False)
        task._wait_non_combat = MagicMock()
        task._pickup_loop(MagicMock())
        # 重试失败后 picked 不增加
        self.assertEqual(task.item_targets["屠戮者"]["picked"], 0)

    def test_unrecognized_item_skipped(self):
        """OCR 未识别到物品名时跳过。"""
        task = self._make_task([{"name": "屠戮者", "count": 1}])
        task._find_all_chests = MagicMock(side_effect=[[(0, 100, 200, 0.9)], []])
        task._read_item_name = MagicMock(return_value="")
        task._pickup_one = MagicMock()
        task._wait_non_combat = MagicMock()
        task._pickup_loop(MagicMock())
        task._pickup_one.assert_not_called()
        self.assertEqual(task._stats['items_skipped'], 1)


class TestPatrolLootPickupOne(unittest.TestCase):
    """_pickup_one 单次拾取操作测试 — mock dm/monitor，验证返回值。"""

    def _make_task(self):
        from GameBot.runner.tasks.war3.jiubing2.others.patrol_loot import PatrolLootTask
        cfg = {
            "war3": {"jiubing2": {"tasks": {"others": {"patrol_loot": {}}}}, "key_time": 0.1},
            "hero": {"inventory": [{"id": 0, "hotkey": "6"}]},
            "pickup": {"unclickable_text": "不可点击", "storage_full_text": "储物箱已满", "result_timeout": 0.1},
        }
        task = PatrolLootTask.__new__(PatrolLootTask)
        task.task_cfg = cfg
        task.cfg = cfg["war3"]["jiubing2"]["tasks"]["others"]["patrol_loot"]
        task.war3_cfg = cfg["war3"]
        task.hero_cfg = cfg["hero"]
        task.pickup_cfg = cfg["pickup"]
        task.dm = MagicMock()
        task.war3 = MagicMock()
        task._stop_event = None
        return task

    def test_returns_picked_on_timeout(self):
        """超时无错误提示 = 拾取成功。"""
        task = self._make_task()
        monitor = MagicMock()
        monitor.wait_for_any.return_value = None
        result = task._pickup_one(100, 200, monitor)
        self.assertEqual(result, "picked")

    def test_returns_unclickable(self):
        """监测到'不可点击'文本 → 返回 unclickable。"""
        task = self._make_task()
        monitor = MagicMock()
        monitor.wait_for_any.return_value = "不可点击"
        result = task._pickup_one(100, 200, monitor)
        self.assertEqual(result, "unclickable")

    def test_returns_storage_full(self):
        """监测到'储物箱已满'文本 → 返回 storage_full。"""
        task = self._make_task()
        monitor = MagicMock()
        monitor.wait_for_any.return_value = "储物箱已满"
        result = task._pickup_one(100, 200, monitor)
        self.assertEqual(result, "storage_full")

    def test_presses_correct_hotkey(self):
        """拾取时按物品栏 id=0（拾取）的快捷键。"""
        task = self._make_task()
        monitor = MagicMock()
        monitor.wait_for_any.return_value = None
        task._pickup_one(100, 200, monitor)
        task.dm.key_press_char.assert_any_call("6")


class TestPatrolLootHandleUnclickable(unittest.TestCase):
    """_handle_unclickable 不可点击重试逻辑测试。"""

    def _make_task(self, max_retries=3, retry_interval=0):
        from GameBot.runner.tasks.war3.jiubing2.others.patrol_loot import PatrolLootTask
        cfg = {
            "war3": {"jiubing2": {"tasks": {"others": {"patrol_loot": {}}}}},
            "hero": {},
            "pickup": {"max_retries": max_retries, "retry_interval": retry_interval},
        }
        task = PatrolLootTask.__new__(PatrolLootTask)
        task.task_cfg = cfg
        task.cfg = cfg["war3"]["jiubing2"]["tasks"]["others"]["patrol_loot"]
        task.war3_cfg = cfg["war3"]
        task.hero_cfg = cfg["hero"]
        task.pickup_cfg = cfg["pickup"]
        task.storage_full = False
        task.dm = MagicMock()
        task.war3 = MagicMock()
        task._stop_event = None
        return task

    @patch("GameBot.runner.tasks.war3.jiubing2.others.patrol_loot.time.sleep")
    def test_succeeds_on_first_retry(self, mock_sleep):
        task = self._make_task()
        task._pickup_one = MagicMock(side_effect=["picked"])
        result = task._handle_unclickable(100, 200, MagicMock())
        self.assertTrue(result)

    @patch("GameBot.runner.tasks.war3.jiubing2.others.patrol_loot.time.sleep")
    def test_succeeds_on_second_retry(self, mock_sleep):
        task = self._make_task(max_retries=3)
        task._pickup_one = MagicMock(side_effect=["unclickable", "picked"])
        result = task._handle_unclickable(100, 200, MagicMock())
        self.assertTrue(result)

    @patch("GameBot.runner.tasks.war3.jiubing2.others.patrol_loot.time.sleep")
    def test_fails_after_max_retries(self, mock_sleep):
        task = self._make_task(max_retries=2)
        task._pickup_one = MagicMock(side_effect=["unclickable", "unclickable", "unclickable"])
        result = task._handle_unclickable(100, 200, MagicMock())
        self.assertFalse(result)

    @patch("GameBot.runner.tasks.war3.jiubing2.others.patrol_loot.time.sleep")
    def test_storage_full_during_retry(self, mock_sleep):
        task = self._make_task()
        task._pickup_one = MagicMock(side_effect=["storage_full"])
        result = task._handle_unclickable(100, 200, MagicMock())
        self.assertFalse(result)
        self.assertTrue(task.storage_full)


class TestPatrolLootTryPickupChest(unittest.TestCase):
    """_try_pickup_chest 单个宝箱识别+拾取测试。"""

    def _make_task(self):
        from GameBot.runner.tasks.war3.jiubing2.others.patrol_loot import PatrolLootTask
        cfg = {
            "war3": {"jiubing2": {"tasks": {"others": {"patrol_loot": {}}}}, "key_time": 0.1},
            "hero": {},
            "chest": {}, "item_text": {"char_fixes": {"廣": "魔"}}, "pickup": {},
        }
        task = PatrolLootTask.__new__(PatrolLootTask)
        task.task_cfg = cfg
        task.cfg = cfg["war3"]["jiubing2"]["tasks"]["others"]["patrol_loot"]
        task.war3_cfg = cfg["war3"]
        task.hero_cfg = cfg["hero"]
        task.chest_cfg = cfg["chest"]
        task.item_text_cfg = cfg["item_text"]
        task.pickup_cfg = cfg["pickup"]
        task.hwnd = None
        task.storage_full = False
        task.hover_wait_time = 0
        task.mouse_avoid_pos = [200, 200]
        task.item_targets = PatrolLootTask._parse_item_targets([{"name": "白眼魔盔", "count": 2}])
        task.dm = MagicMock()
        task._stats = {
            'items_picked': {}, 'items_skipped': 0, 'non_target_names': [],
        }
        task._progress_lines_callback = None
        return task

    @patch("GameBot.runner.tasks.war3.jiubing2.others.patrol_loot.time.sleep")
    def test_non_target_returns_none(self, mock_sleep):
        """非目标物品返回 None，items_skipped+1。"""
        task = self._make_task()
        task._read_item_name = MagicMock(return_value="屠戮者")
        task._pickup_one = MagicMock()
        result = task._try_pickup_chest(0, 100, 200, 0.9, MagicMock())
        self.assertIsNone(result)
        self.assertEqual(task._stats['items_skipped'], 1)
        task._pickup_one.assert_not_called()

    @patch("GameBot.runner.tasks.war3.jiubing2.others.patrol_loot.time.sleep")
    def test_unrecognized_returns_none(self, mock_sleep):
        """OCR 未识别返回空字符串 → None。"""
        task = self._make_task()
        task._read_item_name = MagicMock(return_value="")
        result = task._try_pickup_chest(0, 100, 200, 0.9, MagicMock())
        self.assertIsNone(result)
        self.assertEqual(task._stats['items_skipped'], 1)

    @patch("GameBot.runner.tasks.war3.jiubing2.others.patrol_loot.time.sleep")
    def test_picked_success(self, mock_sleep):
        """目标物品拾取成功 → True，picked+1。"""
        task = self._make_task()
        task._read_item_name = MagicMock(return_value="白眼魔盔")
        task._pickup_one = MagicMock(return_value="picked")
        result = task._try_pickup_chest(0, 100, 200, 0.9, MagicMock())
        self.assertTrue(result)
        self.assertEqual(task.item_targets["白眼魔盔"]["picked"], 1)
        self.assertEqual(task._stats['items_picked']["白眼魔盔"], 1)

    @patch("GameBot.runner.tasks.war3.jiubing2.others.patrol_loot.time.sleep")
    def test_storage_full_sets_flag(self, mock_sleep):
        """储物箱满 → False，storage_full=True。"""
        task = self._make_task()
        task._read_item_name = MagicMock(return_value="白眼魔盔")
        task._pickup_one = MagicMock(return_value="storage_full")
        result = task._try_pickup_chest(0, 100, 200, 0.9, MagicMock())
        self.assertFalse(result)
        self.assertTrue(task.storage_full)

    @patch("GameBot.runner.tasks.war3.jiubing2.others.patrol_loot.time.sleep")
    def test_unclickable_retry_success(self, mock_sleep):
        """不可点击 → 重试成功 → True，picked+1。"""
        task = self._make_task()
        task._read_item_name = MagicMock(return_value="白眼魔盔")
        task._pickup_one = MagicMock(return_value="unclickable")
        task._handle_unclickable = MagicMock(return_value=True)
        result = task._try_pickup_chest(0, 100, 200, 0.9, MagicMock())
        self.assertTrue(result)
        self.assertEqual(task.item_targets["白眼魔盔"]["picked"], 1)

    @patch("GameBot.runner.tasks.war3.jiubing2.others.patrol_loot.time.sleep")
    def test_unclickable_retry_fail(self, mock_sleep):
        """不可点击 → 重试失败 → False，picked 不变。"""
        task = self._make_task()
        task._read_item_name = MagicMock(return_value="白眼魔盔")
        task._pickup_one = MagicMock(return_value="unclickable")
        task._handle_unclickable = MagicMock(return_value=False)
        result = task._try_pickup_chest(0, 100, 200, 0.9, MagicMock())
        self.assertFalse(result)
        self.assertEqual(task.item_targets["白眼魔盔"]["picked"], 0)

    @patch("GameBot.runner.tasks.war3.jiubing2.others.patrol_loot.time.sleep")
    def test_char_fixes_applied_before_match(self, mock_sleep):
        """OCR 形近字纠错后再匹配。"""
        task = self._make_task()
        task._read_item_name = MagicMock(return_value="白眼廣盔")
        task._pickup_one = MagicMock(return_value="picked")
        result = task._try_pickup_chest(0, 100, 200, 0.9, MagicMock())
        self.assertTrue(result)
        self.assertEqual(task._stats['items_picked']["白眼魔盔"], 1)


class TestPatrolLootMarkPicked(unittest.TestCase):

    def test_mark_picked_updates_count_and_stats(self):
        from GameBot.runner.tasks.war3.jiubing2.others.patrol_loot import PatrolLootTask
        task = PatrolLootTask.__new__(PatrolLootTask)
        task.item_targets = {"A": {'target': 3, 'picked': 1}}
        task._stats = {'items_picked': {}, 'items_skipped': 0}
        task._progress_lines_callback = None
        task._mark_picked("A", "A")
        self.assertEqual(task.item_targets["A"]["picked"], 2)
        self.assertEqual(task._stats['items_picked']["A"], 1)

    def test_mark_picked_accumulates_stats(self):
        from GameBot.runner.tasks.war3.jiubing2.others.patrol_loot import PatrolLootTask
        task = PatrolLootTask.__new__(PatrolLootTask)
        task.item_targets = {"A": {'target': 3, 'picked': 0}}
        task._stats = {'items_picked': {"A": 1}, 'items_skipped': 0}
        task._progress_lines_callback = None
        task._mark_picked("A", "A")
        self.assertEqual(task._stats['items_picked']["A"], 2)

    def test_mark_picked_uses_matched_item_for_stats(self):
        """stats key 应使用 matched_item（目标名）而非原始 OCR 文本。"""
        from GameBot.runner.tasks.war3.jiubing2.others.patrol_loot import PatrolLootTask
        task = PatrolLootTask.__new__(PatrolLootTask)
        task.item_targets = {"白眼魔盔": {'target': 2, 'picked': 0}}
        task._stats = {'items_picked': {}, 'items_skipped': 0}
        task._progress_lines_callback = None
        # OCR 返回 "白眼廣盔"，但 matched_item 为 "白眼魔盔"
        task._mark_picked("白眼魔盔", "白眼廣盔")
        self.assertEqual(task._stats['items_picked']["白眼魔盔"], 1)
        self.assertNotIn("白眼廣盔", task._stats['items_picked'])


if __name__ == "__main__":
    unittest.main()
