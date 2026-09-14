"""进程级命名互斥锁 — 多脚本场景下的资源认领原语。

基于 Windows Named Mutex（CreateMutexW + WaitForSingleObject(0) 非阻塞获取），
句柄持有到进程退出（崩溃也自动释放）。用于：
- war3 多开窗口认领（Local\\\\GameBot_War3_{hwnd}）
- KK 大厅 PID 识别串行化（Local\\\\GameBot_KK_Hall_Identify_PID_{pid}）
"""

import ctypes
from ctypes import wintypes
from typing import Optional

_kernel32 = ctypes.windll.kernel32
_kernel32.CreateMutexW.restype = wintypes.HANDLE
_kernel32.CreateMutexW.argtypes = [ctypes.c_void_p, wintypes.BOOL, wintypes.LPCWSTR]
_kernel32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
_kernel32.ReleaseMutex.argtypes = [wintypes.HANDLE]
_kernel32.CloseHandle.argtypes = [wintypes.HANDLE]

WAIT_OBJECT_0 = 0x0
WAIT_ABANDONED = 0x80
WAIT_TIMEOUT = 0x102


class NamedMutex:
    """Windows 命名互斥锁，非阻塞 try_acquire 语义。

    获取成功后锁一直持有（直到显式 release 或进程退出），
    用于认领"本进程独占"的资源（如某个 war3 窗口句柄）。
    """

    def __init__(self, name: str):
        self._name = name
        self._handle: Optional[int] = None

    def try_acquire(self) -> bool:
        """非阻塞尝试获取锁。成功返回 True（锁持续持有），被占用返回 False。"""
        return self.acquire(timeout_ms=0)

    def acquire(self, timeout_ms: int = 0xFFFFFFFF) -> bool:
        """获取锁（默认无限阻塞，传入 timeout_ms 限时等待）。

        成功返回 True（锁持续持有直到 release/进程退出），超时返回 False。
        """
        if self._handle is not None:
            return True  # 已持有，幂等
        handle = _kernel32.CreateMutexW(None, False, self._name)
        if not handle:
            raise OSError(f"创建命名互斥锁失败: {self._name}")
        result = _kernel32.WaitForSingleObject(handle, timeout_ms)
        if result in (WAIT_OBJECT_0, WAIT_ABANDONED):
            self._handle = handle
            return True
        _kernel32.CloseHandle(handle)
        return False

    def release(self):
        """释放锁（如未持有则无操作）。"""
        if self._handle is not None:
            _kernel32.ReleaseMutex(self._handle)
            _kernel32.CloseHandle(self._handle)
            self._handle = None

    @property
    def held(self) -> bool:
        return self._handle is not None

    def __enter__(self) -> "NamedMutex":
        if not self.try_acquire():
            raise RuntimeError(f"命名互斥锁已被占用: {self._name}")
        return self

    def __exit__(self, *exc):
        self.release()
        return False

    def __del__(self):
        self.release()
