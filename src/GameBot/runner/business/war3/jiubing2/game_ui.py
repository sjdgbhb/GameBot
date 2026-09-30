"""
游戏 UI 面板操作 — 卡牌窗口、神碎窗口、圣痕窗口、技能面板、属性面板等。
每个方法独立可调用，不绑定特定游戏阶段，任何任务中途都可以单独调用。
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    pass
from GameBot.config import resolve_bind_cfg
from GameBot.utils import logger


class GameUI:
    __doc__ = '九种兵器2 游戏内 UI 面板交互。\n\n    封装所有弹出式窗口/面板的"打开 → 操作 → 关闭"流程。\n    不包含任何任务编排逻辑，每个方法都可以被不同任务独立调用。\n    依赖 self._war3 来执行 send_msg 等 War3 通用操作。\n    '

    def __init__(self, dm, war3_cfg, hero_cfg, cfg, war3):
        """
        :param dm: DmClient 大漠客户端
        :param war3_cfg: war3 配置（窗口尺寸、响应时间等）
        :param hero_cfg: 英雄配置（楼层、坐标、技能、卡牌/神碎/圣痕设置）
        :param cfg: 任务依赖闭包配置（load_task 结果，含 game/skill_panel/card/shard/stigmata 等段）
        :param war3: War3Business 实例，用于 send_msg 等基础操作
        """
        self.dm = dm
        self.war3_cfg = war3_cfg
        self.hero_cfg = hero_cfg
        self.cfg = cfg
        self.game_cfg = cfg.get("war3", {}).get("jiubing2", {}).get("game", {})
        self._war3 = war3

    def _wait(self, seconds: float, stop_event=None):
        """可中断等待：stop_event 设置时抛 StopTaskError，否则等价 time.sleep。"""
        self._war3.interruptible_wait(seconds, stop_event)

    def get_skill_coords(self, index_x: "int", index_y: "int") -> "tuple":
        """将技能面板行列索引转换为屏幕坐标（纯计算，无 IO）。

        :param index_x: 技能面板行号（1-based）
        :param index_y: 技能面板列号（1-based）
        :return: (screen_x, screen_y)
        """
        panel = self.cfg.get("war3", {}).get("jiubing2", {}).get("skill_panel", {})
        first = panel.get("first_coords", [0, 0])
        return (first[0] + (index_y - 1) * panel.get("gap_x", 0), first[1] + (index_x - 1) * panel.get("gap_y", 0))

    def learn_skill(self, stop_event=None):
        """学习英雄技能。

        流程：循环点击"学习技能"按钮 → 点击每个待学技能格。
        技能列表由 hero_cfg['learn_skills'] 配置。

        :param stop_event: 停止事件，设置时中断等待
        """
        logger.info("学习技能")
        panel = self.cfg.get("war3", {}).get("jiubing2", {}).get("skill_panel", {})
        learn_coords = (self.get_skill_coords)(*panel["learn_skill_grid"])
        gt = self.war3_cfg["general_time"]
        for item in self.hero_cfg["learn_skills"]:
            (self.dm.move_to)(*learn_coords)
            self._wait(gt, stop_event)
            self.dm.left_click()
            self._wait(gt, stop_event)
            coords = self.get_skill_coords(item["index_x"], item["index_y"])
            (self.dm.move_to)(*coords)
            self._wait(gt, stop_event)
            self.dm.left_click()
            self._wait(gt, stop_event)

    def is_difficulty_visible(self, hwnd: int = 0) -> bool:
        """难度选择界面是否在场（OCR difficulty.keywords 判定，只读不操作）。

        :param hwnd: 目标窗口句柄；为 0 时取认领/绑定窗口
        :return: True=难度界面在场
        """
        diff_cfg = self.cfg.get("war3", {}).get("jiubing2", {}).get("difficulty", {})
        keywords = diff_cfg.get("keywords", [])
        hwnd = hwnd or self._war3._find_war3_hwnd()
        if not keywords or not hwnd:
            return False
        # 窗口可能未统一客户区尺寸（认领前检测），按尺寸差外扩 OCR 区域
        ocr_cfg = dict(diff_cfg)
        if "area_coords" in ocr_cfg:
            ocr_cfg["area_coords"] = self._war3._size_tolerant_area(hwnd, ocr_cfg["area_coords"])
        lines = self._war3.ocr_lines(hwnd, ocr_cfg)
        return any(kw in line.get("text", "") for kw in keywords for line in lines)

    def select_difficulty(
        self, task_cfg: dict = None, stop_event=None, hwnd: int = 0, only_if_visible: bool = False
    ) -> bool:
        """OCR 识别难度选项并点击目标难度。

        从 task_cfg['difficulty'] 或 game.default_difficulty 获取目标难度关键词，
        在难度选择界面 OCR 区域中查找包含该关键词的文本，点击对应坐标完成选择。
        无配置时回退到默认行为（按 Enter 选第一项）。

        :param task_cfg: 任务配置（含 difficulty 字段，fallback 到 game.default_difficulty）
        :param stop_event: 停止事件，设置时中断等待
        :param hwnd: 目标窗口句柄；为 0 时取认领/绑定窗口（_find_war3_hwnd）
        :param only_if_visible: True 时仅在难度选择界面确实存在（OCR 命中任一
            difficulty.keywords）时才操作，否则直接返回 False——用于窗口归属未确认的
            认领前阶段，不发 Enter 等按键避免误触
        :return: True=已点击目标难度, False=未选择
        """
        diff_cfg = self.cfg.get("war3", {}).get("jiubing2", {}).get("difficulty", {})
        target = (task_cfg or {}).get("difficulty") or self.game_cfg.get("default_difficulty")

        if not target or not diff_cfg:
            if only_if_visible:
                return False
            logger.info("未配置难度选择，使用默认（Enter）")
            self.dm.key_press_char("enter")
            self._wait(self.war3_cfg["general_time"], stop_event)
            return True

        if not only_if_visible:
            logger.info(f"选择难度，关键词：{target}")
        hwnd = hwnd or self._war3._find_war3_hwnd()
        if not hwnd:
            if only_if_visible:
                return False
            logger.warning("未找到 War3 窗口，回退到默认（Enter）")
            self.dm.key_press_char("enter")
            self._wait(self.war3_cfg["general_time"], stop_event)
            return True

        area_coords = diff_cfg.get("area_coords", [0, 0, 0, 0])
        lines = self._war3.ocr_lines(hwnd, diff_cfg)
        texts = [line.get("text", "") for line in lines]
        for line, text in zip(lines, texts):
            if target in text:
                x = int(line.get("x_center", 0)) + area_coords[0]
                y = int(line.get("y_center", 0)) + area_coords[1]
                logger.info(f"已匹配难度：{text}，点击 ({x}, {y})")
                self.dm.move_to(x, y)
                self._wait(self.war3_cfg["general_time"], stop_event)
                self.dm.left_click()
                self._wait(self.war3_cfg["general_time"], stop_event)
                return True
        # 难度界面存在性判定：任一难度关键词命中即认为界面在场
        keywords = diff_cfg.get("keywords", [])
        visible = bool(keywords) and any(kw in text for kw in keywords for text in texts)
        if only_if_visible:
            if visible:
                logger.warning(f"难度选择界面在场但未匹配到目标「{target}」，跳过选择（OCR: {texts}）")
            return False
        logger.warning(f"未找到难度关键词「{target}」，回退到默认（Enter）")
        self.dm.key_press_char("enter")
        self._wait(self.war3_cfg["general_time"], stop_event)
        return True

    def wait_and_select_difficulty(
        self, hwnd: int, task_cfg: dict = None, stop_event=None, timeout: float = None
    ) -> bool:
        """等待难度选择界面出现并选择目标难度；界面始终未出现则返回 False。

        供认领前钩子调用（窗口归属未确认）：内部自行绑定 hwnd，
        全程只做安全的 OCR + 目标点击，不发送 Enter 等按键。

        :param hwnd: 目标窗口句柄
        :param task_cfg: 任务配置（含 difficulty 字段）
        :param stop_event: 停止事件
        :param timeout: 最长等待秒数，None 时用 difficulty.wait_ui_time（默认 8s）
        :return: True=已选择难度, False=界面未出现/未选择
        """
        diff_cfg = self.cfg.get("war3", {}).get("jiubing2", {}).get("difficulty", {})
        wait_ui_time = float(timeout if timeout is not None else diff_cfg.get("wait_ui_time", 8))
        deadline = time.time() + wait_ui_time
        with self.dm.bind_window(hwnd, bind_cfg=resolve_bind_cfg(self.war3_cfg)):
            while True:
                if self.select_difficulty(task_cfg, stop_event=stop_event, hwnd=hwnd, only_if_visible=True):
                    return True
                if time.time() >= deadline:
                    logger.debug(f"等待难度选择界面超时（{wait_ui_time}s），按无界面处理")
                    return False
                self._wait(0.5, stop_event)

    def select_hero(self, stop_event=None):
        """选择英雄。

        流程：按楼层快捷键切换到英雄所在楼层 → 点小地图切视角 → 双击英雄头像。
        hero_cfg['floor_key'] 为 None 时抛出异常。

        :param stop_event: 停止事件，设置时中断等待
        """
        logger.info("选择英雄")
        floor_key = self.hero_cfg["floor_key"]
        if floor_key is None:
            raise ValueError(f"英雄 {self.hero_cfg.get('selected_hero', '?')} 未配置楼层键")
        coords = self.hero_cfg["coords"]
        mini_coords = self.hero_cfg.get("mini_coords")
        bind_hwnd = self.dm.get_bind_window()
        logger.info(
            f"选英雄前状态: bind_hwnd={bind_hwnd}, floor_key={floor_key}, mini_coords={mini_coords}, coords={coords}"
        )
        self.dm.key_press_char(floor_key)
        self._wait(self.war3_cfg["small_window_response_time"], stop_event)
        # 点小地图切换视角到英雄所在区域，否则英雄头像可能不在屏幕可见范围
        if mini_coords:
            logger.info(f"点小地图切视角: move_to({mini_coords[0]}, {mini_coords[1]})")
            self.dm.move_to(*mini_coords)
            self._wait(self.war3_cfg["key_time"], stop_event)
            self.dm.left_click()
            self._wait(self.war3_cfg["general_time"], stop_event)
        logger.info(f"move_to({coords[0]}, {coords[1]})")
        (self.dm.move_to)(*coords)
        gt = self.war3_cfg["general_time"]
        self._wait(gt, stop_event)
        self.dm.left_double_click()
        self._wait(gt, stop_event)

    def load_save(self, stop_event=None):
        """通过聊天指令读取英雄存档。

        以 -load 开头的存档码发送到游戏聊天栏。
        如果 hero_cfg 未配置 load_save 则跳过。

        :param stop_event: 停止事件，设置时中断等待
        """
        load_save = self.hero_cfg.get("load_save")
        if not load_save:
            return
        logger.info("读取存档")
        self._war3.send_msg(load_save, stop_event=stop_event)
        self._wait(self.game_cfg["load_save_time"], stop_event)

    def _get_card_coords(self) -> "list":
        """根据 hero_cfg 中配置的卡牌行列计算屏幕坐标列表。

        :return: [(x1, y1), (x2, y2), ...]
        """
        card_cfg = self.cfg.get("war3", {}).get("jiubing2", {}).get("card", {})
        coords = []
        for row, col in self.hero_cfg["card"]["use_index"]:
            x = card_cfg["first_coords"][0] + (col - 1) * card_cfg["gap_x"]
            y = card_cfg["first_coords"][1] + (row - 1) * card_cfg["gap_y"]
            coords.append((x, y))

        return coords

    def equip_cards(self, stop_event=None):
        """打开卡牌窗口 → 逐张点击 → 确定 → 关闭窗口。

        会重试打开窗口直到识别到卡牌窗口图标。
        如果 hero_cfg['card']['is_open'] 为 False 则跳过。

        :param stop_event: 停止事件，设置时中断等待
        """
        logger.info("装备卡牌")
        if not self.hero_cfg.get("card", {}).get("is_open", False):
            return
        card_cfg = self.cfg.get("war3", {}).get("jiubing2", {}).get("card", {})
        hotkey = card_cfg["switch_hotkey"]
        delta_color = card_cfg.get("card_show_delta_color", "000000")

        def _card_window_open() -> bool:
            index, _, _ = self.dm.find_pic(
                *card_cfg["card_show_area_coords"],
                card_cfg["card_show_img"],
                sim=card_cfg["card_show_sim"],
                delta_color=delta_color,
            )
            return index > -1

        # 卡牌窗口打开有渲染延迟：按一次热键后在 open_timeout 内轮询找图，
        # 确认未打开才重按——否则 F4 会把刚打开还没渲染出来的窗口又按关，反复开关
        open_timeout = card_cfg.get("open_timeout", 2.0)
        # F4 是开关切换：先检测一次，已打开则跳过按键（避免把开着的窗口按关）
        opened = _card_window_open()
        while not opened:
            self.dm.key_press_char(hotkey)
            deadline = time.monotonic() + open_timeout
            while time.monotonic() < deadline:
                self._wait(self.war3_cfg["small_window_response_time"], stop_event)
                if _card_window_open():
                    opened = True
                    break
            if not opened:
                logger.warning("未打开卡牌窗口，稍后重试...")
                self._wait(self.war3_cfg["general_time"], stop_event)
        logger.info("成功打开卡牌窗口")

        gt = self.war3_cfg["general_time"]
        for c in self._get_card_coords():
            (self.dm.move_to)(*c)
            self._wait(gt, stop_event)
            self.dm.left_click()
            self._wait(gt, stop_event)

        (self.dm.move_to)(*card_cfg["confirm_coords"])
        self._wait(gt, stop_event)
        self.dm.left_click()
        self._wait(gt, stop_event)
        self.dm.key_press_char(hotkey)
        self._wait(gt, stop_event)

    def _get_shard_coords(self, index: "int") -> "tuple":
        """计算指定行号的神碎激活开关屏幕坐标。

        :param index: 神碎行号（1-based）
        :return: (x, y)
        """
        shard_cfg = self.cfg.get("war3", {}).get("jiubing2", {}).get("shard", {})
        return (shard_cfg["first_coords"][0], shard_cfg["first_coords"][1] + (index - 1) * shard_cfg["gap"])

    def _flip_to_page(self, cur_page: "int", target_page: "int", stop_event=None) -> "int":
        """翻页到目标神碎页面（仅向后翻）。

        :param cur_page: 当前页码（1-based）
        :param target_page: 目标页码（1-based）
        :param stop_event: 停止事件，设置时中断等待
        :return: 翻页后的当前页码
        """
        if cur_page == target_page:
            return cur_page
        max_pages = self.hero_cfg["shard"]["max_pages"]
        clicks = (target_page - cur_page) % max_pages
        if clicks == 0:
            return cur_page
        next_coords = self.cfg.get("war3", {}).get("jiubing2", {}).get("shard", {}).get("next_page_coords")
        (self.dm.move_to)(*next_coords)
        self._wait(self.war3_cfg["general_time"], stop_event)
        for _ in range(clicks):
            self.dm.left_click()
            cur_page = cur_page % max_pages + 1
            self._wait(self.war3_cfg["small_window_response_time"], stop_event)

        return cur_page

    def equip_shards(self, stop_event=None):
        """开启神碎：激活 → 共鸣 → 吸收。

        流程：打开神碎窗口 → 翻页逐行激活 → 激活共鸣 → 吸收未开启的神碎 → 关闭。
        如果 hero_cfg['shard']['is_open'] 为 False 则跳过。

        :param stop_event: 停止事件，设置时中断等待
        """
        logger.info("开启神碎")
        hero_shard = self.hero_cfg.get("shard", {})
        if not hero_shard.get("is_open", False):
            return
        shard_cfg = self.cfg.get("war3", {}).get("jiubing2", {}).get("shard", {})
        hotkey = shard_cfg["switch_hotkey"]
        self.dm.key_press_char(hotkey)
        self._wait(self.war3_cfg["small_window_response_time"], stop_event)
        gt = self.war3_cfg["general_time"]
        swt = self.war3_cfg["small_window_response_time"]
        cur_page = 1
        for item in hero_shard["use_index"]:
            page, index = item[0], item[1]
            cur_page = self._flip_to_page(cur_page, page, stop_event)
            (self.dm.move_to)(*self._get_shard_coords(index))
            self._wait(gt, stop_event)
            self.dm.left_click()

        if hero_shard["is_resonance"]:
            (self.dm.move_to)(*shard_cfg["resonance_coords"])
            self._wait(gt, stop_event)
            self.dm.left_click()
            self._wait(swt, stop_event)
            (self.dm.move_to)(*shard_cfg["resonance_hero_coords"])
            self._wait(gt, stop_event)
            self.dm.left_click()
        if hero_shard["is_absorb"]:
            page, index = hero_shard["absorb_index"][0], hero_shard["absorb_index"][1]
            cur_page = self._flip_to_page(cur_page, page, stop_event)
            index_set = {item[1] for item in hero_shard["use_index"] if item[0] == cur_page}
            if len(index_set) >= shard_cfg["shards_per_page"]:
                logger.warning("待吸收神碎所在页面的神碎已全部开启，无法再吸收！请检查配置")
            elif index in index_set:
                logger.warning("待吸收神碎位置已被开启，无法再吸收！请检查配置")
            else:
                index_set = {i for i in index_set if i < index}
                for _ in range(index - len(index_set)):
                    (self.dm.move_to)(*shard_cfg["switch_absorb_coords"])
                    self._wait(gt, stop_event)
                    self.dm.left_click()
                    self._wait(gt, stop_event)

        self.dm.key_press_char(hotkey)

    def load_stigmata(self, stop_event=None):
        """读取圣痕。

        如果使用第2/3套圣痕栏位：打开窗口 → 点击对应栏位 → 关闭 → 发送读取指令。
        第1套栏位只需发送读取指令，无需窗口操作。
        如果 hero_cfg['stigmata']['is_open'] 为 False 则跳过。

        :param stop_event: 停止事件，设置时中断等待
        """
        logger.info("读取圣痕")
        hero_stigmata = self.hero_cfg.get("stigmata", {})
        if not hero_stigmata.get("is_open", False):
            return
        use_index = hero_stigmata["use_index"]
        if use_index < 1 or use_index > 3:
            raise ValueError("圣痕索引必须为 1~3！")
        stigmata_cfg = self.cfg.get("war3", {}).get("jiubing2", {}).get("stigmata", {})
        gt = self.war3_cfg["general_time"]
        if use_index != 1:
            hotkey = stigmata_cfg["switch_hotkey"]
            self.dm.key_press_char(hotkey)
            self._wait(self.war3_cfg["small_window_response_time"], stop_event)
            (self.dm.move_to)(*stigmata_cfg["coords"][use_index - 1])
            self._wait(gt, stop_event)
            self.dm.left_click()
            self._wait(gt, stop_event)
            self.dm.key_press_char(hotkey)
        self._war3.send_msg(stigmata_cfg["load_stigmata"], stop_event=stop_event)
        self._wait(gt, stop_event)

    def switch_attribute_panel(self, is_fold: "bool" = True, stop_event=None):
        """折叠/展开属性面板。

        先找图确认面板当前状态，只有状态不匹配才点击切换。

        :param is_fold: True=折叠面板, False=展开面板
        :param stop_event: 停止事件，设置时中断等待
        :return: 1=执行了点击, 0=无需操作
        """
        panel_cfg = self.cfg.get("war3", {}).get("jiubing2", {}).get("attribute_panel", {})
        img = panel_cfg["fold_icon"] if is_fold else panel_cfg["unfold_icon"]
        (index, x, y) = (self.dm.find_pic)(
            *panel_cfg["switch_area_coords"], *(img, panel_cfg["switch_sim"], panel_cfg["switch_delta_color"])
        )
        if index == -1:
            return 0
        logger.info("收起属性面板" if is_fold else "展开属性面板")
        gt = self.war3_cfg["general_time"]
        (w, h) = panel_cfg["switch_size"]
        self.dm.move_to(x + w / 2, y + h / 2)
        self._wait(gt, stop_event)
        self.dm.left_click()
        self._wait(gt, stop_event)
        return 1
