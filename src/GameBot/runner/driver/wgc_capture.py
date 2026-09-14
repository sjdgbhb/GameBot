"""WGC 窗口截图 — 基于 Windows Graphics Capture（windows-capture 库）。

从 DWM 合成面按 hwnd 取窗口帧，完全不进游戏进程、不碰大漠钩子；窗口被遮挡、
在屏幕外都能拿到当前帧（不能最小化）。用于替代大漠 dx2 Capture：后者与 dx 系鼠标
注入共用游戏进程内钩子，每次截图都会撕开注入锁并卡游戏一帧。

设计原则（见 docs/change_logs/war3后台开发记录.md）：
- 项目截图只有 WGC 一种实现，不做多后端抽象
- 任何失败（会话未启动 / 窗口关闭 / 帧流停止 / 裁剪越界）直接抛 CaptureError 终止任务，
  不返回 None、不静默重试、不回退其他截图方式
- 同一 hwnd 多处使用共用一个会话（引用计数），用 acquire()/release() 管理
- bbox 统一为客户区坐标，与 OCR 配置 area_coords 一致

用法：
    cap = WgcCapture.acquire(hwnd, min_interval_ms=200)
    try:
        img = cap.grab_client((x1, y1, x2, y2))   # BGRA ndarray
    finally:
        cap.release()
"""

import atexit
import ctypes
import threading
import time
from ctypes import wintypes
from typing import Dict, Optional, Tuple

import numpy as np

from GameBot.utils.exception_handler import CaptureError
from GameBot.utils.logger import logger

# DwmGetWindowAttribute：不含 Win10 隐形边框的窗口实际可见矩形
DWMWA_EXTENDED_FRAME_BOUNDS = 9

_user32 = ctypes.windll.user32
_dwmapi = ctypes.windll.dwmapi
_user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
_user32.GetWindowRect.restype = wintypes.BOOL
_user32.ClientToScreen.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.POINT)]
_user32.ClientToScreen.restype = wintypes.BOOL
_user32.GetClientRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
_user32.GetClientRect.restype = wintypes.BOOL
_user32.IsWindow.argtypes = [wintypes.HWND]
_user32.IsWindow.restype = wintypes.BOOL
_user32.IsIconic.argtypes = [wintypes.HWND]
_user32.IsIconic.restype = wintypes.BOOL
_dwmapi.DwmGetWindowAttribute.argtypes = [wintypes.HWND, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD]
_dwmapi.DwmGetWindowAttribute.restype = ctypes.c_long


def _window_rect(hwnd: int) -> Tuple[int, int, int, int]:
    rc = wintypes.RECT()
    if not _user32.GetWindowRect(hwnd, ctypes.byref(rc)):
        raise CaptureError(f"GetWindowRect 失败: hwnd={hwnd}")
    return rc.left, rc.top, rc.right, rc.bottom


def _extended_frame_rect(hwnd: int) -> Optional[Tuple[int, int, int, int]]:
    rc = wintypes.RECT()
    hr = _dwmapi.DwmGetWindowAttribute(hwnd, DWMWA_EXTENDED_FRAME_BOUNDS, ctypes.byref(rc), ctypes.sizeof(rc))
    if hr != 0:
        return None
    return rc.left, rc.top, rc.right, rc.bottom


def _client_origin(hwnd: int) -> Tuple[int, int]:
    pt = wintypes.POINT(0, 0)
    if not _user32.ClientToScreen(hwnd, ctypes.byref(pt)):
        raise CaptureError(f"ClientToScreen 失败: hwnd={hwnd}")
    return pt.x, pt.y


def _client_size(hwnd: int) -> Tuple[int, int]:
    rc = wintypes.RECT()
    if not _user32.GetClientRect(hwnd, ctypes.byref(rc)):
        raise CaptureError(f"GetClientRect 失败: hwnd={hwnd}")
    return rc.right, rc.bottom


