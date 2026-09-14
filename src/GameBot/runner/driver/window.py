"""窗口操作 Mixin — 窗口绑定、查找、枚举（基于 _com_call 原语组合）。

含 layered window 强制刷新（取消 WS_EX_LAYERED → RedrawWindow → 恢复），
解决 Qt 5.15.2 layered window 后台输入后画面不刷新的问题。
"""

import ctypes
import ctypes.wintypes
import time
from contextlib import contextmanager
from typing import List, Tuple

from GameBot.utils.exception_handler import DmError
from GameBot.utils.logger import logger

# Windows API 常量（layered window 刷新用）
GWL_EXSTYLE = -20
WS_EX_LAYERED = 0x00080000
RDW_INVALIDATE = 0x0001
RDW_UPDATENOW = 0x0100
RDW_ALLCHILDREN = 0x0080


def scale_client_point(dm, hwnd: int, point, base_size) -> tuple[int, int]:
    """将基准客户区坐标缩放到窗口当前客户区。"""
    x1, y1, x2, y2 = dm.get_client_rect(hwnd)
    width, height = x2 - x1, y2 - y1
    return round(point[0] * width / base_size[0]), round(point[1] * height / base_size[1])


def scale_client_area(dm, hwnd: int, area, base_size) -> list[int]:
    """将基准客户区矩形缩放到窗口当前客户区。"""
    x1, y1, x2, y2 = dm.get_client_rect(hwnd)
    width, height = x2 - x1, y2 - y1
    return [
        round(area[0] * width / base_size[0]),
        round(area[1] * height / base_size[1]),
        round(area[2] * width / base_size[0]),
        round(area[3] * height / base_size[1]),
    ]


