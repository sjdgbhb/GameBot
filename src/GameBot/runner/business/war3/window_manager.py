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

from GameBot.config import resolve_bind_cfg
from GameBot.runner.business.claim import (
    claim_window,
    ensure_registered,
    player_matches,
    self_kk_pid,
)
from GameBot.runner.driver.claim_registry import parent_pid, window_pid
from GameBot.runner.driver.wgc_capture import WgcCapture
from GameBot.utils import WindowLostError, logger

_user32 = ctypes.windll.user32
_user32.IsWindow.argtypes = [wintypes.HWND]
_user32.IsWindow.restype = wintypes.BOOL
_user32.IsIconic.argtypes = [wintypes.HWND]
_user32.IsIconic.restype = wintypes.BOOL


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

    def claim_war3_window(
        self,
        target_player: str = "",
        stop_event=None,
        claim_timeout: float = None,
    ) -> int:
        """认领一个 war3 窗口（多开隔离），返回 hwnd；超时抛 ClaimError。

        协议（统一认领原语 claim_window）：枚举候选 → per-hwnd 互斥锁 →
        归属判定 `ppid(窗口进程) == 本账号 kk_pid`（Toolhelp32 直接父进程比对，
        纯只读、读图期零操作，任意游戏阶段可用）→ kk_pid 未知（游戏内启动且
        注册表未命中）时发聊天 token 自举，命中后由 ppid 推出 kk_pid 写注册表。

        认领成功后窗口互斥锁一直持有到显式释放或进程退出（崩溃自动释放），
        self._claimed_hwnd / self.claimed_owner 记录结果，全链路只用该 hwnd。
        多局任务每局新开 war3 窗口，须在局间调用 release_war3_claim 释放旧认领。

        :param target_player: 目标玩家名；为空则认领第一个未被占用的窗口
        :param stop_event: 停止事件
        :param claim_timeout: 认领总超时（秒），None 时用 multi_instance.claim_timeout
        :return: 认领的窗口句柄
        :raises ClaimError: 认领超时（任务须终止，归属未确认不可继续运行）
        """
        if getattr(self, "_claimed_hwnd", 0):
            if _user32.IsWindow(self._claimed_hwnd):
                return self._claimed_hwnd
            # 认领窗口已销毁（如上局结束 war3 退出），释放窗口锁重新认领
            self.release_war3_claim()
        reg = ensure_registered(self, self.war3_cfg, target_player)
        mi_cfg = self.war3_cfg.get("multi_instance", {})
        if claim_timeout is None:
            claim_timeout = float(mi_cfg.get("claim_timeout", 60))
        retry_interval = float(mi_cfg.get("claim_retry_interval", 0.5))
        kk_pid_box = [self_kk_pid(self, self.war3_cfg, target_player, reg=reg)]
        window_class = self.war3_cfg.get("window_class", "")
        window_title = self.war3_cfg.get("window_title", "")

        def _candidates() -> list:
            return [
                w["hwnd"]
                for w in self.dm.find_windows(window_class, window_title)
            ]

        def _resolve(hwnd: int):
            """war3 归属判定（只读）：窗口进程的直接父 PID 与本账号 kk_pid 比对。"""
            if not target_player:
                return True
            ppid = parent_pid(window_pid(hwnd))
            if not ppid:
                return None
            kk_pid = kk_pid_box[0]
            if kk_pid:
                # kk_pid 已知：归属判定是确定性的，不再落入 token 识别
                return ppid == kk_pid
            player = reg.player_of_kk_pid(ppid)
            if not player:
                return None
            return player_matches(player, target_player)

        def _identify(hwnd: int) -> bool:
            """war3 聊天 token 自举（仅游戏内启动、kk_pid 未知时触发）。"""
            owner = self._identify_owner_by_chat(hwnd, stop_event)
            if not owner:
                return False
            kk_pid = parent_pid(window_pid(hwnd))
            if kk_pid:
                reg.set_kk_owner(kk_pid, owner)
            if target_player and player_matches(owner, target_player):
                self._kk_pid = kk_pid_box[0] = kk_pid
                logger.info(f"war3 token 自举命中: hwnd={hwnd}，归属玩家 {owner}，kk_pid={kk_pid}")
                return True
            logger.info(f"war3 窗口 {hwnd} 归属 {owner}，与目标玩家 {target_player} 不匹配")
            return False

        hwnd, mutex = claim_window(
            kind="war3",
            candidates_fn=_candidates,
            mutex_prefix="Local\\GameBot_War3_",
            resolve_owner=_resolve,
            identify=_identify,
            timeout=claim_timeout,
            retry_interval=retry_interval,
            stop_event=stop_event,
            registry=reg,
        )
        self._claimed_mutex = mutex
        self._claimed_hwnd = hwnd
        self.claimed_owner = target_player
        logger.info(f"已认领 war3 窗口 hwnd={hwnd}" + (f"，归属玩家 {target_player}" if target_player else ""))
        return hwnd

    def release_war3_claim(self) -> None:
        """释放当前认领的 war3 窗口锁并清除缓存句柄/注册表窗口记录。

        多局任务每局新开 war3 窗口，局间调用以便下一轮认领新句柄；
        窗口锁按 hwnd 命名，仅影响本进程对该 hwnd 的占用标记。
        """
        hwnd = getattr(self, "_claimed_hwnd", 0)
        mutex = getattr(self, "_claimed_mutex", None)
        if mutex is not None:
            mutex.release()
        self._claimed_mutex = None
        self._claimed_hwnd = 0
        self.claimed_owner = ""
        if hwnd:
            try:
                from GameBot.runner.business.claim import get_registry

                get_registry(self, self.war3_cfg).release_window("war3", hwnd)
            except Exception as e:
                logger.debug(f"清理 war3 注册表记录失败: {e}")

    def _identify_owner_by_chat(self, hwnd: int, stop_event=None) -> str:
        """向 hwnd 发送随机 token，OCR 聊天区匹配"玩家名：token"行，返回玩家名。

        token 进程级唯一（gb + pid16进制 + 随机hex），跨进程不会串；
        但同进程逐窗识别时旧 token 行会残留在共享聊天区，故归属判定
        优先整串命中本次 token，退化取最下方（最新）的 marker 行。
        聊天行格式"玩家名：消息"，取 token 所在行分隔符前的文本为归属名。

        :return: 玩家名；token 未上屏/超时返回空字符串
        """
        mi_cfg = self.war3_cfg.get("multi_instance", {})
        area = mi_cfg.get("chat_area_coords")
        if not area:
            logger.warning("未配置 multi_instance.chat_area_coords，无法聊天识别归属")
            return ""
        # 聊天区坐标按配置分辨率校准，先统一客户区尺寸再绑定发 token
        self.set_client_size(hwnd)
        # token = 前缀+pid+随机尾；校验只查 marker（前缀+pid）——
        # OCR 可能丢/错读 token 尾部字符，精确匹配整串会漏
        marker = f"{mi_cfg.get('token_prefix', 'gb')}{os.getpid():x}"
        token = f"{marker}{secrets.token_hex(2)}"
        retries = int(mi_cfg.get("send_retries", 3))
        verify_wait = float(mi_cfg.get("verify_wait", 1.0))
        for attempt in range(1, retries + 1):
            with self.dm.bind_window(hwnd, bind_cfg=resolve_bind_cfg(self.war3_cfg)):
                self.send_msg(token, stop_event=stop_event)
            self.interruptible_wait(verify_wait, stop_event)
            lines = self.ocr_lines(hwnd, {"area_coords": area})
            # 多开同图时聊天广播共享：此前窗口发过的 marker 旧行会残留在聊天区，
            # 只查 marker 前缀取首个命中会错领归属——优先整串匹配本次 token，
            # OCR 丢/错读尾字符时退化为取最下方（最新）的 marker 行
            owner = None  # None=无 marker 行；""=有 marker 行但无名字分隔符
            for line in lines:
                text = line.get("text", "").strip()
                if marker not in text:
                    continue
                # 聊天行格式"〔盟友〕玩家名：消息"，取 ： 左边的发送者段
                sender = next((text.split(sep, 1)[0].strip() for sep in ("：", ":") if sep in text), "")
                if not sender:
                    # OCR 漏识别"："（如"善木木Vgbxx"连读）：取 marker 前的文本段兜底
                    compact = text.replace(" ", "")
                    pos = compact.find(marker)
                    if pos > 0:
                        sender = compact[:pos].strip("：: ")
                if token in text:
                    logger.debug(f"窗口 {hwnd} token 整串命中，归属行: {text}")
                    return sender
                owner = sender
            if owner is not None:
                logger.debug(f"窗口 {hwnd} 取最新 marker 行判定归属: {owner}")
                return owner
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
        if self.war3_cfg.get("bind_mode") != "background":
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

    def wait_enter_game(self, task, stop_event=None, hwnd: int = 0):
        """等待进入游戏，带超时和窗口消失检测。

        循环检测游戏内信号（is_in_game），检测到后记录 game_start_time。
        如果 War3 窗口消失则抛出 WindowLostError（掉线）。
        超时未进入则抛 TimeoutError（可能卡在加载界面）。

        :param task: 任务对象（需有 game_start_time / pet_feed_time 属性）
        :param stop_event: 停止事件，设置时中断等待
        :param hwnd: 非 0 时对指定窗口做无绑定 WGC 轮询（读图期等待进游戏用，
            全程不绑定/不触碰窗口）；为 0 时检测当前绑定窗口
        :raises WindowLostError: War3 窗口消失（掉线）
        :raises TimeoutError: 等待进入游戏超时（卡在加载界面）
        """
        detect_cfg = self.war3_cfg.get("in_game_detect", {})
        timeout = detect_cfg.get("timeout", 120)
        method = detect_cfg.get("method", "image")
        interval = self.war3_cfg.get("check_interval_time", 2)

        start = time.time()
        while time.time() - start < timeout:
            if method == "image" and self.is_in_game(hwnd):
                task.game_start_time = task.pet_feed_time = time.time()
                logger.info("已进入游戏")
                return
            # 检查 War3 窗口是否还在（只判断窗口是否存在，后台模式下窗口本就不是前台）
            alive = bool(_user32.IsWindow(hwnd)) if hwnd else bool(self._find_war3_hwnd())
            if not alive:
                logger.error("War3 窗口消失，可能掉线，已保存截图")
                self.dm.save_active_window_screenshot(label="war3_window_lost")
                raise WindowLostError("War3 窗口消失，可能掉线")
            self.interruptible_wait(interval, stop_event)
        raise TimeoutError(f"等待进入游戏超时（{timeout}s），可能卡在加载界面")

    def _size_tolerant_area(self, hwnd: int, area: list) -> list:
        """未统一尺寸的窗口按"实际-校准"客户区尺寸差外扩检测区域。

        读图期不允许改尺寸，但检测区域按校准分辨率标定——外扩保证锚点位移后
        目标仍落在区域内（找图/OCR 都是区域内识别，非定点比对，外扩无副作用）。
        """
        try:
            cw, ch = WgcCapture.for_hwnd(hwnd).client_size()
        except Exception:
            return list(area)  # 取不到实际尺寸（窗口将死/无帧）时按原样返回
        ew, eh = self.war3_cfg.get("client_size", [cw, ch])
        mx, my = abs(cw - ew) + 8, abs(ch - eh) + 8
        return [max(0, area[0] - mx), max(0, area[1] - my), min(cw, area[2] + mx), min(ch, area[3] + my)]

    def is_in_game(self, hwnd: int = 0):
        """
        是否处于游戏内
        :param hwnd: 非 0 时对指定窗口做 WGC 找图（无需绑定，可用于读图期/认领前检测）；
            为 0 时检测当前绑定窗口
        :return:
        """
        area = list(self.war3_cfg["mini_map_signal_area_coords"])
        if hwnd:
            area = self._size_tolerant_area(hwnd, area)
        index, x, y = self.dm.find_pic(
            *area,
            self.war3_cfg["mini_map_signal_img"],
            self.war3_cfg["mini_map_signal_sim"],
            self.war3_cfg["mini_map_signal_delta_color"],
            hwnd=hwnd,
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


