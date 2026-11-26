# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec file for AIgiveaway (Windows x64)."""

import os
from PyInstaller.utils.hooks import collect_data_files

block_cipher = None

ROOT = os.path.abspath(os.path.join(SPECPATH, ".."))
ICON_PATH = os.path.join(ROOT, "assets", "app.ico")

ctk_datas = collect_data_files("customtkinter")
assets_datas = [(ICON_PATH, "assets")] if os.path.exists(ICON_PATH) else []

a = Analysis(
    [os.path.join(ROOT, "main.py")],
    pathex=[ROOT],
    binaries=[],
    datas=ctk_datas + assets_datas,
    hiddenimports=[
        "pystray._win32",
        "win32api",
        "win32con",
        "win32gui",
        "win32ui",
        "PIL._tkinter_finder",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["matplotlib", "numpy", "pandas", "scipy", "pytest"],
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
    name="AIgiveaway",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=ICON_PATH if os.path.exists(ICON_PATH) else None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="AIgiveaway",
)
