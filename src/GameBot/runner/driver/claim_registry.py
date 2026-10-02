"""机器级共享认领注册表 — 多脚本实例间的窗口归属协调。

注册表文件：`%LOCALAPPDATA%\\GameBot\\claim_registry.json`（机器级路径，
同机不同安装目录的实例共享同一文件）。读-改-写全程持命名互斥锁
`Local\\GameBot_Registry`，写盘用临时文件 + `os.replace` 原子替换；
文件损坏/缺失按空注册表处理并告警，不使脚本崩溃。

注册表结构（JSON）::

    {
      "instances": {"<script_pid>": {"player": str, "task": str, "registered_at": float}},
      "kk_owner":  {"<kk_pid>": {"player": str, "start_time": int}},  # FILETIME u64
      "windows":   {"<kind>:<hwnd>": kk_pid}  # kind: war3 / kk_room / kk_hall ...
    }

活性校验：instances 条目读时以 OpenProcess 剪枝死实例；kk_owner 条目以
"进程存活 + 启动时间一致"防 PID 复用错认；windows 条目以 IsWindow +
归属关系复核（war3 复核直接父进程 PID、KK 窗口复核窗口 PID）。

进程/窗口辅助函数（parent_pid / process_start_time / window_pid 等）为
纯 Win32 只读调用，不经过 dm_bridge，可注入替换以便测试。
"""

from __future__ import annotations

import ctypes
import json
import os
import tempfile
import time
from contextlib import contextmanager
from ctypes import wintypes
from pathlib import Path
from typing import Optional

from GameBot.runner.driver.process_lock import NamedMutex
from GameBot.utils import ClaimError, logger

_kernel32 = ctypes.windll.kernel32
_user32 = ctypes.windll.user32

_kernel32.OpenProcess.restype = wintypes.HANDLE
_kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
_kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
_kernel32.GetProcessTimes.argtypes = [
    wintypes.HANDLE,
    wintypes.LPFILETIME,
    wintypes.LPFILETIME,
    wintypes.LPFILETIME,
    wintypes.LPFILETIME,
]
_kernel32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
_kernel32.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
_user32.IsWindow.argtypes = [wintypes.HWND]
_user32.IsWindow.restype = wintypes.BOOL
_user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
_user32.GetWindowThreadProcessId.restype = wintypes.DWORD

PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
TH32CS_SNAPPROCESS = 0x00000002
INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value

REGISTRY_MUTEX_NAME = "Local\\GameBot_Registry"
DEFAULT_LOCK_TIMEOUT_MS = 5000


class PROCESSENTRY32W(ctypes.Structure):
    _fields_ = [
        ("dwSize", wintypes.DWORD),
        ("cntUsage", wintypes.DWORD),
        ("th32ProcessID", wintypes.DWORD),
        ("th32DefaultHeapID", ctypes.c_void_p),
        ("th32ModuleID", wintypes.DWORD),
        ("cntThreads", wintypes.DWORD),
        ("th32ParentProcessID", wintypes.DWORD),
        ("pcPriClassBase", ctypes.c_long),
        ("dwFlags", wintypes.DWORD),
        ("szExeFile", wintypes.WCHAR * 260),
    ]


def default_registry_path() -> str:
    """注册表默认路径：%LOCALAPPDATA%\\GameBot\\claim_registry.json。"""
    base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
    return str(Path(base) / "GameBot" / "claim_registry.json")


def pid_alive(pid: int) -> bool:
    """进程是否存活（OpenProcess + GetExitCodeProcess 探测）。

    OpenProcess 对已终止但仍有句柄引用的僵尸进程对象也会成功，
    须再查退出码：返回 STILL_ACTIVE(259) 才算存活。
    """
    if not pid:
        return False
    handle = _kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, int(pid))
    if not handle:
        return False
    try:
        code = wintypes.DWORD(0)
        if not _kernel32.GetExitCodeProcess(handle, ctypes.byref(code)):
            return False
        return code.value == 259  # STILL_ACTIVE
    finally:
        _kernel32.CloseHandle(handle)


def process_start_time(pid: int) -> int:
    """进程启动时间（GetProcessTimes 创建时间 FILETIME，u64 整数）；失败返回 0。"""
    if not pid:
        return 0
    handle = _kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, int(pid))
    if not handle:
        return 0
    try:
        create, exit_t, kernel_t, user_t = (
            wintypes.FILETIME(),
            wintypes.FILETIME(),
            wintypes.FILETIME(),
            wintypes.FILETIME(),
        )
        if not _kernel32.GetProcessTimes(
            handle, ctypes.byref(create), ctypes.byref(exit_t), ctypes.byref(kernel_t), ctypes.byref(user_t)
        ):
            return 0
        return (create.dwHighDateTime << 32) | create.dwLowDateTime
    finally:
        _kernel32.CloseHandle(handle)


