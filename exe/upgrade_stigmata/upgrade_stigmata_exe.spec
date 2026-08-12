# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller 打包配置 — 升级圣痕 EXE（32 位 Python 3.8 + 大漠插件）"""

import os
from pathlib import Path

block_cipher = None

project_root = Path(os.getcwd()).resolve()
exe_name = '升级圣痕'
config_data_dir = project_root / 'exe' / 'upgrade_stigmata' / 'data'

stigmata_tomls = [
    config_data_dir / 'base.toml',
    config_data_dir / 'war3.toml',
    config_data_dir / 'jiubing2.toml',
    config_data_dir / 'scenes' / 'blackstone_city.toml',
    config_data_dir / 'tasks' / 'atomic' / 'blackstone_gate_harassment.toml',
    config_data_dir / 'tasks' / 'others' / 'upgrade_stigmata.toml',
]
datas = []
for toml_file in stigmata_tomls:
    rel = toml_file.relative_to(config_data_dir)
    target_dir = str(Path('config') / 'data' / rel.parent)
    datas.append((str(toml_file), target_dir))

hiddenimports = [
    'win32com.client',
    'pythoncom',
    'winreg',
    'pywintypes',
    'win32api',
    'win32con',
    'win32gui',
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
    'GameBot.inference.worker',
    'GameBot.inference.chest_detector',
    'GameBot.inference.combat_detector',
    'GameBot.runner.tasks.achievements',
    'GameBot.runner.tasks.endless',
    'GameBot.runner.tasks.others.fishing',
    'GameBot.runner.tasks.others.patrol_loot',
    'GameBot.runner.tasks.reputation',
    'GameBot.runner.business.kk',
    'GameBot.runner.business.jiubing2.endless_runner',
]

a = Analysis(
    [str(project_root / 'exe' / 'upgrade_stigmata' / 'upgrade_stigmata_exe.py')],
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
