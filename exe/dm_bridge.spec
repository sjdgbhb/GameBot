# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller 打包配置 — dm_bridge 子进程 EXE（32 位 Python 3.8 + 大漠插件 COM）

主 EXE（64 位 3.12）经此子进程调用大漠 COM（32 位 COM 亲和限制）。
通信：stdin/stdout 行式 JSON（由主进程 DmBridgeClient 拉起）。

在 .venv-dm（32 位 Python 3.8）环境中运行：
    .venv-dm/Scripts/pyinstaller.exe exe/dm_bridge.spec --noconfirm

或使用统一构建脚本：
    uv run python exe/build_all.py
"""

import os
from pathlib import Path

block_cipher = None

project_root = Path(os.getcwd()).resolve()

exe_name = 'dm_bridge'
dist_dir = str(project_root / 'exe' / 'dist')
work_dir = str(project_root / 'exe' / 'build')

# 无需打包额外数据文件（dm.dll 由主包 dm/ 目录提供，运行时通过配置路径定位）
datas = []

# 隐藏导入（PyInstaller 可能无法自动检测的模块）
hiddenimports = [
    'win32com.client',
    'pythoncom',
    'pywintypes',
    'winreg',
    'tomli',
    'loguru',
    'PIL',
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
    'tkinter',
    # Web 相关（dm_bridge 不需要）
    'GameBot.web',
    # 推理相关（dm_bridge 不做推理）
    'GameBot.inference',
    # 业务任务模块（dm_bridge 仅做 COM 转发）
    'GameBot.runner.tasks',
    'GameBot.runner.business',
    'GameBot.runner.ui',
]

a = Analysis(
    [str(project_root / 'src' / 'GameBot' / 'dm_bridge' / '__main__.py')],
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
    console=True,  # dm_bridge 需要 console（stdin/stdout JSON 通信）
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
