"""配置包 — 统一管理配置数据和加载系统。

子包：
- data/   — TOML 配置数据文件（base、war3、jiubing2、heroes/、tasks/、scenes/）
- system/ — 配置加载系统代码（Config 单例、依赖解析、合并构建、用户覆盖）

对外导出（通过 system 子包转发）：
- Config, ConfigurationError, config（加载器单例：load_task/resolve_path/get_provenance）
- derive 派生助手：resolve_bind_cfg / force_bind_mode / resolve_item_names / get_task_view
  （调用点按 bind_mode 实时选表；组队等非标准加载路径复用）
"""

from .system import (
    Config,
    ConfigurationError,
    config,
    force_bind_mode,
    get_task_view,
    resolve_bind_cfg,
    resolve_item_names,
)

__all__ = [
    "Config",
    "ConfigurationError",
    "config",
    "force_bind_mode",
    "get_task_view",
    "resolve_bind_cfg",
    "resolve_item_names",
]
