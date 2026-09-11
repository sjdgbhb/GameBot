"""测试大漠后台截图对 KK 各类 Qt 窗口的截图能力。

覆盖五种单窗口测试目标（用户手动打开窗口后运行脚本）：
1. dropdown  — 下拉框（Qt5152QWindowPopupSaveBits），点击头像弹出
2. create_room — 创建房间弹窗（Qt5152QWindow），点击创建房间按钮弹出
3. password  — 加入房间的密码输入弹窗（Qt5152QWindow），搜索房间后点击搜索结果弹出
4. hall      — KK 大厅主界面窗口
5. room      — KK 房间窗口

新增 compatibility 目标，对 hall / dropdown / create_room / password / room 五个窗口
执行 BindWindowEx 兼容性矩阵测试，并生成 JSON 报告。

新增 render_password / render_room 目标，验证后台绑定下对窗口执行输入/点击
操作后，Windows API 强制刷新是否能让截图/OCR 画面更新。

配置来源：src/GameBot/config/data/kk.toml

用法：
    uv run python tests/manual/test_dm_background_capture.py dropdown
    uv run python tests/manual/test_dm_background_capture.py compatibility
    uv run python tests/manual/test_dm_background_capture.py compatibility --displays gdi dx --mice windows2
"""

from __future__ import annotations

import argparse
import ctypes
import ctypes.wintypes
import json
import sys
import time
from pathlib import Path

from GameBot.config import config
from GameBot.inference import get_inference_client
from GameBot.runner.driver import create_dm_client
from GameBot.utils import logger, setup_log_file

OUT_DIR = Path("logs/diag_dm_capture")

DEFAULT_DISPLAYS = ["gdi2", "gdi", "dx", "dx2", "dx3", "dx.graphic.2d", "dx.graphic.3d"]
DEFAULT_MICE = ["windows", "windows2", "windows3"]
DEFAULT_KEYPADS = ["windows"]
DEFAULT_MODES = [0]

# Windows API 强制刷新相关常量
RDW_INVALIDATE = 0x0001
RDW_UPDATENOW = 0x0100
RDW_ALLCHILDREN = 0x0080
SWP_NOMOVE = 0x0002
SWP_NOSIZE = 0x0001
SWP_NOZORDER = 0x0004
SWP_NOACTIVATE = 0x0010
SWP_FRAMECHANGED = 0x0020
SWP_NOCOPYBITS = 0x0100
PW_CLIENTONLY = 0x00000001
# PW_RENDERFULLCONTENT（Windows 8.1+）：强制窗口把当前完整内容
# （含未 flush 的 backing store / DWM 合成内容）渲染到目标 DC。
# 对 Qt 这种走 backing store 的窗口，这是唯一能主动逼出"输入后最新画面"的标志。
PW_RENDERFULLCONTENT = 0x00000002
PW_CLIENT_FULL = PW_CLIENTONLY | PW_RENDERFULLCONTENT  # 0x3


def load_bind_cfg(kk_cfg: dict) -> dict:
    """从 kk_cfg 读取后台绑定配置，优先使用 bind_multi。"""
    if "bind_multi" in kk_cfg:
        cfg = dict(kk_cfg["bind_multi"])
        logger.info(f"使用 bind_multi 后台绑定: {cfg}")
        return cfg
    bind_cfg = dict(kk_cfg.get("bind", {}))
    logger.info(f"使用 bind 配置: {bind_cfg}")
    return bind_cfg


def find_window_by_class(
    dm,
    window_class: str,
    window_title: str,
    expected_size: tuple[int, int] | None = None,
    size_tolerance: int = 50,
) -> int:
    """按类名+标题精确匹配窗口，可选按客户区尺寸过滤。

    :param expected_size: (w, h) 期望客户区尺寸，为 None 时不检查
    :param size_tolerance: 尺寸容差（像素）
    :return: 窗口句柄，未找到返回 0
    """
    candidates = dm.enum_windows(window_class, window_title, filter=1 + 2 + 16)
    for h in candidates:
        if not dm.is_window_visible(h):
            continue
        if dm.get_window_class(h) != window_class:
            continue
        if window_title and dm.get_window_title(h) != window_title:
            continue
        if expected_size:
            x1, y1, x2, y2 = dm.get_client_rect(h)
            w, h_ = x2 - x1, y2 - y1
            if abs(w - expected_size[0]) > size_tolerance or abs(h_ - expected_size[1]) > size_tolerance:
                continue
        return int(h)
    return 0


def find_hall_window(dm, kk_cfg: dict) -> int:
    """精确匹配类名+标题查找 KK 主界面窗口。"""
    window_class = kk_cfg.get("window_class", "")
    window_title = kk_cfg.get("window_title", "")
    for h in dm.enum_windows(window_class, window_title):
        if not dm.is_window_visible(h):
            continue
        if dm.get_window_class(h) != window_class:
            continue
        if window_title and dm.get_window_title(h) != window_title:
            continue
        return int(h)
    return 0


def enum_visible_windows_by_pid(target_pid: int) -> list[dict]:
    """枚举指定 PID 的所有可见顶层窗口，返回 [{hwnd, title, class, rect}]。"""
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


def _redraw_window(hwnd, flags: int) -> None:
    """调用 user32.RedrawWindow 强制刷新窗口客户区。

    :param hwnd: 目标窗口句柄
    :param flags: RedrawWindow flags（如 RDW_INVALIDATE | RDW_UPDATENOW）
    """
    user32 = ctypes.windll.user32
    user32.RedrawWindow.argtypes = [
        ctypes.wintypes.HWND,
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.wintypes.UINT,
    ]
    user32.RedrawWindow(int(hwnd), 0, 0, flags)


def _invalidate_update(hwnd) -> None:
    """调用 InvalidateRect + UpdateWindow 立即重绘窗口。"""
    user32 = ctypes.windll.user32
    user32.InvalidateRect.argtypes = [
        ctypes.wintypes.HWND,
        ctypes.c_void_p,
        ctypes.wintypes.BOOL,
    ]
    user32.InvalidateRect(int(hwnd), 0, True)
    user32.UpdateWindow.argtypes = [ctypes.wintypes.HWND]
    user32.UpdateWindow(int(hwnd))


def _set_window_pos_refresh(hwnd) -> None:
    """通过 SetWindowPos 发送 SWP_FRAMECHANGED | SWP_NOCOPYBITS 等标志刷新窗口。"""
    user32 = ctypes.windll.user32
    user32.SetWindowPos.argtypes = [
        ctypes.wintypes.HWND,
        ctypes.wintypes.HWND,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.wintypes.UINT,
    ]
    flags = SWP_NOMOVE | SWP_NOSIZE | SWP_NOZORDER | SWP_NOACTIVATE | SWP_FRAMECHANGED | SWP_NOCOPYBITS
    user32.SetWindowPos(int(hwnd), 0, 0, 0, 0, 0, flags)


def _force_repaint_all(hwnd) -> None:
    """依次调用 RedrawWindow、InvalidateRect+UpdateWindow、SetWindowPos 强制全部刷新。"""
    _redraw_window(hwnd, RDW_INVALIDATE | RDW_UPDATENOW)
    _invalidate_update(hwnd)
    _set_window_pos_refresh(hwnd)


