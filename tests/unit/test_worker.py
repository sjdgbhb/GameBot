"""推理子进程 worker 单元测试 — 覆盖 inference/worker.py 中的纯函数和可 mock 逻辑。

覆盖范围：
- _load_config: 环境变量配置加载
- _extract_text: OCR 文本提取
- _extract_lines: OCR 逐行提取含坐标
- _letterbox: 等比缩放填充
- _nms: 非极大值抑制
- _send: JSON 协议输出
- _run_chest_detection: 宝箱检测完整流程（mock session）
- _handle_predict_combat: 战斗检测（mock session）
- _handle_capture_and_predict_combat: 截屏战斗检测含取消逻辑（mock）
"""

import json
import os
import tempfile
import unittest
from unittest.mock import MagicMock, patch

import numpy as np
import pytest
from PIL import Image

pytestmark = [pytest.mark.unit, pytest.mark.inference]


class TestWorkerLoadConfig(unittest.TestCase):
    """测试 _load_config 从环境变量加载配置。"""

    def setUp(self):
        """每个测试前清空全局 _cfg 和环境变量。"""
        from GameBot.inference import worker

        worker._cfg = {}
        self._old_env = os.environ.pop("JIUBING_INFERENCE_CONFIG", None)

    def tearDown(self):
        os.environ.pop("JIUBING_INFERENCE_CONFIG", None)
        if self._old_env is not None:
            os.environ["JIUBING_INFERENCE_CONFIG"] = self._old_env

    def test_load_config_from_env(self):
        """有环境变量时应解析为 dict。"""
        from GameBot.inference import worker

        os.environ["JIUBING_INFERENCE_CONFIG"] = json.dumps({"ocr_device": "gpu", "chest_conf": 0.7})
        worker._load_config()
        self.assertEqual(worker._cfg["ocr_device"], "gpu")
        self.assertEqual(worker._cfg["chest_conf"], 0.7)

    def test_load_config_empty_env(self):
        """无环境变量时应设为空 dict。"""
        from GameBot.inference import worker

        os.environ.pop("JIUBING_INFERENCE_CONFIG", None)
        worker._load_config()
        self.assertEqual(worker._cfg, {})

    def test_load_config_overwrites_previous(self):
        """多次调用应覆盖之前的配置。"""
        from GameBot.inference import worker

        os.environ["JIUBING_INFERENCE_CONFIG"] = json.dumps({"key1": "val1"})
        worker._load_config()
        self.assertEqual(worker._cfg, {"key1": "val1"})

        os.environ["JIUBING_INFERENCE_CONFIG"] = json.dumps({"key2": "val2"})
        worker._load_config()
        self.assertEqual(worker._cfg, {"key2": "val2"})


class TestWorkerExtractText(unittest.TestCase):
    """测试 _extract_text OCR 文本提取。"""

    def _make_result(self, txts):
        """创建 mock OCR result。"""
        result = MagicMock()
        result.txts = txts
        return result

    def test_normal_text(self):
        """正常文本应拼接返回。"""
        from GameBot.inference.worker import _extract_text

        result = self._make_result(["你好", "世界"])
        self.assertEqual(_extract_text(result), "你好世界")

    def test_empty_txts(self):
        """空 txts 应返回空字符串。"""
        from GameBot.inference.worker import _extract_text

        result = self._make_result([])
        self.assertEqual(_extract_text(result), "")

    def test_none_txts(self):
        """txts 为 None 应返回空字符串。"""
        from GameBot.inference.worker import _extract_text

        result = MagicMock()
        result.txts = None
        self.assertEqual(_extract_text(result), "")

    def test_no_txts_attr(self):
        """无 txts 属性应返回空字符串。"""
        from GameBot.inference.worker import _extract_text

        result = MagicMock(spec=[])
        self.assertEqual(_extract_text(result), "")

    def test_contains_empty_string(self):
        """txts 中包含空字符串应跳过。"""
        from GameBot.inference.worker import _extract_text

        result = self._make_result(["你好", "", "世界"])
        self.assertEqual(_extract_text(result), "你好世界")

    def test_contains_none(self):
        """txts 中包含 None 应跳过。"""
        from GameBot.inference.worker import _extract_text

        result = self._make_result(["你好", None, "世界"])
        self.assertEqual(_extract_text(result), "你好世界")


