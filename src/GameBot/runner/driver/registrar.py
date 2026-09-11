"""大漠 COM 注册管理 — 仅 32 位环境（dm_bridge --register）使用。

依赖 pywin32（pythoncom / win32com），请勿在 64 位主环境的常驻路径中导入本模块。
"""

import ctypes
import os
import subprocess
import sys
from pathlib import Path
from typing import Union

import pythoncom
import win32com.client

from GameBot.utils.exception_handler import DmError
from GameBot.utils.logger import logger


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
            ret = subprocess.run([regsvr, "/s", dll_path], capture_output=True).returncode
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
            ctypes.windll.shell32.ShellExecuteW(None, "runas", sys.executable, " ".join(sys.argv), None, 1)
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
        logger.warning("大漠未注册或版本不符，开始注册（需要管理员权限）...")
        DmRegistrar.register(dll_path)
        # 注册后验证
        if not DmRegistrar.is_registered(expected_version):
            raise DmError("大漠注册后仍无法创建对象，请检查系统环境")