def _save_dc_to_bmp(hdc, width, height, path: str) -> bool:
    """用 ctypes 调用 GDI API 从 HDC 当前位图创建 DIB，写入 24 位 BMP 文件。

    不依赖 Pillow，全部使用 ctypes/windll；文件头为标准
    BITMAPFILEHEADER + BITMAPINFOHEADER。
    """
    try:
        gdi32 = ctypes.windll.gdi32

        OBJ_BITMAP = 7
        DIB_RGB_COLORS = 0

        class BITMAPFILEHEADER(ctypes.Structure):
            _pack_ = 2
            _fields_ = [
                ("bfType", ctypes.c_uint16),
                ("bfSize", ctypes.c_uint32),
                ("bfReserved1", ctypes.c_uint16),
                ("bfReserved2", ctypes.c_uint16),
                ("bfOffBits", ctypes.c_uint32),
            ]

        class BITMAPINFOHEADER(ctypes.Structure):
            _fields_ = [
                ("biSize", ctypes.c_uint32),
                ("biWidth", ctypes.c_long),
                ("biHeight", ctypes.c_long),
                ("biPlanes", ctypes.c_uint16),
                ("biBitCount", ctypes.c_uint16),
                ("biCompression", ctypes.c_uint32),
                ("biSizeImage", ctypes.c_uint32),
                ("biXPelsPerMeter", ctypes.c_long),
                ("biYPelsPerMeter", ctypes.c_long),
                ("biClrUsed", ctypes.c_uint32),
                ("biClrImportant", ctypes.c_uint32),
            ]

        gdi32.GetCurrentObject.argtypes = [
            ctypes.wintypes.HDC,
            ctypes.wintypes.UINT,
        ]
        gdi32.GetCurrentObject.restype = ctypes.wintypes.HGDIOBJ

        gdi32.GetDIBits.argtypes = [
            ctypes.wintypes.HDC,
            ctypes.wintypes.HBITMAP,
            ctypes.wintypes.UINT,
            ctypes.wintypes.UINT,
            ctypes.c_void_p,
            ctypes.c_void_p,
            ctypes.wintypes.UINT,
        ]
        gdi32.GetDIBits.restype = ctypes.c_int

        hbitmap = gdi32.GetCurrentObject(hdc, OBJ_BITMAP)
        if not hbitmap:
            logger.warning("_save_dc_to_bmp: GetCurrentObject 失败")
            return False

        # 24 位 BMP 每行按 4 字节对齐
        row_bytes = (width * 3 + 3) & ~3
        image_size = row_bytes * height

        bih = BITMAPINFOHEADER()
        bih.biSize = ctypes.sizeof(BITMAPINFOHEADER)
        bih.biWidth = width
        bih.biHeight = height
        bih.biPlanes = 1
        bih.biBitCount = 24
        bih.biCompression = 0  # BI_RGB
        bih.biSizeImage = image_size

        bits = (ctypes.c_ubyte * image_size)()
        ret = gdi32.GetDIBits(
            hdc,
            hbitmap,
            0,
            height,
            ctypes.byref(bits),
            ctypes.byref(bih),
            DIB_RGB_COLORS,
        )
        if ret != height:
            logger.warning(f"_save_dc_to_bmp: GetDIBits 返回 {ret}, 期望 {height}")
            return False

        bfh = BITMAPFILEHEADER()
        bfh.bfType = 0x4D42  # 'BM'
        bfh.bfSize = ctypes.sizeof(BITMAPFILEHEADER) + ctypes.sizeof(BITMAPINFOHEADER) + image_size
        bfh.bfOffBits = ctypes.sizeof(BITMAPFILEHEADER) + ctypes.sizeof(BITMAPINFOHEADER)

        Path(path).parent.mkdir(parents=True, exist_ok=True)
        with open(path, "wb") as f:
            f.write(ctypes.string_at(ctypes.addressof(bfh), ctypes.sizeof(bfh)))
            f.write(ctypes.string_at(ctypes.addressof(bih), ctypes.sizeof(bih)))
            f.write(ctypes.string_at(ctypes.addressof(bits), image_size))
        return True
    except Exception as e:
        logger.warning(f"_save_dc_to_bmp 失败: {e}")
        return False


def _ocr_texts(inf, img_path: str) -> list[str]:
    """对图片做 OCR，返回非空文本列表。"""
    lines = inf.ocr_lines_from_file(img_path)
    return [ln.get("text", "").strip() for ln in lines if ln.get("text", "").strip()]


def _print_window_capture(hwnd, w, h, path: str, flags: int = PW_CLIENT_FULL) -> bool:
    """使用 PrintWindow 强制目标窗口把客户区渲染到指定 DC，并保存为 BMP。

    :param flags: PrintWindow 标志。默认 PW_CLIENT_FULL = PW_CLIENTONLY|PW_RENDERFULLCONTENT，
                  强制窗口渲染当前完整内容（含未 flush 的 backing store）。
                  传 PW_CLIENTONLY 可回退到旧行为做对照。
    """
    try:
        user32 = ctypes.windll.user32
        gdi32 = ctypes.windll.gdi32

        user32.GetDC.argtypes = [ctypes.wintypes.HWND]
        user32.GetDC.restype = ctypes.wintypes.HDC
        user32.ReleaseDC.argtypes = [
            ctypes.wintypes.HWND,
            ctypes.wintypes.HDC,
        ]
        user32.ReleaseDC.restype = ctypes.wintypes.BOOL

        gdi32.CreateCompatibleDC.argtypes = [ctypes.wintypes.HDC]
        gdi32.CreateCompatibleDC.restype = ctypes.wintypes.HDC
        gdi32.DeleteDC.argtypes = [ctypes.wintypes.HDC]
        gdi32.DeleteDC.restype = ctypes.wintypes.BOOL

        gdi32.CreateCompatibleBitmap.argtypes = [
            ctypes.wintypes.HDC,
            ctypes.c_int,
            ctypes.c_int,
        ]
        gdi32.CreateCompatibleBitmap.restype = ctypes.wintypes.HBITMAP
        gdi32.SelectObject.argtypes = [
            ctypes.wintypes.HDC,
            ctypes.wintypes.HGDIOBJ,
        ]
        gdi32.SelectObject.restype = ctypes.wintypes.HGDIOBJ
        gdi32.DeleteObject.argtypes = [ctypes.wintypes.HGDIOBJ]
        gdi32.DeleteObject.restype = ctypes.wintypes.BOOL

        user32.PrintWindow.argtypes = [
            ctypes.wintypes.HWND,
            ctypes.wintypes.HDC,
            ctypes.wintypes.UINT,
        ]
        user32.PrintWindow.restype = ctypes.wintypes.BOOL

        window_dc = user32.GetDC(int(hwnd))
        if not window_dc:
            logger.warning("_print_window_capture: GetDC 失败")
            return False

        mem_dc = gdi32.CreateCompatibleDC(window_dc)
        if not mem_dc:
            user32.ReleaseDC(int(hwnd), window_dc)
            return False

        hbitmap = gdi32.CreateCompatibleBitmap(window_dc, w, h)
        if not hbitmap:
            gdi32.DeleteDC(mem_dc)
            user32.ReleaseDC(int(hwnd), window_dc)
            return False

        old_obj = gdi32.SelectObject(mem_dc, hbitmap)
        if not old_obj:
            gdi32.DeleteObject(hbitmap)
            gdi32.DeleteDC(mem_dc)
            user32.ReleaseDC(int(hwnd), window_dc)
            logger.warning("_print_window_capture: SelectObject 失败")
            return False

        ok = user32.PrintWindow(int(hwnd), mem_dc, flags)
        if not ok:
            gdi32.SelectObject(mem_dc, old_obj)
            gdi32.DeleteObject(hbitmap)
            gdi32.DeleteDC(mem_dc)
            user32.ReleaseDC(int(hwnd), window_dc)
            logger.warning("_print_window_capture: PrintWindow 失败")
            return False

        save_ok = _save_dc_to_bmp(mem_dc, w, h, path)

        gdi32.SelectObject(mem_dc, old_obj)
        gdi32.DeleteObject(hbitmap)
        gdi32.DeleteDC(mem_dc)
        user32.ReleaseDC(int(hwnd), window_dc)
        return save_ok
    except Exception as e:
        logger.warning(f"_print_window_capture 失败: {e}")
        return False


def _is_blank_or_solid_by_color(dm, w: int, h: int) -> tuple[bool, bool, bool]:
    """用大漠 get_color 对客户区采样，判断是否纯色/黑屏。

    在客户区内均匀取 5x5 采样点（边缘留白），调用 dm.get_color 获取颜色。
    :return: (blank, solid, black)
    """
    if w <= 0 or h <= 0:
        return True, True, True

    # 5x5 均匀网格，边缘各留 1/6 边距，避免边框干扰；采样点更密，降低漏掉文字的概率
    xs = [int(w * i / 6) for i in (1, 2, 3, 4, 5)]
    ys = [int(h * i / 6) for i in (1, 2, 3, 4, 5)]
    colors: list[str] = []
    for x in xs:
        for y in ys:
            try:
                color = dm.get_color(x, y)
                colors.append((color or "").lower().strip("#"))
            except Exception as e:
                logger.warning(f"get_color 失败: ({x},{y}), 错误: {e}")
                colors.append("")

    if not colors or all(c == "" for c in colors):
        return True, True, True

    valid_colors = [c for c in colors if c]
    if not valid_colors:
        return True, True, True

    first = valid_colors[0]
    blank = all(c == first for c in valid_colors)
    black = blank and first == "000000"
    solid = blank
    return blank, solid, black


def _try_set_client_size(dm, hwnd: int, size: tuple[int, int], label: str) -> None:
    """尝试将窗口客户区设置为指定尺寸，失败仅记录警告。"""
    if size[0] <= 0 or size[1] <= 0:
        return
    try:
        dm.set_client_size(hwnd, *size)
        logger.info(f"[{label}] 已设置客户区尺寸: {size}")
        time.sleep(0.3)
    except Exception as e:
        logger.warning(f"[{label}] set_client_size 失败: {e}")


def _get_client_size(dm, hwnd: int, label: str) -> tuple[int, int]:
    """获取窗口当前客户区尺寸，失败返回 (0, 0)。"""
    try:
        x1, y1, x2, y2 = dm.get_client_rect(hwnd)
        return x2 - x1, y2 - y1
    except Exception as e:
        logger.error(f"[{label}] 获取客户区尺寸失败: {e}")
        return 0, 0


