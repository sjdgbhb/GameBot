# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller 打包配置 — 钓鱼自动化 EXE（64 位 Python 3.12，dm_bridge 子进程调大漠 COM）

在主环境（.venv，64 位 Python 3.12）中运行：
    uv run python -m PyInstaller exe/fishing/fishing_exe.spec --noconfirm

或使用构建脚本：
    uv run python exe/fishing/build.py
"""

import os
from pathlib import Path

block_cipher = None

# 项目根目录
project_root = Path(os.getcwd()).resolve()

# 打包到 exe/ 目录下
exe_name = '钓鱼'
dist_dir = str(project_root / 'exe' / 'dist')
work_dir = str(project_root / 'exe' / 'build')

# 钓鱼依赖链所需的 TOML 配置文件（精简版，仅含钓鱼相关参数）
config_data_dir = project_root / 'exe' / 'fishing' / 'data'
fishing_tomls = [
    config_data_dir / 'base.toml',
    config_data_dir / 'war3.toml',
    config_data_dir / 'jiubing2.toml',
    config_data_dir / 'tasks' / 'others' / 'fishing.toml',
]
datas = []
for toml_file in fishing_tomls:
    rel = toml_file.relative_to(config_data_dir)
    target_dir = str(Path('config') / 'data' / rel.parent)
    datas.append((str(toml_file), target_dir))

# 隐藏导入（PyInstaller 可能无法自动检测的模块）
# 主 EXE 为 64 位 3.12，大漠 COM 经 dm_bridge 子进程调用，不直接依赖 win32com
hiddenimports = [
    'win32api',
    'win32con',
    'win32gui',
    'pywintypes',
    'tomli',
    'loguru',
    'PIL',
    'tkinter',
    'tkinter.ttk',
    'ctypes.wintypes',
]

# 排除不需要的大模块（减小体积）
excludes = [
    'onnxruntime',
    'rapidocr',
    'ultralytics',
    'torch',
    'torchvision',
    'numpy',
    'pandas',
    'matplotlib',
    'scipy',
    'fastapi',
    'uvicorn',
    'pydantic',
    # Web 相关
    'GameBot.web',
    # 推理相关（钓鱼不需要推理，但 inference/__init__.py 模块级导入 local，
    # 故仅排除 worker/model_loader，local 的延迟导入不会触发）
    'GameBot.inference.worker',
    'GameBot.inference.model_loader',
    # 无关任务模块
    'GameBot.runner.tasks.achievements',
    'GameBot.runner.tasks.atomic',
    'GameBot.runner.tasks.endless',
    'GameBot.runner.tasks.reputation',
    'GameBot.runner.tasks.others.patrol_loot',
    'GameBot.runner.tasks.others.upgrade_stigmata',
    # 无关 business 模块
    'GameBot.runner.business.kk',
    'GameBot.runner.business.jiubing2.endless_runner',
    'GameBot.runner.business.jiubing2.scene_navigator',
]

a = Analysis(
    [str(project_root / 'exe' / 'fishing' / 'fishing_exe.py')],
    pathex=[str(project_root / 'src')],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=excludes,
    noarchive=False,
    cipher=block_cipher,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name=exe_name,
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    icon=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name=exe_name,
)
