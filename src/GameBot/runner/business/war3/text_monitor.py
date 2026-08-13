"""OCR 文字监测 — 从 war3.py 拆分。

包含 War3Business 的文字识别 mixin 和独立的 TextMonitor 常驻监测类。
"""
import threading
import time
from typing import List, Optional

from GameBot.inference import get_ocr_client
from GameBot.utils import logger


class TextMonitorMixin:
    """War3Business 的 OCR 文字识别 mixin。

    提供 OCR 区域识别、文字等待、后台文字监测等能力。
    依赖 self.dm（DmClient）和 self.war3_cfg（dict）。
    """

    @staticmethod
    def _normalize_ocr(text: str) -> str:
        """规范化 OCR 返回的文字：合并换行、统一全角/半角标点。"""
        if not text:
            return ""
        text = text.replace("\n", "").replace("\r", "")
        # 常见全角→半角映射（OCR 常把全角标点识别为半角）
        replacements = str.maketrans({
            "：": ":", "，": ",", "。": ".", "！": "!", "？": "?",
            "（": "(", "）": ")", "；": ";", "＂": '"',
        })
        return text.translate(replacements)

    def _compute_ocr_bbox(self, ocr_cfg: dict, hwnd: int):
        """用大漠把客户区坐标 area_coords 换算成屏幕 bbox（主线程调用）。

        大漠 GetClientRect 返回客户区在屏幕上的矩形，其 left/top 即客户区原点屏幕坐标，
        加上 area_coords 偏移即为屏幕 bbox，交给 OCR 子进程截屏。
        """
        cx, cy, _, _ = self.dm.get_client_rect(hwnd)
        x1, y1, x2, y2 = ocr_cfg["area_coords"]
        return (cx + x1, cy + y1, cx + x2, cy + y2)

    def _ocr_region_text(self, ocr_cfg: dict, hwnd: int = None) -> str:
        """OCR 指定区域，返回原始识别文字（未规范化）。

        主线程用大漠算出屏幕 bbox，交给 OCR 子进程截屏识别（子进程不碰窗口、
        不依赖大漠）。
        """
        if hwnd is None:
            hwnd = self._find_war3_hwnd()
        if not hwnd:
            raise RuntimeError("未找到 war3 窗口，无法计算 OCR 区域")
        bbox = self._compute_ocr_bbox(ocr_cfg, hwnd)
        return get_ocr_client().ocr_screen(bbox)

    def wait_for_text(self, ocr_cfg: dict, expected_text: str, timeout: int = 8, interval: float = 0.5, stop_event: Optional[threading.Event] = None) -> bool:
        start = time.time()
        normalized_expected = self._normalize_ocr(expected_text)
        # 循环检测屏幕区域（子进程检测），直到出现预期文字或超时
        while time.time() - start < timeout:
            if stop_event is not None and stop_event.is_set():
                return False
            try:
                result = self._ocr_region_text(ocr_cfg)
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

    def wait_for_any_text(self, ocr_cfg: dict, expected_texts: List[str],
                          timeout: int = 8, interval: float = 0.5, stop_event: Optional[threading.Event] = None) -> Optional[str]:
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

    def start_text_watcher(self, ocr_cfg: dict, expected_text: str,
                           interval: float = 1.0,
                           hwnd: int = None) -> threading.Event:
        """启动后台线程持续 OCR 监测指定文字，检测到后设置返回的 Event。

        屏幕 bbox 在主线程用大漠算好（大漠 COM 线程亲和，子线程不能用），
        子线程只把这个固定 bbox 转发给 OCR 子进程截屏识别。子线程既不碰大漠
        也不碰 win32gui。war3 在自动化期间窗口位置不动，算一次即可。

        :param ocr_cfg: OCR 配置（仅使用 area_coords；color/sim 在 RapidOCR 下忽略）
        :param expected_text: 期待出现的文字
        :param interval: 检测间隔（秒）
        :param hwnd: 目标窗口句柄（不传则用大漠 find_window 查找）
        :return: threading.Event，检测到文字时被设置
        """
        event = threading.Event()

        # 主线程：用大漠算好屏幕 bbox（子线程不能调大漠）
        if hwnd is None:
            hwnd = self._find_war3_hwnd()
        if not hwnd:
            logger.warning("后台 OCR 线程：未找到 war3 窗口")
            return event
        _bbox = self._compute_ocr_bbox(ocr_cfg, hwnd)
        _expected = self._normalize_ocr(expected_text)

        def _loop():
            # 预热 OCR 子进程（首次启动 + 模型加载较慢，放线程内避免阻塞主线程）
            try:
                _client = get_ocr_client()
            except Exception as e:
                logger.error(f"OCR 子进程启动失败: {e}")
                return

            while not event.is_set():
                try:
                    result = self._normalize_ocr(_client.ocr_screen(_bbox))
                    # 每周期打印识别结果（截断），便于排查"完成已发生但迟迟未检测到"的延迟：
                    # 若结果为空说明目标文字不在 bbox 内（多为滚动日志带子位置问题）。
                    logger.debug(f"OCR 监测: {result[:80]!r}")
                    if result and _expected in result:
                        logger.info(f"检测到文字: {result}")
                        event.set()
                        return
                except Exception as e:
                    logger.debug(f"文字监测线程异常: {e}")
                time.sleep(interval)

        t = threading.Thread(target=_loop, daemon=True, name="TextWatcher")
        t.start()
        logger.info(f"文字监测线程已启动，等待: {expected_text}")
        return event

    @staticmethod
    def stop_text_watcher(event: threading.Event):
        """停止文字监测。"""
        event.set()
        logger.info("文字监测线程已停止")