def _capture_single(dm, hwnd: int, bind_cfg: dict, label: str, inf, keyword: str = "") -> dict:
    """单次绑定窗口、全客户区截图、采样颜色校验、大漠 OCR 识别，返回结果字典。"""
    img_path = (OUT_DIR / f"{label}.bmp").resolve()
    result = {
        "display": bind_cfg.get("display", "normal"),
        "mouse": bind_cfg.get("mouse", "normal"),
        "keypad": bind_cfg.get("keypad", "normal"),
        "mode": int(bind_cfg.get("mode", 0)),
        "success": False,
        "screenshot": "",
        "solid": False,
        "black": False,
        "ocr_texts": [],
        "keyword": keyword,
        "keyword_matched": False,
        "error": "",
    }

    try_cfg = dict(bind_cfg)
    try_cfg.setdefault("bind_delay", 1.0)

    try:
        with dm.bind_window(hwnd, bind_cfg=try_cfg):
            x1, y1, x2, y2 = dm.get_client_rect(hwnd)
            w, h = x2 - x1, y2 - y1
            logger.info(f"[{label}] 绑定成功，客户区=({x1},{y1},{x2},{y2}), 截图区域=(0,0,{w},{h})")
            ok = dm.capture_region(0, 0, w, h, str(img_path))
            if not ok:
                result["error"] = "capture_region 失败"
                return result

            result["success"] = True
            result["screenshot"] = str(img_path)
            blank, solid, black = _is_blank_or_solid_by_color(dm, w, h)
            result["solid"] = solid
            result["black"] = black

            # 使用 RapidOCR 识别截图文件（大漠只负责截图，OCR 走 RapidOCR）
            try:
                lines = inf.ocr_lines_from_file(str(img_path))
                texts = [ln.get("text", "").strip() for ln in lines if ln.get("text", "").strip()]
                result["ocr_texts"] = texts
                all_text = "".join(texts)
                if keyword:
                    result["keyword_matched"] = keyword in all_text
                logger.info(f"[{label}] OCR 结果: {texts}")

                # OCR 识别到文字，说明截图不是纯色/黑屏
                if texts:
                    if result["solid"] or result["black"]:
                        logger.info(f"[{label}] OCR 识别到文字，推翻纯色/黑屏判断")
                        result["solid"] = False
                        result["black"] = False
            except Exception as e:
                result["error"] = f"OCR 失败: {e}"
                logger.warning(f"[{label}] OCR 失败: {e}")

            if result["solid"]:
                result["error"] = "截图纯色/黑屏" if result["black"] else "截图纯色"
                logger.warning(f"[{label}] {result['error']}")
    except Exception as e:
        result["error"] = f"{type(e).__name__}: {e}"
        logger.warning(f"[{label}] 绑定/截图失败: {e}")

    return result


def capture_and_ocr(dm, hwnd: int, bind_cfg: dict, label: str, inf, keyword: str = "") -> list[dict]:
    """对指定窗口分别用多种 display 后台模式绑定截图 + OCR。

     用于单目标测试。默认测试 display 模式包含 DEFAULT_DISPLAYS 中所有后台模式
    （gdi2 / gdi / dx / dx2 / dx3 / dx.graphic.2d / dx.graphic.3d），优先测 gdi2。
     返回按 display 顺序的结果列表。
    """
    # 优先使用 bind_cfg 里的 display，再补齐 DEFAULT_DISPLAYS 中的后台 display 模式
    display_modes = [m for m in (bind_cfg.get("display", "gdi2"),) if m != "normal"]
    for mode in DEFAULT_DISPLAYS:
        if mode not in display_modes:
            display_modes.append(mode)

    results = []
    for display in display_modes:
        try_cfg = dict(bind_cfg)
        try_cfg["display"] = display
        try_cfg.setdefault("bind_delay", 1.0)
        result = _capture_single(dm, hwnd, try_cfg, f"{label}_{display}", inf, keyword=keyword)
        results.append(result)

    success_count = sum(1 for r in results if r["success"] and not r["solid"] and not r["black"])
    if success_count == 0:
        logger.error(f"[{label}] 所有 display 模式均失败或为纯色/黑屏")
    else:
        logger.info(f"[{label}] 共 {len(results)} 种 display 模式，有效 {success_count}")
    return results


def test_dropdown(dm, kk_cfg: dict, bind_cfg: dict, inf) -> None:
    """测试下拉框后台截图。

    脚本自动绑定主窗口 → 点击头像弹出下拉框 → diff 检测新增窗口 →
    设置下拉框尺寸 → 绑定下拉框截图 + OCR。
    前提：KK 大厅窗口已打开，停在主界面。
    """
    logger.info("\n" + "=" * 60)
    logger.info("测试下拉框（Qt Popup 窗口）后台截图")
    logger.info("=" * 60)

    main_cfg = kk_cfg.get("main", {})
    main_size = tuple(main_cfg.get("window_size", [1332, 945]))
    profile_icon = main_cfg.get("profile_icon_coords", [0, 0])
    dropdown_wait = main_cfg.get("dropdown_wait_time", 1)
    # 下拉框类名从 [kk] 配置读取，而非 [kk.main]
    dropdown_class = kk_cfg.get("dropdown_window_class", "")
    dropdown_cfg = kk_cfg.get("dropdown", {})
    dropdown_size = tuple(dropdown_cfg.get("window_size", [0, 0]))

    hall_hwnd = find_hall_window(dm, kk_cfg)
    if not hall_hwnd:
        logger.error("  未找到 KK 大厅窗口")
        return
    logger.info(f"  大厅窗口: hwnd={hall_hwnd}")

    pid = dm.get_window_process_id(hall_hwnd)
    before = enum_visible_windows_by_pid(pid)

    # 绑定主窗口，点击头像弹出下拉框
    _try_set_client_size(dm, hall_hwnd, main_size, "dropdown_hall")
    with dm.bind_window(hall_hwnd, bind_cfg=bind_cfg):
        dm.move_to(*profile_icon)
        time.sleep(0.3)
        dm.left_click()
        logger.info(f"  已点击头像图标 {profile_icon}，等待 {dropdown_wait}s...")
        time.sleep(dropdown_wait)

    # 枚举新增窗口，筛选下拉框
    after = enum_visible_windows_by_pid(pid)
    before_hwnds = {w["hwnd"] for w in before}
    new_wins = [w for w in after if w["hwnd"] not in before_hwnds]
    dropdown_wins = [w for w in new_wins if dropdown_class and dropdown_class.lower() in w["class"].lower()]
    target_wins = dropdown_wins or new_wins

    if not target_wins:
        logger.error("  未检测到下拉框窗口")
        return

    for i, win in enumerate(target_wins):
        dd_hwnd = win["hwnd"]
        if not dm.is_window_visible(dd_hwnd):
            logger.warning(f"  下拉框窗口 {dd_hwnd} 已不可见，可能已关闭")
            continue

        # 若 [kk.dropdown].window_size 非 [0,0]，则统一尺寸
        if dropdown_size[0] > 0 and dropdown_size[1] > 0:
            _try_set_client_size(dm, dd_hwnd, dropdown_size, f"dropdown_{dd_hwnd}")
        else:
            logger.info(f"  下拉框 {dd_hwnd} 使用检测到的自然尺寸")

        dd_w, dd_h = _get_client_size(dm, dd_hwnd, f"dropdown_{dd_hwnd}")
        if dd_w <= 0 or dd_h <= 0:
            logger.error(f"  下拉框 {dd_hwnd} 客户区尺寸无效，跳过")
            continue
        logger.info(f"  下拉框窗口 {i}: hwnd={dd_hwnd}, 客户区尺寸=({dd_w}x{dd_h})")

        capture_and_ocr(
            dm,
            dd_hwnd,
            bind_cfg,
            label=f"dropdown_{dd_hwnd}",
            inf=inf,
        )

    # 关闭下拉框
    with dm.bind_window(hall_hwnd, bind_cfg=bind_cfg):
        dm.key_press_char("esc")
    time.sleep(0.3)


def test_create_room(dm, kk_cfg: dict, bind_cfg: dict, inf) -> None:
    """测试创建房间弹窗后台截图。

    前提：用户已手动打开创建房间弹窗（点击创建房间按钮后出现的弹窗）。
    """
    logger.info("\n" + "=" * 60)
    logger.info("测试创建房间弹窗（Qt5152QWindow）后台截图")
    logger.info("=" * 60)

    create_cfg = kk_cfg.get("create_room", {})
    dialog_size = tuple(create_cfg.get("dialog_window_size", [584, 488]))
    dialog_keyword = create_cfg.get("dialog_keyword", "创建房间")
    popup_class = kk_cfg.get("create_room_window_class", "")
    window_title = kk_cfg.get("window_title", "")

    dialog_hwnd = find_window_by_class(dm, popup_class, window_title, expected_size=dialog_size)
    if not dialog_hwnd:
        logger.error(f"  未找到创建房间弹窗（class={popup_class}, 尺寸={dialog_size}）")
        logger.error("  请先手动点击创建房间按钮打开弹窗")
        return

    # 在绑定前统一为客户区基准尺寸
    _try_set_client_size(dm, dialog_hwnd, dialog_size, "create_room")
    w, h = _get_client_size(dm, dialog_hwnd, "create_room")
    logger.info(f"  创建房间弹窗: hwnd={dialog_hwnd}, 客户区尺寸=({w}x{h})")

    capture_and_ocr(
        dm,
        dialog_hwnd,
        bind_cfg,
        label=f"create_room_{dialog_hwnd}",
        inf=inf,
        keyword=dialog_keyword,
    )


