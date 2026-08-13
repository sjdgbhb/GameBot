"""推理子进程客户端 —— 在主进程（32 位，大漠 COM）中调用。

主进程通过本模块启动一个 64 位 Python 子进程运行 inference_worker.py，
以行式 JSON 通信，统一提供三种推理能力：
  - OCR（屏幕区域文字识别）
  - 宝箱检测（YOLOv8 目标检测）
  - 战斗状态检测（分类模型）

子进程常驻，模型只加载一次。线程安全（内部加锁）。
"""
import json
import os
import subprocess
import threading
from pathlib import Path
from typing import List, Tuple

from GameBot.config import config
from GameBot.utils import logger

_client = None
_init_lock = threading.Lock()


def _worker_script_path() -> str:
    # 支持 exe 打包环境：inference.worker_script 为空时表示 python_path 本身就是 worker exe
    worker_script = config.get("inference.worker_script", None)
    if worker_script is not None and worker_script == "":
        return ""
    if worker_script:
        p = Path(worker_script)
        if not p.is_absolute():
            p = config.project_root / p
        return str(p)
    return str(
        config.project_root / "src" / "GameBot" / "inference" / "worker.py"
    )


def _python_path() -> str:
    raw = config.get("inference.python_path", ".venv/Scripts/python.exe")
    p = Path(raw)
    if not p.is_absolute():
        p = config.project_root / p
    return str(p)


def _build_worker_config(load_chest: bool = True, load_combat: bool = True) -> dict:
    """从项目配置中提取子进程需要的参数，序列化为 JSON 传给子进程。

    Args:
        load_chest: 是否预加载宝箱检测模型
        load_combat: 是否预加载战斗状态检测模型
    """
    inf_cfg = config.get("inference", {})
    models_dir = inf_cfg.get("models_dir", "src/GameBot/resources/models")
    models_abs = os.path.join(config.project_root, models_dir)

    return {
        "load_chest": load_chest,
        "load_combat": load_combat,
        "ocr_device": str(config.get("inference.device", "cpu") or "cpu"),
        "ai_device": str(config.get("inference.device", "cpu") or "cpu"),
        "chest_model_path": os.path.join(models_abs, "chest_detector.onnx"),
        "combat_model_path": os.path.join(models_abs, "combat_status.onnx"),
        "chest_input_size": int(config.get("chest.ai_input_size", 1280)),
        "chest_conf": float(config.get("chest.ai_conf", 0.5)),
        "chest_iou": float(config.get("chest.ai_iou", 0.5)),
        "combat_img_w": int(config.get("combat_status.ai_img_w", 87)),
        "combat_img_h": int(config.get("combat_status.ai_img_h", 61)),
        "combat_threshold": float(config.get("combat_status.ai_threshold", 0.5)),
    }


