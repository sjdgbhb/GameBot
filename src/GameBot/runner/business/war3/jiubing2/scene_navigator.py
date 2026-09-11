"""
场景导航 — 通过传送+小地图+坐标将英雄从 A 场景移动到 B 场景。
endless_cfg 作为方法参数传入，不持久化到实例。
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    import threading

    from GameBot.runner.driver.base import DmClientBase as DmClient
from GameBot.utils import logger

from .combat_helper import get_inventory_hotkey


class SceneNavigator:
    """九种兵器2 游戏内场景切换。

    负责英雄在不同地图场景之间的移动：米奈希尔 ↔ 皇宫 ↔ 无尽地图。
    依赖 _war3（War3Business）提供 move_to_minimap_point / center_hero 等移动原语，
    依赖 _ui（GameUI）提供 get_skill_coords 用于点击 NPC 技能格。
    """

    def __init__(self, dm: DmClient, war3_cfg: dict, hero_cfg: dict, cfg: dict, war3, game_ui):
        """
        :param dm: DmClient
        :param war3_cfg: war3 配置（窗口尺寸、响应时间等）
        :param hero_cfg: 英雄配置（背包物品）
        :param cfg: 任务依赖闭包配置（load_task 结果，需含 game 段与
            scenes.menethil / scenes.palace 命名空间配置）
        :param war3: War3Business 实例
        :param game_ui: GameUI 实例
        """
        self.dm = dm
        self.war3_cfg = war3_cfg
        self.hero_cfg = hero_cfg
        self.game_cfg = cfg.get("game", {})
        scenes = cfg.get("war3", {}).get("jiubing2", {}).get("scenes", {})
        self.menethil_cfg = scenes.get("menethil", {})
        self.palace_cfg = scenes.get("palace", {})
        self._war3 = war3
        self._ui = game_ui

    def enter_palace(self, stop_event: Optional["threading.Event"] = None):
        """传送到米奈希尔 → 小地图走到皇宫入口。

        使用物品栏4号位（米奈希尔传送券）传送到主城，然后通过小地图走到皇宫入口区域。
        """
        logger.info("进入皇宫")
        hotkey = get_inventory_hotkey(self.hero_cfg, 4)
        if hotkey:
            self.dm.key_press_char(hotkey)
        self._war3.interruptible_wait(self.game_cfg["teleport_time"], stop_event)
        gt = self.war3_cfg["general_time"]
        self._war3.center_hero()
        self._war3.interruptible_wait(gt, stop_event)
        waygate = self.menethil_cfg["teleport"]["palace_waygate"]
        self._war3.go_through_teleport(waygate, stop_event)

    def tp_enter_forest_city(self, stop_event: Optional["threading.Event"] = None):
        """tp 传送至远古森林外围入口 → 走进传送圈进入远古森林（即到达森之城）。

        使用物品栏5号位（远古森林外围入口传送卷轴，目前仅 paladin 配置）传送，
        再走进 menethil 场景的 forest_waygate 传送圈。
        """
        logger.info("tp 后进入森之城")
        hotkey = get_inventory_hotkey(self.hero_cfg, 5)
        if hotkey:
            self.dm.key_press_char(hotkey)
        self._war3.interruptible_wait(self.game_cfg["teleport_time"], stop_event)
        gt = self.war3_cfg["general_time"]
        self.dm.key_press_char("F1")
        self._war3.interruptible_wait(gt, stop_event)
        waygate = self.menethil_cfg["teleport"]["forest_waygate"]
        self._war3.go_through_teleport(waygate, stop_event)

    # 中文路线名 → menethil.toml 中 resurrection_stone.skill 英文键名映射
    ROUTE_SCHEME_TO_SKILL_KEY = {
        "奇异之地": "strange_land",
        "荒漠废墟": "unknown_cave",
    }

    def tp_to_patrol_area(self, route_scheme: str, stop_event: Optional["threading.Event"] = None):
        """TP 至米奈希尔 → 走到复活石 NPC → 点击传送至对应区域。

        :param route_scheme: 路线方案名称（中文，如 "奇异之地" 或 "荒漠废墟"，
            通过 ROUTE_SCHEME_TO_SKILL_KEY 映射到 menethil.toml 中的英文技能键）
        :param stop_event: 停止事件
        """
        logger.info(f"传送至巡逻区域：{route_scheme}")
        # 1. 使用米奈希尔传送卷轴（物品 id=4）传送至米奈希尔
        hotkey = get_inventory_hotkey(self.hero_cfg, 4)
        if hotkey:
            self.dm.key_press_char(hotkey)
        self._war3.interruptible_wait(self.game_cfg["teleport_time"], stop_event)
        gt = self.war3_cfg["general_time"]
        self._war3.center_hero()
        self._war3.interruptible_wait(gt, stop_event)

        # 2. 走到复活石 NPC 并点击
        stone_cfg = self.menethil_cfg.get("resurrection_stone", {})
        point = stone_cfg.get("point", {})
        coords = point.get("coords", [0, 0])
        self._war3.move_to_minimap_point(
            point.get("mini_coords"),
            [coords[0] - 100, coords[1]],
            point.get("walk_mode", 2),
            point.get("time", 5),
            stop_event,
        )
        self.dm.move_to(*coords)
        self._war3.interruptible_wait(gt, stop_event)
        self.dm.left_click()
        self._war3.interruptible_wait(self.war3_cfg["small_window_response_time"], stop_event)

        # 3. 点击对应技能格传送（技能格由 menethil.toml 中 resurrection_stone.skill 映射配置）
        skill = stone_cfg.get("skill", {})
        skill_key = self.ROUTE_SCHEME_TO_SKILL_KEY.get(route_scheme, route_scheme)
        grid = skill.get(skill_key)
        if not grid:
            logger.error(f"复活石技能格映射中未找到路线方案「{route_scheme}」（技能键「{skill_key}」）")
            return
        target_coords = self._ui.get_skill_coords(*grid)
        self.dm.move_to(*target_coords)
        self._war3.interruptible_wait(gt, stop_event)
        self.dm.left_click()
        self._war3.interruptible_wait(gt, stop_event)
        logger.info(f"已传送至{route_scheme}")

    def enter_endless(self, task, endless_cfg: dict, stop_event: Optional["threading.Event"] = None):
        """从皇宫走到无尽 NPC → 重置层数 → 进入无尽地图。

        流程：F1 居中 → 小地图走到 NPC 附近 → 点击 NPC →
        点击重置技能格 → 点击进入技能格。

        重置类型由 min_level 自动判断：< 15 重置为 1 层，>= 15 重置为 15 层。

        :param task: 任务对象（需有 game_start_time 属性，用于计算重置 cd）
        :param endless_cfg: 无尽配置（min_level / wait_time）
        :param stop_event: 停止事件，设置时中断等待
        """
        logger.info("进入无尽")
        gt = self.war3_cfg["general_time"]
        self.dm.key_press_char("F1")
        self._war3.interruptible_wait(gt, stop_event)

        npc = self.palace_cfg["endless_npc"]
        point = npc["point"]
        coords = point["coords"]
        self._war3.move_to_minimap_point(
            point["mini_coords"],
            [coords[0] - 100, coords[1]],
            point["walk_mode"],
            point["time"],
            stop_event,
        )
        self.dm.move_to(*coords)
        self._war3.interruptible_wait(gt, stop_event)
        self.dm.left_click()
        self._war3.interruptible_wait(self.war3_cfg["small_window_response_time"], stop_event)

        npc_skill = npc["skill"]

        # 重置无尽层数（受 cd 限制）：min_level < 15 重置为 1 层，>= 15 重置为 15 层
        min_level = endless_cfg.get("min_level", 1)
        reset_type = 1 if min_level < 15 else 15
        grid_key = f"reset_{reset_type}_grid"
        reset_grid = npc_skill.get(grid_key)
        if reset_grid is None:
            logger.warning(f"未找到重置类型 {reset_type} 的 grid 配置（{grid_key}），跳过重置")
        else:
            reset_coords = self._ui.get_skill_coords(*reset_grid)
            wait_time = endless_cfg["wait_time"] - (time.time() - task.game_start_time)
            if wait_time > 0:
                logger.info(f"重置无尽层数为 {reset_type} 层，等待重置 cd，等待 {round(wait_time)}s")
                self._war3.interruptible_wait(wait_time, stop_event)
                self.dm.move_to(*reset_coords)
                self._war3.interruptible_wait(gt, stop_event)
                self.dm.left_click()
                self._war3.interruptible_wait(gt, stop_event)

        enter_coords = self._ui.get_skill_coords(*npc_skill["enter_grid"])
        self.dm.move_to(*enter_coords)
        self._war3.interruptible_wait(gt, stop_event)
        self.dm.left_click()
        self._war3.interruptible_wait(gt, stop_event)
