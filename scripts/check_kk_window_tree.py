"""检查 KK 平台及 War3 窗口父子关系。

运行方式（不需要大漠 COM，仅使用 Win32 API，可在任意 Python 环境执行）：
    uv run python scripts/check_kk_window_tree.py

测试目的：
    在 KK 处于不同状态（主界面、创建房间弹窗、房间）时运行，
    检查这些窗口之间是否存在 Win32 父子关系。

    建议在以下状态时分别运行：
    1. 仅打开 KK 主界面
    2. 在主界面中点击"创建房间"，弹出创建房间弹窗时
    3. 进入 KK 房间后
    4. 多开两个 KK，上述每种状态

窗口尺寸从配置文件读取，确保与实际运行时一致：
    - KK 主界面：kk.toml [kk.main] window_size
    - KK 房间：kk.toml [kk.room] window_size
    - 创建房间弹窗：kk.toml [kk.create_room] dialog_window_size
    - 掉线重连弹窗：kk.toml [kk.disconnect_dialog] window_size
    - War3：war3.toml [war3] client_size
"""

import ctypes
from ctypes import wintypes
from pathlib import Path

import tomllib

user32 = ctypes.windll.user32

# 配置文件路径
CONFIG_DIR = Path(__file__).resolve().parent.parent / "src" / "GameBot" / "config" / "data"


def load_window_sizes():
    """从 TOML 配置文件读取窗口尺寸，确保与实际运行时一致。"""
    sizes = {}

    # KK 配置
    kk_path = CONFIG_DIR / "kk.toml"
    if kk_path.exists():
        with open(kk_path, "rb") as f:
            kk = tomllib.load(f)
        kk_cfg = kk.get("kk", {})
        if "main" in kk_cfg:
            sizes["kk_main"] = tuple(kk_cfg["main"]["window_size"])
        if "room" in kk_cfg:
            sizes["kk_room"] = tuple(kk_cfg["room"]["window_size"])
        if "create_room" in kk_cfg:
            sizes["create_room_dialog"] = tuple(kk_cfg["create_room"]["dialog_window_size"])
        if "disconnect_dialog" in kk_cfg:
            sizes["disconnect_dialog"] = tuple(kk_cfg["disconnect_dialog"]["window_size"])

    # War3 配置
    war3_path = CONFIG_DIR / "war3" / "war3.toml"
    if war3_path.exists():
        with open(war3_path, "rb") as f:
            war3 = tomllib.load(f)
        if "war3" in war3:
            sizes["war3"] = tuple(war3["war3"]["client_size"])

    return sizes


# 启动时从配置文件加载
WINDOW_SIZES = load_window_sizes()


def get_window_text(hwnd: int) -> str:
    length = user32.GetWindowTextLengthW(hwnd)
    if length == 0:
        return ""
    buffer = ctypes.create_unicode_buffer(length + 1)
    user32.GetWindowTextW(hwnd, buffer, length + 1)
    return buffer.value


def get_class_name(hwnd: int) -> str:
    buffer = ctypes.create_unicode_buffer(256)
    user32.GetClassNameW(hwnd, buffer, 256)
    return buffer.value


def get_window_parent(hwnd: int) -> int:
    return user32.GetParent(hwnd)


def get_window_rect(hwnd: int) -> tuple:
    rect = wintypes.RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(rect))
    return (rect.left, rect.top, rect.right, rect.bottom)


def is_window_visible(hwnd: int) -> bool:
    return bool(user32.IsWindowVisible(hwnd))


def get_window_pid(hwnd: int) -> int:
    pid = wintypes.DWORD()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    return pid.value


def get_client_size(hwnd: int) -> tuple:
    x1, y1, x2, y2 = get_window_rect(hwnd)
    return (x2 - x1, y2 - y1)


def classify_window(width: int, height: int) -> str:
    """根据配置文件中的窗口尺寸判断窗口类型。"""
    size = (width, height)
    if size == WINDOW_SIZES.get("kk_main"):
        return "KK主界面"
    if size == WINDOW_SIZES.get("kk_room"):
        return "KK房间"
    if size == WINDOW_SIZES.get("create_room_dialog"):
        return "创建房间弹窗"
    if size == WINDOW_SIZES.get("disconnect_dialog"):
        return "掉线重连弹窗"
    if size == WINDOW_SIZES.get("war3"):
        return "War3"
    if width >= 200 and height >= 100:
        return f"其他({width}x{height})"
    return f"Qt内部({width}x{height})"


def enum_all_target_windows():
    """枚举所有 KK 标题窗口和 War3 窗口（含不可见/小尺寸）。"""
    results = []
    enum_proc = ctypes.WINFUNCTYPE(
        wintypes.BOOL,
        wintypes.HWND,
        wintypes.LPARAM,
    )

    def callback(hwnd, _):
        text = get_window_text(hwnd)
        cls = get_class_name(hwnd)
        # 匹配 KK 标题窗口或 War3 窗口
        if "KK" in text or "Warcraft III" in text or cls == "Warcraft III":
            pid = get_window_pid(hwnd)
            visible = is_window_visible(hwnd)
            width, height = get_client_size(hwnd)
            wtype = classify_window(width, height)
            results.append(
                {
                    "hwnd": hwnd,
                    "cls": cls,
                    "text": text,
                    "pid": pid,
                    "visible": visible,
                    "size": (width, height),
                    "type": wtype,
                }
            )
        return True

    proc = enum_proc(callback)
    user32.EnumWindows(proc, 0)
    return results


