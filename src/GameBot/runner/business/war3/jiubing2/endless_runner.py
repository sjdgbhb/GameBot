"""
无尽循环编排器 — 准备阶段 → 进入无尽 → 循环刷怪。
endless.py（完整流程）和 endless_single.py（已在无尽内）共用。
"""

import time

from GameBot.utils import logger


class BossDeathTimeoutError(Exception):
    """BOSS 死亡提示检测超时"""

    pass


class EndlessRunner:
    """无尽副本流程编排器。

    封装无尽副本的完整业务逻辑：等待进入游戏、准备阶段、移动到起点、
    以及核心的循环刷怪流程。不包含场景导航（进皇宫、进无尽）——这些由 SceneNavigator 负责。
    endless.py 和 endless_single.py 共用此类：前者走完整流程，后者直接调用主循环。
    """

    def __init__(self, dm, war3, ui, combat, war3_cfg: dict, hero_cfg: dict, cfg: dict):
        """
        :param dm: DmClient
        :param war3: War3Business 实例（is_in_game / move_to_minimap_point / send_msg / use_inventory_item）
        :param ui: GameUI 实例（switch_attribute_panel 等）
        :param combat: CombatHelper 实例（execute_actions / feed_pet）
        :param war3_cfg: war3 配置
        :param hero_cfg: 英雄配置
        :param cfg: 任务依赖闭包配置（load_task 结果，含 game/command 等段）
        """
        self.dm = dm
        self._war3 = war3
        self._ui = ui
        self._combat = combat
        self.war3_cfg = war3_cfg
        self.hero_cfg = hero_cfg
        self.game_cfg = cfg.get("game", {})
        self.command_cfg = cfg.get("command", {})
        self._prompt_text_cfg = cfg.get("prompt_text", {})

    # ── 游戏进入 & 准备 ───────────────────────────────────

    def wait_enter_game(self, task, stop_event=None):
        """等待进入游戏（委托 War3Business.wait_enter_game，带超时和掉线检测）。

        :param task: 任务对象（需有 game_start_time / pet_feed_time 属性）
        :param stop_event: 停止事件，设置时中断等待
        :raises WindowLostError: War3 窗口消失（掉线）
        :raises TimeoutError: 等待进入游戏超时（卡在加载界面）
        """
        self._war3.wait_enter_game(task, stop_event)

    def do_preparation_phase(self, task_cfg: dict = None, stop_event=None, skip_select_difficulty: bool = False):
        """完整准备阶段。

        顺序：选难度 → 等游戏初始化 → 选英雄 → 读档 → 圣痕 → 卡牌 → 神碎 → 学技能。

        :param task_cfg: 任务配置（含 difficulty 字段，传给 select_difficulty）
        :param stop_event: 停止事件，设置时中断等待
        :param skip_select_difficulty: 是否跳过选难度（组队时由队长单独选）
        """
        if not skip_select_difficulty:
            self._ui.select_difficulty(task_cfg)
        logger.info(f"初始化...（等待 {self.game_cfg['init_game_time']}s）")
        self._war3.interruptible_wait(self.game_cfg["init_game_time"], stop_event)
        self._ui.select_hero()
        self._ui.load_save()
        self._ui.load_stigmata()
        self._ui.equip_cards()
        self._ui.equip_shards()
        self._ui.learn_skill()

    # ── 无尽入口 ──────────────────────────────────────────

    def move_to_start(self, endless_cfg: dict, is_from_entrance: bool = False, stop_event=None):
        """F1 居中 → 通过小地图走到循环起始位置。

        从入口走来（is_from_entrance=True）和打完 BOSS 回来，等待时间不同，
        由 endless_cfg['points'][-1] 中的 entrance_to_start_time / time 分别控制。

        :param endless_cfg: 无尽配置（含 points 路线列表）
        :param is_from_entrance: True=从入口走来（用 entrance_to_start_time），False=打完回来（用 time）
        :param stop_event: 停止事件，设置时中断等待
        """
        self.dm.key_press_char("F1")
        self._war3.interruptible_wait(self.war3_cfg["general_time"], stop_event)
        section = endless_cfg["points"][-1]
        wait = section["entrance_to_start_time"] if is_from_entrance else section["time"]
        logger.info(f"目标位置：{section['desc']}，等待时间：{wait}s")
        self._war3.move_to_minimap_point(section["mini_coords"], section["coords"], 2, wait, stop_event=stop_event)

    def start_endless(self, task, game_idx: int, endless_cfg: dict):
        """无尽入口：回到起点 → 开始循环刷怪。

        :param task: 任务对象
        :param game_idx: 当前局数编号（1-based）
        :param endless_cfg: 无尽配置
        """
        logger.info("开始无尽")
        stop_event = getattr(task, "_stop_event", None)
        self.move_to_start(endless_cfg, is_from_entrance=True, stop_event=stop_event)
        self.clear_endless_monster_loop(task, game_idx, endless_cfg)

    # ── 无尽主循环 ────────────────────────────────────────

    def clear_endless_monster_loop(self, task, game_idx: int, endless_cfg: dict):
        """无尽刷怪主循环。

        endless_single 直接调用此方法（已在无尽地图内，无需走准备阶段）。
        每层：遍历所有路线点 → 到达后根据点位类型执行不同操作 → 等待刷新。

        :param task: 任务对象（需有 boss_death_time / _stop_event 属性）
        :param game_idx: 当前局数
        :param endless_cfg: 无尽配置（min_level / max_level / points / refresh_timer 等）
        """
        stop_event = getattr(task, "_stop_event", None)
        progress_callback = getattr(task, "_progress_callback", None) or (lambda text: None)
        path_points = endless_cfg["points"]
        max_level = endless_cfg["max_level"]
        total_games = endless_cfg.get("games")
        is_multi = total_games is not None
        for floor in range(endless_cfg["min_level"], max_level + 1):
            logger.info(f"开始清理无尽第 {floor} 层...")
            if is_multi:
                progress_callback(f"第 {game_idx}/{total_games} 局 - 楼层 {floor}/{max_level}")
            else:
                progress_callback(f"楼层 {floor}/{max_level}")
            # 启动后台 OCR 监测，在路径遍历期间持续检测 BOSS 死亡提示
            boss_death_event = self._start_boss_death_watcher(endless_cfg)
            feed_timer = time.time()  # 记录喂食时间
            for idx, pt in enumerate(path_points):
                # 每隔一定时间喂一次宠物
                if time.time() - feed_timer >= endless_cfg["pet_feed_interval"]:
                    self._combat.feed_pet(task, stop_event)
                    feed_timer = time.time()
                # 移动 → 到达后执行 actions
                self._navigate_to_point(pt, stop_event)
                self._on_arrive(task, pt, floor, idx, path_points, endless_cfg, stop_event)

            logger.info(f"无尽第 {floor} 层清理完毕")
            if is_multi:
                logger.info(f"任务进度：局数：{game_idx} / {total_games} - 层数：{floor} / {max_level}")
            else:
                logger.info(f"任务进度：层数：{floor} / {max_level}")
            # 检查后台监测结果，未检测到则回退到前台轮询
            self._wait_boss_dead(task, endless_cfg, boss_death_event)
            # 等待本层刷新计时器结束（非最后一层）
            if floor < max_level:
                remaining = endless_cfg["refresh_timer"] - (time.time() - task.boss_death_time)
                if remaining > 0:
                    self._war3.interruptible_wait(remaining, stop_event)

    def _start_boss_death_watcher(self, endless_cfg: dict):
        """启动后台 OCR 监测线程，在路径遍历期间持续检测 BOSS 死亡提示。

        BOSS 在路径中途被击杀后，"开始挑战"提示会向上滚动，等走完所有点位
        再检测时文本可能已滚出 OCR 区域。后台线程在遍历期间持续监测，避免遗漏。

        :return: threading.Event，检测到文本时被 set；无 prompt_text 配置时返回 None
        """
        if not self._prompt_text_cfg:
            return None
        boss_death_text = endless_cfg.get("boss_death_text", "开始挑战")
        return self._war3.start_text_watcher(self._prompt_text_cfg, boss_death_text, interval=1.0)

    def _wait_boss_dead(self, task, endless_cfg: dict, boss_death_event=None):
        """等待 BOSS 死亡（后台 OCR 监测），记录 boss_death_time。

        后台监测线程在路径遍历期间持续检测，走完路径后检查结果。
        未检测到则等待额外超时时间（处理 BOSS 在最后点位才被击杀的情况），
        超时未检测到则保存截图并抛出 BossDeathTimeoutError。

        :param task: 任务对象（需有 boss_death_time 属性）
        :param endless_cfg: 无尽配置（boss_death_text / boss_death_timeout）
        :param boss_death_event: 后台监测线程返回的 Event（可选）
        :raises BossDeathTimeoutError: BOSS 死亡提示检测超时
        """
        timeout = endless_cfg.get("boss_death_timeout", 60)
        stop_event = getattr(task, "_stop_event", None)
        if self._prompt_text_cfg and boss_death_event is not None:
            # 后台已检测到 → 直接记录
            if boss_death_event.is_set():
                self._war3.stop_text_watcher(boss_death_event)
                task.boss_death_time = time.time()
                logger.info("检测到 BOSS 死亡")
                return
            # 后台未检测到 → 额外等待超时时间（BOSS 可能在最后点位才被击杀）
            deadline = time.time() + timeout
            while time.time() < deadline:
                if stop_event is not None and stop_event.is_set():
                    break
                if boss_death_event.wait(timeout=1.0):
                    break
            detected = boss_death_event.is_set()
            self._war3.stop_text_watcher(boss_death_event)
            if detected:
                task.boss_death_time = time.time()
                logger.info("检测到 BOSS 死亡")
                return
            logger.warning("等待 BOSS 死亡超时，保存截图")
            self.dm.save_screenshot(label="boss_death_timeout", force=True)
            raise BossDeathTimeoutError("BOSS 死亡提示超时")
        task.boss_death_time = time.time()

    def _navigate_to_point(self, pt: dict, stop_event=None):
        """F1 居中 → 小地图走到路线点。

        :param pt: 点位配置（mini_coords / coords / walk_mode / time / desc）
        :param stop_event: 可选的停止事件，设置时中断移动等待
        """
        self.dm.key_press_char("F1")
        self._war3.interruptible_wait(self.war3_cfg["key_time"], stop_event)
        logger.info(f"目标位置：{pt.get('desc')}，等待时间：{pt.get('time', 3)}s")
        self._war3.move_to_minimap_point(
            pt.get("mini_coords"),
            pt.get("coords"),
            pt.get("walk_mode", 1),
            pt.get("time", 3),
            stop_event=stop_event,
        )

    def _on_arrive(self, task, pt: dict, floor: int, idx: int, path_points: list, endless_cfg: dict, stop_event=None):
        """到达路线点后执行 actions。

        :param task: 任务对象
        :param pt: 点位配置
        :param floor: 当前楼层
        :param idx: 当前点位在路线中的索引
        :param path_points: 完整路线列表
        :param endless_cfg: 无尽配置
        :param stop_event: 停止事件，设置时中断等待
        """
        # 楼层门控：低于 use_shard_floor 时移除水晶（id=8）的 item action
        pt_eff = dict(pt)
        actions = pt_eff.get("actions")
        if actions and floor < endless_cfg.get("use_shard_floor", 0):
            filtered = [a for a in actions if not (a and a.get("type") == "item" and int(a.get("id", 0)) == 8)]
            if filtered:
                pt_eff["actions"] = filtered
            else:
                pt_eff.pop("actions", None)

        self._combat.execute_actions(pt_eff, pt.get("coords"), stop_event=stop_event)
