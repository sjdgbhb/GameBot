"""九种兵器2 业务子包。

延迟导入以避免在主环境（3.12 无 pywin32）中触发 win32com 依赖。
"""


def __getattr__(name):
    if name == "GameUI":
        from .game_ui import GameUI

        return GameUI
    if name == "SceneNavigator":
        from .scene_navigator import SceneNavigator

        return SceneNavigator
    if name == "CombatHelper":
        from .combat_helper import CombatHelper

        return CombatHelper
    if name == "get_inventory_hotkey":
        from .combat_helper import get_inventory_hotkey

        return get_inventory_hotkey
    if name == "get_inventory_hotkeys":
        from .combat_helper import get_inventory_hotkeys

        return get_inventory_hotkeys
    if name == "EndlessRunner":
        from .endless_runner import EndlessRunner

        return EndlessRunner
    if name == "NearbyCleaner":
        from .nearby_cleaner import NearbyCleaner

        return NearbyCleaner
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = [
    "GameUI",
    "SceneNavigator",
    "CombatHelper",
    "get_inventory_hotkey",
    "get_inventory_hotkeys",
    "EndlessRunner",
    "NearbyCleaner",
]
