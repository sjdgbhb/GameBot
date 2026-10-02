"""实机验证：KK 房间窗口与 war3 窗口之间的进程/窗口关系。

用法（KK 房间已启动 war3 后运行，纯只读检测，对游戏零干扰）：
    uv run python tests/manual/test_kk_war3_relation.py
    uv run python tests/manual/test_kk_war3_relation.py --delay 3

输出：
1. 全部 KK 类窗口（Qt5152QWindowIcon/Qt5152QWindow/Qt5152QWindowPopupSaveBits）
   与 war3 窗口的 hwnd、PID、TID、标题、尺寸、可见性、parent/owner/root 句柄。
2. 每个目标窗口所在进程的完整祖先链（Toolhelp32 快照还原 ppid 链），
   判断 war3.exe 是否为 KK 进程的后代、或反之。
3. 窗口层关系判定：war3 窗口的 GetParent/GW_OWNER/GetAncestor 是否指向
   KK 侧任一窗口句柄。
"""

from __future__ import annotations

import argparse
import ctypes
import ctypes.wintypes
import sys
import time

from GameBot.config import config
from GameBot.utils import logger, setup_log_file

user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32

user32.GetParent.restype = ctypes.c_void_p
user32.GetWindow.restype = ctypes.c_void_p
user32.GetAncestor.restype = ctypes.c_void_p
user32.GetWindowLongPtrW.restype = ctypes.c_ssize_t

GW_OWNER = 4
GA_PARENT = 1
GA_ROOT = 2
GA_ROOTOWNER = 3
GWL_HWNDPARENT = -8
GWLP_HWNDPARENT = -8

PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
TH32CS_SNAPPROCESS = 0x00000002


class PROCESSENTRY32W(ctypes.Structure):
    _fields_ = [
        ("dwSize", ctypes.wintypes.DWORD),
        ("cntUsage", ctypes.wintypes.DWORD),
        ("th32ProcessID", ctypes.wintypes.DWORD),
        ("th32DefaultHeapID", ctypes.c_void_p),
        ("th32ModuleID", ctypes.wintypes.DWORD),
        ("cntThreads", ctypes.wintypes.DWORD),
        ("th32ParentProcessID", ctypes.wintypes.DWORD),
        ("pcPriClassBase", ctypes.c_long),
        ("dwFlags", ctypes.wintypes.DWORD),
        ("szExeFile", ctypes.wintypes.WCHAR * 260),
    ]


def get_window_props(hwnd: int) -> dict:
    """取窗口关键属性：标题/类名/矩形/PID/TID/父窗口/属主/根窗口。"""
    title_buf = ctypes.create_unicode_buffer(512)
    user32.GetWindowTextW(hwnd, title_buf, 512)
    cls_buf = ctypes.create_unicode_buffer(256)
    user32.GetClassNameW(hwnd, cls_buf, 256)

    rect = ctypes.wintypes.RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(rect))

    pid = ctypes.c_ulong()
    tid = user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))

    return {
        "hwnd": int(hwnd),
        "title": title_buf.value,
        "class": cls_buf.value,
        "visible": bool(user32.IsWindowVisible(hwnd)),
        "rect": (int(rect.left), int(rect.top), int(rect.right), int(rect.bottom)),
        "pid": int(pid.value),
        "tid": int(tid),
        "parent": int(user32.GetParent(hwnd) or 0),
        "owner": int(user32.GetWindow(hwnd, GW_OWNER) or 0),
        "hwndparent": int(user32.GetWindowLongPtrW(hwnd, GWLP_HWNDPARENT) or 0),
        "root": int(user32.GetAncestor(hwnd, GA_ROOT) or 0),
        "rootowner": int(user32.GetAncestor(hwnd, GA_ROOTOWNER) or 0),
    }


def enum_top_windows() -> list:
    """枚举全部顶层窗口（含不可见，KK 大厅进房间后可能被置为不可见）。"""
    results = []
    EnumWindowsProc = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)

    def cb(hwnd, _lparam):
        results.append(get_window_props(int(hwnd)))
        return True

    user32.EnumWindows(EnumWindowsProc(cb), 0)
    return results


def snapshot_processes() -> dict:
    """Toolhelp32 进程快照：pid -> {"ppid": int, "exe": str}。"""
    snap = kernel32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
    if snap == ctypes.c_void_p(-1).value:
        raise RuntimeError("CreateToolhelp32Snapshot 失败")
    table = {}
    try:
        entry = PROCESSENTRY32W()
        entry.dwSize = ctypes.sizeof(PROCESSENTRY32W)
        ok = kernel32.Process32FirstW(snap, ctypes.byref(entry))
        while ok:
            table[int(entry.th32ProcessID)] = {
                "ppid": int(entry.th32ParentProcessID),
                "exe": entry.szExeFile,
            }
            ok = kernel32.Process32NextW(snap, ctypes.byref(entry))
    finally:
        kernel32.CloseHandle(snap)
    return table


