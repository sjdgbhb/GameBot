"""claim_window 统一认领原语测试。

覆盖（任务 2.2–2.3）：
- 缓存 hwnd 复用（存活+归属复核一致）
- 枚举 → per-hwnd 互斥锁竞争 → resolve_owner/identify 归属判定
- 不匹配释放锁、超时抛 ClaimError
- 单开快速路径：单实例+单候选跳过 identify，仍持锁登记

NamedMutex / _window_usable / 注册表均 mock，不触碰真实窗口。
"""

import threading
import unittest
from unittest.mock import MagicMock, patch

import pytest

pytestmark = [pytest.mark.unit]

_MOD = "GameBot.runner.business.claim"


class _FakeMutex:
    """模拟 per-hwnd 命名互斥锁：busy 集合中的名字 try_acquire 失败。"""

    busy_names = set()
    instances = []

    def __init__(self, name):
        _FakeMutex.instances.append(self)
        self.name = name
        self.acquired = False
        self.released = False

    def try_acquire(self):
        if self.name in _FakeMutex.busy_names:
            return False
        self.acquired = True
        return True

    def acquire(self, timeout_ms=0):
        return self.try_acquire()

    def release(self):
        self.acquired = False
        self.released = True


def _make_registry():
    """mock 注册表：alive_count 可配置，record_window 记日志。"""
    reg = MagicMock()
    reg.alive_count.return_value = 2
    reg.record_window.return_value = 4567
    return reg


