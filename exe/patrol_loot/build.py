"""
刷装备 EXE 构建脚本 — 需在两个环境中分步运行

用法：
    uv run python exe/patrol_loot/build.py --worker                              # 步骤 1：主环境（64 位 3.12）打包推理子进程
    .venv-dm/Scripts/python.exe exe/patrol_loot/build.py --main                  # 步骤 2：大漠环境（32 位 3.8）打包主程序 + 复制文件
    .venv-dm/Scripts/python.exe exe/patrol_loot/build.py --copy                  # 仅复制外部文件（exe 已打包好时）
"""
import os
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


def build_worker(project_root: Path, exe_dir: Path):
    """步骤 1：在主环境（64 位 Python 3.12）中打包推理子进程。"""
    print("=" * 60)
    print("步骤 1：打包推理子进程 inference_worker.exe（64 位）")
    print("=" * 60)

    _ensure_pyinstaller()

    spec_file = str(exe_dir / "patrol_loot" / "inference_worker.spec")
    dist_path = str(exe_dir / "dist")
    work_path = str(exe_dir / "build")
    result = subprocess.run(
        [sys.executable, "-m", "PyInstaller", spec_file, "--noconfirm",
         "--distpath", dist_path, "--workpath", work_path],
        cwd=str(project_root),
    )
    if result.returncode != 0:
        print("推理子进程打包失败！")
        sys.exit(1)
    print("推理子进程打包完成。")


def build_main(project_root: Path, exe_dir: Path):
    """步骤 2：在大漠环境（32 位 Python 3.8）中打包主程序。"""
    print("=" * 60)
    print("步骤 2：打包主程序 patrol_loot.exe（32 位）")
    print("=" * 60)

    _ensure_pyinstaller()

    spec_file = str(exe_dir / "patrol_loot" / "patrol_loot_exe.spec")
    dist_path = str(exe_dir / "dist")
    work_path = str(exe_dir / "build")
    result = subprocess.run(
        [sys.executable, "-m", "PyInstaller", spec_file, "--noconfirm",
         "--distpath", dist_path, "--workpath", work_path],
        cwd=str(project_root),
    )
    if result.returncode != 0:
        print("主程序打包失败！")
        sys.exit(1)
    print("主程序打包完成。")


def copy_files(project_root: Path, exe_dir: Path):
    """步骤 3：复制外部文件到 dist/patrol_loot/ 目录。"""
    print()
    print("=" * 60)
    print("步骤 3：复制外部文件")
    print("=" * 60)

    dist_dir = exe_dir / "dist" / "patrol_loot"
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

    # inference/ 目录 — 从 dist/inference_worker/ 复制
    worker_dist = exe_dir / "dist" / "inference_worker"
    inference_dst = dist_dir / "inference"
    if worker_dist.exists():
        inference_dst.mkdir(parents=True, exist_ok=True)
        # 复制 inference_worker.exe
        worker_exe = worker_dist / "inference_worker.exe"
        if worker_exe.exists():
            shutil.copy2(worker_exe, inference_dst / "inference_worker.exe")
            print(f"  复制: inference/inference_worker.exe")
        # 复制 _internal/ 目录（依赖库）
        worker_internal = worker_dist / "_internal"
        if worker_internal.exists():
            internal_dst = inference_dst / "_internal"
            if internal_dst.exists():
                shutil.rmtree(internal_dst)
            shutil.copytree(worker_internal, internal_dst)
            print(f"  复制: inference/_internal/ (依赖库)")
    else:
        print(f"  警告：推理子进程未打包，请先运行 --worker 步骤")

    # resources/models/ 目录 — 模型文件
    models_src = project_root / "src" / "gamebot" / "resources" / "models"
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
    config_dst = dist_dir / "config.toml"
    shutil.copy2(config_src, config_dst)
    print(f"  复制: config.toml")

    # patrol_loot.toml — 完整任务配置（含路线点），用户可编辑路线点参数
    task_toml_src = exe_dir / "patrol_loot" / "data" / "war3" / "jiubing2" / "tasks" / "others" / "patrol_loot.toml"
    if task_toml_src.exists():
        task_toml_dst = dist_dir / "patrol_loot.toml"
        shutil.copy2(task_toml_src, task_toml_dst)
        print(f"  复制: patrol_loot.toml")

    # README.md
    readme_src = exe_dir / "patrol_loot" / "README.md"
    if readme_src.exists():
        readme_dst = dist_dir / "README.md"
        shutil.copy2(readme_src, readme_dst)
        print(f"  复制: README.md")

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
            elif item.name == "inference":
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
    print("将整个 patrol_loot/ 文件夹分发给用户即可。")
    print("用户只需编辑 config.toml，然后运行 patrol_loot.exe。")


def main():
    project_root = Path(__file__).resolve().parent.parent.parent
    exe_dir = project_root / "exe"

    args = sys.argv[1:]
    if not args or "--all" in args:
        # 完整构建（当前环境打包 + 复制文件）
        # 检测当前 Python 位数
        is_64bit = sys.maxsize > 2**32
        if is_64bit:
            print("检测到 64 位 Python，打包推理子进程...")
            build_worker(project_root, exe_dir)
            print()
            print("请切换到 32 位 Python 3.8 环境运行：")
            print(f"  .venv-dm/Scripts/python.exe exe/patrol_loot/build.py --main")
            return
        else:
            print("检测到 32 位 Python，打包主程序...")
            build_main(project_root, exe_dir)
            copy_files(project_root, exe_dir)
            return

    if "--worker" in args:
        build_worker(project_root, exe_dir)
    elif "--main" in args:
        build_main(project_root, exe_dir)
        copy_files(project_root, exe_dir)
    elif "--copy" in args:
        copy_files(project_root, exe_dir)
    else:
        print(__doc__)
        sys.exit(1)


if __name__ == "__main__":
    main()
