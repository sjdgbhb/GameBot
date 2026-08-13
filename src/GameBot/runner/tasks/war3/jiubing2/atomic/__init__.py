"""原子任务包 — 提供原子任务类注册表。

注册表 ATOMIC_TASK_REGISTRY 将配置 key（如 "blackstone_gate_harassment"）
映射到对应的原子任务类，供 MultiAtomicLoopTask 等编排类查找。
新增原子任务时，在此处注册即可。
"""

from GameBot.runner.tasks.war3.jiubing2.atomic.blackstone_gate_harassment import GateHarassmentTask
from GameBot.runner.tasks.war3.jiubing2.atomic.little_flame_snake import LittleFlameSnakeTask
from GameBot.runner.tasks.war3.jiubing2.atomic.snake_egg import SnakeEggTask
from GameBot.runner.tasks.war3.jiubing2.atomic.swift_beast import SwiftBeastTask
from GameBot.runner.tasks.war3.jiubing2.atomic.venomous_snake import VenomousSnakeTask

ATOMIC_TASK_REGISTRY = {
    "blackstone_gate_harassment": GateHarassmentTask,
    "swift_beast": SwiftBeastTask,
    "venomous_snake": VenomousSnakeTask,
    "snake_egg": SnakeEggTask,
    "little_flame_snake": LittleFlameSnakeTask,
}

__all__ = [
    "ATOMIC_TASK_REGISTRY",
    "GateHarassmentTask",
    "SwiftBeastTask",
    "VenomousSnakeTask",
    "SnakeEggTask",
    "LittleFlameSnakeTask",
]
