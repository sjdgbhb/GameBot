"""大漠脚本运行器 — 32 位 Python 3.8 环境下的自动化脚本包。

包含：
- dm_client.py       — 大漠插件 COM 封装
- resource_manager.py — 资源路径管理
- ui/                — 浮窗、热键等用户界面
- business/          — 游戏业务逻辑（KK、War3、九种兵器2）
- tasks/             — 任务编排

注意：DmClient 延迟导入，避免在主环境（3.12，无 pywin32）中
import GameBot.runner 时触发 win32com 依赖。
"""


def __getattr__(name):
    if name == "DmClient":
        from .dm_client import DmClient

        return DmClient
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = ["DmClient"]
