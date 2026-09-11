"""队员流程 — 轮询房间信息、加入房间、准备、等待游戏开始。

队员负责：
1. 轮询 IPC room_info.json，获取队长广播的房间号和密码
2. 在 KK 主界面按房间号搜索并加入房间
3. 点击准备按钮
4. 等待队长开始游戏（检测游戏窗口出现即视为已开始）
"""

from __future__ import annotations

import time
from typing import Optional

from GameBot.runner.team.ipc import TeamIPC
from GameBot.utils import logger

from .base import TeamMemberBase


class TeamFollower(TeamMemberBase):
    """队员流程控制。"""

    def __init__(
        self,
        cfg: dict,
        member_cfg: dict,
        ipc: TeamIPC,
        sync_source: str,
        follower_index: int,
        stop_event=None,
    ):
        """
        :param follower_index: 队员序号（0-based，用于 role 标识）
        """
        super().__init__(cfg, member_cfg, ipc, sync_source, stop_event)
        self.follower_index = follower_index
        # 上次读取到的房间信息时间戳，用于判断新局
        self._last_room_timestamp = 0.0

    def get_role(self) -> str:
        return f"follower_{self.follower_index}"

    def kk_phase(self, round_num: int) -> bool:
        """队员 KK 阶段：检查是否已在房间/游戏 → 轮询房间信息 → 加入房间 → 准备 → 等待游戏开始。

        :return: True=成功进入游戏, False=失败
        """
        # 0. KK 阶段不应存在 War3 窗口，残留则关闭
        if self._current_war3_hwnd:
            logger.warning(f"KK 阶段检测到残留 War3 窗口，关闭后继续 KK 流程 (round={round_num})")
            self._close_stale_war3_window()

        if not self._claim_hall_window():
            # 认领大厅失败，可能玩家还在房间内（上一局结束后未退出房间）
            room_hwnd = self.kk.dismiss_room_popups(self.dm, owner_pid=0)
            if room_hwnd:
                logger.warning(f"玩家 {self.target_player} 在房间内，无法认领大厅。请手动退出房间后重试")
            logger.error(f"无法认领玩家 {self.target_player} 的 KK 窗口，跳过本局")
            return False

        # 1. 检查是否已在房间内（重启后可能残留房间窗口）
        room_hwnd = self.kk.dismiss_room_popups(self.dm, owner_pid=self.owner_pid)
        if room_hwnd:
            room_info = self._wait_for_room_info(round_num)
            if not room_info:
                logger.error(f"等待房间信息超时 (round={round_num})")
                return False
            round_num = self._current_round
            logger.info(f"检测到已在房间中，直接准备 (round={round_num})")
            if not self._click_ready(room_hwnd):
                logger.error("准备失败，跳过本局")
                return False
            self._report_progress(state="ready", round_num=round_num)
            logger.info("已准备，等待队长开始游戏")
            return True

        # 2. 认领属于本账号的 KK 大厅窗口
        self._claim_hall_window()

        # 3. 轮询等待队长广播房间信息
        room_info = self._wait_for_room_info(round_num)
        if not room_info:
            logger.error(f"等待房间信息超时 (round={round_num})")
            self.dm.save_screenshot(label="follower_room_info_timeout", force=True)
            return False

        round_num = self._current_round
        room_id = room_info.get("room_id", "")
        password = room_info.get("password", "")
        map_name = room_info.get("map_name", "")

        if not room_id:
            logger.error("房间信息中缺少房间号")
            return False

        # 4. 尝试找到已有房间（后续局可能已在房间中）
        room_hwnd = self.kk.dismiss_room_popups(self.dm, owner_pid=self.owner_pid)
        if room_hwnd:
            logger.info(f"已在房间中，无需重新加入 (round={round_num})")
        else:
            # 5. 不在房间中，按房间号加入（带重试）
            ipc_cfg = self.task_cfg.get("team", {}).get("team_task", {}).get("ipc", {})
            retry_max = ipc_cfg.get("join_retry_max", 3)
            retry_interval = ipc_cfg.get("join_retry_interval", 5)
            for attempt in range(1, retry_max + 1):
                if self.stop_event.is_set():
                    return False
                logger.info(f"按房间号 {room_id} 加入房间 (round={round_num}, 尝试 {attempt}/{retry_max})")
                self.kk.dismiss_hall_popups(self.dm, owner_pid=self.owner_pid)
                room_hwnd = self.kk.join_room_by_id(
                    self.dm,
                    room_id=room_id,
                    password=password,
                    map_name=map_name,
                    hall_hwnd=self.hall_hwnd,
                    owner_pid=self.owner_pid,
                )
                if room_hwnd:
                    break
                logger.warning(f"加入房间 {room_id} 失败 (尝试 {attempt}/{retry_max})")
                if attempt < retry_max:
                    time.sleep(retry_interval)
            if not room_hwnd:
                logger.error(f"加入房间 {room_id} 失败，已重试 {retry_max} 次")
                self.dm.save_screenshot(label="follower_join_room_failed", force=True)
                return False

        # 6. 点击准备按钮（OCR 验证：点击前检测"准备"，点击后检测"取消准备"）
        if not self._click_ready(room_hwnd):
            logger.error("准备失败，跳过本局")
            self.dm.save_screenshot(label="follower_click_ready_failed", force=True)
            return False

        # 7. 上报 ready 状态，供队长通过 IPC 检测
        self._report_progress(state="ready", round_num=round_num)

        # 8. 等待游戏开始（游戏窗口出现即视为已开始）
        logger.info("已准备，等待队长开始游戏")
        return True

    def _wait_for_room_info(self, round_num: int, timeout: Optional[int] = None) -> Optional[dict]:
        """轮询等待队长广播的房间信息。

        通过 timestamp 变化判断是新局信息还是旧信息。
        room_info.round 作为全局权威局号，用于修正自身 _current_round。
        restart 后的首条 room_info 无条件接受，避免 leader 局号回退死锁。

        :param round_num: 当前局数
        :param timeout: 超时秒数，未提供时从 team_cfg.ipc.room_info_wait_timeout 读取
        :return: 房间信息 dict，超时返回 None
        """
        if timeout is None:
            ipc_cfg = self.task_cfg.get("team", {}).get("team_task", {}).get("ipc", {})
            timeout = ipc_cfg.get("room_info_wait_timeout", 120)

        start = time.time()
        while time.time() - start < timeout:
            if self.stop_event.is_set():
                return None

            room_info = self.ipc.read_room_info()
            if room_info:
                timestamp = room_info.get("timestamp", 0)
                info_round = room_info.get("round", 0)
                is_new = timestamp > self._last_room_timestamp
                accept = False
                if is_new and self._accept_any_room_info:
                    # restart 后的新纪元：无条件接受首条 room_info
                    self._accept_any_room_info = False
                    accept = True
                    logger.info(f"restart 后无条件接受 room_info (round={info_round})")
                elif is_new and info_round >= round_num:
                    accept = True

                if accept:
                    self._last_room_timestamp = timestamp
                    self._current_round = info_round
                    logger.info(
                        f"收到房间信息: 房间号={room_info.get('room_id')}, "
                        f"局数={info_round}"
                    )
                    return room_info

            time.sleep(0.5)

        return None

    def _click_ready(self, room_hwnd: int, max_retries: int = 3) -> bool:
        """在房间中点击准备按钮。

        后台 gdi 模式下截图可能不反映点击后的 UI 变化（渲染缓存问题），
        类似密码框输入后不显示但实际已生效。因此：
        - 点击前 OCR 判断是否已准备（避免重复点击取消准备）
        - 点击后不依赖 OCR 后验，等待一段时间让状态生效即可

        :param room_hwnd: 房间窗口句柄
        :param max_retries: 最大重试次数（仅用于点击前 OCR 读不到按钮文本的情况）
        :return: True=已点击准备, False=未找到准备按钮
        """
        room_cfg = self.kk_cfg.get("room", {})
        room_size = tuple(room_cfg.get("window_size", [1224, 904]))
        try:
            self.dm.set_client_size(room_hwnd, *room_size)
        except Exception as e:
            logger.warning(f"设置房间尺寸失败: {e}")
        ready_keyword = room_cfg.get("ready_keyword", "取消准备")
        not_ready_keyword = room_cfg.get("not_ready_keyword", "准备")
        ocr_area = room_cfg.get("start_button_ocr_area_coords", [0, 0, 0, 0])

        # 从 OCR 区域中心计算按钮坐标
        if ocr_area != [0, 0, 0, 0]:
            base_ready_coords = [
                (ocr_area[0] + ocr_area[2]) // 2,
                (ocr_area[1] + ocr_area[3]) // 2,
            ]
        else:
            base_ready_coords = room_cfg.get("start_button_coords", [867, 613])
        ready_coords = base_ready_coords

        def _read_button_text() -> str:
            """OCR 读取按钮区域的首行非空文本（需在 bind 上下文内调用）。"""
            if ocr_area == [0, 0, 0, 0]:
                return ""
            lines = self.kk.ocr_kk_lines(
                self.dm,
                room_hwnd,
                {"area_coords": ocr_area},
            )
            for line in lines:
                text = line.get("text", "").strip()
                if text:
                    return text
            return ""

        bind_cfg = self.kk_cfg.get("bind", {})
        for attempt in range(1, max_retries + 1):
            if self.stop_event.is_set():
                return False

            # 先直接 OCR，成功就不刷新（避免不必要的 force_refresh 导致黑边）
            # 仅在 OCR 为空时才 force_refresh 后重试
            if attempt > 1:
                self.dm.force_refresh_layered(room_hwnd)
            with self.dm.bind_window(room_hwnd, bind_cfg=bind_cfg):
                button_text = _read_button_text()

            # 已准备：跳过点击
            if ready_keyword in button_text:
                logger.info("检测到已处于准备状态，不重复点击")
                return True

            # OCR 为空且未到最大重试次数：刷新后重试
            if not button_text and attempt < max_retries:
                logger.debug(f"按钮 OCR 为空，刷新后重试 (尝试 {attempt}/{max_retries})")
                continue

            # 未准备或 OCR 有文本但不匹配：点击准备
            if not_ready_keyword in button_text:
                logger.info(f"检测到未准备状态，点击准备按钮 (尝试 {attempt}/{max_retries})")
            else:
                logger.info(f"按钮文本为'{button_text}'，默认点击准备按钮 (尝试 {attempt}/{max_retries})")

            with self.dm.bind_window(room_hwnd, bind_cfg=bind_cfg):
                self.dm.move_to(*ready_coords)
                time.sleep(0.3)
                # 后台模式下用 LeftDown + LeftUp 模拟真实点击，兼容性优于 LeftClick
                self.dm.left_down()
                time.sleep(0.05)
                self.dm.left_up()
            logger.info("已点击准备按钮")
            # 等待一段时间让状态生效
            time.sleep(1)
            return True

        logger.warning(f"准备按钮重试 {max_retries} 次仍未找到准备按钮")
        return False


def main():
    """队员子进程入口 — 由 TeamOrchestrator 通过 subprocess 启动。"""
    from GameBot.runner.team.base import load_member_config
    from GameBot.utils import setup_log_file

    setup_log_file("队员")

    ctx = load_member_config()
    if ctx is None:
        return

    # 计算 follower_index = 当前 member 之前非 leader 的数量
    members = ctx["team_cfg"].get("members", [])
    member_index = ctx["member_index"]
    follower_index = sum(1 for i in range(member_index) if members[i].get("role") != "leader")

    follower = TeamFollower(
        cfg=ctx["cfg"],
        member_cfg=ctx["member_cfg"],
        ipc=ctx["ipc"],
        sync_source=ctx["sync_source"],
        follower_index=follower_index,
        stop_event=ctx["stop_event"],
    )
    logger.info(f"队员子进程启动: target_player={follower.target_player}, follower_index={follower_index}")
    follower.run()


if __name__ == "__main__":
    main()
