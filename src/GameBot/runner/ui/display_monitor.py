import queue
import threading
import time

import win32api
import win32con
import win32gui


class DisplayChangeMonitor:
    """显示器变化监听器（与主脚本解耦）"""

    def __init__(self, callback_func):
        """
        :param callback_func: 当显示器变化时要调用的函数（在主线程中执行）
        """
        self.callback_func = callback_func
        self.running = False
        self.hwnd_listener = None
        self.wc = None
        self.callback_queue = queue.Queue()  # 线程安全队列

    def _window_proc(self, hwnd, msg, wparam, lparam):
        if msg == win32con.WM_DISPLAYCHANGE:
            # 将回调函数放入队列，让主线程去执行（避免COM线程问题）
            self.callback_queue.put(self.callback_func)
        return win32gui.DefWindowProc(hwnd, msg, wparam, lparam)

    def _listener_thread(self):
        """后台监听线程"""
        # 注册窗口类
        self.wc = win32gui.WNDCLASS()
        self.wc.lpfnWndProc = self._window_proc
        self.wc.lpszClassName = "War3DisplayMonitor"
        self.wc.hInstance = win32api.GetModuleHandle(None)
        class_atom = win32gui.RegisterClass(self.wc)

        # 创建隐藏窗口
        self.hwnd_listener = win32gui.CreateWindow(
            class_atom, "", 0, 0, 0, 0, 0, 0, 0, self.wc.hInstance, None
        )

        # 消息循环
        while self.running:
            win32gui.PumpWaitingMessages()
            time.sleep(0.05)

    def start(self):
        """启动监听（非阻塞）"""
        if self.running:
            return
        self.running = True
        thread = threading.Thread(target=self._listener_thread, daemon=True)
        thread.start()
        print("[DisplayMonitor] 显示器变化监听已启动")

    def stop(self):
        """停止监听"""
        self.running = False
        if self.hwnd_listener:
            win32gui.DestroyWindow(self.hwnd_listener)
            win32gui.UnregisterClass(self.wc.lpszClassName, self.wc.hInstance)
        print("[DisplayMonitor] 监听已停止")

    def process_callbacks(self):
        """在主线程循环中调用此方法，处理待执行的回调"""
        try:
            while True:
                callback = self.callback_queue.get_nowait()
                # 延迟1秒，确保系统显示重置完成
                threading.Timer(1.0, callback).start()
        except queue.Empty:
            pass