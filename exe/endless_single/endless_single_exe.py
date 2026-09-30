"""
单局无尽 EXE 入口 — 64 位 Python 3.12（进程内 OCR 推理 + dm_bridge 子进程调大漠 COM）

功能：已在无尽地图内，直接开刷（英雄需站在 3 点石笋位置）。
大漠 COM 经同目录下的 dm_bridge/dm_bridge.exe（32 位）子进程调用。

启动后先弹出配置选择窗口，列出 exe 同目录的配置文件：
- 单局无尽.toml（基础配置·单开）
- 单局无尽_<玩家名>.toml（变体配置：先加载基础配置，再用该文件覆盖差异字段，
  [tasks.endless.endless_single] target_player 写本账号玩家名，用于多开认领）

同一配置（按 target_player，未填则按文件名）只允许一个实例运行。
"""

import ctypes
import sys
from pathlib import Path

# ===== 1. 确定路径 =====
# PyInstaller --onedir 模式：
#   sys.executable = 包目录/单局无尽.exe
#   sys._MEIPASS  = 包目录/_internal/
# 开发模式：
#   __file__ = exe/endless_single/endless_single_exe.py
if getattr(sys, "frozen", False):
    EXE_DIR = Path(sys.executable).parent
    BUNDLED_DIR = Path(sys._MEIPASS) / "config" / "data"
else:
    EXE_DIR = Path(__file__).resolve().parent
    BUNDLED_DIR = EXE_DIR.parent.parent / "src" / "GameBot" / "config" / "data"

# ===== 2. 初始化配置系统（必须在导入其他 GameBot 模块之前）=====
from GameBot.config import config

# 指向打包在 _internal 内的 TOML 配置文件
config.config_path = BUNDLED_DIR
# project_root 指向 exe 所在目录（dm/、resources/、单局无尽.toml 都在这里）
if getattr(sys, "frozen", False):
    config._project_root_override = EXE_DIR

# ===== 3. 导入业务模块（此时 logger 会使用正确的 project_root）=====
from GameBot.config import get_task_view, resolve_action_item_names, resolve_item_names
from GameBot.inference import get_inference_client
from GameBot.runner.tasks.war3.jiubing2.endless.endless_single import EndlessSingleTask
from GameBot.runner.ui import run_with_float_window
from GameBot.utils import logger, setup_log_file
from GameBot.utils.exception_handler import setup_global_exception_hook

try:
    import tomli
except ImportError:
    # Python 3.11+ 内置 tomllib
    import tomllib as tomli

BASE_CONFIG_NAME = "单局无尽.toml"
TASK_NS = "war3.jiubing2.tasks.endless"
TASK_GROUP = "endless"  # 用户配置 [tasks.<组>.<任务>] 中的组名
BASE_TASK_LEAF = "endless_single"
TASK_NAME = f"{TASK_NS}.{BASE_TASK_LEAF}"
DISPLAY_PREFIX = "单局无尽"


def _read_toml(path: Path) -> dict:
    """读取 TOML 文件，失败告警并返回空字典。"""
    try:
        with open(path, "rb") as f:
            return tomli.load(f)
    except Exception as exc:
        logger.warning(f"读取配置文件失败 {path}: {exc}")
        return {}


def _load_user_config(cfg_path: Path | None) -> dict:
    """读取用户配置：基础配置（单局无尽.toml）先加载，选中的变体文件合并覆盖。

    :param cfg_path: 选择窗口选定的配置文件；None 或基础配置本身时只加载基础配置。
    """
    merged: dict = {}
    paths = []
    base_path = EXE_DIR / BASE_CONFIG_NAME
    if base_path.exists():
        paths.append(base_path)
    if cfg_path is not None and cfg_path != base_path:
        paths.append(cfg_path)
    if not paths:
        logger.warning(f"未找到用户配置文件: {base_path}，将使用默认配置")
        return {}
    for p in paths:
        _deep_merge(merged, _read_toml(p))
    logger.info(f"已加载用户配置: {', '.join(p.name for p in paths)}")
    return merged


def _deep_merge(base: dict, override: dict):
    """深度合并 override 到 base（原地修改）。"""
    for key, value in override.items():
        if key in base and isinstance(base[key], dict) and isinstance(value, dict):
            _deep_merge(base[key], value)
        else:
            base[key] = value


# 用户配置顶层键 → 命名空间映射：war3/kk/base/web/hero 本就是顶层键；
# dm/paths/inference/float_window 归属 base；其余（tasks/game/command/pet/chest/…）归属 war3.jiubing2
_NS_TOP_KEYS = {"war3", "kk", "base", "web", "hero"}
_BASE_USER_KEYS = {"dm", "paths", "inference", "float_window"}