def test_password(dm, kk_cfg: dict, bind_cfg: dict, inf) -> None:
    """测试加入房间的密码输入弹窗后台截图。

    前提：用户已手动打开密码输入弹窗（搜索房间后点击搜索结果弹出的密码框）。
    """
    logger.info("\n" + "=" * 60)
    logger.info("测试密码输入弹窗（Qt5152QWindow）后台截图")
    logger.info("=" * 60)

    password_cfg = kk_cfg.get("password_input", {})
    dialog_size = tuple(password_cfg.get("window_size", [440, 260]))
    password_keyword = password_cfg.get("dialog_keyword", "输入房间密码")
    popup_class = kk_cfg.get("create_room_window_class", "")
    window_title = kk_cfg.get("window_title", "")

    pwd_hwnd = find_window_by_class(dm, popup_class, window_title, expected_size=dialog_size)
    if not pwd_hwnd:
        logger.error(f"  未找到密码输入弹窗（class={popup_class}, 尺寸={dialog_size}）")
        logger.error("  请先手动搜索房间并点击搜索结果打开密码弹窗")
        return

    _try_set_client_size(dm, pwd_hwnd, dialog_size, "password")
    w, h = _get_client_size(dm, pwd_hwnd, "password")
    logger.info(f"  密码弹窗: hwnd={pwd_hwnd}, 客户区尺寸=({w}x{h})")

    capture_and_ocr(
        dm,
        pwd_hwnd,
        bind_cfg,
        label=f"password_{pwd_hwnd}",
        inf=inf,
        keyword=password_keyword,
    )


def test_hall(dm, kk_cfg: dict, bind_cfg: dict, inf) -> None:
    """测试 KK 主界面窗口后台截图。

    前提：KK 大厅窗口已打开，停在主界面。
    """
    logger.info("\n" + "=" * 60)
    logger.info("测试主界面窗口（Qt5152QWindowIcon）后台截图")
    logger.info("=" * 60)

    main_cfg = kk_cfg.get("main", {})
    main_size = tuple(main_cfg.get("window_size", [1332, 945]))

    hall_hwnd = find_hall_window(dm, kk_cfg)
    if not hall_hwnd:
        logger.error("  未找到 KK 大厅窗口")
        return

    _try_set_client_size(dm, hall_hwnd, main_size, "hall")
    w, h = _get_client_size(dm, hall_hwnd, "hall")
    logger.info(f"  主界面窗口: hwnd={hall_hwnd}, 客户区尺寸=({w}x{h})")

    capture_and_ocr(
        dm,
        hall_hwnd,
        bind_cfg,
        label=f"hall_{hall_hwnd}",
        inf=inf,
    )


def test_room(dm, kk_cfg: dict, bind_cfg: dict, inf) -> None:
    """测试 KK 房间窗口后台截图。

    前提：用户已手动进入一个房间（房间窗口已打开）。
    """
    logger.info("\n" + "=" * 60)
    logger.info("测试房间窗口（Qt5152QWindowIcon）后台截图")
    logger.info("=" * 60)

    room_cfg = kk_cfg.get("room", {})
    room_size = tuple(room_cfg.get("window_size", [1224, 904]))
    room_keyword = room_cfg.get("keyword", "房间号")
    window_class = kk_cfg.get("window_class", "")
    min_w, min_h = kk_cfg.get("min_business_window_size", [200, 200])

    # 房间窗口与主界面同类名同标题，用 ex_style 区分：
    # 房间窗口 ex_style=0x80000 (WS_EX_APPWINDOW)，主界面 ex_style=0x0
    WS_EX_APPWINDOW = 0x80000
    user32 = ctypes.windll.user32
    GetWindowLongPtrW = user32.GetWindowLongPtrW

    hall_hwnd = find_hall_window(dm, kk_cfg)
    pid = dm.get_window_process_id(hall_hwnd) if hall_hwnd else 0

    room_hwnd = 0
    if pid:
        for win in enum_visible_windows_by_pid(pid):
            if win["class"] != window_class:
                continue
            ww = win["rect"][2] - win["rect"][0]
            wh = win["rect"][3] - win["rect"][1]
            if ww < min_w or wh < min_h:
                continue
            ex_style = GetWindowLongPtrW(win["hwnd"], -20)  # GWL_EXSTYLE
            if ex_style & WS_EX_APPWINDOW:
                room_hwnd = win["hwnd"]
                logger.info(f"  房间窗口: hwnd={room_hwnd}, 尺寸=({ww}x{wh}), ex_style={hex(ex_style)}")
                break

    if not room_hwnd:
        logger.error("  未找到房间窗口，请先手动进入一个房间")
        return

    _try_set_client_size(dm, room_hwnd, room_size, "room")
    w, h = _get_client_size(dm, room_hwnd, "room")
    logger.info(f"  统一尺寸后: 客户区尺寸=({w}x{h})")

    capture_and_ocr(
        dm,
        room_hwnd,
        bind_cfg,
        label=f"room_{room_hwnd}",
        inf=inf,
        keyword=room_keyword,
    )


def _redraw_while_bound(dm, hwnd, bind_cfg, w, h, label) -> str:
    """绑定态内执行 RedrawWindow(RDW_INVALIDATE|RDW_UPDATENOW|RDW_ALLCHILDREN)
    后等待并截图，验证 gdi2/dx2 hook 能否捕获 Qt 的强制 flush。

    与其它刷新方式的区别：RedrawWindow 在 bind_window 上下文内调用，
    这样 Qt flush 的 BitBlt 才会经过大漠 hook 写入 shadow buffer。
    返回 BMP 路径，失败返回空串。
    """
    after_path = (OUT_DIR / f"{label}_redraw_while_bound_after.bmp").resolve()
    try:
        with dm.bind_window(hwnd, bind_cfg=bind_cfg):
            _redraw_window(hwnd, RDW_INVALIDATE | RDW_UPDATENOW | RDW_ALLCHILDREN)
            # 给 Qt 处理 WM_PAINT + flush + 大漠 hook 拷贝留时间
            time.sleep(0.4)
            ok = dm.capture_region(0, 0, w, h, str(after_path))
            if not ok:
                logger.error(f"[{label}] redraw_while_bound capture_region 失败")
                return ""
    except Exception as e:
        logger.error(f"[{label}] redraw_while_bound 绑定/刷新/截图失败: {e}")
        return ""
    return str(after_path)


