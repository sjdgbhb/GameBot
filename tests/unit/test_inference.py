"""推理层单元测试 — 覆盖 inference/ 下的纯 Python 逻辑。

覆盖范围：
- chest_detector: _letterbox 等比缩放、_nms 非极大值抑制、detect_chests 后处理
- combat_detector: predict_combat / predict_combat_batch 推理逻辑
- client: InferenceClient 请求/响应/重连逻辑（mock 子进程）
- ocr_compat: OCR 兼容层
"""

import unittest
from unittest.mock import MagicMock, patch

import numpy as np
import pytest
from PIL import Image

pytestmark = [pytest.mark.unit, pytest.mark.inference]


class TestChestDetectorLetterbox(unittest.TestCase):
    """测试 chest_detector._letterbox 等比缩放逻辑。"""

    def test_letterbox_square(self):
        """正方形图片无需填充，直接缩放。"""
        from GameBot.inference.chest_detector import _letterbox

        img = Image.new("RGB", (100, 100))
        result, scale, pad_x, pad_y = _letterbox(img, 200)
        self.assertEqual(result.size, (200, 200))
        self.assertAlmostEqual(scale, 2.0)
        self.assertEqual(pad_x, 0)
        self.assertEqual(pad_y, 0)

    def test_letterbox_landscape(self):
        """宽图应上下填充灰色。"""
        from GameBot.inference.chest_detector import _letterbox

        img = Image.new("RGB", (200, 100))
        result, scale, pad_x, pad_y = _letterbox(img, 100)
        self.assertEqual(result.size, (100, 100))
        self.assertAlmostEqual(scale, 0.5)
        self.assertEqual(pad_x, 0)
        self.assertEqual(pad_y, 25)  # (100 - 50) / 2

    def test_letterbox_portrait(self):
        """高图应左右填充灰色。"""
        from GameBot.inference.chest_detector import _letterbox

        img = Image.new("RGB", (100, 200))
        result, scale, pad_x, pad_y = _letterbox(img, 100)
        self.assertEqual(result.size, (100, 100))
        self.assertAlmostEqual(scale, 0.5)
        self.assertEqual(pad_x, 25)
        self.assertEqual(pad_y, 0)

    def test_letterbox_pad_color(self):
        """填充区域应为灰色 (114, 114, 114)。"""
        from GameBot.inference.chest_detector import PAD_COLOR, _letterbox

        img = Image.new("RGB", (200, 100), (255, 0, 0))
        result, scale, pad_x, pad_y = _letterbox(img, 100)
        # 检查填充区域颜色
        pixel = result.getpixel((0, 0))
        self.assertEqual(pixel[:3], PAD_COLOR)

    def test_letterbox_no_upscale_needed(self):
        """图片恰好等于目标尺寸时无需缩放。"""
        from GameBot.inference.chest_detector import _letterbox

        img = Image.new("RGB", (1280, 1280))
        result, scale, pad_x, pad_y = _letterbox(img, 1280)
        self.assertEqual(result.size, (1280, 1280))
        self.assertAlmostEqual(scale, 1.0)
        self.assertEqual(pad_x, 0)
        self.assertEqual(pad_y, 0)


