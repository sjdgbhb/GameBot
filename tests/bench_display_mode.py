"""
测量不同 BindWindow display 模式下 find_color / get_color 的耗时
用法：uv run python tests/bench_display_mode.py
"""
import time
import ctypes

from GameBot.config import config
from GameBot.runner import DmClient
from GameBot.runner.business.war3 import War3Business


def bench_display(dm, display_mode, x1, y1, x2, y2, color_str, sim, N=100):
    """用指定 display 模式绑定窗口，测量各操作耗时"""
    hwnd = dm.get_active_window()
    # 先解绑再重绑
    try:
        dm.dm.UnBindWindow()
    except Exception:
        pass

    ret = dm.dm.BindWindow(hwnd, display_mode, "normal", "normal", 0)
    if ret != 1:
        print(f"  [跳过] BindWindow display={display_mode} 失败 ret={ret}")
        return

    try:
        try:
            ctypes.windll.winmm.timeBeginPeriod(1)
        except Exception:
            pass

        # find_color
        t0 = time.perf_counter()
        for _ in range(N):
            dm.find_color(x1, y1, x2, y2, color_str, sim)
        elapsed = time.perf_counter() - t0
        print(f"  find_color  {N}次  平均 {elapsed/N*1000:.2f}ms")

        # get_color 单像素
        t0 = time.perf_counter()
        for _ in range(N):
            dm.get_color(x1, y1)
        elapsed = time.perf_counter() - t0
        print(f"  get_color   {N}次  平均 {elapsed/N*1000:.2f}ms")

        # FindColorEx（返回所有匹配点）
        t0 = time.perf_counter()
        for _ in range(N):
            dm.dm.FindColorEx(x1, y1, x2, y2, color_str, sim, 0)
        elapsed = time.perf_counter() - t0
        print(f"  FindColorEx {N}次  平均 {elapsed/N*1000:.2f}ms")

        # GetScreenData（获取屏幕数据到内存）
        t0 = time.perf_counter()
        for _ in range(N):
            dm.dm.GetScreenData(x1, y1, x2, y2)
        elapsed = time.perf_counter() - t0
        print(f"  GetScreenData {N}次  平均 {elapsed/N*1000:.2f}ms")

        try:
            ctypes.windll.winmm.timeEndPeriod(1)
        except Exception:
            pass
    finally:
        dm.dm.UnBindWindow()


def main():
    time.sleep(5)
    cfg = config.load_task("war3.jiubing2.tasks.fishing")
    dm = DmClient()
    war3 = War3Business(dm, cfg.get("war3", {}))
    fishing_cfg = cfg.get("tasks", {}).get("fishing", {})
    check_cfg = fishing_cfg.get("check", {})

    hwnd = dm.get_active_window()
    # 先用 normal 模式绑定一次，设置客户区大小
    dm.dm.BindWindow(hwnd, "normal", "normal", "normal", 0)
    war3.set_client_size(hwnd)
    dm.dm.UnBindWindow()

    x1, y1, x2, y2 = check_cfg["status_area_coords"]
    delta_color = check_cfg.get("hook_delta_color", "000000")
    hook_color = check_cfg.get("hook_color", "ff0000")
    color_str = f"{hook_color}-{delta_color}"
    sim = check_cfg["hook_sim"]

    modes = ["normal", "gdi", "gdi2", "dx", "dx2"]
    for mode in modes:
        print(f"\n=== display={mode} ===")
        bench_display(dm, mode, x1, y1, x2, y2, color_str, sim)

    # 最后用 normal 重新绑定，保持窗口状态
    dm.dm.BindWindow(hwnd, "normal", "normal", "normal", 0)
    print("\n完成。")


if __name__ == "__main__":
    main()