def _render_test_common(
    dm,
    hwnd: int,
    bind_cfg: dict,
    inf,
    size: tuple[int, int],
    action_fn,
) -> None:
    """后台绑定下先截图得到 OCR 基准，再执行操作，最后测试多种 Windows API 刷新效果。

    :param action_fn: 真实操作函数 fn(dm, hwnd)，内部自行绑定/解绑
    """
    label = getattr(action_fn, "__name__", "render")
    _try_set_client_size(dm, hwnd, size, label)
    w, h = _get_client_size(dm, hwnd, label)
    if w <= 0 or h <= 0:
        logger.error(f"[{label}] 客户区尺寸无效，跳过渲染刷新测试")
        return

    before_texts: list[str] = []
    before_path = (OUT_DIR / f"{label}_before.bmp").resolve()
    try:
        with dm.bind_window(hwnd, bind_cfg=bind_cfg):
            ok = dm.capture_region(0, 0, w, h, str(before_path))
            if not ok:
                logger.error(f"[{label}] 操作前截图失败")
                return
            lines = inf.ocr_lines_from_file(str(before_path))
            before_texts = [ln.get("text", "").strip() for ln in lines if ln.get("text", "").strip()]
            logger.info(f"[{label}] 操作前 OCR: {before_texts}")
    except Exception as e:
        logger.error(f"[{label}] 操作前绑定/截图/OCR 失败: {e}")
        return

    # 解绑后由 action_fn 自行完成真实操作（绑定/解绑在内部处理）
    try:
        action_fn(dm, hwnd)
    except Exception as e:
        logger.error(f"[{label}] action_fn 执行失败: {e}")
        return

    def make_captures(method_name: str):
        """生成 PrintWindow 系列刷新函数，返回一个接受 hwnd 的 fn。"""

        if method_name == "print_window":
            # 默认用 PW_CLIENT_FULL（PW_CLIENTONLY|PW_RENDERFULLCONTENT），
            # 主动逼窗口渲染当前完整内容（含未 flush 的 backing store）。
            def _print_window_only(hwnd_):
                path = (OUT_DIR / f"{label}_{method_name}.bmp").resolve()
                if _print_window_capture(hwnd_, w, h, str(path), PW_CLIENT_FULL):
                    return str(path)
                return ""

            return _print_window_only

        if method_name == "print_window_clientonly":
            # 对照组：仅 PW_CLIENTONLY，不强制渲染未 flush 内容（旧行为）。
            def _print_window_clientonly(hwnd_):
                path = (OUT_DIR / f"{label}_{method_name}.bmp").resolve()
                if _print_window_capture(hwnd_, w, h, str(path), PW_CLIENTONLY):
                    return str(path)
                return ""

            return _print_window_clientonly

        if method_name == "print_window_after_bind":

            def _print_window_then_bind(hwnd_):
                print_path = (OUT_DIR / f"{label}_{method_name}_print.bmp").resolve()
                if not _print_window_capture(hwnd_, w, h, str(print_path), PW_CLIENT_FULL):
                    return ""
                after_path = (OUT_DIR / f"{label}_{method_name}_after.bmp").resolve()
                try:
                    with dm.bind_window(hwnd_, bind_cfg=bind_cfg):
                        ok = dm.capture_region(0, 0, w, h, str(after_path))
                        if not ok:
                            logger.error(f"[{label}] {method_name} capture_region 失败")
                            return ""
                except Exception as e:
                    logger.error(f"[{label}] {method_name} 绑定/截图失败: {e}")
                    return ""
                return str(after_path)

            return _print_window_then_bind

        return lambda _: None

    refresh_methods = [
        ("no_refresh", lambda h: None),
        (
            "redraw_window",
            lambda h: _redraw_window(h, RDW_INVALIDATE | RDW_UPDATENOW),
        ),
        (
            "redraw_window_allchildren",
            lambda h: _redraw_window(h, RDW_INVALIDATE | RDW_UPDATENOW | RDW_ALLCHILDREN),
        ),
        ("invalidate_update", _invalidate_update),
        ("set_window_pos", _set_window_pos_refresh),
        ("force_repaint_all", _force_repaint_all),
        ("print_window", make_captures("print_window")),
        ("print_window_clientonly", make_captures("print_window_clientonly")),
        (
            "print_window_after_bind",
            make_captures("print_window_after_bind"),
        ),
        # 关键对照：绑定态内强制刷新 + 截图（验证"RedrawWindow 必须在绑定态执行
        # 才能让 gdi2 hook 捕获 Qt flush"的假设）。返回 BMP 路径。
        (
            "redraw_while_bound",
            lambda h: _redraw_while_bound(dm, h, bind_cfg, w, h, label),
        ),
    ]

    logger.info(f"[{label}] 开始依次验证 {len(refresh_methods)} 种刷新方式")
    for method_name, refresh_fn in refresh_methods:
        try:
            result = refresh_fn(hwnd)
        except Exception as e:
            logger.warning(f"[{label}] {method_name} 调用失败: {e}")
            continue

        # 刷新函数返回路径时直接 OCR；否则走原有绑定 + capture_region 流程
        if isinstance(result, (str, Path)):
            if not result:
                logger.error(f"[{label}] {method_name} 未生成有效图片")
                continue
            after_path = Path(result)
            after_texts: list[str] = []
            try:
                lines = inf.ocr_lines_from_file(str(after_path))
                after_texts = [ln.get("text", "").strip() for ln in lines if ln.get("text", "").strip()]
            except Exception as e:
                logger.error(f"[{label}] {method_name} 直接 OCR 失败: {e}")
                continue
        else:
            after_path = (OUT_DIR / f"{label}_{method_name}_after.bmp").resolve()
            after_texts: list[str] = []
            try:
                with dm.bind_window(hwnd, bind_cfg=bind_cfg):
                    ok = dm.capture_region(0, 0, w, h, str(after_path))
                    if not ok:
                        logger.error(f"[{label}] {method_name} 截图失败")
                        continue
                    lines = inf.ocr_lines_from_file(str(after_path))
                    after_texts = [ln.get("text", "").strip() for ln in lines if ln.get("text", "").strip()]
            except Exception as e:
                logger.error(f"[{label}] {method_name} 刷新后绑定/截图/OCR 失败: {e}")
                continue

        is_refreshed = after_texts != before_texts
        logger.info(
            f"[{label}] 方式={method_name}, before={before_texts}, after={after_texts}, 是否刷新={is_refreshed}"
        )


def test_render_password(dm, kk_cfg: dict, bind_cfg: dict, inf) -> None:
    """测试后台绑定下密码弹窗输入后，Windows API 强制刷新能否让截图/OCR 更新。"""
    logger.info("\n" + "=" * 60)
    logger.info("测试密码弹窗后台操作后的 Windows API 强制刷新效果")
    logger.info("=" * 60)

    password_cfg = kk_cfg.get("password_input", {})
    dialog_size = (440, 260)
    popup_class = kk_cfg.get("create_room_window_class", "")
    window_title = kk_cfg.get("window_title", "")
    password_input_coords = password_cfg.get("password_input_coords", [0, 0])

    pwd_hwnd = find_window_by_class(dm, popup_class, window_title, expected_size=dialog_size)
    if not pwd_hwnd:
        logger.error(f"  未找到密码输入弹窗（class={popup_class}, 尺寸={dialog_size}）")
        logger.error("  请先手动搜索房间并点击搜索结果打开密码弹窗")
        return

    def _action_password(dm_action, hwnd: int) -> None:
        if password_input_coords == [0, 0]:
            logger.warning("  未配置 password_input.password_input_coords")
            return
        with dm_action.bind_window(hwnd, bind_cfg=bind_cfg):
            x1, y1, x2, y2 = dm_action.get_client_rect(hwnd)
            aw, ah = x2 - x1, y2 - y1
            base_w, base_h = dialog_size
            if base_w > 0 and base_h > 0:
                click_x = round(password_input_coords[0] * aw / base_w)
                click_y = round(password_input_coords[1] * ah / base_h)
            else:
                click_x, click_y = password_input_coords
            dm_action.move_to(click_x, click_y)
            time.sleep(0.3)
            dm_action.left_click()
            time.sleep(0.3)
            dm_action.send_string("1234", hwnd=hwnd)
            time.sleep(0.5)

    _render_test_common(dm, pwd_hwnd, bind_cfg, inf, dialog_size, _action_password)


def test_render_password_minimal(dm, kk_cfg: dict, bind_cfg: dict, inf) -> None:
    """最小化密码弹窗测试：只输入 1234，不点确定，只截图一次。"""
    logger.info("\n" + "=" * 60)
    logger.info("最小化测试：密码弹窗输入 1234 后仅截图一次")
    logger.info("=" * 60)

    password_cfg = kk_cfg.get("password_input", {})
    dialog_size = (440, 260)
    popup_class = kk_cfg.get("create_room_window_class", "")
    window_title = kk_cfg.get("window_title", "")
    password_input_coords = password_cfg.get("password_input_coords", [0, 0])

    pwd_hwnd = find_window_by_class(dm, popup_class, window_title, expected_size=dialog_size)
    if not pwd_hwnd:
        logger.error("未找到密码弹窗")
        return

    _try_set_client_size(dm, pwd_hwnd, dialog_size, "minimal_password")
    w, h = _get_client_size(dm, pwd_hwnd, "minimal_password")
    if w <= 0 or h <= 0:
        logger.error("密码弹窗尺寸无效")
        return

    img_path = (OUT_DIR / "minimal_password_after.bmp").resolve()
    with dm.bind_window(pwd_hwnd, bind_cfg=bind_cfg):
        if password_input_coords != [0, 0]:
            click_x = round(password_input_coords[0] * w / 440)
            click_y = round(password_input_coords[1] * h / 260)
            dm.move_to(click_x, click_y)
            time.sleep(0.3)
            dm.left_click()
            time.sleep(0.3)
        dm.send_string("1234", hwnd=pwd_hwnd)
        time.sleep(1.0)
        dm.capture_region(0, 0, w, h, str(img_path))

    lines = inf.ocr_lines_from_file(str(img_path))
    texts = [ln.get("text", "").strip() for ln in lines if ln.get("text", "").strip()]
    logger.info(f"[大漠 Capture] 输入 1234 后 OCR: {texts}")
    logger.info(f"[大漠 Capture] 截图保存: {img_path}")

    # 对照：PrintWindow + PW_RENDERFULLCONTENT（不依赖大漠 hook / shadow buffer，
    # 主动逼窗口渲染当前完整内容）。解绑态下直接抓。
    pw_full_path = (OUT_DIR / "minimal_password_pw_full.bmp").resolve()
    if _print_window_capture(pwd_hwnd, w, h, str(pw_full_path), PW_CLIENT_FULL):
        pw_lines = inf.ocr_lines_from_file(str(pw_full_path))
        pw_texts = [ln.get("text", "").strip() for ln in pw_lines if ln.get("text", "").strip()]
        logger.info(f"[PrintWindow PW_RENDERFULLCONTENT] OCR: {pw_texts}")
        logger.info(f"[PrintWindow PW_RENDERFULLCONTENT] 截图保存: {pw_full_path}")
    else:
        logger.warning("[PrintWindow PW_RENDERFULLCONTENT] 截图失败")

    # 对照：PrintWindow 仅 PW_CLIENTONLY（旧行为）
    pw_co_path = (OUT_DIR / "minimal_password_pw_clientonly.bmp").resolve()
    if _print_window_capture(pwd_hwnd, w, h, str(pw_co_path), PW_CLIENTONLY):
        pwco_lines = inf.ocr_lines_from_file(str(pw_co_path))
        pwco_texts = [ln.get("text", "").strip() for ln in pwco_lines if ln.get("text", "").strip()]
        logger.info(f"[PrintWindow PW_CLIENTONLY] OCR: {pwco_texts}")
        logger.info(f"[PrintWindow PW_CLIENTONLY] 截图保存: {pw_co_path}")


