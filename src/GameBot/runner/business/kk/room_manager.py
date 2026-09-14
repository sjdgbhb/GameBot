"""KK 房间管理 mixin — 从 __init__.py 拆分。

包含 KKBusiness 的房间相关方法：开始游戏、弹窗清理、掉线重连。
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from GameBot.runner.driver.base import DmClientBase as DmClient
from GameBot.utils import logger


class RoomManagerMixin:
    """KK 房间操作 mixin。依赖 self.dm（DmClient）和 self.kk_cfg（dict）。"""

    def start_game(self, dm: DmClient, room_hwnd: int = 0) -> bool:
        """在KK房间中点击开始游戏按钮。

        先关闭挡在前面的 KK 弹窗（弹窗会导致开始按钮无法点击），
        找到房间窗口后 OCR 验证按钮文本为"开始游戏"再点击。

        :param room_hwnd: 已知的房间句柄，传入时跳过 dismiss_room_popups 检测
        :return: True=成功点击开始游戏, False=按钮文本不是"开始游戏"
        """
        room_cfg = self.kk_cfg.get("room", {})
        room_size = tuple(room_cfg.get("window_size", [1324, 904]))

        if not room_hwnd:
            room_hwnd = self.dismiss_room_popups(dm, room_size)
        if not room_hwnd:
            logger.error("未找到 KK 房间窗口")
            dm.save_screenshot(label="kk_room_not_found", force=True)
            return False

        try:
            dm.set_client_size(room_hwnd, *room_size)
            logger.info(f"房间窗口已统一尺寸: {room_size}")
        except Exception as e:
            logger.warning(f"设置房间尺寸失败: {e}")

        start_game_keyword = room_cfg.get("start_game_keyword", "开始游戏")
        ocr_area = room_cfg.get("start_button_ocr_area_coords", [0, 0, 0, 0])
        start_coords = room_cfg.get("start_button_coords", [0, 0])

        bind_cfg = self.kk_cfg.get("bind", {})
        with dm.bind_window(room_hwnd, bind_cfg=bind_cfg):
            # OCR 验证按钮文本是否为"开始游戏"
            if ocr_area != [0, 0, 0, 0]:
                lines = self.ocr_kk_lines(
                    room_hwnd,
                    {"area_coords": ocr_area},
                )
                button_text = ""
                for line in lines:
                    text = line.get("text", "").strip()
                    if text:
                        button_text = text
                        break
                if start_game_keyword in button_text:
                    logger.debug(f"OCR 确认开始按钮文本: {button_text}")
                else:
                    logger.debug(f"开始按钮视觉帧尚未更新（当前: {button_text}），按业务状态继续点击")

            dm.move_to(*start_coords)
            time.sleep(0.2)
            dm.left_click()
        logger.debug("已点击开始游戏，等待进入war3")
        time.sleep(room_cfg["start_wait_time"])
        return True

    def dismiss_room_popups(self, dm: DmClient, room_size: tuple = None, owner_pid: int = 0) -> int:
        """清理目标 KK 进程的房间弹窗，并通过按钮状态 OCR 返回房间句柄。"""
        popup_cfg = self.kk_cfg.get("popup", {})
        offset_x, offset_y = popup_cfg.get("close_offset", [15, 15])
        protected_keywords = popup_cfg.get("protected_keywords", [])
        popup_class = self.kk_cfg.get("create_room_window_class", "")
        min_width, min_height = self.kk_cfg.get("min_business_window_size", [200, 200])
        attempted_hwnds = set()

        for _ in range(5):
            room_hwnd = self._find_room_window(dm, owner_pid=owner_pid)
            if room_hwnd:
                return room_hwnd
            if not popup_class:
                break

            popup_hwnd = 0
            window_title = self.kk_cfg.get("window_title", "")
            for w in dm.find_windows(popup_class, window_title, owner_pid):
                hwnd = w["hwnd"]
                if hwnd in attempted_hwnds:
                    continue
                try:
                    x1, y1, x2, y2 = dm.get_client_rect(hwnd)
                    if x2 - x1 < min_width or y2 - y1 < min_height:
                        continue
                except Exception:
                    continue
                popup_hwnd = hwnd
                break
            if not popup_hwnd:
                break

            try:
                x1, y1, x2, y2 = dm.get_client_rect(popup_hwnd)
                lines = self.ocr_kk_lines(
                    popup_hwnd,
                    {"area_coords": [0, 0, x2 - x1, y2 - y1]},
                )
            except Exception as e:
                logger.warning(f"识别 KK 弹窗 {popup_hwnd} 失败: {e}")
                break

            all_text = " ".join(line.get("text", "") for line in lines)
            if any(keyword in all_text for keyword in protected_keywords):
                logger.debug(f"窗口 {popup_hwnd} 含保护关键词，跳过关闭: {all_text}")
                break

            attempted_hwnds.add(popup_hwnd)
            logger.warning(f"检测到 KK 弹窗: hwnd={popup_hwnd}，尝试点击右上角 X 关闭")
            if not dm.close_window_by_x(popup_hwnd, offset_x, offset_y):
                break
            time.sleep(0.3)

        return self._find_room_window(dm, owner_pid=owner_pid)

    def _find_room_window(self, dm: DmClient, owner_pid: int = 0) -> int:
        """按 PID、类名和原生客户区尺寸查找房间窗口。"""
        room_cfg = self.kk_cfg.get("room", {})
        room_size = tuple(room_cfg.get("window_size", [1224, 904]))
        size_tolerance = room_cfg.get("size_tolerance", 30)
        window_class = self.kk_cfg.get("window_class", "")
        min_width, min_height = self.kk_cfg.get("min_business_window_size", [200, 200])
        if not window_class:
            return 0

        window_title = self.kk_cfg.get("window_title", "")
        for w in dm.find_windows(window_class, window_title, owner_pid):
            hwnd = w["hwnd"]
            try:
                x1, y1, x2, y2 = dm.get_client_rect(hwnd)
                width, height = x2 - x1, y2 - y1
                if width < min_width or height < min_height:
                    continue
                if abs(width - room_size[0]) <= size_tolerance and abs(height - room_size[1]) <= size_tolerance:
                    logger.debug(f"识别到 KK 房间窗口: hwnd={hwnd}, size=({width}x{height})")
                    return hwnd
            except Exception as e:
                logger.debug(f"识别 KK 房间候选窗口 {hwnd} 失败: {e}")
        return 0

    def handle_disconnect_dialog(self, dm: DmClient, owner_pid: int = 0) -> bool:
        """检测并处理 KK 掉线重连弹窗。

        弹窗类名与 create_room_window_class 相同，通过窗口尺寸区分。
        多开时通过 owner_pid 只枚举本进程的窗口，避免误操作其他账号的弹窗。

        :param owner_pid: 所属 KK 进程 PID，>0 时按 PID 枚举；0 时单开用 find_window
        :return: True=检测到弹窗并已处理, False=未检测到弹窗
        """
        dialog_cfg = self.kk_cfg.get("disconnect_dialog", {})
        popup_class = self.kk_cfg.get("create_room_window_class", "")
        expect_size = dialog_cfg.get("window_size", [440, 260])

        # 按 PID + 类名 + 标题枚举，找到尺寸匹配的掉线弹窗
        target_hwnd = 0
        window_title = self.kk_cfg.get("window_title", "")
        for w in dm.find_windows(popup_class, window_title, owner_pid):
            hwnd = w["hwnd"]
            try:
                x1, y1, x2, y2 = dm.get_client_rect(hwnd)
                if (x2 - x1, y2 - y1) == tuple(expect_size):
                    target_hwnd = hwnd
                    break
            except Exception:
                continue
        if not target_hwnd:
            return False
        logger.warning("检测到 KK 掉线重连弹窗，点击取消重连")
        try:
            dm.set_client_size(target_hwnd, *expect_size)
        except Exception as e:
            logger.warning(f"设置掉线弹窗尺寸失败: {e}")
        coords = dialog_cfg.get("cancel_button_coords", [317, 192])
        dm.move_to(*coords)
        time.sleep(0.2)
        dm.left_click()
        logger.info("已点击取消重连按钮，等待回到房间")
        time.sleep(dialog_cfg.get("cancel_wait_time", 3))
        return True
