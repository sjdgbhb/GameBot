"""单独测试 KK 创建房间弹窗的密码输入。

用法：
    # 先手动打开 KK 大厅到地图详情页，点击“创建房间”按钮
    # 然后运行：
    uv run python tests/manual/test_create_room_password_input.py
    uv run python tests/manual/test_create_room_password_input.py --delay 3

流程：
1. 查找已打开的创建房间弹窗。
2. 用不同方式尝试输入密码：
   - 先 send_string2
   - 再用 key_press_char 逐个字符兜底
3. 每一步后都截图保存到 logs/diag_create_room_password/
4. 最后弹出提示，让用户人工查看弹窗里是否有密码。

不点击“创建”按钮，因此不会真的创建房间。
"""

import argparse
import copy
import ctypes
import sys
import time
from pathlib import Path

from PIL import Image

from GameBot.config import config
from GameBot.runner.driver import create_dm_client
from GameBot.utils import logger, setup_log_file

OUT_DIR = Path("logs/diag_create_room_password")


def is_blank_image(img_path: str) -> bool:
    """判断图片是否为纯色（黑屏/白屏）。"""
    try:
        mn, mx = Image.open(img_path).convert("L").getextrema()
        return mn == mx
    except Exception:
        return False


def enum_pid_windows(target_pid: int) -> list:
    """枚举指定 PID 的可见顶层窗口。"""
    user32 = ctypes.windll.user32
    EnumWindows = user32.EnumWindows
    EnumWindowsProc = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)
    GetWindowThreadProcessId = user32.GetWindowThreadProcessId
    GetWindowRect = user32.GetWindowRect
    GetClassNameW = user32.GetClassNameW
    IsWindowVisible = user32.IsWindowVisible
    results = []

    def cb(hwnd, _):
        if not IsWindowVisible(hwnd):
            return True
        pid = ctypes.c_ulong()
        GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if int(pid.value) != target_pid:
            return True
        cls = ctypes.create_unicode_buffer(256)
        GetClassNameW(hwnd, cls, 256)
        rect = ctypes.wintypes.RECT()
        GetWindowRect(hwnd, ctypes.byref(rect))
        results.append(
            {
                "hwnd": int(hwnd),
                "class": cls.value,
                "rect": (rect.left, rect.top, rect.right, rect.bottom),
            }
        )
        return True

    EnumWindows(EnumWindowsProc(cb), 0)
    return results


def find_create_room_dialog(dm, kk_cfg: dict, owner_pid: int) -> int:
    """查找已打开的创建房间弹窗。"""
    popup_class = kk_cfg.get("create_room_window_class", "")
    create_cfg = kk_cfg.get("create_room", {})
    dialog_size = tuple(create_cfg.get("dialog_window_size", [584, 488]))
    size_tol = 30

    for win in enum_pid_windows(owner_pid):
        if popup_class and popup_class.lower() not in win["class"].lower():
            continue
        if win["class"] == kk_cfg.get("window_class", ""):
            # 排除大厅窗口（主界面类名与弹窗类名不同）
            continue
        w = win["rect"][2] - win["rect"][0]
        h = win["rect"][3] - win["rect"][1]
        if abs(w - dialog_size[0]) > size_tol or abs(h - dialog_size[1]) > size_tol:
            continue
        return int(win["hwnd"])
    return 0


def save_dialog_screenshot(dm, dialog_hwnd: int, bind_cfg: dict, label: str) -> str:
    """保存弹窗全客户区截图。"""
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    x1, y1, x2, y2 = dm.get_client_rect(dialog_hwnd)
    w, h = x2 - x1, y2 - y1
    out_path = (OUT_DIR / f"{label}_{dialog_hwnd}.bmp").resolve()
    try:
        with dm.bind_window(dialog_hwnd, bind_cfg=bind_cfg):
            ok = dm.capture_region(0, 0, w, h, str(out_path))
            if ok and not is_blank_image(str(out_path)):
                return str(out_path)
    except Exception as e:
        logger.warning(f"截图失败 {label}: {e}")
    return ""


def try_send_string2(dm, dialog_hwnd: int, password: str, password_input: list, bind_cfg: dict) -> bool:
    """尝试用 send_string2 输入密码，并截图。"""
    logger.info("尝试 send_string2 输入密码")
    with dm.bind_window(dialog_hwnd, bind_cfg=bind_cfg):
        # 点击输入框，争取焦点
        dm.move_to(*password_input)
        time.sleep(0.3)
        dm.left_click()
        time.sleep(0.2)

        # 清空
        dm.key_press_char("end")
        time.sleep(0.1)
        for _ in range(20):
            dm.key_press_char("back")
            time.sleep(0.01)
        dm.key_press_char("ctrl+a")
        time.sleep(0.2)
        dm.key_press_char("back")
        time.sleep(0.2)

        # 输入
        ret = dm.send_string2(password, hwnd=dialog_hwnd)
        logger.info(f"send_string2 返回值: {ret}")
        time.sleep(0.5)

    save_dialog_screenshot(dm, dialog_hwnd, bind_cfg, "after_send_string2")
    return True


