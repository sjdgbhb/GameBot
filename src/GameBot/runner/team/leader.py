"""队长流程 — 创建房间、广播房间信息、等待队员准备、开始游戏。

队长负责：
1. 在 KK 主界面搜索地图并创建密码房间
2. OCR 识别房间号
3. 通过 IPC 广播房间信息（room_info.json）
4. OCR 检测所有队员准备状态
5. 点击开始游戏
"""

from __future__ import annotations

import os
import time

from GameBot.runner.team.ipc import TeamIPC
from GameBot.utils import logger

from .base import TeamMemberBase

# 测试开关：设为 "1" 时跳过"开始游戏"点击，仅测试 KK 端流程
_SKIP_START_GAME = os.environ.get("KK_TEST_NO_START_GAME", "") == "1"


class TeamLeader(TeamMemberBase):
    """队长流程控制。"""

    def __init__(
        self,
        cfg: dict,
        member_cfg: dict,
        ipc: TeamIPC,
        sync_source: str,
        team_cfg: dict,
        stop_event=None,
    ):
        """
        :param team_cfg: team_task 配置段（含 members 列表、sync 设置等）
        """
        super().__init__(cfg, member_cfg, ipc, sync_source, stop_event)
        self.team_cfg = team_cfg
        self.members = team_cfg.get("members", [])
        # 队员数量（不含队长）
        self.follower_count = sum(1 for m in self.members if m.get("role") != "leader")
        # 房间信息
        self.room_id = ""
        self.password = ""
        self.map_name = cfg.get("war3", {}).get("jiubing2", {}).get("game", {}).get("map_name", "")

    def get_role(self) -> str:
        return "leader"

    def kk_phase(self, round_num: int) -> bool:
        """队长 KK 阶段：检查是否已在房间/游戏 → 创建房间 → 广播房间号 → 等待队员准备 → 开始游戏。

        :return: True=成功开始游戏, False=失败
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

        # 第一局创建新房间，后续局尝试复用已有房间
        if round_num == 1:
            return self._create_and_broadcast_room(round_num)
        else:
            # 后续局：尝试找到已有房间直接开始
            if self._try_reuse_room(round_num):
                return True
            # 房间不存在，重新创建
            logger.info("房间已不存在，重新创建房间")
            return self._create_and_broadcast_room(round_num)

    def _create_and_broadcast_room(self, round_num: int) -> bool:
        """创建房间、广播房间信息、等待队员准备、开始游戏。"""
        # 0. 检查是否已在房间内（重启后可能残留房间窗口）
        room_hwnd = self.kk.dismiss_room_popups(self.dm, owner_pid=self.owner_pid)
        if room_hwnd:
            logger.info(f"检测到已在房间中，直接复用 (round={round_num})")
            # OCR 识别房间号
            self.room_id = self._ocr_room_id(room_hwnd)
            if self.room_id:
                # 广播房间信息
                create_cfg = self.kk_cfg.get("create_room", {})
                self.password = create_cfg.get("password", "")
                self.ipc.write_room_info(
                    room_id=self.room_id,
                    password=self.password,
                    map_name=self.map_name,
                    round_num=round_num,
                )
                logger.info(f"已广播房间信息: 房间号={self.room_id}, 局数={round_num}")
                # 等待队员准备并开始游戏
                if self.follower_count > 0:
                    ready_timeout = self.team_cfg.get("ipc", {}).get("ready_timeout", 120)
                    if not self._wait_followers_ready(room_hwnd, round_num, timeout=ready_timeout):
                        logger.error("等待队员准备超时，终止程序")
                        self.ipc.write_stop_signal(reason="followers_ready_timeout")
                        self.stop_event.set()
                        return False
                if _SKIP_START_GAME:
                    logger.info("【测试模式】跳过开始游戏，KK 端流程完成")
                    self.stop_event.set()
                    return True
                if not self.kk.start_game(self.dm, room_hwnd=room_hwnd):
                    logger.error("开始游戏失败：按钮未变为'开始游戏'")
                    return False
                return True
            else:
                logger.warning("已在房间中但无法识别房间号，请手动退出房间后重新运行任务")
                self.dm.save_screenshot(label="room_id_unreadable", force=True)
                return False

        # 1. 认领属于本账号的 KK 大厅窗口
        self._claim_hall_window()

        # 2. 清理主界面弹窗（带 PID 过滤，排除主大厅窗口）
        self.kk.dismiss_hall_popups(self.dm, exclude_hwnds={self.hall_hwnd}, owner_pid=self.owner_pid)

        # 3. 创建房间
        room_hwnd = self.kk.create_room(
            self.dm,
            map_name=self.map_name,
            hall_hwnd=self.hall_hwnd,
            owner_pid=self.owner_pid,
        )
        if not room_hwnd:
            logger.error("队长创建房间失败")
            self.dm.save_screenshot(label="leader_create_room_failed", force=True)
            return False

        # 4. OCR 识别房间号
        self.room_id = self._ocr_room_id(room_hwnd)
        if not self.room_id:
            logger.error("无法识别房间号，队员无法加入")
            self.dm.save_screenshot(label="leader_ocr_room_id_failed", force=True)
            return False

        # 5. 广播房间信息
        create_cfg = self.kk_cfg.get("create_room", {})
        self.password = create_cfg.get("password", "")
        self.ipc.write_room_info(
            room_id=self.room_id,
            password=self.password,
            map_name=self.map_name,
            round_num=round_num,
        )
        logger.info(f"已广播房间信息: 房间号={self.room_id}, 局数={round_num}")

        # 6. 等待队员准备（IPC ready 信号 + OCR 开始按钮双重检测）
        if self.follower_count > 0:
            ready_timeout = self.team_cfg.get("ipc", {}).get("ready_timeout", 120)
            if not self._wait_followers_ready(room_hwnd, round_num, timeout=ready_timeout):
                logger.error("等待队员准备超时，终止程序")
                self.dm.save_screenshot(label="leader_followers_ready_timeout", force=True)
                self.ipc.write_stop_signal(reason="followers_ready_timeout")
                self.stop_event.set()
                return False

        # 7. 开始游戏（OCR 验证按钮文本）
        if _SKIP_START_GAME:
            logger.info("【测试模式】跳过开始游戏，KK 端流程完成")
            self.stop_event.set()
            return True
        if not self.kk.start_game(self.dm, room_hwnd=room_hwnd):
            logger.error("开始游戏失败：按钮未变为'开始游戏'")
            self.dm.save_screenshot(label="leader_start_game_failed", force=True)
            return False
        return True

    def _try_reuse_room(self, round_num: int) -> bool:
        """尝试找到已有房间并直接开始游戏（后续局复用）。"""
        room_hwnd = self.kk.dismiss_room_popups(self.dm, owner_pid=self.owner_pid)
        if not room_hwnd:
            return False

        # 广播房间信息（使用已知的房间号）
        self.ipc.write_room_info(
            room_id=self.room_id,
            password=self.password,
            map_name=self.map_name,
            round_num=round_num,
        )
        logger.info(f"复用房间 {self.room_id}，已广播新局信息 (round={round_num})")

        # 等待队员准备（IPC ready 信号 + OCR 开始按钮双重检测）
        if self.follower_count > 0:
            ready_timeout = self.team_cfg.get("ipc", {}).get("ready_timeout", 120)
            if not self._wait_followers_ready(room_hwnd, round_num, timeout=ready_timeout):
                logger.error("等待队员准备超时，终止程序")
                self.dm.save_screenshot(label="leader_reuse_ready_timeout", force=True)
                self.ipc.write_stop_signal(reason="followers_ready_timeout")
                self.stop_event.set()
                return False

        # 开始游戏（OCR 验证按钮文本）
        if _SKIP_START_GAME:
            logger.info("【测试模式】跳过开始游戏，KK 端流程完成")
            self.stop_event.set()
            return True
        if not self.kk.start_game(self.dm, room_hwnd=room_hwnd):
            logger.error("开始游戏失败：按钮未变为'开始游戏'")
            self.dm.save_screenshot(label="leader_reuse_start_game_failed", force=True)
            return False
        return True

    def _ocr_room_id(self, room_hwnd: int) -> str:
        """OCR 识别 KK 房间窗口中的房间号。

        OCR 区域包含"房间号：xxx"整段文本，需从中提取纯数字房间号。

        :param room_hwnd: 房间窗口句柄
        :return: 纯数字房间号字符串，识别失败返回空字符串
        """
        import re

        room_cfg = self.kk_cfg.get("room", {})
        room_size = tuple(room_cfg.get("window_size", [1224, 904]))
        try:
            self.dm.set_client_size(room_hwnd, *room_size)
        except Exception as e:
            logger.warning(f"设置房间尺寸失败: {e}")
        ocr_area = room_cfg.get("room_id_ocr_area_coords", [0, 0, 0, 0])

        # 先直接 OCR，成功就不刷新（避免不必要的 force_refresh 导致黑边）
        # 失败才 force_refresh 后重试，最多 3 次
        for attempt in range(1, 4):
            if attempt > 1:
                self.dm.force_refresh_layered(room_hwnd)
            lines = self.kk.ocr_kk_lines(room_hwnd, {"area_coords": ocr_area})
            # 从 OCR 文本中提取纯数字房间号（OCR 可能返回"房间号：106660"或"106660"）
            for line in lines:
                text = line.get("text", "").strip()
                if not text:
                    continue
                # 提取连续数字串（房间号均为数字）
                digits = re.search(r"\d+", text)
                if digits:
                    room_id = digits.group()
                    logger.info(f"识别到房间号: {room_id}（原始 OCR: {text}）")
                    return room_id
            logger.debug(f"房间号 OCR 第 {attempt}/3 次未识别到，重试")
            time.sleep(1)

        logger.warning("未能识别房间号")
        return ""

    def _wait_followers_ready(self, room_hwnd: int, round_num: int, timeout: int = 120) -> bool:
        """等待所有队员通过 IPC 上报当前局已执行准备点击。

        Qt 后台视觉帧可能不更新，因此不使用开始按钮 OCR 作为放行条件；
        后续点击开始并等待 War3 窗口作为最终业务确认。

        :param room_hwnd: 房间窗口句柄
        :param round_num: 当前局数
        :param timeout: 超时秒数
        :return: True=所有队员已上报准备, False=超时
        """

        # 构建期望的队员角色集合
        expected_follower_roles = set()
        follower_idx = 0
        for m in self.members:
            if m.get("role") != "leader":
                expected_follower_roles.add(f"follower_{follower_idx}")
                follower_idx += 1

        start = time.time()
        ready_roles: set = set()
        last_log = 0.0
        while time.time() - start < timeout:
            if self.stop_event.is_set():
                return False
            now = time.time()

            # 条件 1：检查 IPC progress 中所有队员 state=ready 且 round 匹配
            # follower 写 ready 后，base.run 会立即覆盖为 game_phase（已准备进入等待游戏阶段），
            # 因此 ready 和 game_phase 都视为已准备。
            # 注意：不在此处 force_refresh 房间窗口——IPC 读 progress 不依赖画面，
            # 反复 force_refresh 会导致 layered window 黑边闪烁。
            all_progress = self.ipc.read_all_progress()
            for role, progress in all_progress.items():
                if role not in expected_follower_roles:
                    continue
                state = progress.get("state", "")
                prog_round = progress.get("round", 0)
                if state in ("ready", "game_phase") and prog_round == round_num:
                    ready_roles.add(role)

            all_ready = expected_follower_roles.issubset(ready_roles)
            if all_ready:
                logger.info("所有队员已上报准备，尝试开始游戏")
                return True
            elif now - last_log >= 5.0:
                waiting = expected_follower_roles - ready_roles
                logger.info(
                    f"等待队员准备: 已准备 {len(ready_roles)}/{len(expected_follower_roles)}, 等待 {sorted(waiting)}"
                )
                last_log = now

            time.sleep(2)

        logger.warning(f"等待队员准备超时 ({timeout}s), 已准备: {sorted(ready_roles)}")
        return False


def main():
    """队长子进程入口 — 由 TeamOrchestrator 通过 subprocess 启动。"""
    from GameBot.runner.team.base import load_member_config
    from GameBot.utils import setup_log_file

    setup_log_file("队长")

    ctx = load_member_config()
    if ctx is None:
        return

    leader = TeamLeader(
        cfg=ctx["cfg"],
        member_cfg=ctx["member_cfg"],
        ipc=ctx["ipc"],
        sync_source=ctx["sync_source"],
        team_cfg=ctx["team_cfg"],
        stop_event=ctx["stop_event"],
    )
    logger.info(f"队长子进程启动: target_player={leader.target_player}, sync_source={ctx['sync_source']}")
    leader.run()


if __name__ == "__main__":
    main()
