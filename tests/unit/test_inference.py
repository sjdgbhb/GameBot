"""推理层单元测试 — 覆盖 inference/ 下的纯 Python 逻辑。

覆盖范围：
- worker: _letterbox 等比缩放、_nms 非极大值抑制、_run_chest_detection 后处理
- worker: _handle_predict_combat 战斗检测推理逻辑
- model_loader: provider 选择与 session 缓存
"""

import unittest
from unittest.mock import MagicMock, patch

import numpy as np
import pytest
from PIL import Image

pytestmark = [pytest.mark.unit, pytest.mark.inference]


class TestChestDetectorLetterbox(unittest.TestCase):
    """测试 worker._letterbox 等比缩放逻辑。"""

    def test_letterbox_square(self):
        """正方形图片无需填充，直接缩放。"""
        from GameBot.inference.worker import _letterbox

        img = Image.new("RGB", (100, 100))
        result, scale, pad_x, pad_y = _letterbox(img, 200)
        self.assertEqual(result.size, (200, 200))
        self.assertAlmostEqual(scale, 2.0)
        self.assertEqual(pad_x, 0)
        self.assertEqual(pad_y, 0)

    def test_letterbox_landscape(self):
        """宽图应上下填充灰色。"""
        from GameBot.inference.worker import _letterbox

        img = Image.new("RGB", (200, 100))
        result, scale, pad_x, pad_y = _letterbox(img, 100)
        self.assertEqual(result.size, (100, 100))
        self.assertAlmostEqual(scale, 0.5)
        self.assertEqual(pad_x, 0)
        self.assertEqual(pad_y, 25)  # (100 - 50) / 2

    def test_letterbox_portrait(self):
        """高图应左右填充灰色。"""
        from GameBot.inference.worker import _letterbox

        img = Image.new("RGB", (100, 200))
        result, scale, pad_x, pad_y = _letterbox(img, 100)
        self.assertEqual(result.size, (100, 100))
        self.assertAlmostEqual(scale, 0.5)
        self.assertEqual(pad_x, 25)
        self.assertEqual(pad_y, 0)

    def test_letterbox_pad_color(self):
        """填充区域应为灰色 (114, 114, 114)。"""
        from GameBot.inference.worker import PAD_COLOR, _letterbox

        img = Image.new("RGB", (200, 100), (255, 0, 0))
        result, scale, pad_x, pad_y = _letterbox(img, 100)
        # 检查填充区域颜色
        pixel = result.getpixel((0, 0))
        self.assertEqual(pixel[:3], PAD_COLOR)

    def test_letterbox_no_upscale_needed(self):
        """图片恰好等于目标尺寸时无需缩放。"""
        from GameBot.inference.worker import _letterbox

        img = Image.new("RGB", (1280, 1280))
        result, scale, pad_x, pad_y = _letterbox(img, 1280)
        self.assertEqual(result.size, (1280, 1280))
        self.assertAlmostEqual(scale, 1.0)
        self.assertEqual(pad_x, 0)
        self.assertEqual(pad_y, 0)


class TestChestDetectorNMS(unittest.TestCase):
    """测试 worker._nms 非极大值抑制。"""

    def test_nms_empty(self):
        """空输入应返回空列表。"""
        from GameBot.inference.worker import _nms

        boxes = np.array([]).reshape(0, 4)
        scores = np.array([])
        result = _nms(boxes, scores, 0.5)
        self.assertEqual(result, [])

    def test_nms_single_box(self):
        """单个框应直接保留。"""
        from GameBot.inference.worker import _nms

        boxes = np.array([[10, 10, 50, 50]])
        scores = np.array([0.9])
        result = _nms(boxes, scores, 0.5)
        self.assertEqual(result, [0])

    def test_nms_no_overlap(self):
        """不重叠的框应全部保留。"""
        from GameBot.inference.worker import _nms

        boxes = np.array(
            [
                [0, 0, 10, 10],
                [100, 100, 110, 110],
                [200, 200, 210, 210],
            ]
        )
        scores = np.array([0.9, 0.8, 0.7])
        result = _nms(boxes, scores, 0.5)
        self.assertEqual(len(result), 3)

    def test_nms_high_overlap_suppressed(self):
        """高重叠低分框应被抑制。"""
        from GameBot.inference.worker import _nms

        boxes = np.array(
            [
                [10, 10, 50, 50],
                [12, 12, 52, 52],  # 与第一个框高度重叠
            ]
        )
        scores = np.array([0.9, 0.8])
        result = _nms(boxes, scores, 0.3)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0], 0)  # 保留高分框

    def test_nms_low_threshold_keeps_all(self):
        """IoU 阈值很低时重叠框也被保留。"""
        from GameBot.inference.worker import _nms

        boxes = np.array(
            [
                [10, 10, 50, 50],
                [12, 12, 52, 52],
            ]
        )
        scores = np.array([0.9, 0.8])
        result = _nms(boxes, scores, 0.95)  # IoU < 0.95，都保留
        self.assertEqual(len(result), 2)

    def test_nms_keeps_highest_score(self):
        """NMS 应优先保留得分最高的框。"""
        from GameBot.inference.worker import _nms

        boxes = np.array(
            [
                [10, 10, 50, 50],
                [12, 12, 52, 52],
                [100, 100, 140, 140],
            ]
        )
        scores = np.array([0.7, 0.95, 0.8])  # 第二个框得分最高
        result = _nms(boxes, scores, 0.3)
        # 前两个框高度重叠，保留得分更高的第二个
        self.assertIn(1, result)
        self.assertNotIn(0, result)
        self.assertIn(2, result)  # 第三个不重叠，保留


