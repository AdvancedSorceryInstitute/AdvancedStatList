# -*- mode: python ; coding: utf-8 -*-
import sys

from PyInstaller.utils.hooks import collect_all
from PyInstaller.utils.win32.versioninfo import (
    FixedFileInfo, StringFileInfo, StringStruct, StringTable, VSVersionInfo,
    VarFileInfo, VarStruct,
)

tkdnd_datas, tkdnd_binaries, tkdnd_hiddenimports = collect_all('tkinterdnd2')

# exe のプロパティ（詳細タブ）に出すバージョン情報。定義箇所は src/version.py だけ
sys.path.insert(0, SPECPATH)
from version import __version__

_nums = tuple(int(n) for n in __version__.split('.'))
_nums += (0,) * (4 - len(_nums))  # Windows は (major, minor, patch, build) の4つ組を要求する
version_info = VSVersionInfo(
    ffi=FixedFileInfo(filevers=_nums, prodvers=_nums),
    kids=[
        StringFileInfo([StringTable('041104B0', [
            StringStruct('CompanyName', 'AdvancedSorceryInstitute'),
            StringStruct('FileDescription', 'マビノギ用の常駐ツール'),
            StringStruct('FileVersion', __version__),
            StringStruct('InternalName', 'AdvancedStatList'),
            StringStruct('LegalCopyright', 'Copyright (c) 2026 AdvancedSorceryInstitute'),
            StringStruct('OriginalFilename', 'AdvancedStatList.exe'),
            StringStruct('ProductName', 'AdvancedStatList'),
            StringStruct('ProductVersion', __version__),
        ])]),
        # 0x411 = 日本語, 1200 = Unicode
        VarFileInfo([VarStruct('Translation', [0x411, 1200])]),
    ],
)

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
    version=version_info,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    name='AdvancedStatList',
)
