"""测试大漠对 KK 主界面窗口的后台截图。

用法：
    uv run python tests/manual/test_kk_hall_background.py
    uv run python tests/manual/test_kk_hall_background.py --delay 10

流程：
1. 等待 N 秒（默认 5 秒），方便用户提前打开/切换好 KK 主界面。
2. 从配置读取 KK 窗口类名、标题和客户区尺寸。
3. 查找并绑定 KK 主界面窗口，优先使用配置里的 [kk.bind_background]，
   失败则回退 gdi2 → gdi → normal。
4. 截取全客户区并保存到 logs/diag_kk_hall_screenshot/。

配置来源：src/GameBot/config/data/kk.toml
"""

import argparse
import ctypes
import sys
import time
from datetime import datetime
from pathlib import Path

from GameBot.config import config
from GameBot.runner.driver import create_dm_client
from GameBot.utils import DmError, logger, setup_log_file

OUT_DIR = Path("logs/diag_kk_hall_screenshot")


def find_hall_window(dm, window_class: str, window_title: str) -> int:
    """按类名+标题查找可见的 KK 主界面窗口。"""
    for h in dm.enum_windows(window_class, window_title):
        if not dm.is_window_visible(h):
            continue
        if dm.get_window_class(h) != window_class:
            continue
        if window_title and dm.get_window_title(h) != window_title:
            continue
        return int(h)
    return 0


def get_bind_cfg(kk_cfg: dict) -> dict:
    """优先使用 [kk.bind_background] 的绑定配置，否则用默认 gdi2。"""
    bind_background = kk_cfg.get("bind_background", {})
    if bind_background:
        return dict(bind_background)
    return {
        "display": "gdi2",
        "mouse": "windows3",
        "keypad": "windows",
        "mode": 0,
        "bind_delay": 1.0,
    }


def capture_hall_background(dm, hwnd: int, w: int, h: int, bind_cfg: dict, out_path: Path) -> bool:
    """尝试多种 display 模式绑定并截图，返回是否成功。"""
    display_order = [bind_cfg.get("display", "gdi2")]
    for mode in ("gdi2", "gdi", "normal"):
        if mode not in display_order:
            display_order.append(mode)

    for display in display_order:
        try_cfg = dict(bind_cfg)
        try_cfg["display"] = display
        try_cfg.setdefault("bind_delay", 1.0)

        logger.info(f"尝试 display='{display}' 后台绑定 hwnd={hwnd}")
        try:
            with dm.bind_window(hwnd, bind_cfg=try_cfg):
                # 大漠 Capture 以 SetPath 为基准解析相对路径，此处用绝对路径避免写到 dll 目录
                ok = dm.capture_region(0, 0, w, h, str(out_path.absolute()))
                if ok:
                    logger.info(f"display='{display}' 截图成功: {out_path}")
                    return True
                logger.warning(f"display='{display}' capture_region 返回失败")
        except DmError as e:
            logger.warning(f"display='{display}' 绑定或截图失败: {e}")
            continue

    logger.error("所有 display 模式均截图失败")
    return False


def main() -> int:
    parser = argparse.ArgumentParser(description="KK 主界面后台截图测试")
    parser.add_argument("--delay", type=int, default=5, help="启动前等待秒数（默认 5）")
    args = parser.parse_args()

    setup_log_file("kk主界面后台截图")
    logger.info("=" * 60)
    logger.info("KK 主界面后台截图测试")
    logger.info("=" * 60)

    # 倒计时
    for i in range(args.delay, 0, -1):
        logger.info(f"{i} 秒后开始...")
        time.sleep(1)

    # 加载配置
    cfg = config.load_task("kk")
    kk_cfg = cfg.get("kk", {})
    window_class = kk_cfg.get("window_class", "")
    window_title = kk_cfg.get("window_title", "")
    main_cfg = kk_cfg.get("main", {})
    main_size = tuple(main_cfg.get("window_size", [1332, 945]))
    bind_cfg = get_bind_cfg(kk_cfg)

    logger.info(f"KK 窗口类名: {window_class}")
    logger.info(f"KK 窗口标题: {window_title}")
    logger.info(f"客户区目标尺寸: {main_size}")
    logger.info(f"绑定配置: {bind_cfg}")

    dm = create_dm_client()
    logger.info(f"大漠版本: {dm.version}")

    try:
        # 查找窗口
        hwnd = find_hall_window(dm, window_class, window_title)
        if not hwnd:
            logger.error("未找到 KK 主界面窗口")
            return 1

        logger.info(f"找到 KK 主界面窗口: hwnd={hwnd}")
        x1, y1, x2, y2 = dm.get_client_rect(hwnd)
        logger.info(f"当前客户区屏幕坐标: ({x1},{y1},{x2},{y2})")

        # 检查最小化
        if dm.is_window_minimized(hwnd):
            logger.warning("窗口当前处于最小化状态，gdi2 后台截图可能黑屏，将尝试恢复窗口")
            # SW_RESTORE = 9：恢复窗口，避免最小化导致截图黑屏
            ctypes.windll.user32.ShowWindow(int(hwnd), 9)
            time.sleep(0.5)

        # 对齐客户区尺寸
        dm.set_client_size(hwnd, *main_size)
        time.sleep(0.5)

        w, h = main_size
        OUT_DIR.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        out_path = OUT_DIR / f"kk_hall_{hwnd}_{timestamp}.bmp"

        logger.info(f"准备截取客户区 0,0,{w},{h}，保存到 {out_path}")
        ok = capture_hall_background(dm, hwnd, w, h, bind_cfg, out_path)

        if ok:
            logger.info("测试通过，截图已保存")
            logger.info(f"完整路径: {out_path.absolute()}")
            return 0
        else:
            logger.error("测试失败，未成功截取 KK 主界面")
            return 1

    finally:
        dm.close()


if __name__ == "__main__":
    sys.exit(main())
