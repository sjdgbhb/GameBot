"""推理子进程 worker —— 由 64 位 Python 运行（exe 打包用）。

合并三种推理能力在一个常驻子进程中：
1. OCR（RapidOCR / onnxruntime 后端）—— 图片文件识别文字
2. 宝箱检测（YOLOv8 ONNX）—— 图片文件目标检测
3. 战斗状态检测（分类 ONNX）—— 英雄头像图片二分类

截图统一由主进程 WGC 完成，本子进程只接收图片文件/路径，不再有截屏入口。

主进程通过行式 JSON 通信：
  请求：{"cmd": "ocr_from_file", "img_path": "C:/temp/xxx.png"}
        {"cmd": "ocr_lines_from_file", "img_path": "...", "merge_lines": true}
        {"cmd": "detect_chests", "img_path": "C:/temp/xxx.bmp"}
        {"cmd": "predict_combat", "img_paths": ["C:/temp/a.bmp", ...]}
        {"cmd": "quit"}
  响应：{"text": "..."}
        {"lines": [...]}
        {"chests": [[x1,y1,x2,y2,conf], ...]}
        {"combat": [true, false, ...]}
        {"ready": true}
        {"error": "..."}

配置通过环境变量 JIUBING_INFERENCE_CONFIG 传入（JSON 字符串），包含：
  - ocr_device: "cpu" 或 "gpu"
  - chest_model_path: 宝箱检测模型路径
  - combat_model_path: 战斗状态模型路径
  - chest_input_size: 宝箱模型输入尺寸（默认 1280）
  - chest_conf: 置信度阈值
  - chest_iou: NMS IoU 阈值
  - combat_img_w / combat_img_h: 战斗模型输入尺寸
  - combat_threshold: 战斗分类阈值
  - ai_device: AI 推理设备
"""

import json
import os
import sys

import numpy as np
from PIL import Image

try:
    from . import model_loader
except ImportError:
    import model_loader

# 协议 JSON 必须独占 stdout。第三方库可能往 stdout print 噪声，破坏行式 JSON 协议。
# 故启动时把真实 stdout 的 fd 复制一份专供 _send 使用，再把 sys.stdout 让给第三方。
_REAL_STDOUT = None

# 全局配置和模型实例
_cfg = {}
_ocr = None
_chest_session = None
_combat_session = None


def _init_stdout():
    global _REAL_STDOUT
    _REAL_STDOUT = os.fdopen(os.dup(sys.stdout.fileno()), "w", encoding="utf-8")
    sys.stdout = sys.stderr


def _send(obj: dict):
    _REAL_STDOUT.write(json.dumps(obj, ensure_ascii=True) + "\n")
    _REAL_STDOUT.flush()


def _load_config():
    """从环境变量 JIUBING_INFERENCE_CONFIG 加载 JSON 配置。"""
    global _cfg
    raw = os.environ.get("JIUBING_INFERENCE_CONFIG", "")
    if raw:
        _cfg = json.loads(raw)
    else:
        _cfg = {}


# ── OCR ──────────────────────────────────────────────


def _build_ocr():
    from rapidocr import RapidOCR

    device = _cfg.get("ocr_device", "cpu")
    params = {
        "Global.use_cls": False,
        "Global.log_level": "ERROR",
        "Det.limit_type": "max",
        "Det.limit_side_len": 960,
        "EngineConfig.onnxruntime.use_cuda": device == "gpu",
    }
    try:
        return RapidOCR(params=params)
    except Exception as e:
        sys.stderr.write(f"[worker] RapidOCR 构造失败(device={device}): {e}\n回退 CPU\n")
        params["EngineConfig.onnxruntime.use_cuda"] = False
        return RapidOCR(params=params)


def _extract_text(result) -> str:
    txts = getattr(result, "txts", None)
    if not txts:
        return ""
    return "".join(t for t in txts if t)


