"""
钓鱼填充节奏帧采集脚本

抛竿后以固定频率连拍检测区域帧序列，连续采集多个填充循环
（从左到右填充 → 从右到左去填充 → 循环），用于分析：
1. 圈圈/三角形未填充时的边框颜色与位置、格间距
2. 蓝色/红色填充的色值与每格填充间隔、循环周期
3. 红色三角形填充的出现/消失时间线（events.txt）

使用方法：
  .venv-dm/Scripts/python.exe scripts/collect_fishing_frames.py
运行后 5 秒内切换到游戏窗口，脚本会自动抛竿并连拍。
采集期间不收竿，直到采集时长结束才按 S 收竿。
帧保存到 data/fishing_frames/<时间戳>/，文件名为相对抛竿时刻的毫秒数。
注意：帧序列约 100~200MB，分析完成后可删除。
"""
import ctypes
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(__file__)), "src"))

from GameBot.config import config
from GameBot.utils.logger import logger
from GameBot.runner.dm_client import DmClient
from GameBot.runner.business.war3 import War3Business

EXPAND_X = 150           # 采集区域相对检测区域左右扩展的像素（覆盖整排圈圈）
EXPAND_Y = 40            # 采集区域相对检测区域上下扩展的像素
FRAME_INTERVAL = 0.03    # 连拍间隔（秒），约 30fps
CAPTURE_SECONDS = 15     # 总采集时长（秒），需覆盖至少一个完整填充循环


def main():
    cfg = config.load_task("war3.jiubing2.tasks.others.fishing")
    fishing_cfg = cfg.get("war3", {}).get("jiubing2", {}).get("tasks", {}).get("others", {}).get("fishing", {})
    check_cfg = fishing_cfg.get("check", {})

    dm = DmClient()
    war3 = War3Business(dm, cfg.get("war3", {}))

    logger.info("5 秒内请切换到游戏窗口...")
    time.sleep(5)

    hwnd = dm.get_active_window()
    out_dir = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "data", "fishing_frames", time.strftime("%Y%m%d%H%M%S"),
    )
    os.makedirs(out_dir, exist_ok=True)

    # 检测参数（与钓鱼任务保持一致）
    x1, y1, x2, y2 = check_cfg["status_area_coords"]
    sim = check_cfg["hook_sim"]
    delta_color = check_cfg.get("hook_delta_color", "000000")
    hook_image = check_cfg.get("hook_status_image", "hook_status1.bmp")

    # 采集区域：在检测区域基础上向四周扩展，覆盖整排圈圈
    client_size = cfg.get("war3", {}).get("client_size", [1902, 1033])
    cap_x1 = max(0, x1 - EXPAND_X)
    cap_y1 = max(0, y1 - EXPAND_Y)
    cap_x2 = min(client_size[0], x2 + EXPAND_X)
    cap_y2 = min(client_size[1], y2 + EXPAND_Y)

    red_events = []   # [(时刻ms, "出现"/"消失", x, y), ...]
    red_visible = False
    frame_count = 0

    with dm.bind_window(hwnd, display="gdi"):
        war3.set_client_size(hwnd)
        try:
            ctypes.windll.winmm.timeBeginPeriod(1)
        except Exception:
            pass
        try:
            dm.dm.SetKeypadDelay("normal", 2)
        except Exception:
            pass

        war3.center_hero()
        # 抛竿
        dm.move_to(*fishing_cfg["hook_coords"])
        time.sleep(0.1)
        dm.key_press_char(fishing_cfg["fishing_hotkey"])
        time.sleep(0.1)
        dm.left_click()
        time.sleep(0.05)

        t_cast = time.perf_counter()
        logger.info(
            f"开始连拍 {CAPTURE_SECONDS}s，采集区域 ({cap_x1},{cap_y1},{cap_x2},{cap_y2})，"
            f"保存到 {out_dir}"
        )

        while True:
            now_ms = (time.perf_counter() - t_cast) * 1000
            if now_ms > CAPTURE_SECONDS * 1000:
                break

            # 连拍一帧（文件名为相对抛竿时刻的毫秒数）
            path = os.path.join(out_dir, f"t_{int(now_ms):06d}.bmp")
            dm.capture_region(cap_x1, cap_y1, cap_x2, cap_y2, path)
            frame_count += 1

            # 用与钓鱼任务一致的找图逻辑检测红色三角形填充，记录出现/消失事件
            index, rx, ry = dm.find_pic(
                x1, y1, x2, y2, hook_image, sim=sim, delta_color=delta_color,
            )
            found = index != -1
            if found != red_visible:
                t_ms = (time.perf_counter() - t_cast) * 1000
                red_events.append((t_ms, "出现" if found else "消失", rx, ry))
                logger.info(f"红色{'出现' if found else '消失'} t={t_ms:.0f}ms 坐标=({rx},{ry})")
                red_visible = found

            time.sleep(FRAME_INTERVAL)

        # 采集结束，收竿
        dm.key_press_char("s")
        logger.info("采集结束，已按 S 收竿")

        try:
            ctypes.windll.winmm.timeEndPeriod(1)
        except Exception:
            pass

    # 写事件时间线
    events_path = os.path.join(out_dir, "events.txt")
    with open(events_path, "w", encoding="utf-8") as f:
        f.write("t_cast_ms=0\n")
        f.write(f"frames={frame_count}\n")
        f.write(f"capture_area={cap_x1},{cap_y1},{cap_x2},{cap_y2}\n")
        f.write(f"detect_area={x1},{y1},{x2},{y2}\n")
        for t_ms, event, rx, ry in red_events:
            f.write(f"红色{event} t={t_ms:.1f}ms 坐标=({rx},{ry})\n")
    logger.info(f"采集完成：{frame_count} 帧，红色事件 {len(red_events)} 条，已写入 {events_path}")


if __name__ == "__main__":
    main()
