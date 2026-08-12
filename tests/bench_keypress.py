"""
测量不同按键方式的耗时，并验证游戏是否能识别
用法：切到魔兽窗口后运行 uv run python tests/bench_keypress.py
"""
import time
import ctypes

from GameBot.config import config
from GameBot.runner import DmClient
from GameBot.runner.business.war3 import War3Business

user32 = ctypes.windll.user32

def post_message_key(hwnd, key_code, key_up=False):
    """用 PostMessage 发送 WM_KEYDOWN/WM_KEYUP"""
    msg = 0x0101 if key_up else 0x0100  # WM_KEYUP / WM_KEYDOWN
    user32.PostMessageW(hwnd, msg, key_code, 0)

def main():
    time.sleep(5)
    cfg = config.load_task("war3.jiubing2.tasks.fishing")
    dm = DmClient()
    war3 = War3Business(dm, cfg.get("war3", {}))

    hwnd = dm.get_active_window()
    with dm.bind_window(hwnd, display='gdi'):
        war3.set_client_size(hwnd)
        try:
            ctypes.windll.winmm.timeBeginPeriod(1)
        except Exception:
            pass

        # 'S' 键的虚拟键码
        VK_S = 0x53
        N = 100

        # 1. dm.key_press_char（当前方案）
        t0 = time.perf_counter()
        for _ in range(N):
            dm.key_press_char("s")
        elapsed = time.perf_counter() - t0
        print(f"[key_press_char]      {N}次  平均 {elapsed/N*1000:.2f}ms")

        time.sleep(1)

        # 2. dm.key_down_char + key_up_char（无 sleep）
        t0 = time.perf_counter()
        for _ in range(N):
            dm.key_down_char("s")
            dm.key_up_char("s")
        elapsed = time.perf_counter() - t0
        print(f"[key_down+key_up]     {N}次  平均 {elapsed/N*1000:.2f}ms")

        time.sleep(1)

        # 3. PostMessage
        t0 = time.perf_counter()
        for _ in range(N):
            post_message_key(hwnd, VK_S)
            post_message_key(hwnd, VK_S, key_up=True)
        elapsed = time.perf_counter() - t0
        print(f"[PostMessage]         {N}次  平均 {elapsed/N*1000:.2f}ms")

        time.sleep(1)

        # 4. SendMessage
        t0 = time.perf_counter()
        for _ in range(N):
            user32.SendMessageW(hwnd, 0x0100, VK_S, 0)  # WM_KEYDOWN
            user32.SendMessageW(hwnd, 0x0101, VK_S, 0)  # WM_KEYUP
        elapsed = time.perf_counter() - t0
        print(f"[SendMessage]         {N}次  平均 {elapsed/N*1000:.2f}ms")

        try:
            ctypes.windll.winmm.timeEndPeriod(1)
        except Exception:
            pass

    print("\n完成。注意：以上按键已实际发送，请在游戏中观察效果。")

if __name__ == "__main__":
    main()
