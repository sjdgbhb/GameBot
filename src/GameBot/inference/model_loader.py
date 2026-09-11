"""ONNX 模型加载器

统一负责所有 AI ONNX 模型（宝箱检测、战斗状态等）的加载与全局缓存。
业务层/任务层不直接调用此处，而是通过 inference.client.get_inference_client() 间接使用。
"""

import os
from typing import Any, Dict, List, Tuple

# 全局 session 缓存，按 (model_path, device) 维度去重
_SESSIONS: Dict[Tuple[str, str], Any] = {}


def _get_ort():
    """懒加载 onnxruntime，便于单测 mock 和无 onnxruntime 环境降级。"""
    try:
        import onnxruntime as ort
    except ImportError as e:
        raise ImportError("onnxruntime 未安装") from e
    return ort


def get_providers(device: str) -> List[str]:
    """根据设备选择 onnxruntime ExecutionProvider 列表。"""
    if device == "gpu":
        try:
            ort = _get_ort()
            available = ort.get_available_providers()
            if "CUDAExecutionProvider" in available:
                return ["CUDAExecutionProvider", "CPUExecutionProvider"]
        except (ImportError, RuntimeError):
            pass
    return ["CPUExecutionProvider"]


def _load_session(model_path: str, device: str):
    """实际创建 ONNX InferenceSession（项目中唯一调用 ort.InferenceSession 的地方）。"""
    ort = _get_ort()
    if not os.path.exists(model_path):
        raise FileNotFoundError(f"ONNX 模型不存在: {model_path}")

    opts = ort.SessionOptions()
    opts.log_severity_level = 3  # 只显示 Error，抑制 GPU 等 Warning
    providers = get_providers(device)
    return ort.InferenceSession(model_path, sess_options=opts, providers=providers)


def get_session(model_path: str, device: str = "cpu"):
    """获取指定模型的 ONNX session，全局缓存保证同一模型只加载一次。"""
    key = (model_path, device)
    session = _SESSIONS.get(key)
    if session is None:
        session = _load_session(model_path, device)
        _SESSIONS[key] = session
    return session


def clear_sessions():
    """清空全局 session 缓存（主要用于测试）。"""
    _SESSIONS.clear()
