"""
九种兵器2 自动化工具 — 统一打包脚本

将多局无尽、单局无尽两个任务打包到同一目录。
主 EXE 为 64 位 Python 3.12（进程内 OCR 推理），大漠 COM 经 32 位 dm_bridge 子进程调用。
两个主 EXE 共享 dm/、dm_bridge/、resources/ 和 _internal/。

用法（单步构建，自动分两步调用对应环境）：

    uv run python exe/build_all.py

    # 仅组装（主 EXE 和 dm_bridge 已打包好时）
    uv run python exe/build_all.py --assemble

    # 仅更新单个任务到已有包
    uv run python exe/build_all.py --update <任务名>
"""

import os
import shutil
import subprocess
import sys
from pathlib import Path

# 无尽任务共用图片：属性面板折叠图标、卡牌检测、结算页检测、小地图信号（游戏内检测）
_ENDLESS_IMAGES = [
    "attribute_panel_fold_icon.bmp",
    "attribute_panel_unfold_icon.bmp",
    "card_show.bmp",
    "end_war3_statistics.bmp",
    "mini_map_signal_icon.bmp",
]

# ── 任务定义 ──────────────────────────────────────────────────────────
TASKS = [
    {
        "name": "多局无尽",
        "spec": "exe/endless/endless_exe.spec",
        "config_src": "exe/endless/config.toml",
        "config_dst": "多局无尽.toml",
        "needs_inference": True,
        "needs_models": False,
        "needs_images": True,
        "images": _ENDLESS_IMAGES,
        "external_task_toml": None,
    },
    {
        "name": "单局无尽",
        "spec": "exe/endless_single/endless_single_exe.spec",
        "config_src": "exe/endless_single/config.toml",
        "config_dst": "单局无尽.toml",
        "needs_inference": True,
        "needs_models": False,
        "needs_images": True,
        "images": _ENDLESS_IMAGES,
        "external_task_toml": None,
    },
]

PACKAGE_NAME = "九兵2脚本集合"


def _ensure_pyinstaller():
    try:
        import PyInstaller  # noqa: F401

        return
    except ImportError:
        pass
    print("未安装 PyInstaller，正在安装...")
    for cmd in (
        [sys.executable, "-m", "pip", "install", "pyinstaller"],
        ["uv", "pip", "install", "pyinstaller"],
    ):
        try:
            subprocess.check_call(cmd)
            return
        except (subprocess.CalledProcessError, FileNotFoundError):
            continue
    print("错误：无法安装 PyInstaller，请手动安装：uv pip install pyinstaller")
    sys.exit(1)


def _run_pyinstaller(project_root: Path, spec_file: str, exe_dir: Path):
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "PyInstaller",
            spec_file,
            "--noconfirm",
            "--distpath",
            str(exe_dir / "dist"),
            "--workpath",
            str(exe_dir / "build"),
        ],
        cwd=str(project_root),
    )
    if result.returncode != 0:
        print(f"打包失败: {spec_file}")
        sys.exit(1)


# ── 步骤 1：打包主程序 EXE（64 位 3.12，进程内推理） ────────────────
def build_mains(project_root: Path, exe_dir: Path):
    print()
    print("=" * 60)
    print("步骤 1：打包主程序 EXE（64 位 Python 3.12，进程内推理）")
    print("=" * 60)
    _ensure_pyinstaller()
    for task in TASKS:
        print(f"\n--- 打包: {task['name']} ---")
        spec_file = str(project_root / task["spec"])
        _run_pyinstaller(project_root, spec_file, exe_dir)
        print(f"  {task['name']} 打包完成")


