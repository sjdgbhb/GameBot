"""SendString 兼容性测试：KK / War3 文本输入验证。

用法：
    uv run python tests/manual/test_send_string_compat.py --kk-search
    uv run python tests/manual/test_send_string_compat.py --kk-password
    uv run python tests/manual/test_send_string_compat.py --war3

可选参数：
    --api send_string2   用旧版 SendString2 对照测试（默认 send_string）
    --mode foreground|background   覆盖绑定模式（默认用配置解析结果）
    --delay N            启动前等待秒数（默认 5）

测试内容：
- --kk-search：KK 大厅地图搜索框，输入中文+字母数字混合文本
- --kk-password：KK 创建房间密码弹窗（需先手动打开弹窗），输入密码
- --war3：War3 聊天框，依次发送一条中文、一条字母数字消息

每步输入后截图保存到 logs/diag_send_string/，请人工核对截图与游戏内实际显示。
"""

import argparse
import ctypes
import sys
import time
from ctypes import wintypes
from datetime import datetime
from pathlib import Path

from PIL import Image

from GameBot.config import config
from GameBot.runner.driver import create_dm_client
from GameBot.utils import logger, setup_log_file

OUT_DIR = Path("logs/diag_send_string")


def is_blank_image(img_path: str) -> bool:
    """判断图片是否为纯色（黑屏/白屏）。"""
    try:
        mn, mx = Image.open(img_path).convert("L").getextrema()
        return mn == mx
    except Exception:
        return False


def save_region(dm, hwnd: int, region: list, bind_cfg: dict, label: str) -> str:
    """截取窗口客户区指定区域保存到 OUT_DIR，返回文件路径。"""
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%H%M%S")
    out_path = (OUT_DIR / f"{label}_{hwnd}_{timestamp}.bmp").resolve()
    try:
        with dm.bind_window(hwnd, bind_cfg=bind_cfg):
            ok = dm.capture_region(*region, str(out_path))
        if ok and not is_blank_image(str(out_path)):
            logger.info(f"截图已保存: {out_path}")
            return str(out_path)
    except Exception as e:
        logger.warning(f"截图失败 {label}: {e}")
    return ""


def find_window(dm, window_class: str, window_title: str) -> int:
    """按类名+标题查找可见窗口。"""
    for h in dm.enum_windows(window_class, window_title):
        if not dm.is_window_visible(h):
            continue
        if dm.get_window_class(h) != window_class:
            continue
        if window_title and dm.get_window_title(h) != window_title:
            continue
        return int(h)
    return 0


def enum_pid_windows(target_pid: int) -> list:
    """枚举指定 PID 的可见顶层窗口。"""
    user32 = ctypes.windll.user32
    EnumWindowsProc = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)
    results = []

    def cb(hwnd, _):
        if not user32.IsWindowVisible(hwnd):
            return True
        pid = ctypes.c_ulong()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if int(pid.value) != target_pid:
            return True
        cls = ctypes.create_unicode_buffer(256)
        user32.GetClassNameW(hwnd, cls, 256)
        rect = wintypes.RECT()
        user32.GetWindowRect(hwnd, ctypes.byref(rect))
        results.append({"hwnd": int(hwnd), "class": cls.value, "rect": (rect.left, rect.top, rect.right, rect.bottom)})
        return True

    user32.EnumWindows(EnumWindowsProc(cb), 0)
    return results


def find_create_room_dialog(kk_cfg: dict, owner_pid: int) -> int:
    """查找已打开的创建房间弹窗（需用户先手动打开）。"""
    popup_class = kk_cfg.get("create_room_window_class", "")
    dialog_size = tuple(kk_cfg.get("create_room", {}).get("dialog_window_size", [584, 488]))
    size_tol = 30
    for win in enum_pid_windows(owner_pid):
        if popup_class and popup_class.lower() not in win["class"].lower():
            continue
        if win["class"] == kk_cfg.get("window_class", ""):
            continue  # 排除大厅主窗口
        w = win["rect"][2] - win["rect"][0]
        h = win["rect"][3] - win["rect"][1]
        if abs(w - dialog_size[0]) > size_tol or abs(h - dialog_size[1]) > size_tol:
            continue
        return int(win["hwnd"])
    return 0


