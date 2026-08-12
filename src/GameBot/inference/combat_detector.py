"""
战斗状态 AI 检测模块

使用 ONNX 模型对英雄头像截图进行战斗/非战斗二分类。
模型由 scripts/train_combat_model.py 训练并导出。
"""
import os
import tempfile

import numpy as np
from PIL import Image

try:
    import onnxruntime as ort
except ImportError:
    ort = None

from GameBot.utils.logger import logger
from GameBot.config import config


def _get_model_path():
    """从 base.toml [inference] 读取模型目录，拼接战斗状态模型路径。"""
    inf_cfg = config.get("inference", {})
    models_dir = inf_cfg.get("models_dir", "src/GameBot/resources/models")
    return os.path.join(config.project_root, models_dir, "combat_status.onnx")


def _get_provider():
    """从 base.toml [inference] 读取 onnxruntime provider。"""
    device = config.get("inference.device", "cpu")
    if device == "gpu":
        return ["CUDAExecutionProvider", "CPUExecutionProvider"]
    return ["CPUExecutionProvider"]


def _get_img_size():
    """从 jiubing2.toml [combat_status] 读取模型输入尺寸。"""
    w = int(config.get("combat_status.ai_img_w", 87))
    h = int(config.get("combat_status.ai_img_h", 61))
    return w, h


def _get_threshold():
    """从 jiubing2.toml [combat_status] 读取分类阈值。"""
    return float(config.get("combat_status.ai_threshold", 0.5))

_session = None


def _get_session():
    global _session
    if _session is None:
        if ort is None:
            raise ImportError("onnxruntime 未安装")
        model_path = _get_model_path()
        if not os.path.exists(model_path):
            raise FileNotFoundError(f"战斗状态模型不存在: {model_path}")
        _session = ort.InferenceSession(model_path, providers=_get_provider())
        logger.info(f"战斗状态模型已加载: {model_path}")
    return _session


def predict_combat(img: Image.Image) -> bool:
    """对单张头像图片进行战斗状态预测，返回 True=战斗中。"""
    session = _get_session()
    img_w, img_h = _get_img_size()
    threshold = _get_threshold()
    img = img.convert("RGB").resize((img_w, img_h))
    arr = np.array(img).transpose(2, 0, 1).astype(np.float32) / 255.0
    arr = np.expand_dims(arr, axis=0)

    result = session.run(["output"], {"input": arr})
    prob = float(result[0][0])
    return prob > threshold


def predict_combat_batch(imgs: list) -> list:
    """对多张头像图片批量预测，返回 [True/False, ...]。"""
    if not imgs:
        return []
    session = _get_session()
    img_w, img_h = _get_img_size()
    threshold = _get_threshold()
    batch = []
    for img in imgs:
        img = img.convert("RGB").resize((img_w, img_h))
        arr = np.array(img).transpose(2, 0, 1).astype(np.float32) / 255.0
        batch.append(arr)
    batch = np.stack(batch)

    result = session.run(["output"], {"input": batch})
    probs = result[0].flatten()
    return [p > threshold for p in probs]
