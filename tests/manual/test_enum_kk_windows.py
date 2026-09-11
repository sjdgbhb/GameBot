"""枚举 KK 进程下所有可见顶层窗口，打印类名、尺寸、PID，用于排查干扰弹窗。

用法：
    uv run python tests/manual/test_enum_kk_windows.py
    uv run python tests/manual/test_enum_kk_windows.py --player "善木木"
"""

import argparse
import ctypes
import ctypes.wintypes
import sys

from GameBot.config import config
from GameBot.runner.business.kk import KKBusiness
from GameBot.runner.driver import create_dm_client
from GameBot.utils import logger, setup_log_file


def enum_all_visible_windows() -> list:
    """枚举所有可见顶层窗口。"""
    user32 = ctypes.windll.user32
    results = []

    def cb(hwnd, _):
        if not user32.IsWindowVisible(hwnd):
            return True
        p = ctypes.c_ulong()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(p))
        cls = ctypes.create_unicode_buffer(256)
        user32.GetClassNameW(hwnd, cls, 256)
        title = ctypes.create_unicode_buffer(512)
        user32.GetWindowTextW(hwnd, title, 512)
        rect = ctypes.wintypes.RECT()
        user32.GetWindowRect(hwnd, ctypes.byref(rect))
        results.append({
            "hwnd": int(hwnd),
            "class": cls.value,
            "title": title.value,
            "rect": (rect.left, rect.top, rect.right, rect.bottom),
            "pid": int(p.value),
        })
        return True

    EnumWindowsProc = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)
    user32.EnumWindows(EnumWindowsProc(cb), 0)
    return results


def main():
    parser = argparse.ArgumentParser(description="枚举 KK 进程窗口诊断")
    parser.add_argument("--player", type=str, default="", help="目标玩家 ID（用于获取 PID）")
    parser.add_argument("--delay", type=int, default=5, help="启动前等待秒数（默认 5）")
    args = parser.parse_args()

    setup_log_file("KK窗口枚举")
    logger.info("=" * 60)
    logger.info("KK 进程窗口枚举诊断")
    logger.info("=" * 60)

    for i in range(args.delay, 0, -1):
        logger.info(f"{i} 秒后开始...")
        import time; time.sleep(1)

    cfg = config.load_task("kk")
    kk_cfg = cfg.get("kk", {})

    dm = create_dm_client()
    kk = KKBusiness(dm, kk_cfg)

    try:
        # 获取目标 PID
        if args.player:
            hwnd, pid = kk.claim_hall_window(dm, args.player)
            if not hwnd:
                logger.error(f"未找到玩家 {args.player} 的大厅窗口")
                return 1
        else:
            hall_hwnd = kk._find_hall_hwnd(dm)
            if not hall_hwnd:
                logger.error("未找到 KK 大厅窗口")
                return 1
            pid = dm.get_window_process_id(hall_hwnd)

        logger.info(f"目标 PID: {pid}")
        logger.info("")

        # 枚举该 PID 下所有可见窗口
        kk_window_class = kk_cfg.get("window_class", "")
        popup_class = kk_cfg.get("create_room_window_class", "")
        logger.info(f"配置: window_class={kk_window_class}, create_room_window_class={popup_class}")
        logger.info("")

        found = []
        for win in enum_all_visible_windows():
            if win["pid"] != pid:
                continue
            w = win["rect"][2] - win["rect"][0]
            h = win["rect"][3] - win["rect"][1]
            tag = ""
            if win["class"] == kk_window_class:
                tag = " ← 主窗口/房间类名"
            elif win["class"] == popup_class:
                tag = " ← 弹窗类名(dismiss_hall_popups 会处理)"
            else:
                tag = " ← 其他类名(dismiss_hall_popups 不会处理)"
            line = f"  hwnd={win['hwnd']}, class='{win['class']}', title='{win['title']}', size=({w}x{h}){tag}"
            logger.info(line)
            found.append(win)

        if not found:
            logger.warning("该 PID 下没有可见窗口")
        else:
            logger.info(f"\n共 {len(found)} 个可见窗口")

        # 列出所有不重复的类名
        classes = set(win["class"] for win in found)
        logger.info(f"\n所有类名: {classes}")
        logger.info(f"dismiss_hall_popups 只处理 class={popup_class} 的窗口")
        logger.info(f"未被处理的类名: {classes - {kk_window_class, popup_class}}")

    except Exception as e:
        logger.exception(f"异常: {e}")
        return 1
    finally:
        dm.close()
        logger.complete()

    return 0


if __name__ == "__main__":
    sys.exit(main())