class TestWorkerExtractLines(unittest.TestCase):
    """测试 _extract_lines OCR 逐行提取含坐标。"""

    def _make_result(self, txts, boxes=None):
        """创建 mock OCR result。"""
        result = MagicMock()
        result.txts = txts
        result.boxes = boxes
        return result

    def test_normal_lines(self):
        """正常文本应返回逐行结果，按 y_center 排序。"""
        from GameBot.inference.worker import _extract_lines

        boxes = [
            [[10, 30], [50, 30], [50, 40], [10, 40]],  # y_center=35
            [[10, 10], [50, 10], [50, 20], [10, 20]],  # y_center=15
        ]
        result = self._make_result(["第二行", "第一行"], boxes)
        lines = _extract_lines(result)
        self.assertEqual(len(lines), 2)
        # 按 y_center 升序排列，第一行 y_center=15 在前
        self.assertEqual(lines[0]["text"], "第一行")
        self.assertAlmostEqual(lines[0]["y_center"], 15.0)
        self.assertEqual(lines[1]["text"], "第二行")
        self.assertAlmostEqual(lines[1]["y_center"], 35.0)

    def test_empty_txts(self):
        """空 txts 应返回空列表。"""
        from GameBot.inference.worker import _extract_lines

        result = self._make_result([])
        self.assertEqual(_extract_lines(result), [])

    def test_none_txts(self):
        """txts 为 None 应返回空列表。"""
        from GameBot.inference.worker import _extract_lines

        result = MagicMock()
        result.txts = None
        result.boxes = None
        self.assertEqual(_extract_lines(result), [])

    def test_no_boxes(self):
        """无 boxes 时坐标应为 0.0。"""
        from GameBot.inference.worker import _extract_lines

        result = self._make_result(["文本"], None)
        lines = _extract_lines(result)
        self.assertEqual(len(lines), 1)
        self.assertEqual(lines[0]["text"], "文本")
        self.assertEqual(lines[0]["x_center"], 0.0)
        self.assertEqual(lines[0]["y_center"], 0.0)

    def test_skip_empty_text(self):
        """空文本行应被跳过。"""
        from GameBot.inference.worker import _extract_lines

        boxes = [
            [[10, 10], [50, 10], [50, 20], [10, 20]],  # y_center=15
            [[10, 20], [50, 20], [50, 30], [10, 30]],  # 空，y_center=25
            [[10, 25], [50, 25], [50, 35], [10, 35]],  # None，y_center=30
            [[10, 30], [50, 30], [50, 40], [10, 40]],  # y_center=35
        ]
        result = self._make_result(["有内容", "", None, "也有内容"], boxes)
        lines = _extract_lines(result)
        self.assertEqual(len(lines), 2)
        self.assertEqual(lines[0]["text"], "有内容")
        self.assertEqual(lines[1]["text"], "也有内容")

    def test_boxes_shorter_than_txts(self):
        """boxes 数量少于 txts 时，超出部分坐标为 0.0。"""
        from GameBot.inference.worker import _extract_lines

        boxes = [[[10, 10], [20, 10], [20, 20], [10, 20]]]  # 只有 1 个 box，y_center=15
        result = self._make_result(["有坐标", "无坐标"], boxes)
        lines = _extract_lines(result)
        self.assertEqual(len(lines), 2)
        # 无坐标的行 y_center=0.0，排序后排在前面
        self.assertEqual(lines[0]["text"], "无坐标")
        self.assertEqual(lines[0]["x_center"], 0.0)
        self.assertEqual(lines[1]["text"], "有坐标")
        self.assertAlmostEqual(lines[1]["x_center"], 15.0)

    def test_x_center_calculation(self):
        """x_center 应为四角点 x 坐标的平均值。"""
        from GameBot.inference.worker import _extract_lines

        boxes = [[[0, 0], [100, 0], [100, 50], [0, 50]]]  # x_center=50, y_center=25
        result = self._make_result(["测试"], boxes)
        lines = _extract_lines(result)
        self.assertAlmostEqual(lines[0]["x_center"], 50.0)
        self.assertAlmostEqual(lines[0]["y_center"], 25.0)

    def test_merge_same_line_boxes(self):
        """同一行的多个文字框应合并为一行，按 x 排序拼接。"""
        from GameBot.inference.worker import _extract_lines

        boxes = [
            [[100, 10], [150, 10], [150, 30], [100, 30]],  # y_center=20, x_center=125
            [[10, 12], [90, 12], [90, 28], [10, 28]],     # y_center=20, x_center=50
            [[10, 60], [100, 60], [100, 80], [10, 80]],   # y_center=70, x_center=55
        ]
        result = self._make_result(["诸神战场", "九种兵器2", "第二行"], boxes)
        lines = _extract_lines(result)
        # 前两个框 y_center 接近，应合并为一行
        self.assertEqual(len(lines), 2)
        # 合并后按 x_center 排序：九种兵器2(x=50) + 诸神战场(x=125)
        self.assertEqual(lines[0]["text"], "九种兵器2诸神战场")
        self.assertEqual(lines[1]["text"], "第二行")


