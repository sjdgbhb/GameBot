from __future__ import annotations

import time
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from GameBot.runner.dm_client import DmClient
from .base import BasePlatform
from GameBot.utils import logger


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

        绑定窗口后先设置客户区尺寸，确保按钮坐标不偏移。
        """
        room_cfg = self.kk_cfg.get('room', {})
        hwnd = dm.find_window(self.kk_cfg['window_class'], self.kk_cfg['window_title'])
        if hwnd:
            w, h = room_cfg.get('window_size', [1328, 945])
            dm.set_client_size(hwnd, w, h)
        dm.move_to(*room_cfg['start_button_coords'])
        time.sleep(0.2)
        dm.left_click()
        logger.debug("已点击开始游戏，等待进入war3")
        time.sleep(room_cfg['start_wait_time'])

    def handle_disconnect_dialog(self, dm: DmClient) -> bool:
        """检测并处理 KK 掉线重连弹窗。

        弹窗类名与 create_room_window_class 相同，通过窗口尺寸区分。
        如果检测到弹窗则点击"开始"按钮重连。

        :return: True=检测到弹窗并已处理, False=未检测到弹窗
        """
        dialog_cfg = self.kk_cfg.get('disconnect_dialog', {})
        hwnd = dm.find_window(
            self.kk_cfg.get('create_room_window_class', ''),
            self.kk_cfg.get('window_title', ''),
        )
        if not hwnd:
            return False
        # 通过客户区尺寸确认是弹窗而非主窗口
        try:
            x1, y1, x2, y2 = dm.get_client_rect(hwnd)
            actual_w, actual_h = x2 - x1, y2 - y1
        except Exception:
            return False
        expect_size = dialog_cfg.get('window_size', [440, 260])
        if actual_w != expect_size[0] or actual_h != expect_size[1]:
            return False
        logger.warning("检测到 KK 掉线重连弹窗，点击取消重连")
        dm.set_client_size(hwnd, *expect_size)
        coords = dialog_cfg.get('cancel_button_coords', [317, 192])
        dm.move_to(*coords)
        time.sleep(0.2)
        dm.left_click()
        logger.info("已点击取消重连按钮，等待回到房间")
        time.sleep(dialog_cfg.get('cancel_wait_time', 3))
        return True