class TestChestDetectorNMS(unittest.TestCase):
    """测试 chest_detector._nms 非极大值抑制。"""

    def test_nms_empty(self):
        """空输入应返回空列表。"""
        from GameBot.inference.chest_detector import _nms

        boxes = np.array([]).reshape(0, 4)
        scores = np.array([])
        result = _nms(boxes, scores, 0.5)
        self.assertEqual(result, [])

    def test_nms_single_box(self):
        """单个框应直接保留。"""
        from GameBot.inference.chest_detector import _nms

        boxes = np.array([[10, 10, 50, 50]])
        scores = np.array([0.9])
        result = _nms(boxes, scores, 0.5)
        self.assertEqual(result, [0])

    def test_nms_no_overlap(self):
        """不重叠的框应全部保留。"""
        from GameBot.inference.chest_detector import _nms

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
        from GameBot.inference.chest_detector import _nms

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
        from GameBot.inference.chest_detector import _nms

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
        from GameBot.inference.chest_detector import _nms

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
    """测试 chest_detector.detect_chests 完整流程（mock ONNX session）。"""

    def _make_mock_session(self, output_array):
        """创建 mock ONNX session，run 返回指定数组。"""
        session = MagicMock()
        session.run.return_value = [output_array]
        session.get_inputs.return_value = [MagicMock(name="input")]
        return session

    @patch("GameBot.inference.chest_detector._get_session")
    @patch("GameBot.inference.chest_detector._get_input_size", return_value=1280)
    @patch("GameBot.inference.chest_detector._get_conf_threshold", return_value=0.5)
    @patch("GameBot.inference.chest_detector._get_iou_threshold", return_value=0.5)
    def test_detect_no_chests(self, mock_iou, mock_conf, mock_size, mock_session):
        """无检测结果时应返回空列表。"""
        # 模拟 ONNX 输出：[1, 5, 1] 全零
        mock_session.return_value = self._make_mock_session(np.zeros((1, 5, 1), dtype=np.float32))

        from GameBot.inference.chest_detector import detect_chests

        img = Image.new("RGB", (800, 600))
        result = detect_chests(img)
        self.assertEqual(result, [])

    @patch("GameBot.inference.chest_detector._get_session")
    @patch("GameBot.inference.chest_detector._get_input_size", return_value=1280)
    @patch("GameBot.inference.chest_detector._get_conf_threshold", return_value=0.5)
    @patch("GameBot.inference.chest_detector._get_iou_threshold", return_value=0.5)
    def test_detect_with_chest(self, mock_iou, mock_conf, mock_size, mock_session):
        """检测到宝箱时应返回坐标和置信度。"""
        # YOLOv8 输出格式: [1, 5, num_anchors]
        fake_output = np.array([[[640], [320], [100], [100], [0.9]]], dtype=np.float32)
        mock_session.return_value = self._make_mock_session(fake_output)

        from GameBot.inference.chest_detector import detect_chests

        img = Image.new("RGB", (800, 600))
        result = detect_chests(img)
        self.assertEqual(len(result), 1)
        x1, y1, x2, y2, conf = result[0]
        self.assertGreater(conf, 0.5)
        # 坐标应在原图范围内
        self.assertGreaterEqual(x1, 0)
        self.assertLessEqual(x2, 800)
        self.assertGreaterEqual(y1, 0)
        self.assertLessEqual(y2, 600)

    @patch("GameBot.inference.chest_detector._get_session")
    @patch("GameBot.inference.chest_detector._get_input_size", return_value=1280)
    @patch("GameBot.inference.chest_detector._get_conf_threshold", return_value=0.95)
    @patch("GameBot.inference.chest_detector._get_iou_threshold", return_value=0.5)
    def test_detect_low_confidence_filtered(self, mock_iou, mock_conf, mock_size, mock_session):
        """低于置信度阈值的检测应被过滤。"""
        # conf=0.3 低于阈值 0.95
        fake_output = np.array([[[640], [320], [100], [100], [0.3]]], dtype=np.float32)
        mock_session.return_value = self._make_mock_session(fake_output)

        from GameBot.inference.chest_detector import detect_chests

        img = Image.new("RGB", (800, 600))
        result = detect_chests(img)
        self.assertEqual(result, [])


