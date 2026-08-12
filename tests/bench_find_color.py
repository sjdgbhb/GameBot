"""
测量 find_color / get_color / key_press 实际耗时
用法：uv run python scripts/bench_find_color.py
"""
import time
import ctypes

from GameBot.config import config
from GameBot.runner import DmClient
from GameBot.runner.business.war3 import War3Business


def main():
    cfg = config.load_task("war3.jiubing2.tasks.fishing")
    dm = DmClient()
    war3 = War3Business(dm, cfg.get("war3", {}))
    fishing_cfg = cfg.get("tasks", {}).get("fishing", {})
    check_cfg = fishing_cfg.get("check", {})

    hwnd = dm.get_active_window()
    with dm.bind_window(hwnd):
        war3.set_client_size(hwnd)
        try:
            ctypes.windll.winmm.timeBeginPeriod(1)
        except Exception:
            pass

        x1, y1, x2, y2 = check_cfg["status_area_coords"]
        delta_color = check_cfg.get("hook_delta_color", "000000")
        hook_color = check_cfg.get("hook_color", "ff0000")
        color_str = f"{hook_color}-{delta_color}"
        sim = check_cfg["hook_sim"]

        # 缩小区域测试
        narrow = [x1, y1, x1 + 50, y2]  # 50px 宽窄带

        # ---- find_color：全区域 ----
        N = 200
        t0 = time.perf_counter()
        for _ in range(N):
            dm.find_color(x1, y1, x2, y2, color_str, sim)
        elapsed = time.perf_counter() - t0
        print(f"[find_color] 全区域 {x2-x1}x{y2-y1}  {N}次  平均 {elapsed/N*1000:.2f}ms  总 {elapsed*1000:.0f}ms")

        # ---- find_color：窄带 50px ----
        t0 = time.perf_counter()
        for _ in range(N):
            dm.find_color(*narrow, color_str, sim)
        elapsed = time.perf_counter() - t0
        print(f"[find_color] 窄带 50x{y2-y1}   {N}次  平均 {elapsed/N*1000:.2f}ms  总 {elapsed*1000:.0f}ms")

        # ---- get_color：单像素 ----
        t0 = time.perf_counter()
        for _ in range(N):
            dm.get_color(x1, y1)
        elapsed = time.perf_counter() - t0
        print(f"[get_color]  单像素          {N}次  平均 {elapsed/N*1000:.2f}ms  总 {elapsed*1000:.0f}ms")

        # ---- get_color：2像素 ----
        t0 = time.perf_counter()
        for _ in range(N):
            dm.get_color(x1, y1)
            dm.get_color(x1 + 20, y1)
        elapsed = time.perf_counter() - t0
        print(f"[get_color]  2像素           {N}次  平均 {elapsed/N*1000:.2f}ms  总 {elapsed*1000:.0f}ms")

        # ---- key_press_char ----
        # 不实际按键，只测 COM 调用开销（用不存在的键避免副作用）
        t0 = time.perf_counter()
        for _ in range(N):
            dm.dm.SetKeypadDelay("normal", 10)  # 模拟一次 COM 属性写入
        elapsed = time.perf_counter() - t0
        print(f"[COM写入]    SetKeypadDelay  {N}次  平均 {elapsed/N*1000:.2f}ms  总 {elapsed*1000:.0f}ms")

        # ---- find_pic：全区域 ----
        t0 = time.perf_counter()
        for _ in range(N):
            dm.find_pic(x1, y1, x2, y2, check_cfg["hook_status_image"], sim=sim, delta_color=delta_color)
        elapsed = time.perf_counter() - t0
        print(f"[find_pic]   全区域          {N}次  平均 {elapsed/N*1000:.2f}ms  总 {elapsed*1000:.0f}ms")

        print("\n完成。")

        try:
            ctypes.windll.winmm.timeEndPeriod(1)
        except Exception:
            pass


if __name__ == "__main__":
    main()
