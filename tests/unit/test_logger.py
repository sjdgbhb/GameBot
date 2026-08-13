"""logger 模块单元测试 — 覆盖 get_logger 和 setup_log_file。

注意：logger 模块在导入时即有副作用（创建日志目录、添加 sink），
因此测试通过 mock config 控制行为，并使用 loguru 的 sink 管理接口验证。
"""
import sys
import unittest
from unittest.mock import MagicMock, patch

import pytest

pytestmark = [pytest.mark.unit]


class TestGetLogger(unittest.TestCase):
    """测试 get_logger 函数。"""

    def test_get_logger_without_name(self):
        """不传 name 时应返回全局 logger 实例。"""
        from GameBot.utils.logger import get_logger, logger
        result = get_logger()
        self.assertIs(result, logger)

    def test_get_logger_with_name(self):
        """传 name 时应返回绑定了 name 的 logger。"""
        from GameBot.utils.logger import get_logger, logger
        result = get_logger("MyModule")
        # loguru 的 bind 返回一个新的 logger 实例，不是同一个对象
        self.assertIsNot(result, logger)

    def test_get_logger_with_empty_name(self):
        """传空字符串 name 时应返回绑定了 name 的 logger。"""
        from GameBot.utils.logger import get_logger
        result = get_logger("")
        # 不应崩溃
        # 空字符串 name 也会创建 bind
        self.assertIsNotNone(result)


class TestSetupLogFile(unittest.TestCase):
    """测试 setup_log_file 函数。"""

    def test_setup_log_file_removes_default_sinks(self):
        """setup_log_file 应移除默认 file sink 并清空 _default_file_sinks。"""
        import sys
        logger_module = sys.modules['GameBot.utils.logger']

        original_sinks = list(logger_module._default_file_sinks)
        try:
            logger_module.setup_log_file("test_script")
            self.assertEqual(len(logger_module._default_file_sinks), 0)
        finally:
            logger_module._default_file_sinks = original_sinks

    def test_setup_log_file_with_different_names(self):
        """不同 script_name 应都能正常工作。"""
        import sys
        logger_module = sys.modules['GameBot.utils.logger']

        original_sinks = list(logger_module._default_file_sinks)
        try:
            with patch.object(logger_module, 'logger') as mock_logger:
                mock_logger.remove = MagicMock()
                mock_logger.add = MagicMock()
                logger_module.setup_log_file("钓鱼")
                logger_module.setup_log_file("无尽刷怪")
                logger_module.setup_log_file("巡逻拾取")
                # 每次 setup_log_file 应调用 2 次 add（info + error）
                self.assertEqual(mock_logger.add.call_count, 6)
        finally:
            logger_module._default_file_sinks = original_sinks


if __name__ == "__main__":
    unittest.main()
