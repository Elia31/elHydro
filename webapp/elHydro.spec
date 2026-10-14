# -*- mode: python ; coding: utf-8 -*-
# PyInstaller-Spec für die elHydro.exe (Windows). Bauen im Ordner webapp/:
#   pip install pyinstaller
#   pyinstaller elHydro.spec
# Ergebnis: dist/elHydro.exe. Der Ordner data/ wird bewusst nicht eingebunden,
# damit keine Messdaten oder Geräte-Einstellungen in der exe landen.


a = Analysis(
    ['launcher.py'],
    pathex=[],
    binaries=[],
    datas=[('static', 'static')],
    hiddenimports=[
        'main',
        'src', 'src.api', 'src.ble', 'src.core', 'src.utils',
        'src.api.routes_devices', 'src.api.routes_logs', 'src.api.routes_measurements', 'src.api.ws',
        'src.ble.ble_worker', 'src.ble.parser',
        'src.core.brain', 'src.core.data_manager', 'src.core.log_store', 'src.core.weather',
        'src.utils.constants',
        'uvicorn.logging', 'uvicorn.protocols.http', 'uvicorn.protocols.http.auto',
        'uvicorn.protocols.websockets', 'uvicorn.protocols.websockets.auto',
        'uvicorn.lifespan', 'uvicorn.lifespan.on',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
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
    name='elHydro',
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
    icon=['static/elhydro.ico'],
)
