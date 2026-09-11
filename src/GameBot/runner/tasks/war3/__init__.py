"""War3 任务子包 — 委托给具体地图子包。"""


def __getattr__(name):
    if name in (
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
    ):
        from GameBot.runner.tasks.war3 import jiubing2

        return getattr(jiubing2, name)
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
