"""对比 KK 主界面窗口与房间窗口的特征差异。

枚举同进程同类名窗口，打印所有可获取的窗口属性，帮助找到区分特征。

运行：uv run python tests/manual/test_window_diff.py
前提：KK 主界面和房间窗口都已打开。
配置来源：src/GameBot/config/data/kk.toml
"""

import ctypes
import time

from GameBot.config import config
from GameBot.runner.driver import create_dm_client
from GameBot.utils import logger, setup_log_file

# ctypes 定义
user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32

EnumWindows = user32.EnumWindows
EnumWindowsProc = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)
GetWindowTextW = user32.GetWindowTextW
GetWindowTextLengthW = user32.GetWindowTextLengthW
GetClassNameW = user32.GetClassNameW
IsWindowVisible = user32.IsWindowVisible
GetWindowRect = user32.GetWindowRect
GetClientRect = user32.GetClientRect
GetWindowThreadProcessId = user32.GetWindowThreadProcessId
GetWindowLongW = user32.GetWindowLongW
GetWindowLongPtrW = user32.GetWindowLongPtrW
GetParent = user32.GetParent
GetAncestor = user32.GetAncestor
GetWindow = user32.GetWindow
IsWindowEnabled = user32.IsWindowEnabled
IsWindowUnicode = user32.IsWindowUnicode


def get_window_props(hwnd: int) -> dict:
    """获取窗口的所有可区分属性。"""
    # 标题
    length = GetWindowTextLengthW(hwnd)
    buf = ctypes.create_unicode_buffer(length + 1)
    GetWindowTextW(hwnd, buf, length + 1)
    title = buf.value

    # 类名
    cls_buf = ctypes.create_unicode_buffer(256)
    GetClassNameW(hwnd, cls_buf, 256)
    cls = cls_buf.value

    # 窗口矩形（屏幕坐标）
    wrect = ctypes.wintypes.RECT()
    GetWindowRect(hwnd, ctypes.byref(wrect))

    # 客户区矩形（屏幕坐标）
    crect = ctypes.wintypes.RECT()
    GetClientRect(hwnd, ctypes.byref(crect))

    # 客户区左上角屏幕坐标
    pt = ctypes.wintypes.POINT(0, 0)
    user32.ClientToScreen(hwnd, ctypes.byref(pt))

    # PID 和 TID
    pid = ctypes.c_ulong()
    tid = GetWindowThreadProcessId(hwnd, ctypes.byref(pid))

    # 窗口风格
    style = GetWindowLongPtrW(hwnd, -16)  # GWL_STYLE
    ex_style = GetWindowLongPtrW(hwnd, -20)  # GWL_EXSTYLE

    # 父窗口
    parent = GetParent(hwnd)

    # 拥有者窗口（通过 GetWindow with GW_OWNER = 3）
    owner = GetWindow(hwnd, 3)

    # 祖先窗口（GA_ROOT = 2）
    root = 0
    try:
        root = GetAncestor(hwnd, 2)
    except Exception:
        pass

    # 是否启用
    enabled = IsWindowEnabled(hwnd)

    # 是否 Unicode
    is_unicode = IsWindowUnicode(hwnd)

    # 窗口 ID (GWLP_ID = -12)
    win_id = GetWindowLongPtrW(hwnd, -12)

    return {
        "hwnd": int(hwnd),
        "title": title,
        "class": cls,
        "window_rect": (int(wrect.left), int(wrect.top), int(wrect.right), int(wrect.bottom)),
        "window_size": (int(wrect.right - wrect.left), int(wrect.bottom - wrect.top)),
        "client_rect": (int(crect.left), int(crect.top), int(crect.right), int(crect.bottom)),
        "client_size": (int(crect.right - crect.left), int(crect.bottom - crect.top)),
        "client_screen_origin": (int(pt.x), int(pt.y)),
        "pid": int(pid.value),
        "tid": int(tid),
        "style": hex(int(style)),
        "ex_style": hex(int(ex_style)),
        "parent": int(parent),
        "owner": int(owner),
        "root": int(root),
        "enabled": bool(enabled),
        "is_unicode": bool(is_unicode),
        "win_id": int(win_id),
    }


def main():
    setup_log_file("窗口特征对比")
    logger.info("############################# 窗口特征对比 #############################")
    logger.info("前提：KK 主界面和房间窗口都已打开")
    logger.info("5 秒后开始...")
    time.sleep(5)

    cfg = config.load_task("kk")
    kk_cfg = cfg.get("kk", {})
    window_class = kk_cfg.get("window_class", "")
    window_title = kk_cfg.get("window_title", "")
    min_w, min_h = kk_cfg.get("min_business_window_size", [200, 200])

    dm = create_dm_client()
    logger.info(f"大漠版本: {dm.version}")

    # 先找到主界面 PID
    hall_hwnd = 0
    for h in dm.enum_windows(window_class, window_title):
        if not dm.is_window_visible(h):
            continue
        if dm.get_window_class(h) != window_class:
            continue
        hall_hwnd = int(h)
        break

    if not hall_hwnd:
        logger.error("未找到 KK 主界面窗口")
        return

    pid = dm.get_window_process_id(hall_hwnd)
    logger.info(f"主界面窗口: hwnd={hall_hwnd}, PID={pid}")

    # 枚举同 PID 所有可见窗口
    results = []

    def callback(hwnd, _lparam):
        if not IsWindowVisible(hwnd):
            return True
        p = ctypes.c_ulong()
        GetWindowThreadProcessId(hwnd, ctypes.byref(p))
        if int(p.value) != pid:
            return True
        props = get_window_props(int(hwnd))
        results.append(props)
        return True

    EnumWindows(EnumWindowsProc(callback), 0)

    # 筛选同类名窗口
    same_class = [r for r in results if r["class"] == window_class]
    logger.info(f"\n同类名窗口（class={window_class}）共 {len(same_class)} 个:")

    for i, r in enumerate(same_class):
        tag = " ← 主界面" if r["hwnd"] == hall_hwnd else " ← 房间?"
        logger.info(f"\n--- 窗口 [{i}] hwnd={r['hwnd']}{tag} ---")
        for k, v in r.items():
            logger.info(f"  {k:25s} = {v}")

    # 对比差异
    if len(same_class) >= 2:
        logger.info("\n" + "=" * 60)
        logger.info("属性差异对比:")
        logger.info("=" * 60)
        w1 = same_class[0]
        w2 = same_class[1]
        for k in w1:
            if w1[k] != w2[k]:
                logger.info(f"  {k:25s} 窗口0={w1[k]}  vs  窗口1={w2[k]}")
        logger.info("(以上是两个窗口值不同的属性)")

    dm.close()
    logger.info("\n对比完成")


if __name__ == "__main__":
    main()
