"""视觉操作 Mixin — 找图找色、截图、OCR（基于 _com_call 原语组合）。

含 PrintWindow + PW_RENDERFULLCONTENT 截图，用于 WS_EX_LAYERED 窗口
（KK 的 Qt 5.15.2 弹窗），大漠 gdi2/dx2 对 layered window 截图无效。
"""

import ctypes
import ctypes.wintypes
import os
import tempfile
import time
import uuid
from typing import Tuple

from GameBot.runner.resource_manager import res_mgr
from GameBot.utils.logger import logger

# PrintWindow 标志
PW_CLIENTONLY = 0x00000001
PW_RENDERFULLCONTENT = 0x00000002
PW_CLIENT_FULL = PW_CLIENTONLY | PW_RENDERFULLCONTENT  # 0x3


class VisualMixin:
    """视觉相关操作：找图、找色、截图、OCR。

    依赖子类提供 `_com_call(name, *args)` 原语。
    """

    def find_pic(self, x1, y1, x2, y2, pic_name, sim=0.9, delta_color="000000", dir=0) -> Tuple[int, int, int]:
        """找图，返回 (是否找到, x, y)"""
        pic_path = res_mgr.get_image_path(pic_name)
        # 直接调用，不传入输出参数
        result = self._com_call("FindPic", x1, y1, x2, y2, pic_path, delta_color, sim, dir)
        return result

    def click_pic(self, pic_name, x1=0, y1=0, x2=1920, y2=1080, delta_color="000000", sim=0.9, offset_x=0, offset_y=0):
        """点击图片中心（偏移后）"""
        is_found, x, y = self.find_pic(x1, y1, x2, y2, pic_name, delta_color, sim)
        if not is_found:
            return False
        click_x = x + offset_x
        click_y = y + offset_y
        self._com_call("MoveTo", click_x, click_y)
        self._com_call("LeftClick")
        logger.info(f"点击图片: {pic_name} 坐标({click_x},{click_y})")
        return True

    def find_pics(self, x1, y1, x2, y2, pic_names, delta_color="000000", sim=0.9, dir=0):
        """
        使用大漠 FindPicEx 查找多个图片。
        Args:
            pic_names: 多个图片名用 "|" 分隔
        Returns:
            List[Tuple[int, int, int]]：[(index, x, y), ...]，空则返回 []
        """
        pic_paths = "|".join(str(res_mgr.get_image_path(pic_name)) for pic_name in pic_names.split("|"))
        result = self._com_call("FindPicEx", x1, y1, x2, y2, pic_paths, delta_color, sim, dir)
        if not result:
            return []

        matches = []
        for item in result.split("|"):
            parts = item.split(",")
            if len(parts) != 3:
                continue
            index, x, y = parts
            matches.append((int(index), int(x), int(y)))
        return matches

    def find_color(self, x1, y1, x2, y2, color="ff0000-000000", sim=0.9, dir=0) -> Tuple[int, int, int]:
        """找色，返回 (是否找到, x, y)"""
        result = self._com_call("FindColor", x1, y1, x2, y2, color, sim, dir)
        return result

    def get_color(self, x: int, y: int) -> str:
        """获取指定像素颜色（十六进制字符串，如 'ff0000'）"""
        return self._com_call("GetColor", x, y)

    def capture_region(self, x1, y1, x2, y2, filepath: str) -> bool:
        """截取屏幕区域到文件，返回是否成功。

        对 WS_EX_LAYERED 窗口（KK 的 Qt 弹窗）自动使用 PrintWindow + PW_RENDERFULLCONTENT，
        因为大漠 gdi2/dx2 对 layered window 截图无效（全黑或旧画面）。
        需在窗口绑定上下文内调用。
        """
        hwnd = getattr(self, "_current_bind_hwnd", 0)
        if hwnd and self.is_layered_window(hwnd):
            return self.capture_region_printwindow(hwnd, x1, y1, x2, y2, filepath)
        ret = self._com_call("Capture", x1, y1, x2, y2, filepath)
        return ret == 1

    def capture_region_printwindow(
        self, hwnd: int, x1: int, y1: int, x2: int, y2: int, filepath: str
    ) -> bool:
        """使用 PrintWindow + PW_RENDERFULLCONTENT 截取 layered window 区域。

        对 WS_EX_LAYERED 窗口，PrintWindow + PW_RENDERFULLCONTENT 能从 DWM
        合成表面抓取当前完整内容，不依赖窗口 DC（layered window 的窗口 DC 无内容）。

        :param hwnd: 目标窗口句柄
        :param x1,y1,x2,y2: 客户区坐标
        :param filepath: 输出 BMP 文件路径
        :return: 是否成功
        """
        try:
            user32 = ctypes.windll.user32
            gdi32 = ctypes.windll.gdi32

            # 大漠 bind_window (dx2) 会 hook 窗口 GDI 调用，导致 PrintWindow 抓到黑屏。
            # 对 layered window，需要临时解绑后再 PrintWindow，然后重新绑定。
            was_bound = getattr(self, "_current_bind_hwnd", 0)
            bind_params = getattr(self, "_current_bind_params", None)
            if was_bound:
                try:
                    self._com_call("UnBindWindow")
                except Exception:
                    pass

            # 设置 argtypes/restype，避免 64 位系统上句柄溢出
            user32.GetDC.argtypes = [ctypes.wintypes.HWND]
            user32.GetDC.restype = ctypes.wintypes.HDC
            user32.ReleaseDC.argtypes = [ctypes.wintypes.HWND, ctypes.wintypes.HDC]
            user32.ReleaseDC.restype = ctypes.wintypes.BOOL
            user32.GetClientRect.argtypes = [ctypes.wintypes.HWND, ctypes.c_void_p]
            user32.GetClientRect.restype = ctypes.wintypes.BOOL
            user32.PrintWindow.argtypes = [
                ctypes.wintypes.HWND, ctypes.wintypes.HDC, ctypes.wintypes.UINT,
            ]
            user32.PrintWindow.restype = ctypes.wintypes.BOOL

            gdi32.CreateCompatibleDC.argtypes = [ctypes.wintypes.HDC]
            gdi32.CreateCompatibleDC.restype = ctypes.wintypes.HDC
            gdi32.DeleteDC.argtypes = [ctypes.wintypes.HDC]
            gdi32.DeleteDC.restype = ctypes.wintypes.BOOL
            gdi32.CreateCompatibleBitmap.argtypes = [
                ctypes.wintypes.HDC, ctypes.c_int, ctypes.c_int,
            ]
            gdi32.CreateCompatibleBitmap.restype = ctypes.wintypes.HBITMAP
            gdi32.SelectObject.argtypes = [ctypes.wintypes.HDC, ctypes.wintypes.HGDIOBJ]
            gdi32.SelectObject.restype = ctypes.wintypes.HGDIOBJ
            gdi32.DeleteObject.argtypes = [ctypes.wintypes.HGDIOBJ]
            gdi32.DeleteObject.restype = ctypes.wintypes.BOOL
            gdi32.GetCurrentObject.argtypes = [ctypes.wintypes.HDC, ctypes.c_uint]
            gdi32.GetCurrentObject.restype = ctypes.wintypes.HGDIOBJ
            gdi32.GetDIBits.argtypes = [
                ctypes.wintypes.HDC, ctypes.wintypes.HBITMAP, ctypes.c_uint,
                ctypes.c_uint, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_uint,
            ]
            gdi32.GetDIBits.restype = ctypes.c_int

            w = x2 - x1
            h = y2 - y1
            if w <= 0 or h <= 0:
                logger.warning(f"PrintWindow 截图区域无效: ({x1},{y1},{x2},{y2})")
                return False

            # PrintWindow 总是把整个窗口画到 DC，因此先截取整个客户区，
            # 再从结果中裁剪出目标区域（避免局部区域截图时内容错位）
            client_rect = ctypes.wintypes.RECT()
            user32.GetClientRect(hwnd, ctypes.byref(client_rect))
            full_w = client_rect.right
            full_h = client_rect.bottom
            if full_w <= 0 or full_h <= 0:
                logger.warning(f"PrintWindow: 客户区尺寸无效 ({full_w}x{full_h})")
                return False

            wnd_dc = user32.GetDC(hwnd)
            if not wnd_dc:
                logger.warning("PrintWindow: GetDC 失败")
                return False
            try:
                mem_dc = gdi32.CreateCompatibleDC(wnd_dc)
                bmp = gdi32.CreateCompatibleBitmap(wnd_dc, full_w, full_h)
                old = gdi32.SelectObject(mem_dc, bmp)
                try:
                    ok = user32.PrintWindow(hwnd, mem_dc, PW_CLIENT_FULL)
                    if not ok:
                        logger.warning("PrintWindow 调用失败")
                        return False
                    # 从全窗口截图中裁剪出目标区域
                    from PIL import Image
                    full_path = filepath + ".full.tmp"
                    if not self._save_dc_to_bmp(mem_dc, full_w, full_h, full_path):
                        return False
                    try:
                        img = Image.open(full_path).convert("RGB")
                        # 确保裁剪区域不越界
                        cx2 = min(x2, full_w)
                        cy2 = min(y2, full_h)
                        crop = img.crop((x1, y1, cx2, cy2))
                        crop.save(filepath, "BMP")
                        return True
                    finally:
                        try:
                            os.remove(full_path)
                        except OSError:
                            pass
                finally:
                    gdi32.SelectObject(mem_dc, old)
                    gdi32.DeleteObject(bmp)
                    gdi32.DeleteDC(mem_dc)
            finally:
                user32.ReleaseDC(hwnd, wnd_dc)
        except Exception as e:
            logger.warning(f"PrintWindow 截图异常: {e}")
            return False
        finally:
            # 重新绑定窗口（如果之前已绑定）
            if was_bound and bind_params:
                try:
                    display, mouse, keypad, public, mode = bind_params
                    self._com_call("BindWindowEx", was_bound, display, mouse, keypad, public, mode)
                except Exception as e:
                    logger.warning(f"PrintWindow 后重新绑定窗口失败: {e}")

    @staticmethod
    def _save_dc_to_bmp(hdc, width: int, height: int, path: str) -> bool:
        """从 HDC 当前位图创建 DIB，写入 24 位 BMP 文件。

        使用 PIL ImageGrab.frombuffer 读取 DIB 数据，避免直接写文件时
        GetDIBits 在 64 位系统上对大 HDC 句柄溢出的问题。
        """
        from PIL import Image

        gdi32 = ctypes.windll.gdi32
        DIB_RGB_COLORS = 0
        OBJ_BITMAP = 7

        # 设置 argtypes/restype，避免 64 位系统上句柄溢出
        gdi32.GetCurrentObject.argtypes = [ctypes.wintypes.HDC, ctypes.c_uint]
        gdi32.GetCurrentObject.restype = ctypes.wintypes.HGDIOBJ
        gdi32.GetDIBits.argtypes = [
            ctypes.wintypes.HDC, ctypes.wintypes.HBITMAP, ctypes.c_uint,
            ctypes.c_uint, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_uint,
        ]
        gdi32.GetDIBits.restype = ctypes.c_int

        class BITMAPINFOHEADER(ctypes.Structure):
            _fields_ = [
                ("biSize", ctypes.c_uint32), ("biWidth", ctypes.c_long),
                ("biHeight", ctypes.c_long), ("biPlanes", ctypes.c_uint16),
                ("biBitCount", ctypes.c_uint16), ("biCompression", ctypes.c_uint32),
                ("biSizeImage", ctypes.c_uint32), ("biXPelsPerMeter", ctypes.c_long),
                ("biYPelsPerMeter", ctypes.c_long), ("biClrUsed", ctypes.c_uint32),
                ("biClrImportant", ctypes.c_uint32),
            ]

        hbm = gdi32.GetCurrentObject(hdc, OBJ_BITMAP)
        bmi = BITMAPINFOHEADER()
        bmi.biSize = ctypes.sizeof(BITMAPINFOHEADER)
        bmi.biWidth = width
        bmi.biHeight = -height  # 自上而下（负值 = top-down）
        bmi.biPlanes = 1
        bmi.biBitCount = 32  # 用 32 位（BGRA），避免 24 位行对齐问题
        bmi.biCompression = 0
        buf_size = width * height * 4
        buf = ctypes.create_string_buffer(buf_size)
        ok = gdi32.GetDIBits(hdc, hbm, 0, height, buf, ctypes.byref(bmi), DIB_RGB_COLORS)
        if not ok:
            logger.warning("_save_dc_to_bmp: GetDIBits 失败")
            return False
        # 用 PIL 从 raw buffer 创建图像（32 位 BGRA → RGB）
        img = Image.frombuffer("RGBA", (width, height), buf.raw, "raw", "BGRA", 0, 1)
        img = img.convert("RGB")
        img.save(path, "BMP")
        return True

    def capture_to_temp(self, x1, y1, x2, y2, prefix: str = "ocr") -> str:
        """截取屏幕区域到临时 BMP 文件，返回文件路径（失败返回空字符串）。

        需在窗口绑定上下文内调用，以支持后台窗口截图。
        调用方负责在使用完毕后删除临时文件。
        """
        temp_dir = tempfile.gettempdir()
        filename = f"gamebot_{prefix}_{os.getpid()}_{uuid.uuid4().hex}.bmp"
        filepath = os.path.join(temp_dir, filename)
        if self.capture_region(x1, y1, x2, y2, filepath):
            return filepath
        logger.warning(f"截图失败: bbox=({x1},{y1},{x2},{y2})")
        return ""

    def wait_pic(self, pic_name, x1=0, y1=0, x2=1920, y2=1080, timeout=10, interval=0.5, **kwargs):
        """等待图片出现，默认全屏查找"""
        start = time.time()
        while time.time() - start < timeout:
            found, _, _ = self.find_pic(x1, y1, x2, y2, pic_name, **kwargs)
            if found:
                return True
            time.sleep(interval)
        logger.warning(f"等待图片超时: {pic_name}")
        return False