class TestWorkerLetterbox(unittest.TestCase):
    """测试 worker._letterbox 等比缩放逻辑。"""

    def test_square_image(self):
        """正方形图片无需填充。"""
        from GameBot.inference.worker import _letterbox

        img = Image.new("RGB", (100, 100))
        result, scale, pad_x, pad_y = _letterbox(img, 200)
        self.assertEqual(result.size, (200, 200))
        self.assertAlmostEqual(scale, 2.0)
        self.assertEqual(pad_x, 0)
        self.assertEqual(pad_y, 0)

    def test_landscape_image(self):
        """宽图应上下填充。"""
        from GameBot.inference.worker import _letterbox

        img = Image.new("RGB", (200, 100))
        result, scale, pad_x, pad_y = _letterbox(img, 100)
        self.assertEqual(result.size, (100, 100))
        self.assertAlmostEqual(scale, 0.5)
        self.assertEqual(pad_x, 0)
        self.assertEqual(pad_y, 25)

    def test_portrait_image(self):
        """高图应左右填充。"""
        from GameBot.inference.worker import _letterbox

        img = Image.new("RGB", (100, 200))
        result, scale, pad_x, pad_y = _letterbox(img, 100)
        self.assertEqual(result.size, (100, 100))
        self.assertAlmostEqual(scale, 0.5)
        self.assertEqual(pad_x, 25)
        self.assertEqual(pad_y, 0)

    def test_pad_color(self):
        """填充区域应为灰色 (114, 114, 114)。"""
        from GameBot.inference.worker import PAD_COLOR, _letterbox

        img = Image.new("RGB", (200, 100), (255, 0, 0))
        result, _, _, _ = _letterbox(img, 100)
        pixel = result.getpixel((0, 0))
        self.assertEqual(pixel[:3], PAD_COLOR)

    def test_exact_size(self):
        """图片恰好等于目标尺寸时无需缩放。"""
        from GameBot.inference.worker import _letterbox

        img = Image.new("RGB", (1280, 1280))
        result, scale, pad_x, pad_y = _letterbox(img, 1280)
        self.assertEqual(result.size, (1280, 1280))
        self.assertAlmostEqual(scale, 1.0)
        self.assertEqual(pad_x, 0)
        self.assertEqual(pad_y, 0)


