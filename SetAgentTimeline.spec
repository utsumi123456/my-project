# -*- mode: python ; coding: utf-8 -*-


a = Analysis(
    ['run_timeline.py'],
    pathex=['.'],
    binaries=[],
    datas=[('C:/Users/7166700/source/setagent/setagent_new/setagent/webui/index.html', 'setagent/webui')],
    hiddenimports=['tools.decrypt_masterdb', 'webview.platforms.winforms', 'clr_loader'],
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
    name='SetAgentTimeline',
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
