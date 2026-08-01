# -*- mode: python ; coding: utf-8 -*-
import os
from PyInstaller.utils.hooks import collect_all

datas = []
binaries = []
hiddenimports = []
tmp_ret = collect_all('HardwareMonitor')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
tmp_ret = collect_all('pythonnet')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
tmp_ret = collect_all('customtkinter')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
tmp_ret = collect_all('esptool')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
# (esptool e' usado pela aba Firmware -- ver firmware_engine.py. O usuario
# seleciona o .bin na hora, na propria janela do app; nao ha pasta de
# firmware embutida no build.)

# PawnIO_setup.exe (driver de CPU, ver garantir_pawnio() em orbepc_app.py)
# embutido no .exe se estiver presente na pasta do projeto na hora do
# build -- baixe uma vez em
# https://github.com/namazso/PawnIO.Setup/releases/latest/download/PawnIO_setup.exe
# Se o arquivo nao estiver aqui, o build segue normal (so cai no aviso
# em log.txt na primeira execucao, pedindo pra colocar o arquivo do lado
# do OrbePC.exe manualmente).
if os.path.exists('PawnIO_setup.exe'):
    binaries.append(('PawnIO_setup.exe', '.'))


a = Analysis(
    ['orbepc_app.py'],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
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
    name='OrbePC',
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
    icon=['orbepc_icon.ico'],
)
