"""组队任务步骤基类 — 各任务模块继承此类实现 preparation / position_init / pre_exit / run_task。

通用框架，不绑定特定游戏（War3/Y3 等）。
各游戏需自行创建子类，提供游戏特定的默认实现。

设计要点：
- preparation: 默认无操作，子类按需覆盖（如选难度、选英雄、读档等准备流程）
- position_init: 默认无操作，子类按需覆盖（如进入特定地图场景）
- pre_exit: 默认无操作，子类按需覆盖（如发送存档指令）
- run_task: 抽象方法，子类必须实现（主任务循环）

使用方式（在任务模块中）：
    class _Steps(Jiubing2TaskSteps):
        def run_task(self, member, stop_event=None, **kwargs):
            ...

    _steps = _Steps()
    preparation = _steps.preparation
    position_init = _steps.position_init
    pre_exit = _steps.pre_exit
    run_task = _steps.run_task

这样模块级函数即为单例的绑定方法，供 steps 通过别名直接调用。
"""

from __future__ import annotations

import abc
import threading
from typing import Optional


class TeamTaskSteps(abc.ABC):
    """组队任务步骤基类 — 各任务模块继承并实现具体逻辑。

    方法签名约定：func(self, member, stop_event, **kwargs) -> None
    member 为 TeamMemberBase 实例，拥有 dm, war3, kk, task_cfg, member_cfg, task_ctx, ipc 等属性。
    失败时设置 member._flow_failed = True，框架自动跳过剩余步骤。
    """

    def preparation(self, member, stop_event: Optional[threading.Event] = None, **kwargs) -> None:
        """准备阶段 — 默认无操作，子类按需覆盖。

        典型场景：选难度 → 选英雄 → 读档 → 装备/技能准备。
        """
        pass

    def position_init(self, member, stop_event: Optional[threading.Event] = None, **kwargs) -> None:
        """就位 — 默认无操作，子类按需覆盖。

        典型场景：折叠属性面板 → 进入特定 NPC 区域 → 进入任务地图。
        """
        pass

    def pre_exit(self, member, stop_event: Optional[threading.Event] = None, **kwargs) -> None:
        """退出前 — 默认无操作，子类按需覆盖。

        典型场景：发送存档指令、清理物品等。
        """
        pass

    @abc.abstractmethod
    def run_task(self, member, stop_event: Optional[threading.Event] = None, **kwargs) -> None:
        """主任务循环 — 子类必须实现。

        失败时设置 member._flow_failed = True。
        """
        ...
