# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller 打包配置 — 坐标兼容性测试 EXE（64 位 Python 3.12）

在主环境（.venv，64 位 Python 3.12）中运行：
    uv run python -m PyInstaller exe/coords_test/coords_test_exe.spec --noconfirm
"""

import os
from pathlib import Path

block_cipher = None

project_root = Path(os.getcwd()).resolve()

exe_name = '游戏中点我测试'
dist_dir = str(project_root / 'exe' / 'dist')
work_dir = str(project_root / 'exe' / 'build')

# 仅需 base.toml 和 war3.toml
config_data_dir = project_root / 'exe' / 'coords_test' / 'data'
test_tomls = [
    config_data_dir / 'base.toml',
    config_data_dir / 'war3.toml',
]
datas = []
for toml_file in test_tomls:
    rel = toml_file.relative_to(config_data_dir)
    target_dir = str(Path('config') / 'data' / rel.parent)
    datas.append((str(toml_file), target_dir))

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
    'GameBot.web',
    'GameBot.inference',
    'GameBot.runner.tasks',
    'GameBot.runner.business.kk',
    'GameBot.runner.business.jiubing2',
]

a = Analysis(
    [str(project_root / 'exe' / 'coords_test' / 'coords_test_exe.py')],
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
    console=True,
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