# ── 步骤 2：打包 dm_bridge 子进程（32 位 3.8，大漠 COM） ────────────
def build_dm_bridge(project_root: Path, exe_dir: Path):
    print()
    print("=" * 60)
    print("步骤 2：打包 dm_bridge 子进程 dm_bridge.exe（32 位 Python 3.8）")
    print("=" * 60)
    dm_python = project_root / ".venv-dm" / "Scripts" / "python.exe"
    if not dm_python.exists():
        print(f"错误：32 位大漠环境 Python 不存在: {dm_python}")
        print("请先创建 .venv-dm：uv venv .venv-dm --python 3.8（需 32 位 Python 3.8）")
        sys.exit(1)
    spec_file = str(exe_dir / "dm_bridge.spec")
    result = subprocess.run(
        [
            str(dm_python),
            "-m",
            "PyInstaller",
            spec_file,
            "--noconfirm",
            "--distpath",
            str(exe_dir / "dist"),
            "--workpath",
            str(exe_dir / "build"),
        ],
        cwd=str(project_root),
    )
    if result.returncode != 0:
        print(f"打包失败: {spec_file}")
        sys.exit(1)
    print("dm_bridge 子进程打包完成。")


# ── 步骤 3：组装到同一目录 ──────────────────────────────────────────
def assemble(project_root: Path, exe_dir: Path):
    print()
    print("=" * 60)
    print("步骤 3：组装统一目录")
    print("=" * 60)

    pkg_dir = exe_dir / "dist" / PACKAGE_NAME
    if pkg_dir.exists():
        shutil.rmtree(pkg_dir)
    pkg_dir.mkdir(parents=True)

    # 3.1 复制各任务 EXE + 合并 _internal/
    # 以第一个任务的 _internal/ 作为基础，其余任务的 _internal/ 合并补充
    base_internal = None
    for task in TASKS:
        task_dist = exe_dir / "dist" / task["name"]
        if not task_dist.exists():
            print(f"  错误：{task['name']} 打包目录不存在: {task_dist}")
            sys.exit(1)

        # 复制 EXE
        exe_file = task_dist / f"{task['name']}.exe"
        if not exe_file.exists():
            print(f"  错误：{task['name']}.exe 不存在")
            sys.exit(1)
        shutil.copy2(exe_file, pkg_dir / f"{task['name']}.exe")
        print(f"  复制: {task['name']}.exe")

        # 合并 _internal/
        task_internal = task_dist / "_internal"
        if task_internal.exists():
            if base_internal is None:
                # 第一个任务：直接复制整个 _internal/
                shutil.copytree(task_internal, pkg_dir / "_internal")
                base_internal = pkg_dir / "_internal"
                print("  复制: _internal/ (基础)")
            else:
                # 后续任务：合并（只补充不存在的文件）
                _merge_internal(task_internal, base_internal)
                print(f"  合并: _internal/ ({task['name']})")

    # 3.1.1 用主仓库完整的 config/data/ 覆盖包目录中的版本
    # 各任务 spec 已打包完整 config/data（含变体 TOML），此处再以主仓库为准覆盖一次，
    # 保证多个任务合并后配置齐全且为最新
    full_config_data = project_root / "src" / "GameBot" / "config" / "data"
    pkg_config_data = pkg_dir / "_internal" / "config" / "data"
    if full_config_data.exists() and pkg_config_data.exists():
        shutil.rmtree(pkg_config_data)
        shutil.copytree(full_config_data, pkg_config_data)
        print("  覆盖: _internal/config/data/ (主仓库完整配置)")

    # 3.1.2 修正 VC 运行库版本（PyInstaller 打包的旧版会导致 onnxruntime 初始化失败）
    _fix_vc_runtime(pkg_dir / "_internal")

    # 3.2 复制 dm/ 目录
    dm_src = project_root / "external" / "dm"
    dm_dst = pkg_dir / "dm"
    if dm_src.exists():
        dm_dst.mkdir(parents=True, exist_ok=True)
        for f in dm_src.iterdir():
            if f.is_file():
                shutil.copy2(f, dm_dst / f.name)
        print(f"  复制: dm/ ({sum(1 for _ in dm_src.iterdir())} 个文件)")
    else:
        print(f"  警告：大漠插件目录不存在: {dm_src}")

    # 3.3 复制 dm_bridge 子进程目录（32 位大漠 COM 桥接，所有任务共享）
    bridge_dist = exe_dir / "dist" / "dm_bridge"
    if bridge_dist.exists():
        bridge_dst = pkg_dir / "dm_bridge"
        bridge_dst.mkdir(parents=True, exist_ok=True)
        bridge_exe = bridge_dist / "dm_bridge.exe"
        if bridge_exe.exists():
            shutil.copy2(bridge_exe, bridge_dst / "dm_bridge.exe")
        bridge_internal = bridge_dist / "_internal"
        if bridge_internal.exists():
            internal_dst = bridge_dst / "_internal"
            if internal_dst.exists():
                shutil.rmtree(internal_dst)
            shutil.copytree(bridge_internal, internal_dst)
        print("  复制: dm_bridge/ (32 位大漠 COM 桥接子进程)")
    else:
        print("  警告：dm_bridge 子进程未打包，请先运行完整构建")

    # 3.4 复制 resources/ 目录
    resources_dst = pkg_dir / "resources"
    resources_dst.mkdir(parents=True, exist_ok=True)

    # 模型文件（仅打包声明 needs_models 的任务才复制，如刷装备的宝箱检测模型）
    if any(t.get("needs_models") for t in TASKS):
        models_src = project_root / "src" / "GameBot" / "resources" / "models"
        models_dst = resources_dst / "models"
        if models_src.exists():
            models_dst.mkdir(parents=True, exist_ok=True)
            for model_file in ("chest_detector.onnx", "combat_status.onnx"):
                src = models_src / model_file
                if src.exists():
                    shutil.copy2(src, models_dst / model_file)
                    size_mb = src.stat().st_size / 1024 / 1024
                    print(f"  复制: resources/models/{model_file} ({size_mb:.0f} MB)")

    # 图片文件（按各任务 images 列表复制）
    images_src = project_root / "src" / "GameBot" / "resources" / "images"
    images_dst = resources_dst / "images"
    if images_src.exists():
        images_dst.mkdir(parents=True, exist_ok=True)
        for task in TASKS:
            for fname in task.get("images", []):
                src = images_src / fname
                if src.exists():
                    shutil.copy2(src, images_dst / fname)
                    print(f"  复制: resources/images/{fname}")

    # 3.5 复制各任务的配置文件（config.toml → <任务名>.toml；同目录其余 toml 为变体配置，原名复制）
    for task in TASKS:
        if not task.get("config_src"):
            continue
        config_src = project_root / task["config_src"]
        if config_src.exists():
            shutil.copy2(config_src, pkg_dir / task["config_dst"])
            print(f"  复制: {task['config_dst']}")
            for extra in sorted(config_src.parent.glob("*.toml")):
                if extra.name == config_src.name:
                    continue
                shutil.copy2(extra, pkg_dir / extra.name)
                print(f"  复制: {extra.name}")

        # 外部任务配置（external_task_toml，如刷装备的 patrol_loot.toml）
        ext = task.get("external_task_toml")
        if ext:
            ext_src = project_root / ext[0]
            if ext_src.exists():
                shutil.copy2(ext_src, pkg_dir / ext[1])
                print(f"  复制: {ext[1]}")

    # 3.6 复制 README.md
    readme_src = exe_dir / "README.md"
    if readme_src.exists():
        shutil.copy2(readme_src, pkg_dir / "README.md")
        print("  复制: README.md")

    # 3.7 输出目录结构
    print()
    print("=" * 60)
    print("组装完成")
    print("=" * 60)
    print(f"输出目录: {pkg_dir}")
    print()
    print("目录结构:")
    _print_tree(pkg_dir, prefix="  ")
    print()
    print(f"将整个 {PACKAGE_NAME}/ 文件夹分发给用户即可。")
    print("用户做什么任务就运行对应的 .exe。")


