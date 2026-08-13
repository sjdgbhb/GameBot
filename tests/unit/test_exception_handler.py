"""异常处理工具单元测试 — 覆盖 retry 装饰器和全局异常钩子。

覆盖范围：
- retry: 成功不重试、失败重试成功、全部失败抛出最后异常、异常类型过滤、
  日志记录、max_attempts=1 不重试、delay 生效、保留函数元信息
- setup_global_exception_hook: StopTaskError 记 info、其他异常记 error、
  无 logger 时使用默认 logger
- 异常类继承关系
"""

import logging
import unittest
from unittest.mock import MagicMock, patch

import pytest

pytestmark = [pytest.mark.unit]


class TestRetryDecorator(unittest.TestCase):
    """测试 retry 装饰器。"""

    @patch("GameBot.utils.exception_handler.time")
    def test_success_no_retry(self, mock_time):
        """首次成功时不应重试或 sleep。"""
        from GameBot.utils.exception_handler import retry

        @retry(max_attempts=3, delay=0.01)
        def func():
            return "ok"

        self.assertEqual(func(), "ok")
        mock_time.sleep.assert_not_called()

    @patch("GameBot.utils.exception_handler.time")
    def test_retry_then_success(self, mock_time):
        """前两次失败、第三次成功时应重试并返回结果。"""
        from GameBot.utils.exception_handler import retry

        call_count = [0]

        @retry(max_attempts=3, delay=0.01)
        def func():
            call_count[0] += 1
            if call_count[0] < 3:
                raise ValueError("fail")
            return "ok"

        self.assertEqual(func(), "ok")
        self.assertEqual(call_count[0], 3)
        self.assertEqual(mock_time.sleep.call_count, 2)

    @patch("GameBot.utils.exception_handler.time")
    def test_all_failures_raise_last(self, mock_time):
        """全部失败时应抛出最后一次的异常。"""
        from GameBot.utils.exception_handler import retry

        @retry(max_attempts=3, delay=0.01)
        def func():
            raise ValueError("final fail")

        with self.assertRaises(ValueError) as ctx:
            func()
        self.assertEqual(str(ctx.exception), "final fail")
        self.assertEqual(mock_time.sleep.call_count, 2)

    @patch("GameBot.utils.exception_handler.time")
    def test_max_attempts_1_no_retry(self, mock_time):
        """max_attempts=1 时不应重试。"""
        from GameBot.utils.exception_handler import retry

        call_count = [0]

        @retry(max_attempts=1, delay=0.01)
        def func():
            call_count[0] += 1
            raise ValueError("fail")

        with self.assertRaises(ValueError):
            func()
        self.assertEqual(call_count[0], 1)
        mock_time.sleep.assert_not_called()

    @patch("GameBot.utils.exception_handler.time")
    def test_exception_type_filter(self, mock_time):
        """只重试指定异常类型，其他异常直接抛出。"""
        from GameBot.utils.exception_handler import retry

        call_count = [0]

        @retry(max_attempts=3, delay=0.01, exceptions=(ValueError,))
        def func():
            call_count[0] += 1
            raise TypeError("not retried")

        with self.assertRaises(TypeError):
            func()
        self.assertEqual(call_count[0], 1)
        mock_time.sleep.assert_not_called()

    @patch("GameBot.utils.exception_handler.time")
    def test_exception_type_retried(self, mock_time):
        """指定异常类型应触发重试。"""
        from GameBot.utils.exception_handler import retry

        call_count = [0]

        @retry(max_attempts=3, delay=0.01, exceptions=(ValueError,))
        def func():
            call_count[0] += 1
            if call_count[0] < 2:
                raise ValueError("retried")
            return "ok"

        self.assertEqual(func(), "ok")
        self.assertEqual(call_count[0], 2)

    @patch("GameBot.utils.exception_handler.time")
    def test_multiple_exception_types(self, mock_time):
        """支持多种异常类型重试。"""
        from GameBot.utils.exception_handler import retry

        call_count = [0]

        @retry(max_attempts=5, delay=0.01, exceptions=(ValueError, TypeError))
        def func():
            call_count[0] += 1
            if call_count[0] == 1:
                raise ValueError("first")
            if call_count[0] == 2:
                raise TypeError("second")
            return "ok"

        self.assertEqual(func(), "ok")
        self.assertEqual(call_count[0], 3)

    @patch("GameBot.utils.exception_handler.time")
    def test_logger_warning_on_retry(self, mock_time):
        """有 logger 时应在重试时记录 warning。"""
        from GameBot.utils.exception_handler import retry

        mock_logger = MagicMock(spec=logging.Logger)

        @retry(max_attempts=3, delay=0.01, logger=mock_logger)
        def func():
            raise ValueError("fail")

        with self.assertRaises(ValueError):
            func()
        # 前两次失败应 warning，第三次失败应 error
        self.assertEqual(mock_logger.warning.call_count, 2)
        mock_logger.error.assert_called_once()

    @patch("GameBot.utils.exception_handler.time")
    def test_logger_error_on_final_failure(self, mock_time):
        """有 logger 时最终失败应记录 error。"""
        from GameBot.utils.exception_handler import retry

        mock_logger = MagicMock(spec=logging.Logger)

        @retry(max_attempts=2, delay=0.01, logger=mock_logger)
        def func():
            raise RuntimeError("final")

        with self.assertRaises(RuntimeError):
            func()
        self.assertEqual(mock_logger.warning.call_count, 1)
        mock_logger.error.assert_called_once()

    @patch("GameBot.utils.exception_handler.time")
    def test_no_logger_no_crash(self, mock_time):
        """无 logger 时不应崩溃。"""
        from GameBot.utils.exception_handler import retry

        @retry(max_attempts=2, delay=0.01)
        def func():
            raise ValueError("fail")

        with self.assertRaises(ValueError):
            func()

    @patch("GameBot.utils.exception_handler.time")
    def test_delay_applied_between_retries(self, mock_time):
        """每次重试前应 sleep delay 秒。"""
        from GameBot.utils.exception_handler import retry

        @retry(max_attempts=3, delay=0.5)
        def func():
            raise ValueError("fail")

        with self.assertRaises(ValueError):
            func()
        # 2 次重试，每次 sleep(0.5)
        self.assertEqual(mock_time.sleep.call_count, 2)
        for call in mock_time.sleep.call_args_list:
            self.assertEqual(call[0][0], 0.5)

    @patch("GameBot.utils.exception_handler.time")
    def test_preserves_function_metadata(self, mock_time):
        """retry 应保留被装饰函数的元信息。"""
        from GameBot.utils.exception_handler import retry

        @retry(max_attempts=3, delay=0.01)
        def my_function():
            """My docstring."""
            return "ok"

        self.assertEqual(my_function.__name__, "my_function")
        self.assertEqual(my_function.__doc__, "My docstring.")

    @patch("GameBot.utils.exception_handler.time")
    def test_passes_args_kwargs(self, mock_time):
        """retry 应正确传递位置参数和关键字参数。"""
        from GameBot.utils.exception_handler import retry

        received_args = []

        @retry(max_attempts=1, delay=0.01)
        def func(a, b, c=None):
            received_args.append((a, b, c))
            return a + b + (c or 0)

        result = func(1, 2, c=3)
        self.assertEqual(result, 6)
        self.assertEqual(received_args[0], (1, 2, 3))

    @patch("GameBot.utils.exception_handler.time")
    def test_different_exception_each_attempt(self, mock_time):
        """每次尝试抛出不同异常时，最后一次异常应被抛出。"""
        from GameBot.utils.exception_handler import retry

        call_count = [0]

        @retry(max_attempts=3, delay=0.01)
        def func():
            call_count[0] += 1
            if call_count[0] == 1:
                raise ValueError("first")
            if call_count[0] == 2:
                raise TypeError("second")
            raise RuntimeError("third")

        with self.assertRaises(RuntimeError) as ctx:
            func()
        self.assertEqual(str(ctx.exception), "third")


