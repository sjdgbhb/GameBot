"""
升级圣痕自动化 EXE 入口 — 32 位 Python 3.8 + 大漠插件 COM

功能：交替执行城门骚扰（获取升级机会）→ 走到圣痕 NPC → 自动选择未满词条升级，直至全部达标。
推理子进程（OCR）由同目录下的 inference/inference_worker.exe 提供（64 位）。
用户配置：编辑同目录下的 升级圣痕_config.toml 文件。
"""
import sys
from pathlib import Path

# ===== 1. 确定路径 =====
if getattr(sys, 'frozen', False):
    EXE_DIR = Path(sys.executable).parent
    BUNDLED_DIR = Path(sys._MEIPASS) / 'config' / 'data'
else:
    EXE_DIR = Path(__file__).parent
    BUNDLED_DIR = EXE_DIR.parent / 'src' / 'GameBot' / 'config' / 'data'

# ===== 2. 初始化配置系统（必须在导入其他 GameBot 模块之前）=====
from GameBot.config import config

config.config_path = BUNDLED_DIR
config._project_root_override = EXE_DIR

# ===== 3. 导入业务模块 =====
from GameBot.utils import setup_global_exception_hook, logger
from GameBot.config import config as cfg_singleton
from GameBot.runner.tasks.war3.jiubing2.others.upgrade_stigmata import UpgradeStigmataTask
from GameBot.runner.ui import run_with_float_window

try:
    import tomli
except ImportError:
    import tomllib as tomli


def _load_user_config() -> dict:
    """读取 exe 同级目录的 config.toml，返回用户覆盖配置。"""
    user_cfg_path = EXE_DIR / "升级圣痕_config.toml"
    if not user_cfg_path.exists():
        logger.warning(f"未找到用户配置文件: {user_cfg_path}，将使用默认配置")
        return {}
    with open(user_cfg_path, 'rb') as f:
        return tomli.load(f)


def _deep_merge(base: dict, override: dict):
    """深度合并 override 到 base（原地修改）。"""
    for key, value in override.items():
        if key in base and isinstance(base[key], dict) and isinstance(value, dict):
            _deep_merge(base[key], value)
        else:
            base[key] = value


def _apply_overrides(task_cfg: dict, user_cfg: dict):
    """将用户 config.toml 的覆盖应用到任务配置字典和全局配置。"""
    _deep_merge(task_cfg, user_cfg)
    _deep_merge(cfg_singleton._config, user_cfg)

    # 覆盖 exe 环境的路径配置
    if "dm" not in cfg_singleton._config:
        cfg_singleton._config["dm"] = {}
    cfg_singleton._config["dm"]["dll_path"] = "dm"
    if "paths" not in cfg_singleton._config:
        cfg_singleton._config["paths"] = {}
    cfg_singleton._config["paths"]["resources_path"] = "resources"

    if "dm" in task_cfg:
        task_cfg["dm"]["dll_path"] = "dm"
    if "paths" in task_cfg:
        task_cfg["paths"]["resources_path"] = "resources"

    # 配置推理子进程路径
    if "inference" not in cfg_singleton._config:
        cfg_singleton._config["inference"] = {}
    inf_cfg = cfg_singleton._config["inference"]
    inf_cfg["python_path"] = "inference/inference_worker.exe"
    inf_cfg["worker_script"] = ""
    inf_cfg["models_dir"] = "resources/models"

    if "inference" in task_cfg:
        task_cfg["inference"]["python_path"] = "inference/inference_worker.exe"
        task_cfg["inference"]["worker_script"] = ""
        task_cfg["inference"]["models_dir"] = "resources/models"
    else:
        task_cfg["inference"] = {
            "python_path": "inference/inference_worker.exe",
            "worker_script": "",
            "models_dir": "resources/models",
        }


def main():
    setup_global_exception_hook()
    logger.info("############################# 升级圣痕（EXE 版） #############################")
    logger.info(f"EXE 目录: {EXE_DIR}")
    logger.info(f"打包资源目录: {BUNDLED_DIR}")

    # 检查大漠插件目录
    dm_dll = EXE_DIR / "dm" / "dm.dll"
    if not dm_dll.exists():
        logger.error(f"大漠插件 DLL 不存在: {dm_dll}")
        logger.error("请确保 dm/dm.dll 文件与 升级圣痕.exe 在同一目录下")
        sys.exit(1)

    # 检查推理子进程
    worker_exe = EXE_DIR / "inference" / "inference_worker.exe"
    if not worker_exe.exists():
        logger.error(f"推理子进程不存在: {worker_exe}")
        logger.error("请确保 inference/inference_worker.exe 与 升级圣痕.exe 在同一目录下")
        sys.exit(1)

    # 加载用户配置
    user_cfg = _load_user_config()
    if user_cfg:
        logger.info(f"已加载用户配置: {EXE_DIR / '升级圣痕_config.toml'}")

    # 预加载任务配置以获取 float_window 设置
    # 优先级：user_cfg > 任务配置文件 > 默认配置
    pre_cfg = config.load_task("war3.jiubing2.tasks.others.upgrade_stigmata")
    _apply_overrides(pre_cfg, user_cfg)
    float_cfg = pre_cfg.get("float_window", {})

    def task_wrapper(stop_event, progress_callback=None, progress_lines_callback=None):
        cfg = config.load_task("war3.jiubing2.tasks.others.upgrade_stigmata")
        _apply_overrides(cfg, user_cfg)
        task = UpgradeStigmataTask(cfg)
        task.run(stop_event=stop_event, progress_lines_callback=progress_lines_callback)

    run_with_float_window("升级圣痕", task_wrapper, countdown_seconds=5,
                          float_cfg=float_cfg)


if __name__ == "__main__":
    main()
