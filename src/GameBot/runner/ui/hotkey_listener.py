"""全局热键监听器 —— 在游戏内一键启停脚本。

使用 Windows API GetAsyncKeyState 轮询按键状态，无需消息循环，
后台守护线程运行，不影响主线程的 COM 操作。

默认热键：
  F7  → 开始任务
  F6  → 停止任务

使用方式：
  listener = HotkeyListener()
  listener.start()
  listener.wait_for_start()   # 阻塞等待 F7
  listener.wait_for_start()   # 再次等待 F7（停止后重新开始）
  # 在任务循环中检查：
  if listener.is_stop_requested():
      break
  listener.stop()             # 关闭监听线程
"""
import ctypes
import threading
import time

# 虚拟键码
VK_F7 = 0x76
VK_F6 = 0x75

_user32 = ctypes.windll.user32


class HotkeyListener:
    """全局热键监听器，后台线程轮询按键边沿触发。"""

    def __init__(self, start_key: int = VK_F7, stop_key: int = VK_F6):
        self._start_key = start_key
        self._stop_key = stop_key
        self._start_event = threading.Event()
        self._stop_event = threading.Event()
        self._thread = None
        self._running = False

    def start(self):
        """启动后台轮询线程。"""
        if self._thread is not None and self._thread.is_alive():
            return
        self._running = True
        self._thread = threading.Thread(target=self._poll_loop, daemon=True, name="HotkeyListener")
        self._thread.start()

    def _poll_loop(self):
        prev_start = False
        prev_stop = False
        while self._running:
            # GetAsyncKeyState 返回 short，最高位为 1 表示当前按下
            cur_start = bool(_user32.GetAsyncKeyState(self._start_key) & 0x8000)
            cur_stop = bool(_user32.GetAsyncKeyState(self._stop_key) & 0x8000)

            # 边沿检测：按下瞬间触发（前一帧未按、当前帧按下）
            if cur_start and not prev_start:
                self._start_event.set()
            if cur_stop and not prev_stop:
                self._stop_event.set()

            prev_start = cur_start
            prev_stop = cur_stop
            time.sleep(0.05)

    def wait_for_start(self, timeout: float = None) -> bool:
        """阻塞等待开始热键被按下。"""
        triggered = self._start_event.wait(timeout=timeout)
        if triggered:
            self._start_event.clear()
        return triggered

    def is_stop_requested(self) -> bool:
        """检查是否收到了停止信号（非阻塞）。"""
        return self._stop_event.is_set()

    def clear_stop(self):
        """清除停止信号（重新开始任务前调用）。"""
        self._stop_event.clear()

    @property
    def stop_event(self) -> threading.Event:
        """直接暴露 Event 对象，供任务循环检查。"""
        return self._stop_event

    def stop(self):
        """停止监听线程。"""
        self._running = False
        if self._thread is not None:
            self._thread.join(timeout=1)