class TestChestDetectorDetect(unittest.TestCase):
    """测试 worker._run_chest_detection 完整流程（mock ONNX session）。"""

    def _make_mock_session(self, output_array):
        """创建 mock ONNX session，run 返回指定数组。"""
        session = MagicMock()
        session.run.return_value = [output_array]
        session.get_inputs.return_value = [MagicMock(name="input")]
        return session

    def setUp(self):
        from GameBot.inference import worker

        self._worker = worker
        self._orig_cfg = worker._cfg.copy()
        worker._cfg = {"chest_input_size": 1280, "chest_conf": 0.5, "chest_iou": 0.5}

    def tearDown(self):
        self._worker._cfg = self._orig_cfg

    @patch("GameBot.inference.worker._get_chest_session")
    def test_detect_no_chests(self, mock_session):
        """无检测结果时应返回空列表。"""
        mock_session.return_value = self._make_mock_session(np.zeros((1, 5, 1), dtype=np.float32))
        img = Image.new("RGB", (800, 600))
        result = self._worker._run_chest_detection(img)
        self.assertEqual(result, {"chests": []})

    @patch("GameBot.inference.worker._get_chest_session")
    def test_detect_with_chest(self, mock_session):
        """检测到宝箱时应返回坐标和置信度。"""
        fake_output = np.array([[[640], [320], [100], [100], [0.9]]], dtype=np.float32)
        mock_session.return_value = self._make_mock_session(fake_output)
        img = Image.new("RGB", (800, 600))
        result = self._worker._run_chest_detection(img)
        self.assertEqual(len(result["chests"]), 1)
        x1, y1, x2, y2, conf = result["chests"][0]
        self.assertGreater(conf, 0.5)
        self.assertGreaterEqual(x1, 0)
        self.assertLessEqual(x2, 800)
        self.assertGreaterEqual(y1, 0)
        self.assertLessEqual(y2, 600)

    @patch("GameBot.inference.worker._get_chest_session")
    def test_detect_low_confidence_filtered(self, mock_session):
        """低于置信度阈值的检测应被过滤。"""
        self._worker._cfg["chest_conf"] = 0.95
        fake_output = np.array([[[640], [320], [100], [100], [0.3]]], dtype=np.float32)
        mock_session.return_value = self._make_mock_session(fake_output)
        img = Image.new("RGB", (800, 600))
        result = self._worker._run_chest_detection(img)
        self.assertEqual(result, {"chests": []})


class TestCombatDetector(unittest.TestCase):
    """测试 worker._handle_predict_combat 推理逻辑。"""

    def _make_combat_session(self, output_array):
        """创建 mock combat session。"""
        session = MagicMock()
        session.run.return_value = [output_array]
        return session

    def setUp(self):
        from GameBot.inference import worker

        self._worker = worker
        self._orig_cfg = worker._cfg.copy()
        worker._cfg = {"combat_img_w": 87, "combat_img_h": 61, "combat_threshold": 0.5}

    def tearDown(self):
        self._worker._cfg = self._orig_cfg

    @patch("GameBot.inference.worker.Image.open")
    @patch("GameBot.inference.worker._get_combat_session")
    def test_predict_combat_in_combat(self, mock_session, mock_open):
        """战斗中（prob > threshold）应返回 True。"""
        mock_session.return_value = self._make_combat_session(np.array([0.9]))
        mock_open.return_value = Image.new("RGB", (87, 61))
        result = self._worker._handle_predict_combat(["/fake/a.bmp"])
        self.assertEqual(result, {"combat": [True]})

    @patch("GameBot.inference.worker.Image.open")
    @patch("GameBot.inference.worker._get_combat_session")
    def test_predict_combat_not_in_combat(self, mock_session, mock_open):
        """非战斗（prob <= threshold）应返回 False。"""
        mock_session.return_value = self._make_combat_session(np.array([0.3]))
        mock_open.return_value = Image.new("RGB", (87, 61))
        result = self._worker._handle_predict_combat(["/fake/a.bmp"])
        self.assertEqual(result, {"combat": [False]})

    @patch("GameBot.inference.worker.Image.open")
    @patch("GameBot.inference.worker._get_combat_session")
    def test_predict_combat_threshold_boundary(self, mock_session, mock_open):
        """prob 恰好等于阈值时应返回 False（> 而非 >=）。"""
        mock_session.return_value = self._make_combat_session(np.array([0.5]))
        mock_open.return_value = Image.new("RGB", (87, 61))
        result = self._worker._handle_predict_combat(["/fake/a.bmp"])
        self.assertEqual(result, {"combat": [False]})

    def test_predict_combat_batch_empty(self):
        """空列表应直接返回空列表，不调用模型。"""
        result = self._worker._handle_predict_combat([])
        self.assertEqual(result, {"combat": []})

    @patch("GameBot.inference.worker.Image.open")
    @patch("GameBot.inference.worker._get_combat_session")
    def test_predict_combat_batch_multiple(self, mock_session, mock_open):
        """批量预测应返回与输入数量相同的结果。"""
        mock_session.return_value = self._make_combat_session(np.array([[0.9], [0.1], [0.8]]))
        mock_open.return_value = Image.new("RGB", (87, 61))
        result = self._worker._handle_predict_combat(["/fake/a.bmp", "/fake/b.bmp", "/fake/c.bmp"])
        self.assertEqual(len(result["combat"]), 3)
        self.assertTrue(result["combat"][0])
        self.assertFalse(result["combat"][1])
        self.assertTrue(result["combat"][2])


if __name__ == "__main__":
    unittest.main()