class TestCombatDetector(unittest.TestCase):
    """测试 combat_detector 推理逻辑。"""

    def _make_combat_session(self, output_array):
        """创建 mock combat session。"""
        session = MagicMock()
        session.run.return_value = [output_array]
        return session

    @patch("GameBot.inference.combat_detector._get_session")
    @patch("GameBot.inference.combat_detector._get_img_size", return_value=(87, 61))
    @patch("GameBot.inference.combat_detector._get_threshold", return_value=0.5)
    def test_predict_combat_in_combat(self, mock_thresh, mock_size, mock_session):
        """战斗中（prob > threshold）应返回 True。"""
        mock_session.return_value = self._make_combat_session(np.array([0.9]))
        from GameBot.inference.combat_detector import predict_combat

        img = Image.new("RGB", (87, 61))
        self.assertTrue(predict_combat(img))

    @patch("GameBot.inference.combat_detector._get_session")
    @patch("GameBot.inference.combat_detector._get_img_size", return_value=(87, 61))
    @patch("GameBot.inference.combat_detector._get_threshold", return_value=0.5)
    def test_predict_combat_not_in_combat(self, mock_thresh, mock_size, mock_session):
        """非战斗（prob <= threshold）应返回 False。"""
        mock_session.return_value = self._make_combat_session(np.array([0.3]))
        from GameBot.inference.combat_detector import predict_combat

        img = Image.new("RGB", (87, 61))
        self.assertFalse(predict_combat(img))

    @patch("GameBot.inference.combat_detector._get_session")
    @patch("GameBot.inference.combat_detector._get_img_size", return_value=(87, 61))
    @patch("GameBot.inference.combat_detector._get_threshold", return_value=0.5)
    def test_predict_combat_threshold_boundary(self, mock_thresh, mock_size, mock_session):
        """prob 恰好等于阈值时应返回 False（> 而非 >=）。"""
        mock_session.return_value = self._make_combat_session(np.array([0.5]))
        from GameBot.inference.combat_detector import predict_combat

        img = Image.new("RGB", (87, 61))
        self.assertFalse(predict_combat(img))

    @patch("GameBot.inference.combat_detector._get_session")
    @patch("GameBot.inference.combat_detector._get_img_size", return_value=(87, 61))
    @patch("GameBot.inference.combat_detector._get_threshold", return_value=0.5)
    def test_predict_combat_batch_empty(self, mock_thresh, mock_size, mock_session):
        """空列表应直接返回空列表，不调用模型。"""
        from GameBot.inference.combat_detector import predict_combat_batch

        self.assertEqual(predict_combat_batch([]), [])
        mock_session.assert_not_called()

    @patch("GameBot.inference.combat_detector._get_session")
    @patch("GameBot.inference.combat_detector._get_img_size", return_value=(87, 61))
    @patch("GameBot.inference.combat_detector._get_threshold", return_value=0.5)
    def test_predict_combat_batch_multiple(self, mock_thresh, mock_size, mock_session):
        """批量预测应返回与输入数量相同的结果。"""
        mock_session.return_value = self._make_combat_session(np.array([[0.9], [0.1], [0.8]]))
        from GameBot.inference.combat_detector import predict_combat_batch

        imgs = [Image.new("RGB", (87, 61)) for _ in range(3)]
        result = predict_combat_batch(imgs)
        self.assertEqual(len(result), 3)
        self.assertTrue(result[0])
        self.assertFalse(result[1])
        self.assertTrue(result[2])


