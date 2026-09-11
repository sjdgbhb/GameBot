"""任务基类纯逻辑单元测试。

覆盖 AtomicLoopTask._get_nested / _interruptible_sleep / _run_loop / _effective_times、
ReputationTask._effective_times / _report_progress / _build_atomic_cfg、
AtomicTaskBase._interruptible_wait / run、
_CombinedEvent 等不依赖大漠 COM 的纯逻辑方法。
"""

import sys
import threading
import unittest
from unittest.mock import MagicMock, patch

import pytest

pytestmark = [pytest.mark.unit]

# Mock Windows COM 依赖，使主环境 3.12 可导入 runner 模块
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
    """在 sys.modules 中注入 mock 的 Windows COM 模块。"""
    originals = {name: sys.modules.get(name) for name in _DM_MODULES}
    for name in _DM_MODULES:
        sys.modules[name] = MagicMock()
    return originals


def _restore_dm_modules(originals):
    """恢复原始 sys.modules 状态。"""
    for name, mod in originals.items():
        if mod is None:
            sys.modules.pop(name, None)
        else:
            sys.modules[name] = mod


class TestGetNested(unittest.TestCase):
    """测试 AtomicLoopTask._get_nested 静态方法。"""

    def setUp(self):
        self._orig = _mock_dm_modules()

    def tearDown(self):
        _restore_dm_modules(self._orig)

    def test_get_nested_simple_path(self):
        """单层路径应正确提取。"""
        from GameBot.runner.tasks.war3.jiubing2.base import AtomicLoopTask

        cfg = {"a": {"b": {"c": 42}}}
        self.assertEqual(AtomicLoopTask._get_nested(cfg, ("a",)), {"b": {"c": 42}})

    def test_get_nested_deep_path(self):
        """多层路径应正确提取。"""
        from GameBot.runner.tasks.war3.jiubing2.base import AtomicLoopTask

        cfg = {"a": {"b": {"c": 42}}}
        self.assertEqual(AtomicLoopTask._get_nested(cfg, ("a", "b", "c")), 42)

    def test_get_nested_missing_key(self):
        """缺失的键应返回空字典（不抛异常）。"""
        from GameBot.runner.tasks.war3.jiubing2.base import AtomicLoopTask

        cfg = {"a": {"b": 1}}
        self.assertEqual(AtomicLoopTask._get_nested(cfg, ("a", "x", "y")), {})

    def test_get_nested_none_path(self):
        """path 为 None 应返回空字典。"""
        from GameBot.runner.tasks.war3.jiubing2.base import AtomicLoopTask

        self.assertEqual(AtomicLoopTask._get_nested({"a": 1}, None), {})

    def test_get_nested_empty_dict(self):
        """空字典应返回空字典。"""
        from GameBot.runner.tasks.war3.jiubing2.base import AtomicLoopTask

        self.assertEqual(AtomicLoopTask._get_nested({}, ("a", "b")), {})

    def test_get_nested_empty_path(self):
        """空路径元组应返回原字典。"""
        from GameBot.runner.tasks.war3.jiubing2.base import AtomicLoopTask

        cfg = {"a": 1}
        self.assertEqual(AtomicLoopTask._get_nested(cfg, ()), cfg)


class TestInterruptibleSleep(unittest.TestCase):
    """测试 AtomicLoopTask._interruptible_sleep。"""

    def setUp(self):
        self._orig = _mock_dm_modules()

    def tearDown(self):
        _restore_dm_modules(self._orig)

    def _make_task(self):
        """构造一个不触发 __init__ 的 AtomicLoopTask 实例。"""
        from GameBot.runner.tasks.war3.jiubing2.base import AtomicLoopTask

        task = AtomicLoopTask.__new__(AtomicLoopTask)
        return task

    def test_sleep_without_stop_event(self):
        """无 stop_event 时应正常 sleep。"""
        task = self._make_task()
        task._stop_event = None
        with patch("GameBot.runner.tasks.war3.jiubing2.base.time") as mock_time:
            task._interruptible_sleep(1.5)
            mock_time.sleep.assert_called_once_with(1.5)

    def test_sleep_with_stop_event_not_set(self):
        """stop_event 未设置时应等待并返回。"""
        task = self._make_task()
        stop_event = MagicMock(spec=threading.Event)
        stop_event.wait.return_value = False  # 未被 set
        task._stop_event = stop_event

        task._interruptible_sleep(2.0)
        stop_event.wait.assert_called_once_with(2.0)

    def test_sleep_with_stop_event_set(self):
        """stop_event 已设置时应抛出 StopTaskError。"""
        from GameBot.utils.exception_handler import StopTaskError

        task = self._make_task()
        stop_event = MagicMock(spec=threading.Event)
        stop_event.wait.return_value = True  # 被 set
        task._stop_event = stop_event

        with self.assertRaises(StopTaskError):
            task._interruptible_sleep(2.0)


