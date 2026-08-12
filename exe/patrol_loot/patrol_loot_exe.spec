# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller 打包配置 — 刷装备自动化 EXE（32 位 Python 3.8 + 大漠插件）

在 .venv-dm（32 位 Python 3.8）环境中运行：
    .venv-dm/Scripts/pyinstaller.exe exe/patrol_loot/patrol_loot_exe.spec --noconfirm

或使用构建脚本：
    .venv-dm/Scripts/python.exe exe/patrol_loot/build.py
"""

import os
from pathlib import Path

block_cipher = None

project_root = Path(os.getcwd()).resolve()

exe_name = '刷装备'
dist_dir = str(project_root / 'exe' / 'dist')
work_dir = str(project_root / 'exe' / 'build')

# 刷装备依赖链所需的 TOML 配置文件
config_data_dir = project_root / 'exe' / 'patrol_loot' / 'data'
patrol_loot_tomls = [
    config_data_dir / 'base.toml',
    config_data_dir / 'war3.toml',
    config_data_dir / 'jiubing2.toml',
    config_data_dir / 'tasks' / 'others' / 'patrol_loot.toml',
]
datas = []
for toml_file in patrol_loot_tomls:
    rel = toml_file.relative_to(config_data_dir)
    target_dir = str(Path('config') / 'data' / rel.parent)
    datas.append((str(toml_file), target_dir))

# 隐藏导入（PyInstaller 可能无法自动检测的模块）
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
    # 推理子进程相关（由独立的 64 位 exe 提供）
    'GameBot.inference.worker',
    'GameBot.inference.chest_detector',
    'GameBot.inference.combat_detector',

    # 无关任务模块
    'GameBot.runner.tasks.achievements',
    'GameBot.runner.tasks.atomic',
    'GameBot.runner.tasks.endless',
    'GameBot.runner.tasks.reputation',
    'GameBot.runner.tasks.others.fishing',
    'GameBot.runner.tasks.others.upgrade_stigmata',
    # 无关 business 模块
    'GameBot.runner.business.kk',
    'GameBot.runner.business.jiubing2.endless_runner',
    'GameBot.runner.business.jiubing2.scene_navigator',
]

a = Analysis(
    [str(project_root / 'exe' / 'patrol_loot' / 'patrol_loot_exe.py')],
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
