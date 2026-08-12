import os
import time
import sys
import ctypes
import subprocess
from contextlib import contextmanager
from pathlib import Path

import win32com.client
import pythoncom
import winreg
from typing import Tuple, Optional, List, Union

from GameBot.utils.logger import logger
from GameBot.config import config
from GameBot.utils.exception_handler import DmError, retry
from GameBot.runner.resource_manager import res_mgr

# 声明进程 DPI 感知，避免 Windows DPI 缩放导致大漠坐标与实际像素不一致
try:
    ctypes.windll.shcore.SetProcessDpiAwareness(2)  # PER_MONITOR_AWARE
except Exception:
    try:
        ctypes.windll.user32.SetProcessDPIAware()
    except Exception:
        pass


class DmRegistrar:
    """大漠注册管理（使用 RegDll.dll 或 regsvr32）"""

    @staticmethod
    def is_registered(expected_version: str) -> bool:
        """检查大漠是否已注册且版本匹配"""
        try:
            # 尝试创建对象
            dm = win32com.client.Dispatch("dm.dmsoft")
            ver = dm.Ver()
            return ver == expected_version
        except Exception:
            return False

    @staticmethod
    def _try_regsvr32(dll_path: str) -> bool:
        """尝试用 32 位和 64 位 regsvr32 注册 DLL，成功返回 True。"""
        # 32 位 DLL 优先用 SysWOW64\regsvr32.exe，64 位 DLL 用 System32\regsvr32.exe
        candidates = [
            os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "SysWOW64", "regsvr32.exe"),
            os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "System32", "regsvr32.exe"),
        ]
        for regsvr in candidates:
            if not os.path.isfile(regsvr):
                continue
            ret = subprocess.run([regsvr, '/s', dll_path], capture_output=True).returncode
            if ret == 0:
                logger.info(f"regsvr32 注册成功: {regsvr} -> {dll_path}")
                return True
            logger.warning(f"regsvr32 注册失败（返回值 {ret}）: {regsvr}")
        return False

    @staticmethod
    def register(dll_path: str):
        """注册 dm.dll（优先使用 RegDll.dll，回退 regsvr32）"""
        if not os.path.exists(dll_path):
            raise FileNotFoundError(f"dm.dll 不存在: {dll_path}")

        # 需要管理员权限
        if not ctypes.windll.shell32.IsUserAnAdmin():
            logger.warning("当前非管理员权限，尝试提权...")
            # 重新以管理员身份运行当前脚本
            ctypes.windll.shell32.ShellExecuteW(
                None, "runas", sys.executable, " ".join(sys.argv), None, 1
            )
            sys.exit(0)  # 当前进程退出，等待提权后的新进程

        # 方式一：直接调用 dm.dll 的 DllRegisterServer（标准 COM 注册接口）
        # 需要先初始化 COM 并切换到 DLL 所在目录，以便 DLL 找到依赖文件
        try:
            pythoncom.CoInitialize()
            old_cwd = os.getcwd()
            os.chdir(str(Path(dll_path).parent))
            lib = ctypes.WinDLL(str(dll_path))
            ret = lib.DllRegisterServer()
            os.chdir(old_cwd)
            if ret == 0:  # S_OK
                logger.info(f"DllRegisterServer 注册成功: {dll_path}")
                return
            logger.warning(f"DllRegisterServer 注册失败，返回值 {ret}，尝试 regsvr32...")
        except Exception as e:
            logger.warning(f"DllRegisterServer 注册异常: {e}，尝试 regsvr32...")
        finally:
            try:
                os.chdir(old_cwd)
            except Exception:
                pass

        # 方式二：回退到 regsvr32（依次尝试 32 位和 64 位）
        if not DmRegistrar._try_regsvr32(str(dll_path)):
            raise DmError(f"dm.dll 注册失败，regsvr32 均未成功: {dll_path}")

    @staticmethod
    def ensure_registered(expected_version: str, dll_path: Union[str, Path]):
        """确保大漠已注册且版本正确，否则自动注册"""
        if DmRegistrar.is_registered(expected_version):
            return
        logger.warning(f"大漠未注册或版本不符，开始注册（需要管理员权限）...")
        DmRegistrar.register(dll_path)
        # 注册后验证
        if not DmRegistrar.is_registered(expected_version):
            raise DmError("大漠注册后仍无法创建对象，请检查系统环境")