def _remap_user_cfg(user_cfg: dict) -> dict:
    """把用户配置里的简写顶层键重映射到命名空间路径（如 [tasks.x] → war3.jiubing2.tasks.x）。"""
    remapped = {}
    for key, value in user_cfg.items():
        if key in _NS_TOP_KEYS:
            if isinstance(value, dict):
                # NS 顶层键必须合并而非整表赋值（否则 [war3] 段会吞掉排在它前面的 [tasks.*] 段）
                _deep_merge(remapped.setdefault(key, {}), value)
            else:
                remapped[key] = value
        elif key in _BASE_USER_KEYS:
            remapped.setdefault("base", {})[key] = value
        else:
            remapped.setdefault("war3", {}).setdefault("jiubing2", {})[key] = value
    return remapped


# exe 环境路径覆盖：dm_bridge 子进程与 resources 均在 exe 同级目录
_EXE_PATH_OVERRIDES = {
    "base": {
        "dm": {"dll_path": "dm", "python_path": "dm_bridge/dm_bridge.exe"},
        "paths": {"resources_path": "resources"},
        "inference": {"models_dir": "resources/models"},
    },
}


def _apply_overrides(task_cfg: dict, user_cfg: dict):
    """将用户配置覆盖与 exe 环境路径写入任务闭包及各自加载闭包的缓存。

    load_task 按配置名缓存闭包 dict（同一对象引用）；dm_bridge 启动参数、
    推理参数、日志目录等由各自模块另行 load_task("base"/"war3.jiubing2"/"kk")
    获取，此处对这些常用闭包同步打补丁，使其读到 exe 环境路径。
    """
    # 0. 用户配置的简写顶层键重映射到新命名空间
    user_cfg = _remap_user_cfg(user_cfg)

    # 1. 覆盖任务配置中的用户可调参数
    _deep_merge(task_cfg, user_cfg)

    # 2. 覆盖 exe 环境的路径配置（与开发环境不同；dm/paths/inference 归属 base 命名空间）
    _deep_merge(task_cfg, _EXE_PATH_OVERRIDES)

    # 3. 用户覆盖后补一次物品名 → item_id 解析（业务侧只读 item_id，无 id 兜底）
    _j2 = task_cfg.get("war3", {}).get("jiubing2", {})
    resolve_item_names(task_cfg.get("hero", {}).get("inventory", []), _j2.get("items", []))
    resolve_action_item_names(_j2.get("tasks", {}), _j2.get("items", []))

    # 4. 同步补丁到各自加载闭包的缓存（仅覆盖其中已存在的顶层键）
    for name in ("base", "kk", "war3.jiubing2"):
        other = config.load_task(name)
        _deep_merge(other, {k: v for k, v in user_cfg.items() if k in other})
        _deep_merge(other, {k: v for k, v in _EXE_PATH_OVERRIDES.items() if k in other})


# ===== 配置选择与单实例锁 =====

_INSTANCE_MUTEXES = []  # 持有句柄防 GC；进程退出时内核自动释放


def _acquire_instance_mutex(key: str) -> int:
    """同一配置只允许一个实例运行：成功返回互斥锁句柄，已被占用返回 0。"""
    handle = ctypes.windll.kernel32.CreateMutexW(None, False, f"GameBot_task_{key}")
    if not handle:
        return 0
    if ctypes.windll.kernel32.GetLastError() == 183:  # ERROR_ALREADY_EXISTS
        ctypes.windll.kernel32.CloseHandle(handle)
        return 0
    return handle


def _read_target_player(path: Path) -> str:
    """读取配置文件的 [tasks.<组>.<任务>] target_player（用于显示与实例锁）。"""
    data = _read_toml(path)
    return data.get("tasks", {}).get(TASK_GROUP, {}).get(BASE_TASK_LEAF, {}).get("target_player", "")


def _list_task_options() -> list:
    """[(显示名, 配置路径)]：基础配置（单开）+ 同目录全部变体（单局无尽_<玩家>.toml，多开）。"""
    options = []
    base = EXE_DIR / BASE_CONFIG_NAME
    if base.exists():
        options.append((f"{base.name}（单开）", base))
    for f in sorted(EXE_DIR.glob(f"{DISPLAY_PREFIX}_*.toml")):
        options.append((f"{f.name}（多开）", f))
    if not options:
        options.append((f"{DISPLAY_PREFIX}（未找到配置文件，使用默认配置）", None))
    return options


