"""文件 IPC 模块 — 原子写入、轮询读取，用于队长/队员间通信。

IPC 文件结构：
    logs/team_ipc/team_ipc_<session_id>/
    ├── room_info.json          # 队长广播：{ room_id, password, map_name, round, timestamp }
    ├── game_state.json         # 游戏状态广播：{ phase, sync_source, round, timestamp }
    ├── exit_signal.json        # 退出信号：{ round, reason, timestamp }
    ├── stop_signal.json        # 全局停止信号
    ├── hall_owners/            # 本次会话的大厅 HWND/PID/用户名识别缓存
    └── progress/               # 各成员任务进度
        ├── leader.json
        ├── follower_0.json
        └── follower_1.json

写入：原子写入（先写 .tmp 再 os.replace），避免读取到半写内容。
轮询：队员每 0.5s 轮询 room_info.json，检测 timestamp 变化判断新局开始。
无外部依赖：仅用 os、json、time。
"""

from __future__ import annotations

import json
import os
import time
from typing import Any, Dict, Optional

from GameBot.utils import logger


class TeamIPC:
    """文件 IPC 读写封装。

    所有文件操作基于 session_id 对应的 IPC 目录。
    """

    def __init__(self, session_id: str, ipc_dir: str = "logs/team_ipc") -> None:
        """
        :param session_id: 会话 ID（由入口进程生成）
        :param ipc_dir: IPC 文件根目录（相对项目根或绝对路径）
        """
        self.session_id = session_id
        self.ipc_root = ipc_dir
        self.base_dir = os.path.join(ipc_dir, f"team_ipc_{session_id}")
        self.progress_dir = os.path.join(self.base_dir, "progress")
        self.hall_owners_dir = os.path.join(self.base_dir, "hall_owners")
        os.makedirs(self.progress_dir, exist_ok=True)
        os.makedirs(self.hall_owners_dir, exist_ok=True)

    def cleanup_stale(self) -> None:
        """清理其他会话残留的 IPC 目录，防止污染当前任务。

        在 orchestrator 启动前调用，删除 ipc_root 下所有非当前 session 的 team_ipc_* 目录。
        """
        if not os.path.isdir(self.ipc_root):
            return
        current = f"team_ipc_{self.session_id}"
        import shutil

        for name in os.listdir(self.ipc_root):
            if name.startswith("team_ipc_") and name != current:
                stale_dir = os.path.join(self.ipc_root, name)
                shutil.rmtree(stale_dir, ignore_errors=True)
                logger.info(f"清理残留 IPC 目录: {name}")

    # ---------- 原子写入 ----------

    def _atomic_write(self, filepath: str, data: dict) -> None:
        """原子写入 JSON 文件：先写 .tmp 再 os.replace。"""
        tmp_path = filepath + ".tmp"
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False)
        os.replace(tmp_path, filepath)

    # ---------- 广播文件（room_info / game_state / exit_signal / stop_signal） ----------

    def write_room_info(
        self,
        room_id: str,
        password: str,
        map_name: str,
        round_num: int = 1,
    ) -> None:
        """队长广播房间信息。"""
        filepath = os.path.join(self.base_dir, "room_info.json")
        data = {
            "room_id": room_id,
            "password": password,
            "map_name": map_name,
            "round": round_num,
            "timestamp": time.time(),
        }
        self._atomic_write(filepath, data)
        logger.debug(f"广播 room_info: room_id={room_id}, round={round_num}")

    def read_room_info(self, timeout: float = 0, poll_interval: float = 0.5) -> Optional[dict]:
        """队员轮询读取房间信息。

        :param timeout: 超时秒数，0 表示不等待（读一次就返回）
        :param poll_interval: 轮询间隔秒数
        :return: 房间信息 dict，无文件或超时返回 None
        """
        filepath = os.path.join(self.base_dir, "room_info.json")
        return self._poll_read(filepath, timeout, poll_interval)

    def write_game_state(
        self,
        phase: str,
        sync_source: str = "",
        round_num: int = 1,
        **extra: Any,
    ) -> None:
        """广播游戏状态。

        :param phase: 游戏阶段（如 "in_game", "exiting"）
        :param sync_source: 同步源玩家 ID
        :param round_num: 当前局数
        :param extra: 额外字段
        """
        filepath = os.path.join(self.base_dir, "game_state.json")
        data = {
            "phase": phase,
            "sync_source": sync_source,
            "round": round_num,
            "timestamp": time.time(),
            **extra,
        }
        self._atomic_write(filepath, data)
        logger.debug(f"广播 game_state: phase={phase}, round={round_num}")

    def read_game_state(self, timeout: float = 0, poll_interval: float = 0.5) -> Optional[dict]:
        """读取游戏状态。"""
        filepath = os.path.join(self.base_dir, "game_state.json")
        return self._poll_read(filepath, timeout, poll_interval)

    def write_exit_signal(self, round_num: int, reason: str = "task_complete") -> None:
        """同步源广播退出信号。"""
        filepath = os.path.join(self.base_dir, "exit_signal.json")
        data = {
            "round": round_num,
            "reason": reason,
            "timestamp": time.time(),
        }
        self._atomic_write(filepath, data)
        logger.info(f"广播 exit_signal: round={round_num}, reason={reason}")

    def read_exit_signal(self, timeout: float = 0, poll_interval: float = 0.5, min_round: int = 0) -> Optional[dict]:
        """读取退出信号，按 round 纪元过滤。

        消费者只接受 round >= min_round 的信号；旧 round 的信号自然失效，
        由新一局 room_info(round+1) 取代，不删除共享文件。

        :param min_round: 最小可接受局号
        """
        filepath = os.path.join(self.base_dir, "exit_signal.json")
        start = time.time()
        while True:
            if os.path.exists(filepath):
                try:
                    with open(filepath, "r", encoding="utf-8") as f:
                        data = json.load(f)
                    if data.get("round", 0) >= min_round:
                        return data
                except (json.JSONDecodeError, IOError) as e:
                    logger.warning(f"读取 exit_signal 失败: {e}")
                    return None
            if timeout <= 0 or time.time() - start >= timeout:
                return None
            time.sleep(poll_interval)

    def write_stop_signal(self, reason: str = "manual_stop") -> None:
        """入口进程广播全局停止信号。"""
        filepath = os.path.join(self.base_dir, "stop_signal.json")
        data = {
            "reason": reason,
            "timestamp": time.time(),
        }
        self._atomic_write(filepath, data)
        logger.info(f"广播 stop_signal: reason={reason}")

    def read_stop_signal(self) -> bool:
        """检查是否存在停止信号。"""
        filepath = os.path.join(self.base_dir, "stop_signal.json")
        return os.path.exists(filepath)

    # ---------- 大厅归属缓存 ----------

    def write_hall_owner(self, hwnd: int, pid: int, owner: str) -> None:
        """写入大厅窗口归属，供其他进程跳过重复 OCR。"""
        filepath = os.path.join(self.hall_owners_dir, f"{int(hwnd)}.json")
        self._atomic_write(
            filepath,
            {
                "hwnd": int(hwnd),
                "pid": int(pid),
                "owner": owner,
                "timestamp": time.time(),
            },
        )

    def read_hall_owner(self, hwnd: int, pid: int = 0) -> Optional[str]:
        """读取大厅窗口归属；PID 不匹配时忽略，防止 HWND 复用误判。"""
        filepath = os.path.join(self.hall_owners_dir, f"{int(hwnd)}.json")
        data = self._poll_read(filepath)
        if not data:
            return None
        if pid and data.get("pid") != int(pid):
            return None
        owner = data.get("owner", "")
        return owner if owner else None

    # ---------- 进度文件 ----------

    def write_progress(
        self,
        role: str,
        member_name: str,
        task_name: str,
        task_progress: str,
        state: str = "",
        round_num: int = 1,
        **extra: Any,
    ) -> None:
        """各子进程上报自身进度。

        :param role: 角色标识（如 "leader", "follower_0"）
        :param member_name: 成员名称（玩家 ID）
        :param task_name: 任务名称（如 "endless_single", "fishing"）
        :param task_progress: 任务进度文本（如 "round=3/10", "caught=5/20"）
        :param state: 脚本流程状态（如 "waiting_room", "in_game"），仅用于调试
        :param round_num: 当前局数
        :param extra: 额外字段
        """
        filepath = os.path.join(self.progress_dir, f"{role}.json")
        data = {
            "member_name": member_name,
            "task_name": task_name,
            "task_progress": task_progress,
            "state": state,
            "round": round_num,
            "timestamp": time.time(),
            **extra,
        }
        self._atomic_write(filepath, data)

    def read_all_progress(self) -> Dict[str, dict]:
        """读取所有成员的进度文件。

        :return: { role: progress_dict } 字典
        """
        result = {}
        if not os.path.isdir(self.progress_dir):
            return result
        for filename in os.listdir(self.progress_dir):
            if not filename.endswith(".json"):
                continue
            role = filename[:-5]  # 去掉 .json
            filepath = os.path.join(self.progress_dir, filename)
            try:
                with open(filepath, "r", encoding="utf-8") as f:
                    result[role] = json.load(f)
            except (json.JSONDecodeError, IOError) as e:
                logger.warning(f"读取进度文件 {filename} 失败: {e}")
        return result

    # ---------- 清理 ----------

    def cleanup(self) -> None:
        """清理 IPC 目录（任务结束后调用）。"""
        import shutil

        if os.path.isdir(self.base_dir):
            shutil.rmtree(self.base_dir, ignore_errors=True)
            logger.info(f"已清理 IPC 目录: {self.base_dir}")

    # ---------- 内部辅助 ----------

    def _poll_read(self, filepath: str, timeout: float = 0, poll_interval: float = 0.5) -> Optional[dict]:
        """轮询读取 JSON 文件。

        :param filepath: 文件路径
        :param timeout: 超时秒数，0 表示不等待
        :param poll_interval: 轮询间隔
        :return: 文件内容 dict，无文件或超时返回 None
        """
        start = time.time()
        while True:
            if os.path.exists(filepath):
                try:
                    with open(filepath, "r", encoding="utf-8") as f:
                        return json.load(f)
                except (json.JSONDecodeError, IOError) as e:
                    logger.warning(f"读取 IPC 文件 {filepath} 失败: {e}")
                    return None
            if timeout <= 0 or time.time() - start >= timeout:
                return None
            time.sleep(poll_interval)
