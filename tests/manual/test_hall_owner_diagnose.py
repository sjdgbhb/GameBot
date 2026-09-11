"""诊断脚本：定位 KK 大厅头像下拉框窗口并尝试截图 OCR。

核心问题：GDI2 后台截图捕获不到下拉框内容，导致 OCR 为空。
本脚本通过点击前/后枚举同 PID 窗口的差异，找到下拉框窗口，
然后对它做 GDI2 后台截图 + 屏幕截图对比，并尝试 OCR。

运行：uv run python tests/manual/test_hall_owner_diagnose.py
"""

import ctypes
import time
from pathlib import Path

from PIL import ImageGrab

from GameBot.config import config
from GameBot.inference import get_inference_client
from GameBot.runner.driver import create_dm_client
from GameBot.runner.driver.window import WindowMixin
from GameBot.utils import logger, setup_log_file


def enum_visible_windows_by_pid(target_pid: int) -> list:
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


def screen_capture(bbox, filepath: str):
    """ImageGrab 屏幕截图。"""
    img = ImageGrab.grab(bbox=bbox)
    img.save(filepath)
    logger.info(f"  屏幕截图已保存: {filepath}")


def diff_windows(before: list, after: list) -> list:
    """找出 after 中新增的窗口（按 hwnd 差集）。"""
    before_hwnds = {w["hwnd"] for w in before}
    return [w for w in after if w["hwnd"] not in before_hwnds]