class TestRunLoop(unittest.TestCase):
    """测试 AtomicLoopTask._run_loop 循环逻辑。"""

    def setUp(self):
        self._orig = _mock_dm_modules()

    def tearDown(self):
        _restore_dm_modules(self._orig)

    def _make_task(self, cfg=None):
        """构造一个不触发 __init__ 的 AtomicLoopTask 实例。"""
        from GameBot.runner.tasks.war3.jiubing2.base import AtomicLoopTask

        task = AtomicLoopTask.__new__(AtomicLoopTask)
        task.cfg = cfg or {}
        task.atomic_name = "测试"
        task._stop_event = None
        task._progress_lines = None
        return task

    def test_run_loop_all_success(self):
        """所有原子任务成功时应返回成功次数。"""
        task = self._make_task()
        task._run_one_atomic = MagicMock(return_value=True)
        task._interruptible_sleep = MagicMock()

        done = task._run_loop(3, 0.01)
        self.assertEqual(done, 3)
        self.assertEqual(task._run_one_atomic.call_count, 3)

    def test_run_loop_all_fail(self):
        """所有原子任务失败时应返回 0。"""
        task = self._make_task()
        task._run_one_atomic = MagicMock(return_value=False)
        task._interruptible_sleep = MagicMock()

        done = task._run_loop(3, 0.01)
        self.assertEqual(done, 0)

    def test_run_loop_mixed(self):
        """部分成功部分失败时应返回成功次数。"""
        task = self._make_task()
        task._run_one_atomic = MagicMock(side_effect=[True, False, True])
        task._interruptible_sleep = MagicMock()

        done = task._run_loop(3, 0.01)
        self.assertEqual(done, 2)

    def test_run_loop_stops_on_stop_task_error(self):
        """StopTaskError 应中断循环。"""
        from GameBot.utils.exception_handler import StopTaskError

        task = self._make_task()
        task._run_one_atomic = MagicMock(side_effect=StopTaskError("stop"))
        task._interruptible_sleep = MagicMock()

        done = task._run_loop(5, 0.01)
        self.assertEqual(done, 0)
        self.assertEqual(task._run_one_atomic.call_count, 1)

    def test_run_loop_no_sleep_after_last(self):
        """最后一次循环后不应 sleep。"""
        task = self._make_task()
        task._run_one_atomic = MagicMock(return_value=True)
        task._interruptible_sleep = MagicMock()

        task._run_loop(2, 0.01)
        # 2 次循环，只在第 1 次后 sleep（i < times 时才 sleep）
        self.assertEqual(task._interruptible_sleep.call_count, 1)


class TestReputationEffectiveTimes(unittest.TestCase):
    """测试 ReputationTask._effective_times 次数反推逻辑。"""

    def setUp(self):
        self._orig = _mock_dm_modules()

    def tearDown(self):
        _restore_dm_modules(self._orig)

    def _make_task(self, cfg):
        from GameBot.runner.tasks.war3.jiubing2.base import ReputationTask

        task = ReputationTask.__new__(ReputationTask)
        task.cfg = cfg
        task.atomic_name = "测试"
        return task

    def test_exact_division(self):
        """整除时应返回精确商。"""
        task = self._make_task({"target_reputation": 150, "reputation_per_run": 5})
        self.assertEqual(task._effective_times(), 30)

    def test_non_exact_division(self):
        """非整除时应向上取整。"""
        task = self._make_task({"target_reputation": 150, "reputation_per_run": 7})
        import math

        self.assertEqual(task._effective_times(), math.ceil(150 / 7))

    def test_default_values(self):
        """未配置时应使用默认值 150/5=30。"""
        task = self._make_task({})
        self.assertEqual(task._effective_times(), 30)

    def test_custom_values(self):
        """自定义值应正确计算。"""
        task = self._make_task({"target_reputation": 200, "reputation_per_run": 10})
        self.assertEqual(task._effective_times(), 20)