class TestClaimWindow(unittest.TestCase):
    """claim_window 认领骨架测试。"""

    def setUp(self):
        _FakeMutex.busy_names = set()
        _FakeMutex.instances = []
        self._patches = [
            patch(f"{_MOD}.NamedMutex", _FakeMutex),
            patch(f"{_MOD}._window_usable", return_value=True),
        ]
        for p in self._patches:
            p.start()

    def tearDown(self):
        for p in self._patches:
            p.stop()

    def _claim(self, **kw):
        from GameBot.runner.business.claim import claim_window

        defaults = dict(
            kind="war3",
            candidates_fn=lambda: [],
            mutex_prefix="Local\\GameBot_War3_",
            resolve_owner=lambda h: None,
            timeout=0.05,
            retry_interval=0.01,
            registry=_make_registry(),
        )
        defaults.update(kw)
        return claim_window(**defaults)

    def test_cached_hwnd_reuse(self):
        """缓存 hwnd 存活且归属复核一致时直接复用，不枚举候选。"""
        candidates_fn = MagicMock(return_value=[])
        hwnd, mutex = self._claim(
            candidates_fn=candidates_fn,
            cached_hwnd=700,
            resolve_owner=lambda h: True,
        )
        self.assertEqual(hwnd, 700)
        self.assertTrue(mutex.acquired)
        candidates_fn.assert_not_called()

    def test_cached_hwnd_stale_falls_back_to_enum(self):
        """缓存 hwnd 复核失败时走枚举路径。"""
        hwnd, _ = self._claim(
            candidates_fn=lambda: [800],
            cached_hwnd=700,
            resolve_owner=lambda h: h == 800,
        )
        self.assertEqual(hwnd, 800)

    def test_two_window_competition(self):
        """两窗口竞争：占用锁的窗口跳过，归属匹配的窗口认领成功。"""
        _FakeMutex.busy_names = {"Local\\GameBot_War3_500"}
        owners = {500: None, 600: True}
        hwnd, mutex = self._claim(
            candidates_fn=lambda: [500, 600],
            resolve_owner=lambda h: owners[h],
        )
        self.assertEqual(hwnd, 600)
        self.assertTrue(mutex.acquired)

    def test_mismatched_owner_releases_mutex(self):
        """归属他人时释放窗口锁，继续尝试下一个。"""
        hwnd, _ = self._claim(
            candidates_fn=lambda: [500, 600],
            resolve_owner=lambda h: h == 600,
        )
        self.assertEqual(hwnd, 600)
        mutex500 = next(m for m in _FakeMutex.instances if m.name.endswith("_500"))
        mutex600 = next(m for m in _FakeMutex.instances if m.name.endswith("_600"))
        self.assertTrue(mutex500.released)
        self.assertFalse(mutex600.released)

    def test_timeout_raises_claim_error(self):
        """超时未认领抛 ClaimError。"""
        from GameBot.utils import ClaimError

        with self.assertRaises(ClaimError):
            self._claim(candidates_fn=lambda: [500], resolve_owner=lambda h: False)

    def test_timeout_all_occupied_raises(self):
        """全部候选被占用且超时抛 ClaimError。"""
        from GameBot.utils import ClaimError

        _FakeMutex.busy_names = {"Local\\GameBot_War3_500"}
        with self.assertRaises(ClaimError):
            self._claim(candidates_fn=lambda: [500], resolve_owner=lambda h: True)

    def test_identify_called_only_when_owner_unknown(self):
        """resolve_owner 返回 None 时才调 identify；返回确定性结果时跳过。"""
        identify = MagicMock(return_value=True)
        # resolve 给出确定性 False：identify 不应调用
        with self.assertRaises(Exception):
            self._claim(
                candidates_fn=lambda: [500],
                resolve_owner=lambda h: False,
                identify=identify,
            )
        identify.assert_not_called()

        # resolve None → identify 调用
        identify2 = MagicMock(return_value=True)
        hwnd, _ = self._claim(
            candidates_fn=lambda: [500],
            resolve_owner=lambda h: None,
            identify=identify2,
        )
        self.assertEqual(hwnd, 500)
        identify2.assert_called_once_with(500)

    def test_fast_path_skips_identify(self):
        """单开快速路径：注册表单实例+单候选时跳过 identify 直接认领。"""
        reg = _make_registry()
        reg.alive_count.return_value = 1
        identify = MagicMock(return_value=False)
        resolve = MagicMock(return_value=None)
        hwnd, mutex = self._claim(
            candidates_fn=lambda: [500],
            resolve_owner=resolve,
            identify=identify,
            registry=reg,
        )
        self.assertEqual(hwnd, 500)
        identify.assert_not_called()
        resolve.assert_not_called()
        reg.record_window.assert_called_once_with("war3", 500)
        self.assertTrue(mutex.acquired)

    def test_fast_path_not_taken_with_multiple_candidates(self):
        """候选数大于 1 时即使单实例也走完整归属判定。"""
        reg = _make_registry()
        reg.alive_count.return_value = 1
        resolve = MagicMock(side_effect=lambda h: h == 600)
        hwnd, _ = self._claim(
            candidates_fn=lambda: [500, 600],
            resolve_owner=resolve,
            registry=reg,
        )
        self.assertEqual(hwnd, 600)
        self.assertEqual(resolve.call_count, 2)

    def test_matched_window_registered(self):
        """认领成功时写注册表窗口记录。"""
        reg = _make_registry()
        hwnd, _ = self._claim(
            candidates_fn=lambda: [500],
            resolve_owner=lambda h: True,
            registry=reg,
        )
        self.assertEqual(hwnd, 500)
        reg.record_window.assert_called_once_with("war3", 500)

    def test_identify_exception_releases_mutex(self):
        """identify 抛异常时窗口锁释放，异常上抛。"""

        def _raise(h):
            raise RuntimeError("boom")

        with self.assertRaises(RuntimeError):
            self._claim(
                candidates_fn=lambda: [500],
                resolve_owner=lambda h: None,
                identify=_raise,
            )

    def test_stop_event_raises(self):
        """stop_event 置位时抛 StopTaskError。"""
        from GameBot.utils import StopTaskError

        stop = threading.Event()
        stop.set()
        with self.assertRaises(StopTaskError):
            self._claim(
                candidates_fn=lambda: [500],
                resolve_owner=lambda h: False,
                stop_event=stop,
            )
