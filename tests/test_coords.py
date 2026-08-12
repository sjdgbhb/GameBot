"""坐标兼容性测试 — 重置窗口 → 框选屏幕文本，观察是否刚好框住。

用法（大漠脚本环境 .venv-dm）：
  .venv-dm/Scripts/python.exe tests/test_coords.py

流程：
  1. 浮窗倒计时（按 Num- 可停止）
  2. 绑定 war3 窗口，强制设置客户区尺寸（重置窗口）
  3. 框选指定区域文本，暂停供肉眼核对
  4. 循环执行，按 Num- 停止
"""
import time

from GameBot.config import config
from GameBot.runner.dm_client import DmClient
from GameBot.runner.business.war3 import War3Business
from GameBot.runner.ui import run_with_float_window

# 框选区域 [x1, y1, x2, y2]（客户区坐标，基于 1902x1033）
BOX_COORDS = [779,753,863,779]
# 每次框选后停留时间（秒），供观察
HOLD_TIME = 5
# 两次框选间隔（秒）
INTERVAL_TIME = 2


def main():
    cfg = config.load_task("war3")
    war3_cfg = cfg.get("war3", {})

    def task_func(stop_event, progress_callback=None):
        dm = DmClient()
        war3 = War3Business(dm, war3_cfg)

        hwnd = dm.get_active_window(
            war3_cfg.get("window_class", ""),
            war3_cfg.get("window_title", ""),
        )
        if not hwnd:
            progress_callback("未找到 war3 窗口，请先切换到魔兽窗口")
            return

        with dm.bind_window(hwnd):
            # 重置窗口尺寸
            progress_callback("重置窗口尺寸...")
            war3.set_client_size(hwnd)
            x1, y1, x2, y2 = dm.get_client_rect(hwnd)
            actual_w, actual_h = x2 - x1, y2 - y1
            expected = war3_cfg.get("client_size", [1902, 1033])
            print(f"窗口客户区: ({x1}, {y1}) ~ ({x2}, {y2}), 尺寸 {actual_w}x{actual_h}")
            print(f"配置期望: {expected[0]}x{expected[1]}")
            print(f"大漠版本: {dm.version}")
            if actual_w != expected[0] or actual_h != expected[1]:
                print(f"⚠ 客户区尺寸不匹配！坐标可能偏移")
                progress_callback(f"⚠ 尺寸不匹配: 实际 {actual_w}x{actual_h} vs 期望 {expected[0]}x{expected[1]}")
            else:
                print(f"✓ 客户区尺寸匹配")
                progress_callback(f"✓ 尺寸匹配 {actual_w}x{actual_h}")
            print()

            round_num = 0
            while not stop_event.is_set():
                round_num += 1
                progress_callback(f"第 {round_num} 轮: 框选文本")

                # 手动框选（可被 stop_event 中断）
                general_time = war3_cfg.get("general_time", 0.3)
                dm.move_to(*BOX_COORDS[:2])
                time.sleep(general_time)
                dm.left_down()
                time.sleep(general_time)
                dm.move_to(*BOX_COORDS[2:])
                # 分段等待，每 0.1s 检查 stop_event
                elapsed = 0.0
                while elapsed < HOLD_TIME and not stop_event.is_set():
                    time.sleep(0.1)
                    elapsed += 0.1
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

    run_with_float_window("坐标兼容性测试", task_func, countdown_seconds=5)


if __name__ == "__main__":
    main()
