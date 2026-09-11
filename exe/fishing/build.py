"""
钓鱼 EXE 构建脚本 — 在主环境（64 位 Python 3.12）中运行

用法：
    uv run python exe/fishing/build.py

功能：
    1. 调用 PyInstaller 打包 fishing_exe.py → dist/fishing/
    2. 复制外部文件（dm.dll、图片、config.toml、README.md）到 dist/fishing/
    3. 输出最终目录结构
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


def main():
    project_root = Path(__file__).resolve().parent.parent.parent
    exe_dir = project_root / "exe"
    dist_dir = exe_dir / "dist" / "fishing"

    _ensure_pyinstaller()

    # 1. 运行 PyInstaller
    print("=" * 60)
    print("步骤 1/3：PyInstaller 打包")
    print("=" * 60)
    spec_file = str(exe_dir / "fishing_exe.spec")
    dist_path = str(exe_dir / "dist")
    work_path = str(exe_dir / "build")
    result = subprocess.run(
        [sys.executable, "-m", "PyInstaller", spec_file, "--noconfirm",
         "--distpath", dist_path, "--workpath", work_path],
        cwd=str(project_root),
    )
    if result.returncode != 0:
        print("PyInstaller 打包失败！")
        sys.exit(1)

    # 2. 复制外部文件到 dist/fishing/
    print()
    print("=" * 60)
    print("步骤 2/3：复制外部文件")
    print("=" * 60)

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

    # resources/images/ 目录 — 仅复制钓鱼相关图片
    images_src = project_root / "src" / "gamebot" / "resources" / "images"
    images_dst = dist_dir / "resources" / "images"
    images_dst.mkdir(parents=True, exist_ok=True)
    fishing_images = ["hook_status.bmp"]
    for fname in fishing_images:
        src = images_src / fname
        if src.exists():
            shutil.copy2(src, images_dst / fname)
            print(f"  复制: resources/images/{fname}")

    # config.toml
    config_src = exe_dir / "config.toml"
    config_dst = dist_dir / "config.toml"
    shutil.copy2(config_src, config_dst)
    print(f"  复制: config.toml")

    # README.md
    readme_src = exe_dir / "README.md"
    readme_dst = dist_dir / "README.md"
    shutil.copy2(readme_src, readme_dst)
    print(f"  复制: README.md")

    # 3. 输出目录结构
    print()
    print("=" * 60)
    print("步骤 3/3：构建完成")
    print("=" * 60)
    print(f"输出目录: {dist_dir}")
    print()
    print("目录结构:")
    for item in sorted(dist_dir.iterdir()):
        if item.is_dir():
            if item.name == "_internal":
                print(f"  ├── {item.name}/  (Python 运行时和库)")
            else:
                print(f"  ├── {item.name}/")
                for sub in sorted(item.iterdir()):
                    if sub.is_dir():
                        print(f"  │   ├── {sub.name}/")
                        for sub2 in sorted(sub.iterdir()):
                            if sub2.is_file():
                                size_kb = sub2.stat().st_size / 1024
                                print(f"  │   │   ├── {sub2.name}  ({size_kb:.0f} KB)")
                    elif sub.is_file():
                        size_kb = sub.stat().st_size / 1024
                        print(f"  │   ├── {sub.name}  ({size_kb:.0f} KB)")
        else:
            size_kb = item.stat().st_size / 1024
            print(f"  ├── {item.name}  ({size_kb:.0f} KB)")

    print()
    print("将整个 fishing/ 文件夹分发给用户即可。")
    print("用户只需编辑 config.toml，然后运行 fishing.exe。")


if __name__ == "__main__":
    main()