class TestWorkerNMS(unittest.TestCase):
    """测试 worker._nms 非极大值抑制。"""

    def test_empty_input(self):
        """空输入应返回空列表。"""
        from GameBot.inference.worker import _nms

        boxes = np.array([]).reshape(0, 4)
        scores = np.array([])
        self.assertEqual(_nms(boxes, scores, 0.5), [])

    def test_single_box(self):
        """单个框应直接保留。"""
        from GameBot.inference.worker import _nms

        boxes = np.array([[10, 10, 50, 50]])
        scores = np.array([0.9])
        self.assertEqual(_nms(boxes, scores, 0.5), [0])

    def test_no_overlap_all_kept(self):
        """不重叠的框应全部保留。"""
        from GameBot.inference.worker import _nms

        boxes = np.array([[0, 0, 10, 10], [100, 100, 110, 110], [200, 200, 210, 210]])
        scores = np.array([0.9, 0.8, 0.7])
        result = _nms(boxes, scores, 0.5)
        self.assertEqual(len(result), 3)

    def test_high_overlap_suppressed(self):
        """高重叠低分框应被抑制。"""
        from GameBot.inference.worker import _nms

        boxes = np.array([[10, 10, 50, 50], [12, 12, 52, 52]])
        scores = np.array([0.9, 0.8])
        result = _nms(boxes, scores, 0.3)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0], 0)

    def test_keeps_highest_score(self):
        """应优先保留得分最高的框。"""
        from GameBot.inference.worker import _nms

        boxes = np.array([[10, 10, 50, 50], [12, 12, 52, 52], [100, 100, 140, 140]])
        scores = np.array([0.7, 0.95, 0.8])
        result = _nms(boxes, scores, 0.3)
        self.assertIn(1, result)
        self.assertNotIn(0, result)
        self.assertIn(2, result)


class TestWorkerSend(unittest.TestCase):
    """测试 _send JSON 协议输出。"""

    @patch("GameBot.inference.worker._REAL_STDOUT")
    def test_send_writes_json_line(self, mock_stdout):
        """_send 应写入 JSON + 换行并 flush。"""
        from GameBot.inference.worker import _send

        _send({"ready": True})
        written = mock_stdout.write.call_args[0][0]
        self.assertIn('"ready"', written)
        self.assertTrue(written.endswith("\n"))
        mock_stdout.flush.assert_called_once()

    @patch("GameBot.inference.worker._REAL_STDOUT")
    def test_send_ensure_ascii(self, mock_stdout):
        """_send 应使用 ensure_ascii=True 编码。"""
        from GameBot.inference.worker import _send

        _send({"text": "你好"})
        written = mock_stdout.write.call_args[0][0]
        # ensure_ascii=True 时中文被转义为 \uXXXX
        self.assertIn("\\u", written)
        self.assertNotIn("你好", written)