class TestSetupGlobalExceptionHook(unittest.TestCase):
    """测试 setup_global_exception_hook。"""

    def setUp(self):
        """保存原始 threading.excepthook 以便恢复。"""
        import threading

        self._original_hook = threading.excepthook

    def tearDown(self):
        """恢复原始 threading.excepthook。"""
        import threading

        threading.excepthook = self._original_hook

    def test_stop_task_error_logs_info(self):
        """StopTaskError 应记录 info 级别日志。"""
        from GameBot.utils.exception_handler import StopTaskError, setup_global_exception_hook

        mock_logger = MagicMock(spec=logging.Logger)
        setup_global_exception_hook(mock_logger)

        import threading

        args = MagicMock()
        args.exc_type = StopTaskError
        args.exc_value = StopTaskError("stop")
        args.exc_traceback = None

        threading.excepthook(args)
        mock_logger.info.assert_called_once_with("任务已停止")
        mock_logger.error.assert_not_called()

    def test_other_exception_logs_error(self):
        """非 StopTaskError 异常应记录 error 级别日志。"""
        from GameBot.utils.exception_handler import setup_global_exception_hook

        mock_logger = MagicMock(spec=logging.Logger)
        setup_global_exception_hook(mock_logger)

        import threading

        args = MagicMock()
        args.exc_type = RuntimeError
        args.exc_value = RuntimeError("crash")
        args.exc_traceback = None

        threading.excepthook(args)
        mock_logger.error.assert_called_once()
        mock_logger.info.assert_not_called()

    def test_default_logger_when_none(self):
        """未传入 logger 时应使用默认 GameBot logger。"""
        from GameBot.utils.exception_handler import setup_global_exception_hook

        setup_global_exception_hook(None)

        import threading

        args = MagicMock()
        args.exc_type = RuntimeError
        args.exc_value = RuntimeError("crash")
        args.exc_traceback = None

        # 不应崩溃
        threading.excepthook(args)


class TestExceptionHierarchy(unittest.TestCase):
    """测试异常类继承关系。"""

    def test_all_errors_inherit_gamebot_error(self):
        """所有自定义异常应继承 GameBotError。"""
        from GameBot.utils.exception_handler import (
            ConfigError,
            DmError,
            GameBotError,
            ResourceNotFoundError,
            StopTaskError,
            TaskTimeoutError,
            WindowLostError,
        )

        for exc_cls in [DmError, ConfigError, ResourceNotFoundError, TaskTimeoutError, StopTaskError, WindowLostError]:
            self.assertTrue(issubclass(exc_cls, GameBotError))

    def test_gamebot_error_inherits_exception(self):
        """GameBotError 应继承 Exception。"""
        from GameBot.utils.exception_handler import GameBotError

        self.assertTrue(issubclass(GameBotError, Exception))


if __name__ == "__main__":
    unittest.main()
