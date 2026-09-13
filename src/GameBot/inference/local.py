"""进程内推理客户端 — 在 3.12 主环境中直接加载模型，无需子进程。

模型加载通过 inference.model_loader 统一管理，后处理工具（_letterbox / _nms）
复用 inference.worker 中的实现。
"""

import os
from typing import List, Tuple

from PIL import Image, ImageGrab

from GameBot.config import config
from GameBot.utils import logger

from . import model_loader


class LocalInferenceClient:
    """进程内推理客户端，提供 OCR、宝箱检测、战斗检测三种能力。

    模型懒加载：首次调用对应方法时才初始化引擎。
    """

    def __init__(self):
        self.load_chest = True
        self.load_combat = True
        self._ocr = None
        self._chest_session = None
        self._combat_session = None
        self._cfg = self._build_config()

    def _build_config(self) -> dict:
        """从项目配置中提取推理参数。"""
        inf_cfg = config.get("inference", {})
        models_dir = inf_cfg.get("models_dir", "src/GameBot/resources/models")
        models_abs = os.path.join(config.project_root, models_dir)

        return {
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

    def start(self):
        """兼容接口：进程内无需启动子进程，仅预加载模型。"""
        if self._ocr is None:
            self._ocr = self._build_ocr()
        if self.load_chest and self._chest_session is None:
            try:
                self._get_chest_session()
            except Exception as e:
                logger.warning(f"宝箱检测模型预加载失败: {e}")
        if self.load_combat and self._combat_session is None:
            try:
                self._get_combat_session()
            except Exception as e:
                logger.warning(f"战斗状态模型预加载失败: {e}")

    def close(self):
        """兼容接口：进程内无需关闭子进程。"""
        self._ocr = None
        self._chest_session = None
        self._combat_session = None

    # ---------- OCR ----------

    def _build_ocr(self):
        from rapidocr import RapidOCR

        device = self._cfg.get("ocr_device", "cpu")
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
            logger.warning(f"RapidOCR 构造失败(device={device}): {e}，回退 CPU")
            params["EngineConfig.onnxruntime.use_cuda"] = False
            return RapidOCR(params=params)

    def _ocr_screen(self, bbox):
        import numpy as np

        if self._ocr is None:
            self._ocr = self._build_ocr()
        img = ImageGrab.grab(bbox=tuple(bbox), all_screens=True)
        result = self._ocr(np.array(img))
        return result

    def ocr_screen(self, bbox) -> str:
        """对屏幕区域 bbox=[x1,y1,x2,y2] 截屏并 OCR，返回识别文字。"""
        try:
            result = self._ocr_screen(bbox)
            txts = getattr(result, "txts", None)
            if not txts:
                return ""
            return "".join(t for t in txts if t)
        except Exception as e:
            logger.debug(f"OCR 识别异常: {e}")
            return ""

    def ocr_lines(self, bbox, merge_lines: bool = True) -> list:
        """对屏幕区域截屏并 OCR，返回逐行结果（含 y 坐标）。

        :param merge_lines: True 时合并同一行的多个文字框（适用于单列文本）；
                            False 时保持每个文字框独立（适用于网格布局，如搜索结果）。
        """
        try:
            result = self._ocr_screen(bbox)
            return self._merge_ocr_result(result, merge_lines=merge_lines)
        except Exception as e:
            logger.debug(f"OCR 逐行识别异常: {e}")
            return []

    def _ocr_from_file_impl(self, img_path: str):
        """从图片文件加载并 OCR，返回 RapidOCR result 对象。"""
        import numpy as np

        if self._ocr is None:
            self._ocr = self._build_ocr()
        img = Image.open(img_path).convert("RGB")
        return self._ocr(np.array(img))

    def _ocr_from_array_impl(self, img):
        """对内存图像 OCR，返回 RapidOCR result 对象。

        :param img: ndarray，BGRA（WGC 帧，4 通道）或 RGB（3 通道）
        """
        import numpy as np

        if self._ocr is None:
            self._ocr = self._build_ocr()
        arr = np.asarray(img)
        if arr.ndim == 3 and arr.shape[2] == 4:
            arr = np.ascontiguousarray(arr[:, :, [2, 1, 0]])  # BGRA → RGB
        return self._ocr(arr)

    def ocr_from_array(self, img) -> str:
        """对内存图像（WGC 帧裁剪区域）OCR，返回识别文字。"""
        try:
            result = self._ocr_from_array_impl(img)
            txts = getattr(result, "txts", None)
            if not txts:
                return ""
            return "".join(t for t in txts if t)
        except Exception as e:
            logger.debug(f"OCR 数组识别异常: {e}")
            return ""

    def ocr_lines_from_array(self, img, merge_lines: bool = True) -> list:
        """对内存图像 OCR 逐行结果，参数含义同 ocr_lines_from_file。"""
        try:
            result = self._ocr_from_array_impl(img)
            return self._merge_ocr_result(result, merge_lines=merge_lines)
        except Exception as e:
            logger.debug(f"OCR 数组逐行识别异常: {e}")
            return []

    def ocr_from_file(self, img_path: str) -> str:
        """从图片文件 OCR（大漠截图存盘后读图），支持后台窗口截图识别。"""
        try:
            result = self._ocr_from_file_impl(img_path)
            txts = getattr(result, "txts", None)
            if not txts:
                return ""
            return "".join(t for t in txts if t)
        except Exception as e:
            logger.debug(f"OCR 文件识别异常: {e}")
            return ""

    def ocr_lines_from_file(self, img_path: str, merge_lines: bool = True) -> list:
        """从图片文件 OCR 逐行结果，支持后台窗口截图识别。

        :param merge_lines: True 时合并同一行的多个文字框（适用于单列文本）；
                            False 时保持每个文字框独立（适用于网格布局，如搜索结果）。
        """
        try:
            result = self._ocr_from_file_impl(img_path)
            return self._merge_ocr_result(result, merge_lines=merge_lines)
        except Exception as e:
            logger.debug(f"OCR 文件逐行识别异常: {e}")
            return []

    @staticmethod
    def _merge_ocr_result(result, merge_lines: bool = True) -> list:
        """将 OCR 检测结果按行合并，返回 [{text, x_center, y_center}]。

        RapidOCR 返回的是一个个独立文字检测框，同一行的文字可能被拆成多个框。
        merge_lines=True 时将 y_center 接近的框合并为一行，按 x_center 排序拼接文字。
        merge_lines=False 时保持每个框独立，适用于网格布局（如搜索结果）。
        """
        txts = getattr(result, "txts", None)
        boxes = getattr(result, "boxes", None)
        if not txts:
            return []
        # 收集所有文字框
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
        # 按 y_center 排序
        raw.sort(key=lambda b: b["y_center"])
        if not merge_lines:
            # 不合并，每个框独立返回（适用于网格布局）
            return [{"text": b["text"], "x_center": b["x_center"], "y_center": b["y_center"]} for b in raw]
        # 合并同行框：y_center 差异小于行高的一半视为同一行
        merged = []
        current_row = [raw[0]]
        for box in raw[1:]:
            ref_y = current_row[0]["y_center"]
            # 行高阈值：取当前行最大高度的一半，默认 10 像素
            threshold = max(b["height"] for b in current_row) * 0.5 if current_row else 10
            if abs(box["y_center"] - ref_y) <= max(threshold, 10):
                current_row.append(box)
            else:
                merged.append(current_row)
                current_row = [box]
        merged.append(current_row)
        # 每行按 x_center 排序，拼接文字
        lines = []
        for row in merged:
            row.sort(key=lambda b: b["x_center"])
            text = "".join(b["text"] for b in row)
            x_center = sum(b["x_center"] for b in row) / len(row)
            y_center = sum(b["y_center"] for b in row) / len(row)
            lines.append({"text": text, "x_center": x_center, "y_center": y_center})
        lines.sort(key=lambda l: l["y_center"])
        return lines

    # ---------- 宝箱检测 ----------

    def _get_chest_session(self):
        model_path = self._cfg.get("chest_model_path", "")
        if not model_path:
            raise FileNotFoundError("宝箱检测模型路径未配置")
        session = model_loader.get_session(model_path, self._cfg.get("ai_device", "cpu"))
        if self._chest_session is None:
            self._chest_session = session
            logger.info(f"宝箱检测模型已加载: {model_path}")
        return self._chest_session

    def _run_chest_detection(self, img):
        """对 PIL Image 执行宝箱检测，返回 [(x1,y1,x2,y2,conf), ...]。"""
        import numpy as np

        from GameBot.inference.worker import _letterbox, _nms

        session = self._get_chest_session()
        orig_w, orig_h = img.size

        input_size = int(self._cfg.get("chest_input_size", 1280))
        conf_threshold = float(self._cfg.get("chest_conf", 0.5))
        iou_threshold = float(self._cfg.get("chest_iou", 0.5))

        letterboxed, scale, pad_x, pad_y = _letterbox(img, input_size)
        arr = np.array(letterboxed).transpose(2, 0, 1).astype(np.float32) / 255.0
        arr = np.expand_dims(arr, axis=0)

        output = session.run(None, {session.get_inputs()[0].name: arr})[0]
        predictions = output[0].T

        scores = predictions[:, 4]
        mask = scores > conf_threshold
        filtered = predictions[mask]

        if len(filtered) == 0:
            return []

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
            results.append((int(bx1), int(by1), int(bx2), int(by2), float(confs[i])))
        return results

    def detect_chests(self, img_path: str) -> List[Tuple[int, int, int, int, float]]:
        """对指定图片文件进行宝箱检测。"""
        try:
            img = Image.open(img_path).convert("RGB")
            return self._run_chest_detection(img)
        except Exception as e:
            logger.error(f"宝箱检测异常: {e}")
            return []

    def capture_and_detect_chests(self, bbox) -> List[Tuple[int, int, int, int, float]]:
        """截屏 + 宝箱检测，无需写临时文件。"""
        try:
            if bbox:
                img = ImageGrab.grab(bbox=tuple(bbox), all_screens=True)
            else:
                img = ImageGrab.grab(all_screens=True)
            img = img.convert("RGB")
            return self._run_chest_detection(img)
        except Exception as e:
            logger.error(f"宝箱检测异常: {e}")
            return []

    # ---------- 战斗状态检测 ----------

    def _get_combat_session(self):
        model_path = self._cfg.get("combat_model_path", "")
        if not model_path:
            raise FileNotFoundError("战斗状态模型路径未配置")
        session = model_loader.get_session(model_path, self._cfg.get("ai_device", "cpu"))
        if self._combat_session is None:
            self._combat_session = session
            logger.info(f"战斗状态模型已加载: {model_path}")
        return self._combat_session

    def predict_combat_batch(self, img_paths: List[str]) -> List[bool]:
        """对多张头像图片批量预测战斗状态。"""
        if not img_paths:
            return []
        try:
            import numpy as np

            session = self._get_combat_session()
            img_w = int(self._cfg.get("combat_img_w", 87))
            img_h = int(self._cfg.get("combat_img_h", 61))
            threshold = float(self._cfg.get("combat_threshold", 0.5))

            batch = []
            for path in img_paths:
                img = Image.open(path).convert("RGB").resize((img_w, img_h))
                arr = np.array(img).transpose(2, 0, 1).astype(np.float32) / 255.0
                batch.append(arr)
            batch = np.stack(batch)

            result = session.run(["output"], {"input": batch})
            probs = result[0].flatten()
            return [bool(p > threshold) for p in probs]
        except Exception as e:
            logger.error(f"战斗检测异常: {e}")
            return [False] * len(img_paths)

    def capture_and_predict_combat(
        self, bbox, frame_count: int = 10, frame_interval: float = 0.3, cancel_file: str = ""
    ) -> List[bool]:
        """截屏 + 战斗检测，无需写临时文件。"""
        try:
            import time as _time

            import numpy as np

            session = self._get_combat_session()
            img_w = int(self._cfg.get("combat_img_w", 87))
            img_h = int(self._cfg.get("combat_img_h", 61))
            threshold = float(self._cfg.get("combat_threshold", 0.5))

            batch = []
            for i in range(frame_count):
                if cancel_file and os.path.exists(cancel_file):
                    break
                img = ImageGrab.grab(bbox=tuple(bbox), all_screens=True)
                img = img.convert("RGB").resize((img_w, img_h))
                arr = np.array(img).transpose(2, 0, 1).astype(np.float32) / 255.0
                batch.append(arr)
                if i < frame_count - 1 and not (cancel_file and os.path.exists(cancel_file)):
                    _time.sleep(frame_interval)
            if cancel_file and os.path.exists(cancel_file):
                try:
                    os.remove(cancel_file)
                except OSError:
                    pass
                return [False] * max(len(batch), 1)
            if not batch:
                return [False] * frame_count
            batch = np.stack(batch)

            result = session.run(["output"], {"input": batch})
            probs = result[0].flatten()
            return [bool(p > threshold) for p in probs]
        except Exception as e:
            logger.error(f"战斗检测异常: {e}")
            return [False] * frame_count
