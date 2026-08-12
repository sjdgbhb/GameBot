"""
战斗辅助 — 技能筛选、连招执行、物品快捷栏、喂宠物、魔法水晶。
纯工具层，无任务编排逻辑，被无尽循环和原子任务共享。
"""
from __future__ import annotations

import random
import time
import threading
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from GameBot.runner.dm_client import DmClient
from GameBot.utils import logger


def get_inventory_hotkey(hero_cfg: dict, item_id: int) -> str:
    """根据物品 id 查找背包快捷键（随机返回一个匹配项）。

    :param hero_cfg: 英雄配置（含 inventory 列表）
    :param item_id: 物品 id
    :return: 快捷键字符，未找到返回空字符串
    """
    hotkeys = get_inventory_hotkeys(hero_cfg, item_id)
    return random.choice(hotkeys) if hotkeys else ''


def get_inventory_hotkeys(hero_cfg: dict, item_id: int) -> list:
    """根据物品 id 查找背包中所有匹配格子上的快捷键。

    用于同一物品放在多个格子时，依次使用不同快捷键。

    :param hero_cfg: 英雄配置（含 inventory 列表）
    :param item_id: 物品 id
    :return: 快捷键字符列表
    """
    return [item.get('hotkey', '') for item in hero_cfg.get('inventory', []) if item.get('id') == item_id and item.get('hotkey')]