class TestWorkerRunChestDetection(unittest.TestCase):
    """测试 _run_chest_detection 宝箱检测流程（mock session）。"""

    def _make_mock_session(self, output_array):
        session = MagicMock()
        session.run.return_value = [output_array]
        session.get_inputs.return_value = [MagicMock(name="input")]
        return session

    def setUp(self):
        from GameBot.inference import worker

        worker._cfg = {"chest_input_size": 1280, "chest_conf": 0.5, "chest_iou": 0.5}
        worker._chest_session = None

    @patch("GameBot.inference.worker._get_chest_session")
    def test_no_detections(self, mock_session_fn):
        """无检测结果时应返回空列表。"""
        mock_session_fn.return_value = self._make_mock_session(np.zeros((1, 5, 1), dtype=np.float32))
        from GameBot.inference.worker import _run_chest_detection

        img = Image.new("RGB", (800, 600))
        result = _run_chest_detection(img)
        self.assertEqual(result, {"chests": []})

    @patch("GameBot.inference.worker._get_chest_session")
    def test_with_detection(self, mock_session_fn):
        """检测到宝箱时应返回坐标和置信度。"""
        fake_output = np.array([[[640], [320], [100], [100], [0.9]]], dtype=np.float32)
        mock_session_fn.return_value = self._make_mock_session(fake_output)
        from GameBot.inference.worker import _run_chest_detection

        img = Image.new("RGB", (800, 600))
        result = _run_chest_detection(img)
        self.assertEqual(len(result["chests"]), 1)
        x1, y1, x2, y2, conf = result["chests"][0]
        self.assertGreater(conf, 0.5)
        self.assertGreaterEqual(x1, 0)
        self.assertLessEqual(x2, 800)

    @patch("GameBot.inference.worker._get_chest_session")
    def test_low_confidence_filtered(self, mock_session_fn):
        """低于置信度阈值的检测应被过滤。"""
        fake_output = np.array([[[640], [320], [100], [100], [0.3]]], dtype=np.float32)
        mock_session_fn.return_value = self._make_mock_session(fake_output)
        from GameBot.inference.worker import _run_chest_detection

        img = Image.new("RGB", (800, 600))
        result = _run_chest_detection(img)
        self.assertEqual(result, {"chests": []})

    @patch("GameBot.inference.worker._get_chest_session")
    def test_coordinates_clamped_to_image(self, mock_session_fn):
        """坐标应被限制在原图范围内。"""
        # 检测框超出图像边界
        fake_output = np.array([[[10000], [10000], [100], [100], [0.9]]], dtype=np.float32)
        mock_session_fn.return_value = self._make_mock_session(fake_output)
        from GameBot.inference.worker import _run_chest_detection

        img = Image.new("RGB", (800, 600))
        result = _run_chest_detection(img)
        for x1, y1, x2, y2, conf in result["chests"]:
            self.assertGreaterEqual(x1, 0)
            self.assertLessEqual(x2, 800)
            self.assertGreaterEqual(y1, 0)
            self.assertLessEqual(y2, 600)


class TestWorkerHandlePredictCombat(unittest.TestCase):
    """测试 _handle_predict_combat 战斗检测（mock session）。"""

    def _make_combat_session(self, output_array):
        session = MagicMock()
        session.run.return_value = [output_array]
        return session

    def setUp(self):
        from GameBot.inference import worker

        worker._cfg = {"combat_img_w": 87, "combat_img_h": 61, "combat_threshold": 0.5}
        worker._combat_session = None

    @patch("GameBot.inference.worker._get_combat_session")
    @patch("GameBot.inference.worker.Image.open")
    def test_predict_combat_in_combat(self, mock_img_open, mock_session_fn):
        """prob > threshold 应返回 True。"""
        mock_session_fn.return_value = self._make_combat_session(np.array([[0.9]]))
        mock_img = MagicMock()
        mock_img.convert.return_value = Image.new("RGB", (87, 61))
        mock_img_open.return_value = mock_img

        from GameBot.inference.worker import _handle_predict_combat

        result = _handle_predict_combat(["/tmp/test.bmp"])
        self.assertEqual(result, {"combat": [True]})

    @patch("GameBot.inference.worker._get_combat_session")
    @patch("GameBot.inference.worker.Image.open")
    def test_predict_combat_not_in_combat(self, mock_img_open, mock_session_fn):
        """prob <= threshold 应返回 False。"""
        mock_session_fn.return_value = self._make_combat_session(np.array([[0.3]]))
        mock_img = MagicMock()
        mock_img.convert.return_value = Image.new("RGB", (87, 61))
        mock_img_open.return_value = mock_img

        from GameBot.inference.worker import _handle_predict_combat

        result = _handle_predict_combat(["/tmp/test.bmp"])
        self.assertEqual(result, {"combat": [False]})

    @patch("GameBot.inference.worker._get_combat_session")
    @patch("GameBot.inference.worker.Image.open")
    def test_predict_combat_batch(self, mock_img_open, mock_session_fn):
        """批量预测应返回与输入数量相同的结果。"""
        mock_session_fn.return_value = self._make_combat_session(np.array([[0.9], [0.1], [0.8]]))
        mock_img = MagicMock()
        mock_img.convert.return_value = Image.new("RGB", (87, 61))
        mock_img_open.return_value = mock_img

        from GameBot.inference.worker import _handle_predict_combat

        result = _handle_predict_combat(["/tmp/a.bmp", "/tmp/b.bmp", "/tmp/c.bmp"])
        self.assertEqual(result, {"combat": [True, False, True]})


