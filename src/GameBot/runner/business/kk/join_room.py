"""KK 按房间号加入房间 mixin — 队员通过房间号+密码搜索并加入指定房间。

包含 JoinRoomMixin：join_room_by_id 及辅助方法。
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING

from GameBot.runner.business.kk.hall_manager import _longest_common_substring_len
from GameBot.utils import logger

if TYPE_CHECKING:
    from GameBot.runner.driver.base import DmClientBase as DmClient


class JoinRoomMixin:
    """KK 按房间号加入房间 mixin。依赖 self.dm（DmClient）和 self.kk_cfg（dict）。"""

    def join_room_by_id(
        self,
        dm: DmClient,
        room_id: str,
        password: str,
        map_name: str = "九种兵器2诸神战场",
        hall_hwnd: int = 0,
        owner_pid: int = 0,
        target_player: str = "",
    ) -> int:
        """按房间号+密码加入指定房间，返回房间窗口句柄。

        流程：
        1. 搜索地图名 → 进入地图详情页（复用 create_room 前半段逻辑）
        2. 点击"房间列表"按钮
        3. 输入房间号 → 点击搜索
        4. 等待搜索结果 → 双击第一个结果
        5. 弹出密码框 → 输入密码 → 确认
        6. 等待进入房间

        :param room_id: 房间号字符串
        :param password: 房间密码
        :param map_name: 地图名称（用于搜索进入地图详情页）
        :param hall_hwnd: 已知的 KK 主界面窗口句柄，传入时跳过查找
        :param owner_pid: 大厅所属进程 PID，用于弹窗过滤
        :return: 房间窗口句柄，失败返回 0
        """
        main_cfg = self.kk_cfg.get("main", {})
        password_cfg = self.kk_cfg.get("password_input", {})
        main_size = tuple(main_cfg.get("window_size", [1328, 945]))

        # 1. 查找 KK 主界面窗口
        if not hall_hwnd:
            hall_hwnd = self._find_hall_hwnd(dm, target_player=target_player)
        if not hall_hwnd:
            logger.error("未找到 KK 主界面窗口，无法加入房间")
            return 0
        dm.set_client_size(hall_hwnd, *main_size)

        # 2. 搜索地图名 → 进入地图详情页
        if not self._search_map_and_enter_detail(dm, hall_hwnd, map_name, owner_pid=owner_pid):
            logger.error(f"搜索地图 {map_name} 失败，无法加入房间")
            dm.save_screenshot(label="join_room_map_not_found", force=True)
            return 0

        # 清理弹窗
        self.dismiss_hall_popups(dm, exclude_hwnds={hall_hwnd}, owner_pid=owner_pid)

        # 3. 点击"房间列表"按钮
        with dm.bind_window(hall_hwnd, bind_cfg=self.kk_cfg.get("bind", {})):
            room_list_coords = main_cfg.get("room_list_button_coords", [0, 0])
            if room_list_coords == [0, 0]:
                logger.warning("未配置 main.room_list_button_coords")
            dm.move_to(*room_list_coords)
            time.sleep(0.3)
            dm.left_click()

        # 等待房间列表加载
        time.sleep(main_cfg.get("search_room_wait_time", 2))

        # 清理弹窗
        self.dismiss_hall_popups(dm, exclude_hwnds={hall_hwnd}, owner_pid=owner_pid)

        # 4. 输入房间号并搜索
        with dm.bind_window(hall_hwnd, bind_cfg=self.kk_cfg.get("bind", {})):
            # 点击房间号输入框
            room_id_input_coords = main_cfg.get("room_id_input_coords", [0, 0])
            if room_id_input_coords == [0, 0]:
                logger.warning("未配置 main.room_id_input_coords")
            dm.move_to(*room_id_input_coords)
            time.sleep(0.3)
            # 清空输入框：End 移到末尾，再退格删除所有内容
            dm.left_click()
            time.sleep(0.2)
            dm.key_press_char("end")
            time.sleep(0.1)
            for _ in range(20):
                dm.key_press_char("back")
            time.sleep(0.1)
            # 输入房间号
            dm.send_string2(room_id, hwnd=hall_hwnd)
            time.sleep(0.3)
            # 点击搜索按钮
            search_room_coords = main_cfg.get("search_room_coords", [0, 0])
            if search_room_coords == [0, 0]:
                logger.warning("未配置 main.search_room_coords")
            dm.move_to(*search_room_coords)
            time.sleep(0.3)
            dm.left_click()

        # 5. 等待搜索结果
        search_wait = main_cfg.get("search_room_wait_time", 2)
        time.sleep(search_wait)

        # 清理弹窗
        self.dismiss_hall_popups(dm, exclude_hwnds={hall_hwnd}, owner_pid=owner_pid)

        # 6. OCR 检测搜索结果，双击匹配的房间号
        # 房间列表搜索结果复用房间列表区域坐标，若无配置则用 room_result_coords 点击
        ocr_area = main_cfg.get("room_result_coords", [0, 0, 0, 0])
        # room_result_coords 是 [x, y] 点击坐标而非 OCR 区域，搜索结果直接双击该坐标
        popup_class = self.kk_cfg.get("create_room_window_class", "")
        window_title = self.kk_cfg.get("window_title", "")
        existing_popups = {
            w["hwnd"] for w in dm.find_windows(popup_class, window_title, owner_pid)
        }
        if len(ocr_area) == 2:
            # 直接双击搜索结果位置
            with dm.bind_window(hall_hwnd, bind_cfg=self.kk_cfg.get("bind", {})):
                dm.move_to(*ocr_area)
                time.sleep(0.3)
                dm.left_double_click()
        else:
            # 如果配置了 4 元素 OCR 区域，走 OCR 匹配逻辑
            lines = self.ocr_kk_lines(dm, hall_hwnd, {"area_coords": ocr_area}, merge_lines=False)
            # 按 (y_center, x_center) 排序
            sorted_lines = sorted(lines, key=lambda l: (round(l.get("y_center", 0) / 20), l.get("x_center", 0)))
            target_line = None
            for line in sorted_lines:
                text = line.get("text", "").strip()
                if room_id in text:
                    target_line = line
                    break
            if not target_line:
                logger.error(f"搜索结果中未找到房间号：{room_id}")
                dm.save_screenshot(label="join_room_id_not_found", force=True)
                return 0

            # 双击搜索结果进入房间（OCR 坐标是截图区域内相对坐标，需加区域偏移转换为客户区坐标）
            with dm.bind_window(hall_hwnd, bind_cfg=self.kk_cfg.get("bind", {})):
                dm.move_to(int(target_line["x_center"]) + ocr_area[0], int(target_line["y_center"]) + ocr_area[1])
                time.sleep(0.3)
                dm.left_double_click()

        # 7. 等待密码输入框出现并输入密码
        dialog_timeout = password_cfg.get("dialog_detect_timeout", 5)
        dialog_poll = password_cfg.get("dialog_detect_interval", 0.2)
        deadline = time.monotonic() + dialog_timeout
        password_hwnd = 0
        while not password_hwnd:
            password_hwnd = self._find_password_dialog(
                dm,
                owner_pid=owner_pid,
                exclude_hwnds=existing_popups,
            )
            if password_hwnd or time.monotonic() >= deadline:
                break
            time.sleep(dialog_poll)
        if not password_hwnd:
            logger.error("未出现密码输入弹窗")
            dm.save_screenshot(label="join_room_password_dialog_not_found", force=True)
            return 0
        password_size = tuple(password_cfg.get("window_size", [440, 260]))
        password_input_coords = password_cfg.get("password_input_coords", [0, 0])
        confirm_button_coords = password_cfg.get("confirm_button_coords", [0, 0])
        try:
            dm.set_client_size(password_hwnd, *password_size)
            logger.info(f"密码弹窗已统一尺寸: {password_size}")
        except Exception as e:
            logger.warning(f"设置密码弹窗尺寸失败: {e}")

        bind_cfg = self.kk_cfg.get("bind", {})
        with dm.bind_window(password_hwnd, bind_cfg=bind_cfg):
            # 点击密码输入框
            if password_input_coords == [0, 0]:
                logger.warning("未配置 password_input.password_input_coords")
            dm.move_to(*password_input_coords)
            time.sleep(0.5)
            dm.left_click()
            time.sleep(0.5)
            # 清空输入框：Ctrl+A 全选（后台模式下比 50 次 backspace 更可靠）
            dm.key_press_char("ctrl+a")
            time.sleep(0.2)
            # 输入密码
            if password:
                dm.send_string2(password, hwnd=password_hwnd)
                logger.info(f"已输入加入房间密码: {password}")
                time.sleep(0.3)
        # 输入密码后刷新弹窗（layered window 后台输入后画面不刷新）。
        # force_refresh 会取消/恢复 WS_EX_LAYERED，可能破坏大漠后台绑定状态，
        # 因此放在 bind 上下文之外，刷新后重新 bind 再点击确认。
        if password:
            dm.force_refresh_layered(password_hwnd)
            dm.save_screenshot(label="join_password_input_check", force=True)
        # 第二段 bind：点击确认按钮
        with dm.bind_window(password_hwnd, bind_cfg=bind_cfg):
            if confirm_button_coords == [0, 0]:
                logger.warning("未配置 password_input.confirm_button_coords")
            dm.move_to(*confirm_button_coords)
            time.sleep(0.3)
            dm.left_click()

        # 8. 等待进入房间
        join_timeout = password_cfg.get("room_detect_timeout", 8)
        room_poll = password_cfg.get("room_detect_interval", 0.2)
        deadline = time.monotonic() + join_timeout
        room_hwnd = 0
        while not room_hwnd:
            room_hwnd = self._find_room_window(dm, owner_pid=owner_pid)
            if room_hwnd or time.monotonic() >= deadline:
                break
            time.sleep(room_poll)

        # 9. 查找房间窗口
        if room_hwnd:
            logger.info(f"成功加入房间 {room_id}")
            # layered window 后台操作后画面不刷新，强制刷新让 Qt 重绘
            dm.force_refresh_layered(room_hwnd)
        else:
            logger.error(f"加入房间 {room_id} 后未找到房间窗口")
            dm.save_screenshot(label="join_room_failed", force=True)
        return room_hwnd

    def _search_map_and_enter_detail(
        self, dm: DmClient, hall_hwnd: int, map_name: str, owner_pid: int = 0
    ) -> bool:
        """在 KK 主界面搜索地图并进入地图详情页。

        复用 create_room 的前半段逻辑（搜索→点击搜索结果→等待详情页加载）。

        :param owner_pid: 大厅所属进程 PID，用于弹窗过滤
        :return: True=成功进入详情页, False=失败
        """
        main_cfg = self.kk_cfg.get("main", {})
        main_size = tuple(main_cfg.get("window_size", [1328, 945]))
        dm.set_client_size(hall_hwnd, *main_size)

        # 点击搜索输入框，清空并输入地图名
        with dm.bind_window(hall_hwnd, bind_cfg=self.kk_cfg.get("bind", {})):
            search_input_coords = main_cfg.get("search_input_coords", [0, 0])
            if search_input_coords == [0, 0]:
                logger.warning("未配置 main.search_input_coords")
            dm.move_to(*search_input_coords)
            time.sleep(0.3)
            # 清空输入框：End 移到末尾，再退格删除所有内容
            dm.left_click()
            time.sleep(0.2)
            dm.key_press_char("end")
            time.sleep(0.1)
            for _ in range(50):
                dm.key_press_char("back")
            time.sleep(0.1)
            dm.send_string2(map_name, hwnd=hall_hwnd)
            time.sleep(0.3)

        # 清理弹窗
        self.dismiss_hall_popups(dm, exclude_hwnds={hall_hwnd}, owner_pid=owner_pid)

        # 点击搜索图标
        with dm.bind_window(hall_hwnd, bind_cfg=self.kk_cfg.get("bind", {})):
            search_map_coords = main_cfg.get("search_map_coords", [0, 0])
            if search_map_coords == [0, 0]:
                logger.warning("未配置 main.search_map_coords")
            dm.move_to(*search_map_coords)
            time.sleep(0.3)
            dm.left_click()

        # 等待搜索结果
        search_wait = main_cfg.get("search_map_wait_time", 5)
        time.sleep(search_wait)

        # 清理弹窗
        self.dismiss_hall_popups(dm, exclude_hwnds={hall_hwnd}, owner_pid=owner_pid)

        # OCR 检测搜索结果列表
        ocr_area = main_cfg.get("map_result_ocr_area_coords", [0, 0, 0, 0])
        lines = self.ocr_kk_lines(dm, hall_hwnd, {"area_coords": ocr_area}, merge_lines=False)
        sorted_lines = sorted(lines, key=lambda l: (round(l.get("y_center", 0) / 20), l.get("x_center", 0)))
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
                lcs_len = _longest_common_substring_len(map_name, text)
                if lcs_len >= len(map_name) * 0.6:
                    logger.info(f"模糊匹配命中: OCR='{text}', 地图名='{map_name}', LCS={lcs_len}")
                    target_line = line
                    break
        if not target_line:
            logger.error(f"搜索结果中未找到地图：{map_name}")
            return False

        # 点击匹配的搜索结果（OCR 坐标是截图区域内相对坐标，需加区域偏移转换为客户区坐标）
        with dm.bind_window(hall_hwnd, bind_cfg=self.kk_cfg.get("bind", {})):
            dm.move_to(int(target_line["x_center"]) + ocr_area[0], int(target_line["y_center"]) + ocr_area[1])
            time.sleep(0.3)
            dm.left_click()

        # 等待地图详情页加载
        detail_wait = main_cfg.get("detail_wait_time", 3)
        time.sleep(detail_wait)

        # 清理弹窗
        self.dismiss_hall_popups(dm, exclude_hwnds={hall_hwnd}, owner_pid=owner_pid)

        logger.info(f"已进入地图 {map_name} 详情页")
        return True

    def _find_password_dialog(
        self,
        dm: DmClient,
        owner_pid: int = 0,
        exclude_hwnds: set = None,
    ) -> int:
        """通过所属 PID、新 HWND 和原生尺寸识别密码输入弹窗。"""
        password_cfg = self.kk_cfg.get("password_input", {})
        return self._find_dialog_by_keyword(
            dm,
            password_cfg.get("dialog_keyword", "输入房间密码"),
            owner_pid=owner_pid,
            target_size=tuple(password_cfg.get("window_size", [440, 260])),
            exclude_hwnds=exclude_hwnds,
            trust_target_size=exclude_hwnds is not None,
            size_tolerance=password_cfg.get("size_tolerance", 30),
        )