def snapshot_ppid() -> dict:
    """Toolhelp32 进程快照：pid -> ppid。"""
    snap = _kernel32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
    if snap == INVALID_HANDLE_VALUE or not snap:
        return {}
    table = {}
    try:
        entry = PROCESSENTRY32W()
        entry.dwSize = ctypes.sizeof(PROCESSENTRY32W)
        ok = _kernel32.Process32FirstW(snap, ctypes.byref(entry))
        while ok:
            table[int(entry.th32ProcessID)] = int(entry.th32ParentProcessID)
            ok = _kernel32.Process32NextW(snap, ctypes.byref(entry))
    finally:
        _kernel32.CloseHandle(snap)
    return table


def parent_pid(pid: int) -> int:
    """进程的直接父进程 PID（Toolhelp32 快照）；查询失败返回 0。

    多开归属判定必须用直接父进程：war3.exe 是开房 KK 客户端（Platform.exe）
    的直接子进程，各账号客户端由 KK 主实例派生，祖先链包含匹配会错认。
    """
    if not pid:
        return 0
    return snapshot_ppid().get(int(pid), 0)


def window_pid(hwnd: int) -> int:
    """窗口所属进程 PID（GetWindowThreadProcessId）；失败返回 0。"""
    if not hwnd:
        return 0
    pid = wintypes.DWORD(0)
    _user32.GetWindowThreadProcessId(int(hwnd), ctypes.byref(pid))
    return int(pid.value)


def is_window(hwnd: int) -> bool:
    """窗口句柄是否仍有效。"""
    return bool(hwnd) and bool(_user32.IsWindow(int(hwnd)))


def window_owner_pid(kind: str, hwnd: int) -> int:
    """窗口归属的 KK 进程 PID：war3 取窗口进程的直接父 PID，其余取窗口 PID。"""
    pid = window_pid(hwnd)
    if not pid:
        return 0
    return parent_pid(pid) if kind == "war3" else pid