def main():
    setup_log_file("KK大厅下拉框诊断")
    logger.info("############################# KK 大厅下拉框诊断 #############################")

    cfg = config.load_task("war3.jiubing2.tasks.endless.endless")
    kk_cfg = cfg.get("kk", {})
    window_class = kk_cfg.get("window_class", "")
    window_title = kk_cfg.get("window_title", "")
    main_cfg = kk_cfg.get("main", {})
    main_size = tuple(main_cfg.get("window_size", [1332, 945]))
    profile_icon = main_cfg.get("profile_icon_coords", [0, 0])
    username_area = main_cfg.get("username_area_coords", [0, 0, 0, 0])
    dropdown_wait = main_cfg.get("dropdown_wait_time", 1)
    bind_background = kk_cfg.get("bind_background", {})
    min_size = kk_cfg.get("min_business_window_size", [200, 200])

    logger.info(f"头像图标坐标: {profile_icon}")
    logger.info(f"用户名 OCR 区域: {username_area}")
    logger.info(f"下拉框等待时间: {dropdown_wait}s")

    out_dir = Path("logs/diag_hall_owner")
    out_dir.mkdir(parents=True, exist_ok=True)

    dm = create_dm_client()
    inf = get_inference_client(load_chest=False, load_combat=False)

    logger.info("3 秒后开始枚举 KK 主窗口...")
    time.sleep(3)

    # 枚举可见 KK 主窗口
    hwnds = dm.enum_windows(window_class, window_title, filter=1 + 2 + 8 + 16)
    candidates = []
    for hwnd in hwnds:
        if not WindowMixin.is_window_visible(hwnd):
            continue
        try:
            x1, y1, x2, y2 = dm.get_client_rect(hwnd)
            w, h = x2 - x1, y2 - y1
            if w < min_size[0] or h < min_size[1]:
                continue
            pid = dm.get_window_process_id(hwnd)
            candidates.append({"hwnd": hwnd, "pid": pid, "rect": (x1, y1, x2, y2), "size": (w, h)})
            logger.info(f"候选主窗口: hwnd={hwnd}, pid={pid}, 尺寸=({w}x{h})")
        except Exception as e:
            logger.error(f"  hwnd={hwnd} 获取信息失败: {e}")

    if not candidates:
        logger.error("未找到可见的 KK 主窗口候选")
        return

    for idx, cand in enumerate(candidates):
        hwnd = cand["hwnd"]
        pid = cand["pid"]
        rect = cand["rect"]
        w, h = cand["size"]
        label = f"hwnd_{hwnd}_pid_{pid}"

        logger.info(f"\n{'=' * 60}")
        logger.info(f"诊断窗口 {idx + 1}/{len(candidates)}: hwnd={hwnd}, pid={pid}, 尺寸=({w}x{h})")
        logger.info(f"{'=' * 60}")

        # --- 步骤 1：点击前枚举同 PID 窗口 ---
        logger.info("[步骤1] 点击前枚举同 PID 可见窗口")
        wins_before = enum_visible_windows_by_pid(pid)
        for win in wins_before:
            wr = win["rect"]
            tag = " ← 主窗口" if win["hwnd"] == hwnd else ""
            logger.info(
                f"  hwnd={win['hwnd']}, class={win['class']}, title={win['title']!r}, 尺寸=({wr[2] - wr[0]}x{wr[3] - wr[0]}){tag}"
            )

        # --- 步骤 2：绑定主窗口，点击头像 ---
        logger.info(f"[步骤2] 绑定主窗口并点击头像图标 {profile_icon}")
        try:
            dm.set_client_size(hwnd, *main_size)
            with dm.bind_window(hwnd, bind_cfg=bind_background):
                dm.move_to(*profile_icon)
                time.sleep(0.3)
                dm.left_click()
                logger.info(f"  已点击，等待下拉框 {dropdown_wait} 秒...")
                time.sleep(dropdown_wait)

                # --- 步骤 3：在 bind 内对主窗口做 GDI2 截图 ---
                logger.info("[步骤3] GDI2 后台截图 — 主窗口全屏 + 用户名区域")
                gdi_main = out_dir / f"{label}_1_gdi_main_after_click.bmp"
                if dm.capture_region(0, 0, w, h, str(gdi_main)):
                    logger.info(f"  主窗口 GDI2 截图: {gdi_main}")
                ux1, uy1, ux2, uy2 = username_area
                gdi_ocr = out_dir / f"{label}_2_gdi_ocr_area_after_click.bmp"
                if dm.capture_region(ux1, uy1, ux2, uy2, str(gdi_ocr)):
                    logger.info(f"  用户名区域 GDI2 截图: {gdi_ocr}")
                    # 尝试 OCR
                    lines = inf.ocr_lines_from_file(str(gdi_ocr))
                    texts = [ln.get("text", "").strip() for ln in lines if ln.get("text", "").strip()]
                    logger.info(f"  用户名区域 GDI2 OCR 结果: {texts}")

                # --- 步骤 4：在 bind 内枚举同 PID 窗口（下拉框可能已出现） ---
                logger.info("[步骤4] 点击后枚举同 PID 可见窗口")
                wins_after = enum_visible_windows_by_pid(pid)
                new_wins = diff_windows(wins_before, wins_after)
                logger.info(f"  新增窗口 {len(new_wins)} 个:")
                for win in new_wins:
                    wr = win["rect"]
                    ww, wh = wr[2] - wr[0], wr[3] - wr[1]
                    logger.info(
                        f"    hwnd={win['hwnd']}, class={win['class']}, title={win['title']!r}, 尺寸=({ww}x{wh}), 坐标=({wr[0]},{wr[1]})"
                    )

                # --- 步骤 5：对新窗口（下拉框）做截图 ---
                if new_wins:
                    for nidx, new_win in enumerate(new_wins):
                        nhwnd = new_win["hwnd"]
                        nrect = new_win["rect"]
                        nw, nh = nrect[2] - nrect[0], nrect[3] - nrect[1]
                        nlabel = f"{label}_dropdown_{nidx}_hwnd_{nhwnd}"
                        logger.info(f"[步骤5] 对下拉框窗口 hwnd={nhwnd} ({nw}x{nh}) 截图")

                        # 5a. 屏幕截图
                        screen_dd = out_dir / f"{nlabel}_3_screen.png"
                        screen_capture(nrect, str(screen_dd))

                        # 5b. GDI2 后台截图（绑定下拉框窗口）
                        try:
                            with dm.bind_window(nhwnd, bind_cfg=bind_background):
                                gdi_dd = out_dir / f"{nlabel}_4_gdi.bmp"
                                if dm.capture_region(0, 0, nw, nh, str(gdi_dd)):
                                    logger.info(f"  下拉框 GDI2 截图: {gdi_dd}")
                                    # 对整个下拉框做 OCR
                                    lines = inf.ocr_lines_from_file(str(gdi_dd))
                                    texts = [ln.get("text", "").strip() for ln in lines if ln.get("text", "").strip()]
                                    logger.info(f"  下拉框 GDI2 OCR 结果: {texts}")
                                    for ln in lines:
                                        t = ln.get("text", "").strip()
                                        if t:
                                            logger.info(f"    行: {t}  bbox={ln.get('bbox')}")
                        except Exception as e:
                            logger.warning(f"  绑定下拉框窗口失败: {e}")

                        # 5c. 也用前台绑定试试
                        try:
                            with dm.bind_window(nhwnd, bind_cfg=kk_cfg.get("bind", {})):
                                gdi_dd_fg = out_dir / f"{nlabel}_5_gdi_foreground.bmp"
                                if dm.capture_region(0, 0, nw, nh, str(gdi_dd_fg)):
                                    logger.info(f"  下拉框前台绑定截图: {gdi_dd_fg}")
                                    lines = inf.ocr_lines_from_file(str(gdi_dd_fg))
                                    texts = [ln.get("text", "").strip() for ln in lines if ln.get("text", "").strip()]
                                    logger.info(f"  下拉框前台 OCR 结果: {texts}")
                        except Exception as e:
                            logger.warning(f"  前台绑定下拉框失败: {e}")
                else:
                    logger.warning("[步骤5] 未检测到新增窗口！下拉框可能不是独立顶层窗口。")
                    logger.info("  → 下拉框可能是主窗口内的覆盖层，GDI2 无法捕获。")
                    logger.info("  → 需要改用 dx2/dx3 显示模式，或此步骤临时用前台截图。")
                    # 屏幕截图作为 fallback
                    screen_dd = out_dir / f"{label}_6_screen_no_dropdown_window.png"
                    screen_capture(rect, str(screen_dd))

                # --- 步骤 6：按 Esc 关闭下拉框 ---
                logger.info("[步骤6] 按 Esc 关闭下拉框")
                dm.key_press_char("esc")
                time.sleep(0.3)
        except Exception as e:
            logger.error(f"  操作失败: {e}")

    logger.info(f"\n{'=' * 60}")
    logger.info(f"诊断完成！截图保存到: {out_dir.absolute()}")
    logger.info("关键对比：")
    logger.info("  *_1_gdi_main_after_click.bmp  → GDI2 能否看到下拉框")
    logger.info("  *_3_screen.png  → 屏幕上实际的下拉框")
    logger.info("  *_4_gdi.bmp  → 对下拉框独立窗口做 GDI2 截图")
    logger.info("  *_5_gdi_foreground.bmp  → 对下拉框做前台绑定截图")
    logger.info("  日志中 OCR 结果  → 哪种方式能识别到用户名")
    logger.info(f"{'=' * 60}")


if __name__ == "__main__":
    main()