class TextMonitor:
    """持续后台 OCR 监测固定屏幕区域，整段脚本运行期间常驻不重启。

    解决两类需求：
    1) 整个脚本运行过程中都需要监测（不再像 start_text_watcher 那样每段路线起停一次）。
    2) 检测更快：后台线程以较小间隔持续 OCR，文字一出现下一周期即可捕获，避免
       主线程阻塞轮询的 sleep 死区。

    屏幕 bbox 在主线程用大漠算好（大漠 COM 线程亲和，子线程不能调），子线程只把
    固定 bbox 转发给 OCR 子进程截屏识别。

    用法：
      monitor = TextMonitor(war3, ocr_cfg, interval=0.2)
      monitor.start(hwnd)
      ...
      evt = monitor.watch("已完成")   # 注册一次性触发，出现即 set（供行走中断 stop_event）
      ... monitor.wait_for("已领取", timeout=8) / monitor.wait_for_any(["成功","失败"], 8)
      monitor.unwatch(evt)
      ...
      monitor.stop()
    """

    def __init__(self, war3: "TextMonitorMixin", ocr_cfg: dict, interval: float = 0.2):
        self._war3 = war3
        self._ocr_cfg = ocr_cfg
        self._interval = interval
        self._latest = ""                      # 最新识别文本（规范化后）
        self._lock = threading.Lock()
        self._watchers = []                    # [(normalized_expected, event)]
        self._stop = threading.Event()
        self._thread = None
        self._bbox = None

    def start(self, hwnd: int = None):
        """启动后台监测线程（已运行则跳过）。"""
        if self._thread is not None and self._thread.is_alive():
            return
        if hwnd is None:
            hwnd = self._war3._find_war3_hwnd()
        if not hwnd:
            logger.warning("TextMonitor：未找到 war3 窗口，不启动监测")
            return
        self._bbox = self._war3._compute_ocr_bbox(self._ocr_cfg, hwnd)
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, daemon=True, name="TextMonitor")
        self._thread.start()
        logger.info(f"文字监测线程已启动（持续），bbox={self._bbox}，间隔 {self._interval}s")

    def _loop(self):
        # 预热 OCR 子进程（首次启动 + 模型加载较慢，放线程内不阻塞主线程）
        try:
            client = get_ocr_client()
        except Exception as e:
            logger.error(f"TextMonitor OCR 子进程启动失败: {e}")
            return
        while not self._stop.is_set():
            try:
                text = client.ocr_screen(self._bbox)
                norm = self._war3._normalize_ocr(text)
                with self._lock:
                    self._latest = norm
                    # 检查所有已注册的一次性触发
                    for expected, event in self._watchers:
                        if expected and not event.is_set() and expected in norm:
                            event.set()
                            # logger.info(f"检测到文字: {norm}")
            except Exception as e:
                logger.debug(f"TextMonitor 异常: {e}")
            # 可中断睡眠：stop() 时立即唤醒退出
            self._stop.wait(self._interval)

    @property
    def latest(self) -> str:
        with self._lock:
            return self._latest

    def watch(self, expected: str) -> threading.Event:
        """注册一次性监测：当 expected 出现时设置返回的 Event（用完需 unwatch）。"""
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

    def wait_for_any(self, expected_texts: List[str], timeout: int = 8,
                     interval: float = 0.1) -> Optional[str]:
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
        """停止后台监测线程。"""
        self._stop.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2)
        self._thread = None
        with self._lock:
            self._watchers.clear()
        logger.info("文字监测线程已停止")