class TestWorkerCapturePredictCombat(unittest.TestCase):
    """测试 _handle_capture_and_predict_combat 截屏战斗检测含取消逻辑。"""

    def _make_combat_session(self, output_array):
        session = MagicMock()
        session.run.return_value = [output_array]
        return session

    def setUp(self):
        from GameBot.inference import worker

        worker._cfg = {"combat_img_w": 87, "combat_img_h": 61, "combat_threshold": 0.5}
        worker._combat_session = None

    @patch("GameBot.inference.worker._get_combat_session")
    @patch("GameBot.inference.worker.ImageGrab")
    def test_normal_capture(self, mock_grab, mock_session_fn):
        """正常截屏检测应返回战斗状态列表。"""
        mock_session_fn.return_value = self._make_combat_session(np.array([[0.9], [0.1]]))
        mock_grab.grab.return_value = Image.new("RGB", (87, 61))

        from GameBot.inference.worker import _handle_capture_and_predict_combat

        result = _handle_capture_and_predict_combat(bbox=[0, 0, 87, 61], frame_count=2, frame_interval=0.01)
        self.assertEqual(result, {"combat": [True, False]})

    @patch("GameBot.inference.worker._get_combat_session")
    @patch("GameBot.inference.worker.ImageGrab")
    def test_cancel_file_present_from_start(self, mock_grab, mock_session_fn):
        """取消文件一开始就存在时应立即返回 cancelled。"""
        mock_session_fn.return_value = self._make_combat_session(np.array([]))

        with tempfile.NamedTemporaryFile(delete=False) as f:
            cancel_path = f.name

        try:
            from GameBot.inference.worker import _handle_capture_and_predict_combat

            result = _handle_capture_and_predict_combat(
                bbox=[0, 0, 87, 61],
                frame_count=5,
                frame_interval=0.01,
                cancel_file=cancel_path,
            )
            self.assertTrue(result.get("cancelled"))
            self.assertEqual(len(result["combat"]), 1)  # max(len(batch), 1) = max(0, 1) = 1
            self.assertFalse(result["combat"][0])
            # 取消文件应被删除
            self.assertFalse(os.path.exists(cancel_path))
        finally:
            if os.path.exists(cancel_path):
                os.remove(cancel_path)

    @patch("GameBot.inference.worker._get_combat_session")
    @patch("GameBot.inference.worker.ImageGrab")
    def test_cancel_file_created_midway(self, mock_grab, mock_session_fn):
        """截帧中途创建取消文件时应提前终止。"""
        mock_session_fn.return_value = self._make_combat_session(np.array([[0.9]]))

        # 创建一个临时文件作为取消信号
        with tempfile.NamedTemporaryFile(delete=False) as f:
            cancel_path = f.name
        os.remove(cancel_path)  # 先删除，模拟中途创建

        # 在第一帧后创建取消文件
        original_exists = os.path.exists
        call_count = [0]

        def mock_exists(path):
            if path == cancel_path:
                call_count[0] += 1
                return call_count[0] > 2  # 第三次检查时返回 True
            return original_exists(path)

        mock_grab.grab.return_value = Image.new("RGB", (87, 61))

        with patch("os.path.exists", side_effect=mock_exists):
            from GameBot.inference.worker import _handle_capture_and_predict_combat

            result = _handle_capture_and_predict_combat(
                bbox=[0, 0, 87, 61],
                frame_count=5,
                frame_interval=0.01,
                cancel_file=cancel_path,
            )
            self.assertTrue(result.get("cancelled"))


if __name__ == "__main__":
    unittest.main()
