"""
刷装备 EXE 构建脚本 — 在主环境（64 位 Python 3.12）中运行

用法：
    uv run python exe/patrol_loot/build.py          # 打包主程序 + 复制文件
    uv run python exe/patrol_loot/build.py --copy   # 仅复制外部文件（exe 已打包好时）
"""

import shutil
import subprocess
import sys
from pathlib import Path


def _ensure_pyinstaller():
    """确保 PyInstaller 已安装，自动适配 uv/pip 环境。"""
    try:
        import PyInstaller  # noqa: F401

        return
    except ImportError:
        pass
    print("未安装 PyInstaller，正在安装...")
    # uv 管理的环境没有 pip 模块，优先用 uv pip install
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


def build_main(project_root: Path, exe_dir: Path):
    """步骤 1：在主环境（64 位 Python 3.12）中打包主程序（进程内推理）。"""
    print("=" * 60)
    print("步骤 1：打包主程序 刷装备.exe（64 位 Python 3.12，进程内推理）")
    print("=" * 60)

    _ensure_pyinstaller()

    spec_file = str(exe_dir / "patrol_loot" / "patrol_loot_exe.spec")
    dist_path = str(exe_dir / "dist")
    work_path = str(exe_dir / "build")
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "PyInstaller",
            spec_file,
            "--noconfirm",
            "--distpath",
            dist_path,
            "--workpath",
            work_path,
        ],
        cwd=str(project_root),
    )
    if result.returncode != 0:
        print("主程序打包失败！")
        sys.exit(1)
    print("主程序打包完成。")


def copy_files(project_root: Path, exe_dir: Path):
    """步骤 2：复制外部文件到 dist/刷装备/ 目录。"""
    print()
    print("=" * 60)
    print("步骤 2：复制外部文件")
    print("=" * 60)

    dist_dir = exe_dir / "dist" / "刷装备"
    if not dist_dir.exists():
        print(f"错误：打包输出目录不存在: {dist_dir}")
        sys.exit(1)

    # dm/ 目录
    dm_src = project_root / "external" / "dm"
    dm_dst = dist_dir / "dm"
    if dm_src.exists():
        dm_dst.mkdir(parents=True, exist_ok=True)
        for f in dm_src.iterdir():
            if f.is_file():
                shutil.copy2(f, dm_dst / f.name)
                print(f"  复制: dm/{f.name}")
    else:
        print(f"  警告：大漠插件目录不存在: {dm_src}")

    # dm_bridge/ 目录 — 从 dist/dm_bridge/ 复制（32 位大漠 COM 桥接子进程）
    bridge_dist = exe_dir / "dist" / "dm_bridge"
    bridge_dst = dist_dir / "dm_bridge"
    if bridge_dist.exists():
        bridge_dst.mkdir(parents=True, exist_ok=True)
        bridge_exe = bridge_dist / "dm_bridge.exe"
        if bridge_exe.exists():
            shutil.copy2(bridge_exe, bridge_dst / "dm_bridge.exe")
            print("  复制: dm_bridge/dm_bridge.exe")
        bridge_internal = bridge_dist / "_internal"
        if bridge_internal.exists():
            internal_dst = bridge_dst / "_internal"
            if internal_dst.exists():
                shutil.rmtree(internal_dst)
            shutil.copytree(bridge_internal, internal_dst)
            print("  复制: dm_bridge/_internal/ (依赖库)")
    else:
        print("  警告：dm_bridge 子进程未打包，请先运行 exe/build_all.py 或单独打包 dm_bridge")

    # resources/models/ 目录 — 模型文件
    models_src = project_root / "src" / "GameBot" / "resources" / "models"
    models_dst = dist_dir / "resources" / "models"
    models_dst.mkdir(parents=True, exist_ok=True)
    for model_file in ("chest_detector.onnx", "combat_status.onnx"):
        src = models_src / model_file
        if src.exists():
            shutil.copy2(src, models_dst / model_file)
            size_mb = src.stat().st_size / 1024 / 1024
            print(f"  复制: resources/models/{model_file} ({size_mb:.0f} MB)")

    # config.toml
    config_src = exe_dir / "patrol_loot" / "config.toml"
    config_dst = dist_dir / "刷装备_config.toml"
    shutil.copy2(config_src, config_dst)
    print("  复制: 刷装备_config.toml")

    # patrol_loot.toml — 完整任务配置（含路线点），用户可编辑路线点参数
    task_toml_src = exe_dir / "patrol_loot" / "data" / "war3" / "jiubing2" / "tasks" / "others" / "patrol_loot.toml"
    if task_toml_src.exists():
        task_toml_dst = dist_dir / "patrol_loot.toml"
        shutil.copy2(task_toml_src, task_toml_dst)
        print("  复制: patrol_loot.toml")

    # README.md
    readme_src = exe_dir / "patrol_loot" / "README.md"
    if readme_src.exists():
        readme_dst = dist_dir / "README.md"
        shutil.copy2(readme_src, readme_dst)
        print("  复制: README.md")

    # 输出目录结构
    print()
    print("=" * 60)
    print("构建完成")
    print("=" * 60)
    print(f"输出目录: {dist_dir}")
    print()
    print("目录结构:")
    for item in sorted(dist_dir.iterdir()):
        if item.is_dir():
            if item.name == "_internal":
                print(f"  ├── {item.name}/  (Python 运行时和库)")
            elif item.name == "dm_bridge":
                print(f"  ├── {item.name}/")
                for sub in sorted(item.iterdir()):
                    if sub.is_file():
                        size_kb = sub.stat().st_size / 1024
                        print(f"  │   ├── {sub.name}  ({size_kb:.0f} KB)")
                    elif sub.is_dir():
                        print(f"  │   ├── {sub.name}/  (依赖库)")
            else:
                print(f"  ├── {item.name}/")
                for sub in sorted(item.iterdir()):
                    if sub.is_file():
                        size_kb = sub.stat().st_size / 1024
                        print(f"  │   ├── {sub.name}  ({size_kb:.0f} KB)")
        else:
            size_kb = item.stat().st_size / 1024
            print(f"  ├── {item.name}  ({size_kb:.0f} KB)")

    print()
    print("将整个 刷装备/ 文件夹分发给用户即可。")
    print("用户只需编辑 刷装备_config.toml，然后运行 刷装备.exe。")


def main():
    project_root = Path(__file__).resolve().parent.parent.parent
    exe_dir = project_root / "exe"

    args = sys.argv[1:]
    if not args or "--all" in args:
        build_main(project_root, exe_dir)
        copy_files(project_root, exe_dir)
        return

    if "--main" in args:
        build_main(project_root, exe_dir)
    elif "--copy" in args:
        copy_files(project_root, exe_dir)
    else:
        print(__doc__)
        sys.exit(1)


if __name__ == "__main__":
    main()
