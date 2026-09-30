"""War3Business — 魔兽争霸3通用业务逻辑。

本模块原为 645 行单体文件，已拆分为多个 mixin 模块：
- window_manager.py  — 窗口尺寸/查找/进出游戏
- input_controller.py — 按键/点击/移动/传送
- skill_controller.py — 技能施放/连招
- text_monitor.py     — OCR 文字识别/监测 + TextMonitor 类

War3Business 通过多继承组合所有 mixin，对外接口完全不变。
TextMonitor 在此 re-export 以保持 `from .war3 import TextMonitor` 兼容。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from ..base import BaseGame

if TYPE_CHECKING:
    pass
from .input_controller import InputControllerMixin
from .skill_controller import SkillControllerMixin
from .text_monitor import TextMonitor, TextMonitorMixin
from .window_manager import WindowManagerMixin


class War3Business(BaseGame, WindowManagerMixin, InputControllerMixin, SkillControllerMixin, TextMonitorMixin):
    def __init__(self, dm, war3_cfg):
        """
        :param dm: DmClient
        :param war3_cfg: war3 配置段（由任务脚本从 load_task 闭包注入）
        """
        super().__init__(dm)
        self.war3_cfg = war3_cfg
        self._actual_client_size = "未知"
        # 多开认领：目标玩家名（任务侧从 cfg["target_player"] 注入），空则认领空闲窗口
        self.target_player = ""
        self.claimed_owner = ""


__all__ = ["War3Business", "TextMonitor"]
