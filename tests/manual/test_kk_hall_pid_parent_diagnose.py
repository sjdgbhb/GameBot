"""诊断 KK 大厅、下拉框、弹窗、房间的 PID 与父子/属主关系。

用法：
    uv run python tests/manual/test_kk_hall_pid_parent_diagnose.py
    uv run python tests/manual/test_kk_hall_pid_parent_diagnose.py --delay 3
    uv run python tests/manual/test_kk_hall_pid_parent_diagnose.py --only-hall

输出：
1. 当前所有 KK 大厅窗口的 hwnd、PID、父/属主/根窗口、尺寸、标题、类名。
2. 按 PID 分组列出该 KK 进程下所有可见顶层窗口，包含弹窗/房间/下拉框等。
3. 逐个点击每个大厅头像，打印点击前后新增窗口及其 PID、父/属主/根窗口、OCR 玩家名。
4. 对比"旧实现"（直接取 Z 序第一个）与"新实现"（差分 + 父/属主校验）分别会选中的下拉框。

注意：运行前请确保 KK 已打开对应大厅，且大漠桥接环境可用。
"""

from __future__ import annotations

import argparse
import ctypes
import time
from pathlib import Path

from GameBot.config import config
from GameBot.inference import get_inference_client
from GameBot.runner.driver import create_dm_client
from GameBot.runner.driver.window import WindowMixin
from GameBot.utils import logger, setup_log_file

user32 = ctypes.windll.user32

user32.GetParent.restype = ctypes.c_void_p
user32.GetAncestor.restype = ctypes.c_void_p
user32.GetWindowLongPtrW.restype = ctypes.c_size_t

GWL_HWNDPARENT = -8
GA_ROOT = 2


def get_window_props(hwnd: int) -> dict:
    """获取窗口的关键可区分属性。"""
    length = user32.GetWindowTextLengthW(hwnd)
    title_buf = ctypes.create_unicode_buffer(length + 1)
    user32.GetWindowTextW(hwnd, title_buf, length + 1)

    cls_buf = ctypes.create_unicode_buffer(256)
    user32.GetClassNameW(hwnd, cls_buf, 256)

    rect = ctypes.wintypes.RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(rect))

    pid = ctypes.c_ulong()
    tid = user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))

    parent = int(user32.GetParent(hwnd) or 0)
    root = int(user32.GetAncestor(hwnd, GA_ROOT) or 0)
    owner_or_parent = int(user32.GetWindowLongPtrW(hwnd, GWL_HWNDPARENT) or 0)

    return {
        "hwnd": int(hwnd),
        "title": title_buf.value,
        "class": cls_buf.value,
        "rect": (int(rect.left), int(rect.top), int(rect.right), int(rect.bottom)),
        "size": (int(rect.right - rect.left), int(rect.bottom - rect.top)),
        "pid": int(pid.value),
        "tid": int(tid),
        "parent": parent,
        "owner_or_parent": owner_or_parent,
        "root": root,
    }


def enum_visible_windows_by_pid(target_pid: int) -> list:
    """枚举指定 PID 的所有可见顶层窗口。"""
    results = []

    EnumWindowsProc = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)

    def callback(hwnd, _lparam):
        if not user32.IsWindowVisible(hwnd):
            return True
        pid = ctypes.c_ulong()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if int(pid.value) != target_pid:
            return True
        results.append(get_window_props(int(hwnd)))
        return True

    user32.EnumWindows(EnumWindowsProc(callback), 0)
    return results


def find_dropdown_candidates(windows: list, keyword: str) -> list:
    """从窗口列表中筛出类名含 dropdown 关键词的窗口。"""
    return [w for w in windows if keyword.lower() in w["class"].lower()]


def select_dropdown_old(dropdowns: list) -> dict | None:
    """旧实现：直接取 Z 序第一个匹配项。"""
    return dropdowns[0] if dropdowns else None


def select_dropdown_new(before: list, after: list, hall_hwnd: int) -> dict | None:
    """新实现：差分后优先父/属主是当前大厅的下拉框。"""
    before_hwnds = {w["hwnd"] for w in before}
    new = [w for w in after if w["hwnd"] not in before_hwnds]

    if new:
        for w in new:
            if w["parent"] == hall_hwnd or w["owner_or_parent"] == hall_hwnd or w["root"] == hall_hwnd:
                return w
        return new[0]

    for w in after:
        if w["parent"] == hall_hwnd or w["owner_or_parent"] == hall_hwnd or w["root"] == hall_hwnd:
            return w
    return after[0] if after else None


