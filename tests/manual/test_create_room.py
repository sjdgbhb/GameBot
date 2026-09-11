"""测试 KK 后台创建房间：

流程：主界面统一尺寸 -> 点击创建房间 -> 输入密码 -> 点击创建。

用法：
    uv run python tests/manual/test_create_room.py
    uv run python tests/manual/test_create_room.py --delay 10
    uv run python tests/manual/test_create_room.py --dialog-open   # 弹窗已手动打开，跳过点击创建按钮
    uv run python tests/manual/test_create_room.py --dialog-open --method send_string2  # 只测 send_string2
    uv run python tests/manual/test_create_room.py --bind-mode background  # 强制后台绑定（模拟多开）

前提：KK 大厅窗口已打开，停在能点击“创建房间”按钮的页面。
      使用 --dialog-open 时，创建房间弹窗需已手动打开。

--method 可选值：all(默认) / send_string2 / tab / key_press
      用于单独验证每种输入方法是否生效（配合房间是否带密码判断）。
--bind-mode 可选值：auto(默认前台) / background(强制后台)
      与生产代码 team/base.py 的 bind_mode 逻辑一致。
配置来源：src/GameBot/config/data/kk.toml
"""

import argparse
import copy
import ctypes
import sys
import time
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageStat

from GameBot.config import config
from GameBot.runner.driver import create_dm_client
from GameBot.utils import logger, setup_log_file

OUT_DIR = Path("logs/diag_create_room")
WS_EX_APPWINDOW = 0x80000


def is_blank_image(img_path: str) -> bool:
    """判断图片是否为纯色（黑屏/白屏）。"""
    try:
        mn, mx = Image.open(img_path).convert("L").getextrema()
        return mn == mx
    except Exception:
        return False


def draw_markers(src_path: str, dst_path: str, points: list, area: list = None) -> None:
    """在截图上标记点击点和截图区域，用于人工核对坐标。"""
    try:
        img = Image.open(src_path).convert("RGB")
        draw = ImageDraw.Draw(img)
        for x, y in points:
            draw.line([(x - 10, y), (x + 10, y)], fill=(255, 0, 0), width=2)
            draw.line([(x, y - 10), (x, y + 10)], fill=(255, 0, 0), width=2)
        if area and len(area) == 4 and area[2] > area[0] and area[3] > area[1]:
            draw.rectangle([(area[0], area[1]), (area[2], area[3])], outline=(255, 0, 0), width=2)
        img.save(dst_path)
    except Exception as e:
        logger.warning(f"标记截图失败: {e}")


def save_region(dm, hwnd: int, area: list, bind_cfg: dict, label: str) -> str:
    """绑定窗口并截图指定客户区区域，返回文件路径或空字符串。"""
    if not area or area[2] <= area[0] or area[3] <= area[1]:
        out_path = (OUT_DIR / f"{label}_{hwnd}.bmp").resolve()
    else:
        out_path = (OUT_DIR / f"{label}.bmp").resolve()
    try:
        with dm.bind_window(hwnd, bind_cfg=bind_cfg):
            if area and area[2] > area[0] and area[3] > area[1]:
                ok = dm.capture_region(area[0], area[1], area[2], area[3], str(out_path))
            else:
                x1, y1, x2, y2 = dm.get_client_rect(hwnd)
                ok = dm.capture_region(0, 0, x2 - x1, y2 - y1, str(out_path))
            if ok and not is_blank_image(str(out_path)):
                return str(out_path)
    except Exception as e:
        logger.warning(f"截图失败 {label}: {e}")
    return ""


def find_hall_window(dm, kk_cfg: dict) -> int:
    """精确匹配类名+标题查找 KK 大厅窗口。"""
    window_class = kk_cfg.get("window_class", "")
    window_title = kk_cfg.get("window_title", "")
    for h in dm.enum_windows(window_class, window_title, filter=1 + 2 + 8 + 16):
        if not dm.is_window_visible(h):
            continue
        if dm.get_window_class(h) != window_class:
            continue
        if window_title and dm.get_window_title(h) != window_title:
            continue
        return int(h)
    return 0