def _merge_internal(src: Path, dst: Path):
    """合并 src 目录到 dst 目录（只补充 dst 中不存在的文件）。"""
    for item in src.rglob("*"):
        if item.is_file():
            rel = item.relative_to(src)
            target = dst / rel
            if not target.exists():
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(item, target)


# PyInstaller 会从 Python 安装目录打包 VC 运行库，版本可能过旧（实测 14.28），
# 冻结进程优先加载 _internal/ 中的旧版，会导致 onnxruntime_pybind11_state 等
# 新编译扩展初始化失败（"DLL 初始化例程失败"）。组装时用 System32 的较新版本覆盖。
_VC_RUNTIME_DLLS = ("msvcp140.dll", "msvcp140_1.dll", "vcruntime140.dll", "vcruntime140_1.dll")


def _file_version(path: Path) -> tuple:
    """读取文件版本号，失败返回 (0,0,0,0)。"""
    try:
        import win32api

        info = win32api.GetFileVersionInfo(str(path), "\\")
        return (
            win32api.HIWORD(info["FileVersionMS"]),
            win32api.LOWORD(info["FileVersionMS"]),
            win32api.HIWORD(info["FileVersionLS"]),
            win32api.LOWORD(info["FileVersionLS"]),
        )
    except Exception:
        return (0, 0, 0, 0)