def ocr_dropdown(dm, inf, hwnd: int, w: int, h: int, bind_cfg: dict) -> str:
    """绑定下拉框，GDI2 后台截图并 OCR 返回第一个非空文本。"""
    out_dir = Path("logs/diag_hall_pid_parent")
    out_dir.mkdir(parents=True, exist_ok=True)
    img = out_dir / f"dropdown_{hwnd}.bmp"

    try:
        with dm.bind_window(hwnd, bind_cfg=bind_cfg):
            dm.capture_region(0, 0, w, h, str(img))
            lines = inf.ocr_lines_from_file(str(img))
            for line in lines:
                text = line.get("text", "").strip()
                if text:
                    return text
    except Exception as e:
        logger.warning(f"下拉框 {hwnd} OCR 异常: {e}")
    return ""


def main() -> int:
    parser = argparse.ArgumentParser(description="KK 大厅下拉框 PID/父子关系诊断")
    parser.add_argument("--delay", type=int, default=3, help="启动前等待秒数")
    parser.add_argument("--only-hall", action="store_true", help="只枚举大厅信息，不点击头像")
    args = parser.parse_args()

    setup_log_file("KK大厅PID父子诊断")
    logger.info("=" * 80)
    logger.info("KK 大厅 / 下拉框 / 弹窗 PID 与父子/属主关系诊断")
    logger.info("=" * 80)

    for i in range(args.delay, 0, -1):
        logger.info(f"{i} 秒后开始...")
        time.sleep(1)

    cfg = config.load_task("kk")
    kk_cfg = cfg.get("kk", {})
    window_class = kk_cfg.get("window_class", "")
    window_title = kk_cfg.get("window_title", "")
    min_w, min_h = kk_cfg.get("min_business_window_size", [200, 200])
    main_size = tuple(kk_cfg.get("main", {}).get("window_size", [1332, 945]))
    profile_icon = tuple(kk_cfg.get("main", {}).get("profile_icon_coords", [0, 0]))
    dropdown_wait = kk_cfg.get("main", {}).get("dropdown_wait_time", 1)
    dropdown_class_kw = kk_cfg.get("main", {}).get("dropdown_window_class", "Popup")
    bind_background = kk_cfg.get("bind_background", {})

    if not bind_background:
        logger.warning("配置中未找到 [kk.bind_background]，诊断脚本使用 bind_background 后台绑定可能失败")

    dm = create_dm_client()
    inf = get_inference_client(load_chest=False, load_combat=False)

    logger.info(f"\n大漠版本: {dm.version}")
    logger.info(f"目标窗口类名: {window_class}")
    logger.info(f"目标窗口标题: {window_title}")
    logger.info(f"头像坐标: {profile_icon}")

    # 1. 枚举所有候选大厅窗口
    all_hwnds = dm.enum_windows(window_class, window_title, filter=1 + 2 + 8 + 16)
    candidates = []
    for hwnd in all_hwnds:
        hwnd = int(hwnd)
        if not WindowMixin.is_window_visible(hwnd):
            continue
        x1, y1, x2, y2 = dm.get_client_rect(hwnd)
        w, h = x2 - x1, y2 - y1
        if w < min_w or h < min_h:
            continue
        props = get_window_props(hwnd)
        props["client_rect"] = (x1, y1, x2, y2)
        candidates.append(props)

    if not candidates:
        logger.error("未找到可见的 KK 大厅候选窗口")
        return 1

    logger.info(f"\n找到 {len(candidates)} 个候选大厅窗口:")
    for c in candidates:
        logger.info(
            f"  hwnd={c['hwnd']}, pid={c['pid']}, class={c['class']!r}, "
            f"title={c['title']!r}, size={c['size']}, "
            f"parent={c['parent']}, owner_or_parent={c['owner_or_parent']}, root={c['root']}"
        )

    # 2. 按 PID 分组展示当前所有可见窗口
    all_pids = {c["pid"] for c in candidates}
    logger.info(f"\n涉及 PID 集合: {sorted(all_pids)}")
    for pid in all_pids:
        wins = enum_visible_windows_by_pid(pid)
        logger.info(f"\n--- PID {pid} 下可见顶层窗口（共 {len(wins)} 个）---")
        for w in wins:
            logger.info(
                f"  hwnd={w['hwnd']}, class={w['class']!r}, title={w['title']!r}, "
                f"size={w['size']}, parent={w['parent']}, "
                f"owner_or_parent={w['owner_or_parent']}, root={w['root']}"
            )

    if args.only_hall:
        logger.info("\n--only-hall 模式，跳过点击头像诊断")
        return 0

    # 3. 逐个点击头像，诊断下拉框
    logger.info("\n" + "=" * 80)
    logger.info("逐个点击大厅头像，观察下拉框归属")
    logger.info("=" * 80)

    for c in candidates:
        hall_hwnd = c["hwnd"]
        pid = c["pid"]
        logger.info(f"\n--- 诊断大厅 hwnd={hall_hwnd}, pid={pid} ---")

        # 点击前快照
        before = enum_visible_windows_by_pid(pid)
        before_dropdowns = find_dropdown_candidates(before, dropdown_class_kw)
        logger.info(
            f"点击前同 PID 下拉框候选: {len(before_dropdowns)} 个，hwnds={[w['hwnd'] for w in before_dropdowns]}"
        )

        # 绑定大厅，点击头像
        try:
            dm.set_client_size(hall_hwnd, *main_size)
            with dm.bind_window(hall_hwnd, bind_cfg=bind_background):
                dm.move_to(*profile_icon)
                time.sleep(0.3)
                dm.left_click()
                logger.info(f"已点击头像 {profile_icon}，等待 {dropdown_wait}s...")
                time.sleep(dropdown_wait)
        except Exception as e:
            logger.error(f"点击头像失败: {e}")
            continue

        # 点击后快照
        after = enum_visible_windows_by_pid(pid)
        after_dropdowns = find_dropdown_candidates(after, dropdown_class_kw)
        logger.info(f"点击后同 PID 下拉框候选: {len(after_dropdowns)} 个")
        for w in after_dropdowns:
            logger.info(
                f"  hwnd={w['hwnd']}, class={w['class']!r}, title={w['title']!r}, "
                f"size={w['size']}, parent={w['parent']}, "
                f"owner_or_parent={w['owner_or_parent']}, root={w['root']}"
            )

        # 旧/新实现分别会选中的下拉框
        old_dd = select_dropdown_old(after_dropdowns)
        new_dd = select_dropdown_new(before_dropdowns, after_dropdowns, hall_hwnd)

        if old_dd:
            logger.info(
                f"旧实现会选中: hwnd={old_dd['hwnd']}, parent={old_dd['parent']}, "
                f"owner_or_parent={old_dd['owner_or_parent']}"
            )
        if new_dd:
            logger.info(
                f"新实现会选中: hwnd={new_dd['hwnd']}, parent={new_dd['parent']}, "
                f"owner_or_parent={new_dd['owner_or_parent']}"
            )

        # 对两个实现分别选中窗口做 OCR，便于对比
        for name, dd in (("旧实现", old_dd), ("新实现", new_dd)):
            if not dd:
                logger.warning(f"{name} 未找到下拉框，无法 OCR")
                continue
            dd_w = dd["rect"][2] - dd["rect"][0]
            dd_h = dd["rect"][3] - dd["rect"][1]
            text = ocr_dropdown(dm, inf, dd["hwnd"], dd_w, dd_h, bind_background)
            logger.info(f"{name} 下拉框 OCR 玩家名: {text!r}")

        # 关闭下拉框
        try:
            with dm.bind_window(hall_hwnd, bind_cfg=bind_background):
                dm.key_press_char("esc")
                time.sleep(0.3)
        except Exception as e:
            logger.warning(f"关闭下拉框失败: {e}")

        logger.info(f"--- 大厅 hwnd={hall_hwnd} 诊断结束 ---")

    dm.close()
    logger.info("\n诊断完成")
    return 0


if __name__ == "__main__":
    import sys

    sys.exit(main())