def _extract_lines(result, merge_lines: bool = True) -> list:
    """提取逐行文本及中心坐标。

    RapidOCR result.txts 为文本列表，result.boxes 为对应边界框坐标列表。
    merge_lines=True 时将 y_center 接近的框合并为一行，按 x_center 排序拼接文字。
    merge_lines=False 时保持每个框独立，适用于网格布局（如搜索结果）。
    返回 [{"text": "...", "x_center": float, "y_center": float}, ...]，按 y_center 升序排列。
    """
    txts = getattr(result, "txts", None)
    boxes = getattr(result, "boxes", None)
    if not txts:
        return []
    raw = []
    for i, txt in enumerate(txts):
        if not txt:
            continue
        x_center = 0.0
        y_center = 0.0
        height = 0.0
        if boxes is not None and i < len(boxes):
            box = boxes[i]
            xs = [p[0] for p in box]
            ys = [p[1] for p in box]
            x_center = float(sum(xs) / len(xs))
            y_center = float(sum(ys) / len(ys))
            height = float(max(ys) - min(ys))
        raw.append({"text": txt, "x_center": x_center, "y_center": y_center, "height": height})
    if not raw:
        return []
    raw.sort(key=lambda b: b["y_center"])
    if not merge_lines:
        # 不合并，每个框独立返回（适用于网格布局）
        return [{"text": b["text"], "x_center": b["x_center"], "y_center": b["y_center"]} for b in raw]
    # 合并同行框：y_center 差异小于行高的一半视为同一行
    merged = []
    current_row = [raw[0]]
    for box in raw[1:]:
        ref_y = current_row[0]["y_center"]
        threshold = max(b["height"] for b in current_row) * 0.5 if current_row else 10
        if abs(box["y_center"] - ref_y) <= max(threshold, 10):
            current_row.append(box)
        else:
            merged.append(current_row)
            current_row = [box]
    merged.append(current_row)
    lines = []
    for row in merged:
        row.sort(key=lambda b: b["x_center"])
        text = "".join(b["text"] for b in row)
        x_center = sum(b["x_center"] for b in row) / len(row)
        y_center = sum(b["y_center"] for b in row) / len(row)
        lines.append({"text": text, "x_center": x_center, "y_center": y_center})
    lines.sort(key=lambda l: l["y_center"])
    return lines


def _handle_ocr_from_file(img_path: str) -> dict:
    """从图片文件 OCR（大漠截图存盘后读图），支持后台窗口截图识别。"""
    if _ocr is None:
        raise RuntimeError("OCR 引擎未初始化")
    img = Image.open(img_path).convert("RGB")
    result = _ocr(np.array(img))
    return {"text": _extract_text(result)}


def _handle_ocr_lines_from_file(img_path: str, merge_lines: bool = True) -> dict:
    """从图片文件 OCR 逐行结果（大漠截图存盘后读图），支持后台窗口截图识别。"""
    if _ocr is None:
        raise RuntimeError("OCR 引擎未初始化")
    img = Image.open(img_path).convert("RGB")
    result = _ocr(np.array(img))
    return {"lines": _extract_lines(result, merge_lines=merge_lines)}


# ── 宝箱检测 ─────────────────────────────────────────

PAD_COLOR = (114, 114, 114)


def _get_chest_session():
    global _chest_session
    model_path = _cfg.get("chest_model_path", "")
    if not model_path:
        raise FileNotFoundError("宝箱检测模型路径未配置")
    session = model_loader.get_session(model_path, _cfg.get("ai_device", "cpu"))
    if _chest_session is None:
        _chest_session = session
        sys.stderr.write(f"[worker] 宝箱检测模型已加载: {model_path}\n")
    return _chest_session


def _letterbox(img: Image.Image, target_size: int):
    w, h = img.size
    scale = min(target_size / w, target_size / h)
    new_w = int(w * scale)
    new_h = int(h * scale)
    resized = img.resize((new_w, new_h), Image.BILINEAR)
    canvas = Image.new("RGB", (target_size, target_size), PAD_COLOR)
    pad_x = (target_size - new_w) // 2
    pad_y = (target_size - new_h) // 2
    canvas.paste(resized, (pad_x, pad_y))
    return canvas, scale, pad_x, pad_y


def _nms(boxes: np.ndarray, scores: np.ndarray, iou_threshold: float) -> list:
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


