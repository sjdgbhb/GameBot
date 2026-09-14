"""窗口管理 — 从 war3.py 拆分。

包含 War3Business 的窗口管理 mixin：窗口尺寸设置/验证、窗口刷新、
窗口查找、多开认领、进出游戏判断等。
"""

import ctypes
import os
import secrets
import time
from ctypes import wintypes
from typing import Optional

from GameBot.runner.driver.process_lock import NamedMutex
from GameBot.utils import WindowLostError, logger

_user32 = ctypes.windll.user32
_user32.IsWindow.argtypes = [wintypes.HWND]
_user32.IsWindow.restype = wintypes.BOOL


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
        hwnd = self.find_game_window()
        if hwnd:
            self.set_client_size(hwnd, width - 1, height - 1)
            time.sleep(0.1)
            self.set_client_size(hwnd, width, height)
            logger.info("[主脚本] 窗口边界已刷新")
        else:
            logger.info("[主脚本] 未找到游戏窗口，跳过刷新")

    def _find_war3_hwnd(self) -> int:
        """返回本脚本认领的 war3 窗口；未走认领流程时退化为按类名/标题查找。

        认领后不再重新枚举窗口——多开场景下重新 find_window 可能拿到
        其他玩家的窗口，存活判断用 IsWindow 校验认领句柄。
        """
        claimed = getattr(self, "_claimed_hwnd", 0)
        if claimed:
            return claimed if _user32.IsWindow(claimed) else 0
        return self.dm.find_window(
            self.war3_cfg.get("window_class", ""),
            self.war3_cfg.get("window_title", ""),
        )

    # ── 多开窗口认领 ─────────────────────────────────────

    def claim_war3_window(self, target_player: str = "", stop_event=None) -> int:
        """认领一个 war3 窗口（多开隔离），返回 hwnd。

        协议：先拿全局认领锁 `Local\\GameBot_War3_Claim`（串行化整个认领过程，
        防止两脚本同时发 token/占用窗口互踩）→ 枚举窗口逐个尝试窗口锁（已被
        认领的直接跳过，不发 token）→ 配了 target_player 时向窗口发随机 token，
        OCR 聊天区"〔盟友〕玩家名：token"行提取归属名匹配；不匹配释放窗口锁换
        下一个。认领成功或本轮全部失败都释放全局锁，让其他脚本认领。

        认领成功后窗口互斥锁一直持有到进程退出（崩溃自动释放），
        self._claimed_hwnd / self.claimed_owner 记录结果，全链路只用该 hwnd。

        :param target_player: 目标玩家名；为空则认领第一个未被占用的窗口
        :param stop_event: 停止事件
        :return: 认领的窗口句柄，无可用窗口返回 0
        """
        if getattr(self, "_claimed_hwnd", 0):
            return self._claimed_hwnd
        mi_cfg = self.war3_cfg.get("multi_instance", {})
        claim_timeout = float(mi_cfg.get("claim_timeout", 60))
        retry_interval = float(mi_cfg.get("claim_retry_interval", 0.5))
        start = time.time()
        last_wins = 0
        while time.time() - start < claim_timeout:
            # 全局认领锁：整个扫描+验证过程串行，其他脚本排队等待
            claim_lock = NamedMutex("Local\\GameBot_War3_Claim")
            remaining_ms = int(max(0, claim_timeout - (time.time() - start)) * 1000)
            if not claim_lock.acquire(timeout_ms=remaining_ms):
                break  # 超时还没拿到全局锁，放弃
            try:
                wins = self.dm.find_windows(
                    self.war3_cfg.get("window_class", ""),
                    self.war3_cfg.get("window_title", ""),
                )
                if wins:
                    last_wins = len(wins)
                claimed = self._claim_one_pass(wins, target_player, stop_event)
            finally:
                claim_lock.release()
            if claimed:
                return claimed
            # 本轮没认领到（都被占用或不匹配），稍后重扫
            self.interruptible_wait(retry_interval, stop_event)
        logger.error(f"认领超时（{claim_timeout}s）：共 {last_wins} 个 war3 窗口，均已被占用或不匹配")
        return 0

    def _claim_one_pass(self, wins: list, target_player: str, stop_event=None) -> int:
        """单轮认领：在全局认领锁保护下逐个尝试窗口锁并验证归属。"""
        for w in wins:
            hwnd = w["hwnd"]
            mutex = NamedMutex(f"Local\\GameBot_War3_{hwnd}")
            if not mutex.try_acquire():
                logger.info(f"war3 窗口 {hwnd} 已被其他脚本认领，跳过")
                continue
            owner = ""
            if target_player:
                # 先统一客户区尺寸：chat_area_coords 按配置分辨率校准，
                # 尺寸不一致时 OCR 区域与真实聊天区错位，token 永远找不到
                self.set_client_size(hwnd)
                owner = self._identify_owner_by_chat(hwnd, stop_event)
                # 包含匹配：target_player 出现在"："左边的发送者段中即归属
                if not owner or target_player not in owner:
                    logger.info(
                        f"war3 窗口 {hwnd} 归属 {owner or '未知'}，与目标玩家 {target_player} 不匹配，释放"
                    )
                    mutex.release()
                    continue
            self._claimed_mutex = mutex
            self._claimed_hwnd = hwnd
            self.claimed_owner = owner
            logger.info(f"已认领 war3 窗口 hwnd={hwnd}" + (f"，归属玩家 {owner}" if owner else ""))
            return hwnd
        return 0

    def _identify_owner_by_chat(self, hwnd: int, stop_event=None) -> str:
        """向 hwnd 发送随机 token，OCR 聊天区匹配"玩家名：token"行，返回玩家名。

        token 进程级唯一（gb + pid16进制 + 随机hex），多开同图时广播到所有
        窗口但各自只搜自己的 token，不会错领。
        聊天行格式"玩家名：消息"，取 token 所在行分隔符前的文本为归属名。

        :return: 玩家名；token 未上屏/超时返回空字符串
        """
        mi_cfg = self.war3_cfg.get("multi_instance", {})
        area = mi_cfg.get("chat_area_coords")
        if not area:
            logger.warning("未配置 multi_instance.chat_area_coords，无法聊天识别归属")
            return ""
        # token = 前缀+pid+随机尾；校验只查 marker（前缀+pid）——
        # OCR 可能丢/错读 token 尾部字符，精确匹配整串会漏
        marker = f"{mi_cfg.get('token_prefix', 'gb')}{os.getpid():x}"
        token = f"{marker}{secrets.token_hex(2)}"
        retries = int(mi_cfg.get("send_retries", 3))
        verify_wait = float(mi_cfg.get("verify_wait", 1.0))
        for attempt in range(1, retries + 1):
            with self.dm.bind_window(hwnd, bind_cfg=self.war3_cfg.get("bind", {})):
                self.send_msg(token, stop_event=stop_event)
            self.interruptible_wait(verify_wait, stop_event)
            lines = self.ocr_lines(hwnd, {"area_coords": area})
            for line in lines:
                text = line.get("text", "").strip()
                if marker in text:
                    # 聊天行格式"〔盟友〕玩家名：消息"，返回 ： 左边的发送者段
                    for sep in ("：", ":"):
                        if sep in text:
                            return text.split(sep, 1)[0].strip()
                    return ""  # 找到 token 但无名字分隔符
            # 诊断：打出聊天区实际 OCR 内容，便于排查 token 未上屏原因
            seen = [line.get("text", "").strip() for line in lines if line.get("text", "").strip()]
            logger.debug(f"窗口 {hwnd} 第 {attempt}/{retries} 次 token 未上屏，聊天区 OCR: {seen}")
        return ""

    def find_game_window(self, capture: bool = True) -> int:
        """按绑定模式查找 war3 窗口句柄（任务入口统一走这里）。

        - 前台绑定（bind_foreground）：要求 war3 是活动窗口（真实键鼠输入需要前台焦点）。
        - 后台绑定（bind_background）：走多开认领协议（claim_war3_window），
          单开时同样生效（互斥锁即取即得），保证与其他脚本互不干扰。
        """
        if self.war3_cfg.get("bind", {}).get("bind_mode") != "background":
            return self.dm.get_active_window(
                self.war3_cfg["window_class"], self.war3_cfg["window_title"], capture=capture
            )
        return self.claim_war3_window(target_player=getattr(self, "target_player", ""))

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
            # 检查 War3 窗口是否还在（只判断窗口是否存在，后台模式下窗口本就不是前台）
            hwnd = self._find_war3_hwnd()
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

        lines = self.ocr_lines(hwnd, loading_cfg)
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
