"""OCR 文字监测 — 从 war3.py 拆分。

包含 War3Business 的文字识别 mixin 和独立的 TextMonitor 常驻监测类。

截图统一走 WGC（runner/driver/wgc_capture.py），不经大漠：大漠 dx2 Capture 与 dx 系
鼠标注入共用游戏进程内钩子，每次截图都会撕开注入锁并卡游戏一帧。
截图失败抛 CaptureError 终止任务，不回退其他截图方式。
"""

import threading
import time
from typing import Callable, Dict, List, Optional

from GameBot.inference.client import get_inference_client
from GameBot.runner.driver.wgc_capture import WgcCapture
from GameBot.utils import logger
from GameBot.utils.exception_handler import CaptureError


class WatchEvent(threading.Event):
    """start_text_watcher 返回的事件：监测线程出错时记录在 error，stop_text_watcher 时抛出。"""

    def __init__(self):
        super().__init__()
        self.error: Optional[BaseException] = None


class TextMonitorMixin:
    """War3Business 的 OCR 文字识别 mixin。

    提供 OCR 区域识别、文字等待、后台文字监测等能力。
    依赖 self.war3_cfg（dict）；截图走 WGC，不依赖 self.dm。
    """

    _wgc_sessions: Dict[int, WgcCapture]

    def _wgc(self, hwnd: int) -> WgcCapture:
        """获取 hwnd 的 WGC 截图会话（首次 acquire 后缓存，release_wgc 时释放）。"""
        sessions = self.__dict__.setdefault("_wgc_sessions", {})
        cap = sessions.get(hwnd)
        if cap is None:
            interval_ms = int(self.war3_cfg.get("wgc_min_interval_ms", 100))
            cap = WgcCapture.acquire(hwnd, min_interval_ms=interval_ms)
            sessions[hwnd] = cap
        return cap

    def release_wgc(self):
        """释放本对象持有的全部 WGC 会话（任务结束时调用）。"""
        sessions = self.__dict__.pop("_wgc_sessions", {})
        for cap in sessions.values():
            cap.release()

    @staticmethod
    def _normalize_ocr(text: str) -> str:
        """规范化 OCR 返回的文字：合并换行、统一全角/半角标点。"""
        if not text:
            return ""
        text = text.replace("\n", "").replace("\r", "")
        # 常见全角→半角映射（OCR 常把全角标点识别为半角）
        replacements = str.maketrans(
            {
                "：": ":",
                "，": ",",
                "。": ".",
                "！": "!",
                "？": "?",
                "（": "(",
                "）": ")",
                "；": ";",
                "＂": '"',
            }
        )
        return text.translate(replacements)

    def _ocr_region_text(self, ocr_cfg: dict, hwnd: int = None) -> str:
        """OCR 指定区域（客户区坐标 area_coords），返回原始识别文字（未规范化）。

        WGC 取帧 → 裁剪 → RapidOCR。不经大漠、不需要绑定上下文，可在任意线程调用。
        截图失败抛 CaptureError。
        """
        if hwnd is None:
            hwnd = self._find_war3_hwnd()
        if not hwnd:
            raise CaptureError("未找到 war3 窗口，无法 OCR")
        img = self._wgc(hwnd).grab_client(tuple(ocr_cfg["area_coords"]))
        return get_inference_client(load_chest=False, load_combat=False).ocr_from_array(img)

    def wait_for_text(
        self,
        ocr_cfg: dict,
        expected_text: str,
        timeout: int = 8,
        interval: float = 0.5,
        stop_event: Optional[threading.Event] = None,
    ) -> bool:
        start = time.time()
        normalized_expected = self._normalize_ocr(expected_text)
        # 循环检测屏幕区域（子进程检测），直到出现预期文字或超时
        while time.time() - start < timeout:
            if stop_event is not None and stop_event.is_set():
                return False
            try:
                result = self._ocr_region_text(ocr_cfg)
            except CaptureError:
                raise
            except Exception as e:
                logger.debug(f"wait_for_text 识别异常: {e}")
                result = ""
            if result and normalized_expected in self._normalize_ocr(result):
                logger.info(f"检测到提示: {result}")
                return True
            if stop_event is not None:
                if stop_event.wait(timeout=interval):
                    return False
            else:
                time.sleep(interval)
        logger.warning(f"等待提示超时: {expected_text}")
        return False

    def wait_for_any_text(
        self,
        ocr_cfg: dict,
        expected_texts: List[str],
        timeout: int = 8,
        interval: float = 0.5,
        stop_event: Optional[threading.Event] = None,
    ) -> Optional[str]:
        """轮询 OCR 区域，返回首个匹配到的预期文字（expected_texts 中的原样字符串）；超时返回 None。

        适用于结果二选一（如升级圣痕的"成功"/"失败"）的场景。
        """
        start = time.time()
        normalized = [self._normalize_ocr(t) for t in expected_texts]
        while time.time() - start < timeout:
            if stop_event is not None and stop_event.is_set():
                return None
            try:
                result = self._ocr_region_text(ocr_cfg)
            except CaptureError:
                raise
            except Exception as e:
                logger.debug(f"wait_for_any_text 识别异常: {e}")
                result = ""
            norm = self._normalize_ocr(result)
            if norm:
                for raw, want in zip(expected_texts, normalized):
                    if want in norm:
                        logger.info(f"检测到提示: {result}")
                        return raw
            if stop_event is not None:
                if stop_event.wait(timeout=interval):
                    return None
            else:
                time.sleep(interval)
        logger.warning(f"等待提示超时: {expected_texts}")
        return None

    # ── 后台 OCR 文字监测 ─────────────────────────────────

    def start_text_watcher(self, ocr_cfg: dict, expected_text: str, interval: float = 1.0, hwnd: int = None) -> WatchEvent:
        """启动后台线程持续 OCR 监测指定文字，检测到后设置返回的 Event。

        子线程走 WGC 取帧 + OCR，不碰大漠。截图出错时线程退出并把异常记在
        event.error，由 stop_text_watcher 抛出。

        :param ocr_cfg: OCR 配置（仅使用 area_coords；color/sim 在 RapidOCR 下忽略）
        :param expected_text: 期待出现的文字
        :param interval: 检测间隔（秒）
        :param hwnd: 目标窗口句柄（不传则用 find_window 查找）
        :return: WatchEvent，检测到文字时被设置
        """
        event = WatchEvent()
        if hwnd is None:
            hwnd = self._find_war3_hwnd()
        if not hwnd:
            raise CaptureError("后台 OCR 线程：未找到 war3 窗口")
        # 会话在主线程建好（首帧等待、偏移计算在此完成），子线程只取帧
        self._wgc(hwnd)
        _expected = self._normalize_ocr(expected_text)

        def _loop():
            while not event.is_set():
                try:
                    result = self._normalize_ocr(self._ocr_region_text(ocr_cfg, hwnd))
                except Exception as e:
                    logger.error(f"文字监测线程截图/识别失败，线程退出: {e}")
                    event.error = e
                    return
                if result and _expected in result:
                    event.set()
                    return
                time.sleep(interval)

        t = threading.Thread(target=_loop, daemon=True, name="TextWatcher")
        t.start()
        return event

    def stop_text_watcher(self, event: threading.Event):
        """停止文字监测并释放 WGC 会话；监测线程曾出错时在此抛出该异常。"""
        event.set()
        self.release_wgc()
        err = getattr(event, "error", None)
        if err is not None:
            raise err


