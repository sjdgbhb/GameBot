"""TeamIPC 单元测试。

覆盖文件 IPC 的原子写入、轮询读取、信号读写、进度文件、清理等纯逻辑。
"""

import os
import threading
import time

import pytest

pytestmark = [pytest.mark.unit, pytest.mark.integration]

from GameBot.runner.team.ipc import TeamIPC


@pytest.fixture
def ipc(tmp_path):
    """创建临时 IPC 实例。"""
    base_dir = str(tmp_path / "team_ipc")
    ipc = TeamIPC("test_session", base_dir)
    yield ipc
    ipc.cleanup()


class TestTeamIPC:
    """TeamIPC 核心功能测试。"""

    def test_init_creates_directories(self, tmp_path):
        """初始化应创建 IPC 目录和 progress 子目录。"""
        base_dir = str(tmp_path / "team_ipc")
        ipc = TeamIPC("session1", base_dir)

        assert os.path.isdir(ipc.base_dir)
        assert os.path.isdir(ipc.progress_dir)

    def test_write_and_read_room_info(self, ipc):
        """队长写入房间信息后，队员应能读取到。"""
        ipc.write_room_info(room_id="12345", password="abc", map_name="九种兵器2", round_num=1)

        info = ipc.read_room_info()
        assert info is not None
        assert info["room_id"] == "12345"
        assert info["password"] == "abc"
        assert info["map_name"] == "九种兵器2"
        assert info["round"] == 1
        assert "timestamp" in info

    def test_poll_read_timeout(self, ipc):
        """文件不存在时轮询应超时返回 None。"""
        start = time.time()
        info = ipc.read_room_info(timeout=0.2, poll_interval=0.05)
        elapsed = time.time() - start

        assert info is None
        assert elapsed >= 0.2

    def test_poll_read_eventual_success(self, ipc):
        """延迟写入后，轮询应最终读取到数据。"""
        def delayed_write():
            time.sleep(0.1)
            ipc.write_room_info(room_id="999", password="", map_name="", round_num=2)

        threading.Thread(target=delayed_write).start()

        info = ipc.read_room_info(timeout=1.0, poll_interval=0.05)
        assert info is not None
        assert info["room_id"] == "999"
        assert info["round"] == 2

    def test_exit_and_stop_signals(self, ipc):
        """退出信号和停止信号读写应正常。"""
        ipc.write_exit_signal(round_num=3, reason="test")
        signal = ipc.read_exit_signal()
        assert signal is not None
        assert signal["round"] == 3
        assert signal["reason"] == "test"

        assert ipc.read_stop_signal() is False
        ipc.write_stop_signal(reason="manual")
        assert ipc.read_stop_signal() is True

    def test_hall_owner_cache_read_write(self, ipc):
        """大厅归属缓存的读写。"""
        # 未缓存返回 None
        assert ipc.read_hall_owner(100) is None

        # 写入归属缓存
        ipc.write_hall_owner(100, 200, "善木木#123")
        assert ipc.read_hall_owner(100) == "善木木#123"
        # PID 校验：不匹配返回 None（防止 hwnd 复用误判）
        assert ipc.read_hall_owner(100, 201) is None
        assert ipc.read_hall_owner(100, 200) == "善木木#123"

    def test_cleanup_stale_removes_other_sessions(self, tmp_path):
        """cleanup_stale 应删除其他会话的残留 IPC 目录，保留当前会话。"""
        base_dir = str(tmp_path / "team_ipc")
        # 模拟旧会话残留
        old = TeamIPC("old_session", base_dir)
        old.write_hall_owner(500, 123, "旧玩家")
        # 当前会话
        current = TeamIPC("current_session", base_dir)

        current.cleanup_stale()

        # 旧目录被删除
        assert not os.path.isdir(os.path.join(base_dir, "team_ipc_old_session"))
        # 当前目录保留
        assert os.path.isdir(current.base_dir)

    def test_progress_files(self, ipc):
        """进度写入和批量读取应正确。"""
        ipc.write_progress(
            role="leader",
            member_name="player1",
            task_name="endless",
            task_progress="3/10",
            state="in_game",
            round_num=2,
        )
        ipc.write_progress(
            role="follower_0",
            member_name="player2",
            task_name="endless",
            task_progress="3/10",
            state="in_game",
            round_num=2,
        )

        all_progress = ipc.read_all_progress()
        assert len(all_progress) == 2
        assert all_progress["leader"]["member_name"] == "player1"
        assert all_progress["follower_0"]["member_name"] == "player2"

    def test_exit_signal_min_round(self, ipc):
        """read_exit_signal 应只接受 round >= min_round 的信号。"""
        ipc.write_exit_signal(round_num=2, reason="test")

        # round=2 >= min_round=3 不应被接受
        assert ipc.read_exit_signal(timeout=0.1, min_round=3) is None
        # round=2 >= min_round=2 应被接受
        signal = ipc.read_exit_signal(timeout=0.1, min_round=2)
        assert signal is not None
        assert signal["round"] == 2

    def test_atomic_write_no_partial_read(self, ipc):
        """原子写入不应产生半写文件。"""
        # 覆盖 _atomic_write 内部，验证没有 .tmp 残留
        ipc.write_room_info(room_id="x", password="", map_name="", round_num=1)

        tmp_files = [f for f in os.listdir(ipc.base_dir) if f.endswith(".tmp")]
        assert len(tmp_files) == 0

    def test_cleanup(self, ipc):
        """cleanup 应删除整个 IPC 目录。"""
        ipc.write_room_info(room_id="1", password="", map_name="", round_num=1)
        assert os.path.isdir(ipc.base_dir)

        ipc.cleanup()
        assert not os.path.exists(ipc.base_dir)