class TestInferenceClient(unittest.TestCase):
    """测试 InferenceClient 请求/响应/重连逻辑（mock 子进程）。"""

    def test_ocr_screen_success(self):
        """OCR 请求应正确发送 cmd 并解析响应。"""
        from GameBot.inference.client import InferenceClient

        client = InferenceClient()
        client._proc = MagicMock()
        client._proc.poll.return_value = None  # 进程存活
        client._proc.stdout.readline.return_value = '{"text": "已完成"}\n'

        with patch.object(client, "start"):
            result = client.ocr_screen([0, 0, 100, 100])
        self.assertEqual(result, "已完成")

        # 验证发送的 payload
        sent = client._proc.stdin.write.call_args[0][0]
        import json

        payload = json.loads(sent)
        self.assertEqual(payload["cmd"], "ocr")
        self.assertEqual(payload["bbox"], [0, 0, 100, 100])

    def test_ocr_screen_error_response(self):
        """OCR 返回 error 时应返回空字符串。"""
        from GameBot.inference.client import InferenceClient

        client = InferenceClient()
        client._proc = MagicMock()
        client._proc.poll.return_value = None
        client._proc.stdout.readline.return_value = '{"error": "OCR 失败"}\n'

        with patch.object(client, "start"):
            result = client.ocr_screen([0, 0, 100, 100])
        self.assertEqual(result, "")

    def test_detect_chests_success(self):
        """宝箱检测应返回坐标元组列表。"""
        from GameBot.inference.client import InferenceClient

        client = InferenceClient()
        client._proc = MagicMock()
        client._proc.poll.return_value = None
        client._proc.stdout.readline.return_value = '{"chests": [[10, 20, 30, 40, 0.9], [50, 60, 70, 80, 0.8]]}\n'

        with patch.object(client, "start"):
            result = client.detect_chests("/tmp/test.bmp")
        self.assertEqual(len(result), 2)
        self.assertEqual(result[0], (10, 20, 30, 40, 0.9))
        self.assertEqual(result[1], (50, 60, 70, 80, 0.8))

    def test_detect_chests_error_returns_empty(self):
        """宝箱检测返回 error 时应返回空列表。"""
        from GameBot.inference.client import InferenceClient

        client = InferenceClient()
        client._proc = MagicMock()
        client._proc.poll.return_value = None
        client._proc.stdout.readline.return_value = '{"error": "模型未加载"}\n'

        with patch.object(client, "start"):
            result = client.detect_chests("/tmp/test.bmp")
        self.assertEqual(result, [])

    def test_predict_combat_batch_empty_input(self):
        """空输入列表应直接返回空列表。"""
        from GameBot.inference.client import InferenceClient

        client = InferenceClient()
        result = client.predict_combat_batch([])
        self.assertEqual(result, [])

    def test_predict_combat_batch_success(self):
        """批量战斗检测应返回布尔列表。"""
        from GameBot.inference.client import InferenceClient

        client = InferenceClient()
        client._proc = MagicMock()
        client._proc.poll.return_value = None
        client._proc.stdout.readline.return_value = '{"combat": [true, false, true]}\n'

        with patch.object(client, "start"):
            result = client.predict_combat_batch(["/tmp/a.bmp", "/tmp/b.bmp", "/tmp/c.bmp"])
        self.assertEqual(result, [True, False, True])

    def test_predict_combat_batch_error_returns_false(self):
        """战斗检测返回 error 时应全部返回 False。"""
        from GameBot.inference.client import InferenceClient

        client = InferenceClient()
        client._proc = MagicMock()
        client._proc.poll.return_value = None
        client._proc.stdout.readline.return_value = '{"error": "模型异常"}\n'

        with patch.object(client, "start"):
            result = client.predict_combat_batch(["/tmp/a.bmp", "/tmp/b.bmp"])
        self.assertEqual(result, [False, False])

    def test_ocr_lines_success(self):
        """ocr_lines 应返回逐行结果列表。"""
        from GameBot.inference.client import InferenceClient

        client = InferenceClient()
        client._proc = MagicMock()
        client._proc.poll.return_value = None
        client._proc.stdout.readline.return_value = (
            '{"lines": [{"text": "第一行", "y_center": 10.0}, {"text": "第二行", "y_center": 30.0}]}\n'
        )

        with patch.object(client, "start"):
            result = client.ocr_lines([0, 0, 100, 100])
        self.assertEqual(len(result), 2)
        self.assertEqual(result[0]["text"], "第一行")
        self.assertEqual(result[1]["y_center"], 30.0)

    def test_request_retry_on_broken_pipe(self):
        """管道断裂时应自动重启并重试一次。"""
        from GameBot.inference.client import InferenceClient

        client = InferenceClient()
        client._proc = MagicMock()
        client._proc.poll.return_value = None
        # 第一次 write 抛 BrokenPipeError，第二次成功
        client._proc.stdin.write.side_effect = [BrokenPipeError("broken"), None]
        client._proc.stdout.readline.return_value = '{"text": "重试成功"}\n'

        with patch.object(client, "start"), patch.object(client, "_restart") as mock_restart:
            result = client.ocr_screen([0, 0, 100, 100])
        self.assertEqual(result, "重试成功")
        mock_restart.assert_called_once()

    def test_request_retry_on_empty_response(self):
        """子进程无响应时应自动重启并重试一次。"""
        from GameBot.inference.client import InferenceClient

        client = InferenceClient()
        client._proc = MagicMock()
        client._proc.poll.return_value = None
        # 第一次 readline 返回空（子进程已退出），第二次正常
        client._proc.stdout.readline.side_effect = ["", '{"text": "重试成功"}\n']

        with patch.object(client, "start"), patch.object(client, "_restart") as mock_restart:
            result = client.ocr_screen([0, 0, 100, 100])
        self.assertEqual(result, "重试成功")
        mock_restart.assert_called_once()

    def test_request_fails_after_retry(self):
        """重试后仍失败应抛出 RuntimeError。"""
        from GameBot.inference.client import InferenceClient

        client = InferenceClient()
        client._proc = MagicMock()
        client._proc.poll.return_value = None
        # 两次都 BrokenPipeError
        client._proc.stdin.write.side_effect = [BrokenPipeError("broken"), BrokenPipeError("broken")]

        with patch.object(client, "start"), patch.object(client, "_restart"):
            with self.assertRaises(RuntimeError):
                client.ocr_screen([0, 0, 100, 100])

    def test_close_sends_quit_command(self):
        """close 应发送 quit 命令并等待子进程退出。"""
        from GameBot.inference.client import InferenceClient

        client = InferenceClient()
        proc = MagicMock()
        client._proc = proc
        proc.poll.return_value = None
        proc.wait.return_value = 0

        client.close()
        # 验证发送了 quit 命令
        sent = proc.stdin.write.call_args[0][0]
        import json

        payload = json.loads(sent)
        self.assertEqual(payload["cmd"], "quit")

    def test_close_kills_on_timeout(self):
        """close 超时应 kill 子进程。"""
        from GameBot.inference.client import InferenceClient

        client = InferenceClient()
        proc = MagicMock()
        client._proc = proc
        proc.poll.return_value = None
        proc.wait.side_effect = Exception("timeout")

        client.close()
        proc.kill.assert_called_once()