def test_render_create_room_password(dm, kk_cfg: dict, bind_cfg: dict, inf) -> None:
    """在创建房间弹窗的密码输入框里输入 1234，不点创建，只截图一次。"""
    logger.info("\n" + "=" * 60)
    logger.info("最小化测试：创建房间弹窗输入密码 1234 后仅截图一次")
    logger.info("=" * 60)

    create_cfg = kk_cfg.get("create_room", {})
    dialog_size = tuple(create_cfg.get("dialog_window_size", [584, 488]))
    popup_class = kk_cfg.get("create_room_window_class", "")
    window_title = kk_cfg.get("window_title", "")
    password_input_coords = create_cfg.get("password_input_coords", [0, 0])
    size_tolerance = create_cfg.get("size_tolerance", 40)

    dialog_hwnd = find_window_by_class(
        dm,
        popup_class,
        window_title,
        expected_size=dialog_size,
        size_tolerance=size_tolerance,
    )
    if not dialog_hwnd:
        logger.error("未找到创建房间弹窗")
        return

    _try_set_client_size(dm, dialog_hwnd, dialog_size, "create_room_password")
    w, h = _get_client_size(dm, dialog_hwnd, "create_room_password")
    if w <= 0 or h <= 0:
        logger.error("创建房间弹窗尺寸无效")
        return

    # ---- 第 1 步：后台输入 1234（只输入一次，去掉重复的 key_press_char）----
    with dm.bind_window(dialog_hwnd, bind_cfg=bind_cfg):
        if password_input_coords != [0, 0]:
            base_w, base_h = dialog_size
            click_x = round(password_input_coords[0] * w / base_w)
            click_y = round(password_input_coords[1] * h / base_h)
            dm.move_to(click_x, click_y)
            time.sleep(0.3)
            dm.left_click()
            time.sleep(0.3)
        dm.send_string("1234", hwnd=dialog_hwnd)
        time.sleep(1.0)

    # ---- 第 2 步：多路截图对照 ----

    # 2a. 大漠 Capture（现状，无强制刷新）—— 预期看不到 1234
    img_path = (OUT_DIR / "create_room_password_dm_capture.bmp").resolve()
    with dm.bind_window(dialog_hwnd, bind_cfg=bind_cfg):
        dm.capture_region(0, 0, w, h, str(img_path))
    texts = _ocr_texts(inf, str(img_path))
    logger.info(f"[2a 大漠 Capture 无刷新] OCR: {texts}")

    # 2b. PrintWindow+PW_RENDERFULLCONTENT（无强制刷新）—— 预期看不到 1234
    pw_path = (OUT_DIR / "create_room_password_pw_full.bmp").resolve()
    if _print_window_capture(dialog_hwnd, w, h, str(pw_path), PW_CLIENT_FULL):
        texts = _ocr_texts(inf, str(pw_path))
        logger.info(f"[2b PrintWindow PW_RENDERFULLCONTENT 无刷新] OCR: {texts}")

    # 2c. RedrawWindow（解绑态）→ 大漠 Capture —— 预期看不到（hook 没激活）
    _redraw_window(dialog_hwnd, RDW_INVALIDATE | RDW_UPDATENOW | RDW_ALLCHILDREN)
    time.sleep(0.4)
    img_path = (OUT_DIR / "create_room_password_dm_after_redraw_unbound.bmp").resolve()
    with dm.bind_window(dialog_hwnd, bind_cfg=bind_cfg):
        dm.capture_region(0, 0, w, h, str(img_path))
    texts = _ocr_texts(inf, str(img_path))
    logger.info(f"[2c 大漠 Capture 解绑态Redraw后] OCR: {texts}")

    # 2d. RedrawWindow（绑定态内）→ 大漠 Capture —— 关键：hook 激活时逼 Qt flush
    img_path = (OUT_DIR / "create_room_password_dm_redraw_bound.bmp").resolve()
    with dm.bind_window(dialog_hwnd, bind_cfg=bind_cfg):
        _redraw_window(dialog_hwnd, RDW_INVALIDATE | RDW_UPDATENOW | RDW_ALLCHILDREN)
        time.sleep(0.4)
        dm.capture_region(0, 0, w, h, str(img_path))
    texts = _ocr_texts(inf, str(img_path))
    logger.info(f"[2d 大漠 Capture 绑定态Redraw后] OCR: {texts}")

    # 2e. RedrawWindow（解绑态）→ PrintWindow+PW_RENDERFULLCONTENT
    #      —— 关键：Redraw 逼 Qt 更新 backing store，PrintWindow 渲染更新后的内容
    _redraw_window(dialog_hwnd, RDW_INVALIDATE | RDW_UPDATENOW | RDW_ALLCHILDREN)
    time.sleep(0.4)
    pw_path = (OUT_DIR / "create_room_password_pw_after_redraw.bmp").resolve()
    if _print_window_capture(dialog_hwnd, w, h, str(pw_path), PW_CLIENT_FULL):
        texts = _ocr_texts(inf, str(pw_path))
        logger.info(f"[2e PrintWindow PW_RENDERFULLCONTENT Redraw后] OCR: {texts}")

    # 2f. UpdateWindow（解绑态）→ PrintWindow+PW_RENDERFULLCONTENT —— 另一种逼 WM_PAINT 的方式
    _invalidate_update(dialog_hwnd)
    time.sleep(0.4)
    pw_path = (OUT_DIR / "create_room_password_pw_after_update.bmp").resolve()
    if _print_window_capture(dialog_hwnd, w, h, str(pw_path), PW_CLIENT_FULL):
        texts = _ocr_texts(inf, str(pw_path))
        logger.info(f"[2f PrintWindow PW_RENDERFULLCONTENT UpdateWindow后] OCR: {texts}")

    logger.info(f"截图保存目录: {OUT_DIR}")


def test_render_room(dm, kk_cfg: dict, bind_cfg: dict, inf) -> None:
    """测试后台绑定下房间窗口点击准备/取消准备后，Windows API 强制刷新能否让截图/OCR 更新。"""
    logger.info("\n" + "=" * 60)
    logger.info("测试房间窗口后台操作后的 Windows API 强制刷新效果")
    logger.info("=" * 60)

    room_cfg = kk_cfg.get("room", {})
    room_size = (1224, 904)
    window_class = kk_cfg.get("window_class", "")
    window_title = kk_cfg.get("window_title", "")
    size_tolerance = kk_cfg.get("size_tolerance", 30)
    start_button_ocr_area = room_cfg.get("start_button_ocr_area_coords", [0, 0, 0, 0])
    # 渲染测试只点击"准备/取消准备"按钮，避免误点房主的"开始游戏"
    button_keywords = ["准备", "取消准备"]
    exclude_keywords = ["开始游戏", "等待准备"]

    WS_EX_APPWINDOW = 0x80000
    user32 = ctypes.windll.user32
    GetWindowLongPtrW = user32.GetWindowLongPtrW
    GWL_EXSTYLE = -20

    player_room_hwnd = 0
    logger.info("  开始扫描可见的 KK 房间窗口...")

    for hwnd in dm.enum_windows(window_class, window_title or "", filter=1 + 2 + 8 + 16):
        if not dm.is_window_visible(hwnd):
            continue
        if dm.get_window_class(hwnd) != window_class:
            continue
        if window_title and dm.get_window_title(hwnd) != window_title:
            continue

        x1, y1, x2, y2 = dm.get_client_rect(hwnd)
        aw, ah = x2 - x1, y2 - y1
        if abs(aw - room_size[0]) > size_tolerance or abs(ah - room_size[1]) > size_tolerance:
            continue

        ex_style = GetWindowLongPtrW(hwnd, GWL_EXSTYLE)
        if not (ex_style & WS_EX_APPWINDOW):
            continue

        logger.info(f"  候选房间窗口: hwnd={hwnd}, 客户区=({aw}x{ah}), ex_style={hex(ex_style)}")

        _try_set_client_size(dm, hwnd, room_size, "render_room_scan")
        x1, y1, x2, y2 = dm.get_client_rect(hwnd)
        aw, ah = x2 - x1, y2 - y1
        if aw <= 0 or ah <= 0:
            continue

        if start_button_ocr_area == [0, 0, 0, 0]:
            logger.warning("  未配置 start_button_ocr_area_coords，跳过 OCR 识别")
            continue

        base_w, base_h = room_size
        ax1 = round(start_button_ocr_area[0] * aw / base_w)
        ay1 = round(start_button_ocr_area[1] * ah / base_h)
        ax2 = round(start_button_ocr_area[2] * aw / base_w)
        ay2 = round(start_button_ocr_area[3] * ah / base_h)
        ax1, ay1 = max(0, ax1), max(0, ay1)
        ax2, ay2 = min(aw, ax2), min(ah, ay2)
        if ax2 <= ax1 or ay2 <= ay1:
            continue

        ocr_path = (OUT_DIR / f"render_room_scan_{hwnd}_button_ocr.bmp").resolve()
        try:
            with dm.bind_window(hwnd, bind_cfg=bind_cfg):
                ok = dm.capture_region(ax1, ay1, ax2, ay2, str(ocr_path))
                if not ok:
                    logger.warning(f"  候选窗口 {hwnd} 按钮区域截图失败")
                    continue
                lines = inf.ocr_lines_from_file(str(ocr_path))
        except Exception as e:
            logger.warning(f"  候选窗口 {hwnd} 绑定/OCR 失败: {e}")
            continue

        button_text = " ".join(ln.get("text", "").strip() for ln in lines)
        logger.info(f"  候选窗口 {hwnd} 按钮 OCR 文本: {button_text}")

        if any(kw in button_text for kw in exclude_keywords):
            logger.info(f"  候选窗口 {hwnd} 不是队员房间（包含 {exclude_keywords}）")
            continue
        if any(kw in button_text for kw in button_keywords):
            player_room_hwnd = hwnd
            logger.info(f"  找到队员房间窗口: hwnd={player_room_hwnd}, 客户区=({aw}x{ah}), 按钮文本={button_text}")
            break

    if not player_room_hwnd:
        logger.error("未找到队员房间窗口，请让另一个 KK 以普通队员身份加入房间，并确保按钮显示'准备'或'取消准备'")
        return

    def _action_room(dm_action, hwnd: int) -> None:
        with dm_action.bind_window(hwnd, bind_cfg=bind_cfg):
            x1, y1, x2, y2 = dm_action.get_client_rect(hwnd)
            aw, ah = x2 - x1, y2 - y1
            base_w, base_h = room_size

            clicked = False
            if start_button_ocr_area != [0, 0, 0, 0]:
                if base_w > 0 and base_h > 0:
                    ax1 = round(start_button_ocr_area[0] * aw / base_w)
                    ay1 = round(start_button_ocr_area[1] * ah / base_h)
                    ax2 = round(start_button_ocr_area[2] * aw / base_w)
                    ay2 = round(start_button_ocr_area[3] * ah / base_h)
                else:
                    ax1, ay1, ax2, ay2 = start_button_ocr_area
                # 限制在客户区内
                ax1, ay1 = max(0, ax1), max(0, ay1)
                ax2, ay2 = min(aw, ax2), min(ah, ay2)

                if ax2 > ax1 and ay2 > ay1:
                    ocr_path = (OUT_DIR / f"render_room_{hwnd}_button_ocr.bmp").resolve()
                    if dm_action.capture_region(ax1, ay1, ax2, ay2, str(ocr_path)):
                        lines = inf.ocr_lines_from_file(str(ocr_path))
                        for ln in lines:
                            text = ln.get("text", "").strip()
                            if any(kw in text for kw in button_keywords):
                                cx = ax1 + int(ln.get("x_center", 0))
                                cy = ay1 + int(ln.get("y_center", 0))
                                dm_action.move_to(cx, cy)
                                time.sleep(0.3)
                                dm_action.left_click()
                                clicked = True
                                logger.info(f"  点击 OCR 识别到的按钮: {text} ({cx},{cy})")
                                break
                        if not clicked:
                            logger.info("  OCR 区域未找到目标文本，回退到 start_button_coords")
                    else:
                        logger.warning("  开始按钮 OCR 区域截图失败")
                else:
                    logger.warning("  开始按钮 OCR 区域计算无效")

            if not clicked:
                # 渲染测试只能点"准备/取消准备"，不能回退到固定坐标（避免误点房主的"开始游戏"）
                logger.warning("  未在按钮 OCR 区域识别到'准备'/'取消准备'，跳过点击（避免误点开始游戏）")
                return

            time.sleep(0.5)

    _render_test_common(dm, player_room_hwnd, bind_cfg, inf, room_size, _action_room)


