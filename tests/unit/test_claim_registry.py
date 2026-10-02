"""ClaimRegistry 共享认领注册表测试。

覆盖（任务 1.1–1.4）：
- 1.1: 空文件初始化、损坏文件按空表处理告警、并发写不丢数据
- 1.2: 实例注册/重复 target_player 拒绝/死 PID 不阻塞
- 1.3: kk_owner 写入/命中/进程存活校验/PID 复用失效
- 1.4: windows 记录 kind:hwnd→kk_pid，IsWindow 失效清条目、归属复核不一致清除

所有 Win32 依赖（pid_alive/process_start_time/window_pid/parent_pid/is_window）
均 patch 模块级函数，不触碰真实进程/窗口。
"""

import json
import os
import tempfile
import threading
import unittest
from contextlib import ExitStack, contextmanager
from pathlib import Path
from unittest.mock import patch

import pytest

pytestmark = [pytest.mark.unit]

_MOD = "GameBot.runner.driver.claim_registry"


@contextmanager
def _patches(**kw):
    """patch claim_registry 模块级 win32 函数：callable 值作 side_effect，其余作 return_value。"""
    with ExitStack() as stack:
        for name, val in kw.items():
            if callable(val):
                stack.enter_context(patch(f"{_MOD}.{name}", side_effect=val))
            else:
                stack.enter_context(patch(f"{_MOD}.{name}", return_value=val))
        yield


def _reg_in(td: str):
    from GameBot.runner.driver.claim_registry import ClaimRegistry

    return ClaimRegistry(path=str(Path(td) / "claim_registry.json"))


class TestRegistryFileIO(unittest.TestCase):
    """1.1 注册表文件读写。"""

    def test_empty_file_initialization(self):
        """文件不存在时读为空注册表，首次写入正常落盘（目录自动创建）。"""
        with tempfile.TemporaryDirectory() as td:
            reg = _reg_in(os.path.join(td, "sub"))
            with _patches(pid_alive=False):
                self.assertEqual(reg.alive_instances(), [])
            data = {"instances": {"1": {"player": "A"}}, "kk_owner": {}, "windows": {}}
            reg._save(data)
            self.assertEqual(json.loads(reg.path.read_text(encoding="utf-8")), data)

    def test_corrupted_registry_treated_as_empty(self):
        """损坏 JSON 按空表处理并告警，不抛异常。"""
        with tempfile.TemporaryDirectory() as td:
            reg = _reg_in(td)
            reg.path.write_text("{not valid json!!!", encoding="utf-8")
            # loguru logger 不走 logging，验证返回空表且不抛异常即可
            data = reg._load()
            self.assertEqual(data, {"instances": {}, "kk_owner": {}, "windows": {}})

    def test_concurrent_writes_no_lost_update(self):
        """并发读-改-写在互斥锁内执行，8 线程各写一条实例不丢数据。"""
        with tempfile.TemporaryDirectory() as td:
            reg = _reg_in(td)
            errors = []

            def worker(i):
                try:
                    with reg._locked():
                        data = reg._load()
                        data["instances"][str(1000 + i)] = {"player": f"P{i}"}
                        reg._save(data)
                except Exception as e:  # noqa: BLE001
                    errors.append(e)

            threads = [threading.Thread(target=worker, args=(i,)) for i in range(8)]
            for t in threads:
                t.start()
            for t in threads:
                t.join()

            self.assertEqual(errors, [])
            data = json.loads(reg.path.read_text(encoding="utf-8"))
            self.assertEqual(len(data["instances"]), 8)


class TestInstanceRegistration(unittest.TestCase):
    """1.2 实例注册。"""

    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.reg = _reg_in(self._td.name)

    def tearDown(self):
        self._td.cleanup()

    def test_register_instance_writes_record(self):
        with _patches(pid_alive=True):
            self.reg.register_instance("玩家A", "endless")
            data = json.loads(self.reg.path.read_text(encoding="utf-8"))
        entry = data["instances"][str(os.getpid())]
        self.assertEqual(entry["player"], "玩家A")
        self.assertEqual(entry["task"], "endless")
        self.assertIn("registered_at", entry)

    def test_duplicate_live_player_rejected(self):
        """非空 target_player 已被存活实例注册时抛 ClaimError。"""
        from GameBot.utils import ClaimError

        other_pid = 999999
        with _patches(pid_alive=True):
            self.reg.register_instance("玩家A")
            # 模拟另一进程已注册同玩家
            with self.reg._locked():
                data = self.reg._load()
                data["instances"][str(other_pid)] = {"player": "玩家A", "task": "", "registered_at": 0}
                self.reg._save(data)
            with self.assertRaises(ClaimError):
                self.reg.register_instance("玩家A")

    def test_dead_pid_does_not_block_registration(self):
        """原实例 PID 已死时同玩家可重新注册，且死实例被剪枝。"""
        other_pid = 999999
        with self.reg._locked():
            data = self.reg._load()
            data["instances"][str(other_pid)] = {"player": "玩家A", "task": "", "registered_at": 0}
            self.reg._save(data)
        # other_pid 已死，本进程存活
        with _patches(pid_alive=lambda p: p != other_pid):
            self.reg.register_instance("玩家A")  # 不抛
            instances = self.reg.alive_instances()
        self.assertEqual(len(instances), 1)
        self.assertEqual(instances[0]["player"], "玩家A")

    def test_empty_player_no_conflict(self):
        """空 target_player 实例不冲突。"""
        with _patches(pid_alive=True):
            self.reg.register_instance("")
            with self.reg._locked():
                data = self.reg._load()
                data["instances"]["999999"] = {"player": "", "task": "", "registered_at": 0}
                self.reg._save(data)
            self.reg.register_instance("")  # 不抛