def _enum_visible_top_windows() -> list:
    """枚举所有可见顶层窗口，返回 [{hwnd, class, rect, pid}, ...]。"""
    user32 = ctypes.windll.user32
    results = []

    def cb(hwnd, _):
        if not user32.IsWindowVisible(hwnd):
            return True
        p = ctypes.c_ulong()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(p))
        cls = ctypes.create_unicode_buffer(256)
        user32.GetClassNameW(hwnd, cls, 256)
        rect = ctypes.wintypes.RECT()
        user32.GetWindowRect(hwnd, ctypes.byref(rect))
        results.append({
            "hwnd": int(hwnd),
            "class": cls.value,
            "rect": (rect.left, rect.top, rect.right, rect.bottom),
            "pid": int(p.value),
        })
        return True

    EnumWindowsProc = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)
    user32.EnumWindows(EnumWindowsProc(cb), 0)
    return results


def find_create_room_dialog(dm, kk_cfg: dict, pid: int = 0) -> int:
    """通过枚举顶层窗口查找创建房间弹窗。

    pid 为 0 时不按进程过滤，直接按类名+尺寸匹配（用于弹窗已手动打开、不依赖大厅窗口的场景）。
    """
    popup_class = kk_cfg.get("create_room_window_class", "")
    dialog_size = tuple(kk_cfg.get("create_room", {}).get("dialog_window_size", [584, 488]))
    size_tol = 30

    for win in _enum_visible_top_windows():
        if pid and win["pid"] != pid:
            continue
        if popup_class and popup_class.lower() not in win["class"].lower():
            continue
        if win["class"] == kk_cfg.get("window_class", ""):
            continue
        w = win["rect"][2] - win["rect"][0]
        h = win["rect"][3] - win["rect"][1]
        if abs(w - dialog_size[0]) <= size_tol and abs(h - dialog_size[1]) <= size_tol:
            return int(win["hwnd"])
    return 0


def find_room_window(dm, kk_cfg: dict, pid: int) -> int:
    """通过枚举进程窗口查找房间窗口。

    房间窗口与主界面类名相同，用 ExStyle 中的 WS_EX_APPWINDOW 区分。
    """
    window_class = kk_cfg.get("window_class", "")
    room_size = tuple(kk_cfg.get("room", {}).get("window_size", [1224, 904]))
    size_tol = 30
    min_w, min_h = 200, 200
    user32 = ctypes.windll.user32
    GetWindowLongPtrW = user32.GetWindowLongPtrW

    def callback():
        results = []

        def cb(hwnd, _):
            if not user32.IsWindowVisible(hwnd):
                return True
            p = ctypes.c_ulong()
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(p))
            if int(p.value) != pid:
                return True
            cls = ctypes.create_unicode_buffer(256)
            user32.GetClassNameW(hwnd, cls, 256)
            rect = ctypes.wintypes.RECT()
            user32.GetWindowRect(hwnd, ctypes.byref(rect))
            results.append({"hwnd": int(hwnd), "class": cls.value, "rect": (rect.left, rect.top, rect.right, rect.bottom)})
            return True

        EnumWindowsProc = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)
        user32.EnumWindows(EnumWindowsProc(cb), 0)
        return results

    for win in callback():
        if win["class"] != window_class:
            continue
        w = win["rect"][2] - win["rect"][0]
        h = win["rect"][3] - win["rect"][1]
        if w < min_w or h < min_h:
            continue
        if abs(w - room_size[0]) > size_tol or abs(h - room_size[1]) > size_tol:
            continue
        ex_style = GetWindowLongPtrW(win["hwnd"], -20)
        if ex_style & WS_EX_APPWINDOW:
            return int(win["hwnd"])
    return 0


def click_at(dm, x: int, y: int, before: float = 0.3, after: float = 0.2) -> None:
    """移动并点击客户区坐标。"""
    dm.move_to(x, y)
    time.sleep(before)
    dm.left_click()
    time.sleep(after)


