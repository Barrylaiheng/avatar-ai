# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_all, collect_submodules

hiddenimports = ['asyncio.base_events', 'sqlite3', '_sqlite3', 'qrcode', 'jwt', 'flask', 'wechatpy', 'mcp.server.mcpserver', 'mcp.server.fastmcp']
hiddenimports += collect_submodules('asyncio')
hiddenimports += collect_submodules('PyQt6')

# 对齐原版 v2.10.0 exe 的清单：这几样原版有、之前漏打了
#   wcferry —— 微信 WCF 渠道，必须连 sdk.dll / spy.dll / spy_debug.dll 一起打
#              （只写 collect_submodules 收不到二进制，会导致 Wcf() 初始化找不到 DLL）
#   docx / pptx —— 知识库文档解析（app/storage/doc_parser.py 用 python-docx / python-pptx）
#   PIL —— qrcode 生成二维码（企微/微信扫码登录）的默认图片后端，也是 python-pptx 的依赖
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
    datas=[('app\\__pycache__', 'app\\__pycache__'), ('app\\channel\\__pycache__', 'app\\channel\\__pycache__'), ('app\\storage\\__pycache__', 'app\\storage\\__pycache__'), ('app\\apps', 'app\\apps'), ('app\\web', 'web'), ('channels', 'channels'), ('avatar_icon.ico', '.')] + extra_datas,
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
