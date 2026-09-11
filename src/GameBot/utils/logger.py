# src/GameBot/utils/logger.py
import sys

from loguru import logger

from GameBot.config import config

# 移除默认的 handler
logger.remove()

# 日志格式：时间 | 级别 | 模块名:行号 | 消息
log_format = (
    "<green>{time:YYYY-MM-DD HH:mm:ss.SSS}</green> | "
    "<level>{level: <8}</level> | "
    "<cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> | "
    "<level>{message}</level>"
)

# 控制台输出（带颜色，方便调试）
# PyInstaller console=False 模式下 sys.stdout 为 None，需跳过
if sys.stdout is not None:
    logger.add(
        sys.stdout,
        format=log_format,
        level="DEBUG",
        colorize=None,
    )

# 日志目录
log_dir = config.get_path("paths.log_path")
if not log_dir or log_dir == config.project_root:
    log_dir = config.project_root / "logs"
log_dir.mkdir(parents=True, exist_ok=True)

# 默认日志文件 sink 的 ID，setup_log_file 调用时会移除
_default_file_sinks = []

# 默认文件输出：自动按天轮转，保留30天
_default_file_sinks.append(
    logger.add(
        log_dir / "{time:YYYY-MM-DD}.log",
        format=log_format,
        level="INFO",
        rotation="1 day",
        retention="30 days",
        encoding="utf-8",
        enqueue=True,
    )
)

# 默认错误日志文件（只记录 ERROR 及以上）
_default_file_sinks.append(
    logger.add(
        log_dir / "error_{time:YYYY-MM-DD}.log",
        format=log_format,
        level="ERROR",
        rotation="1 day",
        retention="30 days",
        encoding="utf-8",
        enqueue=True,
    )
)


def setup_log_file(script_name: str):
    """按脚本名设置日志文件，替换默认的全局日志文件 sink。

    :param script_name: 脚本名称（如 "无尽刷怪"、"钓鱼"），用于日志文件名前缀
    """
    global _default_file_sinks
    # 移除默认的文件 sink
    for sink_id in _default_file_sinks:
        logger.remove(sink_id)
    _default_file_sinks = []

    # 清理可能已创建的空全局日志文件
    import datetime as _dt

    _today = _dt.date.today().strftime("%Y-%m-%d")
    for _name in (f"{_today}.log", f"error_{_today}.log"):
        _f = log_dir / _name
        if _f.exists() and _f.stat().st_size == 0:
            try:
                _f.unlink()
            except OSError:
                pass

    # 按脚本名命名日志文件
    logger.add(
        log_dir / f"{{time:YYYY-MM-DD}}_{script_name}.log",
        format=log_format,
        level="INFO",
        rotation="1 day",
        retention="30 days",
        encoding="utf-8",
        enqueue=True,
    )
    logger.add(
        log_dir / f"{{time:YYYY-MM-DD}}_{script_name}_error.log",
        format=log_format,
        level="ERROR",
        rotation="1 day",
        retention="30 days",
        encoding="utf-8",
        enqueue=True,
    )


# 提供便捷函数，获取带模块名的 logger（也可以直接使用全局 logger）
def get_logger(name: str = None):
    """
    获取一个绑定了模块名的 logger，便于区分日志来源。
    如果不传 name，返回全局 logger。
    """
    if name is None:
        return logger
    return logger.bind(name=name)


# 直接导出 logger 实例，其他模块可 from utils.logger import logger
__all__ = ["logger", "get_logger", "setup_log_file"]
