"""大漠脚本运行器 — 自动化脚本包（64 位主环境经 dm_bridge 调用大漠 COM）。

包含：
- driver/            — 大漠驱动（bridge RPC 子进程，工厂 create_dm_client）
- resource_manager.py — 资源路径管理
- ui/                — 浮窗等用户界面
- business/          — 游戏业务逻辑（KK、War3、九种兵器2）
- tasks/             — 任务编排

注意：大漠客户端通过 create_dm_client 工厂创建，返回 DmBridgeClient 实例。
"""


def __getattr__(name):
    if name == "create_dm_client":
        from .driver import create_dm_client

        return create_dm_client
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = ["create_dm_client"]
