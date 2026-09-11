"""UI 子包 — 浮窗、显示器监听等用户界面工具。

延迟导入以避免在主环境（3.12 无 pywin32）中触发 win32 依赖。

子模块：
- float_window.py    — 任务运行控制（Tkinter 暗黑弹窗 + 倒计时 + 小键盘减号停止）
- display_monitor.py — 显示器变化监听器
"""


def __getattr__(name):
    if name == "run_with_float_window":
        from .float_window import run_with_float_window

        return run_with_float_window
    if name == "DisplayChangeMonitor":
        from .display_monitor import DisplayChangeMonitor

        return DisplayChangeMonitor
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = ["run_with_float_window", "DisplayChangeMonitor"]
