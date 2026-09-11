from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from GameBot.runner.driver.base import DmClientBase as DmClient

from ..base import BasePlatform
from .hall_manager import HallManagerMixin
from .join_room import JoinRoomMixin
from .multi_instance import MultiInstanceMixin
from .room_manager import RoomManagerMixin


class KKBusiness(BasePlatform, RoomManagerMixin, HallManagerMixin, MultiInstanceMixin, JoinRoomMixin):
    """KK 平台业务逻辑。"""

    def __init__(self, dm: DmClient, kk_cfg: dict) -> None:
        """
        :param dm: DmClient
        :param kk_cfg: kk 平台配置段（由任务脚本从 load_task 闭包注入）
        """
        super().__init__(dm)
        self.dm = dm
        self.kk_cfg = kk_cfg

    def ocr_kk_lines(self, dm: DmClient, hwnd: int, ocr_cfg: dict, merge_lines: bool = True) -> list:
        """OCR KK 窗口区域，返回逐行结果。委托 Base.ocr_lines，传入 KK bind 配置。"""
        bind_cfg = self.kk_cfg.get("bind", {})
        return self.ocr_lines(dm, hwnd, ocr_cfg, bind_cfg=bind_cfg, merge_lines=merge_lines)


__all__ = ["KKBusiness"]