def main():
    print("=" * 70)
    print("KK 窗口父子关系检测脚本")
    print("=" * 70)
    print()
    print("提示：请在 KK 处于目标状态时运行此脚本：")
    print("  - 主界面状态：只打开 KK 主界面")
    print("  - 创建房间弹窗：在主界面点击创建房间，弹窗出现时运行")
    print("  - 房间状态：进入 KK 房间后运行")
    print("  - War3 状态：进入游戏后运行")
    print("  - 多开状态：打开两个 KK，分别测试上述状态")
    print()

    # 打印从配置文件加载的窗口尺寸
    print("配置文件中的窗口尺寸：")
    for name, size in WINDOW_SIZES.items():
        print(f"  {name}: {size[0]}x{size[1]}")
    print()

    windows = enum_all_target_windows()
    if not windows:
        print("未找到任何 KK 或 War3 窗口。请先启动 KK 平台或 War3。")
        return

    # 按类型分组统计
    type_counts = {}
    for w in windows:
        type_counts.setdefault(w["type"], 0)
        type_counts[w["type"]] += 1

    print(f"共找到 {len(windows)} 个目标窗口：")
    for wtype, count in sorted(type_counts.items()):
        print(f"  {wtype}: {count} 个")

    # 按类型分组显示详情
    print("\n" + "-" * 70)
    print("窗口详情（按类型分组）：")
    print("-" * 70)

    by_type = {}
    for w in windows:
        by_type.setdefault(w["type"], []).append(w)

    for wtype in sorted(by_type.keys()):
        print(f"\n【{wtype}】({len(by_type[wtype])} 个)")
        for w in by_type[wtype]:
            vis = "可见" if w["visible"] else "不可见"
            print(
                f"  句柄={w['hwnd']:08X}, PID={w['pid']}, {vis}, 尺寸={w['size'][0]}x{w['size'][1]}, 类名={w['cls']!r}"
            )

    # 检查所有窗口的父窗口
    print("\n" + "-" * 70)
    print("父子关系检查（GetParent）：")
    print("-" * 70)

    hwnd_set = {w["hwnd"] for w in windows}
    has_any_parent = False

    for w in windows:
        parent = get_window_parent(w["hwnd"])
        if parent:
            has_any_parent = True
            parent_in_set = parent in hwnd_set
            parent_info = f"属于目标窗口({parent:08X})" if parent_in_set else f"非目标窗口({parent:08X})"
            print(f"  {w['type']} 句柄={w['hwnd']:08X} → 父窗口={parent_info}")

    if not has_any_parent:
        print("  所有窗口的 GetParent 均返回 0（顶层窗口），无父子关系。")

    # 检查是否有目标窗口作为其他目标窗口的子窗口（通过 EnumChildWindows）
    print("\n" + "-" * 70)
    print("子窗口检查（EnumChildWindows）：")
    print("-" * 70)

    enum_proc = ctypes.WINFUNCTYPE(
        wintypes.BOOL,
        wintypes.HWND,
        wintypes.LPARAM,
    )
    has_any_child = False

    for w in windows:
        children = []

        def child_callback(child_hwnd, _):
            child_text = get_window_text(child_hwnd)
            child_cls = get_class_name(child_hwnd)
            if "KK" in child_text or "Warcraft III" in child_text or child_cls == "Warcraft III":
                child_size = get_client_size(child_hwnd)
                children.append(
                    {
                        "hwnd": child_hwnd,
                        "cls": child_cls,
                        "text": child_text,
                        "size": child_size,
                    }
                )
            return True

        proc = enum_proc(child_callback)
        user32.EnumChildWindows(w["hwnd"], proc, 0)

        if children:
            has_any_child = True
            print(f"\n  父窗口：{w['type']} 句柄={w['hwnd']:08X} (PID={w['pid']})")
            for c in children:
                print(
                    f"    └─ 子窗口：句柄={c['hwnd']:08X}, 尺寸={c['size'][0]}x{c['size'][1]}, "
                    f"类名={c['cls']!r}, 标题={c['text']!r}"
                )

    if not has_any_child:
        print("  没有任何目标窗口包含目标标题的子窗口。")

    # 结论
    print("\n" + "=" * 70)
    print("结论：")
    if has_any_parent or has_any_child:
        print("  发现窗口之间存在父子关系！")
        print("  - 弹窗（创建房间/掉线等）与其所属的 KK 主界面/房间存在父子关系")
        print("  - 可用于辅助判断弹窗属于哪个 KK 实例")
        print("  - KK 主界面与 KK 房间之间无父子关系（均为独立顶层窗口）")
    else:
        print("  当前状态下窗口之间不存在 Win32 父子关系（均为独立顶层窗口）。")
        print("  请在创建房间弹窗或房间状态下再次运行以检测父子关系。")
    print("=" * 70)


if __name__ == "__main__":
    main()
