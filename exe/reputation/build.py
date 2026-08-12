"""
每日声望 EXE 构建脚本 — 需在两个环境中分步运行

用法：
    uv run python exe/reputation/build.py --worker          # 步骤 1：主环境（64 位 3.12）打包推理子进程
    .venv-dm/Scripts/python.exe exe/reputation/build.py --main  # 步骤 2：大漠环境（32 位 3.8）打包主程序 + 复制文件
    .venv-dm/Scripts/python.exe exe/reputation/build.py --copy  # 仅复制外部文件
"""
import os
import shutil
import subprocess
import sys
from pathlib import Path


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


def build_worker(project_root: Path, exe_dir: Path):
    """步骤 1：在主环境（64 位 Python 3.12）中打包推理子进程。"""
    print("=" * 60)
    print("步骤 1：打包推理子进程 inference_worker.exe（64 位）")
    print("=" * 60)
    _ensure_pyinstaller()
    spec_file = str(exe_dir / "patrol_loot" / "inference_worker.spec")
    result = subprocess.run(
        [sys.executable, "-m", "PyInstaller", spec_file, "--noconfirm",
         "--distpath", str(exe_dir / "dist"), "--workpath", str(exe_dir / "build")],
        cwd=str(project_root),
    )
    if result.returncode != 0:
        print("推理子进程打包失败！")
        sys.exit(1)
    print("推理子进程打包完成。")


def build_main(project_root: Path, exe_dir: Path):
    """步骤 2：在大漠环境（32 位 Python 3.8）中打包主程序。"""
    print("=" * 60)
    print("步骤 2：打包主程序 reputation.exe（32 位）")
    print("=" * 60)
    _ensure_pyinstaller()
    spec_file = str(exe_dir / "reputation" / "reputation_exe.spec")
    result = subprocess.run(
        [sys.executable, "-m", "PyInstaller", spec_file, "--noconfirm",
         "--distpath", str(exe_dir / "dist"), "--workpath", str(exe_dir / "build")],
        cwd=str(project_root),
    )
    if result.returncode != 0:
        print("主程序打包失败！")
        sys.exit(1)
    print("主程序打包完成。")


def copy_files(project_root: Path, exe_dir: Path):
    """步骤 3：复制外部文件到 dist/reputation/ 目录。"""
    print()
    print("=" * 60)
    print("步骤 3：复制外部文件")
    print("=" * 60)
    dist_dir = exe_dir / "dist" / "reputation"
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

    # inference/ 目录
    worker_dist = exe_dir / "dist" / "inference_worker"
    inference_dst = dist_dir / "inference"
    if worker_dist.exists():
        inference_dst.mkdir(parents=True, exist_ok=True)
        worker_exe = worker_dist / "inference_worker.exe"
        if worker_exe.exists():
            shutil.copy2(worker_exe, inference_dst / "inference_worker.exe")
            print(f"  复制: inference/inference_worker.exe")
        worker_internal = worker_dist / "_internal"
        if worker_internal.exists():
            internal_dst = inference_dst / "_internal"
            if internal_dst.exists():
                shutil.rmtree(internal_dst)
            shutil.copytree(worker_internal, internal_dst)
            print(f"  复制: inference/_internal/ (依赖库)")
    else:
        print(f"  警告：推理子进程未打包，请先运行 --worker 步骤")

    # config.toml
    shutil.copy2(exe_dir / "reputation" / "config.toml", dist_dir / "config.toml")
    print(f"  复制: config.toml")

    # README.md
    readme_src = exe_dir / "reputation" / "README.md"
    if readme_src.exists():
        shutil.copy2(readme_src, dist_dir / "README.md")
        print(f"  复制: README.md")

    print()
    print("=" * 60)
    print("构建完成")
    print("=" * 60)
    print(f"输出目录: {dist_dir}")
    print("将整个 reputation/ 文件夹分发给用户即可。")


def main():
    project_root = Path(__file__).resolve().parent.parent.parent
    exe_dir = project_root / "exe"
    args = sys.argv[1:]

    if not args or "--all" in args:
        is_64bit = sys.maxsize > 2**32
        if is_64bit:
            build_worker(project_root, exe_dir)
            print("\n请切换到 32 位 Python 3.8 环境运行：")
            print(f"  .venv-dm/Scripts/python.exe exe/reputation/build.py --main")
        else:
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
