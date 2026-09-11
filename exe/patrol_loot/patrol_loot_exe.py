"""
刷装备自动化 EXE 入口 — 64 位 Python 3.12（进程内推理 + dm_bridge 子进程调大漠 COM）

功能：巡逻杀怪 + AI 宝箱检测 + OCR 物品识别 + 自动拾取。
推理在主进程内直接进行（onnxruntime/rapidocr），大漠 COM 经同目录下的
dm_bridge/dm_bridge.exe（32 位）子进程调用。
用户配置：编辑同目录下的 刷装备_config.toml 文件。
"""

import sys
from pathlib import Path

# ===== 1. 确定路径 =====
if getattr(sys, "frozen", False):
    EXE_DIR = Path(sys.executable).parent
    BUNDLED_DIR = Path(sys._MEIPASS) / "config" / "data"
else:
    EXE_DIR = Path(__file__).parent
    BUNDLED_DIR = EXE_DIR.parent / "src" / "GameBot" / "config" / "data"

# ===== 2. 初始化配置系统（必须在导入其他 GameBot 模块之前）=====
from GameBot.config import config

config.config_path = BUNDLED_DIR
config._project_root_override = EXE_DIR

# ===== 3. 导入业务模块 =====
from GameBot.config import config as cfg_singleton
from GameBot.runner.tasks.war3.jiubing2.others.patrol_loot import PatrolLootTask
from GameBot.runner.ui import run_with_float_window
from GameBot.utils import logger, setup_global_exception_hook

try:
    import tomli
except ImportError:
    import tomllib as tomli


def _load_user_config() -> dict:
    """读取 exe 同级目录的 config.toml，返回用户覆盖配置。"""
    user_cfg_path = EXE_DIR / "刷装备_config.toml"
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

    同时设置 exe 环境的路径配置（dm、dm_bridge、resources）。
    推理在主进程内进行，无需配置推理子进程路径。
    """
    # 1. 覆盖任务配置中的用户可调参数
    _deep_merge(task_cfg, user_cfg)

    # 2. 同步覆盖到全局配置
    _deep_merge(cfg_singleton._config, user_cfg)

    # 3. 覆盖 exe 环境的路径配置
    if "dm" not in cfg_singleton._config:
        cfg_singleton._config["dm"] = {}
    cfg_singleton._config["dm"]["dll_path"] = "dm"
    # dm_bridge 子进程路径（exe 版使用打包的 dm_bridge.exe，32 位大漠 COM 桥接）
    cfg_singleton._config["dm"]["python_path"] = "dm_bridge/dm_bridge.exe"
    if "paths" not in cfg_singleton._config:
        cfg_singleton._config["paths"] = {}
    cfg_singleton._config["paths"]["resources_path"] = "resources"

    if "dm" in task_cfg:
        task_cfg["dm"]["dll_path"] = "dm"
        task_cfg["dm"]["python_path"] = "dm_bridge/dm_bridge.exe"
    if "paths" in task_cfg:
        task_cfg["paths"]["resources_path"] = "resources"

    # 4. 配置推理路径（进程内推理，模型目录指向 resources/models）
    if "inference" not in cfg_singleton._config:
        cfg_singleton._config["inference"] = {}
    cfg_singleton._config["inference"]["models_dir"] = "resources/models"

    if "inference" in task_cfg:
        task_cfg["inference"]["models_dir"] = "resources/models"
    else:
        task_cfg["inference"] = {"models_dir": "resources/models"}


def main():
    setup_global_exception_hook()
    logger.info("############################# 刷装备任务（EXE 版） #############################")
    logger.info(f"EXE 目录: {EXE_DIR}")
    logger.info(f"打包资源目录: {BUNDLED_DIR}")

    # 检查大漠插件目录
    dm_dll = EXE_DIR / "dm" / "dm.dll"
    if not dm_dll.exists():
        logger.error(f"大漠插件 DLL 不存在: {dm_dll}")
        logger.error("请确保 dm/dm.dll 文件与 刷装备.exe 在同一目录下")
        sys.exit(1)

    # 检查 dm_bridge 子进程
    bridge_exe = EXE_DIR / "dm_bridge" / "dm_bridge.exe"
    if not bridge_exe.exists():
        logger.error(f"dm_bridge 子进程不存在: {bridge_exe}")
        logger.error("请确保 dm_bridge/dm_bridge.exe 与 刷装备.exe 在同一目录下")
        sys.exit(1)

    # 检查模型文件
    chest_model = EXE_DIR / "resources" / "models" / "chest_detector.onnx"
    combat_model = EXE_DIR / "resources" / "models" / "combat_status.onnx"
    if not chest_model.exists():
        logger.error(f"宝箱检测模型不存在: {chest_model}")
        sys.exit(1)
    if not combat_model.exists():
        logger.error(f"战斗状态模型不存在: {combat_model}")
        sys.exit(1)

    # 加载用户配置
    user_cfg = _load_user_config()
    if user_cfg:
        logger.info(f"已加载用户配置: {EXE_DIR / '刷装备_config.toml'}")

    def task_wrapper(stop_event, progress_callback=None, **kwargs):
        cfg = config.load_task("war3.jiubing2.tasks.others.patrol_loot")
        _apply_overrides(cfg, user_cfg)
        task = PatrolLootTask(cfg, stop_event=stop_event, progress_lines_callback=kwargs.get("progress_lines_callback"))
        task.run()

    route_scheme = user_cfg.get("tasks", {}).get("others", {}).get("patrol_loot", {}).get("route_scheme", "")
    title = f"刷装备（{route_scheme}）" if route_scheme else "刷装备"
    run_with_float_window(title, task_wrapper, countdown_seconds=5)


if __name__ == "__main__":
    main()
