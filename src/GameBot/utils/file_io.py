"""文件 I/O 辅助函数 — 统一处理 TOML/JSON 加载的异常捕获和默认值返回。

消除各模块中重复的 try-except 样板代码，收窄异常类型避免吞掉编程错误。
"""

import json
import sys
from pathlib import Path
from typing import Optional, Union

if sys.version_info >= (3, 11):
    import tomllib

    _TOMLDecodeError = tomllib.TOMLDecodeError
else:
    import tomli as tomllib

    _TOMLDecodeError = tomllib.TOMLDecodeError

PathLike = Union[str, Path]


def _get_logger():
    """延迟导入 logger，避免循环依赖（file_io → logger → config → user → file_io）。"""
    from GameBot.utils.logger import logger

    return logger


def load_toml(path: PathLike) -> Optional[dict]:
    """加载 TOML 文件，失败时返回 None 并记录 debug 日志。

    仅捕获 OSError 和 TOMLDecodeError，不吞掉编程错误。
    """
    path = Path(path)
    try:
        with open(path, "rb") as f:
            return tomllib.load(f)
    except (OSError, _TOMLDecodeError) as e:
        _get_logger().debug(f"加载 TOML 失败: {path}: {e}")
        return None


def load_toml_str(content: str) -> Optional[dict]:
    """从字符串解析 TOML，失败时返回 None 并记录 debug 日志。"""
    try:
        return tomllib.loads(content)
    except _TOMLDecodeError as e:
        _get_logger().debug(f"解析 TOML 字符串失败: {e}")
        return None


def load_json(path: PathLike, encoding: str = "utf-8") -> Optional:
    """加载 JSON 文件，失败时返回 None 并记录 debug 日志。

    仅捕获 OSError 和 JSONDecodeError，不吞掉编程错误。
    """
    path = Path(path)
    try:
        with open(path, "r", encoding=encoding) as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        _get_logger().debug(f"加载 JSON 失败: {path}: {e}")
        return None