class TestKkOwnerMapping(unittest.TestCase):
    """1.3 kk_pid → player 映射。"""

    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.reg = _reg_in(self._td.name)

    def tearDown(self):
        self._td.cleanup()

    def test_write_and_hit(self):
        """写入后可双向查询：kk_pid_of / player_of_kk_pid。"""
        with _patches(pid_alive=True, process_start_time=12345):
            self.reg.set_kk_owner(4567, "善木木")
            self.assertEqual(self.reg.player_of_kk_pid(4567), "善木木")
            self.assertEqual(self.reg.kk_pid_of("善木木"), 4567)

    def test_dead_pid_invalidates_entry(self):
        """kk_pid 对应进程已死时映射失效并清理。"""
        with _patches(pid_alive=True, process_start_time=111):
            self.reg.set_kk_owner(4567, "善木木")
        with _patches(pid_alive=False):
            self.assertEqual(self.reg.player_of_kk_pid(4567), "")
            self.assertEqual(self.reg.kk_pid_of("善木木"), 0)

    def test_pid_reuse_detected_by_start_time(self):
        """PID 被新进程复用（启动时间不一致）时映射失效。"""
        with _patches(pid_alive=True, process_start_time=111):
            self.reg.set_kk_owner(4567, "善木木")
        # 同 PID 但启动时间不同 → PID 复用
        with _patches(pid_alive=True, process_start_time=222):
            self.assertEqual(self.reg.player_of_kk_pid(4567), "")
            self.assertEqual(self.reg.kk_pid_of("善木木"), 0)


class TestWindowRecords(unittest.TestCase):
    """1.4 已认领窗口记录。"""

    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.reg = _reg_in(self._td.name)

    def tearDown(self):
        self._td.cleanup()

    def test_record_and_read(self):
        """kk_room 记录按窗口 PID 写入并可读回。"""
        with _patches(window_pid=4567, parent_pid=4567, is_window=True):
            kk_pid = self.reg.record_window("kk_room", 100)
            self.assertEqual(kk_pid, 4567)
            self.assertEqual(self.reg.window_kk_pid("kk_room", 100), 4567)

    def test_war3_record_uses_parent_pid(self):
        """war3 记录按窗口进程的直接父 PID 写入。"""
        with _patches(window_pid=9000, parent_pid=4567, is_window=True):
            kk_pid = self.reg.record_window("war3", 200)
            self.assertEqual(kk_pid, 4567)
            self.assertEqual(self.reg.window_kk_pid("war3", 200), 4567)

    def test_destroyed_hwnd_entry_removed(self):
        """hwnd 已销毁（IsWindow=False）时记录失效并清条目。"""
        with _patches(window_pid=4567, parent_pid=4567, is_window=True):
            self.reg.record_window("kk_room", 100)
        with _patches(is_window=False):
            self.assertEqual(self.reg.window_kk_pid("kk_room", 100), 0)
        data = json.loads(self.reg.path.read_text(encoding="utf-8"))
        self.assertNotIn("kk_room:100", data["windows"])

    def test_ownership_mismatch_invalidates(self):
        """归属复核不一致（hwnd 复用到其他进程）时记录失效。"""
        with _patches(window_pid=4567, parent_pid=4567, is_window=True):
            self.reg.record_window("kk_room", 100)
        # hwnd 复用：窗口存活但进程已变
        with _patches(is_window=True, window_pid=8888, parent_pid=8888):
            self.assertEqual(self.reg.window_kk_pid("kk_room", 100), 0)

    def test_release_window(self):
        """release_window 清除指定记录。"""
        with _patches(window_pid=4567, parent_pid=4567, is_window=True):
            self.reg.record_window("war3", 300)
            self.reg.release_window("war3", 300)
        data = json.loads(self.reg.path.read_text(encoding="utf-8"))
        self.assertNotIn("war3:300", data["windows"])