class TestReputationReportProgress(unittest.TestCase):
    """测试 ReputationTask._report_progress 进度回调。"""

    def setUp(self):
        self._orig = _mock_dm_modules()

    def tearDown(self):
        _restore_dm_modules(self._orig)

    def _make_task(self, cfg):
        from GameBot.runner.tasks.war3.jiubing2.base import ReputationTask

        task = ReputationTask.__new__(ReputationTask)
        task.cfg = cfg
        task.atomic_name = "测试"
        task._progress_lines = MagicMock()
        return task

    def test_report_progress_no_callback(self):
        """无回调函数时应直接返回。"""
        from GameBot.runner.tasks.war3.jiubing2.base import ReputationTask

        task = ReputationTask.__new__(ReputationTask)
        task.cfg = {}
        task._progress_lines = None
        # 不应抛异常
        task._report_progress(5, 30)

    def test_report_progress_without_state(self):
        """无共享状态时应直接发送单行进度。"""
        task = self._make_task({"reputation_per_run": 5, "target_reputation": 150})
        task._progress_lines(["测试：25/150"])

        task._progress_lines.assert_called_once()
        args = task._progress_lines.call_args[0][0]
        self.assertIn("25/150", args[0])

    def test_report_progress_with_state(self):
        """有共享状态时应更新对应行并发送所有行。"""
        task = self._make_task(
            {
                "reputation_per_run": 5,
                "target_reputation": 150,
                "progress_label": "黑石城",
            }
        )
        task._progress_lines = MagicMock()
        state = {"黑石城": "黑石城：0/150", "森之城": "森之城：50/150"}
        task._progress_state = state

        task._report_progress(10, 30)

        task._progress_lines.assert_called_once()
        lines = task._progress_lines.call_args[0][0]
        # 应有 2 行（更新了黑石城行）
        self.assertEqual(len(lines), 2)
        # 黑石城行应更新为 50/150
        blackstone_line = next(l for l in lines if "黑石城" in l)
        self.assertIn("50/150", blackstone_line)

    def test_report_progress_capped_at_target(self):
        """进度不应超过目标值。"""
        task = self._make_task({"reputation_per_run": 5, "target_reputation": 150})
        task._progress_lines = MagicMock()

        task._report_progress(100, 30)  # 100*5=500 > 150

        lines = task._progress_lines.call_args[0][0]
        self.assertIn("150/150", lines[0])

    def test_report_progress_custom_label(self):
        """自定义 progress_label 应在进度行中使用。"""
        task = self._make_task(
            {
                "reputation_per_run": 10,
                "target_reputation": 150,
                "progress_label": "自定义标签",
            }
        )
        task._progress_lines = MagicMock()

        task._report_progress(5, 15)

        lines = task._progress_lines.call_args[0][0]
        self.assertIn("自定义标签", lines[0])


class TestBuildAtomicCfg(unittest.TestCase):
    """测试 ReputationTask._build_atomic_cfg 配置覆盖逻辑。"""

    def setUp(self):
        self._orig = _mock_dm_modules()

    def tearDown(self):
        _restore_dm_modules(self._orig)

    def _make_task(self, cfg, atomic_cfg):
        from GameBot.runner.tasks.war3.jiubing2.base import ReputationTask

        task = ReputationTask.__new__(ReputationTask)
        task.cfg = cfg
        task.atomic_cfg = atomic_cfg
        return task

    def test_points_override(self):
        """任务级 points 应覆盖原子任务配置中的 points。"""
        original_points = [{"x": 1, "y": 2}]
        new_points = [{"x": 3, "y": 4}]
        task = self._make_task(
            cfg={"points": new_points},
            atomic_cfg={"points": original_points, "other": "val"},
        )

        result = task._build_atomic_cfg()
        self.assertEqual(result["points"], new_points)
        self.assertEqual(result["other"], "val")

    def test_no_points_override(self):
        """无任务级 points 时应保留原子任务原配置。"""
        original_points = [{"x": 1, "y": 2}]
        task = self._make_task(
            cfg={},
            atomic_cfg={"points": original_points, "other": "val"},
        )

        result = task._build_atomic_cfg()
        self.assertEqual(result["points"], original_points)

    def test_deep_copy_not_reference(self):
        """返回的配置应为深拷贝，修改不影响原配置。"""
        original_points = [{"x": 1, "y": 2}]
        new_points = [{"x": 3, "y": 4}]
        task = self._make_task(
            cfg={"points": new_points},
            atomic_cfg={"points": original_points},
        )

        result = task._build_atomic_cfg()
        result["points"][0]["x"] = 999
        # 原始 new_points 不应被修改
        self.assertEqual(new_points[0]["x"], 3)


