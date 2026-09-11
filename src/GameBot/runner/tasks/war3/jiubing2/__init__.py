"""九种兵器2 任务子包 — 延迟导入任务类以避免 win32com 依赖。"""


def __getattr__(name):
    if name == "FishingTask":
        from GameBot.runner.tasks.war3.jiubing2.others.fishing import FishingTask

        return FishingTask
    if name == "EndlessTask":
        from GameBot.runner.tasks.war3.jiubing2.endless.endless import EndlessTask

        return EndlessTask
    if name == "EndlessSingleTask":
        from GameBot.runner.tasks.war3.jiubing2.endless.endless_single import EndlessSingleTask

        return EndlessSingleTask
    if name == "PatrolLootTask":
        from GameBot.runner.tasks.war3.jiubing2.others.patrol_loot import PatrolLootTask

        return PatrolLootTask
    if name == "PaladinWindDragonTask":
        from GameBot.runner.tasks.war3.jiubing2.others.paladin_wind_dragon import PaladinWindDragonTask

        return PaladinWindDragonTask
    if name == "UpgradeStigmataTask":
        from GameBot.runner.tasks.war3.jiubing2.others.upgrade_stigmata import UpgradeStigmataTask

        return UpgradeStigmataTask
    if name == "DailyReputationTask":
        from GameBot.runner.tasks.war3.jiubing2.reputation.daily_reputation import DailyReputationTask

        return DailyReputationTask
    if name == "BlackstoneReputationTask":
        from GameBot.runner.tasks.war3.jiubing2.reputation.blackstone_reputation import BlackstoneReputationTask

        return BlackstoneReputationTask
    if name == "ForestReputationTask":
        from GameBot.runner.tasks.war3.jiubing2.reputation.forest_reputation import ForestReputationTask

        return ForestReputationTask
    if name == "IngameSpecialTask":
        from GameBot.runner.tasks.war3.jiubing2.festival.ingame_special import IngameSpecialTask

        return IngameSpecialTask
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = [
    "FishingTask",
    "EndlessTask",
    "EndlessSingleTask",
    "PatrolLootTask",
    "PaladinWindDragonTask",
    "UpgradeStigmataTask",
    "DailyReputationTask",
    "BlackstoneReputationTask",
    "ForestReputationTask",
    "IngameSpecialTask",
]