def _run_chest_detection(img: Image.Image) -> dict:
    """对 PIL Image 执行宝箱检测，返回 {"chests": [[x1,y1,x2,y2,conf], ...]}。"""
    session = _get_chest_session()
    orig_w, orig_h = img.size

    input_size = int(_cfg.get("chest_input_size", 1280))
    conf_threshold = float(_cfg.get("chest_conf", 0.5))
    iou_threshold = float(_cfg.get("chest_iou", 0.5))

    letterboxed, scale, pad_x, pad_y = _letterbox(img, input_size)
    arr = np.array(letterboxed).transpose(2, 0, 1).astype(np.float32) / 255.0
    arr = np.expand_dims(arr, axis=0)

    output = session.run(None, {session.get_inputs()[0].name: arr})[0]
    predictions = output[0].T  # [N, 5]: cx, cy, w, h, conf

    scores = predictions[:, 4]
    mask = scores > conf_threshold
    filtered = predictions[mask]

    if len(filtered) == 0:
        return {"chests": []}

    cx, cy, w, h = filtered[:, 0], filtered[:, 1], filtered[:, 2], filtered[:, 3]
    confs = filtered[:, 4]
    x1 = cx - w / 2
    y1 = cy - h / 2
    x2 = cx + w / 2
    y2 = cy + h / 2
    boxes = np.stack([x1, y1, x2, y2], axis=1)

    keep_idx = _nms(boxes, confs, iou_threshold)

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
        results.append([int(bx1), int(by1), int(bx2), int(by2), float(confs[i])])

    return {"chests": results}


def _handle_detect_chests(img_path: str) -> dict:
    img = Image.open(img_path).convert("RGB")
    return _run_chest_detection(img)


# ── 战斗状态检测 ──────────────────────────────────────


def _get_combat_session():
    global _combat_session
    model_path = _cfg.get("combat_model_path", "")
    if not model_path:
        raise FileNotFoundError("战斗状态模型路径未配置")
    session = model_loader.get_session(model_path, _cfg.get("ai_device", "cpu"))
    if _combat_session is None:
        _combat_session = session
        sys.stderr.write(f"[worker] 战斗状态模型已加载: {model_path}\n")
    return _combat_session


def _handle_predict_combat(img_paths: list) -> dict:
    if not img_paths:
        return {"combat": []}
    session = _get_combat_session()
    img_w = int(_cfg.get("combat_img_w", 87))
    img_h = int(_cfg.get("combat_img_h", 61))
    threshold = float(_cfg.get("combat_threshold", 0.5))

    batch = []
    for path in img_paths:
        img = Image.open(path).convert("RGB").resize((img_w, img_h))
        arr = np.array(img).transpose(2, 0, 1).astype(np.float32) / 255.0
        batch.append(arr)
    batch = np.stack(batch)

    result = session.run(["output"], {"input": batch})
    probs = result[0].flatten()
    combat = [bool(p > threshold) for p in probs]
    return {"combat": combat}


# ── 主循环 ────────────────────────────────────────────


def main():
    _init_stdout()
    _load_config()

    # 初始化 OCR 引擎
    global _ocr
    _ocr = _build_ocr()

    # 预加载 AI 模型（可配置跳过）
    if _cfg.get("load_chest", True):
        try:
            _get_chest_session()
        except (ImportError, OSError, RuntimeError) as e:
            sys.stderr.write(f"[worker] 宝箱检测模型预加载失败: {e}\n")
    if _cfg.get("load_combat", True):
        try:
            _get_combat_session()
        except (ImportError, OSError, RuntimeError) as e:
            sys.stderr.write(f"[worker] 战斗状态模型预加载失败: {e}\n")

    _send({"ready": True})

    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            cmd = json.loads(line)
        except (json.JSONDecodeError, ValueError) as e:
            _send({"error": f"bad json: {e}"})
            continue

        action = cmd.get("cmd", "")
        try:
            if action == "quit":
                break
            elif action == "ocr_from_file":
                result = _handle_ocr_from_file(cmd.get("img_path", ""))
                _send(result)
            elif action == "ocr_lines_from_file":
                result = _handle_ocr_lines_from_file(cmd.get("img_path", ""), merge_lines=cmd.get("merge_lines", True))
                _send(result)
            elif action == "detect_chests":
                result = _handle_detect_chests(cmd.get("img_path", ""))
                _send(result)
            elif action == "predict_combat":
                result = _handle_predict_combat(cmd.get("img_paths", []))
                _send(result)
            else:
                _send({"error": f"unknown cmd: {action}"})
        except Exception as e:
            _send({"error": str(e)})


if __name__ == "__main__":
    main()
