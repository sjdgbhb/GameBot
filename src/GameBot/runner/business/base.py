from __future__ import annotations

import time
from abc import ABC
from typing import TYPE_CHECKING

from GameBot.inference import get_inference_client
from GameBot.runner.driver.wgc_capture import WgcCapture

if TYPE_CHECKING:
    from GameBot.runner.driver.base import DmClientBase as DmClient


class Base(ABC):
    def __init__(self, dm: DmClient):
        self.dm = dm

    def sleep(self, seconds: float):
        """统一休眠，可在此处加入全局暂停检查逻辑"""
        time.sleep(seconds)

    def is_dm_valid(self) -> bool:
        """检查大漠对象是否可用（如 Ver 方法）"""
        return self.dm.version != ""

    def ocr_lines(self, hwnd: int, ocr_cfg: dict, merge_lines: bool = True) -> list:
        """WGC 截图 → OCR 逐行识别，返回行列表。

        :param hwnd: 目标窗口句柄
        :param ocr_cfg: 含 area_coords [x1,y1,x2,y2]（客户区坐标）
        :param merge_lines: False 时保持每个 OCR 框独立（网格布局）
        """
        x1, y1, x2, y2 = ocr_cfg["area_coords"]
        img = WgcCapture.for_hwnd(hwnd).grab_client_rgb((x1, y1, x2, y2))
        return get_inference_client(load_chest=False, load_combat=False).ocr_lines_from_array(
            img, merge_lines=merge_lines
        )

    def ocr_text(self, hwnd: int, ocr_cfg: dict) -> str:
        """WGC 截图 → OCR 识别，返回文本。"""
        x1, y1, x2, y2 = ocr_cfg["area_coords"]
        img = WgcCapture.for_hwnd(hwnd).grab_client_rgb((x1, y1, x2, y2))
        return get_inference_client(load_chest=False, load_combat=False).ocr_from_array(img)


class BasePlatform(Base):
    pass


class BaseGame(Base):
    pass