class TestCombinedEvent(unittest.TestCase):
    """测试 _CombinedEvent 组合事件。"""

    def setUp(self):
        self._orig = _mock_dm_modules()

    def tearDown(self):
        _restore_dm_modules(self._orig)

    def _make_event(self, is_set=False):
        """创建一个 mock Event。"""
        ev = MagicMock()
        ev.is_set.return_value = is_set
        return ev

    def test_no_events(self):
        """无事件时 is_set 应返回 False。"""
        from GameBot.runner.tasks.war3.jiubing2.atomic.base import _CombinedEvent

        ce = _CombinedEvent()
        self.assertFalse(ce.is_set())

    def test_none_events_filtered(self):
        """None 事件应被过滤。"""
        from GameBot.runner.tasks.war3.jiubing2.atomic.base import _CombinedEvent

        ev1 = self._make_event(is_set=True)
        ce = _CombinedEvent(None, ev1, None)
        self.assertTrue(ce.is_set())

    def test_any_set_returns_true(self):
        """任一事件被 set 时应返回 True。"""
        from GameBot.runner.tasks.war3.jiubing2.atomic.base import _CombinedEvent

        ev1 = self._make_event(is_set=False)
        ev2 = self._make_event(is_set=True)
        ce = _CombinedEvent(ev1, ev2)
        self.assertTrue(ce.is_set())

    def test_all_not_set_returns_false(self):
        """所有事件都未 set 时应返回 False。"""
        from GameBot.runner.tasks.war3.jiubing2.atomic.base import _CombinedEvent

        ev1 = self._make_event(is_set=False)
        ev2 = self._make_event(is_set=False)
        ce = _CombinedEvent(ev1, ev2)
        self.assertFalse(ce.is_set())

    def test_wait_no_events_with_timeout(self):
        """无事件且有 timeout 时应 sleep 后返回 False。"""
        from GameBot.runner.tasks.war3.jiubing2.atomic.base import _CombinedEvent

        ce = _CombinedEvent()
        with patch("GameBot.runner.tasks.war3.jiubing2.atomic.base.time") as mock_time:
            result = ce.wait(1.0)
            self.assertFalse(result)
            mock_time.sleep.assert_called_once_with(1.0)

    def test_wait_no_events_no_timeout(self):
        """无事件且无 timeout 时应直接返回 False。"""
        from GameBot.runner.tasks.war3.jiubing2.atomic.base import _CombinedEvent

        ce = _CombinedEvent()
        with patch("GameBot.runner.tasks.war3.jiubing2.atomic.base.time"):
            result = ce.wait()
            self.assertFalse(result)

    def test_wait_event_already_set(self):
        """事件已 set 时 wait 应立即返回 True。"""
        from GameBot.runner.tasks.war3.jiubing2.atomic.base import _CombinedEvent

        ev = self._make_event(is_set=True)
        ce = _CombinedEvent(ev)
        result = ce.wait(5.0)
        self.assertTrue(result)

    def test_wait_timeout_expires(self):
        """超时后应返回 False。"""
        from GameBot.runner.tasks.war3.jiubing2.atomic.base import _CombinedEvent

        ev = self._make_event(is_set=False)
        ce = _CombinedEvent(ev)

        # 模拟时间流逝使超时到期
        with patch("GameBot.runner.tasks.war3.jiubing2.atomic.base.time") as mock_time:
            mock_time.monotonic.side_effect = [0.0, 0.0, 1.1]  # deadline=1.0, 检查时已超
            mock_time.sleep = MagicMock()
            result = ce.wait(1.0)
            self.assertFalse(result)

    def test_wait_event_set_during_wait(self):
        """等待期间事件被 set 时应返回 True。"""
        from GameBot.runner.tasks.war3.jiubing2.atomic.base import _CombinedEvent

        ev = MagicMock()
        # 第一次 is_set=False，第二次 is_set=True
        ev.is_set.side_effect = [False, True]
        ce = _CombinedEvent(ev)

        with patch("GameBot.runner.tasks.war3.jiubing2.atomic.base.time") as mock_time:
            mock_time.monotonic.return_value = 0.0
            mock_time.sleep = MagicMock()
            result = ce.wait(5.0)
            self.assertTrue(result)


