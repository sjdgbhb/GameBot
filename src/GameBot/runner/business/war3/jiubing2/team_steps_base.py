"""九种兵器2 组队任务步骤基类 — 在通用 TeamTaskSteps 基础上提供九兵特有的 preparation 默认实现。

preparation: 选难度 → 等初始化 → 选英雄 → 读档 → 圣痕 → 卡牌 → 神碎 → 学技能。
pre_exit: 无默认实现（仅个别任务需要存档，由子类按需覆盖）。
各任务模块继承此类，实现 run_task，按需覆盖 position_init / pre_exit。

使用方式（在任务模块中）：
    class _Steps(Jiubing2TaskSteps):
        def run_task(self, member, stop_event=None, **kwargs):
            ...

    _steps = _Steps()
    preparation = _steps.preparation
    position_init = _steps.position_init
    pre_exit = _steps.pre_exit
    run_task = _steps.run_task
"""

from __future__ import annotations

import threading
import time
from typing import Optional

from GameBot.runner.business.war3.jiubing2 import CombatHelper, EndlessRunner, GameUI, SceneNavigator
from GameBot.runner.team.steps_base import TeamTaskSteps
from GameBot.utils import StopTaskError, logger


def _build_business_objects(member):
    """从 member 实例构建九兵业务对象（GameUI / SceneNavigator / CombatHelper / EndlessRunner）。

    首次构建后缓存到 member._jiubing2_biz，后续调用直接复用，避免重复创建。

    :param member: TeamMemberBase 实例
    :return: (ui, nav, combat, runner)
    """
    cached = getattr(member, "_jiubing2_biz", None)
    if cached is not None:
        return cached
    war3_cfg = member.task_cfg.get("war3", {})
    hero_cfg = member.task_cfg.get("hero", {})
    ui = GameUI(member.dm, war3_cfg, hero_cfg, member.task_cfg, member.war3)
    nav = SceneNavigator(member.dm, war3_cfg, hero_cfg, member.task_cfg, member.war3, ui)
    combat = CombatHelper(member.dm, war3_cfg, hero_cfg, member.task_cfg, member.war3)
    runner = EndlessRunner(member.dm, member.war3, ui, combat, war3_cfg, hero_cfg, member.task_cfg)
    member._jiubing2_biz = (ui, nav, combat, runner)
    return member._jiubing2_biz


def _wait_game_state(member, target_phase: str, stop_event: Optional[threading.Event] = None, timeout: float = 120):
    """非队长成员等待队长广播指定 game_state phase。"""
    start = time.time()
    while time.time() - start < timeout:
        if stop_event and stop_event.is_set():
            raise StopTaskError("用户请求停止任务")
        game_state = member.ipc.read_game_state(timeout=0.5, poll_interval=0.5)
        if game_state and game_state.get("phase") == target_phase and game_state.get("round") == member._current_round:
            logger.info(f"game_state 进入 {target_phase}")
            return
    raise TimeoutError(f"等待 game_state phase={target_phase} 超时（{timeout}s）")


class Jiubing2TaskSteps(TeamTaskSteps):
    """九种兵器2 组队任务步骤基类 — 提供 preparation 默认实现。"""

    def preparation(self, member, stop_event: Optional[threading.Event] = None, **kwargs) -> None:
        """九兵通用准备阶段。

        顺序：选难度 → 等游戏初始化 → 选英雄 → 读档 → 圣痕 → 卡牌 → 神碎 → 学技能。
        队长负责选难度并广播 game_state=in_game，队员等待该信号后再执行剩余准备。
        """
        ui, nav, combat, runner = _build_business_objects(member)
        # 合并任务配置与成员配置：成员配置优先，kwargs 最高优先
        task_cfg = dict(member.task_cfg)
        task_cfg.update(member.member_cfg)
        if "difficulty" in kwargs:
            task_cfg["difficulty"] = kwargs["difficulty"]

        is_leader = member.get_role() == "leader"
        if is_leader:
            ui.select_difficulty(task_cfg)
            member.ipc.write_game_state(
                phase="in_game",
                sync_source=member.sync_source,
                round_num=member._current_round,
            )
            logger.info("队长已选难度，广播 game_state=in_game")
        else:
            logger.info("等待队长选择难度...")
            _wait_game_state(member, "in_game", stop_event)

        logger.info("开始九兵通用准备阶段")
        runner.do_preparation_phase(task_cfg, stop_event, skip_select_difficulty=True)
        logger.info("九兵通用准备阶段完成")
