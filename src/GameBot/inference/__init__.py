"""推理子包 — 统一管理 AI 推理相关模块。

子模块：
- model_loader.py — ONNX 模型加载与全局缓存
- local.py        — 进程内推理客户端（唯一实现）
- client.py       — 单例工厂 get_inference_client()
- worker.py       — 推理子进程 worker（exe 打包用）
"""

from .local import LocalInferenceClient
from .client import get_inference_client

__all__ = ["LocalInferenceClient", "get_inference_client"]
