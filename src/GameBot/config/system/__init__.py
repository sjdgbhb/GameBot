"""配置系统包 — TOML 配置加载、依赖解析、合并构建、用户覆盖。

对外导出：
- Config              — 全局配置单例类
- ConfigurationError  — 配置异常
- config              — 全局配置加载器实例（Config 单例，仅加载，无全局"当前配置"）

子模块：
- base     — ConfigurationError 异常 + 常量
- loader   — 文件加载 & 命名空间拆分 mixin
- resolver — 依赖解析（DFS 后序展开）mixin
- builder  — 合并构建 & 深度合并 mixin
- derive   — 派生值解析（bind 调用时选择、物品名→item_id，供 load_task 与组队路径共用）
- user     — 用户配置覆盖 mixin
- core     — Config 类 + 单例 + load_task + 路径解析
"""

from .base import ConfigurationError
from .core import Config, config
from .derive import (
    derive_bind_mode,
    force_bind_mode,
    get_task_view,
    resolve_bind_cfg,
    resolve_item_names,
)

__all__ = [
    "Config",
    "ConfigurationError",
    "config",
    "derive_bind_mode",
    "force_bind_mode",
    "get_task_view",
    "resolve_bind_cfg",
    "resolve_item_names",
]
