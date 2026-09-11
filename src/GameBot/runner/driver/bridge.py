"""大漠 RPC 桥接驱动 — 64 位主环境经 32 位 dm_bridge 子进程调用大漠 COM。

通信：stdin/stdout 行式 JSON（协议见 GameBot/dm_bridge/__init__.py），
子进程常驻、请求串行（内部加锁，线程安全）。

特点：
- 大漠 COM 线程亲和限制消失（所有调用在桥接进程主线程串行执行）；
- 子进程异常退出时不自动重启（窗口绑定状态无法恢复，静默重启会掩盖问题），
  抛出 DmError 由上层任务框架处理。
"""

import atexit
import json
import os
import subprocess
import threading
from pathlib import Path

from GameBot.config import config
from GameBot.runner.driver.base import DmClientBase
from GameBot.utils.exception_handler import DmError
from GameBot.utils.logger import logger


def resolve_bridge_python() -> str:
    """解析 dm_bridge 使用的 32 位 Python 路径。

    优先 [dm].python_path 配置，未配置则自动检测 .venv-dm/Scripts/python.exe。
    """
    dm_cfg = config.get("dm", {})
    raw = dm_cfg.get("python_path", "")
    if raw:
        p = Path(raw)
        if not p.is_absolute():
            p = config.project_root / p
        if p.exists():
            return str(p)
        logger.warning(f"[dm].python_path 不存在: {p}，尝试自动检测 .venv-dm")
    default = config.project_root / ".venv-dm" / "Scripts" / "python.exe"
    if default.exists():
        return str(default)
    raise DmError(
        "未找到 32 位大漠环境 Python。请创建 .venv-dm："
        "uv venv .venv-dm --python 3.8（需 32 位 Python 3.8），"
        "并安装依赖：uv pip install -r dm-requirements.txt --python .venv-dm；"
        "或在 base.toml [dm].python_path 指定路径"
    )


class DmBridgeClient(DmClientBase):
    """经 dm_bridge 子进程的大漠驱动（每实例独占一个桥接进程，多开互不干扰）。"""

    def __init__(self):
        dm_cfg = config.get("dm", {})
        self.expected_version = dm_cfg.get("version", "3.1233")
        dll_path = dm_cfg.get("dll_path")
        if not dll_path:
            raise ValueError("配置中缺少 'dll_path' 或值为空")
        self.dm_dll = config.project_root / dll_path / "dm.dll"
        if not self.dm_dll.exists():
            raise FileNotFoundError(f"大漠插件 DLL 不存在: {self.dm_dll}")

        self._lock = threading.Lock()
        self._req_id = 0
        self._proc = None
        self._start()
        atexit.register(self.close)

    # ---------- 子进程管理 ----------

    def _start(self):
        """启动 dm_bridge 子进程并等待就绪行。"""
        py = resolve_bridge_python()
        env = os.environ.copy()
        src_path = str(config.project_root / "src")
        old_pp = env.get("PYTHONPATH", "")
        env["PYTHONPATH"] = f"{src_path}{os.pathsep}{old_pp}" if old_pp else src_path
        env["PYTHONUNBUFFERED"] = "1"
        env["PYTHONIOENCODING"] = "utf-8"
        env["GAMEBOT_DM_BRIDGE_CONFIG"] = json.dumps(
            {
                "dll_path": str(self.dm_dll.parent),
                "version": self.expected_version,
                "keypad_delay": 0.03,
                "mouse_delay": 0.03,
            },
            ensure_ascii=True,
        )
        cmd = [py, "-m", "GameBot.dm_bridge"]
        logger.info(f"启动 dm_bridge 子进程: {' '.join(cmd)}")
        self._proc = subprocess.Popen(
            cmd,
            cwd=str(config.project_root),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
            env=env,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        threading.Thread(target=self._drain_stderr, daemon=True, name="DmBridgeStderr").start()

        try:
            line = self._proc.stdout.readline()
            if not line:
                raise DmError(f"dm_bridge 启动无输出（进程已退出，returncode={self._proc.poll()}）")
            try:
                msg = json.loads(line)
            except json.JSONDecodeError:
                raise DmError(f"dm_bridge 首行非 JSON: {line!r}")
            if not msg.get("ready"):
                raise DmError(f"dm_bridge 未就绪: {msg.get('error', msg)}")
        except Exception:
            # 启动失败清理子进程，避免孤儿
            try:
                self._proc.kill()
            except OSError as kill_err:
                logger.debug(f"清理 dm_bridge 子进程失败: {kill_err}")
            raise
        self._bridge_version = msg.get("version", "")
        logger.info(f"dm_bridge 就绪（大漠版本 {self._bridge_version}）")

    def _drain_stderr(self):
        try:
            for line in self._proc.stderr:
                logger.debug(f"[dm_bridge] {line.rstrip()}")
        except (OSError, ValueError):
            pass

    def close(self):
        """终止 dm_bridge 子进程（幂等）。"""
        proc = self._proc
        if proc is None:
            return
        self._proc = None
        try:
            if proc.poll() is None:
                try:
                    proc.stdin.write(json.dumps({"id": -1, "method": "quit"}) + "\n")
                    proc.stdin.flush()
                    proc.wait(timeout=3)
                except (BrokenPipeError, OSError, subprocess.TimeoutExpired):
                    proc.kill()
        except OSError as e:
            logger.debug(f"关闭 dm_bridge 子进程失败: {e}")

    # ---------- 抽象原语实现 ----------

    def _com_call(self, name, *args):
        """经 RPC 调用大漠 COM 方法（线程安全，请求串行）。"""
        with self._lock:
            proc = self._proc
            if proc is None or proc.poll() is not None:
                raise DmError(
                    "dm_bridge 子进程已退出，无法调用大漠方法（不自动重启以避免丢失窗口绑定状态，请重启任务）"
                )
            self._req_id += 1
            req = {"id": self._req_id, "method": "com", "name": name, "args": list(args)}
            try:
                proc.stdin.write(json.dumps(req, ensure_ascii=True) + "\n")
                proc.stdin.flush()
            except (BrokenPipeError, OSError) as e:
                raise DmError(f"dm_bridge 管道写入失败（子进程可能已退出）: {e}")
            line = proc.stdout.readline()
            if not line:
                raise DmError(f"dm_bridge 无响应（子进程已退出，returncode={proc.poll()}）")
            try:
                msg = json.loads(line)
            except json.JSONDecodeError:
                raise DmError(f"dm_bridge 返回非 JSON: {line!r}")
            if msg.get("id") != self._req_id:
                raise DmError(f"dm_bridge 响应 id 不匹配: 期望 {self._req_id}，实际 {msg.get('id')}")
            if not msg.get("ok"):
                raise DmError(f"大漠调用 {name} 失败: {msg.get('error')}")
            result = msg.get("result")
            # COM 元组结果经 JSON 变为 list，还原为 tuple（如 FindPic/GetClientRect）
            if isinstance(result, list):
                return tuple(result)
            return result