class DmClient:
    """大漠基础操作封装（不捕获 COMError，让上层处理重试）"""

    def __init__(self):
        dm_config = config.get("dm", {})
        self.expected_version = dm_config.get("version", "3.1233")
        dll_path = dm_config.get("dll_path")
        if not dll_path:
            raise ValueError("配置中缺少 'dll_path' 或值为空")
        self.dm_dll = config.project_root / dll_path / "dm.dll"
        if not self.dm_dll.exists():
            raise FileNotFoundError(f"大漠插件 DLL 不存在: {self.dm_dll}")

        # 确保注册
        DmRegistrar.ensure_registered(self.expected_version, self.dm_dll)

        # 创建大漠 COM 对象
        self._com = win32com.client.Dispatch("dm.dmsoft")

        # 设置全局路径
        self._com.SetPath(str(self.dm_dll.parent))

        # 设置键鼠按键弹起的默认延迟
        self._com.SetKeypadDelay('normal', 0.03)  # 默认30ms
        self._com.SetMouseDelay('normal', 0.03)  # 默认30ms

    @contextmanager
    def bind_window(self, hwnd, display='normal', mouse='normal', keypad='normal', mode=0):
        if hwnd == 0:
            raise DmError("未找到游戏窗口，hwnd 为 0")
        # 先绑定，如果失败直接抛异常，不会进入 finally
        ret = self._com.BindWindow(hwnd, display, mouse, keypad, mode)
        if ret != 1:
            raise DmError(f"绑定窗口失败，返回值: {ret}")
        try:
            yield
        finally:
            self._com.UnBindWindow()

    # ---------- 基础操作（直接透传，不捕获异常） ----------
    def find_pic(self, x1, y1, x2, y2, pic_name, sim=0.9, delta_color="000000", dir=0) -> Tuple[int, int, int]:
        """找图，返回 (是否找到, x, y)"""
        pic_path = res_mgr.get_image_path(pic_name)
        # 直接调用，不传入输出参数
        result = self._com.FindPic(x1, y1, x2, y2, pic_path, delta_color, sim, dir)
        return result

    def click_pic(self, pic_name, x1=0, y1=0, x2=1920, y2=1080, delta_color="000000", sim=0.9, offset_x=0, offset_y=0):
        """点击图片中心（偏移后）"""
        is_found, x, y = self.find_pic(x1, y1, x2, y2, pic_name, delta_color, sim)
        if not is_found:
            return False
        click_x = x + offset_x
        click_y = y + offset_y
        self._com.MoveTo(click_x, click_y)
        self._com.LeftClick()
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
        result = self._com.FindPicEx(x1, y1, x2, y2, pic_paths, delta_color, sim, dir)
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
        result = self._com.FindColor(x1, y1, x2, y2, color, sim, dir)
        return result

    def get_color(self, x: int, y: int) -> str:
        """获取指定像素颜色（十六进制字符串，如 'ff0000'）"""
        return self._com.GetColor(x, y)

    def capture_region(self, x1, y1, x2, y2, filepath: str) -> bool:
        """截取屏幕区域到文件，返回是否成功。"""
        ret = self._com.Capture(x1, y1, x2, y2, filepath)
        return ret == 1

    def ocr_text(self, x1, y1, x2, y2, color="ff0000-000000", sim=1.0):
        """OCR 识别文字，支持多颜色（用 | 分隔），串行尝试直到有结果。"""
        colors = color.split("|")
        for c in colors:
            c = c.strip()
            result = self._com.Ocr(x1, y1, x2, y2, c, sim)
            result = (result or "").strip()
            if result:
                return result
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

    def set_keypad_delay(self, key_type: str = 'normal', delay: float = 0.03):
        """设置按键弹起延迟（秒）"""
        self._com.SetKeypadDelay(key_type, delay)

    def key_press_char(self, char: str):
        self._com.KeyPressChar(char)

    def key_down_char(self, char: str):
        self._com.KeyDownChar(char)

    def key_up_char(self, char: str):
        self._com.KeyUpChar(char)

    def move_to(self, x: int, y: int):
        self._com.MoveTo(x, y)

    def left_click(self):
        self._com.LeftClick()

    def left_double_click(self):
        self._com.LeftDoubleClick()

    def left_down(self):
        return self._com.LeftDown()

    def left_up(self):
        return self._com.LeftUp()

    def right_click(self):
        self._com.RightClick()

    def set_client_size(self, hwnd: int, width: int, height: int) -> bool:
        ret = self._com.SetClientSize(hwnd, width, height)
        if ret != 1:
            raise DmError(f"设置客户区大小失败，返回值: {ret}")
        return True

    def find_window(self, window_class, window_title) -> int:
        """通过窗口类名、窗口标题查找窗口句柄（模糊匹配），找不到返回 0"""
        return self._com.FindWindow(window_class, window_title)

    def get_client_rect(self, hwnd: int) -> Tuple[int, int, int, int]:
        """获取窗口客户区在屏幕上的矩形 (left, top, right, bottom)。

        大漠 GetClientRect(hwnd, x1,y1,x2,y2) 通过 byref 返回客户区屏幕坐标，
        win32com 调用会返回 (ret, x1, y1, x2, y2)；left/top 即客户区原点屏幕坐标。
        注意：大漠 COM 线程亲和，仅限创建 dm 的线程调用。
        """
        ret, x1, y1, x2, y2 = self._com.GetClientRect(hwnd)
        if ret != 1:
            raise DmError(f"获取客户区矩形失败: hwnd={hwnd}, ret={ret}")
        return int(x1), int(y1), int(x2), int(y2)

    @staticmethod
    def get_foreground_window() -> int:
        """获取当前用户正在操作的活动窗口句柄"""
        user32 = ctypes.windll.user32
        return user32.GetForegroundWindow()

    def enum_windows(self, window_class, window_title, filter: int = 1+2+8+16) -> List[int]:
        """
        枚举符合条件的窗口
        :param window_class: 窗口类名，模糊匹配，为空则匹配所有
        :param window_title: 窗口标题，模糊匹配，为空则匹配所有
        :param filter: 过滤条件，默认 24 = 16(可见窗口) + 8(顶级窗口)
        :return: 窗口句柄列表
        """
        hwnds_str = self._com.EnumWindow(0, window_title, window_class, filter)

        if not hwnds_str:
            return []
        return [int(h) for h in hwnds_str.split(',') if h]

    def get_active_window(self, window_class: str="", window_title: str="") -> int:
        """
        获取当前正在操作的魔兽窗口句柄
        :param window_class: 窗口类名，模糊匹配，为空则匹配所有
        :param window_title: 窗口标题，模糊匹配，为空则匹配所有
        :return: 窗口句柄
        """
        active_hwnd = self.get_foreground_window()
        if active_hwnd == 0:
            logger.warning(f"没有获取到激活的窗口class={window_class}, title={window_title}")
            return 0
        hwnds = self.enum_windows(window_class, window_title)
        # 验证该窗口是否属于魔兽
        if active_hwnd in hwnds:
            return active_hwnd
        logger.warning(f"当前活动窗口不是class={window_class}, title={window_title}，请切换到该窗口后再运行脚本")
        return 0

    @property
    def version(self):
        return self._com.Ver()