def double_click_at(dm, x: int, y: int, before: float = 0.3, after: float = 0.3) -> None:
    """移动并双击客户区坐标，用于获得编辑框焦点。"""
    dm.move_to(x, y)
    time.sleep(before)
    dm.left_double_click()
    time.sleep(after)


def set_dialog_active(dialog_hwnd: int) -> None:
    """激活弹窗（用于测试焦点问题，会短暂把弹窗提到前台）。"""
    try:
        user32 = ctypes.windll.user32
        user32.SetForegroundWindow(dialog_hwnd)
        time.sleep(0.2)
        logger.info(f"已尝试 SetForegroundWindow 激活弹窗: {dialog_hwnd}")
    except Exception as e:
        logger.warning(f"激活弹窗失败: {e}")


def send_activate_messages(dialog_hwnd: int) -> None:
    """向弹窗发送 WM_ACTIVATE / WM_SETFOCUS，尝试在后台激活焦点。

    不窃取前台，只是给 Qt 发送激活/获得焦点消息，让它愿意接收输入。
    """
    try:
        user32 = ctypes.windll.user32
        WM_ACTIVATE = 0x06
        WM_SETFOCUS = 0x07
        WA_ACTIVE = 1
        user32.SendMessageW(dialog_hwnd, WM_ACTIVATE, WA_ACTIVE, 0)
        time.sleep(0.1)
        user32.SendMessageW(dialog_hwnd, WM_SETFOCUS, 0, 0)
        time.sleep(0.1)
        logger.info(f"已发送 WM_ACTIVATE + WM_SETFOCUS 到弹窗: {dialog_hwnd}")
    except Exception as e:
        logger.warning(f"发送激活消息失败: {e}")


