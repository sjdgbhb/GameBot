# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller 打包配置 — 推理子进程 EXE（64 位 Python 3.12）

在主环境（.venv，64 位 Python 3.12）中运行：
    .venv/Scripts/pyinstaller.exe exe/inference_worker.spec --noconfirm

或使用构建脚本：
    uv run python exe/build_patrol_loot.py
"""

import os
import sys
from pathlib import Path

block_cipher = None

project_root = Path(os.getcwd()).resolve()

exe_name = 'inference_worker'
dist_dir = str(project_root / 'exe' / 'dist')
work_dir = str(project_root / 'exe' / 'build')

# 模型文件不打包进 exe，由 build 脚本复制到外部，方便替换
datas = []

# 收集 rapidocr 数据文件（yaml 配置 + 内置 OCR 模型）
import rapidocr as _rapidocr
_rapidocr_dir = os.path.dirname(_rapidocr.__file__)
for d, _, files in os.walk(_rapidocr_dir):
    for f in files:
        if f.endswith(('.py', '.pyc', '.pyi')):
            continue
        src = os.path.join(d, f)
        rel = os.path.relpath(d, _rapidocr_dir)
        dst = os.path.join('rapidocr', rel) if rel != '.' else 'rapidocr'
        datas.append((src, dst))

# 隐藏导入
hiddenimports = [
    'onnxruntime',
    'rapidocr',
    'numpy',
    'PIL',
    'PIL.Image',
    'PIL.ImageGrab',
]

# 排除不需要的模块
excludes = [
    'torch',
    'torchvision',
    'ultralytics',
    'matplotlib',
    'scipy',
    'pandas',
    'fastapi',
    'uvicorn',
    'pydantic',
    'tkinter',
    'win32com',
    'pythoncom',
    'pywintypes',
    'win32api',
    'win32con',
    'win32gui',
    # 大漠脚本相关（32 位 only）
    'GameBot.runner',
    'GameBot.web',
    'GameBot.config',
    'GameBot.utils',
]

a = Analysis(
    [str(project_root / 'src' / 'GameBot' / 'inference' / 'worker.py')],
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

# 过滤掉 OpenCV 视频编解码 DLL（worker 只做图像推理，不需要视频功能，约 29MB）
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
    console=True,  # 推理子进程需要 console（stdin/stdout JSON 通信）
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
