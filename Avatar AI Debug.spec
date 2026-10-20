# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_all, collect_submodules

hiddenimports = ['asyncio.base_events', 'sqlite3', '_sqlite3', 'qrcode', 'jwt', 'flask', 'wechatpy', 'mcp.server.mcpserver', 'mcp.server.fastmcp']
hiddenimports += collect_submodules('asyncio')
hiddenimports += collect_submodules('PyQt6')

# 与 Avatar AI.spec 保持一致：原版有的 wcferry DLL / docx / pptx / PIL 都要打进去
extra_datas, extra_binaries = [], []
for _pkg in ('wcferry', 'docx', 'pptx', 'PIL'):
    _d, _b, _h = collect_all(_pkg)
    extra_datas += _d
    extra_binaries += _b
    hiddenimports += _h


a = Analysis(
    ['bootloader.py'],
    pathex=[],
    binaries=extra_binaries,
    datas=[('app\\__pycache__', 'app\\__pycache__'), ('app\\channel\\__pycache__', 'app\\channel\\__pycache__'), ('app\\storage\\__pycache__', 'app\\storage\\__pycache__'), ('app\\apps', 'app\\apps'), ('app\\web', 'web'), ('avatar_icon.ico', '.')] + extra_datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['torch', 'tensorflow', 'chromadb', 'sklearn', 'tkinter', 'matplotlib', 'numpy', 'scipy'],
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
    name='Avatar AI Debug',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=['avatar_icon.ico'],
)
