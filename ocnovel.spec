# -*- mode: python ; coding: utf-8 -*-
"""OCNovel PyInstaller 打包配置"""

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
    target_arch='arm64',  # Apple Silicon
    codesign_identity=None,
    entitlements_file=None,
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

app = BUNDLE(
    coll,
    name='OCNovel.app',
    icon='assets/ocnovel.icns',
    bundle_identifier='com.ocnovel.app',
    info_plist={
        'CFBundleDisplayName': 'OCNovel',
        'CFBundleShortVersionString': '1.0.1',
        'CFBundleVersion': '1.0.1',
        'NSHighResolutionCapable': True,
        'LSMinimumSystemVersion': '12.0',
        'NSRequiresAquaSystemAppearance': False,  # 支持 Dark Mode
    },
)
