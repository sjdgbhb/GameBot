"""
定时清理英雄附近地面物品的工具。

内联式调用（非后台线程），避免大漠 COM 跨线程安全问题。
任务主循环每次迭代时调用 tick()，以一定概率发送清理指令。
"""

from __future__ import annotations

import random
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from GameBot.runner.business.war3 import War3Business
from GameBot.utils import logger


class NearbyCleaner:
    """概率清理英雄附近地面物品。

    在任务主循环中每次迭代调用 tick()，以 probability 概率发送清理指令。
    无后台线程，避免大漠 COM 跨线程调用风险。

    :param war3: War3Business 实例（用于 send_msg）
    :param command_cfg: command 配置段（含 clear_nearby / clear_endless）
    :param probability: 每次 tick 触发清理的概率（0~1），0 表示禁用
    :param use_endless_cmd: True 用 clear_endless 指令，False 用 clear_nearby（默认）
    """

    def __init__(
        self, war3: "War3Business", command_cfg: dict, probability: float = 0.0, use_endless_cmd: bool = False
    ):
        self._war3 = war3
        self._cmd = command_cfg.get("clear_endless" if use_endless_cmd else "clear_nearby", "-delh")
        self._probability = probability

    def tick(self):
        """在主循环中调用，以概率触发清理。"""
        if self._probability <= 0:
            return
        if random.random() < self._probability:
            self._war3.send_msg(self._cmd)
            logger.info(f"清理英雄附近物品（概率 {self._probability:.0%}）")

    def reset(self):
        """重置状态（概率模式无需重置，保留接口兼容）。"""
        pass
