from __future__ import annotations

import time
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from GameBot.runner.dm_client import DmClient
from GameBot.utils import logger

from .base import BasePlatform


class KKBusiness(BasePlatform):
    def __init__(self, dm: DmClient, kk_cfg: dict) -> None:
        """
        :param dm: DmClient
        :param kk_cfg: kk 平台配置段（由任务脚本从 load_task 闭包注入）
        """
        super().__init__(dm)
        self.dm = dm
        self.kk_cfg = kk_cfg

    def start_game(self, dm: DmClient) -> None:
        """在KK房间中点击开始游戏按钮。

        先关闭挡在前面的 KK 弹窗（弹窗会导致开始按钮无法点击），
        找到房间窗口后再绑定并开始游戏。
        """
        room_cfg = self.kk_cfg.get("room", {})
        room_size = tuple(room_cfg.get("window_size", [1328, 945]))

        room_hwnd = self.dismiss_room_popups(dm, room_size)
        if not room_hwnd:
            logger.error("未找到 KK 房间窗口")
            dm.save_screenshot(label="kk_room_not_found")
            return

        # 对齐房间尺寸，确保开始按钮坐标不偏移
        dm.set_client_size(room_hwnd, *room_size)

        with dm.bind_window(room_hwnd):
            dm.move_to(*room_cfg["start_button_coords"])
            time.sleep(0.2)
            dm.left_click()
            logger.debug("已点击开始游戏，等待进入war3")
            time.sleep(room_cfg["start_wait_time"])

    def dismiss_room_popups(self, dm: DmClient, room_size: tuple[int, int] | None = None) -> int:
        """清理会让 KK 房间开始按钮无法点击的弹窗或遮罩层，返回找到的房间句柄。

        只处理最顶层（活动）窗口：
        - 尺寸与房间一致或受保护的窗口 => 房间/大厅，不关闭。
        - 尺寸明显大于房间的窗口 => 平台大厅等主界面，不关闭。
        - 其它较小的窗口 => 弹窗，点击右上角 X 关闭。

        循环最多尝试 5 次，直到最顶层是房间或受保护窗口。

        :param room_size: 房间客户区尺寸 (宽, 高)，未提供时从配置读取
        :return: 房间句柄，找不到返回 0
        """
        room_cfg = self.kk_cfg.get("room", {})
        popup_cfg = self.kk_cfg.get("popup", {})
        if room_size is None:
            room_size = tuple(room_cfg.get("window_size", [1328, 945]))

        offset_x, offset_y = popup_cfg.get("close_offset", [15, 15])
        protected_sizes = {
            room_size,
            *{tuple(size) for size in popup_cfg.get("protected_window_sizes", []) if len(size) == 2},
        }
        max_area_ratio = popup_cfg.get("max_popup_area_ratio", 0.85)
        room_area = room_size[0] * room_size[1]

        room_hwnd = 0
        for _ in range(5):
            # 每次取最顶层的同名窗口
            hwnd = dm.find_window(
                self.kk_cfg.get("window_class", ""),
                self.kk_cfg.get("window_title", ""),
            )
            if not hwnd:
                break

            try:
                x1, y1, x2, y2 = dm.get_client_rect(hwnd)
                actual_size = (x2 - x1, y2 - y1)
            except Exception:
                break

            # 房间或受保护窗口（如平台大厅主界面）
            if actual_size in protected_sizes:
                room_hwnd = hwnd
                break

            # 明显大于房间的窗口视为大厅/主界面，不关闭
            area = actual_size[0] * actual_size[1]
            if actual_size[0] > room_size[0] or actual_size[1] > room_size[1] or area > room_area * max_area_ratio:
                logger.warning(f"最顶层 KK 窗口尺寸 {actual_size} 大于房间，可能是平台大厅，不关闭")
                break

            # 是弹窗，尝试点击 X 关闭
            logger.warning(f"检测到 KK 弹窗: hwnd={hwnd}, 尺寸 {actual_size}，尝试点击右上角 X 关闭")
            if dm.close_window_by_x(hwnd, offset_x, offset_y):
                time.sleep(0.3)
                continue

            # 关闭失败，不再继续
            break

        if not room_hwnd:
            # 兜底：从窗口类/标题中枚举尺寸等于房间的窗口
            room_hwnd = self._find_room_by_size(dm, room_size)

        return room_hwnd

    def _find_room_by_size(self, dm: DmClient, room_size: tuple[int, int]) -> int:
        """按尺寸在顶层窗口中查找 KK 房间句柄。"""
        for cls in (
            self.kk_cfg.get("window_class", ""),
            self.kk_cfg.get("create_room_window_class", ""),
        ):
            if not cls:
                continue
            for hwnd in dm.enum_windows(cls, self.kk_cfg.get("window_title", "")):
                try:
                    x1, y1, x2, y2 = dm.get_client_rect(hwnd)
                    if (x2 - x1, y2 - y1) == room_size:
                        return hwnd
                except Exception:
                    continue
        return 0

    def handle_disconnect_dialog(self, dm: DmClient) -> bool:
        """检测并处理 KK 掉线重连弹窗。

        弹窗类名与 create_room_window_class 相同，通过窗口尺寸区分。
        如果检测到弹窗则点击"开始"按钮重连。

        :return: True=检测到弹窗并已处理, False=未检测到弹窗
        """
        dialog_cfg = self.kk_cfg.get("disconnect_dialog", {})
        hwnd = dm.find_window(
            self.kk_cfg.get("create_room_window_class", ""),
            self.kk_cfg.get("window_title", ""),
        )
        if not hwnd:
            return False
        # 通过客户区尺寸确认是弹窗而非主窗口
        try:
            x1, y1, x2, y2 = dm.get_client_rect(hwnd)
            actual_w, actual_h = x2 - x1, y2 - y1
        except Exception:
            return False
        expect_size = dialog_cfg.get("window_size", [440, 260])
        if actual_w != expect_size[0] or actual_h != expect_size[1]:
            return False
        logger.warning("检测到 KK 掉线重连弹窗，点击取消重连")
        dm.set_client_size(hwnd, *expect_size)
        coords = dialog_cfg.get("cancel_button_coords", [317, 192])
        dm.move_to(*coords)
        time.sleep(0.2)
        dm.left_click()
        logger.info("已点击取消重连按钮，等待回到房间")
        time.sleep(dialog_cfg.get("cancel_wait_time", 3))
        return True
