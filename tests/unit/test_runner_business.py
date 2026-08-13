"""runner/business 层纯逻辑单元测试。

覆盖：
- NearbyCleaner: 概率清理（触发/不触发/禁用/指令选择）
- ResourceManager: 路径管理（初始化/缓存/不存在文件异常）
- EndlessRunner._on_arrive: 楼层门控（过滤水晶 action / 保留其他 action / 无 action）
- KKBusiness: 掉线弹窗检测（尺寸匹配/不匹配/无窗口/异常回退）
- Base: sleep / is_dm_valid
"""
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

pytestmark = [pytest.mark.unit]

# Mock Windows COM 依赖
_DM_MODULES = (
    "win32com", "win32com.client", "pythoncom", "pywintypes",
    "winreg", "win32gui", "win32con", "win32api",
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


class TestNearbyCleaner(unittest.TestCase):
    """测试 NearbyCleaner 概率清理逻辑。"""

    def setUp(self):
        self._orig = _mock_dm_modules()

    def tearDown(self):
        _restore_dm_modules(self._orig)

    def _make_cleaner(self, probability=0.0, use_endless_cmd=False, cmd_cfg=None):
        from GameBot.runner.business.war3.jiubing2.nearby_cleaner import NearbyCleaner
        war3 = MagicMock()
        if cmd_cfg is None:
            cmd_cfg = {"clear_nearby": "-delh", "clear_endless": "-clear"}
        return NearbyCleaner(war3, cmd_cfg, probability=probability,
                             use_endless_cmd=use_endless_cmd)

    def test_disabled_probability_zero(self):
        """probability=0 时 tick 应直接返回，不调用 send_msg。"""
        cleaner = self._make_cleaner(probability=0.0)
        cleaner.tick()
        cleaner._war3.send_msg.assert_not_called()

    def test_disabled_probability_negative(self):
        """负概率也应禁用。"""
        cleaner = self._make_cleaner(probability=-0.1)
        cleaner.tick()
        cleaner._war3.send_msg.assert_not_called()

    @patch("GameBot.runner.business.war3.jiubing2.nearby_cleaner.random")
    def test_triggers_when_random_below_probability(self, mock_random):
        """random.random() < probability 时应触发清理。"""
        mock_random.random.return_value = 0.3
        cleaner = self._make_cleaner(probability=0.5)
        cleaner.tick()
        cleaner._war3.send_msg.assert_called_once_with("-delh")

    @patch("GameBot.runner.business.war3.jiubing2.nearby_cleaner.random")
    def test_does_not_trigger_when_random_above_probability(self, mock_random):
        """random.random() >= probability 时不应触发。"""
        mock_random.random.return_value = 0.6
        cleaner = self._make_cleaner(probability=0.5)
        cleaner.tick()
        cleaner._war3.send_msg.assert_not_called()

    @patch("GameBot.runner.business.war3.jiubing2.nearby_cleaner.random")
    def test_uses_endless_cmd_when_enabled(self, mock_random):
        """use_endless_cmd=True 时应使用 clear_endless 指令。"""
        mock_random.random.return_value = 0.1
        cleaner = self._make_cleaner(probability=0.5, use_endless_cmd=True)
        cleaner.tick()
        cleaner._war3.send_msg.assert_called_once_with("-clear")

    @patch("GameBot.runner.business.war3.jiubing2.nearby_cleaner.random")
    def test_fallback_default_cmd_when_missing(self, mock_random):
        """配置中缺少 clear_nearby 时应回退到默认 -delh。"""
        mock_random.random.return_value = 0.1
        cleaner = self._make_cleaner(probability=0.5, cmd_cfg={})
        cleaner.tick()
        cleaner._war3.send_msg.assert_called_once_with("-delh")

    @patch("GameBot.runner.business.war3.jiubing2.nearby_cleaner.random")
    def test_fallback_endless_cmd_when_missing(self, mock_random):
        """配置中缺少 clear_endless 时应回退到默认 -delh。"""
        mock_random.random.return_value = 0.1
        cleaner = self._make_cleaner(
            probability=0.5, use_endless_cmd=True, cmd_cfg={}
        )
        cleaner.tick()
        cleaner._war3.send_msg.assert_called_once_with("-delh")

    def test_reset_is_noop(self):
        """reset 应为空操作，不抛异常。"""
        cleaner = self._make_cleaner()
        cleaner.reset()

    @patch("GameBot.runner.business.war3.jiubing2.nearby_cleaner.random")
    def test_probability_boundary_exact_zero_random(self, mock_random):
        """random() 正好等于 0 时应触发（0 < probability）。"""
        mock_random.random.return_value = 0.0
        cleaner = self._make_cleaner(probability=0.01)
        cleaner.tick()
        cleaner._war3.send_msg.assert_called_once()

    @patch("GameBot.runner.business.war3.jiubing2.nearby_cleaner.random")
    def test_probability_boundary_exact_match(self, mock_random):
        """random() 正好等于 probability 时不应触发（严格小于）。"""
        mock_random.random.return_value = 0.5
        cleaner = self._make_cleaner(probability=0.5)
        cleaner.tick()
        cleaner._war3.send_msg.assert_not_called()

    @patch("GameBot.runner.business.war3.jiubing2.nearby_cleaner.random")
    def test_probability_one_always_triggers(self, mock_random):
        """probability=1.0 时除 random()=1.0 外都应触发。"""
        mock_random.random.return_value = 0.999
        cleaner = self._make_cleaner(probability=1.0)
        cleaner.tick()
        cleaner._war3.send_msg.assert_called_once()


class TestResourceManager(unittest.TestCase):
    """测试 ResourceManager 路径管理。"""

    def setUp(self):
        self._orig = _mock_dm_modules()

    def tearDown(self):
        _restore_dm_modules(self._orig)

    def _make_mgr(self, tmp_path):
        """创建一个 ResourceManager 实例，mock config.get_path 返回 tmp_path。"""
        from GameBot.runner.resource_manager import ResourceManager
        mgr = ResourceManager()
        with patch("GameBot.runner.resource_manager.config") as mock_config:
            mock_config.get_path.return_value = tmp_path
            mgr._ensure_initialized()
        return mgr

    def test_images_dir_created(self):
        """_ensure_initialized 应创建 images 目录。"""
        mgr = self._make_mgr(Path("__nonexistent__"))
        # 用 tmp_path 更好
        import tempfile
        tmp = Path(tempfile.mkdtemp())
        try:
            mgr = self._make_mgr(tmp)
            self.assertTrue((tmp / "images").exists())
            self.assertTrue((tmp / "fonts").exists())
        finally:
            import shutil
            shutil.rmtree(tmp, ignore_errors=True)

    def test_get_image_path_existing(self):
        """存在的图片应返回绝对路径。"""
        import tempfile
        tmp = Path(tempfile.mkdtemp())
        try:
            mgr = self._make_mgr(tmp)
            img_file = tmp / "images" / "test.png"
            img_file.write_text("fake")
            result = mgr.get_image_path("test.png")
            self.assertEqual(result, str(img_file))
        finally:
            import shutil
            shutil.rmtree(tmp, ignore_errors=True)

    def test_get_image_path_cached(self):
        """第二次调用应返回缓存值，不检查文件是否存在。"""
        import tempfile
        tmp = Path(tempfile.mkdtemp())
        try:
            mgr = self._make_mgr(tmp)
            img_file = tmp / "images" / "cached.png"
            img_file.write_text("fake")

            first = mgr.get_image_path("cached.png")
            # 删除文件后再次调用，应返回缓存值
            img_file.unlink()
            second = mgr.get_image_path("cached.png")
            self.assertEqual(first, second)
        finally:
            import shutil
            shutil.rmtree(tmp, ignore_errors=True)

    def test_get_image_path_not_found(self):
        """不存在的图片应抛出 ResourceNotFoundError。"""
        import tempfile
        tmp = Path(tempfile.mkdtemp())
        try:
            from GameBot.utils.exception_handler import ResourceNotFoundError
            mgr = self._make_mgr(tmp)
            with self.assertRaises(ResourceNotFoundError):
                mgr.get_image_path("nonexistent.png")
        finally:
            import shutil
            shutil.rmtree(tmp, ignore_errors=True)

    def test_get_font_path_existing(self):
        """存在的字体应返回绝对路径。"""
        import tempfile
        tmp = Path(tempfile.mkdtemp())
        try:
            mgr = self._make_mgr(tmp)
            font_file = tmp / "fonts" / "test.ttf"
            font_file.write_text("fake")
            result = mgr.get_font_path("test.ttf")
            self.assertEqual(result, str(font_file))
        finally:
            import shutil
            shutil.rmtree(tmp, ignore_errors=True)

    def test_get_font_path_not_found(self):
        """不存在的字体应抛出 ResourceNotFoundError。"""
        import tempfile
        tmp = Path(tempfile.mkdtemp())
        try:
            from GameBot.utils.exception_handler import ResourceNotFoundError
            mgr = self._make_mgr(tmp)
            with self.assertRaises(ResourceNotFoundError):
                mgr.get_font_path("nonexistent.ttf")
        finally:
            import shutil
            shutil.rmtree(tmp, ignore_errors=True)

    def test_properties_return_paths(self):
        """resources_dir / images_dir / fonts_dir 应返回正确路径。"""
        import tempfile
        tmp = Path(tempfile.mkdtemp())
        try:
            mgr = self._make_mgr(tmp)
            self.assertEqual(mgr.resources_dir, tmp)
            self.assertEqual(mgr.images_dir, tmp / "images")
            self.assertEqual(mgr.fonts_dir, tmp / "fonts")
        finally:
            import shutil
            shutil.rmtree(tmp, ignore_errors=True)


class TestEndlessRunnerOnArrive(unittest.TestCase):
    """测试 EndlessRunner._on_arrive 楼层门控逻辑。"""

    def setUp(self):
        self._orig = _mock_dm_modules()

    def tearDown(self):
        _restore_dm_modules(self._orig)

    def _make_runner(self, endless_cfg=None):
        from GameBot.runner.business.war3.jiubing2.endless_runner import EndlessRunner
        dm = MagicMock()
        war3 = MagicMock()
        ui = MagicMock()
        combat = MagicMock()
        runner = EndlessRunner(
            dm, war3, ui, combat,
            war3_cfg={"general_time": 0.3, "key_time": 0.05},
            hero_cfg={},
            cfg={"game": {}, "command": {}, "prompt_text": {}},
        )
        return runner

    def test_filters_shard_action_below_threshold(self):
        """楼层低于 use_shard_floor 时应过滤 id=8 的 item action。"""
        runner = self._make_runner()
        pt = {
            "coords": [100, 100],
            "actions": [
                {"type": "item", "id": 8},
                {"type": "skill", "id": 1},
            ],
        }
        endless_cfg = {"use_shard_floor": 5}

        runner._on_arrive(MagicMock(), pt, 3, 0, [pt], endless_cfg)

        call_args = runner._combat.execute_actions.call_args
        pt_eff = call_args[0][0]
        actions = pt_eff.get("actions", [])
        self.assertEqual(len(actions), 1)
        self.assertEqual(actions[0]["type"], "skill")

    def test_keeps_shard_action_at_or_above_threshold(self):
        """楼层 >= use_shard_floor 时应保留 id=8 的 item action。"""
        runner = self._make_runner()
        pt = {
            "coords": [100, 100],
            "actions": [
                {"type": "item", "id": 8},
                {"type": "skill", "id": 1},
            ],
        }
        endless_cfg = {"use_shard_floor": 5}

        runner._on_arrive(MagicMock(), pt, 5, 0, [pt], endless_cfg)

        call_args = runner._combat.execute_actions.call_args
        pt_eff = call_args[0][0]
        actions = pt_eff.get("actions", [])
        self.assertEqual(len(actions), 2)

    def test_no_actions(self):
        """无 actions 时应直接调用 execute_actions。"""
        runner = self._make_runner()
        pt = {"coords": [100, 100]}
        endless_cfg = {"use_shard_floor": 5}

        runner._on_arrive(MagicMock(), pt, 1, 0, [pt], endless_cfg)

        runner._combat.execute_actions.assert_called_once()

    def test_all_actions_filtered_removes_key(self):
        """所有 action 都被过滤时应移除 actions 键。"""
        runner = self._make_runner()
        pt = {
            "coords": [100, 100],
            "actions": [
                {"type": "item", "id": 8},
            ],
        }
        endless_cfg = {"use_shard_floor": 10}

        runner._on_arrive(MagicMock(), pt, 1, 0, [pt], endless_cfg)

        call_args = runner._combat.execute_actions.call_args
        pt_eff = call_args[0][0]
        self.assertNotIn("actions", pt_eff)

    def test_no_use_shard_floor_keeps_all(self):
        """未配置 use_shard_floor 时应保留所有 action。"""
        runner = self._make_runner()
        pt = {
            "coords": [100, 100],
            "actions": [
                {"type": "item", "id": 8},
                {"type": "skill", "id": 1},
            ],
        }
        endless_cfg = {}

        runner._on_arrive(MagicMock(), pt, 1, 0, [pt], endless_cfg)

        call_args = runner._combat.execute_actions.call_args
        pt_eff = call_args[0][0]
        actions = pt_eff.get("actions", [])
        self.assertEqual(len(actions), 2)

    def test_original_pt_not_modified(self):
        """_on_arrive 不应修改原始 pt 字典。"""
        runner = self._make_runner()
        pt = {
            "coords": [100, 100],
            "actions": [
                {"type": "item", "id": 8},
                {"type": "skill", "id": 1},
            ],
        }
        original_actions = list(pt["actions"])
        endless_cfg = {"use_shard_floor": 10}

        runner._on_arrive(MagicMock(), pt, 1, 0, [pt], endless_cfg)

        # 原始 pt 的 actions 不应被修改
        self.assertEqual(len(pt["actions"]), len(original_actions))

    def test_shard_id_as_string(self):
        """id 为字符串 '8' 时也应被过滤。"""
        runner = self._make_runner()
        pt = {
            "coords": [100, 100],
            "actions": [
                {"type": "item", "id": "8"},
                {"type": "skill", "id": 1},
            ],
        }
        endless_cfg = {"use_shard_floor": 5}

        runner._on_arrive(MagicMock(), pt, 1, 0, [pt], endless_cfg)

        call_args = runner._combat.execute_actions.call_args
        pt_eff = call_args[0][0]
        actions = pt_eff.get("actions", [])
        self.assertEqual(len(actions), 1)
        self.assertEqual(actions[0]["type"], "skill")


class TestKKBusiness(unittest.TestCase):
    """测试 KKBusiness 掉线弹窗检测逻辑。"""

    def setUp(self):
        self._orig = _mock_dm_modules()

    def tearDown(self):
        _restore_dm_modules(self._orig)

    def _make_kk(self, kk_cfg=None):
        from GameBot.runner.business.kk import KKBusiness
        dm = MagicMock()
        if kk_cfg is None:
            kk_cfg = {
                "window_class": "KKClass",
                "window_title": "KKTitle",
                "create_room_window_class": "DialogClass",
                "disconnect_dialog": {
                    "window_size": [440, 260],
                    "cancel_button_coords": [317, 192],
                    "cancel_wait_time": 3,
                },
            }
        return KKBusiness(dm, kk_cfg)

    def test_no_window_found(self):
        """未找到窗口时应返回 False。"""
        kk = self._make_kk()
        kk.dm.find_window.return_value = 0
        result = kk.handle_disconnect_dialog(kk.dm)
        self.assertFalse(result)

    def test_window_size_matches_dialog(self):
        """窗口尺寸匹配弹窗尺寸时应处理并返回 True。"""
        kk = self._make_kk()
        kk.dm.find_window.return_value = 12345
        kk.dm.get_client_rect.return_value = (0, 0, 440, 260)

        result = kk.handle_disconnect_dialog(kk.dm)
        self.assertTrue(result)
        kk.dm.set_client_size.assert_called_once_with(12345, 440, 260)
        kk.dm.move_to.assert_called_once_with(317, 192)
        kk.dm.left_click.assert_called_once()

    def test_window_size_does_not_match(self):
        """窗口尺寸不匹配时应返回 False。"""
        kk = self._make_kk()
        kk.dm.find_window.return_value = 12345
        kk.dm.get_client_rect.return_value = (0, 0, 1328, 945)  # 主窗口尺寸

        result = kk.handle_disconnect_dialog(kk.dm)
        self.assertFalse(result)
        kk.dm.move_to.assert_not_called()

    def test_get_client_rect_exception_returns_false(self):
        """get_client_rect 抛异常时应返回 False。"""
        kk = self._make_kk()
        kk.dm.find_window.return_value = 12345
        kk.dm.get_client_rect.side_effect = Exception("COM error")

        result = kk.handle_disconnect_dialog(kk.dm)
        self.assertFalse(result)

    def test_default_dialog_size_when_not_configured(self):
        """未配置 dialog window_size 时应使用默认 [440, 260]。"""
        kk_cfg = {
            "window_class": "KKClass",
            "window_title": "KKTitle",
            "create_room_window_class": "DialogClass",
        }
        kk = self._make_kk(kk_cfg)
        kk.dm.find_window.return_value = 12345
        kk.dm.get_client_rect.return_value = (0, 0, 440, 260)

        result = kk.handle_disconnect_dialog(kk.dm)
        self.assertTrue(result)

    def test_default_cancel_coords_when_not_configured(self):
        """未配置 cancel_button_coords 时应使用默认 [317, 192]。"""
        kk_cfg = {
            "window_class": "KKClass",
            "window_title": "KKTitle",
            "create_room_window_class": "DialogClass",
            "disconnect_dialog": {"window_size": [440, 260]},
        }
        kk = self._make_kk(kk_cfg)
        kk.dm.find_window.return_value = 12345
        kk.dm.get_client_rect.return_value = (0, 0, 440, 260)

        kk.handle_disconnect_dialog(kk.dm)
        kk.dm.move_to.assert_called_once_with(317, 192)


class TestBaseBusiness(unittest.TestCase):
    """测试 Base business 类的纯逻辑方法。"""

    def setUp(self):
        self._orig = _mock_dm_modules()

    def tearDown(self):
        _restore_dm_modules(self._orig)

    def test_is_dm_valid_with_version(self):
        """dm.version 非空时 is_dm_valid 应返回 True。"""
        from GameBot.runner.business.base import Base
        dm = MagicMock()
        dm.version = "3.1233"
        # Base 是 ABC，需要通过子类实例化
        class ConcreteBase(Base):
            pass
        obj = ConcreteBase(dm)
        self.assertTrue(obj.is_dm_valid())

    def test_is_dm_valid_empty_version(self):
        """dm.version 为空时 is_dm_valid 应返回 False。"""
        from GameBot.runner.business.base import Base
        dm = MagicMock()
        dm.version = ""
        class ConcreteBase(Base):
            pass
        obj = ConcreteBase(dm)
        self.assertFalse(obj.is_dm_valid())

    def test_sleep_calls_time_sleep(self):
        """sleep 应委托给 time.sleep。"""
        from GameBot.runner.business.base import Base
        dm = MagicMock()
        class ConcreteBase(Base):
            pass
        obj = ConcreteBase(dm)
        with patch("GameBot.runner.business.base.time") as mock_time:
            obj.sleep(1.5)
            mock_time.sleep.assert_called_once_with(1.5)


if __name__ == "__main__":
    unittest.main()