def _fix_vc_runtime(internal_dir: Path):
    """用 System32 中较新版本的 VC 运行库覆盖 _internal/ 中的旧版。"""
    if not internal_dir.exists():
        return
    sys32 = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32"
    for name in _VC_RUNTIME_DLLS:
        src = sys32 / name
        dst = internal_dir / name
        if not src.exists() or not dst.exists():
            continue
        src_ver, dst_ver = _file_version(src), _file_version(dst)
        if src_ver > dst_ver:
            shutil.copy2(src, dst)
            print(f"  更新 VC 运行库: {name} ({'.'.join(map(str, dst_ver))} -> {'.'.join(map(str, src_ver))})")


def _print_tree(path: Path, prefix: str = "", max_depth: int = 2, depth: int = 0):
    """打印目录树（限制深度）。"""
    if depth >= max_depth:
        return
    items = sorted(path.iterdir(), key=lambda x: (not x.is_file(), x.name))
    for i, item in enumerate(items):
        is_last = i == len(items) - 1
        connector = "└── " if is_last else "├── "
        if item.is_file():
            size_kb = item.stat().st_size / 1024
            if size_kb > 1024:
                print(f"{prefix}{connector}{item.name}  ({size_kb / 1024:.1f} MB)")
            else:
                print(f"{prefix}{connector}{item.name}  ({size_kb:.0f} KB)")
        else:
            print(f"{prefix}{connector}{item.name}/")
            if depth + 1 < max_depth:
                extension = "    " if is_last else "│   "
                _print_tree(item, prefix + extension, max_depth, depth + 1)
            elif any(item.iterdir()):
                print(f"{prefix}{'    ' if is_last else '│   '}└── ...")


