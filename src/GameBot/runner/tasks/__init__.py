"""任务包 — 按游戏/地图组织的任务编排模块。

通过 war3.jiubing2 子包暴露具体任务类，供 main.py 等入口动态加载。
延迟导入以避免在主环境（3.12 无 pywin32）中触发 win32com 依赖。
"""


def __getattr__(name):
    # 委托给 war3.jiubing2 子包
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
        from GameBot.runner.tasks import war3 as war3_tasks

        return getattr(war3_tasks, name)
    if name == "TeamTaskRunner":
        from GameBot.runner.tasks.team.team_task import TeamTaskRunner

        return TeamTaskRunner
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
    "TeamTaskRunner",
]