class WindowMixin:
    """窗口相关操作：绑定/解绑、查找、枚举（优先调用大漠 COM 接口）。

    依赖子类提供 `_com_call(name, *args)` 原语。
    close_window_by_x 另依赖 `move_to`/`left_click`（InputMixin 提供）。
    get_active_window 另依赖 `save_screenshot`/`save_active_window_screenshot`（ScreenshotMixin 提供）。
    """

    # ---------- 窗口绑定 ----------

    @contextmanager
    def bind_window(
        self,
        hwnd,
        display="normal",
        mouse="normal",
        keypad="normal",
        mode=0,
        bind_cfg=None,
    ):
        """绑定窗口，统一使用 BindWindowEx（兼容 BindWindow 全部功能）。

        :param bind_cfg: 绑定模式配置字典，含 display/mouse/keypad/mode/public/bind_delay，
                         显式传入参数优先级高于 bind_cfg。
        """
        public = ""
        bind_delay = 0.0
        if bind_cfg:
            display = bind_cfg.get("display", display)
            mouse = bind_cfg.get("mouse", mouse)
            keypad = bind_cfg.get("keypad", keypad)
            mode = bind_cfg.get("mode", mode)
            public = bind_cfg.get("public", "")
            bind_delay = bind_cfg.get("bind_delay", 0.0)

        if hwnd == 0:
            raise DmError("未找到游戏窗口，hwnd 为 0")
        # 幂等：已绑定同一窗口时直接复用，不重复调用 BindWindowEx（大漠 COM 不支持重入绑定）。
        # 这样嵌套 bind 同一窗口安全，调用方无需关心是否已在 bind 上下文内。
        if getattr(self, "_current_bind_hwnd", 0) == hwnd:
            yield
            return
        # 统一使用 BindWindowEx
        ret = self._com_call("BindWindowEx", hwnd, display, mouse, keypad, public, mode)
        if ret != 1:
            last_err = self._com_call("GetLastError")
            raise DmError(f"绑定窗口失败，返回值: {ret}，错误码: {last_err}")
        # 绑定后延时等待后台生效（大漠文档建议 1~2 秒）
        if bind_delay > 0:
            time.sleep(bind_delay)
        # 记录当前绑定的窗口句柄，供 WGC 取帧（visual/screenshot）确定目标窗口；
        # _last_bind_hwnd 解绑后仍保留，供绑定外的诊断截图找到最近的绑定目标
        self._current_bind_hwnd = hwnd
        self._last_bind_hwnd = hwnd
        try:
            yield
        finally:
            self._current_bind_hwnd = 0
            try:
                self._com_call("UnBindWindow")
            except Exception as e:
                logger.warning(f"解绑窗口失败: {e}")

    # ---------- 窗口操作（COM 调用） ----------

    def get_bind_window(self) -> int:
        """返回当前绑定窗口句柄，未绑定时返回 0。

        大漠插件 COM 无 GetBindWindow 方法，直接返回 bind_window 上下文内跟踪的句柄。
        """
        return int(getattr(self, "_current_bind_hwnd", 0) or 0)

    def set_client_size(self, hwnd: int, width: int, height: int) -> bool:
        ret = self._com_call("SetClientSize", hwnd, width, height)
        if ret != 1:
            raise DmError(f"设置客户区大小失败，返回值: {ret}")
        return True

    def find_window(self, window_class, window_title) -> int:
        """通过窗口类名、窗口标题查找窗口句柄（模糊匹配），找不到返回 0"""
        return self._com_call("FindWindow", window_class, window_title)

    def get_client_rect(self, hwnd: int) -> Tuple[int, int, int, int]:
        """获取窗口客户区在屏幕上的矩形 (left, top, right, bottom)。

        大漠 GetClientRect(hwnd, x1,y1,x2,y2) 通过 byref 返回客户区屏幕坐标，
        win32com 调用会返回 (ret, x1, y1, x2, y2)；left/top 即客户区原点屏幕坐标。
        注意：bridge 模式下所有 COM 调用在 dm_bridge 子进程主线程串行执行，无线程亲和限制。
        """
        ret, x1, y1, x2, y2 = self._com_call("GetClientRect", hwnd)
        if ret != 1:
            raise DmError(f"获取客户区矩形失败: hwnd={hwnd}, ret={ret}")
        return int(x1), int(y1), int(x2), int(y2)

    def enum_windows(self, window_class, window_title, filter: int = 2) -> List[int]:
        """
        大漠 EnumWindow 原语：按类名/标题模糊枚举，返回句柄列表。

        业务代码请优先使用 find_windows，它会再做类名/标题/PID 精确过滤。

        :param window_class: 窗口类名，模糊匹配，为空则匹配所有
        :param window_title: 窗口标题，模糊匹配，为空则匹配所有
        :param filter: 过滤条件，默认 2（只要求顶级窗口）。
                       不含位 1（可见）：KK 大厅在房间窗口打开时可能被设为不可见，但仍有效。
                       不含位 8（活跃窗口）：KK 创建房间弹窗等非活跃窗口会被误排除。
                       find_windows 之后会精确过滤类名/标题/PID，此处宽松枚举即可。
        :return: 窗口句柄列表
        """
        hwnds_str = self._com_call("EnumWindow", 0, window_title, window_class, filter)

        if not hwnds_str:
            return []
        return [int(h) for h in hwnds_str.split(",") if h]

    def find_windows(
        self,
        window_class: str,
        window_title: str = "",
        owner_pid: int = 0,
    ) -> List[dict]:
        """统一查找窗口：大漠枚举后再按 PID/类名/标题精确过滤。

        大漠 EnumWindow 是模糊匹配，本方法对返回的每个句柄取真实类名、标题、
        所属 PID 和窗口矩形，做精确过滤。多开时传入 owner_pid 即可把窗口限定
        到指定进程。

        :param window_class: 精确窗口类名（非空）
        :param window_title: 精确窗口标题，为空时不按标题过滤
        :param owner_pid: 目标进程 PID，>0 时只返回该进程的窗口
        :return: [{"hwnd", "title", "class", "rect"}] 列表，rect 为屏幕坐标 (l,t,r,b)
        """
        if not window_class:
            return []
        results = []
        for hwnd in self.enum_windows(window_class, window_title):
            # 大漠 EnumWindow 的"可见"过滤（filter 位 1）不可靠，部分不可见窗口仍被枚举。
            # 用 Windows API IsWindowVisible 二次过滤，排除不可见窗口（如已关闭但未销毁的 KK 窗口）。
            if not self.is_window_visible(hwnd):
                continue
            try:
                actual_class = self.get_window_class(hwnd)
            except Exception:
                continue
            if actual_class != window_class:
                continue
            try:
                actual_title = self.get_window_title(hwnd)
            except Exception:
                actual_title = ""
            if window_title and actual_title != window_title:
                continue
            if owner_pid and self.get_window_process_id(hwnd) != owner_pid:
                continue
            try:
                rect = self.get_window_rect(hwnd)
            except Exception:
                rect = (0, 0, 0, 0)
            results.append(
                {
                    "hwnd": hwnd,
                    "title": actual_title,
                    "class": actual_class,
                    "rect": rect,
                }
            )
        return results

    def close_window_by_x(self, hwnd: int, offset_x: int = 15, offset_y: int = 15) -> bool:
        """点击窗口右上角 X 关闭按钮。

        通过绑定目标窗口并移动鼠标到客户区右上角偏移位置实现，
        适用于 KK 弹窗等独立顶层窗口。

        :param hwnd: 待关闭窗口句柄
        :param offset_x: 距右侧边界偏移（像素）
        :param offset_y: 距上侧边界偏移（像素）
        :return: 是否成功点击
        """
        if not hwnd:
            return False
        try:
            x1, y1, x2, y2 = self.get_client_rect(hwnd)
        except DmError as e:
            logger.warning(f"获取弹窗客户区失败，无法点击 X: {e}")
            return False

        client_w = x2 - x1
        click_x = client_w - offset_x
        click_y = offset_y
        if click_x < 0 or click_y < 0:
            logger.warning(f"X 按钮计算坐标为负，窗口太小: w={client_w}, offset=({offset_x},{offset_y})")
            return False

        try:
            with self.bind_window(hwnd):
                self.move_to(click_x, click_y)
                time.sleep(0.1)
                self.left_click()
                time.sleep(0.1)
            return True
        except (DmError, OSError) as e:
            logger.warning(f"点击 X 关闭窗口失败: {e}")
            return False

    def get_active_window(self, window_class: str = "", window_title: str = "", capture: bool = True) -> int:
        """
        获取当前正在操作的魔兽窗口句柄
        :param window_class: 窗口类名，模糊匹配，为空则匹配所有
        :param window_title: 窗口标题，模糊匹配，为空则匹配所有
        :param capture: 未找到预期窗口时是否截图（用于调试非预想流程）
        :return: 窗口句柄
        """
        active_hwnd = self.get_foreground_window()
        if active_hwnd == 0:
            logger.warning(f"没有获取到激活的窗口class={window_class}, title={window_title}")
            if capture:
                self.save_screenshot(label="no_active_window")
            return 0
        hwnds = self.enum_windows(window_class, window_title)
        # 验证该窗口是否属于预期窗口
        if active_hwnd in hwnds:
            return active_hwnd
        logger.warning(f"当前活动窗口不是class={window_class}, title={window_title}，请切换到该窗口后再运行脚本")
        if capture:
            safe_title = self._safe_filename(window_title or "unknown")
            safe_class = self._safe_filename(window_class or "unknown")
            self.save_active_window_screenshot(label=f"unexpected_active_window_{safe_class}_{safe_title}")
        return 0

    # ---------- 窗口状态（调用大漠 COM） ----------

    def get_window_rect(self, hwnd: int) -> Tuple[int, int, int, int]:
        """获取窗口整体在屏幕上的矩形 (left, top, right, bottom)。"""
        if not hwnd:
            return 0, 0, 0, 0
        result = self._com_call("GetWindowRect", hwnd)
        if result is None:
            return 0, 0, 0, 0
        # 大漠 GetWindowRect 可能返回 "l|t|r|b" 字符串或 (l, t, r, b) tuple
        if isinstance(result, (tuple, list)):
            if len(result) == 4:
                return tuple(int(p) for p in result)
            return 0, 0, 0, 0
        # 字符串格式 "l|t|r|b"
        parts = [p for p in str(result).split("|") if p]
        if len(parts) == 4:
            return tuple(int(p) for p in parts)
        return 0, 0, 0, 0

    def get_screen_rect(self) -> Tuple[int, int, int, int]:
        """获取主屏幕矩形（不含 DPI 缩放）。"""
        try:
            w = int(self._com_call("GetScreenWidth") or 0)
            h = int(self._com_call("GetScreenHeight") or 0)
            return 0, 0, w, h
        except Exception:
            return 0, 0, 0, 0

    def get_foreground_window(self) -> int:
        """获取当前用户正在操作的活动窗口句柄"""
        try:
            return int(self._com_call("GetForegroundWindow") or 0)
        except Exception:
            return 0

    def is_window_visible(self, hwnd: int) -> bool:
        """窗口是否可见。"""
        if not hwnd:
            return False
        try:
            return bool(self._com_call("GetWindowState", hwnd, 2))
        except Exception:
            return False

    @staticmethod
    def _safe_filename(name: str) -> str:
        """将窗口类名/标题转换为安全文件名片段。"""
        return "".join(c if c.isalnum() or c in "-_" else "_" for c in name)[:50]

    def get_window_parent(self, hwnd: int) -> int:
        """获取窗口的父/属主窗口句柄（大漠 GetWindow flag=0），无父窗口返回 0。"""
        if not hwnd:
            return 0
        try:
            return int(self._com_call("GetWindow", hwnd, 0) or 0)
        except Exception:
            return 0

    def is_window_minimized(self, hwnd: int) -> bool:
        """判断窗口是否最小化（大漠 GetWindowState flag=3）。

        :param hwnd: 窗口句柄
        :return: True=最小化，False=非最小化或句柄无效
        """
        if not hwnd:
            return False
        try:
            return bool(self._com_call("GetWindowState", hwnd, 3))
        except Exception:
            return False

    def get_window_state(self, hwnd: int, flag: int) -> bool:
        """获取窗口指定状态（大漠 GetWindowState），满足条件返回 True。

        常用 flag：
          - 0: 窗口是否存在
          - 1: 是否处于激活
          - 2: 是否可见
          - 3: 是否最小化
          - 4: 是否最大化
        """
        if not hwnd:
            return False
        try:
            return bool(self._com_call("GetWindowState", hwnd, flag))
        except Exception:
            return False

    def set_window_state(self, hwnd: int, flag: int) -> bool:
        """调用大漠 SetWindowState 改变窗口显示状态。

        常用 flag：
          - 5: 恢复/显示窗口但不激活，适合多开后台截图
          - 7: 显示窗口
          - 12: 恢复并激活窗口
          - 0: 关闭窗口

        :param hwnd: 窗口句柄
        :param flag: 大漠 SetWindowState 标志
        :return: 是否成功调用
        """
        if not hwnd:
            return False
        try:
            return bool(self._com_call("SetWindowState", hwnd, flag))
        except Exception:
            return False

    def get_window_process_id(self, hwnd: int) -> int:
        """获取窗口所属进程 ID（大漠 GetWindowProcessId），失败返回 0。"""
        if not hwnd:
            return 0
        try:
            return int(self._com_call("GetWindowProcessId", hwnd) or 0)
        except Exception:
            return 0

    def get_process_info(self, pid: int) -> str:
        """获取进程详细信息（大漠 GetProcessInfo），失败返回空字符串。

        成功时返回格式："进程名|进程路径|CPU占用率|内存占用量"。
        """
        if not pid:
            return ""
        try:
            return str(self._com_call("GetProcessInfo", pid) or "")
        except Exception:
            return ""

    def get_window_class(self, hwnd: int) -> str:
        """获取窗口类名（大漠 GetWindowClass）。"""
        if not hwnd:
            return ""
        return self._com_call("GetWindowClass", hwnd)

    def get_window_title(self, hwnd: int) -> str:
        """获取窗口标题（大漠 GetWindowTitle）。"""
        if not hwnd:
            return ""
        return self._com_call("GetWindowTitle", hwnd)

    # ---------- Layered window 刷新 ----------

    @staticmethod
    def is_layered_window(hwnd: int) -> bool:
        """检查窗口是否带 WS_EX_LAYERED 扩展样式。"""
        if not hwnd:
            return False
        try:
            user32 = ctypes.windll.user32
            ex_style = user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
            return bool(ex_style & WS_EX_LAYERED)
        except Exception:
            return False

    @staticmethod
    def force_refresh_layered(hwnd: int, wait: float = 0.8) -> bool:
        """对 layered window 执行强制刷新，解决后台输入/点击后画面不更新的问题。

        KK 的 Qt 5.15.2 弹窗是 WS_EX_LAYERED 窗口，渲染走 UpdateLayeredWindow，
        RedrawWindow(WM_PAINT) 对它无效。临时取消 layered 属性后 RedrawWindow
        能触发 Qt 正常重绘并 flush 到 DWM 合成表面，恢复 layered 后再 RedrawWindow
        一次确保内容完整，避免黑边或残留旧画面。

        :param hwnd: 目标窗口句柄
        :param wait: 取消 layered 后等待 Qt 重绘的时间（秒）
        :return: 是否成功执行刷新流程
        """
        if not hwnd:
            return False
        try:
            user32 = ctypes.windll.user32
            user32.RedrawWindow.argtypes = [
                ctypes.wintypes.HWND,
                ctypes.c_void_p,
                ctypes.c_void_p,
                ctypes.wintypes.UINT,
            ]
            original_style = user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
            if not (original_style & WS_EX_LAYERED):
                # 非 layered 窗口直接 RedrawWindow
                user32.RedrawWindow(hwnd, 0, 0, RDW_INVALIDATE | RDW_UPDATENOW | RDW_ALLCHILDREN)
                return True
            # 取消 layered → RedrawWindow → 等待 Qt 重绘 → 恢复 layered → 等待 DWM 合成
            user32.SetWindowLongW(hwnd, GWL_EXSTYLE, original_style & ~WS_EX_LAYERED)
            user32.RedrawWindow(hwnd, 0, 0, RDW_INVALIDATE | RDW_UPDATENOW | RDW_ALLCHILDREN)
            time.sleep(wait)
            user32.SetWindowLongW(hwnd, GWL_EXSTYLE, original_style)
            # 恢复 layered 后等待 DWM 自动合成，不再调 RedrawWindow（对 layered 窗口无效）
            time.sleep(0.2)
            logger.debug(f"force_refresh_layered: hwnd={hwnd} 刷新完成")
            return True
        except Exception as e:
            logger.warning(f"force_refresh_layered 失败: hwnd={hwnd}, {e}")
            return False