def _prepare_compatibility_windows(dm, kk_cfg: dict, base_bind_cfg: dict, inf) -> dict[str, dict]:
    """为兼容性矩阵测试准备五个窗口句柄及对应尺寸/关键词（含大厅）。"""
    window_title = kk_cfg.get("window_title", "")
    main_cfg = kk_cfg.get("main", {})
    main_size = tuple(main_cfg.get("window_size", [1332, 945]))
    profile_icon = main_cfg.get("profile_icon_coords", [0, 0])
    dropdown_wait = main_cfg.get("dropdown_wait_time", 1)
    dropdown_class = kk_cfg.get("dropdown_window_class", "")
    dropdown_cfg = kk_cfg.get("dropdown", {})
    dropdown_size = tuple(dropdown_cfg.get("window_size", [0, 0]))

    windows: dict[str, dict] = {}

    # 1. hall：大厅本身也要测试后台绑定
    hall_hwnd = find_hall_window(dm, kk_cfg)
    if hall_hwnd:
        _try_set_client_size(dm, hall_hwnd, main_size, "hall")
        w, h = _get_client_size(dm, hall_hwnd, "hall")
        if w > 0 and h > 0:
            windows["hall"] = {"hwnd": hall_hwnd, "size": (w, h), "keyword": ""}
            logger.info(f"[compatibility] 大厅窗口: hwnd={hall_hwnd}, 客户区=({w}x{h})")
    else:
        logger.error("[compatibility] 未找到大厅窗口")

    # 2. dropdown：需要点击头像触发
    if hall_hwnd:
        pid = dm.get_window_process_id(hall_hwnd)
        before = enum_visible_windows_by_pid(pid)
        _try_set_client_size(dm, hall_hwnd, main_size, "dropdown_hall")
        with dm.bind_window(hall_hwnd, bind_cfg=base_bind_cfg):
            dm.move_to(*profile_icon)
            time.sleep(0.3)
            dm.left_click()
            time.sleep(dropdown_wait)

        after = enum_visible_windows_by_pid(pid)
        before_hwnds = {w["hwnd"] for w in before}
        new_wins = [w for w in after if w["hwnd"] not in before_hwnds]
        dropdown_wins = [w for w in new_wins if dropdown_class and dropdown_class.lower() in w["class"].lower()]
        target_wins = dropdown_wins or new_wins

        if target_wins:
            dd_hwnd = target_wins[0]["hwnd"]
            _try_set_client_size(dm, dd_hwnd, dropdown_size, "dropdown")
            dd_w, dd_h = _get_client_size(dm, dd_hwnd, "dropdown")
            if dd_w > 0 and dd_h > 0:
                windows["dropdown"] = {"hwnd": dd_hwnd, "size": (dd_w, dd_h), "keyword": ""}
                logger.info(f"[compatibility] 下拉框: hwnd={dd_hwnd}, 客户区=({dd_w}x{dd_h})")
            else:
                logger.error("[compatibility] 下拉框客户区尺寸无效")
        else:
            logger.error("[compatibility] 未检测到下拉框窗口")
    else:
        logger.error("[compatibility] 未找到大厅窗口，无法测试下拉框")

    popup_class = kk_cfg.get("create_room_window_class", "")

    # 3. create_room
    create_cfg = kk_cfg.get("create_room", {})
    create_size = tuple(create_cfg.get("dialog_window_size", [584, 488]))
    create_keyword = create_cfg.get("dialog_keyword", "创建房间")
    create_hwnd = find_window_by_class(dm, popup_class, window_title, expected_size=create_size)
    if create_hwnd:
        _try_set_client_size(dm, create_hwnd, create_size, "create_room")
        w, h = _get_client_size(dm, create_hwnd, "create_room")
        if w > 0 and h > 0:
            windows["create_room"] = {
                "hwnd": create_hwnd,
                "size": (w, h),
                "keyword": create_keyword,
            }
            logger.info(f"[compatibility] 创建房间弹窗: hwnd={create_hwnd}, 客户区=({w}x{h})")
    else:
        logger.error("[compatibility] 未找到创建房间弹窗，请手动打开")

    # 4. password
    pwd_cfg = kk_cfg.get("password_input", {})
    pwd_size = tuple(pwd_cfg.get("window_size", [440, 260]))
    pwd_keyword = pwd_cfg.get("dialog_keyword", "输入房间密码")
    pwd_hwnd = find_window_by_class(dm, popup_class, window_title, expected_size=pwd_size)
    if pwd_hwnd:
        _try_set_client_size(dm, pwd_hwnd, pwd_size, "password")
        w, h = _get_client_size(dm, pwd_hwnd, "password")
        if w > 0 and h > 0:
            windows["password"] = {
                "hwnd": pwd_hwnd,
                "size": (w, h),
                "keyword": pwd_keyword,
            }
            logger.info(f"[compatibility] 密码弹窗: hwnd={pwd_hwnd}, 客户区=({w}x{h})")
    else:
        logger.error("[compatibility] 未找到密码弹窗，请手动打开")

    # 4. room
    room_cfg = kk_cfg.get("room", {})
    room_size = tuple(room_cfg.get("window_size", [1224, 904]))
    room_keyword = room_cfg.get("keyword", "房间号")
    window_class = kk_cfg.get("window_class", "")
    min_w, min_h = kk_cfg.get("min_business_window_size", [200, 200])

    hall_hwnd = find_hall_window(dm, kk_cfg)
    pid = dm.get_window_process_id(hall_hwnd) if hall_hwnd else 0
    room_hwnd = 0
    if pid:
        for win in enum_visible_windows_by_pid(pid):
            if win["class"] != window_class:
                continue
            ww = win["rect"][2] - win["rect"][0]
            wh = win["rect"][3] - win["rect"][1]
            if ww < min_w or wh < min_h:
                continue
            ex_style = ctypes.windll.user32.GetWindowLongPtrW(win["hwnd"], -20)
            if ex_style & 0x80000:
                room_hwnd = win["hwnd"]
                break

    if room_hwnd:
        _try_set_client_size(dm, room_hwnd, room_size, "room")
        w, h = _get_client_size(dm, room_hwnd, "room")
        if w > 0 and h > 0:
            windows["room"] = {
                "hwnd": room_hwnd,
                "size": (w, h),
                "keyword": room_keyword,
            }
            logger.info(f"[compatibility] 房间窗口: hwnd={room_hwnd}, 客户区=({w}x{h})")
    else:
        logger.error("[compatibility] 未找到房间窗口，请先手动进入房间")

    return windows


