# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller 打包配置 — 刷装备自动化 EXE（64 位 Python 3.12，进程内推理）

在主环境（.venv，64 位 Python 3.12）中运行：
    uv run python -m PyInstaller exe/patrol_loot/patrol_loot_exe.spec --noconfirm

或使用构建脚本：
    uv run python exe/patrol_loot/build.py
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

# 收集 rapidocr 数据文件（yaml 配置 + 内置 OCR 模型），进程内推理需要
try:
    import rapidocr as _rapidocr
    _rapidocr_dir = os.path.dirname(_rapidocr.__file__)
    for _d, _, _files in os.walk(_rapidocr_dir):
        for _f in _files:
            if _f.endswith(('.py', '.pyc', '.pyi')):
                continue
            _src = os.path.join(_d, _f)
            _rel = os.path.relpath(_d, _rapidocr_dir)
            _dst = os.path.join('rapidocr', _rel) if _rel != '.' else 'rapidocr'
            datas.append((_src, _dst))
except ImportError:
    pass

# 隐藏导入（PyInstaller 可能无法自动检测的模块）
# 主 EXE 为 64 位 3.12，进程内推理（onnxruntime/rapidocr），大漠 COM 经 dm_bridge 子进程
hiddenimports = [
    'onnxruntime',
    'rapidocr',
    'numpy',
    'win32api',
    'win32con',
    'win32gui',
    'pywintypes',
    'tomli',
    'loguru',
    'PIL',
    'PIL.Image',
    'PIL.ImageGrab',
    'tkinter',
    'tkinter.ttk',
    'ctypes.wintypes',
]

# 排除不需要的大模块（减小体积）
excludes = [
    'ultralytics',
    'torch',
    'torchvision',
    'pandas',
    'matplotlib',
    'scipy',
    'fastapi',
    'uvicorn',
    'pydantic',
    # Web 相关
    'GameBot.web',
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

# 过滤掉 onnxruntime-gpu 带的 CUDA/cuDNN DLL（CPU 推理不需要，体积约 1.5GB）
_cuda_keywords = ('cuda', 'cudnn', 'cublas', 'cufft', 'curand', 'cusolver', 'cusparse',
                  'nvrtc', 'nvidia', 'cudart', 'nvinfer', 'nvjit', 'nvtx')
a.binaries = [b for b in a.binaries if not any(k in b[0].lower() for k in _cuda_keywords)]

# 过滤掉 OpenCV 视频编解码 DLL（进程内推理只做图像识别，不需要视频功能）
a.binaries = [b for b in a.binaries if 'opencv_videoio_ffmpeg' not in b[0].lower()]

# 过滤掉 PIL 不常用的图像格式插件（约 5MB）
_pil_skip = ('_imagingcms', '_imagingtk', '_imagingqt')
a.binaries = [b for b in a.binaries if not any(b[0].endswith(s + '.pyd') or b[0].endswith(s + '.dll') for s in _pil_skip)]

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
