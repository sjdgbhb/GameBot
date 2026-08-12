"""OCR 兼容层 —— 统一推理子进程（inference_client）的向后兼容入口。

原 paddle_ocr.py 独立管理 OCR 子进程，现已合并到 inference_client.py 统一管理
（OCR + 宝箱检测 + 战斗检测共用一个 64 位子进程）。本文件保留 get_ocr_client()
接口，内部转发到 inference_client，避免其他模块改动 import。

注意：模块名 paddle_ocr 为历史遗留，实际引擎为 RapidOCR（onnxruntime 后端），
文件名保留以避免大面积 import 改动。
"""
from .client import InferenceClient, get_inference_client

# 向后兼容别名
OcrClient = InferenceClient


def get_ocr_client(load_chest: bool = True, load_combat: bool = True) -> InferenceClient:
    """获取全局共享的推理客户端单例（首次调用启动子进程并加载模型）。

    Args:
        load_chest: 是否预加载宝箱检测模型（仅首次创建时生效）
        load_combat: 是否预加载战斗状态检测模型（仅首次创建时生效）
    """
    return get_inference_client(load_chest=load_chest, load_combat=load_combat)