"""dm_bridge 服务端 — 行式 JSON RPC 循环与大漠 COM 对象管理。

运行环境：32 位 Python 3.8（.venv-dm），仅依赖 stdlib + pywin32。
兼容 Python 3.8 语法。
"""

import ctypes
import json
import os
import subprocess
import sys
import traceback


def set_dpi_aware():
    """声明进程 DPI 感知，保证与主进程坐标体系一致。"""
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)  # PER_MONITOR_AWARE
    except OSError:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except OSError:
            pass


def _log(msg):
    """诊断日志写 stderr（主进程侧 DmBridgeClient 会转发到 logger.debug）。"""
    try:
        sys.stderr.write("%s\n" % msg)
        sys.stderr.flush()
    except (OSError, ValueError):
        pass


def try_register_silent(dll_path):
    """静默注册 dm.dll（不弹 UAC；当前进程已是管理员时才可能成功）。

    依次尝试 DllRegisterServer 和 regsvr32 /s，成功返回 True。
    """
    try:
        old_cwd = os.getcwd()
        try:
            # 切到 DLL 目录，便于其定位依赖文件
            os.chdir(os.path.dirname(dll_path))
            if ctypes.WinDLL(dll_path).DllRegisterServer() == 0:  # S_OK
                _log("DllRegisterServer 注册成功: %s" % dll_path)
                return True
        finally:
            os.chdir(old_cwd)
    except Exception as e:
        _log("DllRegisterServer 注册失败: %s" % e)

    sysroot = os.environ.get("SystemRoot", r"C:\Windows")
    for sub in ("SysWOW64", "System32"):
        regsvr = os.path.join(sysroot, sub, "regsvr32.exe")
        if not os.path.isfile(regsvr):
            continue
        try:
            if subprocess.run([regsvr, "/s", dll_path], capture_output=True).returncode == 0:
                _log("regsvr32 注册成功: %s" % regsvr)
                return True
        except Exception as e:
            _log("regsvr32 调用异常: %s" % e)
    return False


_REGISTER_HINT = r".venv-dm\Scripts\python.exe -m GameBot.dm_bridge --register"


def create_dm(cfg):
    """创建并初始化大漠 COM 对象。

    :param cfg: {"dll_path": DLL 目录, "version": 期望版本,
                 "keypad_delay": 秒, "mouse_delay": 秒}
    :return: (dm COM 对象, 实际版本号)
    :raises RuntimeError: 未注册且静默注册失败 / 版本不符
    """
    import win32com.client

    dll_dir = cfg.get("dll_path", "")
    dll_file = os.path.join(dll_dir, "dm.dll") if dll_dir else ""
    expected = cfg.get("version", "")

    def _dispatch():
        return win32com.client.Dispatch("dm.dmsoft")

    try:
        dm = _dispatch()
    except Exception:
        if not (dll_file and os.path.isfile(dll_file) and try_register_silent(dll_file)):
            raise RuntimeError(
                "无法创建大漠 COM 对象（dm.dll 未注册）。"
                "请以管理员身份执行一次注册：%s" % _REGISTER_HINT
            )
        dm = _dispatch()

    ver = dm.Ver()
    if expected and ver != expected:
        # 版本不符，尝试用配置目录中的 dm.dll 静默重注册（需已是管理员）
        if dll_file and os.path.isfile(dll_file) and try_register_silent(dll_file):
            dm = _dispatch()
            ver = dm.Ver()
        if ver != expected:
            raise RuntimeError(
                "大漠版本不符：期望 %s，实际 %s。"
                "请以管理员身份重新注册：%s" % (expected, ver, _REGISTER_HINT)
            )

    if dll_dir:
        dm.SetPath(dll_dir)
    dm.SetKeypadDelay("normal", float(cfg.get("keypad_delay", 0.03)))
    dm.SetMouseDelay("normal", float(cfg.get("mouse_delay", 0.03)))
    return dm, ver


class BridgeServer:
    """行式 JSON RPC 服务器（stdin 读请求，stdout 写响应，stderr 写日志）。

    可注入 dm 对象与输入输出流，便于单元测试。
    """

    def __init__(self, dm, stdin=None, stdout=None):
        self._dm = dm
        self._stdin = stdin if stdin is not None else sys.stdin
        self._stdout = stdout if stdout is not None else sys.stdout

    def _respond(self, payload):
        """写一行响应；结果不可 JSON 序列化时降级为错误响应。"""
        try:
            text = json.dumps(payload, ensure_ascii=True)
        except (TypeError, ValueError) as e:
            text = json.dumps(
                {
                    "id": payload.get("id"),
                    "ok": False,
                    "error": "结果无法序列化: %s" % e,
                },
                ensure_ascii=True,
            )
        self._stdout.write(text + "\n")
        self._stdout.flush()

    def handle_request(self, req):
        """处理单条请求，返回响应 dict；method=quit 时返回 None（调用方退出循环）。"""
        req_id = req.get("id")
        method = req.get("method", "")
        if method == "quit":
            return None
        if method == "ping":
            return {"id": req_id, "ok": True, "result": "pong"}
        if method == "com":
            name = req.get("name", "")
            args = req.get("args", [])
            try:
                result = getattr(self._dm, name)(*args)
                if isinstance(result, tuple):
                    result = list(result)
                return {"id": req_id, "ok": True, "result": result}
            except Exception as e:
                return {
                    "id": req_id,
                    "ok": False,
                    "error": "%s: %s" % (type(e).__name__, e),
                    "traceback": traceback.format_exc(),
                }
        return {"id": req_id, "ok": False, "error": "未知方法: %r" % method}

    def serve_forever(self):
        """主循环：逐行读请求直到 stdin EOF（父进程退出）或收到 quit。"""
        for line in self._stdin:
            line = line.strip()
            if not line:
                continue
            try:
                req = json.loads(line)
            except (json.JSONDecodeError, ValueError) as e:
                self._respond({"id": None, "ok": False, "error": "请求非 JSON: %s" % e})
                continue
            resp = self.handle_request(req)
            if resp is None:
                self._respond({"id": req.get("id"), "ok": True, "result": "bye"})
                break
            self._respond(resp)
        _log("dm_bridge 退出（stdin 关闭或收到 quit）")