def get_password_area(password_input: list, dialog_size: tuple = (584, 488), width: int = 220, height: int = 50) -> list:
    """根据密码输入框中心点计算截图区域，限制在客户区范围内。"""
    cx, cy = password_input
    x1 = max(0, cx - width // 2)
    y1 = max(0, cy - height // 2)
    x2 = min(dialog_size[0], cx + width // 2)
    y2 = min(dialog_size[1], cy + height // 2)
    return [x1, y1, x2, y2]


def image_mean_diff(path1: str, path2: str) -> float:
    """计算两张图的灰度平均差异，0 表示完全相同。"""
    try:
        img1 = Image.open(path1).convert("L")
        img2 = Image.open(path2).convert("L")
        if img1.size != img2.size:
            return -1.0
        diff = ImageChops.difference(img1, img2)
        stat = ImageStat.Stat(diff)
        return stat.mean[0]
    except Exception as e:
        logger.warning(f"图片对比失败: {e}")
        return -1.0


def input_password(
    dm,
    password: str,
    dialog_hwnd: int,
    password_input: list,
    bind_cfg: dict,
    activate: bool = False,
    activate_msgs: bool = False,
    input_mouse: str = None,
    mode: int = None,
    method: str = "all",
) -> bool:
    """在弹窗中输入密码，并通过同一区域截图对比判断是否成功。

    method 控制只执行哪种输入方法（用于单独验证）：
      - "all"           依次执行 send_string2 -> Tab+send_string2 -> key_press_char（默认，原行为）
      - "send_string2"  只执行方法1 send_string2
      - "tab"           只执行方法2 Tab×3 + send_string2
      - "key_press"     只执行方法3 逐个 key_press_char
    """
    x1, y1, x2, y2 = dm.get_client_rect(dialog_hwnd)
    dialog_size = (x2 - x1, y2 - y1)
    area = get_password_area(password_input, dialog_size)
    logger.info(f"弹窗客户区尺寸: {dialog_size}, 密码输入截图区域: {area}")
    print(f"[INFO] 输入方法: {method}", flush=True)

    # 如果指定了 input_mouse 或 mode，单独为输入阶段调整绑定参数
    input_bind_cfg = copy.deepcopy(bind_cfg)
    if input_mouse:
        input_bind_cfg["mouse"] = input_mouse
        logger.info(f"输入阶段使用 mouse: {input_mouse}")
    if mode is not None:
        input_bind_cfg["mode"] = mode
        logger.info(f"输入阶段使用 mode: {mode}")

    if activate:
        set_dialog_active(dialog_hwnd)
    if activate_msgs:
        send_activate_messages(dialog_hwnd)

    with dm.bind_window(dialog_hwnd, bind_cfg=input_bind_cfg):
        # 点击输入框
        click_at(dm, *password_input)
        time.sleep(0.2)
        # 双击进一步争取焦点
        double_click_at(dm, *password_input)

    # 清空前截图
    before_clear = save_region(dm, dialog_hwnd, area, input_bind_cfg, "password_before_clear")
    logger.info(f"清空前截图: {before_clear}")

    with dm.bind_window(dialog_hwnd, bind_cfg=input_bind_cfg):
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

    # 清空后截图
    after_clear = save_region(dm, dialog_hwnd, area, input_bind_cfg, "password_after_clear")
    if before_clear and after_clear:
        diff = image_mean_diff(before_clear, after_clear)
        logger.info(f"清空前后差异: {diff:.2f}")

    with dm.bind_window(dialog_hwnd, bind_cfg=input_bind_cfg):
        # 再次点击并双击确保焦点
        click_at(dm, *password_input)
        time.sleep(0.1)
        double_click_at(dm, *password_input)

        # 方法 1: send_string2
        if method in ("all", "send_string2"):
            ret = dm.send_string2(password, hwnd=dialog_hwnd)
            logger.info(f"send_string2 返回值: {ret}")
            print(f"[RESULT] send_string2 返回值: {ret}", flush=True)
            time.sleep(0.5)

    # send_string2 后截图
    if method in ("all", "send_string2"):
        after_send = save_region(dm, dialog_hwnd, area, input_bind_cfg, "password_after_send_string2")
        if after_clear and after_send:
            diff = image_mean_diff(after_clear, after_send)
            logger.info(f"send_string2 输入前后差异: {diff:.2f}")
            print(f"[RESULT] send_string2 输入前后差异: {diff:.2f}", flush=True)
            if diff < 0.5:
                logger.warning("send_string2 输入后图像无明显变化，可能未输入成功")
                print("[RESULT] send_string2 图像无明显变化（gdi 截 Qt 弹窗本就截不到，不代表未输入）", flush=True)

    with dm.bind_window(dialog_hwnd, bind_cfg=input_bind_cfg):
        # 尝试 Tab 切焦点后再 send_string2
        if method in ("all", "tab"):
            for _ in range(3):
                dm.key_press_char("tab")
                time.sleep(0.1)
            ret2 = dm.send_string2(password, hwnd=dialog_hwnd)
            logger.info(f"Tab 后 send_string2 返回值: {ret2}")
            print(f"[RESULT] Tab 后 send_string2 返回值: {ret2}", flush=True)
            time.sleep(0.5)

    if method in ("all", "tab"):
        after_tab = save_region(dm, dialog_hwnd, area, input_bind_cfg, "password_after_tab")
        if after_clear and after_tab:
            diff = image_mean_diff(after_clear, after_tab)
            logger.info(f"Tab 后 send_string2 差异: {diff:.2f}")
            print(f"[RESULT] Tab 后 send_string2 差异: {diff:.2f}", flush=True)

    with dm.bind_window(dialog_hwnd, bind_cfg=input_bind_cfg):
        # 方法 3 兜底：逐个按键
        if method in ("all", "key_press"):
            for ch in password:
                dm.key_press_char(ch)
                time.sleep(0.05)
            logger.info(f"已兜底按键输入: {password}")
            print(f"[RESULT] 已执行 key_press_char 兜底输入: {password}", flush=True)
            time.sleep(0.5)

    if method in ("all", "key_press"):
        after_key = save_region(dm, dialog_hwnd, area, input_bind_cfg, "password_after_key_press")
        if after_clear and after_key:
            diff = image_mean_diff(after_clear, after_key)
            logger.info(f"key_press_char 兜底输入前后差异: {diff:.2f}")
            print(f"[RESULT] key_press_char 兜底输入前后差异: {diff:.2f}", flush=True)
            if diff < 0.5:
                logger.warning("key_press_char 输入后图像也无明显变化，可能未输入成功")

    # 最终完整弹窗截图
    save_region(dm, dialog_hwnd, [], input_bind_cfg, "dialog_after_password")
    return True


def main():
    parser = argparse.ArgumentParser(description="KK 后台创建房间测试")
    parser.add_argument("--delay", type=int, default=5, help="启动前等待秒数（默认 5）")
    parser.add_argument("--password", type=str, default=None, help="房间密码（默认读取 kk.create_room.password）")
    parser.add_argument("--activate", action="store_true", help="输入前用 SetForegroundWindow 激活弹窗（测试焦点问题）")
    parser.add_argument("--activate-msgs", action="store_true", help="输入前发送 WM_ACTIVATE + WM_SETFOCUS（不窃取前台）")
    parser.add_argument("--input-mouse", type=str, default=None, help="输入阶段单独指定 mouse 模式（如 windows / windows3 / normal）")
    parser.add_argument("--mode", type=int, default=None, help="输入阶段单独指定大漠 mode（默认读取 bind_multi.mode）")
    parser.add_argument("--dialog-open", action="store_true", help="弹窗已手动打开，跳过点击创建房间按钮，直接查找弹窗并输入密码、点击创建")
    parser.add_argument("--method", type=str, default="all", choices=["all", "send_string2", "tab", "key_press"],
                        help="只执行指定输入方法用于单独验证：all(默认)/send_string2/tab/key_press")
    parser.add_argument("--bind-mode", type=str, default="foreground", choices=["foreground", "background"],
                        help="绑定模式：foreground(前台 bind) / background(后台 bind_multi)")
    parser.add_argument("--bind-multi", action="store_true", help="强制使用 bind_multi（模拟后台）")
    args = parser.parse_args()

    setup_log_file("测试创建房间")
    logger.info("=" * 60)
    logger.info("KK 后台创建房间测试")
    logger.info("=" * 60)

    for i in range(args.delay, 0, -1):
        logger.info(f"{i} 秒后开始...")
        time.sleep(1)

    cfg = config.load_task("kk")
    kk_cfg = cfg.get("kk", {})

    # 绑定配置选择逻辑与生产代码（team/base.py）一致：
    # foreground 用 bind（前台），background 或 --bind-multi 用 bind_multi（后台）
    bind_mode = args.bind_mode
    if bind_mode == "background" or args.bind_multi:
        bind_cfg = copy.deepcopy(kk_cfg.get("bind_multi", {}))
        if not bind_cfg:
            bind_cfg = copy.deepcopy(kk_cfg.get("bind", {}))
    else:
        bind_cfg = copy.deepcopy(kk_cfg.get("bind", {}))
    logger.info(f"bind_mode={bind_mode}, 使用绑定配置: {bind_cfg}")

    main_cfg = kk_cfg.get("main", {})
    create_cfg = kk_cfg.get("create_room", {})

    password = args.password
    if password is None:
        password = create_cfg.get("password", "1234")
    main_window_size = tuple(main_cfg.get("window_size", [1332, 945]))
    dialog_window_size = tuple(create_cfg.get("dialog_window_size", [584, 488]))
    create_button_coords = main_cfg.get("create_button_coords", [0, 0])
    password_input_coords = create_cfg.get("password_input_coords", [0, 0])
    confirm_create_coords = create_cfg.get("confirm_create_coords", [0, 0])
    dialog_wait_time = create_cfg.get("dialog_wait_time", 2)
    create_wait_time = create_cfg.get("create_wait_time", 3)

    if create_button_coords == [0, 0] or password_input_coords == [0, 0] or confirm_create_coords == [0, 0]:
        logger.error("坐标未配置完整")
        return

    dm = create_dm_client()
    logger.info(f"大漠版本: {dm.version}")

    try:
        if args.dialog_open:
            # 弹窗已手动打开：直接查找弹窗，不碰大厅窗口
            logger.info("--dialog-open 已指定，直接查找已打开的创建房间弹窗")
            dialog_hwnd = find_create_room_dialog(dm, kk_cfg, pid=0)
            if not dialog_hwnd:
                logger.error("未找到创建房间弹窗，请确认弹窗已打开")
                return
            logger.info(f"创建房间弹窗: hwnd={dialog_hwnd}")
            pid = dm.get_window_process_id(dialog_hwnd)
        else:
            # 1. 查找并统一大厅尺寸
            hall_hwnd = find_hall_window(dm, kk_cfg)
            if not hall_hwnd:
                logger.error("未找到 KK 大厅窗口")
                return
            logger.info(f"大厅窗口: hwnd={hall_hwnd}")
            dm.set_client_size(hall_hwnd, *main_window_size)
            time.sleep(0.5)
            pid = dm.get_window_process_id(hall_hwnd)

            # 2. 点击创建房间按钮
            logger.info("点击创建房间按钮")
            with dm.bind_window(hall_hwnd, bind_cfg=bind_cfg):
                click_at(dm, *create_button_coords)

            logger.info(f"等待 {dialog_wait_time} 秒弹窗...")
            time.sleep(dialog_wait_time)

            # 3. 查找创建房间弹窗
            dialog_hwnd = find_create_room_dialog(dm, kk_cfg, pid)
            if not dialog_hwnd:
                logger.error("未找到创建房间弹窗，请确认当前页面能点击创建按钮")
                save_region(dm, hall_hwnd, [], bind_cfg, "hall_after_click_create")
                return
            logger.info(f"创建房间弹窗: hwnd={dialog_hwnd}")

        dm.set_client_size(dialog_hwnd, *dialog_window_size)
        time.sleep(0.5)

        # 4. 输入密码
        OUT_DIR.mkdir(parents=True, exist_ok=True)
        dx1, dy1, dx2, dy2 = dm.get_client_rect(dialog_hwnd)
        actual_dialog_size = (dx2 - dx1, dy2 - dy1)
        logger.info(f"弹窗实际客户区尺寸: {actual_dialog_size}")

        before_path = save_region(dm, dialog_hwnd, [], bind_cfg, "dialog_before_password")
        if before_path:
            marker_path = (OUT_DIR / "dialog_with_markers.bmp").resolve()
            password_area = get_password_area(password_input_coords, actual_dialog_size)
            draw_markers(before_path, str(marker_path), [password_input_coords, confirm_create_coords], password_area)
            logger.info(f"已生成带坐标标记的截图: {marker_path}")

        logger.info(f"开始输入密码: {password}")
        input_password(
            dm,
            password,
            dialog_hwnd,
            password_input_coords,
            bind_cfg,
            activate=args.activate,
            activate_msgs=args.activate_msgs,
            input_mouse=args.input_mouse,
            mode=args.mode,
            method=args.method,
        )
        save_region(dm, dialog_hwnd, [], bind_cfg, "dialog_after_password")

        # 5. 点击确认创建
        logger.info("点击创建确认按钮")
        with dm.bind_window(dialog_hwnd, bind_cfg=bind_cfg):
            click_at(dm, *confirm_create_coords)

        logger.info(f"等待 {create_wait_time} 秒房间窗口...")
        time.sleep(create_wait_time)

        # 6. 查找房间窗口
        room_hwnd = find_room_window(dm, kk_cfg, pid)
        if room_hwnd:
            logger.info(f"创建成功，房间窗口: hwnd={room_hwnd}")
        else:
            logger.error("未找到房间窗口，密码输入或创建流程失败")

    except Exception as e:
        logger.exception(f"流程异常: {e}")
    finally:
        dm.close()
        # 强制 flush 异步日志（logger sink 用 enqueue=True），确保日志落盘
        logger.complete()


if __name__ == "__main__":
    sys.exit(main())
