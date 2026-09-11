"""坐标测试工具 — 绑定 war3 窗口后，鼠标移动到指定坐标 / 框选指定区域。

用法（主环境 .venv）：
  .venv/Scripts/python.exe tests/manual/test_coords.py

流程：
  1. 浮窗倒计时（按 Num- 可停止）
  2. 绑定 war3 窗口，校验客户区尺寸
  3. 按步骤列表依次执行每个操作（框选/移动），每步停留 HOLD_TIME 秒
  4. 循环执行，按 Num- 停止
"""

import ctypes
import time

from GameBot.config import config
from GameBot.runner import create_dm_client
from GameBot.runner.business.war3 import War3Business
from GameBot.runner.ui import run_with_float_window

# ==================== 配置区 ====================

# 鼠标移动目标坐标 [x, y]（客户区坐标，基于 1902x1033）
# MOVE_COORDS = [253,865]
MOVE_COORDS = [1039,405]

# 框选区域 [x1, y1, x2, y2]（客户区坐标，基于 1902x1033）
BOX_COORDS = [850, 350, 1200, 450]

# 每次操作后停留时间（秒），供观察
HOLD_TIME = 5

# 两次循环间隔（秒）
INTERVAL_TIME = 2

# 操作步骤列表，按顺序执行。每项为 (类型, 坐标) 元组：
#   ("box", [x1, y1, x2, y2]) — 框选区域
#   ("move", [x, y])          — 移动鼠标到坐标
STEPS = [
    # ("box", BOX_COORDS),
    ("move", MOVE_COORDS),
]

# ==================== 逻辑区 ====================


def check_dpi(hwnd):
    """诊断 war3 窗口 DPI 与所在显示器 DPI 是否一致。

    不一致说明 war3 进程被 Windows DPI 虚拟化（缩放），
    此时物理鼠标坐标与游戏感知坐标存在缩放偏差，坐标必偏移。
    """
    user32 = ctypes.windll.user32
    win_dpi = user32.GetDpiForWindow(hwnd)
    monitor = user32.MonitorFromWindow(hwnd, 2)  # MONITOR_DEFAULTTONEAREST
    mon_x = ctypes.c_uint()
    mon_y = ctypes.c_uint()
    ctypes.windll.shcore.GetDpiForMonitor(monitor, 0, ctypes.byref(mon_x), ctypes.byref(mon_y))
    mon_dpi = mon_x.value
    print(f"war3 窗口 DPI: {win_dpi}, 显示器 DPI: {mon_dpi}（96=100% 缩放）")
    if win_dpi != mon_dpi:
        scale = mon_dpi / win_dpi
        print(f"⚠ war3 被 DPI 虚拟化！缩放比 {scale:.2f}，游戏内坐标 = 物理坐标 / {scale:.2f}，坐标必偏移")
        print("  解决：war3.exe 属性 → 兼容性 → 更改高 DPI 设置 → 替代高 DPI 缩放行为=应用程序；或将显示缩放设为 100% 后重启 war3")
        return False
    print("✓ DPI 一致，无虚拟化缩放")
    return True


def main():
    cfg = config.load_task("war3")
    war3_cfg = cfg.get("war3", {})

    def task_func(stop_event, progress_callback=None):
        dm = create_dm_client()
        war3 = War3Business(dm, war3_cfg)

        hwnd = dm.get_active_window(
            war3_cfg.get("window_class", ""),
            war3_cfg.get("window_title", ""),
        )
        if not hwnd:
            progress_callback("未找到 war3 窗口，请先切换到魔兽窗口")
            return

        with dm.bind_window(hwnd):
            if not check_dpi(hwnd):
                progress_callback("⚠ war3 被 DPI 虚拟化，坐标必偏移，详见控制台")
            war3.set_client_size(hwnd)
            x1, y1, x2, y2 = dm.get_client_rect(hwnd)
            actual_w, actual_h = x2 - x1, y2 - y1
            expected = war3_cfg.get("client_size", [1902, 1033])
            print(f"窗口客户区: ({x1}, {y1}) ~ ({x2}, {y2}), 尺寸 {actual_w}x{actual_h}")
            print(f"配置期望: {expected[0]}x{expected[1]}")
            if actual_w != expected[0] or actual_h != expected[1]:
                print("⚠ 客户区尺寸不匹配！坐标可能偏移")
                progress_callback(f"⚠ 尺寸不匹配: 实际 {actual_w}x{actual_h} vs 期望 {expected[0]}x{expected[1]}")
            else:
                print("✓ 客户区尺寸匹配")
                progress_callback(f"✓ 尺寸匹配 {actual_w}x{actual_h}")
            print()

            round_num = 0
            general_time = war3_cfg.get("general_time", 0.3)
            while not stop_event.is_set():
                round_num += 1

                for step_idx, (step_type, coords) in enumerate(STEPS):
                    if stop_event.is_set():
                        break

                    if step_type == "move":
                        progress_callback(f"第 {round_num} 轮 步骤{step_idx + 1}: 移动到 {coords}")
                        dm.move_to(*coords)
                    elif step_type == "box":
                        progress_callback(f"第 {round_num} 轮 步骤{step_idx + 1}: 框选 {coords}")
                        dm.move_to(*coords[:2])
                        time.sleep(general_time)
                        dm.left_down()
                        time.sleep(general_time)
                        dm.move_to(*coords[2:])

                    # 停留供观察
                    elapsed = 0.0
                    while elapsed < HOLD_TIME and not stop_event.is_set():
                        time.sleep(0.1)
                        elapsed += 0.1

                    if step_type == "box":
                        dm.left_up()

                if stop_event.is_set():
                    break
                progress_callback(f"第 {round_num} 轮完成，{INTERVAL_TIME}s 后重复（Num- 停止）")
                elapsed = 0.0
                while elapsed < INTERVAL_TIME and not stop_event.is_set():
                    time.sleep(0.1)
                    elapsed += 0.1

            progress_callback("测试结束")
            print("测试结束")

    run_with_float_window("坐标测试", task_func, countdown_seconds=5)


if __name__ == "__main__":
    main()