class TextMonitor:
    """持续后台 OCR 监测固定屏幕区域，整段脚本运行期间常驻不重启。

    解决两类需求：
    1) 整个脚本运行过程中都需要监测（不再像 start_text_watcher 那样每段路线起停一次）。
    2) 检测更快：后台线程以较小间隔持续 OCR，文字一出现下一周期即可捕获，避免
       主线程阻塞轮询的 sleep 死区。

    子线程走 WGC 取帧 + OCR，不碰大漠，与主线程的大漠输入互不干扰。

    错误处理：截图/识别抛异常时线程退出并记录在 error；之后任何 watch/wait_for/
    wait_for_any/latest 调用立即抛出该异常，同时调用 on_error 回调（任务侧用它
    set stop_event，让行走中的主线程尽快中断）。不静默重试。

    用法：
      monitor = TextMonitor(war3, ocr_cfg, interval=0.2, on_error=stop_event.set)
      monitor.start(hwnd)
      ...
      evt = monitor.watch("已完成")   # 注册一次性触发，出现即 set（供行走中断 stop_event）
      ... monitor.wait_for("已领取", timeout=8) / monitor.wait_for_any(["成功","失败"], 8)
      monitor.unwatch(evt)
      ...
      monitor.stop()
    """

    def __init__(
        self,
        war3: "TextMonitorMixin",
        ocr_cfg: dict,
        interval: float = 0.2,
        on_error: Optional[Callable[[BaseException], None]] = None,
    ):
        self._war3 = war3
        self._ocr_cfg = ocr_cfg
        self._interval = interval
        self._on_error = on_error
        self._latest = ""  # 最新识别文本（规范化后）
        self._lock = threading.Lock()
        self._watchers = []  # [(normalized_expected, event)]
        self._stop = threading.Event()
        self._thread = None
        self._hwnd = None
        self.error: Optional[BaseException] = None

    def start(self, hwnd: int = None):
        """启动后台监测线程（已运行则跳过）。WGC 会话建不起来直接抛 CaptureError。"""
        if self._thread is not None and self._thread.is_alive():
            return
        if hwnd is None:
            hwnd = self._war3._find_war3_hwnd()
        if not hwnd:
            raise CaptureError("TextMonitor：未找到 war3 窗口")
        # 会话在主线程建好（首帧等待、偏移计算在此完成并直接报错），子线程只取帧
        self._war3._wgc(hwnd)
        self._hwnd = hwnd
        self.error = None
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, daemon=True, name="TextMonitor")
        self._thread.start()
        logger.info(f"文字监测线程已启动，area_coords={self._ocr_cfg.get('area_coords')}，间隔 {self._interval}s")

    def _loop(self):
        while not self._stop.is_set():
            try:
                text = self._war3._ocr_region_text(self._ocr_cfg, self._hwnd)
            except Exception as e:
                logger.error(f"文字监测线程截图/识别失败，线程退出: {e}")
                self.error = e
                if self._on_error is not None:
                    self._on_error(e)
                return
            norm = self._war3._normalize_ocr(text)
            with self._lock:
                self._latest = norm
                # 检查所有已注册的一次性触发
                for expected, event in self._watchers:
                    if expected and not event.is_set() and expected in norm:
                        event.set()
            # 可中断睡眠：stop() 时立即唤醒退出
            self._stop.wait(self._interval)

    def _raise_if_error(self):
        if self.error is not None:
            raise self.error

    @property
    def latest(self) -> str:
        self._raise_if_error()
        with self._lock:
            return self._latest

    def watch(self, expected: str) -> threading.Event:
        """注册一次性监测：当 expected 出现时设置返回的 Event（用完需 unwatch）。"""
        self._raise_if_error()
        event = threading.Event()
        with self._lock:
            self._watchers.append((self._war3._normalize_ocr(expected), event))
        return event

    def unwatch(self, event: threading.Event):
        """注销 watch 返回的 Event。"""
        with self._lock:
            self._watchers = [(e, ev) for (e, ev) in self._watchers if ev is not event]

    def wait_for(self, expected: str, timeout: int = 8, interval: float = 0.1) -> bool:
        """阻塞等待最新文本中出现 expected，命中返回 True，超时返回 False。"""
        norm = self._war3._normalize_ocr(expected)
        start = time.time()
        while time.time() - start < timeout:
            if norm and norm in self.latest:
                # logger.info(f"检测到提示: {self.latest}")
                return True
            time.sleep(interval)
        # 超时时输出最近识别到的文字，用于调试
        latest = self.latest
        if latest:
            logger.warning(f"等待提示超时: {expected}，最近OCR识别: [{latest}]")
        else:
            logger.warning(f"等待提示超时: {expected}，未识别到任何文字（OCR可能失败或区域为空）")
        return False

    def wait_for_any(self, expected_texts: List[str], timeout: int = 8, interval: float = 0.1) -> Optional[str]:
        """阻塞等待最新文本中出现任一预期文字，返回命中的原样字符串，超时返回 None。"""
        norms = [self._war3._normalize_ocr(t) for t in expected_texts]
        start = time.time()
        while time.time() - start < timeout:
            latest = self.latest
            for raw, want in zip(expected_texts, norms):
                if want and want in latest:
                    logger.info(f"检测到提示: {latest}")
                    return raw
            time.sleep(interval)
        logger.warning(f"等待提示超时: {expected_texts}")
        return None

    def stop(self):
        """停止后台监测线程并释放 WGC 会话；监测线程曾出错时在此抛出该异常。"""
        self._stop.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2)
        self._thread = None
        with self._lock:
            self._watchers.clear()
        self._war3.release_wgc()
        logger.info("文字监测线程已停止")
        self._raise_if_error()
