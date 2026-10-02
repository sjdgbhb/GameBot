"""KK 多开识别 mixin — 大厅玩家 ID 识别、房间认领。

多开归属模型（注册表 + PID 匹配，详见 openspec/changes/refactor-window-claim）：
- `player → kk_pid` 映射共享在机器级注册表，一次识别全员复用；
- KK 侧窗口归属判定 = `窗口 PID == 本账号 kk_pid`（只读）；
- kk_pid 未知时场景化自举：房间启动发聊天 token，大厅启动走下拉框 OCR，
  自举成功写 `kk_owner` 反哺注册表。
"""

from __future__ import annotations

import ctypes
import os
import secrets
import time
from contextlib import contextmanager
from ctypes import wintypes
from typing import TYPE_CHECKING, Optional, cast

from GameBot.config import resolve_bind_cfg
from GameBot.runner.business.claim import (
    claim_window,
    ensure_registered,
    player_matches,
    self_kk_pid,
)
from GameBot.runner.driver.claim_registry import window_pid
from GameBot.utils import StopTaskError, logger

if TYPE_CHECKING:
    from GameBot.runner.business.kk import KKBusiness  # 跨 mixin 方法跳转用，避免运行时循环导入
    from GameBot.runner.driver.base import DmClientBase as DmClient