def _select_task() -> tuple | None:
    """弹出配置选择窗口，返回 (显示名, 配置路径)；取消返回 None。"""
    options = _list_task_options()

    import tkinter as tk
    from tkinter import messagebox

    chosen: list[tuple] = []
    root = tk.Tk()
    root.title(f"{DISPLAY_PREFIX} - 选择配置")
    root.resizable(False, False)
    root.attributes("-topmost", True)

    tk.Label(root, text="选择要运行的配置：", anchor="w").pack(fill="x", padx=12, pady=(12, 4))

    lb = tk.Listbox(
        root,
        width=46,
        height=min(len(options), 10),
        exportselection=False,
        font=("Microsoft YaHei UI", 10),
    )
    for label, _ in options:
        lb.insert(tk.END, label)
    lb.selection_set(0)
    lb.pack(padx=12)

    def _ok():
        sel = lb.curselection()
        if not sel:
            return
        label, cfg_path = options[sel[0]]
        # 同一配置不可重复启动：有 target_player 按玩家名判重，否则按文件名
        key = _read_target_player(cfg_path) if cfg_path else ""
        handle = _acquire_instance_mutex(key or (cfg_path.stem if cfg_path else "default"))
        if not handle:
            messagebox.showerror("无法启动", f"「{label}」已在运行中", parent=root)
            return
        _INSTANCE_MUTEXES.append(handle)
        chosen.append((label, cfg_path))
        root.destroy()

    btns = tk.Frame(root)
    btns.pack(pady=(6, 12))
    tk.Button(btns, text="启动", width=10, command=_ok).pack(side="left", padx=6)
    tk.Button(btns, text="取消", width=10, command=root.destroy).pack(side="left", padx=6)
    lb.bind("<Double-Button-1>", lambda _e: _ok())
    root.bind("<Return>", lambda _e: _ok())

    # 居中偏上显示
    root.update_idletasks()
    x = (root.winfo_screenwidth() - root.winfo_width()) // 2
    y = (root.winfo_screenheight() - root.winfo_height()) // 3
    root.geometry(f"+{x}+{y}")

    root.mainloop()
    return chosen[0] if chosen else None


def main():
    setup_global_exception_hook()
    # 先选配置再加载任务（基础配置=单开，变体配置=多开认领指定玩家窗口）
    selected = _select_task()
    if selected is None:
        return
    _label, cfg_path = selected
    cfg = config.load_task(TASK_NAME)
    _apply_overrides(cfg, _load_user_config(cfg_path))

    # 显示名动态计算：配置带 target_player 时拼上玩家名
    target_player = get_task_view(cfg, TASK_NAME).get("target_player", "")
    title = f"{DISPLAY_PREFIX}-{target_player}" if target_player else DISPLAY_PREFIX

    setup_log_file(title)
    logger.info(f"############################# {title}（EXE 版） #############################")
    logger.info(f"EXE 目录: {EXE_DIR}")
    logger.info(f"打包资源目录: {BUNDLED_DIR}")
    if cfg_path is not None and cfg_path.name != BASE_CONFIG_NAME:
        logger.info(f"使用指定配置: {cfg_path.name}")

    # 检查大漠插件目录
    dm_dll = EXE_DIR / "dm" / "dm.dll"
    if not dm_dll.exists():
        logger.error(f"大漠插件 DLL 不存在: {dm_dll}")
        logger.error(f"请确保 dm/dm.dll 文件与 {DISPLAY_PREFIX}.exe 在同一目录下")
        sys.exit(1)

    # 检查 dm_bridge 子进程
    bridge_exe = EXE_DIR / "dm_bridge" / "dm_bridge.exe"
    if not bridge_exe.exists():
        logger.error(f"dm_bridge 子进程不存在: {bridge_exe}")
        logger.error(f"请确保 dm_bridge/dm_bridge.exe 与 {DISPLAY_PREFIX}.exe 在同一目录下")
        sys.exit(1)

    # 预加载 OCR（无尽单局不需要宝箱和战斗模型）
    get_inference_client(load_chest=False, load_combat=False)

    def task_wrapper(stop_event, progress_callback=None):
        EndlessSingleTask(cfg, task_name=TASK_NAME).run(stop_event=stop_event, progress_callback=progress_callback)

    run_with_float_window(
        title,
        task_wrapper,
        countdown_seconds=5,
        float_cfg=cfg.get("base", {}).get("float_window", {}),
    )


if __name__ == "__main__":
    main()