def resolve_bind_cfg(cfg: dict, ns: str, mode: str = None) -> dict:
    """取解析后的 bind；--mode 指定时改用 bind_foreground/bind_background。"""
    ns_cfg = cfg.get(ns, {})
    if mode:
        src = ns_cfg.get("bind_background" if mode == "background" else "bind_foreground", {})
        return dict(src)
    return dict(ns_cfg.get("bind", {}))


def send_text(dm, text: str, hwnd: int, api: str):
    """按 --api 选择 SendString/SendString2 发送文本。"""
    if api == "send_string2":
        return dm.send_string2(text, hwnd=hwnd)
    return dm.send_string(text, hwnd=hwnd)


# ── KK 大厅搜索框：中文+字母数字 ─────────────────────────


def test_kk_search(dm, kk_cfg: dict, bind_cfg: dict, api: str) -> int:
    hall_hwnd = find_window(dm, kk_cfg.get("window_class", ""), kk_cfg.get("window_title", ""))
    if not hall_hwnd:
        logger.error("未找到 KK 主界面窗口")
        return 1
    logger.info(f"KK 大厅 hwnd={hall_hwnd}")

    main_cfg = kk_cfg.get("main", {})
    search_coords = main_cfg.get("search_input_coords", [0, 0])
    if search_coords == [0, 0]:
        logger.error("未配置 kk.main.search_input_coords")
        return 1

    text = "九种兵器2测试abc123"
    with dm.bind_window(hall_hwnd, bind_cfg=bind_cfg):
        dm.move_to(*search_coords)
        time.sleep(0.3)
        dm.left_click()
        time.sleep(0.2)
        # 清空输入框：End 到末尾 + 退格
        dm.key_press_char("end")
        time.sleep(0.1)
        for _ in range(50):
            dm.key_press_char("back")
        time.sleep(0.1)
        ret = send_text(dm, text, hall_hwnd, api)
        logger.info(f"{api} 返回值: {ret}，输入: {text}")
        time.sleep(0.5)

    x1, y1 = search_coords
    save_region(dm, hall_hwnd, [x1 - 20, y1 - 15, x1 + 300, y1 + 15], bind_cfg, "kk_search")
    logger.info("请核对截图：搜索框应显示「九种兵器2测试abc123」且无乱码")
    return 0


# ── KK 密码弹窗 ────────────────────────────────────────


def test_kk_password(dm, kk_cfg: dict, bind_cfg: dict, api: str, password: str) -> int:
    hall_hwnd = find_window(dm, kk_cfg.get("window_class", ""), kk_cfg.get("window_title", ""))
    if not hall_hwnd:
        logger.error("未找到 KK 主界面窗口")
        return 1
    owner_pid = dm.get_window_process_id(hall_hwnd)
    dialog_hwnd = find_create_room_dialog(kk_cfg, owner_pid)
    if not dialog_hwnd:
        logger.error("未找到创建房间弹窗，请先手动打开「创建房间」弹窗再运行")
        return 1
    logger.info(f"密码弹窗 hwnd={dialog_hwnd}")

    password_coords = kk_cfg.get("create_room", {}).get("password_input_coords", [0, 0])
    if password_coords == [0, 0]:
        logger.error("未配置 kk.create_room.password_input_coords")
        return 1

    with dm.bind_window(dialog_hwnd, bind_cfg=bind_cfg):
        dm.move_to(*password_coords)
        time.sleep(0.5)
        dm.left_click()
        time.sleep(0.5)
        # 清空：Ctrl+A 全选（后台模式下比多次退格可靠）
        dm.key_press_char("ctrl+a")
        time.sleep(0.2)
        ret = send_text(dm, password, dialog_hwnd, api)
        logger.info(f"{api} 返回值: {ret}，输入: {password}")
        time.sleep(0.5)

    x1, y1 = password_coords
    save_region(dm, dialog_hwnd, [x1 - 10, y1 - 15, x1 + 250, y1 + 15], bind_cfg, "kk_password")
    logger.info("请核对截图/弹窗：密码框应显示与密码位数一致的圆点")
    return 0


