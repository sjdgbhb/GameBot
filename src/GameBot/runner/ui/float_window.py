"""任务运行控制 — Tkinter 暗黑风格弹窗 + 快捷键停止。

在子线程中运行任务，主线程显示 Tkinter 弹窗并监听小键盘减号（NumPad-）停止信号。
启动前有倒计时，按小键盘减号可随时停止任务。
任务通过 progress_callback 回调报告进度信息。

使用方式：
  from GameBot.runner.ui import run_with_float_window

  def task_func(stop_event, progress_callback):
      progress_callback("成功 3 / 40")
      while not stop_event.is_set():
          ...

  run_with_float_window("钓鱼", task_func)
"""
import inspect
import threading
import time
import ctypes
import tkinter as tk
from typing import Callable, List, Optional

from GameBot.utils import StopTaskError


_VK_NUMPAD_SUBTRACT = 0x6D  # 小键盘减号
_user32 = ctypes.windll.user32

# 暗黑主题配色（与 Web 端一致）
_BG = "#0a0a12"
_BG_ELEVATED = "#121220"
_CARD_BG = "#1a1a2c"
_CARD_BORDER = "#4a4a6a"
_GOLD = "#d4af37"
_GOLD_BRIGHT = "#f0c040"
_TEXT = "#f0f0f5"
_TEXT_DIM = "#a0a0c0"
_DANGER = "#e74c3c"
_SUCCESS = "#27ae60"


