# -*- mode: python ; coding: utf-8 -*-
#
# Onedir, not onefile. A onefile build unpacks the whole bundle to a temp
# directory on every launch, which on a Qt app is a visible delay before the
# window appears -- and this tool is opened to answer a quick question about
# a folder. Onedir starts immediately and the installer hides the folder
# anyway.

a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=[],
    # The icon is loaded at runtime by path, so it has to travel with the
    # build or the window and taskbar fall back to a blank page.
    datas=[('app/resources', 'app/resources')],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    # Nothing here imports these, but PySide6 pulls in the whole Qt family
    # unless told otherwise; excluding them keeps the installer to a size
    # someone will actually download.
    excludes=[
        'PySide6.QtWebEngineCore', 'PySide6.QtWebEngineWidgets',
        'PySide6.QtQuick', 'PySide6.QtQml', 'PySide6.Qt3DCore',
        'PySide6.QtCharts', 'PySide6.QtDataVisualization',
        'PySide6.QtMultimedia', 'PySide6.QtNetwork', 'PySide6.QtSql',
        'PySide6.QtTest', 'PySide6.QtBluetooth', 'PySide6.QtPositioning',
        'tkinter', 'unittest', 'pydoc_data',
    ],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='Archiver',
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
    icon='app/resources/icon.ico',
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='Archiver',
)