def try_key_press_char(dm, dialog_hwnd: int, password: str, password_input: list, bind_cfg: dict) -> bool:
    """用 key_press_char 逐个字符输入密码，并截图。"""
    logger.info("尝试 key_press_char 逐个字符输入密码")
    with dm.bind_window(dialog_hwnd, bind_cfg=bind_cfg):
        # 点击输入框，争取焦点
        dm.move_to(*password_input)
        time.sleep(0.3)
        dm.left_click()
        time.sleep(0.2)

        # 清空
        dm.key_press_char("end")
        time.sleep(0.1)
        for _ in range(20):
            dm.key_press_char("back")
            time.sleep(0.01)
        dm.key_press_char("ctrl+a")
        time.sleep(0.2)
        dm.key_press_char("back")
        time.sleep(0.2)

        # 逐个按键
        for ch in password:
            dm.key_press_char(ch)
            time.sleep(0.05)
        logger.info(f"已按键输入: {password}")
        time.sleep(0.5)

    save_dialog_screenshot(dm, dialog_hwnd, bind_cfg, "after_key_press")
    return True


def main():
    parser = argparse.ArgumentParser(description="KK 创建房间弹窗密码输入测试")
    parser.add_argument("--delay", type=int, default=5, help="启动前等待秒数（默认 5）")
    parser.add_argument("--password", type=str, default=None, help="测试输入的密码（默认读取 kk.create_room.password）")
    parser.add_argument("--display", type=str, default=None, help="绑定 display（默认读取 kk.bind_background.display）")
    parser.add_argument("--mouse", type=str, default=None, help="绑定 mouse（默认读取 kk.bind_background.mouse）")
    parser.add_argument("--keypad", type=str, default=None, help="绑定 keypad（默认读取 kk.bind_background.keypad）")
    parser.add_argument("--mode", type=int, default=None, help="绑定 mode（默认读取 kk.bind_background.mode）")
    args = parser.parse_args()

    setup_log_file("测试创建房间密码输入")
    logger.info("=" * 60)
    logger.info("KK 创建房间弹窗密码输入测试")
    logger.info("=" * 60)

    for i in range(args.delay, 0, -1):
        logger.info(f"{i} 秒后开始...")
        time.sleep(1)

    # 加载配置
    kk_cfg = config.load_task("kk").get("kk", {})
    bind_cfg = copy.deepcopy(kk_cfg.get("bind_background", {}))
    if not bind_cfg:
        bind_cfg = copy.deepcopy(kk_cfg.get("bind", {}))
    if args.display is not None:
        bind_cfg["display"] = args.display
    if args.mouse is not None:
        bind_cfg["mouse"] = args.mouse
    if args.keypad is not None:
        bind_cfg["keypad"] = args.keypad
    if args.mode is not None:
        bind_cfg["mode"] = args.mode

    create_cfg = kk_cfg.get("create_room", {})
    password = args.password
    if password is None:
        password = create_cfg.get("password", "1234")
    password_input = create_cfg.get("password_input_coords", [0, 0])

    logger.info(f"测试密码: {password}")
    logger.info(f"绑定配置: {bind_cfg}")

    if password_input == [0, 0]:
        logger.error("未配置 password_input_coords")
        return

    dm = create_dm_client()
    logger.info(f"大漠版本: {dm.version}")

    try:
        # 查找大厅，用于获取 PID
        hall_hwnd = 0
        window_class = kk_cfg.get("window_class", "")
        window_title = kk_cfg.get("window_title", "")
        for h in dm.enum_windows(window_class, window_title, filter=1 + 2 + 8 + 16):
            if dm.get_window_class(h) == window_class and dm.is_window_visible(h):
                hall_hwnd = int(h)
                break

        if not hall_hwnd:
            logger.error("未找到 KK 大厅窗口")
            return
        pid = dm.get_window_process_id(hall_hwnd)
        logger.info(f"大厅窗口: hwnd={hall_hwnd}, pid={pid}")

        # 查找创建房间弹窗
        dialog_hwnd = find_create_room_dialog(dm, kk_cfg, pid)
        if not dialog_hwnd:
            logger.error("未找到已打开的创建房间弹窗，请先手动点击“创建房间”按钮")
            return
        logger.info(f"创建房间弹窗: hwnd={dialog_hwnd}")

        dialog_size = tuple(create_cfg.get("dialog_window_size", [584, 488]))
        dm.set_client_size(dialog_hwnd, *dialog_size)
        time.sleep(0.5)

        # 初始截图
        save_dialog_screenshot(dm, dialog_hwnd, bind_cfg, "before_input")

        # 方法 1: send_string2
        try_send_string2(dm, dialog_hwnd, password, password_input, bind_cfg)

        # 方法 2: key_press_char 逐个字符
        try_key_press_char(dm, dialog_hwnd, password, password_input, bind_cfg)

        logger.info("测试完成，请查看 logs/diag_create_room_password/ 下的截图")
        logger.info("如果弹窗中已显示密码（点），说明对应方法可用")

    finally:
        dm.close()


if __name__ == "__main__":
    sys.exit(main())
