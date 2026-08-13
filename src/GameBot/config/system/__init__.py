"""配置系统包 — TOML 配置加载、依赖解析、合并构建、用户覆盖。

对外导出：
- Config              — 全局配置单例类
- ConfigurationError  — 配置异常
- config              — 全局配置实例（Config 单例）
- get_config          — 返回全局配置实例的函数

子模块：
- base     — ConfigurationError 异常 + 常量
- loader   — 文件加载 & 命名空间拆分 mixin
- resolver — 依赖解析（DFS 后序展开）mixin
- builder  — 合并构建 & 深度合并 mixin
- user     — 用户配置覆盖 mixin
- core     — Config 类 + 单例 + load_task + 访问方法
"""
from .base import ConfigurationError
from .core import Config, config, get_config

__all__ = [
    "Config",
    "ConfigurationError",
    "config",
    "get_config",
]
