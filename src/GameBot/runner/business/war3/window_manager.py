"""窗口管理 — 从 war3.py 拆分。

包含 War3Business 的窗口管理 mixin：窗口尺寸设置/验证、窗口刷新、
窗口查找、进出游戏判断等。
"""

import time
from typing import Optional

from GameBot.utils import WindowLostError, logger


class WindowManagerMixin:
    """War3Business 的窗口管理 mixin。

    依赖 self.dm（DmClient）和 self.war3_cfg（dict）。
    """

    def set_client_size(self, hwnd, width: Optional[int] = None, height: Optional[int] = None):
        width = self.war3_cfg.get("client_size", [1902, 1033])[0] if width is None else width
        height = self.war3_cfg.get("client_size", [1902, 1033])[1] if height is None else height
        self.dm.set_client_size(hwnd, width, height)
        # 验证实际客户区尺寸是否与配置一致，不一致则重试一次
        actual = self._verify_client_size(hwnd, width, height)
        if not actual:
            logger.warning("客户区尺寸验证失败，重试一次")
            self.dm.set_client_size(hwnd, width - 1, height - 1)
            time.sleep(0.1)
            self.dm.set_client_size(hwnd, width, height)
            actual = self._verify_client_size(hwnd, width, height)
            if not actual:
                logger.error(
                    f"客户区尺寸无法对齐到 {width}x{height}（实际 {self._actual_client_size}），坐标可能偏移\n"
                    f"请在 KK 平台 → 设置 → 图像设置 中，将 war3 分辨率和窗口尺寸均设为 1920x1080，然后重启 war3"
                )

    def _verify_client_size(self, hwnd: int, expect_w: int, expect_h: int) -> bool:
        """验证窗口实际客户区尺寸是否与期望值一致。"""
        try:
            x1, y1, x2, y2 = self.dm.get_client_rect(hwnd)
            actual_w = x2 - x1
            actual_h = y2 - y1
            self._actual_client_size = f"{actual_w}x{actual_h}"
            if actual_w == expect_w and actual_h == expect_h:
                logger.info(f"客户区尺寸验证通过: {actual_w}x{actual_h}")
                return True
            logger.warning(f"客户区尺寸不匹配: 期望 {expect_w}x{expect_h}, 实际 {actual_w}x{actual_h}")
            return False
        except Exception as e:
            logger.warning(f"客户区尺寸验证异常: {e}")
            return False

    def refresh_war3_window(self, hwnd: int, width: Optional[int] = None, height: Optional[int] = None):
        """利用大漠刷新窗口（替代手动最大化/还原）"""
        # 请根据你已有的找窗口方法获取最新句柄（因为句柄可能变化）
        hwnd = self.dm.get_active_window(self.war3_cfg["window_class"], self.war3_cfg["window_title"])
        if hwnd:
            self.set_client_size(hwnd, width - 1, height - 1)
            time.sleep(0.1)
            self.set_client_size(hwnd, width, height)
            logger.info("[主脚本] 窗口边界已刷新")
        else:
            logger.info("[主脚本] 未找到游戏窗口，跳过刷新")

    def _find_war3_hwnd(self) -> int:
        """用大漠按类名/标题查找魔兽窗口句柄（主线程调用，大漠 COM 线程亲和）。"""
        return self.dm.find_window(
            self.war3_cfg.get("window_class", ""),
            self.war3_cfg.get("window_title", ""),
        )

    def wait_for_game_window(self, stop_event=None, timeout: int = 60) -> int:
        """等待 War3 窗口出现（从 KK 启动后），返回 hwnd 或 None。

        等待期间不重复截图，超时后保存一张当前屏幕截图供用户查看。

        :param stop_event: 停止事件，设置时中断等待
        :param timeout: 最大等待时间（秒）
        :return: War3 窗口句柄，超时返回 None
        """
        start = time.time()
        while time.time() - start < timeout:
            if stop_event is not None and stop_event.is_set():
                return None
            hwnd = self.dm.get_active_window(
                self.war3_cfg.get("window_class", ""),
                self.war3_cfg.get("window_title", ""),
                capture=False,
            )
            if hwnd:
                logger.info("已找到 War3 窗口")
                return hwnd
            time.sleep(0.5)
        logger.warning(f"等待 War3 窗口超时（{timeout}s），已保存截图")
        self.dm.save_screenshot(label="wait_for_game_window_timeout")
        return None

    def wait_enter_game(self, task, stop_event=None):
        """等待进入游戏，带超时和窗口消失检测。

        循环检测游戏内信号（is_in_game），检测到后记录 game_start_time。
        如果 War3 窗口消失则抛出 WindowLostError（掉线）。
        超时未进入则抛 TimeoutError（可能卡在加载界面）。

        :param task: 任务对象（需有 game_start_time / pet_feed_time 属性）
        :param stop_event: 停止事件，设置时中断等待
        :raises WindowLostError: War3 窗口消失（掉线）
        :raises TimeoutError: 等待进入游戏超时（卡在加载界面）
        """
        detect_cfg = self.war3_cfg.get("in_game_detect", {})
        timeout = detect_cfg.get("timeout", 120)
        method = detect_cfg.get("method", "image")
        interval = self.war3_cfg.get("check_interval_time", 2)

        start = time.time()
        while time.time() - start < timeout:
            if method == "image" and self.is_in_game():
                task.game_start_time = task.pet_feed_time = time.time()
                logger.info("已进入游戏")
                return
            # 检查 War3 窗口是否还在
            hwnd = self.dm.get_active_window(
                self.war3_cfg.get("window_class", ""),
                self.war3_cfg.get("window_title", ""),
                capture=False,
            )
            if not hwnd:
                logger.error("War3 窗口消失，可能掉线，已保存截图")
                self.dm.save_active_window_screenshot(label="war3_window_lost")
                raise WindowLostError("War3 窗口消失，可能掉线")
            self.interruptible_wait(interval, stop_event)
        raise TimeoutError(f"等待进入游戏超时（{timeout}s），可能卡在加载界面")

    def is_in_game(self):
        """
        是否处于游戏内
        :return:
        """
        index, x, y = self.dm.find_pic(
            *self.war3_cfg["mini_map_signal_area_coords"],
            self.war3_cfg["mini_map_signal_img"],
            self.war3_cfg["mini_map_signal_sim"],
            self.war3_cfg["mini_map_signal_delta_color"],
        )
        return index > -1

    def quit_game(self):
        """退出游戏回到房间（Alt+F4 或菜单退出）"""
        # 简单实现：按 F10 -> E -> Q
        logger.info("退出游戏")
        small_window_response_time = self.war3_cfg["small_window_response_time"]
        self.dm.key_press_char("F10")
        time.sleep(small_window_response_time)
        self.dm.key_press_char("E")
        time.sleep(small_window_response_time)
        self.dm.key_press_char("Q")
        quit_war3_time = self.war3_cfg["quit_war3_time"]
        time.sleep(quit_war3_time)
        # 判断是否出现结尾资源统计画面，如果出现则需关闭该画面
        index, x, y = self.dm.find_pic(
            *self.war3_cfg["end_statistics_area_coords"],
            self.war3_cfg["end_statistics_img"],
            self.war3_cfg["end_statistics_sim"],
            self.war3_cfg["end_statistics_delta_color"],
        )
        if index > -1:
            self.dm.key_press_char("enter")
        time.sleep(quit_war3_time)
