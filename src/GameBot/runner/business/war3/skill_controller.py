"""技能施放 — 从 war3.py 拆分。

包含 War3Business 的技能施放 mixin：单技能施放、连招执行。
"""
import threading
from typing import List, Dict, Optional


class SkillControllerMixin:
    """War3Business 的技能施放 mixin。

    依赖 self.dm（DmClient）和 self.war3_cfg（dict）。
    """

    def cast_skill(self, skill_cfg: dict, coords=None, target_coords=None,
                   stop_event: Optional[threading.Event] = None):
        """
        施放技能

        :param skill_cfg: 技能配置，含 key、target_type、可选 target_coords、可选 cast_time
        :param coords: 英雄坐标（未指定 target_coords 时的默认点击位置）
        :param target_coords: 指定技能施放点击坐标（覆盖 skill_cfg 中的 target_coords）
        :param stop_event: 停止事件，设置时中断等待
        """
        cast_move_time = self.war3_cfg['cast_move_time']
        target_type = skill_cfg['target_type']
        key = skill_cfg['key']
        # 优先使用传入的 target_coords，其次使用技能配置中的 target_coords，最后用英雄坐标
        click_coords = target_coords or skill_cfg.get('target_coords') or coords

        if target_type in ('ground', 'enemy', 'ally'):
            if click_coords is not None:
                self.dm.move_to(*click_coords)
                self.interruptible_wait(cast_move_time, stop_event)
            self.dm.key_press_char(key)
            self.interruptible_wait(cast_move_time, stop_event)
            self.dm.left_click()
        elif target_type == 'self':
            self.dm.key_press_char(key)
        else:
            raise ValueError(f"未知的 target_type: {target_type}")

        # 施放后等待（技能动画/前摇后摇），默认不等
        cast_time = skill_cfg.get('cast_time')
        if cast_time:
            self.interruptible_wait(cast_time, stop_event)

    def execute_combo(self, combo_cfg: List[Dict], coords=None, target_coords=None,
                      stop_event: Optional[threading.Event] = None):
        """
        连招
        :combo_cfg: combo配置
        :param coords: 英雄坐标
        :param target_coords: 指定技能施放点击坐标，此配置忽略direction、coords
        :param stop_event: 停止事件，设置时中断等待
        :return:
        """
        for idx, skill_cfg in enumerate(combo_cfg):
            self.cast_skill(skill_cfg, coords, target_coords, stop_event)
            if idx < len(combo_cfg) - 1:
                # 优先用技能自身的 cast_time 作为间隔，否则用全局 fast_skill_time
                gap = skill_cfg.get('cast_time') or self.war3_cfg['fast_skill_time']
                self.interruptible_wait(gap, stop_event)