class WgcCapture:
    """单个窗口的 WGC 常驻截图会话。

    收帧在 windows-capture 自己的线程；on_frame_arrived 只把最新帧拷一份存起来，
    grab_* 在调用方线程取帧、裁剪，OCR/推理由调用方处理。
    """

    FIRST_FRAME_TIMEOUT = 5.0  # 启动后等首帧的上限（秒）
    CLOSE_TIMEOUT = 3.0  # close() 等收帧线程退出的上限（秒）

    _sessions: Dict[int, "WgcCapture"] = {}
    _sessions_lock = threading.Lock()

    # ── 会话获取 / 释放（引用计数） ──────────────────────

    @classmethod
    def acquire(cls, hwnd: int, min_interval_ms: Optional[int] = None, stale_timeout: Optional[float] = None) -> "WgcCapture":
        """获取 hwnd 对应的会话；首次调用创建并启动，之后复用并增加引用计数。"""
        with cls._sessions_lock:
            cap = cls._sessions.get(hwnd)
            if cap is not None and not cap._closed:
                cap._refs += 1
                return cap
            cap = cls(hwnd, min_interval_ms=min_interval_ms, stale_timeout=stale_timeout)
            cap.start()
            cap._refs = 1
            cls._sessions[hwnd] = cap
            return cap

    @classmethod
    def for_hwnd(cls, hwnd: int, min_interval_ms: Optional[int] = None) -> "WgcCapture":
        """取 hwnd 的常驻会话（进程生命周期），不需 release。

        供 find_pic / ocr / save_screenshot 等"一次性"调用使用：会话创建后常驻，
        进程退出时由 atexit 统一关闭；窗口关闭后再次调用会自动重建。
        """
        if not hwnd:
            raise CaptureError("无有效窗口句柄，无法建立 WGC 会话")
        with cls._sessions_lock:
            cap = cls._sessions.get(hwnd)
            if cap is not None and not cap._closed:
                return cap
            cap = cls(hwnd, min_interval_ms=min_interval_ms)
            cap.start()
            cap._refs = 1  # 常驻引用，不会被 release 到 0
            cls._sessions[hwnd] = cap
            return cap

    def release(self):
        """释放一次引用；引用归零时关闭会话。"""
        with type(self)._sessions_lock:
            self._refs -= 1
            if self._refs > 0:
                return
            type(self)._sessions.pop(self._hwnd, None)
        self.close()

    @classmethod
    def _close_all(cls):
        with cls._sessions_lock:
            caps = list(cls._sessions.values())
            cls._sessions.clear()
        for cap in caps:
            cap.close()

    # ── 生命周期 ─────────────────────────────────────────

    def __init__(self, hwnd: int, min_interval_ms: Optional[int] = None, stale_timeout: Optional[float] = None):
        """
        :param hwnd: 目标窗口句柄（必须用 find_game_window 找到的 hwnd，多开时不能按标题选窗）
        :param min_interval_ms: 请求 WGC 的最小出帧间隔（毫秒），None 用系统默认（随合成器帧率）
        :param stale_timeout: 最新帧超过该秒数未更新视为帧流停止（最小化/锁屏），None 时取 max(2×间隔, 2s)
        """
        if not hwnd or not _user32.IsWindow(hwnd):
            raise CaptureError(f"无效窗口句柄: {hwnd}")
        self._hwnd = int(hwnd)
        self._min_interval_ms = min_interval_ms
        interval_s = (min_interval_ms or 0) / 1000.0
        self._stale_timeout = stale_timeout if stale_timeout is not None else max(2 * interval_s, 2.0)
        self._refs = 0
        self._lock = threading.Lock()
        self._latest: Optional[np.ndarray] = None  # BGRA 整窗帧（已拷贝）
        self._latest_ts = 0.0
        self._first_frame = threading.Event()
        self._closed = False
        self._started = False
        self._capture = None
        self._control = None
        self._callback_error: Optional[BaseException] = None
        # 客户区在帧内的偏移与尺寸缓存，按帧尺寸失效
        self._offset_cache: Optional[Tuple[Tuple[int, int], Tuple[int, int], Tuple[int, int]]] = None

    def start(self):
        """启动 WGC 会话并等待首帧，失败抛 CaptureError。"""
        if self._started:
            return
        if _user32.IsIconic(self._hwnd):
            raise CaptureError(f"窗口已最小化，WGC 无法取帧: hwnd={self._hwnd}")
        try:
            from windows_capture import WindowsCapture
        except ImportError as e:
            raise CaptureError(f"windows-capture 未安装或加载失败（需 Win10 1903+，仅主环境）: {e}") from e

        capture = WindowsCapture(
            cursor_capture=False,
            draw_border=False,
            minimum_update_interval=self._min_interval_ms,
            window_hwnd=self._hwnd,
        )
        capture.frame_handler = self._on_frame_arrived
        capture.closed_handler = self._on_closed
        try:
            self._control = capture.start_free_threaded()
        except Exception as e:
            raise CaptureError(f"WGC 会话启动失败: hwnd={self._hwnd}, {e}") from e
        self._capture = capture
        self._started = True
        if not self._first_frame.wait(self.FIRST_FRAME_TIMEOUT):
            self.close()
            raise CaptureError(
                f"WGC 启动后 {self.FIRST_FRAME_TIMEOUT}s 未收到首帧: hwnd={self._hwnd}"
                f"（窗口是否最小化 / 系统是否 Win10 1903+ / 会话是否锁屏）"
            )
        if self._callback_error is not None:
            self.close()
            raise CaptureError(f"WGC 首帧处理异常: {self._callback_error}") from self._callback_error
        logger.info(f"WGC 截图会话已启动: hwnd={self._hwnd}, interval={self._min_interval_ms}ms")

    def close(self):
        """停止收帧线程并释放资源。超时只记 error（资源问题，不影响业务判定）。"""
        if self._closed:
            return
        self._closed = True
        control = self._control
        self._control = None
        if control is None:
            return
        done = threading.Event()

        def _stop():
            try:
                control.stop()
                control.wait()
            except Exception as e:
                logger.warning(f"WGC 会话停止异常: hwnd={self._hwnd}, {e}")
            finally:
                done.set()

        threading.Thread(target=_stop, daemon=True, name="WgcCaptureStop").start()
        if not done.wait(self.CLOSE_TIMEOUT):
            logger.error(f"WGC 会话停止超时 {self.CLOSE_TIMEOUT}s: hwnd={self._hwnd}")
        else:
            logger.info(f"WGC 截图会话已关闭: hwnd={self._hwnd}")

    # ── 回调（windows-capture 线程） ─────────────────────

    def _on_frame_arrived(self, frame, capture_control):
        try:
            # frame_buffer 是原生映射内存的零拷贝视图，回调返回后失效，必须拷贝
            data = np.array(frame.frame_buffer, copy=True)
            with self._lock:
                self._latest = data
                self._latest_ts = time.monotonic()
            self._first_frame.set()
        except Exception as e:
            # 回调线程异常带回调用方线程（latest_frame 抛出），并停止收帧
            self._callback_error = e
            self._first_frame.set()
            capture_control.stop()
            return
        if self._closed:
            capture_control.stop()

    def _on_closed(self):
        logger.warning(f"WGC 目标窗口已关闭: hwnd={self._hwnd}")
        self._closed = True

    # ── 取帧 ─────────────────────────────────────────────

    @property
    def hwnd(self) -> int:
        return self._hwnd

    def latest_frame(self) -> np.ndarray:
        """返回最新整窗帧（BGRA，含边框/标题栏），失败抛 CaptureError。"""
        if not self._started:
            raise CaptureError(f"WGC 会话未启动: hwnd={self._hwnd}")
        if self._closed:
            raise CaptureError(f"WGC 会话已关闭（窗口关闭或已释放）: hwnd={self._hwnd}")
        if self._callback_error is not None:
            raise CaptureError(f"WGC 收帧回调异常: {self._callback_error}") from self._callback_error
        with self._lock:
            frame, ts = self._latest, self._latest_ts
        if frame is None:
            raise CaptureError(f"WGC 尚无帧: hwnd={self._hwnd}")
        age = time.monotonic() - ts
        if age > self._stale_timeout:
            raise CaptureError(
                f"WGC 帧流已停止 {age:.1f}s（阈值 {self._stale_timeout:.1f}s）: hwnd={self._hwnd}"
                f"，窗口可能已最小化 / 会话锁屏 / RDP 断开"
            )
        return frame

    def grab_window(self) -> np.ndarray:
        """整窗帧的副本（BGRA）。"""
        return self.latest_frame().copy()

    def grab_client(self, bbox: Tuple[int, int, int, int]) -> np.ndarray:
        """按客户区坐标 bbox=(x1,y1,x2,y2) 裁剪最新帧，返回 BGRA ndarray 副本。"""
        frame = self.latest_frame()
        (ox, oy), (cw, ch) = self._client_offset(frame)
        x1, y1, x2, y2 = (int(v) for v in bbox)
        if not (0 <= x1 < x2 <= cw and 0 <= y1 < y2 <= ch):
            raise CaptureError(f"bbox 超出客户区: bbox={bbox}, client={cw}x{ch}, hwnd={self._hwnd}")
        return frame[oy + y1 : oy + y2, ox + x1 : ox + x2].copy()

    def grab_client_rgb(self, bbox: Tuple[int, int, int, int]) -> np.ndarray:
        """同 grab_client，返回 RGB 三通道 ndarray（供找图/找色/推理用）。"""
        return self.grab_client(bbox)[:, :, [2, 1, 0]]

    def client_size(self) -> Tuple[int, int]:
        """当前帧客户区尺寸 (w, h)。"""
        frame = self.latest_frame()
        _, (cw, ch) = self._client_offset(frame)
        return cw, ch

    def save(self, path: str, bbox: Optional[Tuple[int, int, int, int]] = None):
        """把最新帧（或客户区 bbox 区域）存为图片文件，供调试目测。"""
        from PIL import Image

        img = self.grab_client(bbox) if bbox else self.grab_window()
        Image.fromarray(img[:, :, [2, 1, 0]]).save(path)

    def _client_offset(self, frame: np.ndarray) -> Tuple[Tuple[int, int], Tuple[int, int]]:
        """客户区左上角在帧内的偏移与客户区尺寸，按帧尺寸缓存。

        WGC 帧对应窗口的 DWM 可见矩形。Win10 有隐形调整边框的窗口，
        GetWindowRect 会多出边框而 DWMWA_EXTENDED_FRAME_BOUNDS 不含；两者哪个
        与帧尺寸一致就用哪个，都不一致说明窗口尺寸已变或状态异常，直接报错。
        """
        fh, fw = frame.shape[:2]
        cache = self._offset_cache
        if cache is not None and cache[0] == (fw, fh):
            return cache[1], cache[2]

        cx, cy = _client_origin(self._hwnd)
        cw, ch = _client_size(self._hwnd)
        candidates = [("extended_frame", _extended_frame_rect(self._hwnd)), ("window_rect", _window_rect(self._hwnd))]
        for name, rect in candidates:
            if rect is None:
                continue
            left, top, right, bottom = rect
            if (right - left, bottom - top) == (fw, fh):
                ox, oy = cx - left, cy - top
                if ox < 0 or oy < 0 or ox + cw > fw or oy + ch > fh:
                    raise CaptureError(
                        f"客户区超出帧范围: offset=({ox},{oy}), client={cw}x{ch}, frame={fw}x{fh}, hwnd={self._hwnd}"
                    )
                logger.debug(f"WGC 客户区偏移: {name} offset=({ox},{oy}) client={cw}x{ch} frame={fw}x{fh}")
                self._offset_cache = ((fw, fh), (ox, oy), (cw, ch))
                return (ox, oy), (cw, ch)
        raise CaptureError(
            f"WGC 帧尺寸 {fw}x{fh} 与窗口矩形不一致（extended={candidates[0][1]}, window={candidates[1][1]}），"
            f"hwnd={self._hwnd}"
        )


atexit.register(WgcCapture._close_all)
