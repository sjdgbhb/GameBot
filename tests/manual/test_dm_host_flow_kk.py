"""测试 KK 房主完整流程：

大厅搜索地图 -> 点击搜索结果 -> 进入地图详情 -> 点击创建房间
-> 输入密码 -> 点击确认 -> 等待进入房间 -> 识别房间号。

用法：
    uv run python tests/manual/test_dm_host_flow_kk.py
    uv run python tests/manual/test_dm_host_flow_kk.py --delay 10
    uv run python tests/manual/test_dm_host_flow_kk.py --mouse windows3 --keypad windows

配置来源：
- src/GameBot/config/data/kk.toml
- src/GameBot/config/data/war3/jiubing2/jiubing2.toml
"""

import argparse
import copy
import ctypes
import sys
import time
from pathlib import Path

from PIL import Image

from GameBot.config import config
from GameBot.inference import get_inference_client
from GameBot.runner.driver import create_dm_client
from GameBot.utils import logger, setup_log_file

OUT_DIR = Path("logs/diag_dm_host_flow")
WS_EX_APPWINDOW = 0x80000


def enum_visible_windows_by_pid(target_pid: int) -> list:
    """枚举指定 PID 的所有可见顶层窗口，返回 [{hwnd, title, class, rect}]。

    使用 Win32 API 直接枚举，不依赖大漠窗口相关 COM。
    """
    user32 = ctypes.windll.user32
    EnumWindows = user32.EnumWindows
    EnumWindowsProc = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)
    GetWindowTextW = user32.GetWindowTextW
    GetWindowTextLengthW = user32.GetWindowTextLengthW
    GetClassNameW = user32.GetClassNameW
    IsWindowVisible = user32.IsWindowVisible
    GetWindowRect = user32.GetWindowRect
    GetWindowThreadProcessId = user32.GetWindowThreadProcessId

    results = []

    def callback(hwnd, _lparam):
        if not IsWindowVisible(hwnd):
            return True
        pid = ctypes.c_ulong()
        GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if int(pid.value) != target_pid:
            return True
        length = GetWindowTextLengthW(hwnd)
        buf = ctypes.create_unicode_buffer(length + 1)
        GetWindowTextW(hwnd, buf, length + 1)
        cls_buf = ctypes.create_unicode_buffer(256)
        GetClassNameW(hwnd, cls_buf, 256)
        rect = ctypes.wintypes.RECT()
        GetWindowRect(hwnd, ctypes.byref(rect))
        results.append(
            {
                "hwnd": int(hwnd),
                "title": buf.value,
                "class": cls_buf.value,
                "rect": (int(rect.left), int(rect.top), int(rect.right), int(rect.bottom)),
            }
        )
        return True

    EnumWindows(EnumWindowsProc(callback), 0)
    return results


def find_hall_window(dm, kk_cfg: dict) -> int:
    """按类名+标题精确匹配查找 KK 主界面窗口。"""
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


def find_create_room_dialog(dm, kk_cfg: dict, pid: int) -> int:
    """在指定 PID 的可见窗口中查找创建房间弹窗。

    通过类名和尺寸匹配，过滤掉掉线重连等其他 Qt5152QWindow 弹窗。
    """
    popup_class = kk_cfg.get("create_room_window_class", "")
    create_cfg = kk_cfg.get("create_room", {})
    target_w, target_h = create_cfg.get("dialog_window_size", [584, 488])
    size_tol = 30

    for win in enum_visible_windows_by_pid(pid):
        if popup_class and popup_class.lower() not in win["class"].lower():
            continue
        w = win["rect"][2] - win["rect"][0]
        h = win["rect"][3] - win["rect"][1]
        if abs(w - target_w) > size_tol or abs(h - target_h) > size_tol:
            continue
        return int(win["hwnd"])
    return 0


