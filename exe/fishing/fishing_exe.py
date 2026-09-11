"""
钓鱼自动化 EXE 入口 — 64 位 Python 3.12（dm_bridge 子进程调大漠 COM）

功能：快速模式钓鱼（找色 + 预判收竿），不含 Web 配置端和 OCR 推理。
大漠 COM 经同目录下的 dm_bridge/dm_bridge.exe（32 位）子进程调用。
用户配置：编辑同目录下的 钓鱼_config.toml 文件。
"""

import sys
from pathlib import Path

# ===== 1. 确定路径 =====
# PyInstaller --onedir 模式：
#   sys.executable = dist/fishing_exe/fishing.exe
#   sys._MEIPASS  = dist/fishing_exe/_internal/
# 开发模式：
#   __file__ = exe/fishing_exe.py
if getattr(sys, "frozen", False):
    EXE_DIR = Path(sys.executable).parent
    BUNDLED_DIR = Path(sys._MEIPASS) / "config" / "data"
else:
    EXE_DIR = Path(__file__).parent
    BUNDLED_DIR = EXE_DIR.parent / "src" / "GameBot" / "config" / "data"

# ===== 2. 初始化配置系统（必须在导入其他 GameBot 模块之前）=====
from GameBot.config import config

# 指向打包在 _internal 内的 TOML 配置文件
config.config_path = BUNDLED_DIR
# project_root 指向 exe 所在目录（dm/、resources/、config.toml 都在这里）
config._project_root_override = EXE_DIR

# ===== 3. 导入业务模块（此时 logger 会使用正确的 project_root）=====
from GameBot.config import config as cfg_singleton
from GameBot.runner.tasks.war3.jiubing2.others.fishing import FishingTask
from GameBot.runner.ui import run_with_float_window
from GameBot.utils import logger, setup_global_exception_hook

try:
    import tomli
except ImportError:
    # Python 3.11+ 内置 tomllib
    import tomllib as tomli


def _load_user_config() -> dict:
    """读取 exe 同级目录的 config.toml，返回用户覆盖配置。"""
    user_cfg_path = EXE_DIR / "钓鱼_config.toml"
    if not user_cfg_path.exists():
        logger.warning(f"未找到用户配置文件: {user_cfg_path}，将使用默认配置")
        return {}
    with open(user_cfg_path, "rb") as f:
        return tomli.load(f)


def _deep_merge(base: dict, override: dict):
    """深度合并 override 到 base（原地修改）。"""
    for key, value in override.items():
        if key in base and isinstance(base[key], dict) and isinstance(value, dict):
            _deep_merge(base[key], value)
        else:
            base[key] = value


def _apply_overrides(task_cfg: dict, user_cfg: dict):
    """将用户 config.toml 的覆盖应用到任务配置字典和全局配置。

    同时强制锁定快速模式和预判模式（exe 版不支持慢速/非预判），检测模式由用户配置决定。
    """
    # 1. 覆盖任务配置中的用户可调参数
    _deep_merge(task_cfg, user_cfg)

    # 2. 同步覆盖到全局配置（DmClient 和 ResourceManager 从全局配置读取）
    _deep_merge(cfg_singleton._config, user_cfg)

    # 3. 覆盖 exe 环境的路径配置（与开发环境不同）
    if "dm" not in cfg_singleton._config:
        cfg_singleton._config["dm"] = {}
    cfg_singleton._config["dm"]["dll_path"] = "dm"
    # dm_bridge 子进程路径（exe 版使用打包的 dm_bridge.exe，32 位大漠 COM 桥接）
    cfg_singleton._config["dm"]["python_path"] = "dm_bridge/dm_bridge.exe"
    if "paths" not in cfg_singleton._config:
        cfg_singleton._config["paths"] = {}
    cfg_singleton._config["paths"]["resources_path"] = "resources"

    # 同步到 task_cfg 中的路径
    if "dm" in task_cfg:
        task_cfg["dm"]["dll_path"] = "dm"
        task_cfg["dm"]["python_path"] = "dm_bridge/dm_bridge.exe"
    if "paths" in task_cfg:
        task_cfg["paths"]["resources_path"] = "resources"

    # 4. 强制锁定模式（exe 版仅支持快速 + 预判，检测模式由用户配置决定）
    fishing_cfg = task_cfg.setdefault("tasks", {}).setdefault("others", {}).setdefault("fishing", {})
    fishing_cfg["fishing_mode"] = 1  # 快速模式
    check_cfg = fishing_cfg.setdefault("check", {})
    check_cfg["predict_mode"] = True  # 预判收竿

    # 同步到全局配置
    global_fishing = cfg_singleton._config.setdefault("tasks", {}).setdefault("others", {}).setdefault("fishing", {})
    global_fishing["fishing_mode"] = 1
    global_fishing.setdefault("check", {})["predict_mode"] = True


def main():
    setup_global_exception_hook()
    logger.info("############################# 钓鱼任务（EXE 版） #############################")
    logger.info(f"EXE 目录: {EXE_DIR}")
    logger.info(f"打包资源目录: {BUNDLED_DIR}")

    # 检查大漠插件目录
    dm_dll = EXE_DIR / "dm" / "dm.dll"
    if not dm_dll.exists():
        logger.error(f"大漠插件 DLL 不存在: {dm_dll}")
        logger.error("请确保 dm/dm.dll 文件与 钓鱼.exe 在同一目录下")
        sys.exit(1)

    # 检查 dm_bridge 子进程
    bridge_exe = EXE_DIR / "dm_bridge" / "dm_bridge.exe"
    if not bridge_exe.exists():
        logger.error(f"dm_bridge 子进程不存在: {bridge_exe}")
        logger.error("请确保 dm_bridge/dm_bridge.exe 与 钓鱼.exe 在同一目录下")
        sys.exit(1)

    # 加载用户配置
    user_cfg = _load_user_config()
    if user_cfg:
        logger.info(f"已加载用户配置: {EXE_DIR / '钓鱼_config.toml'}")

    def task_wrapper(stop_event, progress_callback):
        cfg = config.load_task("war3.jiubing2.tasks.others.fishing")
        _apply_overrides(cfg, user_cfg)
        FishingTask(cfg, stop_event=stop_event, progress_callback=progress_callback).run()

    run_with_float_window("钓鱼", task_wrapper, countdown_seconds=5)


if __name__ == "__main__":
    main()