def _save_compatibility_report(report: dict) -> None:
    """保存兼容性报告到 logs/diag_dm_capture/compatibility_report.json。"""
    path = OUT_DIR / "compatibility_report.json"
    with open(path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    logger.info(f"兼容性报告已保存: {path.resolve()}")


def _print_compatibility_summary(report: dict) -> None:
    """打印兼容性测试摘要。"""
    logger.info("\n" + "=" * 60)
    logger.info("大漠 BindWindowEx 兼容性测试摘要")
    logger.info("=" * 60)
    for win in report["windows"]:
        total = len(win["results"])
        valid = sum(1 for r in win["results"] if r["success"] and not r["solid"] and not r["black"])
        hits = sum(1 for r in win["results"] if r.get("keyword_matched"))
        solid_or_black = sum(1 for r in win["results"] if r["solid"] or r["black"])
        logger.info(
            f"窗口 {win['name']}: 总组合 {total}, 有效截图 {valid}, 纯色/黑屏 {solid_or_black}, 关键词命中 {hits}"
        )
        for r in win["results"]:
            if r["success"] and not r["solid"] and not r["black"]:
                status = "关键词命中" if r.get("keyword_matched") else "OCR 成功"
                logger.info(
                    f"  OK: display={r['display']}, mouse={r['mouse']}, "
                    f"keypad={r['keypad']}, mode={r['mode']}, {status}"
                )

    summary = report.get("summary", {})
    logger.info(
        f"总计: 组合 {summary.get('total_combos', 0)}, "
        f"有效 {summary.get('valid_captures', 0)}, 关键词命中 {summary.get('keyword_hits', 0)}"
    )


def test_compatibility(dm, kk_cfg: dict, base_bind_cfg: dict, inf, args: argparse.Namespace) -> None:
    """执行 BindWindowEx 兼容性矩阵测试。

    对 hall / dropdown / create_room / password / room 五个窗口，遍历
    display × mouse × keypad × mode 组合，记录截图、纯色/黑屏、OCR 与关键词命中。
    """
    logger.info("\n" + "=" * 60)
    logger.info("开始大漠 BindWindowEx 兼容性矩阵测试")
    logger.info("=" * 60)

    windows = _prepare_compatibility_windows(dm, kk_cfg, base_bind_cfg, inf)
    if not windows:
        logger.error("未找到任何测试窗口，跳过兼容性测试")
        return

    report = {
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        "command": sys.argv,
        "args": vars(args),
        "windows": [],
        "summary": {"total_combos": 0, "valid_captures": 0, "keyword_hits": 0},
    }

    total = 0
    valid = 0
    hits = 0

    for name, info in windows.items():
        hwnd = info["hwnd"]
        keyword = info.get("keyword", "")
        win_results = []
        logger.info(f"[compatibility] 测试窗口 {name}, hwnd={hwnd}")

        for display in args.displays:
            for mouse in args.mice:
                for keypad in args.keypads:
                    for mode in args.modes:
                        combo_cfg = {
                            "display": display,
                            "mouse": mouse,
                            "keypad": keypad,
                            "mode": mode,
                            "bind_delay": args.bind_delay,
                            "public": base_bind_cfg.get("public", ""),
                        }
                        safe_display = display.replace(".", "_")
                        label = f"compat_{name}_{safe_display}_{mouse}_{keypad}_{mode}"
                        result = _capture_single(dm, hwnd, combo_cfg, label, inf, keyword=keyword)

                        win_results.append(result)
                        total += 1
                        if result["success"] and not result["solid"] and not result["black"]:
                            valid += 1
                        if result["keyword_matched"]:
                            hits += 1

                        status = "OK" if (result["success"] and not result["solid"] and not result["black"]) else "FAIL"
                        matched = ", 关键词命中" if result["keyword_matched"] else ""
                        logger.info(f"[{name}] {display}/{mouse}/{keypad}/mode={mode}: {status}{matched}")

        report["windows"].append(
            {
                "name": name,
                "hwnd": hwnd,
                "size": list(info["size"]),
                "keyword": keyword,
                "results": win_results,
            }
        )

    report["summary"] = {
        "total_combos": total,
        "valid_captures": valid,
        "keyword_hits": hits,
    }

    _save_compatibility_report(report)
    _print_compatibility_summary(report)

    # 关闭下拉框
    if "dropdown" in windows:
        hall_hwnd = find_hall_window(dm, kk_cfg)
        if hall_hwnd:
            with dm.bind_window(hall_hwnd, bind_cfg=base_bind_cfg):
                dm.key_press_char("esc")
            time.sleep(0.3)


def _parse_arg_list(values: list[str] | None, default: list, cast: type = str) -> list:
    """解析命令行列表参数，支持逗号分隔和多个空格分隔值。"""
    if values is None:
        return default
    result = []
    for v in values:
        for part in v.split(","):
            part = part.strip()
            if part:
                result.append(cast(part))
    return result or default


def parse_args() -> argparse.Namespace:
    """解析命令行参数，保持旧式 positional target 兼容。"""
    parser = argparse.ArgumentParser(description="大漠后台截图手动测试（单窗口 + BindWindowEx 兼容性矩阵）")
    parser.add_argument(
        "target",
        nargs="?",
        choices=[
            "dropdown",
            "create_room",
            "password",
            "hall",
            "room",
            "compatibility",
            "render_password",
            "render_room",
            "render_password_minimal",
            "render_create_room_password",
        ],
        help="测试目标",
    )
    parser.add_argument(
        "--displays",
        nargs="*",
        type=str,
        default=None,
        help="兼容性测试 display 列表，逗号或空格分隔",
    )
    parser.add_argument(
        "--mice",
        nargs="*",
        type=str,
        default=None,
        help="兼容性测试 mouse 列表",
    )
    parser.add_argument(
        "--keypads",
        nargs="*",
        type=str,
        default=None,
        help="兼容性测试 keypad 列表",
    )
    parser.add_argument(
        "--modes",
        nargs="*",
        type=int,
        default=None,
        help="兼容性测试 mode 列表",
    )
    parser.add_argument(
        "--bind-delay",
        type=float,
        default=1.0,
        help="每次绑定后等待时间（秒），默认 1.0",
    )
    parser.add_argument(
        "--delay",
        type=float,
        default=5.0,
        help="测试开始前等待时间（秒），默认 5.0",
    )
    args = parser.parse_args()
    if args.target is None:
        parser.print_help()
        sys.exit(1)

    args.displays = _parse_arg_list(args.displays, DEFAULT_DISPLAYS)
    args.mice = _parse_arg_list(args.mice, DEFAULT_MICE)
    args.keypads = _parse_arg_list(args.keypads, DEFAULT_KEYPADS)
    args.modes = _parse_arg_list(args.modes, DEFAULT_MODES, cast=int)
    return args


def main() -> None:
    args = parse_args()
    target = args.target

    setup_log_file(f"测试大漠后台截图_{target}")
    logger.info(f"############################# 大漠后台截图测试 — {target} #############################")
    logger.info(f"{args.delay} 秒后开始...")
    time.sleep(args.delay)

    # 从配置文件读取
    cfg = config.load_task("kk")
    kk_cfg = cfg.get("kk", {})
    bind_cfg = load_bind_cfg(kk_cfg)
    bind_cfg["bind_delay"] = args.bind_delay

    OUT_DIR.mkdir(parents=True, exist_ok=True)

    dm = create_dm_client()
    logger.info(f"大漠版本: {dm.version}")
    inf = get_inference_client(load_chest=False, load_combat=False)
    logger.info("RapidOCR 客户端已加载")

    if target == "dropdown":
        test_dropdown(dm, kk_cfg, bind_cfg, inf)
    elif target == "create_room":
        test_create_room(dm, kk_cfg, bind_cfg, inf)
    elif target == "password":
        test_password(dm, kk_cfg, bind_cfg, inf)
    elif target == "hall":
        test_hall(dm, kk_cfg, bind_cfg, inf)
    elif target == "room":
        test_room(dm, kk_cfg, bind_cfg, inf)
    elif target == "render_password":
        test_render_password(dm, kk_cfg, bind_cfg, inf)
    elif target == "render_room":
        test_render_room(dm, kk_cfg, bind_cfg, inf)
    elif target == "render_password_minimal":
        test_render_password_minimal(dm, kk_cfg, bind_cfg, inf)
    elif target == "render_create_room_password":
        test_render_create_room_password(dm, kk_cfg, bind_cfg, inf)
    elif target == "compatibility":
        test_compatibility(dm, kk_cfg, bind_cfg, inf, args)

    logger.info("\n" + "=" * 60)
    logger.info(f"测试完成！截图保存到: {OUT_DIR.absolute()}")
    logger.info("=" * 60)
    dm.close()


if __name__ == "__main__":
    main()