class CombatHelper:
    """战斗中的通用辅助操作。

    负责技能配置解析、连招执行、物品使用、宠物喂食。
    依赖 _war3（War3Business）提供 execute_combo / use_inventory_item 等基础操作。
    """

    def __init__(self, dm: DmClient, war3_cfg: dict, hero_cfg: dict, cfg: dict, war3):
        """
        :param dm: DmClient
        :param war3_cfg: war3 配置（cast_move_time 等）
        :param hero_cfg: 英雄配置（技能列表、背包物品）
        :param cfg: 任务依赖闭包配置（load_task 结果，含 game/pet 等段）
        :param war3: War3Business 实例
        """
        self.dm = dm
        self.war3_cfg = war3_cfg
        self.hero_cfg = hero_cfg
        self.cfg = cfg
        self.game_cfg = cfg.get('game', {})
        self._war3 = war3

    def resolve_point_skills(self, point_skills) -> list:
        """将路线点的技能配置与英雄技能池合并，返回完整技能列表。

        路线点通过 skill id 引用英雄 hero.skills 中的技能，可额外指定 key、target_coords。
        若英雄技能池中不存在该 id，但路线点提供了 key 和 target_type，则按自定义技能处理。

        :param point_skills: 点位技能配置列表（[{id, key?, target_type?, target_coords?}, ...]）
        :return: 合并后的技能配置列表（含 key, desc, target_type, target_coords 等完整字段）
        """
        if not point_skills:
            return []
        skill_map = {s['id']: s for s in self.hero_cfg.get('skills', [])}
        result = []
        for skill_cfg in point_skills:
            sid = skill_cfg['id']
            if sid in skill_map:
                skill_data = skill_map[sid].copy()
                skill_data['target_coords'] = skill_cfg.get('target_coords')
                if skill_cfg.get('key') and skill_map[sid].get('fixed_key'):
                    skill_data['key'] = skill_cfg['key']
                if skill_cfg.get('position'):
                    skill_data['position'] = skill_cfg['position']
                if skill_cfg.get('cast_time') is not None:
                    skill_data['cast_time'] = skill_cfg['cast_time']
                result.append(skill_data)
            elif skill_cfg.get('key') and skill_cfg.get('target_type'):
                skill_data = {
                    'id': sid,
                    'key': skill_cfg['key'],
                    'desc': skill_cfg.get('desc', f'技能{sid}'),
                    'target_type': skill_cfg['target_type'],
                    'target_coords': skill_cfg.get('target_coords'),
                    'position': skill_cfg.get('position', ''),
                    'cast_time': skill_cfg.get('cast_time'),
                }
                result.append(skill_data)
            else:
                logger.warning(f'技能 id "{sid}" 未在英雄技能池中找到，且缺少快捷键/目标类型，跳过')
        return result

    def log_and_execute_combo(self, skills: list, coords: list, desc: str,
                               stop_event: Optional[threading.Event] = None):
        """执行连招并记录耗时。

        :param skills: 技能配置列表
        :param coords: 技能施放坐标（英雄当前屏幕位置）
        :param desc: 日志描述
        :param stop_event: 停止事件，设置时中断等待
        :return: (t_start, t_end) 始终返回时间元组，无技能时返回当前时间
        """
        if not skills:
            return time.time(), time.time()
        logger.info(desc)
        t_start = time.time()
        self._war3.execute_combo(skills, coords, stop_event=stop_event)
        t_end = time.time()
        logger.debug(f'技能施放耗时 {t_end - t_start:.3f}s')
        return t_start, t_end

    def feed_pet(self, task, stop_event: Optional[threading.Event] = None):
        """喂宠物。

        根据 pet 配置段的 feeding_interval（分钟）判断是否需要喂食。
        需要喂时按物品栏9号位快捷键，并更新 task.pet_feed_time。

        :param task: 任务对象（需有 pet_feed_time 属性）
        :param stop_event: 停止事件，设置时中断等待
        """
        passed_time = round(time.time() - task.pet_feed_time)
        feeding_interval = self.cfg.get('pet', {}).get('feeding_interval', 10) * 60
        if passed_time >= feeding_interval:
            logger.info(f'喂食宠物（距上次喂食已过 {passed_time}s，间隔 {feeding_interval}s）')
            hotkeys = get_inventory_hotkeys(self.hero_cfg, 9)
            if hotkeys:
                hotkey = random.choice(hotkeys)
                self._war3.use_inventory_item(hotkey, stop_event)
            task.pet_feed_time = time.time()

    def execute_actions(self, pt: dict, hero_coords: list = None,
                         stop_event: Optional[threading.Event] = None):
        """按顺序执行路线点的 actions 列表。

        每个 action 的 type 决定执行方式：
        - "msg": 发送聊天信息（content 为文本）
        - "skill": 施放技能（id 引用英雄技能，target_coords 可选）
        - "item": 使用物品（id 引用物品栏，coords 可选，有则 move_to→key→click）

        连续的 skill action 会分组合并为一次 execute_combo 调用，
        确保技能之间有 fast_skill_time 延迟，避免英雄还在施法时下一个技能被吞。

        :param pt: 路线点配置，actions 为 action 列表
        :param hero_coords: 英雄当前屏幕坐标（技能默认点击位置）
        :param stop_event: 停止事件，设置时中断等待
        """
        actions = pt.get('actions')
        if not actions:
            return
        pending_skills = []  # 缓冲连续的 skill action
        base_coords = hero_coords or pt.get('coords', [0, 0])

        def flush_skills():
            """将缓冲的 skill action 合并为一次 execute_combo 调用。"""
            if not pending_skills:
                return
            skills = self.resolve_point_skills(pending_skills)
            if skills:
                descs = ' + '.join(s.get('desc', '') for s in skills)
                self.log_and_execute_combo(skills, base_coords, f'施放连招：{descs}',
                                           stop_event=stop_event)
            pending_skills.clear()

        for act in actions:
            if not act:
                continue
            act_type = act.get('type')
            if act_type == 'skill':
                pending_skills.append(act)
            elif act_type == 'msg':
                flush_skills()
                content = act.get('content', '')
                if content:
                    logger.info(f'发送信息：{content}')
                    self._war3.send_msg(content, stop_event=stop_event)
                    self._war3.interruptible_wait(self.war3_cfg['key_time'], stop_event)
            elif act_type == 'item':
                flush_skills()
                item_id = act.get('id')
                coords = act.get('coords')
                cast_time = act.get('cast_time')
                if item_id is None:
                    continue
                hotkeys = get_inventory_hotkeys(self.hero_cfg, int(item_id))
                if not hotkeys:
                    logger.warning(f'物品 id {item_id} 未在物品栏中找到，跳过')
                    continue
                hotkey = random.choice(hotkeys)
                if coords:
                    logger.info(f'使用物品（目标坐标）：{hotkey} → {coords}')
                    self.dm.move_to(*coords)
                    self.dm.key_press_char(hotkey)
                    self._war3.interruptible_wait(self.war3_cfg['key_time'], stop_event)
                    self.dm.left_click()
                else:
                    logger.info(f'使用物品：{hotkey}')
                    self._war3.use_inventory_item(hotkey, stop_event)
                # 施放后等待（物品动画/施放延迟），默认只等 key_time
                self._war3.interruptible_wait(
                    cast_time if cast_time is not None else self.war3_cfg['key_time'], stop_event)
            else:
                flush_skills()
                logger.warning(f'未知 action 类型：{act_type}，跳过')
        flush_skills()
