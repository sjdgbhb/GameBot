"""War3 业务子包 — 魔兽争霸3 通用业务逻辑。

延迟导入以避免在主环境（3.12 无 pywin32）中触发 win32com 依赖。

导出：
- War3Business — 组合所有 mixin 的主类
- TextMonitor  — 常驻 OCR 监测类
"""


def __getattr__(name):
    if name == "War3Business":
        from .core import War3Business

        return War3Business
    if name == "TextMonitor":
        from .core import TextMonitor

        return TextMonitor
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = ["War3Business", "TextMonitor"]
