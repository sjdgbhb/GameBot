"""诊断脚本：枚举所有 KK 窗口，打印 hwnd、尺寸、PID，帮助定位房间窗口。

运行：uv run python tests/manual/test_find_kk_room.py
"""

import time

from GameBot.config import config
from GameBot.runner.driver import create_dm_client
from GameBot.utils import logger, setup_log_file


def main():
    setup_log_file("KK窗口诊断")
    logger.info("############################# KK 窗口诊断 #############################")

    cfg = config.load_task("war3.jiubing2.tasks.endless.endless")
    kk_cfg = cfg.get("kk", {})
    window_class = kk_cfg.get("window_class", "")
    window_title = kk_cfg.get("window_title", "")
    create_room_class = kk_cfg.get("create_room_window_class", "")
    room_size = tuple(kk_cfg.get("room", {}).get("window_size", [1224, 904]))
    main_size = tuple(kk_cfg.get("main", {}).get("window_size", [1328, 945]))

    logger.info(f"配置: window_class={window_class}, window_title={window_title}")
    logger.info(f"配置: create_room_window_class={create_room_class}")
    logger.info(f"期望房间尺寸: {room_size}, 期望大厅尺寸: {main_size}")

    dm = create_dm_client()

    logger.info("5 秒后开始枚举窗口...")
    time.sleep(5)

    # 1. find_window — 最顶层窗口
    hwnd_top = dm.find_window(window_class, window_title)
    logger.info(f"find_window 返回的最顶层窗口: hwnd={hwnd_top}")
    if hwnd_top:
        try:
            x1, y1, x2, y2 = dm.get_client_rect(hwnd_top)
            logger.info(f"  尺寸: ({x2 - x1}, {y2 - y1}), 坐标: ({x1}, {y1}, {x2}, {y2})")
        except Exception as e:
            logger.error(f"  获取客户区失败: {e}")

    # 2. enum_windows — 枚举所有匹配窗口
    for cls_name, cls in [("window_class", window_class), ("create_room_window_class", create_room_class)]:
        if not cls:
            continue
        logger.info(f"\n--- enum_windows(class={cls_name}={cls}, title={window_title}) ---")
        hwnds = dm.enum_windows(cls, window_title)
        logger.info(f"  共找到 {len(hwnds)} 个窗口")
        for hwnd in hwnds:
            try:
                x1, y1, x2, y2 = dm.get_client_rect(hwnd)
                w, h = x2 - x1, y2 - y1
                pid = dm.get_window_process_id(hwnd)
                match = ""
                if (w, h) == room_size:
                    match = " ← 房间尺寸匹配!"
                elif (w, h) == main_size:
                    match = " ← 大厅尺寸匹配!"
                elif w <= 0 or h <= 0:
                    match = " ← 零尺寸"
                elif w < 200 or h < 200:
                    match = " ← 过小窗口"
                logger.info(f"  hwnd={hwnd}, 尺寸=({w}, {h}), pid={pid}, 坐标=({x1},{y1},{x2},{y2}){match}")
            except Exception as e:
                logger.error(f"  hwnd={hwnd}, 获取信息失败: {e}")

    # 3. 尝试用不同 filter 枚举（包含不可见窗口）
    logger.info("\n--- enum_windows(filter=1+2+8) 包含不可见窗口 ---")
    for cls in (window_class, create_room_class):
        if not cls:
            continue
        hwnds = dm.enum_windows(cls, window_title, filter=1 + 2 + 8)
        logger.info(f"  class={cls}: 共 {len(hwnds)} 个窗口")
        for hwnd in hwnds:
            try:
                x1, y1, x2, y2 = dm.get_client_rect(hwnd)
                w, h = x2 - x1, y2 - y1
                pid = dm.get_window_process_id(hwnd)
                logger.info(f"    hwnd={hwnd}, 尺寸=({w}, {h}), pid={pid}")
            except Exception as e:
                logger.error(f"    hwnd={hwnd}, 获取信息失败: {e}")

    logger.info("############################# 诊断结束 #############################")


if __name__ == "__main__":
    main()
