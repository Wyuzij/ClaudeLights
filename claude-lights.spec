# -*- mode: python ; coding: utf-8 -*-

# ClaudeLights — build both the CLI tool and the GUI client

# ---- CLI tool (light server + hook entry point) ----
a1 = Analysis(
    ['main.py'],
    pathex=[],
    binaries=[],
    datas=[('sounds/*', 'sounds')],
    hiddenimports=['core', 'light_server', 'PySide6', 'pygame'],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz1 = PYZ(a1.pure)

exe1 = EXE(
    pyz1,
    a1.scripts,
    a1.binaries,
    a1.datas,
    [],
    name='claude-lights',
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
)

# ---- GUI Client ----
a2 = Analysis(
    ['client.py'],
    pathex=[],
    binaries=[],
    datas=[('sounds/*', 'sounds')],
    hiddenimports=['core', 'light_server', 'PySide6', 'pygame'],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz2 = PYZ(a2.pure)

exe2 = EXE(
    pyz2,
    a2.scripts,
    a2.binaries,
    a2.datas,
    [],
    name='claude-lights-client',
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
)