class ClaimRegistry:
    """机器级共享认领注册表。

    所有读-改-写操作在 `Local\\GameBot_Registry` 命名互斥锁内完成；
    文件损坏/缺失视为空注册表并告警，下次写回自愈。
    """

    def __init__(self, path: Optional[str] = None, lock_timeout_ms: int = DEFAULT_LOCK_TIMEOUT_MS):
        self.path = Path(path) if path else Path(default_registry_path())
        self.lock_timeout_ms = int(lock_timeout_ms)

    # ── 底层读写 ──────────────────────────────────────────

    @contextmanager
    def _locked(self):
        mutex = NamedMutex(REGISTRY_MUTEX_NAME)
        if not mutex.acquire(timeout_ms=self.lock_timeout_ms):
            raise ClaimError(f"注册表互斥锁超时（{self.lock_timeout_ms}ms）：{REGISTRY_MUTEX_NAME}")
        try:
            yield
        finally:
            mutex.release()

    @staticmethod
    def _empty() -> dict:
        return {"instances": {}, "kk_owner": {}, "windows": {}}

    def _load(self) -> dict:
        """读取注册表；损坏/缺失按空表处理并告警。"""
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                raise ValueError("注册表根节点非 dict")
        except FileNotFoundError:
            return self._empty()
        except Exception as e:
            logger.warning(f"认领注册表损坏（{self.path}），按空表处理: {e}")
            return self._empty()
        base = self._empty()
        for key in base:
            if isinstance(data.get(key), dict):
                base[key] = data[key]
        return base

    def _save(self, data: dict) -> None:
        """临时文件 + os.replace 原子写。"""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=str(self.path.parent), prefix="claim_registry_", suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False)
            os.replace(tmp, self.path)
        except BaseException:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise

    def _prune(self, data: dict) -> bool:
        """剪枝失效条目（死实例/死 KK 进程/死窗口句柄），返回是否有改动。"""
        changed = False
        for pid_str in [p for p in data["instances"] if not pid_alive(int(p))]:
            del data["instances"][pid_str]
            changed = True
        for pid_str in [p for p in data["kk_owner"] if not pid_alive(int(p))]:
            del data["kk_owner"][pid_str]
            changed = True
        for key in [k for k in data["windows"] if not is_window(int(k.rsplit(":", 1)[1]))]:
            del data["windows"][key]
            changed = True
        return changed

    # ── 实例注册 ──────────────────────────────────────────

    def register_instance(self, player: str = "", task: str = "") -> None:
        """注册本脚本实例；重复非空 target_player 且原实例存活时抛 ClaimError 拒绝。"""
        pid_str = str(os.getpid())
        with self._locked():
            data = self._load()
            self._prune(data)
            if player:
                for other_pid, info in data["instances"].items():
                    if other_pid != pid_str and info.get("player") == player:
                        raise ClaimError(
                            f"玩家 {player} 已被存活脚本实例 pid={other_pid} 注册，拒绝重复启动"
                        )
            data["instances"][pid_str] = {
                "player": player,
                "task": task,
                "registered_at": time.time(),
            }
            self._save(data)
        logger.debug(f"认领注册表实例已登记: pid={pid_str}, player={player or '<无>'}, task={task or '<无>'}")

    def alive_instances(self) -> list:
        """存活实例列表（读时剪枝死实例并写回）。"""
        with self._locked():
            data = self._load()
            if self._prune(data):
                self._save(data)
            return list(data["instances"].values())

    def alive_count(self) -> int:
        """存活实例数（单开快速路径判据）。"""
        return len(self.alive_instances())

    # ── kk_pid → player 归属映射 ──────────────────────────

    def set_kk_owner(self, kk_pid: int, player: str) -> None:
        """写入 kk_pid 归属映射（带进程启动时间戳防 PID 复用错认）。"""
        if not kk_pid or not player:
            return
        start_time = process_start_time(kk_pid)
        with self._locked():
            data = self._load()
            self._prune(data)
            data["kk_owner"][str(kk_pid)] = {"player": player, "start_time": start_time}
            self._save(data)
        logger.info(f"认领注册表 kk_owner 写入: kk_pid={kk_pid} → {player}")

    def player_of_kk_pid(self, kk_pid: int) -> str:
        """查 kk_pid 的归属玩家；条目失效（进程死/启动时间不一致）返回空串。"""
        if not kk_pid:
            return ""
        with self._locked():
            data = self._load()
            entry = data["kk_owner"].get(str(kk_pid))
            if not entry:
                return ""
            player = str(entry.get("player") or "")
            start_time = int(entry.get("start_time") or 0)
            changed = self._validate_kk_entry(data, str(kk_pid), start_time)
            if changed:
                self._save(data)
            if str(kk_pid) not in data["kk_owner"]:
                return ""
            return player

    def kk_pid_of(self, player: str) -> int:
        """查玩家的 KK 进程 PID；无有效映射返回 0。"""
        if not player:
            return 0
        with self._locked():
            data = self._load()
            changed = False
            result = 0
            for pid_str in list(data["kk_owner"]):
                entry = data["kk_owner"].get(pid_str) or {}
                start_time = int(entry.get("start_time") or 0)
                changed |= self._validate_kk_entry(data, pid_str, start_time)
            for pid_str, entry in data["kk_owner"].items():
                if entry.get("player") == player:
                    result = int(pid_str)
                    break
            if changed:
                self._save(data)
            return result

    def _validate_kk_entry(self, data: dict, pid_str: str, start_time: int) -> bool:
        """校验 kk_owner 条目（存活 + 启动时间一致），失效则删除。返回是否改动。"""
        pid = int(pid_str)
        if not pid_alive(pid) or (start_time and process_start_time(pid) != start_time):
            data["kk_owner"].pop(pid_str, None)
            return True
        return False

    # ── 已认领窗口记录 ────────────────────────────────────

    def record_window(self, kind: str, hwnd: int) -> int:
        """登记已认领窗口 `kind:hwnd → kk_pid`（kk_pid 按归属关系现算）。返回 kk_pid。"""
        kk_pid = window_owner_pid(kind, hwnd)
        if not kk_pid:
            return 0
        with self._locked():
            data = self._load()
            data["windows"][f"{kind}:{int(hwnd)}"] = kk_pid
            self._save(data)
        return kk_pid

    def window_kk_pid(self, kind: str, hwnd: int) -> int:
        """读窗口归属 kk_pid；窗口失效或归属复核不一致返回 0 并清条目。"""
        if not hwnd:
            return 0
        key = f"{kind}:{int(hwnd)}"
        with self._locked():
            data = self._load()
            recorded = int(data["windows"].get(key) or 0)
            if not recorded:
                return 0
            if not is_window(hwnd) or window_owner_pid(kind, hwnd) != recorded:
                del data["windows"][key]
                self._save(data)
                return 0
            return recorded

    def release_window(self, kind: str, hwnd: int) -> None:
        """清除已认领窗口记录（局间释放等场景）。"""
        if not hwnd:
            return
        key = f"{kind}:{int(hwnd)}"
        with self._locked():
            data = self._load()
            if key in data["windows"]:
                del data["windows"][key]
                self._save(data)