class InferenceClient:
    """推理子进程的常驻客户端，提供 OCR、宝箱检测、战斗检测三种能力。"""

    def __init__(self):
        self._proc = None
        self._lock = threading.Lock()
        self.load_chest = True
        self.load_combat = True

    def start(self):
        """启动子进程并等待模型加载就绪（首次较慢）。"""
        if self._proc is not None and self._proc.poll() is None:
            return
        py = _python_path()
        script = _worker_script_path()
        cmd = [py] if not script else [py, script]
        logger.info(f"启动推理子进程: {' '.join(cmd)}")
        # worker exe 模式下检查文件是否存在
        if not script:
            if not os.path.isfile(py):
                raise RuntimeError(f"推理子进程 exe 不存在: {py}")
        env = dict(os.environ)
        env["PYTHONUNBUFFERED"] = "1"
        env["PYTHONIOENCODING"] = "utf-8"
        # 将 pip 安装的 NVIDIA cuDNN/cuBLAS DLL 路径加入 PATH，使 onnxruntime GPU 可用
        # client.py 运行在 3.8 环境，nvidia 包装在 3.12 .venv，需直接查找路径
        venv_site = os.path.join(os.path.dirname(os.path.dirname(py)), "Lib", "site-packages")
        nvidia_dirs = []
        for pkg in ("cudnn", "cublas", "cuda_nvrtc"):
            bin_dir = os.path.join(venv_site, "nvidia", pkg, "bin")
            if os.path.isdir(bin_dir):
                nvidia_dirs.append(bin_dir)
        if nvidia_dirs:
            env["PATH"] = os.pathsep.join(nvidia_dirs) + os.pathsep + env.get("PATH", "")
        env["JIUBING_INFERENCE_CONFIG"] = json.dumps(_build_worker_config(self.load_chest, self.load_combat), ensure_ascii=True)
        # CREATE_NO_WINDOW 隐藏子进程黑窗，不影响 stdin/stdout 管道通信
        self._proc = subprocess.Popen(
            cmd,
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
        threading.Thread(target=self._drain_stderr, daemon=True, name="InferenceStderr").start()

        line = self._proc.stdout.readline()
        if not line:
            raise RuntimeError(f"推理子进程启动无输出，stderr={self._read_stderr()}")
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            raise RuntimeError(f"推理子进程首行非 JSON: {line!r}")
        if not msg.get("ready"):
            raise RuntimeError(f"推理子进程未就绪: {msg}")
        loaded = ["OCR"]
        if self.load_chest:
            loaded.append("宝箱检测")
        if self.load_combat:
            loaded.append("战斗检测")
        logger.info(f"推理子进程就绪（{' + '.join(loaded)}）")

    def _read_stderr(self) -> str:
        try:
            return self._proc.stderr.read() if self._proc.stderr else ""
        except Exception:
            return ""

    def _drain_stderr(self):
        try:
            for line in self._proc.stderr:
                logger.debug(f"[inference] {line.rstrip()}")
        except Exception:
            pass

    def _request(self, payload: dict, _retried: bool = False) -> dict:
        """发送请求并阻塞等待响应。调用者需持有 _lock。

        子进程崩溃时自动重启并重试一次（仅重试一次，避免无限循环）。
        """
        self.start()
        try:
            self._proc.stdin.write(json.dumps(payload) + "\n")
            self._proc.stdin.flush()
        except (BrokenPipeError, OSError) as e:
            if not _retried:
                logger.warning(f"推理子进程管道断裂，尝试重启... ({e})")
                self._restart()
                return self._request(payload, _retried=True)
            raise RuntimeError(f"推理子进程管道断裂且重启失败: {e}")
        line = self._proc.stdout.readline()
        if not line:
            if not _retried:
                logger.warning("推理子进程无响应（可能已退出），尝试重启...")
                self._restart()
                return self._request(payload, _retried=True)
            raise RuntimeError("推理子进程无响应且重启失败（可能已退出）")
        try:
            return json.loads(line)
        except json.JSONDecodeError as e:
            if not _retried:
                logger.warning(f"推理子进程返回非 JSON: {line!r}，尝试重启... ({e})")
                self._restart()
                return self._request(payload, _retried=True)
            raise RuntimeError(f"推理子进程返回非 JSON且重启失败: {line!r} ({e})")

    def _restart(self):
        """终止当前子进程并重新启动。调用者需持有 _lock。"""
        if self._proc is not None:
            try:
                self._proc.kill()
            except Exception:
                pass
            self._proc = None
        self.start()

    def ocr_screen(self, bbox) -> str:
        """对屏幕区域 bbox=[x1,y1,x2,y2] 截屏并 OCR，返回识别文字。"""
        with self._lock:
            msg = self._request({"cmd": "ocr", "bbox": list(bbox)})
        if msg.get("error"):
            logger.debug(f"OCR 识别异常: {msg['error']}")
        return msg.get("text", "")

    def ocr_lines(self, bbox) -> list:
        """对屏幕区域截屏并 OCR，返回逐行结果（含 y 坐标）。

        返回 [{"text": "...", "y_center": float}, ...]，按 y 从上到下排序。
        用于任务弹窗行数解析等需要逐行信息的场景。
        """
        with self._lock:
            msg = self._request({"cmd": "ocr_lines", "bbox": list(bbox)})
        if msg.get("error"):
            logger.debug(f"OCR 逐行识别异常: {msg['error']}")
        return msg.get("lines", [])

    def detect_chests(self, img_path: str) -> List[Tuple[int, int, int, int, float]]:
        """对指定图片文件进行宝箱检测，返回 [(x1, y1, x2, y2, confidence), ...]。"""
        with self._lock:
            msg = self._request({"cmd": "detect_chests", "img_path": img_path})
        if msg.get("error"):
            logger.error(f"宝箱检测异常: {msg['error']}")
            return []
        chests = msg.get("chests", [])
        return [tuple(c) for c in chests]

    def capture_and_detect_chests(self, bbox) -> List[Tuple[int, int, int, int, float]]:
        """子进程直接截屏 + 宝箱检测，无需主进程写临时 BMP 文件。

        :param bbox: 屏幕区域 [x1, y1, x2, y2]，为 None 则全屏
        :return: [(x1, y1, x2, y2, confidence), ...]
        """
        with self._lock:
            req = {"cmd": "capture_and_detect_chests"}
            if bbox:
                req["bbox"] = list(bbox)
            msg = self._request(req)
        if msg.get("error"):
            logger.error(f"宝箱检测异常: {msg['error']}")
            return []
        chests = msg.get("chests", [])
        return [tuple(c) for c in chests]

    def predict_combat_batch(self, img_paths: List[str]) -> List[bool]:
        """对多张头像图片批量预测战斗状态，返回 [True/False, ...]。"""
        if not img_paths:
            return []
        with self._lock:
            msg = self._request({"cmd": "predict_combat", "img_paths": img_paths})
        if msg.get("error"):
            logger.error(f"战斗检测异常: {msg['error']}")
            return [False] * len(img_paths)
        return msg.get("combat", [False] * len(img_paths))

    def capture_and_predict_combat(self, bbox, frame_count: int = 10,
                                   frame_interval: float = 0.3,
                                   cancel_file: str = "") -> List[bool]:
        """子进程直接截屏 + 战斗检测，无需主进程写临时 BMP 文件。

        :param bbox: 屏幕区域 [x1, y1, x2, y2]
        :param frame_count: 采样帧数
        :param frame_interval: 采样间隔（秒）
        :param cancel_file: 取消信号文件路径，存在时子进程提前终止截帧
        :return: [True/False, ...]，每帧的战斗状态
        """
        with self._lock:
            req = {
                "cmd": "capture_and_predict_combat",
                "bbox": list(bbox),
                "frame_count": frame_count,
                "frame_interval": frame_interval,
            }
            if cancel_file:
                req["cancel_file"] = cancel_file
            msg = self._request(req)
        if msg.get("error"):
            logger.error(f"战斗检测异常: {msg['error']}")
            return [False] * frame_count
        return msg.get("combat", [False] * frame_count)

    def close(self):
        if self._proc and self._proc.poll() is None:
            try:
                self._proc.stdin.write(json.dumps({"cmd": "quit"}) + "\n")
                self._proc.stdin.flush()
                self._proc.wait(timeout=5)
            except Exception:
                try:
                    self._proc.kill()
                except Exception:
                    pass
        self._proc = None


def get_inference_client(load_chest: bool = True, load_combat: bool = True) -> InferenceClient:
    """获取全局共享的 InferenceClient 单例（首次调用启动子进程并加载模型）。

    Args:
        load_chest: 是否预加载宝箱检测模型（仅首次创建时生效）
        load_combat: 是否预加载战斗状态检测模型（仅首次创建时生效）
    """
    global _client
    if _client is None:
        with _init_lock:
            if _client is None:
                client = InferenceClient()
                client.load_chest = load_chest
                client.load_combat = load_combat
                client.start()
                _client = client
    return _client