class TestAtomicTaskBaseInterruptibleWait(unittest.TestCase):
    """测试 AtomicTaskBase._interruptible_wait。"""

    def setUp(self):
        self._orig = _mock_dm_modules()

    def tearDown(self):
        _restore_dm_modules(self._orig)

    def _make_task(self):
        from GameBot.runner.tasks.war3.jiubing2.atomic.base import AtomicTaskBase

        task = AtomicTaskBase.__new__(AtomicTaskBase)
        return task

    def test_wait_without_stop_event(self):
        """无 stop_event 时应正常 sleep。"""
        task = self._make_task()
        task._stop_event = None
        with patch("GameBot.runner.tasks.war3.jiubing2.atomic.base.time") as mock_time:
            task._interruptible_wait(1.0)
            mock_time.sleep.assert_called_once_with(1.0)

    def test_wait_with_stop_event_not_set(self):
        """stop_event 未设置时应等待并返回。"""
        task = self._make_task()
        stop_event = MagicMock(spec=threading.Event)
        stop_event.wait.return_value = False
        task._stop_event = stop_event

        task._interruptible_wait(2.0)
        stop_event.wait.assert_called_once_with(2.0)

    def test_wait_with_stop_event_set(self):
        """stop_event 已设置时应抛出 StopTaskError。"""
        from GameBot.utils.exception_handler import StopTaskError

        task = self._make_task()
        stop_event = MagicMock(spec=threading.Event)
        stop_event.wait.return_value = True
        task._stop_event = stop_event

        with self.assertRaises(StopTaskError):
            task._interruptible_wait(2.0)


class TestAtomicTaskBaseRun(unittest.TestCase):
    """测试 AtomicTaskBase.run 主流程逻辑。"""

    def setUp(self):
        self._orig = _mock_dm_modules()

    def tearDown(self):
        _restore_dm_modules(self._orig)

    def _make_task(self):
        from GameBot.runner.tasks.war3.jiubing2.atomic.base import AtomicTaskBase

        task = AtomicTaskBase.__new__(AtomicTaskBase)
        task._stop_event = None
        return task

    def test_run_success(self):
        """_accept 和 _clear_route 都成功时应返回 True。"""
        task = self._make_task()
        task._task_label = "测试"
        task._accept = MagicMock(return_value=True)
        task._clear_route = MagicMock(return_value=True)

        result = task.run()
        self.assertTrue(result)

    def test_run_accept_fails(self):
        """_accept 失败时应返回 False，不调用 _clear_route。"""
        task = self._make_task()
        task._task_label = "测试"
        task._accept = MagicMock(return_value=False)
        task._clear_route = MagicMock()

        result = task.run()
        self.assertFalse(result)
        task._clear_route.assert_not_called()

    def test_run_clear_route_fails(self):
        """_clear_route 失败时应返回 False。"""
        task = self._make_task()
        task._task_label = "测试"
        task._accept = MagicMock(return_value=True)
        task._clear_route = MagicMock(return_value=False)

        result = task.run()
        self.assertFalse(result)

    def test_run_stop_task_error_propagates(self):
        """StopTaskError 应向上传播。"""
        from GameBot.utils.exception_handler import StopTaskError

        task = self._make_task()
        task._task_label = "测试"
        task._accept = MagicMock(side_effect=StopTaskError("stop"))
        task._clear_route = MagicMock()

        with self.assertRaises(StopTaskError):
            task.run()
        task._clear_route.assert_not_called()

    def test_run_sets_stop_event(self):
        """run 应将 stop_event 存储到实例。"""
        task = self._make_task()
        task._task_label = "测试"
        task._accept = MagicMock(return_value=True)
        task._clear_route = MagicMock(return_value=True)

        stop_event = MagicMock(spec=threading.Event)
        task.run(stop_event=stop_event)
        self.assertIs(task._stop_event, stop_event)


class TestAtomicTaskBaseNpcProperty(unittest.TestCase):
    """测试 AtomicTaskBase._npc 属性。"""

    def setUp(self):
        self._orig = _mock_dm_modules()

    def tearDown(self):
        _restore_dm_modules(self._orig)

    def test_npc_raises_not_implemented(self):
        """基类 _npc 属性应抛出 NotImplementedError。"""
        from GameBot.runner.tasks.war3.jiubing2.atomic.base import AtomicTaskBase

        task = AtomicTaskBase.__new__(AtomicTaskBase)
        with self.assertRaises(NotImplementedError):
            _ = task._npc


class TestAtomicTaskBaseOnPointArrival(unittest.TestCase):
    """测试 AtomicTaskBase._on_point_arrival 默认实现。"""

    def setUp(self):
        self._orig = _mock_dm_modules()

    def tearDown(self):
        _restore_dm_modules(self._orig)

    def test_default_noop(self):
        """默认 _on_point_arrival 应为空操作（不抛异常）。"""
        from GameBot.runner.tasks.war3.jiubing2.atomic.base import AtomicTaskBase

        task = AtomicTaskBase.__new__(AtomicTaskBase)
        # 不应抛异常
        task._on_point_arrival({"x": 1}, MagicMock())


if __name__ == "__main__":
    unittest.main()
