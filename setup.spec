# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec for ClaudeLights-Setup.exe
# Single-file installer wizard — no Python/deps required to run

import os
import glob as _glob

# Collect all project files to embed in the setup exe
project_root = os.path.dirname(os.path.abspath(SPECPATH))
embedded_datas = []

# Core modules
for fn in ['core.py', 'light_server.py', 'main.py', 'client.py', 'client.pyw', 'install.ps1', 'README.md']:
    fp = os.path.join(project_root, fn)
    if os.path.exists(fp):
        embedded_datas.append((fp, '.'))

# Sounds directory
sounds_dir = os.path.join(project_root, 'sounds')
if os.path.exists(sounds_dir):
    for fn in os.listdir(sounds_dir):
        fp = os.path.join(sounds_dir, fn)
        if os.path.isfile(fp):
            # Relative path preserved: sounds/filename
            embedded_datas.append((fp, os.path.join('sounds', fn)))

a = Analysis(
    ['setup.py'],
    pathex=[],
    binaries=[],
    datas=embedded_datas,
    hiddenimports=['tkinter', 'json', 're', 'subprocess', 'threading', 'shutil', 'tempfile', 'time'],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['PySide6', 'pygame', 'numpy', 'pandas', 'matplotlib'],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='ClaudeLights-Setup',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=None,
)
