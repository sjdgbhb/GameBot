"""KK 主界面管理 mixin — 主界面弹窗清理、自动创建房间。

包含 HallManagerMixin：dismiss_hall_popups、create_room 及辅助方法。
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, Optional, Set

from GameBot.utils import StopTaskError, logger

if TYPE_CHECKING:
    from GameBot.runner.driver.base import DmClientBase as DmClient


def _longest_common_substring_len(s1: str, s2: str) -> int:
    """计算两个字符串的最长连续公共子串长度。

    用于 OCR 模糊匹配：OCR 可能漏字，但连续子串匹配比散落字符匹配更准确。
    """
    if not s1 or not s2:
        return 0
    m, n = len(s1), len(s2)
    # 滚动数组优化空间
    prev = [0] * (n + 1)
    best = 0
    for i in range(1, m + 1):
        curr = [0] * (n + 1)
        for j in range(1, n + 1):
            if s1[i - 1] == s2[j - 1]:
                curr[j] = prev[j - 1] + 1
                if curr[j] > best:
                    best = curr[j]
        prev = curr
    return best


class HallManagerMixin:
    """KK 主界面操作 mixin。依赖 self.dm（DmClient）和 self.kk_cfg（dict）。"""

    def dismiss_hall_popups(
        self,
        dm: DmClient,
        exclude_hwnds: Optional[Set[int]] = None,
        owner_pid: int = 0,
    ) -> None:
        """扫描并关闭 KK 主界面中的非目标弹窗，循环直到无可关闭弹窗。

        必须在未绑定任何窗口的状态下调用（close_window_by_x 内部会自行绑定弹窗）。

        :param exclude_hwnds: 需要保留的窗口句柄集合（如创建房间弹窗），不关闭。
                              默认为空集合。
        :param owner_pid: 所属 KK 进程 PID，多开时传入以避免关闭其他账号弹窗。
        """
        if exclude_hwnds is None:
            exclude_hwnds = set()
        popup_cfg = self.kk_cfg.get("popup", {})
        offset_x, offset_y = popup_cfg.get("close_offset", [15, 15])
        protected_keywords = popup_cfg.get("protected_keywords", [])
        popup_class = self.kk_cfg.get("create_room_window_class", "")
        min_width, min_height = self.kk_cfg.get("min_business_window_size", [200, 200])
        attempted_hwnds = set()

        max_rounds = 10  # 防止无限循环
        window_title = self.kk_cfg.get("window_title", "")
        for round_idx in range(max_rounds):
            closed_any = False
            if not popup_class:
                break
            for w in dm.find_windows(popup_class, window_title, owner_pid):
                hwnd = w["hwnd"]
                if hwnd in exclude_hwnds or hwnd in attempted_hwnds:
                    continue
                try:
                    x1, y1, x2, y2 = dm.get_client_rect(hwnd)
                    if x2 - x1 < min_width or y2 - y1 < min_height:
                        continue
                    lines = self.ocr_kk_lines(
                        dm,
                        hwnd,
                        {"area_coords": [0, 0, x2 - x1, y2 - y1]},
                    )
                except Exception as e:
                    logger.debug(f"识别 KK 弹窗 {hwnd} 失败: {e}")
                    continue

                all_text = " ".join(line.get("text", "") for line in lines)
                if any(keyword in all_text for keyword in protected_keywords):
                    logger.debug(f"窗口 {hwnd} 含保护关键词，跳过关闭: {all_text}")
                    continue

                attempted_hwnds.add(hwnd)
                logger.warning(f"检测到 KK 弹窗: hwnd={hwnd}，尝试关闭")
                if dm.close_window_by_x(hwnd, offset_x, offset_y):
                    time.sleep(0.3)
                    closed_any = True
                    break
            if not closed_any:
                break
        if round_idx > 0:
            logger.info(f"KK 弹窗清理完成，共清理 {round_idx} 轮")

    def claim_hall_window(
        self,
        dm: DmClient,
        target_player: str,
        stop_event=None,
        hall_owner_cache=None,
        busy_retry: int = 3,
        busy_wait: float = 2.0,
    ) -> tuple[int, int]:
        """多开场景下认领属于 target_player 的 KK 大厅窗口。

        枚举所有候选大厅窗口，逐个 OCR 识别玩家 ID，匹配后返回 (hwnd, pid)。
        认领前会先恢复最小化窗口并清理同 PID 下的 KK 弹窗，避免玩家名区域被遮挡。

        通过 IPC 共享所有非空 OCR 归属。任一进程识别窗口 K1 后立即写入缓存，
        其他进程枚举到 K1 时直接读取归属，省去重复点击头像和 OCR。

        多开并发时，identify_hall_owner 按 KK PID 串行下拉框操作与 OCR；不同 PID
        可并行识别。互斥锁冲突时返回 None，先跳过该窗口继续遍历其他窗口，
        第一轮结束后再回头重试被跳过的窗口。

        :param target_player: 目标玩家 ID
        :param hall_owner_cache: TeamIPC 实例，用于共享已认领窗口信息
        :param busy_retry: 被跳过的正忙窗口的重试轮数
        :param busy_wait: 每轮重试间隔秒数
        :return: (大厅句柄, 进程 PID)，未找到返回 (0, 0)
        """
        window_class = self.kk_cfg.get("window_class", "")
        min_width, min_height = self.kk_cfg.get("min_business_window_size", [200, 200])
        if not window_class:
            return 0, 0

        # 本地缓存：实例属性，跨 claim_hall_window 调用保留，避免重复 OCR 同一窗口
        # 非空结果永久缓存；空结果记录重试次数，超过上限不再重试
        local_cache = getattr(self, "_hall_owner_cache", None)
        if local_cache is None:
            local_cache = self._hall_owner_cache = {}
        # 空结果重试计数：记录每个窗口 OCR 失败次数
        empty_retry_counts = getattr(self, "_hall_empty_retry_counts", None)
        if empty_retry_counts is None:
            empty_retry_counts = self._hall_empty_retry_counts = {}
        max_empty_retries = self.kk_cfg.get("max_hall_owner_empty_retries", 2)
        busy_hwnds: list[int] = []  # 被跳过的正忙窗口

        def _try_identify(hwnd: int, pid: int) -> Optional[str]:
            """识别单个窗口的归属玩家，返回 None 表示窗口正忙需稍后重试。"""
            if stop_event and stop_event.is_set():
                raise StopTaskError("停止 KK 大厅窗口认领")
            # 本地缓存命中（非空结果）：直接返回，跳过点击 OCR
            if hwnd in local_cache:
                return local_cache[hwnd]
            # 空结果重试耗尽：不再点击 OCR，直接返回空字符串
            if empty_retry_counts.get(hwnd, 0) >= max_empty_retries:
                return ""
            # IPC 缓存命中：直接返回，跳过点击 OCR
            if hall_owner_cache:
                cached_owner = hall_owner_cache.read_hall_owner(hwnd, pid)
                if cached_owner:
                    local_cache[hwnd] = cached_owner
                    logger.info(f"大厅归属共享缓存命中: hwnd={hwnd}, pid={pid}, owner={cached_owner}")
                    return cached_owner
            self.dismiss_hall_popups(dm, exclude_hwnds={hwnd}, owner_pid=pid)
            owner = self.identify_hall_owner(
                dm,
                hwnd,
                stop_event=stop_event,
                hall_owner_cache=hall_owner_cache,
            )
            if owner is None:
                return None  # 正忙，稍后重试
            if owner:
                local_cache[hwnd] = owner
            else:
                # 空结果：记录重试次数，超过上限不再重试
                empty_retry_counts[hwnd] = empty_retry_counts.get(hwnd, 0) + 1
                if empty_retry_counts[hwnd] >= max_empty_retries:
                    logger.warning(f"KK 大厅窗口 {hwnd} OCR 空结果已达 {max_empty_retries} 次，不再重试")
            return owner

        def _check_match(owner: str, pid: int, hwnd: int) -> bool:
            """检查 owner 是否匹配 target_player。"""
            normalized_owner = "".join(owner.split()).casefold()
            normalized_target = "".join(target_player.split()).casefold()
            if normalized_target and (
                normalized_owner == normalized_target or normalized_owner.startswith(normalized_target)
            ):
                logger.info(f"认领大厅成功: target={target_player}, hwnd={hwnd}, pid={pid}, owner={owner}")
                return True
            return False

        # 第一轮：按 PID + 类名 + 标题枚举所有窗口，先跳过正忙的，识别其他窗口
        window_title = self.kk_cfg.get("window_title", "")
        for w in dm.find_windows(window_class, window_title, 0):
            hwnd = w["hwnd"]
            if stop_event and stop_event.is_set():
                raise StopTaskError("停止 KK 大厅窗口认领")
            try:
                x1, y1, x2, y2 = dm.get_client_rect(hwnd)
                if x2 - x1 < min_width or y2 - y1 < min_height:
                    continue
                # 排除房间窗口：KK 大厅和房间类名/标题相同，房间窗口点击头像无下拉框
                if self._is_room_window(dm, hwnd):
                    logger.debug(f"跳过房间窗口: hwnd={hwnd}")
                    continue
                pid = dm.get_window_process_id(hwnd)
                if dm.is_window_minimized(hwnd):
                    logger.warning(f"KK 大厅窗口 {hwnd} 处于最小化，尝试无激活恢复")
                    dm.set_window_state(hwnd, 5)
                    if stop_event:
                        if stop_event.wait(0.5):
                            raise StopTaskError("停止 KK 大厅窗口认领")
                    else:
                        time.sleep(0.5)
                owner = _try_identify(hwnd, pid)
                if owner is None:
                    # 窗口正忙，先跳过，留待后续轮次重试
                    busy_hwnds.append(hwnd)
                    continue
                if _check_match(owner, pid, hwnd):
                    return hwnd, pid
            except StopTaskError:
                raise
            except Exception as e:
                logger.warning(f"识别 KK 大厅窗口 {hwnd} 失败: {e}")
                continue

        # 后续轮次：重试被跳过的正忙窗口
        for round_idx in range(busy_retry):
            if not busy_hwnds:
                break
            if stop_event and stop_event.is_set():
                raise StopTaskError("停止 KK 大厅窗口认领")
            logger.debug(f"重试繁忙大厅: hwnds={busy_hwnds}, attempt={round_idx + 1}/{busy_retry}, wait={busy_wait}s")
            if stop_event:
                if stop_event.wait(busy_wait):
                    raise StopTaskError("停止 KK 大厅窗口认领")
            else:
                time.sleep(busy_wait)
            still_busy: list[int] = []
            for hwnd in busy_hwnds:
                if stop_event and stop_event.is_set():
                    raise StopTaskError("停止 KK 大厅窗口认领")
                pid = dm.get_window_process_id(hwnd)
                try:
                    owner = _try_identify(hwnd, pid)
                except StopTaskError:
                    raise
                except Exception as e:
                    logger.warning(f"重试识别 KK 大厅窗口 {hwnd} 失败: {e}")
                    continue
                if owner is None:
                    still_busy.append(hwnd)
                    continue
                if _check_match(owner, pid, hwnd):
                    return hwnd, pid
            busy_hwnds = still_busy

        if busy_hwnds:
            logger.debug(f"大厅认领本轮未完成: target={target_player}, busy_hwnds={busy_hwnds}")
        else:
            logger.debug(f"大厅认领本轮未匹配: target={target_player}")
        return 0, 0

    def _find_hall_hwnd(self, dm: DmClient, target_player: str = "", owner_pid: int = 0) -> int:
        """按 PID + 类名 + 标题枚举 KK 大厅窗口，排除房间窗口。

        KK 大厅和房间的类名、标题相同，通过 OCR 房间按钮关键词区分：
        房间窗口含"开始游戏"/"准备"等按钮文本，大厅窗口不含。

        :param target_player: 目标玩家 ID，提供时优先通过 claim_hall_window 精确认领。
        :param owner_pid: 目标进程 PID，>0 时只枚举该进程的窗口；0 表示单开不过滤。
        """
        if target_player:
            hwnd, pid = self.claim_hall_window(dm, target_player)
            if hwnd and (not owner_pid or pid == owner_pid):
                return hwnd

        main_cfg = self.kk_cfg.get("main", {})
        main_size = tuple(main_cfg.get("window_size", [1328, 945]))
        window_class = self.kk_cfg.get("window_class", "")
        window_title = self.kk_cfg.get("window_title", "")
        min_width, min_height = self.kk_cfg.get("min_business_window_size", [200, 200])
        if not window_class:
            return 0
        for w in dm.find_windows(window_class, window_title, owner_pid):
            hwnd = w["hwnd"]
            try:
                x1, y1, x2, y2 = dm.get_client_rect(hwnd)
                if x2 - x1 < min_width or y2 - y1 < min_height:
                    continue
                # 排除房间窗口：大厅和房间类名/标题相同，用房间按钮关键词区分
                if self._is_room_window(dm, hwnd):
                    continue
                dm.set_client_size(hwnd, *main_size)
                return hwnd
            except Exception:
                continue
        return 0

    def _is_room_window(self, dm: DmClient, hwnd: int) -> bool:
        """检查窗口是否为 KK 房间窗口（含"开始游戏"/"准备"等按钮文本）。"""
        room_cfg = self.kk_cfg.get("room", {})
        ocr_area = room_cfg.get("start_button_ocr_area_coords", [0, 0, 0, 0])
        if ocr_area == [0, 0, 0, 0]:
            return False
        room_size = tuple(room_cfg.get("window_size", [1224, 904]))
        keywords = {
            room_cfg.get("start_game_keyword", "开始游戏"),
            room_cfg.get("ready_keyword", "取消准备"),
            room_cfg.get("not_ready_keyword", "准备"),
            room_cfg.get("wait_ready_keyword", "等待准备"),
        }
        keywords.discard("")
        if not keywords:
            return False
        try:
            x1, y1, x2, y2 = dm.get_client_rect(hwnd)
            scale_x = (x2 - x1) / room_size[0]
            scale_y = (y2 - y1) / room_size[1]
            scaled_ocr_area = [
                round(ocr_area[0] * scale_x),
                round(ocr_area[1] * scale_y),
                round(ocr_area[2] * scale_x),
                round(ocr_area[3] * scale_y),
            ]
            lines = self.ocr_kk_lines(dm, hwnd, {"area_coords": scaled_ocr_area})
            button_text = " ".join(line.get("text", "").strip() for line in lines)
            return any(keyword in button_text for keyword in keywords)
        except Exception:
            return False

    def _find_create_room_dialog(self, dm: DmClient, owner_pid: int = 0) -> int:
        """通过所属 PID、类名和原生尺寸识别创建房间弹窗。"""
        create_cfg = self.kk_cfg.get("create_room", {})
        return self._find_dialog_by_keyword(
            dm,
            create_cfg.get("dialog_keyword", "创建房间"),
            owner_pid=owner_pid,
            target_size=tuple(create_cfg.get("dialog_window_size", [584, 488])),
            trust_target_size=True,
            size_tolerance=create_cfg.get("size_tolerance", 40),
        )

    def _find_dialog_by_keyword(
        self,
        dm: DmClient,
        keyword: str,
        owner_pid: int = 0,
        target_size: tuple = (),
        exclude_hwnds: set = None,
        trust_target_size: bool = False,
        size_tolerance: int = 0,
    ) -> int:
        """按 PID、类名、尺寸和 OCR 关键词查找弹窗。"""
        popup_class = self.kk_cfg.get("create_room_window_class", "")
        window_title = self.kk_cfg.get("window_title", "")
        min_width, min_height = self.kk_cfg.get("min_business_window_size", [200, 200])
        if not popup_class or not keyword:
            return 0
        excluded = exclude_hwnds or set()
        for w in dm.find_windows(popup_class, window_title, owner_pid):
            hwnd = w["hwnd"]
            if hwnd in excluded:
                continue
            try:
                x1, y1, x2, y2 = dm.get_client_rect(hwnd)
                width, height = x2 - x1, y2 - y1
                if width < min_width or height < min_height:
                    continue
                if (
                    trust_target_size
                    and target_size
                    and (
                        abs(width - target_size[0]) <= size_tolerance and abs(height - target_size[1]) <= size_tolerance
                    )
                ):
                    return hwnd
                lines = self.ocr_kk_lines(
                    dm,
                    hwnd,
                    {"area_coords": [0, 0, width, height]},
                )
                logger.debug(f"弹窗 hwnd={hwnd} OCR 结果: {' '.join(l.get('text', '') for l in lines)[:80]}")
            except Exception as e:
                logger.debug(f"识别 KK 弹窗候选 {hwnd} 失败: {e}")
                continue
            all_text = " ".join(line.get("text", "") for line in lines)
            if keyword in all_text:
                return hwnd
        return 0

    def create_room(
        self,
        dm: DmClient,
        map_name: str = "九种兵器2诸神战场",
        hall_hwnd: int = 0,
        owner_pid: int = 0,
        target_player: str = "",
    ) -> int:
        """在 KK 主界面搜索地图并创建密码房间，返回房间窗口句柄。

        流程：搜索地图名 → 点击搜索结果 → 点击创建房间 → 输入密码 → 创建
        每步操作之间退出绑定、清理弹窗、再重新绑定，避免嵌套绑定冲突。

        :param map_name: 要搜索的地图名称（从游戏配置 [game] map_name 传入）
        :param hall_hwnd: 已知大厅句柄，传入时跳过查找
        :param owner_pid: 大厅所属进程 PID，用于弹窗过滤
        :return: KK 房间窗口句柄，失败返回 0
        """
        create_cfg = self.kk_cfg.get("create_room", {})
        main_cfg = self.kk_cfg.get("main", {})
        main_size = tuple(main_cfg.get("window_size", [1328, 945]))

        # 1. 查找 KK 主界面窗口
        if not hall_hwnd:
            hall_hwnd = self._find_hall_hwnd(dm, target_player=target_player)
        if not hall_hwnd:
            logger.error("未找到 KK 主界面窗口，无法创建房间")
            return 0
        dm.set_client_size(hall_hwnd, *main_size)
        # 验证实际窗口尺寸
        hx1, hy1, hx2, hy2 = dm.get_client_rect(hall_hwnd)
        actual_w, actual_h = hx2 - hx1, hy2 - hy1
        logger.info(f"KK 大厅窗口: hwnd={hall_hwnd}, 目标尺寸={main_size}, 实际尺寸=({actual_w},{actual_h})")
        if abs(actual_w - main_size[0]) > 10 or abs(actual_h - main_size[1]) > 10:
            logger.warning("大厅实际尺寸与目标差异过大，坐标可能偏移")

        # 2. 点击搜索输入框，清空并输入地图名
        with dm.bind_window(hall_hwnd, bind_cfg=self.kk_cfg.get("bind", {})):
            dm.move_to(*main_cfg["search_input_coords"])
            time.sleep(0.3)
            dm.left_click()
            time.sleep(0.2)
            # 清空输入框：End 移到末尾，再退格删除所有内容
            dm.key_press_char("end")
            time.sleep(0.1)
            for _ in range(50):
                dm.key_press_char("back")
            time.sleep(0.1)
            # 使用新版 SendString 输入中文，避免旧版 SendString2 受系统编码影响产生乱码
            dm.send_string(map_name, hwnd=hall_hwnd)
            logger.info(f"已输入地图名: {map_name}")
            time.sleep(0.3)

        # 清理弹窗（在未绑定状态下）
        self.dismiss_hall_popups(dm, exclude_hwnds={hall_hwnd}, owner_pid=owner_pid)

        # 3. 点击搜索图标
        with dm.bind_window(hall_hwnd, bind_cfg=self.kk_cfg.get("bind", {})):
            dm.move_to(*main_cfg["search_map_coords"])
            time.sleep(0.3)
            dm.left_click()
            logger.info("已点击搜索图标")

        # 4. 等待搜索结果，OCR 检测地图名
        search_wait = main_cfg.get("search_map_wait_time", 5)
        time.sleep(search_wait)

        # 清理弹窗
        self.dismiss_hall_popups(dm, exclude_hwnds={hall_hwnd}, owner_pid=owner_pid)

        # OCR 检测搜索结果列表
        ocr_area = main_cfg.get("map_result_ocr_area_coords", [0, 0, 0, 0])
        logger.info(f"OCR 搜索结果区域: {ocr_area}")
        lines = self.ocr_kk_lines(dm, hall_hwnd, {"area_coords": ocr_area}, merge_lines=False)
        # 按行排序：y_center 接近的视为同一行，同行内按 x_center 排序
        # 避免网格布局中 y 微小差异导致顺序错乱
        sorted_lines = sorted(lines, key=lambda l: (round(l.get("y_center", 0) / 20), l.get("x_center", 0)))
        all_texts = [ln.get("text", "").strip() for ln in sorted_lines if ln.get("text", "").strip()]
        logger.info(f"搜索结果 OCR 文本: {all_texts}")
        target_line = None
        for line in sorted_lines:
            text = line.get("text", "").strip()
            if map_name in text:
                target_line = line
                break
        # 模糊匹配：OCR 可能漏字，用最长连续公共子串匹配
        if not target_line:
            for line in sorted_lines:
                text = line.get("text", "").strip()
                if not text:
                    continue
                # 计算地图名与 OCR 文本的最长连续公共子串
                lcs_len = _longest_common_substring_len(map_name, text)
                # 最长公共子串至少占地图名长度的 60%
                if lcs_len >= len(map_name) * 0.6:
                    logger.info(f"模糊匹配命中: OCR='{text}', 地图名='{map_name}', LCS={lcs_len}")
                    target_line = line
                    break
        if not target_line:
            logger.error(f"搜索结果中未找到地图：{map_name}")
            # 保存搜索结果区域的 GDI2 后台截图用于诊断
            with dm.bind_window(hall_hwnd, bind_cfg=self.kk_cfg.get("bind", {})):
                dm.save_screenshot(tuple(ocr_area), label="create_room_search_gdi", force=True)
            dm.save_screenshot(label="create_room_map_not_found", force=True)
            return 0

        # 5. 点击匹配的搜索结果（OCR 坐标是截图区域内相对坐标，需加区域偏移转换为客户区坐标）
        click_x = int(target_line["x_center"]) + ocr_area[0]
        click_y = int(target_line["y_center"]) + ocr_area[1]
        logger.info(f"点击搜索结果: {target_line['text']} 坐标=({click_x},{click_y})")
        with dm.bind_window(hall_hwnd, bind_cfg=self.kk_cfg.get("bind", {})):
            dm.move_to(click_x, click_y)
            time.sleep(0.3)
            dm.left_click()

        # 6. 等待地图详情页加载
        detail_wait = main_cfg.get("detail_wait_time", 3)
        time.sleep(detail_wait)

        # 清理弹窗
        self.dismiss_hall_popups(dm, exclude_hwnds={hall_hwnd}, owner_pid=owner_pid)

        # 7. 点击创建房间按钮
        with dm.bind_window(hall_hwnd, bind_cfg=self.kk_cfg.get("bind", {})):
            dm.move_to(*main_cfg["create_button_coords"])
            time.sleep(0.3)
            dm.left_click()

        # 8. 等待创建房间弹窗出现
        dialog_timeout = create_cfg.get("dialog_detect_timeout", 5)
        dialog_poll = create_cfg.get("dialog_detect_interval", 0.2)
        deadline = time.monotonic() + dialog_timeout
        dialog_hwnd = 0
        while not dialog_hwnd:
            dialog_hwnd = self._find_create_room_dialog(dm, owner_pid=owner_pid)
            if dialog_hwnd or time.monotonic() >= deadline:
                break
            time.sleep(dialog_poll)
        if not dialog_hwnd:
            logger.error("未出现创建房间弹窗")
            dm.save_screenshot(label="create_room_dialog_not_found", force=True)
            return 0

        dialog_size = tuple(create_cfg.get("dialog_window_size", [584, 488]))
        try:
            dm.set_client_size(dialog_hwnd, *dialog_size)
            logger.info(f"创建房间弹窗已统一尺寸: {dialog_size}")
        except Exception as e:
            logger.warning(f"设置创建房间弹窗尺寸失败: {e}")
        dx1, dy1, dx2, dy2 = dm.get_client_rect(dialog_hwnd)
        actual_w, actual_h = dx2 - dx1, dy2 - dy1
        password_coords = create_cfg.get("password_input_coords", [0, 0])
        confirm_coords = create_cfg.get("confirm_create_coords", [0, 0])
        logger.info(f"创建房间弹窗: hwnd={dialog_hwnd}, 尺寸=({actual_w},{actual_h})")

        # 9. 在创建房间弹窗中输入密码并创建
        bind_cfg = self.kk_cfg.get("bind", {})
        password = create_cfg.get("password", "")
        # 第一段 bind：点击密码框 → 输入密码
        with dm.bind_window(dialog_hwnd, bind_cfg=bind_cfg):
            dm.move_to(*password_coords)
            time.sleep(0.5)
            dm.left_click()
            time.sleep(0.5)
            # 清空输入框：Ctrl+A 全选（后台模式下比 50 次 backspace 更可靠，避免消息队列淹没导致焦点丢失）
            dm.key_press_char("ctrl+a")
            time.sleep(0.2)
            if password:
                dm.send_string(password, hwnd=dialog_hwnd)
                logger.info(f"已输入房间密码: {password}")
                time.sleep(0.3)
        # 输入密码后刷新弹窗（layered window 后台输入后画面不刷新）。
        # force_refresh 会取消/恢复 WS_EX_LAYERED，可能破坏大漠后台绑定状态，
        # 因此放在 bind 上下文之外，刷新后重新 bind 再点击创建。
        if password:
            dm.force_refresh_layered(dialog_hwnd)
            dm.save_screenshot(label="password_input_check", force=True)
        # 第二段 bind：点击创建按钮
        with dm.bind_window(dialog_hwnd, bind_cfg=bind_cfg):
            dm.move_to(*confirm_coords)
            time.sleep(0.3)
            dm.left_click()
            logger.info("已点击创建房间确认按钮")

        # 10. 等待房间窗口出现
        create_timeout = create_cfg.get("room_detect_timeout", 8)
        room_poll = create_cfg.get("room_detect_interval", 0.2)
        deadline = time.monotonic() + create_timeout
        room_hwnd = 0
        while not room_hwnd:
            room_hwnd = self._find_room_window(dm, owner_pid=owner_pid)
            if room_hwnd or time.monotonic() >= deadline:
                break
            time.sleep(room_poll)
        if room_hwnd:
            logger.info("创建房间成功，已进入 KK 房间")
            # layered window 后台操作后画面不刷新，强制刷新让 Qt 重绘（消除黑框）
            dm.force_refresh_layered(room_hwnd)
        else:
            logger.error("创建房间后未找到房间窗口")
            dm.save_screenshot(label="create_room_failed", force=True)
        return room_hwnd