def process_image_path(pid: int) -> str:
    """取进程可执行文件完整路径（权限不足时返回空串）。"""
    h = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not h:
        return ""
    try:
        buf = ctypes.create_unicode_buffer(1024)
        size = ctypes.wintypes.DWORD(1024)
        if kernel32.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(size)):
            return buf.value
        return ""
    finally:
        kernel32.CloseHandle(h)


def ancestor_chain(pid: int, proc_table: dict) -> list:
    """沿 ppid 向上走完整祖先链 [(pid, exe), ...]，防环截断。"""
    chain = []
    seen = set()
    cur = pid
    while cur and cur not in seen:
        seen.add(cur)
        info = proc_table.get(cur)
        if not info:
            chain.append((cur, "<已退出或不可见>"))
            break
        chain.append((cur, info["exe"]))
        cur = info["ppid"]
    return chain


def fmt_chain(chain: list) -> str:
    return " <- ".join(f"{exe}(pid={pid})" for pid, exe in chain)


def main() -> int:
    parser = argparse.ArgumentParser(description="KK 房间窗口与 war3 窗口关系诊断")
    parser.add_argument("--delay", type=int, default=3, help="启动前等待秒数")
    parser.add_argument("--wait", type=int, default=0, help="等待 war3 窗口出现的超时秒数（0=不等待）")
    args = parser.parse_args()

    setup_log_file("KK与war3窗口关系诊断")
    logger.info("=" * 80)
    logger.info("KK 房间窗口 / war3 窗口 进程与窗口关系诊断（只读）")
    logger.info("=" * 80)

    for i in range(args.delay, 0, -1):
        logger.info(f"{i} 秒后开始...")
        time.sleep(1)

    kk_cfg = config.load_task("kk").get("kk", {})
    war3_cfg = config.load_task("war3").get("war3", {})

    kk_classes = {
        kk_cfg.get("window_class", "Qt5152QWindowIcon"),
        kk_cfg.get("create_room_window_class", "Qt5152QWindow"),
        kk_cfg.get("dropdown_window_class", "Qt5152QWindowPopupSaveBits"),
    }
    war3_class = war3_cfg.get("window_class", "Warcraft III")
    logger.info(f"KK 类名集合: {sorted(kk_classes)}, war3 类名: {war3_class!r}")

    def dump_window(w: dict, tag: str):
        logger.info(
            f"  [{tag}] hwnd={w['hwnd']}, pid={w['pid']}, tid={w['tid']}, "
            f"class={w['class']!r}, title={w['title']!r}, visible={w['visible']}, rect={w['rect']}"
        )
        logger.info(
            f"       parent={w['parent']}, owner(GW_OWNER)={w['owner']}, "
            f"hwndparent={w['hwndparent']}, root={w['root']}, rootowner={w['rootowner']}"
        )

    def scan():
        wins = enum_top_windows()
        return wins, [w for w in wins if w["class"] in kk_classes], [w for w in wins if w["class"] == war3_class]

    # ── 基线快照（war3 启动前）──
    windows, kk_wins, war3_wins = scan()
    baseline_kk = {w["hwnd"]: w for w in kk_wins}
    logger.info(f"\n── 基线快照：KK 类窗口 {len(kk_wins)} 个，war3 {len(war3_wins)} 个 ──")
    for w in kk_wins:
        dump_window(w, "KK基线")

    if args.wait > 0:
        start = time.time()
        while not war3_wins and time.time() - start < args.wait:
            time.sleep(0.5)
            windows, kk_wins, war3_wins = scan()
        if war3_wins:
            logger.info(f"\n等待 {time.time() - start:.1f}s 后检测到 war3 窗口（可能仍在加载页）")

    hwnd_map = {w["hwnd"]: w for w in windows}

    logger.info(f"\n── 终态：顶层窗口 {len(windows)} 个：KK 类 {len(kk_wins)} 个，war3 {len(war3_wins)} 个 ──")

    # 基线对比：KK 窗口在 war3 出现前后是否被移动/隐藏/销毁/新增
    cur_kk = {w["hwnd"]: w for w in kk_wins}
    for hwnd, cur in cur_kk.items():
        old = baseline_kk.get(hwnd)
        if old is None:
            logger.info(f"[变化] 新增 KK 窗口 hwnd={hwnd}, pid={cur['pid']}, rect={cur['rect']}, visible={cur['visible']}")
        elif old["rect"] != cur["rect"] or old["visible"] != cur["visible"]:
            logger.info(
                f"[变化] KK 窗口 hwnd={hwnd}, pid={cur['pid']}: "
                f"rect {old['rect']} -> {cur['rect']}, visible {old['visible']} -> {cur['visible']}"
            )
    for hwnd, old in baseline_kk.items():
        if hwnd not in cur_kk:
            logger.info(f"[变化] KK 窗口 hwnd={hwnd} 已销毁/不可枚举")

    if not kk_wins:
        logger.error("未发现任何 KK 类窗口，请先打开 KK 并进入房间")
    if not war3_wins:
        logger.error("未发现 war3 窗口，请先从 KK 房间启动游戏")
    if not kk_wins or not war3_wins:
        return 1

    logger.info("\n── KK 类窗口明细（终态）──")
    for w in kk_wins:
        dump_window(w, "KK")
    logger.info("\n── war3 窗口明细 ──")
    for w in war3_wins:
        dump_window(w, "war3")

    # ── 进程祖先链 ──
    proc_table = snapshot_processes()
    kk_pids = {w["pid"] for w in kk_wins}
    war3_pids = {w["pid"] for w in war3_wins}

    logger.info("\n── KK 进程祖先链 ──")
    kk_chains = {}
    for pid in sorted(kk_pids):
        chain = ancestor_chain(pid, proc_table)
        kk_chains[pid] = chain
        logger.info(f"  pid={pid} exe={process_image_path(pid) or proc_table.get(pid, {}).get('exe', '?')}")
        logger.info(f"    链: {fmt_chain(chain)}")

    logger.info("\n── war3 进程祖先链 ──")
    war3_chains = {}
    for pid in sorted(war3_pids):
        chain = ancestor_chain(pid, proc_table)
        war3_chains[pid] = chain
        logger.info(f"  pid={pid} exe={process_image_path(pid) or proc_table.get(pid, {}).get('exe', '?')}")
        logger.info(f"    链: {fmt_chain(chain)}")

    # ── 关系判定 ──
    logger.info("\n" + "=" * 80)
    logger.info("关系判定")
    logger.info("=" * 80)

    # 1) 进程树：war3 pid 祖先链是否经过 KK 窗口所属 pid
    for wpid, chain in war3_chains.items():
        hits = [p for p, _exe in chain[1:] if p in kk_pids]
        if hits:
            logger.info(f"[进程] war3(pid={wpid}) 是 KK 进程 {hits} 的后代")
        else:
            names = [exe for _p, exe in chain]
            logger.info(f"[进程] war3(pid={wpid}) 祖先链不含 KK 窗口进程 {sorted(kk_pids)}，链上 exe: {names}")
    for kpid, chain in kk_chains.items():
        hits = [p for p, _exe in chain[1:] if p in war3_pids]
        if hits:
            logger.info(f"[进程] KK(pid={kpid}) 是 war3 进程 {hits} 的后代（异常，理论上不应出现）")

    # 2) 窗口树：war3/KK 窗口的 parent/owner/rootowner 是否指向对方 hwnd
    kk_hwnds = {w["hwnd"] for w in kk_wins}
    war3_hwnds = {w["hwnd"] for w in war3_wins}
    found_link = False
    for w in war3_wins:
        for field in ("parent", "owner", "hwndparent", "root", "rootowner"):
            if w[field] in kk_hwnds:
                logger.info(f"[窗口] war3 hwnd={w['hwnd']} 的 {field} 指向 KK 窗口 hwnd={w[field]}"
                            f"（{hwnd_map[w[field]]['title']!r}）")
                found_link = True
    for w in kk_wins:
        for field in ("parent", "owner", "hwndparent", "root", "rootowner"):
            if w[field] in war3_hwnds:
                logger.info(f"[窗口] KK hwnd={w['hwnd']} 的 {field} 指向 war3 窗口 hwnd={w[field]}")
                found_link = True
    if not found_link:
        logger.info("[窗口] 两侧窗口的 parent/owner/rootowner 互不相指——无窗口层隶属关系")

    # 3) 共享同一线程/消息队列（同一 tid 才共享输入队列）
    kk_tids = {w["tid"] for w in kk_wins}
    shared = [w for w in war3_wins if w["tid"] in kk_tids]
    if shared:
        logger.warning(f"[线程] war3 窗口 {[w['hwnd'] for w in shared]} 与 KK 共享线程 TID（异常）")
    else:
        logger.info("[线程] war3 与 KK 窗口分属不同线程，无共享输入队列")

    logger.complete()
    return 0


if __name__ == "__main__":
    sys.exit(main())