def find_room_window(dm, kk_cfg: dict, pid: int) -> int:
    """在指定 PID 的可见窗口中查找 KK 房间窗口。

    房间窗口与主界面类名相同，但 ExStyle 包含 WS_EX_APPWINDOW。
    """
    window_class = kk_cfg.get("window_class", "")
    min_w, min_h = kk_cfg.get("min_business_window_size", [200, 200])
    room_cfg = kk_cfg.get("room", {})
    room_size = tuple(room_cfg.get("window_size", [1224, 904]))
    size_tol = 30

    user32 = ctypes.windll.user32
    GetWindowLongPtrW = user32.GetWindowLongPtrW

    for win in enum_visible_windows_by_pid(pid):
        if win["class"] != window_class:
            continue
        w = win["rect"][2] - win["rect"][0]
        h = win["rect"][3] - win["rect"][1]
        if w < min_w or h < min_h:
            continue
        if room_size[0] > 0 and abs(w - room_size[0]) > size_tol and abs(h - room_size[1]) > size_tol:
            # 尺寸接近房间窗口才认，避免大厅窗口
            continue
        ex_style = GetWindowLongPtrW(win["hwnd"], -20)  # GWL_EXSTYLE
        if ex_style & WS_EX_APPWINDOW:
            return int(win["hwnd"])
    return 0


def is_blank_image(img_path: str) -> bool:
    """判断图片是否为空/黑屏/白屏。"""
    try:
        mn, mx = Image.open(img_path).convert("L").getextrema()
        return mn == mx
    except Exception:
        return False


def save_region(dm, hwnd: int, area: list, bind_cfg: dict, label: str) -> str:
    """绑定窗口并截图指定客户区区域，保存到 OUT_DIR，返回文件路径或空字符串。"""
    if not area or area[2] <= area[0] or area[3] <= area[1]:
        return ""
    out_path = (OUT_DIR / f"{label}.bmp").resolve()
    try:
        with dm.bind_window(hwnd, bind_cfg=bind_cfg):
            ok = dm.capture_region(area[0], area[1], area[2], area[3], str(out_path))
            if ok and not is_blank_image(str(out_path)):
                return str(out_path)
    except Exception as e:
        logger.warning(f"截图失败 {label}: {e}")
    return ""


def ocr_area(dm, hwnd: int, area: list, bind_cfg: dict, inf, merge_lines: bool = False) -> list:
    """截图指定客户区区域并 OCR，返回 [{text, x_center, y_center}]。"""
    img_path = save_region(dm, hwnd, area, bind_cfg, "ocr_tmp")
    if not img_path:
        return []
    try:
        return inf.ocr_lines_from_file(img_path, merge_lines=merge_lines)
    except Exception as e:
        logger.warning(f"OCR 失败: {e}")
        return []


def longest_common_substring_len(a: str, b: str) -> int:
    """计算两个字符串的最长连续公共子串长度。"""
    if not a or not b:
        return 0
    m, n = len(a), len(b)
    dp = [[0] * (n + 1) for _ in range(m + 1)]
    best = 0
    for i in range(1, m + 1):
        for j in range(1, n + 1):
            if a[i - 1] == b[j - 1]:
                dp[i][j] = dp[i - 1][j - 1] + 1
                best = max(best, dp[i][j])
    return best


def find_map_result(lines: list, map_name: str, area: list) -> tuple:
    """在 OCR 行中查找地图名，返回 (line, client_x, client_y) 或 (None, 0, 0)。

    坐标会加上 area 的左上角偏移，转换为客户区坐标。
    """
    if not lines:
        return None, 0, 0

    # 优先完整包含
    for line in lines:
        text = line.get("text", "").strip()
        if map_name in text:
            x = area[0] + int(line["x_center"])
            y = area[1] + int(line["y_center"])
            return line, x, y

    # 模糊匹配，LCS 至少占地图名 60%
    best = (None, 0, 0, 0)
    for line in lines:
        text = line.get("text", "").strip()
        if not text:
            continue
        lcs = longest_common_substring_len(map_name, text)
        if lcs >= len(map_name) * 0.6 and lcs > best[3]:
            x = area[0] + int(line["x_center"])
            y = area[1] + int(line["y_center"])
            best = (line, x, y, lcs)

    if best[0]:
        logger.info(f"模糊匹配命中: OCR='{best[0]['text']}', LCS={best[3]}")
        return best[0], best[1], best[2]
    return None, 0, 0


def click_at(dm, x: int, y: int, before: float = 0.3, after: float = 0.2) -> None:
    """移动鼠标并左键点击指定客户区坐标。"""
    dm.move_to(x, y)
    time.sleep(before)
    dm.left_click()
    time.sleep(after)


