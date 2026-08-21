# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_all

tkdnd_datas, tkdnd_binaries, tkdnd_hiddenimports = collect_all('tkinterdnd2')

a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=tkdnd_binaries,
    datas=[
        ('../src/core/templates', 'templates'),
*tkdnd_datas,
    ],
    hiddenimports=[
        'pystray._win32',
        'PIL._imagingtk',
        'mss.windows',
        *tkdnd_hiddenimports,
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['pytesseract'],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='AdvancedStatList',
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
    icon='../assets/icon.ico',
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    name='AdvancedStatList',
)