# ── War3 聊天框：中文 + 字母数字 ────────────────────────


def test_war3_chat(dm, war3_cfg: dict, bind_cfg: dict, api: str) -> int:
    hwnd = find_window(dm, war3_cfg.get("window_class", ""), war3_cfg.get("window_title", ""))
    if not hwnd:
        logger.error("未找到 war3 窗口（请先进入游戏）")
        return 1
    logger.info(f"war3 hwnd={hwnd}")

    key_time = war3_cfg.get("key_time", 0.1)
    x1, y1, x2, y2 = dm.get_client_rect(hwnd)
    full_region = [x1, y1, x2, y2]

    with dm.bind_window(hwnd, bind_cfg=bind_cfg):
        for label, text in (("chinese", "测试中文发送"), ("ascii", "abc123-xyz")):
            dm.key_press_char("enter")  # 开聊天框
            time.sleep(0.3)
            # 退格清残留
            for _ in range(5):
                dm.key_press_char("back")
                time.sleep(0.03)
            ret = send_text(dm, text, hwnd, api)
            logger.info(f"{api} [{label}] 返回值: {ret}，输入: {text}")
            time.sleep(0.3)
            dm.key_press_char("enter")  # 发送
            time.sleep(key_time + 0.2)

    # 截图取证：聊天区应保留刚发出的两条消息
    save_region(dm, hwnd, full_region, bind_cfg, "war3_chat")

    logger.info("请核对：聊天区应看到「测试中文发送」和「abc123-xyz」两条消息，无乱码")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="SendString 兼容性测试（KK / War3）")
    parser.add_argument("--kk-search", action="store_true", help="测试 KK 大厅地图搜索框中文输入")
    parser.add_argument("--kk-password", action="store_true", help="测试 KK 创建房间密码弹窗（需先手动打开弹窗）")
    parser.add_argument("--war3", action="store_true", help="测试 War3 聊天框中文/字母数字输入")
    parser.add_argument("--api", choices=["send_string", "send_string2"], default="send_string", help="使用的 dm 接口")
    parser.add_argument("--mode", choices=["foreground", "background"], default=None, help="覆盖绑定模式")
    parser.add_argument("--delay", type=int, default=5, help="启动前等待秒数")
    parser.add_argument("--password", type=str, default=None, help="密码测试文本（默认读 kk.create_room.password）")
    args = parser.parse_args()

    if not (args.kk_search or args.kk_password or args.war3):
        parser.print_help()
        return 1

    setup_log_file("SendString兼容性测试")
    logger.info("=" * 60)
    logger.info(f"SendString 兼容性测试 api={args.api} mode={args.mode or '配置默认'}")
    logger.info("=" * 60)

    for i in range(args.delay, 0, -1):
        logger.info(f"{i} 秒后开始...")
        time.sleep(1)

    dm = create_dm_client()
    logger.info(f"大漠版本: {dm.version}")

    try:
        rc = 0
        if args.kk_search or args.kk_password:
            cfg = config.load_task("kk")
            kk_cfg = cfg.get("kk", {})
            bind_cfg = resolve_bind_cfg(cfg, "kk", args.mode)
            logger.info(f"KK 绑定配置: {bind_cfg}")
            if args.kk_search:
                rc = test_kk_search(dm, kk_cfg, bind_cfg, args.api) or rc
            if args.kk_password:
                password = args.password or kk_cfg.get("create_room", {}).get("password", "test123")
                rc = test_kk_password(dm, kk_cfg, bind_cfg, args.api, password) or rc

        if args.war3:
            cfg = config.load_task("war3.jiubing2.tasks.others.fishing")
            war3_cfg = cfg.get("war3", {})
            bind_cfg = resolve_bind_cfg(cfg, "war3", args.mode)
            logger.info(f"war3 绑定配置: {bind_cfg}")
            rc = test_war3_chat(dm, war3_cfg, bind_cfg, args.api) or rc
        return rc
    finally:
        dm.close()


if __name__ == "__main__":
    sys.exit(main())
