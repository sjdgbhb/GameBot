# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller 打包配置 — 多局无尽 EXE（64 位 Python 3.12，进程内 OCR 推理 + dm_bridge 子进程）

在主环境（.venv，64 位 Python 3.12）中运行：
    uv run python -m PyInstaller exe/endless/endless_exe.spec --noconfirm

或使用统一构建脚本：
    uv run python exe/build_all.py --update 多局无尽
"""

import os
from pathlib import Path

from PyInstaller.utils.hooks import collect_all, collect_data_files, collect_submodules

block_cipher = None

# 项目根目录
project_root = Path(os.getcwd()).resolve()

exe_name = '多局无尽'

# 完整打包配置目录（变体 TOML 运行时按名加载；组装时再用主仓库 config/data 覆盖一次保证最新）
datas = [(str(project_root / 'src' / 'GameBot' / 'config' / 'data'), 'config/data')]
binaries = []

# 隐藏导入（PyInstaller 可能无法自动检测的模块）
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

# windows_capture（WGC）是惰性导入的 Rust pyd，须 collect_all 收集
wc = collect_all('windows_capture')
datas += wc[0]
binaries += wc[1]
hiddenimports += wc[2]

# cv2/shapely/pyclipper 是 rapidocr 的底层依赖，按整个包收集（含 pyd 与包内数据）
for pkg in ('cv2', 'shapely', 'pyclipper'):
    d, b, h = collect_all(pkg)
    datas += d
    binaries += b
    hiddenimports += h

# rapidocr 数据文件（推理引擎配置 yaml、内置 onnx 模型）
datas += collect_data_files('rapidocr')

# 任务注册表经 importlib 动态导入任务模块，收集全部 GameBot 子模块
hiddenimports += collect_submodules('GameBot')

# 排除不需要的大模块（减小体积）
excludes = [
    'torch',
    'torchvision',
    'openvino',
    'paddle',
    'paddleocr',
    'pandas',
    'matplotlib',
    'scipy',
    'fastapi',
    'uvicorn',
    'pydantic',
    # Web 相关
    'GameBot.web',
    # 推理 worker 子进程模式（exe 内进程内推理，不用 worker）
    'GameBot.inference.worker',
]

a = Analysis(
    [str(project_root / 'exe' / 'endless' / 'endless_exe.py')],
    pathex=[str(project_root / 'src')],
    binaries=binaries,
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