class MultiInstanceMixin:
    """KK 多开识别 mixin。依赖 self.kk_cfg（dict）。"""

    # ── 房间窗口认领 ──────────────────────────────────────────

    def claim_room_window(
        self,
        dm: DmClient,
        target_player: str,
        stop_event=None,
        claim_timeout: float = None,
    ) -> tuple[int, int]:
        """认领属于 target_player 的 KK 房间窗口，返回 (room_hwnd, kk_pid)。

        协议（统一认领原语 claim_window）：枚举房间候选 → per-hwnd 互斥锁 →
        归属判定（窗口 PID == 本账号 kk_pid / 注册表 kk_owner 反查）→
        kk_pid 未知时房间聊天 token 自举并写注册表 → 匹配持锁，超时抛 ClaimError。

        认领成功后窗口互斥锁持有到 release_room_claim 或进程退出（崩溃自动释放），
        self._claimed_room_hwnd / _claimed_room_pid 记录结果，复用时校验存活。

        :param target_player: 目标玩家 ID；为空则认领第一个未被占用的房间窗口
        :param stop_event: 停止事件
        :param claim_timeout: 认领总超时（秒），None 时用 multi_instance.claim_timeout
        :return: (房间句柄, 本账号 KK 进程 PID)
        :raises ClaimError: 认领超时（任务须终止，归属未确认不可继续运行）
        """
        if getattr(self, "_claimed_room_hwnd", 0):
            hwnd = self._claimed_room_hwnd
            pid = getattr(self, "_claimed_room_pid", 0)
            # 窗口存活且 PID 未变时复用认领；查询失败/PID 为 0 说明窗口已销毁
            if pid and window_pid(hwnd) == pid:
                return hwnd, pid
            # 认领窗口已销毁（掉线/被踢出房间），释放窗口锁重新认领
            self.release_room_claim()

        reg = ensure_registered(self, self.kk_cfg, target_player)
        mi_cfg = self.kk_cfg.get("multi_instance", {})
        if claim_timeout is None:
            claim_timeout = float(mi_cfg.get("claim_timeout", 60))
        retry_interval = float(mi_cfg.get("claim_retry_interval", 0.5))
        window_class = self.kk_cfg.get("window_class", "")
        window_title = self.kk_cfg.get("window_title", "")
        room_size = tuple(self.kk_cfg.get("room", {}).get("window_size", [1224, 904]))
        kk_pid_box = [self_kk_pid(self, self.kk_cfg, target_player, reg=reg)]
        # self 运行时实为 KKBusiness（各 mixin 组合体），cast 供 IDE 解析跨 mixin 方法
        kk = cast("KKBusiness", self)

        def _candidates() -> list:
            wins = []
            for w in dm.find_windows(window_class, window_title):
                hwnd = w["hwnd"]
                # 枚举到认领存在间隙，房间窗口可能已关闭——此时跳过该窗口
                if not dm.get_window_state(hwnd, 0):
                    continue
                if not kk._check_room_window(dm, hwnd):
                    continue
                wins.append(hwnd)
            return wins

        def _resolve(hwnd: int):
            if not target_player:
                return True
            pid = window_pid(hwnd)
            if not pid:
                return None
            if kk_pid_box[0]:
                # kk_pid 已知：归属判定是确定性的，不再落入 token 识别
                return pid == kk_pid_box[0]
            player = reg.player_of_kk_pid(pid)
            if not player:
                return None
            return player_matches(player, target_player)

        def _identify(hwnd: int) -> bool:
            """房间聊天 token 自举：识别归属写 kk_owner，命中则推出本账号 kk_pid。"""
            # 先统一客户区尺寸：聊天坐标按 room.window_size 校准
            try:
                dm.set_client_size(hwnd, room_size[0], room_size[1])
            except Exception as e:
                logger.info(f"KK 房间窗口 {hwnd} 已失效（{e}），跳过")
                return False
            owner = self._identify_room_owner_by_chat(dm, hwnd, stop_event)
            if not owner:
                return False
            pid = window_pid(hwnd)
            if pid:
                reg.set_kk_owner(pid, owner)
            if target_player and player_matches(owner, target_player):
                self._kk_pid = kk_pid_box[0] = pid
                logger.info(f"房间 token 自举命中: hwnd={hwnd}，归属玩家 {owner}，kk_pid={pid}")
                return True
            logger.info(f"KK 房间窗口 {hwnd} 归属 {owner}，与目标玩家 {target_player} 不匹配")
            return False

        hwnd, mutex = claim_window(
            kind="kk_room",
            candidates_fn=_candidates,
            mutex_prefix="Local\\GameBot_KK_Room_",
            resolve_owner=_resolve,
            identify=_identify,
            timeout=claim_timeout,
            retry_interval=retry_interval,
            stop_event=stop_event,
            registry=reg,
        )
        pid = window_pid(hwnd)
        self._claimed_room_mutex = mutex
        self._claimed_room_hwnd = hwnd
        self._claimed_room_pid = pid
        if pid:
            self._kk_pid = pid
            if target_player:
                # 快速路径/空映射场景下补写归属映射，供 war3 侧认领与其他实例复用
                reg.set_kk_owner(pid, target_player)
        return hwnd, pid

    def claim_own_room(self, dm: DmClient, target_player: str, stop_event=None) -> tuple[int, int]:
        """认领本账号 KK 房间窗口并缓存句柄（认领失败抛 ClaimError 语义内建）。

        :return: (room_hwnd, kk_pid)；kk_pid 供任务层按 PID 过滤弹窗/掉线
        """
        return self.claim_room_window(dm, target_player, stop_event=stop_event)

    def release_room_claim(self) -> None:
        """释放当前认领的 KK 房间窗口锁并清除缓存句柄/注册表窗口记录。"""
        hwnd = getattr(self, "_claimed_room_hwnd", 0)
        mutex = getattr(self, "_claimed_room_mutex", None)
        if mutex is not None:
            mutex.release()
        self._claimed_room_mutex = None
        self._claimed_room_hwnd = 0
        self._claimed_room_pid = 0
        if hwnd:
            try:
                from GameBot.runner.business.claim import get_registry

                get_registry(self, self.kk_cfg).release_window("kk_room", hwnd)
            except Exception as e:
                logger.debug(f"清理 KK 房间注册表记录失败: {e}")

    def _identify_room_owner_by_chat(self, dm: DmClient, hwnd: int, stop_event=None) -> str:
        """向 KK 房间聊天输入框发送随机 token，OCR 聊天记录区提取归属玩家名。

        token = 前缀+本进程 PID(hex)+随机尾缀：不同脚本报文不同，OCR 只认自己的
        marker，不受对方脚本发到本窗口的 token 干扰；取"："左边的发送者段为归属名。
        输入框常驻无需开聊天框；聊天命令仅 ASCII，send_string 够用。

        防刷屏：发送前先查聊天记录——本进程 marker 已上屏则直接解析归属，不再
        重发；发送后**每窗口每轮最多发 1 次 token**：消息渲染上屏有延迟，
        未读到 marker 时重发只会重复灌入聊天（上一轮发的可能晚到），后续只做
        重读验证；仍读不到返回 "" 由认领轮次重试（重试先查 marker，不发新 token）。

        :return: 发送者玩家名，未上屏/无归属返回 ""
        """
        mi_cfg = self.kk_cfg.get("multi_instance", {})
        input_rect = mi_cfg.get("room_chat_input_coords")
        log_area = mi_cfg.get("room_chat_log_area_coords")
        if not input_rect or not log_area:
            logger.warning("kk.multi_instance 未配置房间聊天坐标，无法识别房间归属")
            return ""
        marker = f"{mi_cfg.get('token_prefix', 'gb')}{os.getpid():x}"
        retries = int(mi_cfg.get("send_retries", 3))
        verify_wait = float(mi_cfg.get("verify_wait", 1.0))
        click_x = (input_rect[0] + input_rect[2]) // 2
        click_y = (input_rect[1] + input_rect[3]) // 2

        def _sleep(sec: float) -> None:
            if stop_event is not None:
                if stop_event.wait(sec):
                    raise StopTaskError("用户请求停止任务")
            else:
                time.sleep(sec)

        # 先查聊天记录：本进程 marker 已上屏则直接进入归属名解析，不发新 token
        dm.force_refresh_layered(hwnd)
        saw_marker, owner = self._find_marker_owner(
            cast("KKBusiness", self).ocr_kk_lines(hwnd, {"area_coords": log_area}), marker
        )
        if not saw_marker:
            # 每窗口每轮最多发 1 次：发送后只做重读验证，未上屏返回 "" 由
            # 认领轮次重试（重试先查 marker，不再重复发 token）
            token = marker + secrets.token_hex(2)
            with dm.bind_window(hwnd, bind_cfg=resolve_bind_cfg(self.kk_cfg)):
                dm.move_to(click_x, click_y)
                time.sleep(0.3)
                dm.left_click()
                time.sleep(0.2)
                dm.key_press_char("ctrl+a")  # 清掉输入框残留内容
                dm.send_string(token, hwnd=hwnd)
                time.sleep(0.2)
                dm.key_press_char("enter")  # 发送到房间聊天
            # token 一般秒上屏，发送后尽快首读吃常见快路径；
            # 偶发服务器回显慢（实测可超 10s）靠重读窗口覆盖
            for _ in range(retries):
                _sleep(verify_wait)
                # layered 窗口后台输入后画面不刷新，须在 bind 之外刷新再 OCR
                dm.force_refresh_layered(hwnd)
                saw_marker, owner = self._find_marker_owner(
                    cast("KKBusiness", self).ocr_kk_lines(hwnd, {"area_coords": log_area}), marker
                )
                if saw_marker:
                    break
                logger.debug(f"KK 房间窗口 {hwnd} 聊天记录未上屏 token {token}，重读")
            if not saw_marker:
                return ""

        # marker 已上屏但归属名未解析出（OCR 抖动/拆行）：重截屏重试，不再发 token
        for _ in range(retries):
            if owner:
                return owner
            _sleep(verify_wait)
            dm.force_refresh_layered(hwnd)
            saw_marker, owner = self._find_marker_owner(
                cast("KKBusiness", self).ocr_kk_lines(hwnd, {"area_coords": log_area}), marker
            )
        return owner

    @staticmethod
    def _find_marker_owner(lines: list, marker: str) -> tuple[bool, str]:
        """在 OCR 行列表中查找本进程 marker，提取发送者归属名。

        遍历所有 marker 行，取第一条能解析出归属名的；marker 行无"："分隔符或
        发送者段为空时回看上一行（"玩家名："与消息可能被 OCR 拆成两行）。

        :param lines: ocr_kk_lines 返回的行列表
        :param marker: 本进程 token 前缀（token_prefix + PID hex）
        :return: (是否见到 marker, 归属名)；见到 marker 但归属名解析失败返回空串
        """
        saw_marker = False
        for i, line in enumerate(lines):
            text = line.get("text", "").strip()
            # OCR 可能在 token 中间读出空格导致子串匹配漏判，去空格再比 marker
            if marker not in text.replace(" ", ""):
                continue
            saw_marker = True
            sender = ""
            for sep in ("：", ":"):
                if sep in text:
                    sender = text.split(sep, 1)[0].strip()
                    break
            if not sender:
                # OCR 漏识别"："分隔符（如"岁月神偷Vgbxx"连读）：取 marker 前的文本段兜底
                compact = text.replace(" ", "")
                pos = compact.find(marker)
                if pos > 0:
                    sender = compact[:pos].strip("：: ")
            if not sender and i > 0:
                prev = lines[i - 1].get("text", "").strip()
                for sep in ("：", ":"):
                    if prev.endswith(sep):
                        sender = prev[: -len(sep)].strip()
                        break
            if sender:
                return True, sender
            logger.debug(f"KK 房间窗口 token 行未解析出归属名: {text}")
        return saw_marker, ""


    @contextmanager
    def _pid_identify_lock(self, pid: int, stop_event=None):
        """按 KK 进程 PID 串行化玩家 ID 下拉框操作。"""
        kernel32 = ctypes.windll.kernel32
        kernel32.CreateMutexW.restype = wintypes.HANDLE
        kernel32.CreateMutexW.argtypes = [
            ctypes.c_void_p,
            wintypes.BOOL,
            wintypes.LPCWSTR,
        ]
        kernel32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
        kernel32.ReleaseMutex.argtypes = [wintypes.HANDLE]
        kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
        mutex_name = f"Local\\GameBot_KK_Hall_Identify_PID_{int(pid)}"
        handle = kernel32.CreateMutexW(None, False, mutex_name)
        if not handle:
            raise OSError("创建 KK 大厅 PID 识别互斥锁失败")
        if stop_event and stop_event.is_set():
            kernel32.CloseHandle(handle)
            raise StopTaskError("停止 KK 大厅玩家 ID 识别")
        result = kernel32.WaitForSingleObject(handle, 0)
        if result == 0x102:
            kernel32.CloseHandle(handle)
            yield False
            return
        if result not in (0, 0x80):
            kernel32.CloseHandle(handle)
            raise OSError(f"获取 KK 大厅 PID 识别互斥锁失败: {result}")
        try:
            yield True
        finally:
            kernel32.ReleaseMutex(handle)
            kernel32.CloseHandle(handle)

    def identify_hall_owner(
        self,
        dm: DmClient,
        hall_hwnd: int,
        stop_event=None,
    ) -> Optional[str]:
        """通过点击头像弹出下拉框，对下拉框窗口 OCR 识别 KK 主界面窗口的玩家 ID。

        流程：记录点击前下拉框快照 → 绑定大厅 → 点击头像 → 解绑大厅 →
              找点击后新出现的下拉框（优先父/属主窗口为当前大厅的）→
              绑定下拉框 OCR → ESC 关闭。

        多开下若多个 KK 大厅属于同一 PID，旧实现直接取 Z 序最上层的下拉框，
        会误读其他大厅弹出的下拉框。此处通过"before/after 差分"配合
        父窗口校验，确保只读取本次点击所属于 hall_hwnd 的下拉框。

        同一 KK PID 使用互斥锁串行操作，不同 PID 可并行识别。

        :param hall_hwnd: 主界面窗口句柄
        :return: 玩家 ID；OCR 为空返回空字符串，窗口正忙（互斥锁冲突）返回 None
        """
        main_cfg = self.kk_cfg.get("main", {})
        main_size = tuple(main_cfg.get("window_size", [1328, 945]))
        dropdown_wait = main_cfg.get("dropdown_wait_time", 1)
        # 下拉框完整类名从 [kk] 配置读取
        dropdown_class = self.kk_cfg.get("dropdown_window_class", "")
        window_title = self.kk_cfg.get("window_title", "")
        pid = dm.get_window_process_id(hall_hwnd)

        with self._pid_identify_lock(pid, stop_event=stop_event) as acquired:
            if not acquired:
                return None
            if stop_event and stop_event.is_set():
                raise StopTaskError("停止 KK 大厅玩家 ID 识别")

            # 点击前先记录已有下拉框，避免把其他大厅残留/其他进程刚弹出的框当成本次结果
            before_candidates = dm.find_windows(dropdown_class, window_title, pid)
            before_hwnds = {w["hwnd"] for w in before_candidates}

            # 绑定大厅窗口，点击头像展开下拉框
            dm.set_client_size(hall_hwnd, *main_size)
            with dm.bind_window(hall_hwnd, bind_cfg=resolve_bind_cfg(self.kk_cfg)):
                dm.move_to(*main_cfg["profile_icon_coords"])
                if stop_event:
                    if stop_event.wait(0.3):
                        raise StopTaskError("停止 KK 大厅玩家 ID 识别")
                else:
                    time.sleep(0.3)
                dm.left_click()
                if stop_event and stop_event.wait(dropdown_wait):
                    dm.key_press_char("esc")
                    raise StopTaskError("停止 KK 大厅玩家 ID 识别")
                if not stop_event:
                    time.sleep(dropdown_wait)

            # 大厅已解绑，按 PID + 完整类名 + 标题 + 父/属主窗口找本次点击产生的下拉框
            dropdown = None
            after_candidates = dm.find_windows(dropdown_class, window_title, pid)
            new_candidates = [w for w in after_candidates if w["hwnd"] not in before_hwnds]

            if new_candidates:
                # 在新弹出的下拉框中，优先父/属主窗口是当前大厅的
                for w in new_candidates:
                    if dm.get_window_parent(w["hwnd"]) == hall_hwnd:
                        dropdown = w
                        break
                if dropdown is None:
                    # 没有命中父/属主窗口，按 Z 序取第一个新弹出的下拉框兜底
                    dropdown = new_candidates[0]
            else:
                # 未观察到新下拉框（可能与点击前已有），兜底：优先父/属主是当前大厅的
                for w in after_candidates:
                    if dm.get_window_parent(w["hwnd"]) == hall_hwnd:
                        dropdown = w
                        break
                if dropdown is None and after_candidates:
                    dropdown = after_candidates[0]

            if not dropdown:
                logger.warning(f"KK 主界面窗口 {hall_hwnd} 点击头像后未检测到下拉框窗口")
                with dm.bind_window(hall_hwnd, bind_cfg=resolve_bind_cfg(self.kk_cfg)):
                    dm.key_press_char("esc")
                return ""

            dd_hwnd = dropdown["hwnd"]
            # 优先用 get_client_rect 获取尺寸（find_windows 的 rect 来自 get_window_rect，
            # 在 bridge 模式下可能返回 0）
            try:
                dd_cr = dm.get_client_rect(dd_hwnd)
                dd_w = dd_cr[2] - dd_cr[0]
                dd_h = dd_cr[3] - dd_cr[1]
            except Exception:
                dd_rect = dropdown["rect"]
                dd_w = dd_rect[2] - dd_rect[0]
                dd_h = dd_rect[3] - dd_rect[1]

            # 若配置了基准尺寸，先统一下拉框客户区尺寸
            dropdown_cfg = self.kk_cfg.get("dropdown", {})
            dropdown_size = dropdown_cfg.get("window_size")
            if dropdown_size and len(dropdown_size) >= 2 and dropdown_size[0] > 0 and dropdown_size[1] > 0:
                try:
                    dm.set_client_size(dd_hwnd, *dropdown_size)
                    logger.info(f"下拉框已统一尺寸: {dropdown_size}")
                    x1, y1, x2, y2 = dm.get_client_rect(dd_hwnd)
                    dd_w, dd_h = x2 - x1, y2 - y1
                except Exception as e:
                    logger.warning(f"设置下拉框尺寸失败: {e}")

            logger.debug(f"大厅下拉框定位: hall_hwnd={hall_hwnd}, dropdown_hwnd={dd_hwnd}, size=({dd_w}x{dd_h})")

            # 绑定下拉框窗口做 OCR，OCR 完成后在同一上下文内 ESC 关闭
            owner = ""
            with dm.bind_window(dd_hwnd, bind_cfg=resolve_bind_cfg(self.kk_cfg)):
                lines = self.ocr_lines(
                    dd_hwnd,
                    {"area_coords": [0, 0, dd_w, dd_h]},
                )
                for line in lines:
                    text = line.get("text", "").strip()
                    if text:
                        owner = text
                        break
                if not owner:
                    all_texts = [ln.get("text", "").strip() for ln in lines if ln.get("text", "").strip()]
                    logger.warning(f"下拉框窗口 {dd_hwnd} OCR 为空，所有文本: {all_texts}")
                dm.key_press_char("esc")

            if owner:
                logger.info(f"大厅归属 OCR: hwnd={hall_hwnd}, pid={pid}, owner={owner}")
            return owner