def input_text(dm, text: str, hwnd: int) -> None:
    """在已绑定的窗口中清空输入框并输入文本。

    先 End + 多次 Backspace，再 Ctrl+A + Backspace 兜底。
    """
    dm.key_press_char("end")
    time.sleep(0.1)
    for _ in range(30):
        dm.key_press_char("back")
        time.sleep(0.01)
    dm.key_press_char("ctrl+a")
    time.sleep(0.2)
    dm.key_press_char("back")
    time.sleep(0.2)
    dm.send_string(text, hwnd=hwnd)


def run_host_flow(
    dm,
    kk_cfg: dict,
    bind_cfg: dict,
    map_name: str,
    password: str,
    inf,
) -> int:
    """执行房主流程，返回房间窗口句柄（失败返回 0）。"""
    main_cfg = kk_cfg.get("main", {})
    create_cfg = kk_cfg.get("create_room", {})
    room_cfg = kk_cfg.get("room", {})

    main_size = tuple(main_cfg.get("window_size", [1332, 945]))
    search_input = main_cfg.get("search_input_coords", [0, 0])
    search_icon = main_cfg.get("search_map_coords", [0, 0])
    search_wait = main_cfg.get("search_map_wait_time", 5)
    result_area = main_cfg.get("map_result_ocr_area_coords", [0, 0, 0, 0])
    detail_wait = main_cfg.get("detail_wait_time", 3)
    create_button = main_cfg.get("create_button_coords", [0, 0])
    dialog_wait = create_cfg.get("dialog_wait_time", 2)
    create_wait = create_cfg.get("create_wait_time", 3)
    dialog_size = tuple(create_cfg.get("dialog_window_size", [584, 488]))
    password_input = create_cfg.get("password_input_coords", [0, 0])
    confirm_button = create_cfg.get("confirm_create_coords", [0, 0])
    room_id_area = room_cfg.get("room_id_ocr_area_coords", [0, 0, 0, 0])

    # 1. 查找大厅窗口
    hall_hwnd = find_hall_window(dm, kk_cfg)
    if not hall_hwnd:
        logger.error("未找到 KK 主界面窗口")
        return 0
    logger.info(f"找到 KK 主界面窗口: hwnd={hall_hwnd}")

    dm.set_client_size(hall_hwnd, *main_size)
    time.sleep(0.5)
    pid = dm.get_window_process_id(hall_hwnd)
    logger.info(f"大厅 PID: {pid}")

    # 2. 输入地图名并点击搜索
    logger.info("步骤 1: 输入地图名")
    with dm.bind_window(hall_hwnd, bind_cfg=bind_cfg):
        click_at(dm, *search_input)
        input_text(dm, map_name, hall_hwnd)

    logger.info("步骤 2: 点击搜索图标")
    with dm.bind_window(hall_hwnd, bind_cfg=bind_cfg):
        click_at(dm, *search_icon)

    # 3. 等待并识别搜索结果
    logger.info(f"等待 {search_wait} 秒搜索结果...")
    time.sleep(search_wait)

    # 保存并 OCR 搜索结果区域
    img_path = save_region(dm, hall_hwnd, result_area, bind_cfg, "step3_search_result")
    lines = []
    if img_path:
        lines = inf.ocr_lines_from_file(img_path, merge_lines=False)
        logger.info(f"搜索结果 OCR: {[l['text'] for l in lines]}")

    target, click_x, click_y = find_map_result(lines, map_name, result_area)
    if not target:
        logger.error(f"未在搜索结果中找到地图: {map_name}")
        return 0
    logger.info(f"点击搜索结果: '{target['text']}' 坐标=({click_x},{click_y})")

    # 4. 点击搜索结果进入详情
    logger.info("步骤 3: 点击进入地图详情")
    with dm.bind_window(hall_hwnd, bind_cfg=bind_cfg):
        click_at(dm, click_x, click_y)

    logger.info(f"等待 {detail_wait} 秒加载地图详情...")
    time.sleep(detail_wait)

    # 5. 点击创建房间按钮
    logger.info("步骤 4: 点击创建房间按钮")
    with dm.bind_window(hall_hwnd, bind_cfg=bind_cfg):
        click_at(dm, *create_button)

    logger.info(f"等待 {dialog_wait} 秒创建房间弹窗...")
    time.sleep(dialog_wait)

    # 6. 查找创建房间弹窗
    dialog_hwnd = find_create_room_dialog(dm, kk_cfg, pid)
    if not dialog_hwnd:
        logger.error("未找到创建房间弹窗")
        return 0
    logger.info(f"找到创建房间弹窗: hwnd={dialog_hwnd}")

    dm.set_client_size(dialog_hwnd, *dialog_size)
    time.sleep(0.5)

    # 7. 在弹窗中输入密码并确认
    logger.info("步骤 5: 输入房间密码")
    with dm.bind_window(dialog_hwnd, bind_cfg=bind_cfg):
        click_at(dm, *password_input)
        input_text(dm, password, dialog_hwnd)

    logger.info("步骤 6: 点击确认创建")
    with dm.bind_window(dialog_hwnd, bind_cfg=bind_cfg):
        click_at(dm, *confirm_button)

    # 8. 等待房间窗口出现
    logger.info(f"等待 {create_wait} 秒房间窗口...")
    time.sleep(create_wait)

    room_hwnd = find_room_window(dm, kk_cfg, pid)
    if not room_hwnd:
        logger.error("未找到房间窗口")
        return 0
    logger.info(f"找到房间窗口: hwnd={room_hwnd}")

    # 9. 识别房间号
    dm.set_client_size(room_hwnd, *room_cfg.get("window_size", [1224, 904]))
    time.sleep(0.5)
    room_id_path = save_region(dm, room_hwnd, room_id_area, bind_cfg, "step7_room_id")
    if room_id_path:
        room_lines = inf.ocr_lines_from_file(room_id_path, merge_lines=False)
        logger.info(f"房间号 OCR: {[l['text'] for l in room_lines]}")

    return room_hwnd