# ── 更新单个任务到已有包 ────────────────────────────────────────────
def update_task(project_root: Path, exe_dir: Path, task_name: str):
    """只打包指定任务的 EXE，然后更新到已有包目录（不重建整个包）。"""
    task = None
    for t in TASKS:
        if t["name"] == task_name:
            task = t
            break
    if task is None:
        print(f"错误：未知任务名 '{task_name}'，可选: {', '.join(t['name'] for t in TASKS)}")
        sys.exit(1)

    pkg_dir = exe_dir / "dist" / PACKAGE_NAME
    if not pkg_dir.exists():
        print(f"错误：包目录不存在: {pkg_dir}")
        print("请先运行完整构建：uv run python exe/build_all.py")
        sys.exit(1)

    print("=" * 60)
    print(f"更新任务: {task['name']}")
    print("=" * 60)
    _ensure_pyinstaller()

    # 1. 打包该任务的 EXE
    print(f"\n--- 打包: {task['name']} ---")
    spec_file = str(project_root / task["spec"])
    _run_pyinstaller(project_root, spec_file, exe_dir)

    task_dist = exe_dir / "dist" / task["name"]
    exe_file = task_dist / f"{task['name']}.exe"
    if not exe_file.exists():
        print(f"  错误：{task['name']}.exe 打包失败")
        sys.exit(1)

    # 2. 更新 EXE
    shutil.copy2(exe_file, pkg_dir / f"{task['name']}.exe")
    print(f"  更新: {task['name']}.exe")

    # 3. 更新 _internal/（合并新文件，覆盖已有文件）
    task_internal = task_dist / "_internal"
    if task_internal.exists():
        pkg_internal = pkg_dir / "_internal"
        _update_internal(task_internal, pkg_internal)
        _fix_vc_runtime(pkg_internal)
        print(f"  更新: _internal/ ({task['name']})")

    # 3.1 用主仓库完整的 config/data/ 覆盖（确保配置段齐全）
    full_config_data = project_root / "src" / "GameBot" / "config" / "data"
    pkg_config_data = pkg_dir / "_internal" / "config" / "data"
    if full_config_data.exists():
        if pkg_config_data.exists():
            shutil.rmtree(pkg_config_data)
        pkg_config_data.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(full_config_data, pkg_config_data)
        print("  覆盖: _internal/config/data/ (主仓库完整配置)")

    # 4. 更新该任务的配置文件
    if task.get("config_src"):
        config_src = project_root / task["config_src"]
        if config_src.exists():
            shutil.copy2(config_src, pkg_dir / task["config_dst"])
            print(f"  更新: {task['config_dst']}")
            # 同目录其余 toml 为变体配置（<任务名>_<玩家>.toml），原名复制
            for extra in sorted(config_src.parent.glob("*.toml")):
                if extra.name == config_src.name:
                    continue
                shutil.copy2(extra, pkg_dir / extra.name)
                print(f"  更新: {extra.name}")
        # 清理旧命名遗留：<任务名>_config.toml 已改为 <任务名>.toml
        legacy = pkg_dir / f"{task['name']}_config.toml"
        if legacy.exists():
            legacy.unlink()
            print(f"  删除旧配置: {legacy.name}")

    # 5. 更新该任务需要的资源文件
    if task.get("needs_images"):
        images_src = project_root / "src" / "GameBot" / "resources" / "images"
        images_dst = pkg_dir / "resources" / "images"
        images_dst.mkdir(parents=True, exist_ok=True)
        for fname in task.get("images", []):
            src = images_src / fname
            if src.exists():
                shutil.copy2(src, images_dst / fname)
                print(f"  更新: resources/images/{fname}")

    if task.get("needs_models"):
        models_src = project_root / "src" / "GameBot" / "resources" / "models"
        models_dst = pkg_dir / "resources" / "models"
        models_dst.mkdir(parents=True, exist_ok=True)
        for model_file in ("chest_detector.onnx", "combat_status.onnx"):
            src = models_src / model_file
            if src.exists():
                shutil.copy2(src, models_dst / model_file)
                print(f"  更新: resources/models/{model_file}")

    print()
    print(f"更新完成。{task['name']}.exe 已更新到 {pkg_dir}")


def _update_internal(src: Path, dst: Path):
    """更新 dst 目录：src 中存在的新文件复制过去，已有文件覆盖更新。"""
    for item in src.rglob("*"):
        if item.is_file():
            rel = item.relative_to(src)
            target = dst / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(item, target)


# ── 主入口 ──────────────────────────────────────────────────────────
def main():
    project_root = Path(__file__).resolve().parent.parent
    exe_dir = project_root / "exe"
    args = sys.argv[1:]

    if not args or "--all" in args:
        # 完整构建：主 EXE（64 位 3.12）+ dm_bridge（32 位 3.8）+ 组装
        build_mains(project_root, exe_dir)
        build_dm_bridge(project_root, exe_dir)
        assemble(project_root, exe_dir)
        return

    if "--main" in args:
        build_mains(project_root, exe_dir)
    elif "--bridge" in args:
        build_dm_bridge(project_root, exe_dir)
    elif "--assemble" in args:
        assemble(project_root, exe_dir)
    elif "--update" in args:
        idx = args.index("--update")
        if idx + 1 >= len(args):
            print("用法: --update <任务名>")
            print(f"可选任务: {', '.join(t['name'] for t in TASKS)}")
            sys.exit(1)
        update_task(project_root, exe_dir, args[idx + 1])
    else:
        print(__doc__)
        sys.exit(1)


if __name__ == "__main__":
    main()
