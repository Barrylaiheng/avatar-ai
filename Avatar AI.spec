# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_submodules

hiddenimports = ['asyncio.base_events', 'sqlite3', '_sqlite3', 'qrcode', 'jwt', 'flask', 'wechatpy', 'mcp.server.mcpserver', 'mcp.server.fastmcp']
hiddenimports += collect_submodules('asyncio')
hiddenimports += collect_submodules('PyQt6')
hiddenimports += collect_submodules('wcferry')


a = Analysis(
    ['bootloader.py'],
    pathex=[],
    binaries=[],
    datas=[('app\\__pycache__', 'app\\__pycache__'), ('app\\channel\\__pycache__', 'app\\channel\\__pycache__'), ('app\\storage\\__pycache__', 'app\\storage\\__pycache__'), ('app\\apps', 'app\\apps'), ('app\\web', 'app\\web'), ('avatar_icon.ico', '.')],
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['torch', 'tensorflow', 'chromadb', 'sklearn', 'tkinter', 'matplotlib', 'PIL', 'numpy', 'scipy'],
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
    name='Avatar AI',
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
    icon=['avatar_icon.ico'],
)
