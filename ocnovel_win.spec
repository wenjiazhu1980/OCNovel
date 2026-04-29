# -*- mode: python ; coding: utf-8 -*-
"""OCNovel PyInstaller Windows 打包配置"""

import sys
import os

block_cipher = None

# 项目根目录
ROOT = os.path.abspath('.')

a = Analysis(
    ['gui_main.py'],
    pathex=[ROOT],
    binaries=[],
    datas=[
        ('config.json.example', '.'),
        ('.env.example', '.'),
        ('assets', 'assets'),
        ('src/gui/i18n/*.qm', 'src/gui/i18n'),
    ],
    hiddenimports=[
        'PySide6.QtCore',
        'PySide6.QtGui',
        'PySide6.QtWidgets',
        'google.generativeai',
        'openai',
        'chromadb',
        'chromadb.config',
        'jieba',
        'jieba.posseg',
        'opencc',
        'pydantic',
        'tenacity',
        'dotenv',
        'numpy',
        'faiss',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    # 排除大体积依赖（FlagEmbedding/torch），初版不打包 reranker
    excludes=[
        'FlagEmbedding',
        'torch',
        'torchvision',
        'torchaudio',
        'transformers',
        'matplotlib',
        'scipy',
        'pandas',
        'IPython',
        'notebook',
        'pytest',
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='OCNovel',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,  # 无终端窗口
    disable_windowed_traceback=False,
    argv_emulation=False,
    icon='assets/ocnovel.ico',
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='OCNovel',
)