def run_with_float_window(
    title: str,
    task_func: Callable,
    countdown_seconds: int = 5,
    initial_progress: str = "",
    win_x: Optional[int] = None,
    win_y: Optional[int] = None,
    float_cfg: Optional[dict] = None,
):
    """启动倒计时后在线程中运行任务，显示 Tkinter 弹窗并监听小键盘减号停止。

    :param title: 任务名称（用于弹窗标题和日志）
    :param task_func: 任务函数，接收 (stop_event, progress_callback) 参数；
                      若函数签名包含 progress_lines_callback，则额外传入多行进度回调
    :param countdown_seconds: 启动前倒计时秒数
    :param win_x: 浮窗 x 坐标（优先级高于 float_cfg）
    :param win_y: 浮窗 y 坐标（优先级高于 float_cfg）
    :param float_cfg: 浮窗配置字典（如 base.toml 中的 [float_window]），从中读取 x/y
    """
    win_w_cfg = None
    if float_cfg:
        if win_x is None:
            win_x = float_cfg.get("x")
        if win_y is None:
            win_y = float_cfg.get("y")
        win_w_cfg = float_cfg.get("width")
    stop_event = threading.Event()
    progress_text = {"value": initial_progress}
    progress_lines = {"value": []}
    progress_lock = threading.Lock()

    def progress_callback(text: str):
        with progress_lock:
            progress_text["value"] = text

    def progress_lines_callback(lines: List[str]):
        with progress_lock:
            progress_lines["value"] = lines

    # NumPad- 全局热键轮询
    def _poll_stop_key():
        prev = False
        while not stop_event.is_set():
            cur = bool(_user32.GetAsyncKeyState(_VK_NUMPAD_SUBTRACT) & 0x8000)
            if cur and not prev:
                stop_event.set()
                break
            prev = cur
            time.sleep(0.05)
    stop_key_thread = threading.Thread(target=_poll_stop_key, daemon=True, name="StopKeyListener")
    stop_key_thread.start()

    # 倒计时阶段
    countdown_active = True

    def _run_task():
        # 等待倒计时结束
        while countdown_active and not stop_event.is_set():
            time.sleep(0.1)
        if stop_event.is_set():
            return
        try:
            sig = inspect.signature(task_func)
            if 'progress_lines_callback' in sig.parameters or any(
                p.kind == p.VAR_KEYWORD for p in sig.parameters.values()
            ):
                task_func(stop_event, progress_callback, progress_lines_callback=progress_lines_callback)
            else:
                task_func(stop_event, progress_callback)
        except StopTaskError:
            pass  # 任务已被用户停止
        except Exception as e:
            progress_callback(f"任务异常: {e}")
            raise

    task_thread = threading.Thread(target=_run_task, daemon=True, name="TaskThread")
    task_thread.start()

    # ===== Tkinter 弹窗 =====
    root = tk.Tk()
    root.overrideredirect(True)  # 无原生标题栏
    root.configure(bg=_CARD_BORDER)  # 深色边框底
    root.attributes("-topmost", True)

    # 窗口大小和位置：左侧，垂直 1/4 处
    # 有多行进度时自动增高
    _lines_h = 0  # 会在 _refresh_lines 中动态调整
    win_w = win_w_cfg if win_w_cfg else 300
    win_h_base = 70
    win_h = win_h_base
    screen_w = root.winfo_screenwidth()
    screen_h = root.winfo_screenheight()
    x = win_x if win_x is not None else 20
    y = win_y if win_y is not None else (screen_h - win_h) // 6 + 250
    root.geometry(f"{win_w}x{win_h}+{x}+{y}")

    # 内层容器，留 1px 边框
    inner = tk.Frame(root, bg=_BG, highlightbackground="#6a5a20", highlightthickness=1)
    inner.pack(fill=tk.BOTH, expand=True)

    # 自定义金色标题栏
    title_bar = tk.Frame(inner, bg=_GOLD, height=20)
    title_bar.pack(fill=tk.X)
    title_label = tk.Label(
        title_bar, text=f"{title}  停止按Num-", font=("Microsoft YaHei", 9, "bold"),
        bg=_GOLD, fg=_BG, anchor="w",
    )
    title_label.pack(side=tk.LEFT, padx=6)

    # 标题栏右侧停止提示（按 Num- 后显示）
    stop_hint = tk.Label(
        title_bar, text="", font=("Microsoft YaHei", 9, "bold"),
        bg=_GOLD, fg=_DANGER, anchor="e",
    )
    stop_hint.pack(side=tk.RIGHT, padx=6)

    # 上行：时间 + 进度（左对齐，金色）
    top_label = tk.Label(
        inner, text=f"{countdown_seconds}s  {initial_progress}", font=("Microsoft YaHei", 10),
        bg=_BG, fg=_GOLD, anchor="w",
    )
    top_label.pack(fill=tk.X, padx=10, pady=(6, 4))

    # 多行进度区域（用于显示各装备拾取进度等）
    max_lines = 8  # 最多显示 7 件装备 + 1 行 "..."
    lines_frame = tk.Frame(inner, bg=_BG)
    lines_frame.pack(fill=tk.X, padx=10, pady=(0, 4))
    line_labels: List[tk.Label] = []

    def _refresh_lines():
        nonlocal win_h
        with progress_lock:
            lines_data = list(progress_lines["value"])
        # 超出最大行数时截断，末行显示 "..."
        if len(lines_data) > max_lines:
            lines_data = lines_data[:max_lines - 1] + ["..."]
        # 调整 Label 数量
        while len(line_labels) < len(lines_data):
            lbl = tk.Label(
                lines_frame, text="", font=("Microsoft YaHei", 10),
                bg=_BG, fg=_GOLD, anchor="w",
            )
            lbl.pack(fill=tk.X)
            line_labels.append(lbl)
        while len(line_labels) > len(lines_data):
            lbl = line_labels.pop()
            lbl.destroy()
        # 更新文本（统一金色）
        for lbl, text in zip(line_labels, lines_data):
            lbl.config(text=text, fg=_GOLD)
        # 动态调整窗口高度和位置
        new_h = win_h_base + len(lines_data) * 24
        if new_h != win_h:
            win_h = new_h
            new_y = win_y if win_y is not None else (screen_h - win_h) // 6 + 250
            root.geometry(f"{win_w}x{win_h}+{x}+{new_y}")

    start_time = [None]
    countdown_started = [False]

    def _update():
        if stop_event.is_set():
            stop_hint.config(text="正在停止...")
            root.update_idletasks()
            if task_thread.is_alive():
                task_thread.join(timeout=10)
            root.after(500, root.destroy)
            return

        if countdown_active:
            # 倒计时由 _do_countdown 单独驱动，这里只检查是否需要启动倒计时
            if not countdown_started[0]:
                countdown_started[0] = True
                _do_countdown(countdown_seconds)
        else:
            # 更新运行时间
            if start_time[0] is not None:
                elapsed = time.time() - start_time[0]
                h = int(elapsed // 3600)
                m = int((elapsed % 3600) // 60)
                s = int(elapsed % 60)
                with progress_lock:
                    prog = progress_text["value"]
                top_label.config(text=f"{h:02d}:{m:02d}:{s:02d}  {prog}", fg=_GOLD)
                _refresh_lines()

            if not task_thread.is_alive():
                root.after(1000, root.destroy)
                return

        root.after(200, _update)

    def _do_countdown(remaining):
        if stop_event.is_set() or not countdown_active:
            return
        if remaining <= 0:
            _start_running()
            return
        with progress_lock:
            prog = progress_text["value"]
        top_label.config(text=f"{remaining}s  {prog}", fg=_GOLD)
        root.after(1000, lambda: _do_countdown(remaining - 1))

    def _start_running():
        nonlocal countdown_active
        countdown_active = False
        start_time[0] = time.time()

    root.after(100, _update)
    root.mainloop()

    # 确保任务线程结束
    stop_event.set()
    if task_thread.is_alive():
        task_thread.join(timeout=10)