def main() -> int:
    parser = argparse.ArgumentParser(description="KK 房主完整流程测试")
    parser.add_argument("--delay", type=int, default=5, help="启动前等待秒数（默认 5）")
    parser.add_argument("--map-name", type=str, default=None, help="搜索的地图名（默认读取 jiubing2.toml）")
    parser.add_argument("--password", type=str, default=None, help="房间密码（默认读取 kk.create_room.password）")
    parser.add_argument("--display", type=str, default=None, help="绑定 display（默认读取 kk.bind_background.display）")
    parser.add_argument("--mouse", type=str, default=None, help="绑定 mouse（默认读取 kk.bind_background.mouse）")
    parser.add_argument("--keypad", type=str, default=None, help="绑定 keypad（默认读取 kk.bind_background.keypad）")
    parser.add_argument("--mode", type=int, default=None, help="绑定 mode（默认读取 kk.bind_background.mode）")
    args = parser.parse_args()

    setup_log_file("kk房主流程测试")
    logger.info("=" * 60)
    logger.info("KK 房主完整流程测试")
    logger.info("=" * 60)

    # 倒计时
    for i in range(args.delay, 0, -1):
        logger.info(f"{i} 秒后开始...")
        time.sleep(1)

    # 加载配置
    kk_cfg = config.load_task("kk").get("kk", {})
    bind_background = copy.deepcopy(kk_cfg.get("bind_background", {}))
    if args.display is not None:
        bind_background["display"] = args.display
    if args.mouse is not None:
        bind_background["mouse"] = args.mouse
    if args.keypad is not None:
        bind_background["keypad"] = args.keypad
    if args.mode is not None:
        bind_background["mode"] = args.mode

    # 地图名
    map_name = args.map_name
    if not map_name:
        try:
            jiubing2_cfg = config.load_task("jiubing2")
            map_name = jiubing2_cfg.get("game", {}).get("map_name", "九种兵器2诸神战场")
        except Exception:
            map_name = "九种兵器2诸神战场"

    # 房间密码
    password = args.password
    if password is None:
        password = kk_cfg.get("create_room", {}).get("password", "1234")

    logger.info(f"地图名: {map_name}")
    logger.info(f"房间密码: {password}")
    logger.info(f"绑定配置: {bind_background}")

    OUT_DIR.mkdir(parents=True, exist_ok=True)

    dm = create_dm_client()
    logger.info(f"大漠版本: {dm.version}")
    inf = get_inference_client(load_chest=False, load_combat=False)

    try:
        room_hwnd = run_host_flow(dm, kk_cfg, bind_background, map_name, password, inf)
        if room_hwnd:
            logger.info(f"房主流程测试通过，房间窗口: hwnd={room_hwnd}")
            return 0
        else:
            logger.error("房主流程测试失败")
            return 1
    except Exception as e:
        logger.exception(f"流程异常: {e}")
        return 1
    finally:
        dm.close()


if __name__ == "__main__":
    sys.exit(main())
