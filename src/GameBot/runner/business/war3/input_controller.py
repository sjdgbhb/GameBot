"""输入控制 — 从 war3.py 拆分。

包含 War3Business 的输入操作 mixin：消息发送、英雄居中、移动点击、
传送行走、背包物品使用、框选等。
"""

import threading
import time
from typing import Optional

from GameBot.utils import StopTaskError, logger


class InputControllerMixin:
    """War3Business 的输入操作 mixin。

    依赖 self.dm（DmClient）和 self.war3_cfg（dict）。
    """

    def interruptible_wait(self, seconds: float, stop_event: Optional[threading.Event] = None) -> bool:
        """可中断等待。stop_event 设置时抛出 StopTaskError 中断执行流，否则等待结束后返回 False。

        有 stop_event 时用 event.wait(timeout) 阻塞最多 seconds 秒（被设置即提前返回），
        检测到停止信号后抛 StopTaskError，让异常沿调用栈向上传播，无需调用方手动检查。
        无 stop_event 时直接 sleep。
        """
        if stop_event is not None:
            if stop_event.wait(timeout=seconds):
                raise StopTaskError("用户请求停止任务")
            return False
        time.sleep(seconds)
        return False

    def send_msg(self, msg: str, is_all: bool = False, stop_event: Optional[threading.Event] = None):
        """
        向游戏里发送消息。字符通过大漠绑定窗口的键盘通道注入，不经过系统输入法，
        因此不需要（也不应该）切换系统输入法。
        :param msg: 消息文本（如 -delh）
        :param is_all: 默认发送给盟友
        :param stop_event: 停止事件，设置时中断等待
        :return:
        """
        if is_all:
            self.dm.key_down_char("shift")
            self.interruptible_wait(0.1, stop_event)
            self.dm.key_down_char("enter")
            self.interruptible_wait(0.1, stop_event)
            self.dm.key_up_char("enter")
            self.interruptible_wait(0.1, stop_event)
            self.dm.key_up_char("shift")
        else:
            self.dm.key_press_char("enter")
        self.interruptible_wait(0.1, stop_event)
        for char in msg:
            self.dm.key_press_char(char)
            self.interruptible_wait(0.05, stop_event)
        self.dm.key_press_char("enter")

    def center_hero(self, char: str = "F1"):
        """双击F1将视角居中到英雄"""
        self.dm.key_press_char(char)
        time.sleep(0.05)
        self.dm.key_press_char(char)

    def _check_stop(self, stop_event: Optional[threading.Event]):
        """stop_event 已设置时抛 StopTaskError，用于 click 前的最后一道检查。"""
        if stop_event is not None and stop_event.is_set():
            raise StopTaskError("用户请求停止任务")

    def _click_target(
        self, target_coords: list, mode: int = 0, wait_time: float = None, stop_event: Optional[threading.Event] = None
    ):
        """点击目标位置，让英雄移动过去（右键/A+左键/M+左键）"""
        key_time = self.war3_cfg["key_time"]
        self.dm.move_to(*target_coords)
        # 移动光标后的等待可中断：stop_event 触发时 interruptible_wait 抛 StopTaskError，
        # 避免发出多余的移动指令（上层会转去走最后一个路线点）。
        self.interruptible_wait(key_time, stop_event)
        self._check_stop(stop_event)
        if mode == 0:
            self.dm.right_click()
        elif mode == 1:
            self.dm.key_press_char("A")
            self.interruptible_wait(key_time, stop_event)
            self._check_stop(stop_event)
            self.dm.left_click()
        elif mode == 2:
            self.dm.key_press_char("M")
            self.interruptible_wait(key_time, stop_event)
            self._check_stop(stop_event)
            self.dm.left_click()
        self.interruptible_wait(wait_time or self.war3_cfg["general_time"], stop_event)

    def move_to_point(
        self, target_coords: list, mode: int = 0, wait_time: float = None, stop_event: Optional[threading.Event] = None
    ):
        """
        移动到目标点（当前屏幕可见范围内）
        :param target_coords: 目标坐标（相对客户区）
        :param mode: 0右键移动、1 A+左键攻击移动、2 M+左键移动
        :param wait_time: 移动后等待时间
        :param stop_event: 事件设置时中断等待
        """
        self._click_target(target_coords, mode, wait_time, stop_event)

    def move_to_minimap_point(
        self,
        mini_coords,
        target_coords,
        mode: int = 0,
        wait_time: float = None,
        stop_event: Optional[threading.Event] = None,
    ):
        """
        通过小地图切换到目标位置所在窗口，然后点击目标位置让英雄走过去。
        :param mini_coords: 小地图上的坐标（用于切换视角），为空则跳过小地图点击
        :param target_coords: 切换视角后，主屏幕上的目标位置坐标，为空则只等待
        :param mode: 0右键移动、1 A+左键攻击移动、2 M+左键移动
        :param wait_time: 移动后等待时间
        :param stop_event: 事件设置时中断等待
        """
        # 小地图坐标为空时不点击小地图
        if mini_coords:
            self.dm.move_to(*mini_coords)
            # 切视角前的每段等待可中断，消除完成事件触发后仍要等满
            # key_time + general_time 的死区（合计约 0.6s）。
            self.interruptible_wait(self.war3_cfg["key_time"], stop_event)
            self._check_stop(stop_event)
            self.dm.left_click()
            self.interruptible_wait(self.war3_cfg["general_time"], stop_event)
        # 目标坐标为空时只等待，否则点击目标
        if target_coords:
            self._click_target(target_coords, mode, wait_time, stop_event)
        else:
            self.interruptible_wait(wait_time or self.war3_cfg["general_time"], stop_event)

    def go_through_teleport(self, tp: dict, stop_event: Optional[threading.Event] = None):
        """走到传送点并触发传送。

        :param tp: 传送点配置（mini_coords / coords / walk_mode / time / trigger / desc）
            trigger="walk"：踩圈即传，英雄走到即完成；
            trigger="click"：走近后右键该物体进入。
        :param stop_event: 事件设置时中断等待
        """
        logger.info(f"前往传送点：{tp.get('desc', '')}，等待时间：{tp.get('time', 3)}s")
        self.move_to_minimap_point(
            tp.get("mini_coords"),
            tp.get("coords"),
            tp.get("walk_mode", 1),
            tp.get("time", 3),
            stop_event,
        )
        if tp.get("trigger") == "click":
            coords = tp.get("coords")
            if not coords:
                return
            self.dm.move_to(*coords)
            self.interruptible_wait(self.war3_cfg["key_time"], stop_event)
            self.dm.right_click()
            self.interruptible_wait(self.war3_cfg["general_time"], stop_event)

    def use_inventory_item(self, hotkey: str, stop_event: Optional[threading.Event] = None):
        """使用背包物品（按快捷键）

        :param hotkey: 快捷键字符
        :param stop_event: 停止事件，设置时中断等待
        """
        self.dm.key_press_char(hotkey)
        self.interruptible_wait(self.war3_cfg["key_time"], stop_event)

    def box_selection(self, coords, duration_time: float = 3.0):
        """
        框选区域，用于测试
        :param coords: [x1, y1, x2, y2]
        :param duration_time: 持续时间
        :return:
        """
        general_time = self.war3_cfg["general_time"]
        self.dm.move_to(*coords[:2])
        time.sleep(general_time)
        self.dm.left_down()
        time.sleep(general_time)
        self.dm.move_to(*coords[2:])
        time.sleep(duration_time)
        self.dm.left_up()
