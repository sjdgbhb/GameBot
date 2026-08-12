"""推理子包 — 统一管理 AI 推理相关模块。

子模块：
- client.py          — 推理子进程客户端（主进程调用）
- worker.py          — 64 位推理子进程（OCR / 目标检测 / 分类）
- chest_detector.py  — 宝箱检测（YOLOv8）
- combat_detector.py — 战斗状态分类
- ocr_compat.py      — OCR 兼容层（get_ocr_client 转发）
"""
from .client import InferenceClient, get_inference_client
from .ocr_compat import get_ocr_client

__all__ = ["InferenceClient", "get_inference_client", "get_ocr_client"]
