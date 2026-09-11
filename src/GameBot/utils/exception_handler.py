"""异常处理工具 — 自定义异常类、重试装饰器、全局异常钩子。"""

import functools
import logging
import threading
import time
import traceback
from typing import Callable, Optional, Tuple, Type, TypeVar

T = TypeVar("T")


class GameBotError(Exception):
    """GameBot 所有自定义异常的基类。"""


class DmError(GameBotError):
    """大漠插件相关异常。"""


class ConfigError(GameBotError):
    """配置加载/解析异常。"""


class ResourceNotFoundError(GameBotError):
    """资源文件未找到异常。"""


class TaskTimeoutError(GameBotError):
    """任务超时异常。"""


class StopTaskError(GameBotError):
    """用户请求停止任务时抛出的异常，用于中断执行流。"""


class WindowLostError(GameBotError):
    """游戏窗口消失异常（掉线、崩溃等情况）。"""


def retry(
    max_attempts: int = 3,
    delay: float = 1.0,
    exceptions: Tuple[Type[Exception], ...] = (Exception,),
    logger: Optional[logging.Logger] = None,
) -> Callable:
    """重试装饰器。

    Args:
        max_attempts: 最大尝试次数（含首次）。
        delay: 每次重试前的等待秒数。
        exceptions: 触发重试的异常类型元组。
        logger: 可选的日志记录器，传入则记录重试信息。
    """

    def decorator(func: Callable[..., T]) -> Callable[..., T]:
        @functools.wraps(func)
        def wrapper(*args, **kwargs) -> T:
            last_exc = None
            for attempt in range(1, max_attempts + 1):
                try:
                    return func(*args, **kwargs)
                except exceptions as e:
                    last_exc = e
                    if attempt < max_attempts:
                        if logger is not None:
                            logger.warning(f"{func.__name__} 第 {attempt}/{max_attempts} 次失败: {e}，{delay}s 后重试")
                        time.sleep(delay)
                    else:
                        if logger is not None:
                            logger.error(f"{func.__name__} {max_attempts} 次尝试均失败: {e}")
            raise last_exc

        return wrapper

    return decorator


def safe_call(
    default=None,
    exceptions: Tuple[Type[Exception], ...] = (Exception,),
    log_level: Optional[str] = "warning",
    log_msg: str = "",
) -> Callable:
    """安全调用装饰器 — 捕获指定异常并返回默认值，不重试。

    与 retry 互补：retry 在失败时重试，safe_call 在失败时返回默认值。
    适用于"失败不致命、有合理兜底值"的场景（如加载配置文件、读取可选资源）。

    Args:
        default: 异常时返回的默认值。
        exceptions: 捕获的异常类型元组，建议尽量收窄。
        log_level: 日志级别（"debug"/"warning"/"error"/None 表示不记录）。
        log_msg: 自定义日志消息前缀，默认使用函数名。
    """

    def decorator(func: Callable[..., T]) -> Callable[..., T]:
        @functools.wraps(func)
        def wrapper(*args, **kwargs) -> T:
            try:
                return func(*args, **kwargs)
            except exceptions as e:
                if log_level:
                    from GameBot.utils.logger import logger as _logger

                    msg = log_msg or f"{func.__name__} 失败: {e}"
                    getattr(_logger, log_level)(msg)
                return default

        return wrapper

    return decorator


def setup_global_exception_hook(logger: Optional[logging.Logger] = None):
    """安装全局未捕获异常钩子，将异常信息记录到日志。"""

    _log = logger or logging.getLogger("GameBot")
    _previous_hook = threading.excepthook

    def _hook(args):
        exc_type, exc_value, exc_tb = args.exc_type, args.exc_value, args.exc_traceback
        if issubclass(exc_type, StopTaskError):
            _log.info("任务已停止")
        else:
            _log.error(
                f"未捕获异常: {exc_type.__name__}: {exc_value}\n"
                + "".join(traceback.format_exception(exc_type, exc_value, exc_tb))
            )

    threading.excepthook = _hook
