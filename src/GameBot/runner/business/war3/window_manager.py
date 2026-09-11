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
        # 已对齐则跳过：dx2 绑定状态下真实 resize 会重建交换链导致闪屏，尺寸正确时避免无谓触发
        if self._verify_client_size(hwnd, width, height):
            return
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

        用 find_window 查找窗口是否存在，不要求 War3 是活动窗口
        （多开时 War3 窗口可能不是前台窗口）。

        :param stop_event: 停止事件，设置时中断等待
        :param timeout: 最大等待时间（秒）
        :return: War3 窗口句柄，超时返回 None
        """
        start = time.time()
        while time.time() - start < timeout:
            if stop_event is not None and stop_event.is_set():
                return None
            hwnd = self.dm.find_window(
                self.war3_cfg.get("window_class", ""),
                self.war3_cfg.get("window_title", ""),
            )
            if hwnd:
                logger.info(f"已找到 War3 窗口: hwnd={hwnd}")
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
        """退出游戏回到房间，发送 F10/E/Q 后检测结算页面。

        调用方需确保已在 bind_window 上下文内绑定 War3 窗口。
        """
        logger.info("退出游戏")
        small_window_response_time = self.war3_cfg["small_window_response_time"]
        quit_war3_time = self.war3_cfg["quit_war3_time"]
        try:
            self.dm.key_press_char("F10")
            time.sleep(small_window_response_time)
            self.dm.key_press_char("E")
            time.sleep(small_window_response_time)
            self.dm.key_press_char("Q")
            time.sleep(quit_war3_time)
            # 检测结算页面（仍然是 war3 窗口，无需重新绑定）
            try:
                index, x, y = self.dm.find_pic(
                    *self.war3_cfg["end_statistics_area_coords"],
                    self.war3_cfg["end_statistics_img"],
                    self.war3_cfg["end_statistics_sim"],
                    self.war3_cfg["end_statistics_delta_color"],
                )
                if index > -1:
                    logger.info("检测到结算页面，按回车确认")
                    self.dm.key_press_char("enter")
                    time.sleep(quit_war3_time)
                else:
                    logger.info("未检测到结算页面，已回到 KK 房间")
            except Exception as e:
                logger.warning(f"结算页面检测失败：{e}")
        except Exception as e:
            logger.warning(f"退出游戏流程异常：{e}")

    def identify_war3_owner(self, hwnd: int, known_players: list = None) -> str:
        """通过 War3 加载页面玩家列表 OCR 识别窗口归属玩家。

        仅在游戏加载页面有效，其他时机 OCR 区域无玩家列表。
        调用时机：wait_for_game_window 返回 hwnd 后、wait_enter_game 之前。

        OCR 结果按行(y)再列(x)排序，排除含 exclude_keywords 的文本行，
        第一个非空且未被过滤的行即为最前面的玩家名。

        多开时 OCR 可能把相邻的多个玩家名识别为一行文本（如"善木木岁月神偷"），
        此时用 known_players 子串匹配拆分，取位置最靠前（x_center 最小）的玩家名。

        :param hwnd: War3 窗口句柄
        :param known_players: 已知玩家名列表，用于拆分 OCR 拼接的文本
        :return: 排在最前面的玩家用户名，识别失败返回空字符串
        """
        multi_cfg = self.war3_cfg.get("multi_instance", {})
        loading_cfg = multi_cfg.get("loading_page", {})
        exclude_keywords = loading_cfg.get("exclude_keywords", [])

        lines = self.ocr_lines(self.dm, hwnd, loading_cfg, bind_cfg=self.war3_cfg.get("bind", {}))
        # 按 (y_center, x_center) 排序：先按行排列，再按列排列
        sorted_lines = sorted(lines, key=lambda l: (l.get("y_center", 0), l.get("x_center", 0)))
        for line in sorted_lines:
            text = line.get("text", "").strip()
            if not text:
                continue
            # 排除含关键词的非玩家名文本（称号等）
            if any(kw in text for kw in exclude_keywords):
                logger.debug(f"War3 加载页面排除非玩家名文本：{text}")
                continue
            # 如果提供了已知玩家名列表，尝试从拼接文本中拆分出玩家名
            if known_players:
                matched = []
                for player in known_players:
                    if player and player in text:
                        matched.append(player)
                if matched:
                    # 取在文本中最先出现的玩家名（位置最靠前）
                    matched.sort(key=lambda p: text.index(p))
                    owner = matched[0]
                    logger.info(f"War3 窗口 {hwnd} 归属玩家：{owner}（OCR 原文：{text}）")
                    return owner
            logger.info(f"War3 窗口 {hwnd} 归属玩家：{text}")
            return text
        return ""

    def find_target_war3_hwnd(self, target_player: str = "", known_players: list = None) -> int:
        """查找目标 War3 窗口（支持多开识别）。

        单开时直接返回唯一窗口；多开时通过 OCR 识别窗口归属玩家，
        返回匹配 target_player 的窗口。

        :param target_player: 目标玩家 ID，为空时返回第一个窗口
        :param known_players: 已知玩家名列表，用于拆分 OCR 拼接的文本
        :return: War3 窗口句柄，未找到返回 0
        """
        wins = self.dm.find_windows(
            self.war3_cfg.get("window_class", ""),
            self.war3_cfg.get("window_title", ""),
        )
        if len(wins) == 1:
            return wins[0]["hwnd"]
        if len(wins) > 1:
            if not target_player:
                logger.error("检测到多开 War3 但未配置 target_player，无法识别目标窗口")
                return 0
            for w in wins:
                hwnd = w["hwnd"]
                owner = self.identify_war3_owner(hwnd, known_players=known_players)
                if owner == target_player:
                    return hwnd
            logger.error(f"未找到归属玩家 {target_player} 的 War3 窗口")
            return 0
        return 0

    def bind_war3_window(
        self, target_player: str = "", stop_event=None, timeout: int = 60, known_players: list = None
    ) -> int:
        """等待 War3 窗口出现并绑定准备（多开时验证归属），返回窗口句柄。

        封装了 wait_for_game_window → 多开验证 → set_client_size 的完整流程，
        供组队任务和单局任务复用。调用方拿到 hwnd 后自行 bind_window 执行后续操作。

        :param target_player: 目标玩家 ID，多开时用于窗口归属验证
        :param stop_event: 停止事件
        :param timeout: 等待 War3 窗口超时秒数
        :param known_players: 已知玩家名列表，用于拆分 OCR 拼接的文本
        :return: War3 窗口句柄，失败返回 0
        """
        hwnd = self.wait_for_game_window(stop_event, timeout=timeout)
        if not hwnd:
            return 0
        # 多开时验证窗口归属
        if target_player:
            owner = self.identify_war3_owner(hwnd, known_players=known_players)
            if owner != target_player:
                logger.warning(f"War3 窗口归属 {owner} 与目标 {target_player} 不匹配，尝试查找目标窗口")
                target_hwnd = self.find_target_war3_hwnd(target_player, known_players=known_players)
                if target_hwnd:
                    hwnd = target_hwnd
                else:
                    logger.error(f"未找到归属 {target_player} 的 War3 窗口")
                    return 0
        self.set_client_size(hwnd)
        return hwnd
