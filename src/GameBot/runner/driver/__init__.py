"""大漠驱动包 — 主环境（Python 3.12）经 dm_bridge 子进程调用大漠 COM。

结构：
- base.py      — DmClientBase：全部业务 API（基于 _com_call 原语组合）
- bridge.py    — DmBridgeClient：64 位主环境经 dm_bridge 子进程 RPC 驱动
- registrar.py — DmRegistrar：dm.dll COM 注册（含 UAC 提权）

使用：
    from GameBot.runner.driver import create_dm_client
    dm = create_dm_client()   # 返回 DmBridgeClient 实例
"""

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from GameBot.runner.driver.base import DmClientBase


def create_dm_client() -> "DmClientBase":
    """创建大漠驱动实例（DmBridgeClient）。

    主环境（Python 3.12，64 位）无法直接加载 32 位大漠 COM，
    统一经 dm_bridge 子进程（32 位 Python 3.8）RPC 调用。

    :return: DmBridgeClient 实例
    """
    from GameBot.runner.driver.bridge import DmBridgeClient

    return DmBridgeClient()


def __getattr__(name):
    """懒加载导出，避免在不需要时触发 win32com / 子进程依赖。"""
    if name == "DmClientBase":
        from GameBot.runner.driver.base import DmClientBase

        return DmClientBase
    if name == "DmBridgeClient":
        from GameBot.runner.driver.bridge import DmBridgeClient

        return DmBridgeClient
    if name == "DmRegistrar":
        from GameBot.runner.driver.registrar import DmRegistrar

        return DmRegistrar
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = ["create_dm_client", "DmClientBase", "DmBridgeClient", "DmRegistrar"]