class TestInferenceClientBuildConfig(unittest.TestCase):
    """测试 _build_worker_config 配置构建。"""

    @patch("GameBot.inference.client.config")
    def test_build_config_defaults(self, mock_config):
        """默认参数应正确构建 worker 配置。"""
        mock_config.get.side_effect = lambda key, default=None: default
        mock_config.project_root = "/fake/project"

        from GameBot.inference.client import _build_worker_config

        cfg = _build_worker_config(load_chest=True, load_combat=True)
        self.assertTrue(cfg["load_chest"])
        self.assertTrue(cfg["load_combat"])
        self.assertEqual(cfg["ocr_device"], "cpu")
        self.assertEqual(cfg["ai_device"], "cpu")
        self.assertEqual(cfg["chest_input_size"], 1280)
        self.assertEqual(cfg["chest_conf"], 0.5)
        self.assertEqual(cfg["chest_iou"], 0.5)

    @patch("GameBot.inference.client.config")
    def test_build_config_selective_loading(self, mock_config):
        """load_chest=False, load_combat=False 应正确传递。"""
        mock_config.get.side_effect = lambda key, default=None: default
        mock_config.project_root = "/fake/project"

        from GameBot.inference.client import _build_worker_config

        cfg = _build_worker_config(load_chest=False, load_combat=False)
        self.assertFalse(cfg["load_chest"])
        self.assertFalse(cfg["load_combat"])


if __name__ == "__main__":
    unittest.main()
