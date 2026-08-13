"""
宝箱检测 AI 模块

使用 YOLOv8 ONNX 模型对全屏截图进行宝箱目标检测。
模型由 scripts/train_chest_detector.py 训练并导出。

推理在主进程（32位）中用 onnxruntime CPU 执行，与 combat_detector.py 同模式。
"""
import os

import numpy as np
from PIL import Image

try:
    import onnxruntime as ort
except ImportError:
    ort = None

from GameBot.config import config
from GameBot.utils.logger import logger

PAD_COLOR = (114, 114, 114)


def _get_input_size():
    """从 jiubing2.toml [chest] 读取模型输入尺寸。"""
    return int(config.get("chest.ai_input_size", 1280))


def _get_conf_threshold():
    """从 jiubing2.toml [chest] 读取置信度阈值。"""
    return float(config.get("chest.ai_conf", 0.4))


def _get_iou_threshold():
    """从 jiubing2.toml [chest] 读取 NMS IoU 阈值。"""
    return float(config.get("chest.ai_iou", 0.5))

_session = None


def _get_model_path():
    """从 base.toml [inference] 读取模型路径。"""
    inf_cfg = config.get("inference", {})
    models_dir = inf_cfg.get("models_dir", "src/GameBot/resources/models")
    return os.path.join(config.project_root, models_dir, "chest_detector.onnx")


def _get_provider():
    """从 base.toml [inference] 读取 onnxruntime provider。"""
    device = config.get("inference.device", "cpu")
    if device == "gpu":
        return ["CUDAExecutionProvider", "CPUExecutionProvider"]
    return ["CPUExecutionProvider"]


def _get_session():
    global _session
    if _session is None:
        if ort is None:
            raise ImportError("onnxruntime 未安装")
        model_path = _get_model_path()
        if not os.path.exists(model_path):
            raise FileNotFoundError(f"宝箱检测模型不存在: {model_path}")
        _session = ort.InferenceSession(model_path, providers=_get_provider())
        logger.info(f"宝箱检测模型已加载: {model_path}")
    return _session


def _letterbox(img: Image.Image, target_size: int):
    """等比缩放 + 灰色填充到 target_size x target_size，返回 (resized_img, scale, pad_x, pad_y)。"""
    w, h = img.size
    scale = min(target_size / w, target_size / h)
    new_w = int(w * scale)
    new_h = int(h * scale)
    resized = img.resize((new_w, new_h), Image.LANCZOS)

    canvas = Image.new("RGB", (target_size, target_size), PAD_COLOR)
    pad_x = (target_size - new_w) // 2
    pad_y = (target_size - new_h) // 2
    canvas.paste(resized, (pad_x, pad_y))
    return canvas, scale, pad_x, pad_y


def _nms(boxes: np.ndarray, scores: np.ndarray, iou_threshold: float) -> list:
    """纯 numpy NMS，返回保留的索引列表。boxes: [N,4] xyxy, scores: [N]。"""
    if len(boxes) == 0:
        return []
    x1 = boxes[:, 0]
    y1 = boxes[:, 1]
    x2 = boxes[:, 2]
    y2 = boxes[:, 3]
    areas = (x2 - x1) * (y2 - y1)
    order = scores.argsort()[::-1]

    keep = []
    while order.size > 0:
        i = order[0]
        keep.append(i)
        if order.size == 1:
            break
        xx1 = np.maximum(x1[i], x1[order[1:]])
        yy1 = np.maximum(y1[i], y1[order[1:]])
        xx2 = np.minimum(x2[i], x2[order[1:]])
        yy2 = np.minimum(y2[i], y2[order[1:]])
        w = np.maximum(0, xx2 - xx1)
        h = np.maximum(0, yy2 - yy1)
        inter = w * h
        iou = inter / (areas[i] + areas[order[1:]] - inter + 1e-7)
        order = order[1:][iou <= iou_threshold]
    return keep


def detect_chests(img: Image.Image, conf_threshold: float = None,
                  iou_threshold: float = None) -> list:
    """对全屏截图进行宝箱检测。

    Args:
        img: PIL.Image，全屏截图（RGB）
        conf_threshold: 置信度阈值，None 时从配置读取
        iou_threshold: NMS IoU 阈值，None 时从配置读取

    Returns:
        [(x1, y1, x2, y2, confidence), ...] 坐标为原图像素坐标
    """
    session = _get_session()
    orig_w, orig_h = img.size

    input_size = _get_input_size()
    if conf_threshold is None:
        conf_threshold = _get_conf_threshold()
    if iou_threshold is None:
        iou_threshold = _get_iou_threshold()

    letterboxed, scale, pad_x, pad_y = _letterbox(img, input_size)
    arr = np.array(letterboxed).transpose(2, 0, 1).astype(np.float32) / 255.0
    arr = np.expand_dims(arr, axis=0)

    output = session.run(None, {session.get_inputs()[0].name: arr})[0]

    # YOLOv8 输出: [1, 4+num_classes, num_anchors] → 转置为 [num_anchors, 5]
    predictions = output[0].T  # [N, 5] for 1 class: cx, cy, w, h, conf

    # 过滤低置信度
    scores = predictions[:, 4]
    mask = scores > conf_threshold
    filtered = predictions[mask]

    if len(filtered) == 0:
        return []

    # cxcywh → xyxy（模型输入坐标系）
    cx, cy, w, h = filtered[:, 0], filtered[:, 1], filtered[:, 2], filtered[:, 3]
    confs = filtered[:, 4]
    x1 = cx - w / 2
    y1 = cy - h / 2
    x2 = cx + w / 2
    y2 = cy + h / 2
    boxes = np.stack([x1, y1, x2, y2], axis=1)

    # NMS
    if len(filtered) > 1:
        logger.debug(f"宝箱检测 NMS前: {len(filtered)} 个候选框, iou阈值={iou_threshold}")
        for i in range(len(filtered)):
            logger.debug(f"  候选#{i} box=[{boxes[i,0]:.0f},{boxes[i,1]:.0f},{boxes[i,2]:.0f},{boxes[i,3]:.0f}] conf={confs[i]:.3f}")
    keep_idx = _nms(boxes, confs, iou_threshold)

    # 坐标变换：模型输入坐标 → 原图坐标
    results = []
    for i in keep_idx:
        bx1 = (boxes[i, 0] - pad_x) / scale
        by1 = (boxes[i, 1] - pad_y) / scale
        bx2 = (boxes[i, 2] - pad_x) / scale
        by2 = (boxes[i, 3] - pad_y) / scale
        bx1 = max(0, min(bx1, orig_w))
        by1 = max(0, min(by1, orig_h))
        bx2 = max(0, min(bx2, orig_w))
        by2 = max(0, min(by2, orig_h))
        results.append((int(bx1), int(by1), int(bx2), int(by2), float(confs[i])))

    return results
